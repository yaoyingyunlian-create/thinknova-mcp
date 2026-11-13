"""Opt-in Windows/Codex/YouTube controlled pilot. No AI-generated shell commands."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
import platform
import plistlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from local_state import state_lock, LocalStateBusy
from automation_client import Client
from media_download import download, validate_media
import secure_state
from generation_quality import prepare_prompt

ROOT=Path(__file__).resolve().parent
STATE=(Path.home() / 'Library/Application Support' if platform.system()=='Darwin' else Path(os.environ.get('LOCALAPPDATA', str(Path.home())))) / 'ThinkNova' / 'automation'
CREDENTIALS=STATE/('credentials.keychain' if platform.system()=='Darwin' else 'credentials.dpapi')
YOUTUBE_TOKEN=STATE/('youtube.keychain' if platform.system()=='Darwin' else 'youtube.dpapi')


def atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data, ensure_ascii=False),encoding='utf-8');os.replace(temp,path)


def validate_plan(value: dict) -> dict:
    if not isinstance(value,dict) or set(value)!={'title','description','shots'}:raise RuntimeError('INVALID_CONTENT_PLAN')
    if not isinstance(value['title'],str) or not 1<=len(value['title'])<=100 or not isinstance(value['description'],str) or len(value['description'])>4000:raise RuntimeError('INVALID_CONTENT_PLAN')
    if not isinstance(value['shots'],list) or not 1<=len(value['shots'])<=4:raise RuntimeError('INVALID_CONTENT_PLAN')
    for shot in value['shots']:
        if not isinstance(shot,dict) or set(shot) not in ({'prompt'}, {'prompt', 'first_frame_asset_id'}) or not isinstance(shot['prompt'],str) or not 1<=len(shot['prompt'])<=3500:raise RuntimeError('INVALID_CONTENT_PLAN')
        first_frame = shot.get('first_frame_asset_id')
        if first_frame is not None and (not isinstance(first_frame, str) or not re.fullmatch(r'asset_[A-Za-z0-9]+', first_frame) or len(first_frame) > 64):
            raise RuntimeError('INVALID_FIRST_FRAME_ASSET')
    return value


def shot_tool(shot, rules):
    first_frame = shot.get('first_frame_asset_id')
    authorized = set(rules.get('authorized_asset_ids') or [])
    style = rules.get('style_profile') or {}
    positive = style.get('positive_references') or []
    negative = {reference.get('asset_id') for reference in (style.get('negative_references') or [])}
    candidates = authorized or {reference.get('asset_id') for reference in positive}
    if first_frame:
        if first_frame not in candidates or first_frame in negative:
            raise RuntimeError('FIRST_FRAME_NOT_AUTHORIZED')
        return 'animate_image', {'reference_asset_ids': [first_frame]}
    if 'first_frame_asset_id' in shot and (authorized or positive):
        raise RuntimeError('REFERENCE_FIRST_FRAME_REQUIRED')
    return 'generate_video', {}


def run_command(args: list[str], cwd: Path, timeout=300, stdout=None):
    result=subprocess.run(args, cwd=cwd, capture_output=stdout is None, stdout=stdout, stderr=subprocess.PIPE if stdout else None, timeout=timeout, text=True, encoding='utf-8', errors='replace')
    if result.returncode:raise RuntimeError('LOCAL_COMMAND_FAILED')
    return result


def make_plan(directory: Path, rules: dict) -> dict:
    codex=shutil.which('codex')
    if not codex:raise RuntimeError('CODEX_UNAVAILABLE')
    output=directory/'plan.json'
    # Only a constrained content plan is consumed. No model-provided commands or paths.
    prompt='Create one YouTube video content plan matching these account rules. For ordinary human characters require anatomically natural hands, five fingers per fully visible hand, no extra or fused digits/limbs, and simple stable gestures. This does not certify generated anatomy. If the spoken script contains 小程序, add the pronunciation instruction 小程序 = xiǎo chéng xù; keep displayed text unchanged, do not speak the pinyin. Require listening and visual review for suspected defects before release. Return only the requested JSON. No commands, tool calls, purchases or publication. Do not claim unsupported facts. Rules: '+json.dumps(rules,ensure_ascii=False)
    prompt += (' For each shot set first_frame_asset_id to the exact ThinkNova asset ID only when the account rules explicitly identify '
               'that image as the intended starting frame for the shot. Authorization alone is insufficient. '
               'Never substitute a character sheet, style sample, negative reference or external URL. Use null if no such frame is designated.')
    command=[codex,'exec','--ignore-user-config','--ephemeral','--sandbox','read-only','--skip-git-repo-check','-C',str(directory),'--output-schema',str(ROOT/'automation_plan.schema.json'),'--output-last-message',str(output),'-']
    # Do not inherit device/platform tokens through subprocess environment.
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN','SECRET','PASSWORD','YT_','THINKNOVA_'))}
    started=time.monotonic()
    result=subprocess.run(command,input=prompt,cwd=directory,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
    atomic(directory/'client_usage.json',{'client':'codex','elapsed_seconds':round(time.monotonic()-started,3),'model_tokens':'unknown','tool_calls':'unknown','note':'No client quota or subscription consumption is inferred.'})
    if result.returncode or not output.is_file():raise RuntimeError('CODEX_PLAN_FAILED')
    plan = validate_plan(json.loads(output.read_text(encoding='utf-8')))
    for shot in plan['shots']:
        shot.setdefault('first_frame_asset_id', None)
        prepared = prepare_prompt(shot['prompt'], 'video')
        if len(prepared.encode('utf-8')) > 3500: raise RuntimeError('QUALITY_PROMPT_TOO_LONG')
        shot['prompt'] = prepared
    return validate_plan(plan)


def compose(directory: Path, count: int, progress=lambda: None) -> Path:
    progress()
    output=directory/'final.mp4'
    if output.exists(): return output
    job=directory/'assemble.json'
    atomic(job, {'out':'final.mp4','clips':[{'file':f'shot{i}.mp4','fit':'contain'} for i in range(count)]})
    run_command([sys.executable,str(ROOT/'render/assemble.py'),str(job),'--json'],directory)
    progress()
    return output


def review_spoken_terms(path, prompt):
    if '小程序' not in prompt: return
    from render.speech_review import transcribe, evaluate
    try:
        review = evaluate(transcribe(path), ['小程序'])
        review['source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        atomic(path.with_suffix('.speech-review.json'), review)
    except Exception:
        raise RuntimeError('SPEECH_REVIEW_UNAVAILABLE') from None
    if review['missing_terms']: raise RuntimeError('SPEECH_CONTENT_MISMATCH')
    # ASR agreement is evidence only, never a pronunciation certificate.


def quoted_generation_args(client, tool, args, balance):
    # Quotes always use a read-only tool. Old/mixed deployments can omit the quote, but cannot create paid work.
    if balance.get('quote_mode_supported') is not True:raise RuntimeError('MCP_QUOTE_NOT_SUPPORTED')
    response=client.tool('get_balance',{'quote_request':{'tool':tool,'arguments':args}})
    quote=response.get('generation_quote') or {}
    credits=quote.get('estimated_credits')
    if quote.get('quote_only') is not True or quote.get('creates_task') is not False or quote.get('reserves_credits') is not False or type(credits) is not int or credits<0:
        raise RuntimeError('MCP_QUOTE_INVALID_RESPONSE')
    return {**args,'max_credits':credits}


def execute(client: Client, claim: dict, day_plan=None, budget=None):
    run_no=claim['run_no'];grant=claim['grant']
    if not re.fullmatch(r'run_[a-f0-9]{24}',run_no):raise RuntimeError('INVALID_RUN_ID')
    directory=STATE/'runs'/run_no;directory.mkdir(parents=True,exist_ok=True)
    state_path=directory/'state.json';steps=dict(claim.get('steps') or {})
    if state_path.exists():steps.update(json.loads(state_path.read_text(encoding='utf-8')))
    def checkpoint(status='running',error=None):
        atomic(state_path,steps);client.receipt(run_no,steps,status,error)
    try:
        preflight = connected_report() if day_plan is None else connected_report(require_codex=False)
        if not preflight['automation_ready']:
            raise RuntimeError('AUTOMATION_PREFLIGHT_INCOMPLETE')
        project = grant.get('project_key')
        rules = client.tool('get_content_rules', {'project_key': project}) if project else client.tool('get_content_rules')
        if rules['version']!=grant['rules_version'] or rules.get('needs_onboarding'):raise RuntimeError('RULES_CHANGED')
        balance=client.tool('get_balance')
        if not balance.get('generation_available') or balance.get('available_credits',0)<=0:raise RuntimeError('CREDITS_OR_PLAN_REQUIRED')
        if balance.get('quote_mode_supported') is not True:raise RuntimeError('MCP_QUOTE_NOT_SUPPORTED')
        if day_plan is not None:
            return execute_store_day(client, claim, day_plan, budget, rules, balance, directory, steps, checkpoint)
        plan_path=directory/'content.json'
        steps['stage']='planning';checkpoint()
        if plan_path.exists():plan=validate_plan(json.loads(plan_path.read_text(encoding='utf-8')))
        else:plan=make_plan(directory,rules['effective_rules']);atomic(plan_path,plan)
        routes = [shot_tool(shot, rules['effective_rules']) for shot in plan['shots']]
        steps['stage']='generation'
        if any('小程序' in shot['prompt'] for shot in plan['shots']):
            try:
                from render.speech_review import ensure_runtime
                ensure_runtime()
            except Exception:
                raise RuntimeError('SPEECH_REVIEW_UNAVAILABLE') from None
        for index,shot in enumerate(plan['shots']):
            key=f'task_{index}'
            if key not in steps:
                checkpoint()
                tool, reference_args = routes[index]
                arguments={**reference_args,'prompt':shot['prompt'],'client_request_id':f'{run_no}:shot:{index}','automation_run_id':run_no}
                quote_key=f'quote_credits_{index}'
                if quote_key in steps:
                    arguments['max_credits']=int(steps[quote_key])
                else:
                    arguments=quoted_generation_args(client,tool,arguments,balance)
                    steps[quote_key]=str(arguments['max_credits']);checkpoint()
                created=client.tool(tool,arguments)
                steps[key]=created['task_id'];checkpoint()
            deadline=time.monotonic()+900
            while True:
                task=client.tool('get_task',{'task_id':steps[key]})
                if task['status']=='succeeded':break
                if task['status'] in ('failed','canceled','cancelled'):raise RuntimeError('GENERATION_TERMINAL_FAILURE')
                if time.monotonic()>deadline:raise RuntimeError('GENERATION_STILL_RUNNING')
                checkpoint();time.sleep(20)
            path=directory/f'shot{index}.mp4'
            cached = path.is_file()
            if cached:
                try:
                    validate_media(path)
                except RuntimeError:
                    cached = False
            if not cached:
                result=client.tool('get_result',{'task_id':steps[key]})
                assets=[a for a in result.get('assets',[]) if a.get('type')=='video']
                if not assets:raise RuntimeError('VIDEO_DELIVERY_MISSING')
                download(assets[0]['download_url'], path, task_id=steps[key])
            steps['stage']='speech_review';checkpoint()
            review_spoken_terms(path, shot['prompt'])
        steps['stage']='render';checkpoint()
        output=compose(directory,len(plan['shots']),checkpoint)
        # The publisher persists an upload-attempt marker before calling YouTube.
        # If the outcome is unknown, a later run cannot blindly re-upload.
        checkpoint()
        steps['stage']='publication';checkpoint()
        job={'video':str(output),'title':plan['title'],'description':plan['description'],'privacy':'public','aigc':True,'expected_channel_id':grant['channel_id'],'automation_run_id':run_no,'automation_steps':steps}
        job_path=directory/'job.json';atomic(job_path,job)
        checkpoint() # live authorization/lease check immediately before starting publication
        os.environ['THINKNOVA_RUN_LEASE']=client.lease
        try:run_command([sys.executable,str(ROOT/'publish/youtube/upload.py'),str(job_path),'--execute'],directory,timeout=300)
        finally:os.environ.pop('THINKNOVA_RUN_LEASE',None)
        receipt=json.loads(Path(str(job_path)+'.receipt.json').read_text(encoding='utf-8'))
        if receipt.get('state')!='verified':raise RuntimeError('PUBLICATION_UNVERIFIED')
        steps['youtube_video_id']=receipt['video_id'];steps['published_hash']=hashlib.sha256(output.read_bytes()).hexdigest();steps['stage']='complete';checkpoint('succeeded')
        try:client.post('/mcp/device/heartbeat',{'state':'normal','platform':'youtube','stage':'publication','last_run_state':'succeeded'},execution=False)
        except Exception:pass
    except Exception as exc:
        code=str(exc) if re.fullmatch('[A-Z0-9_]{1,64}',str(exc)) else 'LOCAL_RUN_FAILED'
        receipt_path=directory/'job.json.receipt.json'
        if receipt_path.exists():
            receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
            if isinstance(receipt.get('video_id'),str) and re.fullmatch('[A-Za-z0-9_-]{11}',receipt['video_id']):steps['youtube_video_id']=receipt['video_id']
        try:client.post('/mcp/device/heartbeat',{'state':'failed','platform':'youtube','stage':steps.get('stage','unknown'),'error_code':code},execution=False)
        except Exception:pass
        checkpoint('waiting_user',code)
        raise RuntimeError(code) from None


def execute_store_day(client, claim, plan, budget, rules, balance, directory, steps, checkpoint):
    from store_film import generation_arguments

    grant = claim['grant']
    if (plan['rules_version'] != rules['version'] or plan['date'] != claim.get('usage_date')
            or plan.get('project_key') != grant.get('project_key')):
        raise RuntimeError('DAY_PLAN_STALE')
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    if steps.get('day_plan_sha256') not in (None, digest):
        raise RuntimeError('DAY_PLAN_CHANGED')
    authorized = set(rules['effective_rules'].get('authorized_asset_ids') or [])
    shop = rules['effective_rules'].get('shop_profile') or {}
    shop_assets = shop.get('location_assets') or {}
    if shop.get('name') != plan['shop_name'] or shop.get('featured_service') != plan['featured_service']:
        raise RuntimeError('DAY_PLAN_SHOP_PROFILE_MISMATCH')
    editorial_row = None
    copy_policies = {}
    if grant.get('project_key'):
        from store_editorial import validate_plan_copy, validate_rotation
        if set(plan['platforms']) != {'youtube'}:
            raise RuntimeError('DAY_PLAN_PLATFORM_NOT_AUTHORIZED')
        if plan['platforms']['youtube'].get('expected_channel_id') != grant['channel_id']:
            raise RuntimeError('YOUTUBE_CHANNEL_MISMATCH')
        rows = plan.get('week_rows')
        if not isinstance(rows, list):
            raise RuntimeError('DAY_PLAN_WEEK_REQUIRED')
        history_path = STATE / f"topics-{grant['channel_id']}-{grant['project_key']}.json"
        history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.is_file() else []
        validate_rotation(rows, history, shop.get('editorial') or {})
        editorial_row = next((row for row in rows if row['date'] == plan['date']), None)
        if not editorial_row or editorial_row['opening'] != plan['opening']:
            raise RuntimeError('DAY_PLAN_TOPIC_MISMATCH')
        for platform, entry in (rules.get('platform_rules') or {}).items():
            terms = (entry.get('hard_constraints') or {}).get('copy_forbidden_terms')
            if terms:
                copy_policies[platform] = {'forbidden_terms': json.loads(terms)}
        validate_plan_copy(plan, copy_policies)
    run_no = claim['run_no']
    if any(key.startswith('task_') for key in steps) and not steps.get('day_plan_sha256'):
        raise RuntimeError('DAY_PLAN_RUN_ALREADY_USED')
    steps['day_plan_sha256'] = digest
    requests = []
    for index, segment in enumerate(plan['segments']):
        args = generation_arguments(segment, shop_assets, authorized)
        args.update(client_request_id=f'{run_no}:store:{index}', automation_run_id=run_no)
        if grant.get('project_key'):
            args['project_key'] = grant['project_key']
        price_key = f'quote_credits_{index}'
        if f'task_{index}' in steps and price_key in steps:
            args['max_credits'] = int(steps[price_key])
        else:
            args = quoted_generation_args(client, 'animate_image', args, balance)
        requests.append(args)
    total = sum(args['max_credits'] for args in requests)
    if total > min(budget, int(grant['daily_budget'])):
        raise RuntimeError('DAY_PLAN_OVER_BUDGET')
    new_total = sum(args['max_credits'] for index, args in enumerate(requests) if f'task_{index}' not in steps)
    if new_total > int(balance.get('available_credits', 0)):
        raise RuntimeError('DAY_PLAN_INSUFFICIENT_CREDITS')
    steps['stage'] = 'generation'
    checkpoint()
    clips = []
    for index, (segment, args) in enumerate(zip(plan['segments'], requests)):
        key = f'task_{index}'
        if key not in steps:
            steps[f'quote_credits_{index}'] = str(args['max_credits'])
            checkpoint()
            steps[key] = client.tool('animate_image', args)['task_id']
            checkpoint()
        deadline = time.monotonic() + 900
        while True:
            task = client.tool('get_task', {'task_id': steps[key]})
            if task['status'] == 'succeeded':
                break
            if task['status'] in ('failed', 'canceled', 'cancelled'):
                raise RuntimeError('GENERATION_TERMINAL_FAILURE')
            if time.monotonic() >= deadline:
                checkpoint()
                return {'status': 'running', 'stage': 'generation', 'run_no': run_no}
            checkpoint()
            time.sleep(20)
        path = directory / f'shot{index}.mp4'
        if path.is_file():
            validate_media(path)
        else:
            result = client.tool('get_result', {'task_id': steps[key]})
            assets = [asset for asset in result.get('assets', []) if asset.get('type') == 'video']
            if not assets:
                raise RuntimeError('VIDEO_DELIVERY_MISSING')
            download(assets[0]['download_url'], path, task_id=steps[key])
        clips.append({'file': path.name, 'fit': 'cover', **{
            key: segment[key] for key in ('beats', 'subs', 'subs2') if key in segment}})
    steps['stage'] = 'render'
    checkpoint()
    output = directory / 'final.mp4'
    job_path = directory / 'assemble.json'
    job = {'out': output.name, 'film_profile': 'store_v2', 'film_type': plan['film_type'],
           'shop_name': plan['shop_name'], 'featured_service': plan['featured_service'], 'clips': clips}
    if plan.get('speech_language'):
        job['speech_language'] = plan['speech_language']
    if set(plan['platforms']) == {'xiaohongshu'}:
        job['platform'] = 'xiaohongshu'
    else:
        job['end_card'] = plan['end_card']
    atomic(job_path, job)
    if not output.exists():
        result = subprocess.run([sys.executable, str(ROOT / 'render/assemble.py'), str(job_path), '--json'],
                                cwd=directory, capture_output=True, encoding='utf-8', errors='replace', timeout=900)
        if result.returncode:
            report = json.loads(result.stdout)
            atomic(directory / 'film-check.json', report)
            raise RuntimeError('FILM_CHECK_FAILED')
    from publish.dispatch import film_review
    film_review(job_path, {'job': {'film': True}, 'artifacts': [
        {'role': 'video', 'file': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}],
        'platform': 'youtube', 'manifest_sha256': ''})
    publish_job = directory / 'publish.json'
    publish_payload = {'video': str(output), 'film': True, 'platforms': plan['platforms']}
    if editorial_row is not None:
        publish_payload.update(marketing_standard='store_v2', copy_policies=copy_policies)
        history = [row for row in history if row['date'] != plan['date']]
        atomic(history_path, sorted([*history, editorial_row], key=lambda row: row['date'])[-120:])
    atomic(publish_job, publish_payload)
    summary = {'status': 'awaiting_review', 'output': str(output), 'publish_job': str(publish_job),
               'run_no': run_no, 'quoted_credits': total}
    atomic(directory / 'review-ready.json', summary)
    if grant.get('auto_publish'):
        steps['stage'] = 'ready_to_publish'
        steps['publish_job_hash'] = hashlib.sha256(publish_job.read_bytes()).hexdigest()
        steps['film_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
        checkpoint('pending')
        return {**summary, 'status': 'ready_to_publish'}
    steps['stage'] = 'review'
    checkpoint('waiting_user')
    return summary


def authorization():
    if not CREDENTIALS.is_file():
        return {'status': 'unconfigured'}
    client = Client(secure_state.load(CREDENTIALS))
    config, _ = client.post('/mcp/device/configuration', {})
    data = config.get('data', {})
    grant = data.get('grant') or data
    if not grant:
        return {'status': 'unconfigured'}
    fields = ('grant_no', 'channel_id', 'rules_version', 'daily_budget', 'publish_time',
              'timezone', 'expires_at', 'project_key', 'weekly_budget', 'production_time')
    return {'status': 'available', 'platform': 'youtube',
            **{key: grant[key] for key in fields if key in grant}}


def preflight_plan_copy(client, plan):
    from store_editorial import validate_plan_copy
    project = plan.get('project_key')
    if not project:
        return
    rules = client.tool('get_content_rules', {'project_key': project})
    if rules.get('version') != plan['rules_version']:
        raise RuntimeError('DAY_PLAN_STALE')
    policies = {}
    for platform, entry in (rules.get('platform_rules') or {}).items():
        terms = (entry.get('hard_constraints') or {}).get('copy_forbidden_terms')
        if terms:
            policies[platform] = {'forbidden_terms': json.loads(terms)}
    validate_plan_copy(plan, policies)
    for row in plan.get('week_rows', ()):
        validate_plan_copy(row, policies, plan['platforms'])


def run_day(path, budget):
    from store_film import validate_day_plan

    plan = validate_day_plan(json.loads(path.read_text(encoding='utf-8-sig')))
    if budget < 0:
        raise RuntimeError('DAY_PLAN_BUDGET_INVALID')
    with state_lock(STATE / 'runner'):
        if (STATE / 'paused.json').exists():
            raise RuntimeError('AUTOMATION_PAUSED')
        client = Client(secure_state.load(CREDENTIALS))
        preflight_plan_copy(client, plan)
        claim = client.claim('produce')
        if not claim.get('due'):
            raise RuntimeError('DAY_PLAN_RUN_NOT_DUE')
        return execute(client, claim, day_plan=plan, budget=budget)


def scheduled_store_day(phase):
    """Poll a due phase for the device; publishing consumes a verified handoff."""
    from store_film import validate_day_plan

    if not CREDENTIALS.is_file() or (STATE / 'paused.json').exists():
        return
    with state_lock(STATE / 'runner'):
        client = Client(secure_state.load(CREDENTIALS))
        payload, _ = client.post('/mcp/device/configuration', {})
        grant = payload.get('data') or {}
        if not grant.get('project_key'):
            return
        day = grant.get('local_date', '')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            raise RuntimeError('AUTOMATION_DATE_UNAVAILABLE')
        if phase == 'produce':
            if grant.get('local_time', '') < grant.get('production_time', '10:00'):
                return
            path = STATE / 'plans' / grant['project_key'] / f'{day}.json'
            if path.is_file():
                try:
                    raw_plan = json.loads(path.read_text(encoding='utf-8-sig'))
                except (OSError, ValueError):
                    atomic(STATE / 'daily-reminder.json', {'date': day, 'error_code': 'DAY_PLAN_FILE_INVALID'})
                    return
            else:
                try:
                    response, _ = client.post('/mcp/device/day-plan', {})
                except (RuntimeError, OSError) as exc:
                    code = str(exc) if re.fullmatch(r'[A-Z0-9_]{1,64}', str(exc)) else 'DAY_PLAN_CONNECTION_FAILED'
                    atomic(STATE / 'daily-reminder.json', {'date': day, 'error_code': code})
                    return
                result = response.get('data') or {}
                status = result.get('status')
                if status != 'ready':
                    if status not in ('processing', 'not_due'):
                        atomic(STATE / 'daily-reminder.json', {
                            'date': day, 'error_code': result.get('error_code') or 'DAY_PLAN_INPUT_REQUIRED',
                            'missing_fields': result.get('missing_fields', []),
                        })
                    return
                raw_plan = result.get('plan')
            try:
                plan = validate_day_plan(raw_plan)
            except ValueError as exc:
                atomic(STATE / 'daily-reminder.json', {'date': day, 'error_code': str(exc)})
                return
            if (plan['date'] != day or plan['rules_version'] != grant['rules_version']
                    or plan.get('project_key') != grant['project_key']):
                atomic(STATE / 'daily-reminder.json', {'date': day, 'error_code': 'DAY_PLAN_SCOPE_CHANGED'})
                return
            try:
                preflight_plan_copy(client, plan)
            except (ValueError, RuntimeError) as exc:
                atomic(STATE / 'daily-reminder.json', {'date': day, 'error_code': str(exc)})
                return
            claim = client.claim('produce')
            if claim.get('due'):
                try:
                    execute(client, claim, day_plan=plan, budget=int(grant['daily_budget']))
                except RuntimeError as exc:
                    atomic(STATE / 'daily-reminder.json', {'date': day, 'error_code': str(exc)})
                    raise
        elif grant.get('auto_publish'):
            claim = client.claim('publish')
            if claim.get('due'):
                publish_store_day(client, claim)


def publish_store_day(client, claim):
    from publish.dispatch import dispatch

    run_no = claim['run_no']
    if not re.fullmatch(r'run_[a-f0-9]{24}', run_no):
        raise RuntimeError('INVALID_RUN_ID')
    directory = STATE / 'runs' / run_no
    grant, steps = claim['grant'], dict(claim['steps'])
    job_path = directory / 'publish.json'
    frozen = directory / 'youtube-authorized.json'
    receipt_path = Path(str(frozen) + '.receipt.json')
    try:
        if not grant.get('auto_publish') or not grant.get('project_key'):
            raise RuntimeError('AUTOMATION_PUBLICATION_NOT_AUTHORIZED')
        if hashlib.sha256(job_path.read_bytes()).hexdigest() != steps.get('publish_job_hash'):
            raise RuntimeError('PUBLICATION_JOB_CHANGED')
        if steps.get('publication_started') != 'yes':
            os.environ['YT_TOKEN'] = str(YOUTUBE_TOKEN)
            value = dispatch(job_path, 'youtube')
            video = next(item for item in value['artifacts'] if item['role'] == 'video')
            if video['sha256'] != steps.get('film_sha256'):
                raise RuntimeError('PUBLICATION_VIDEO_CHANGED')
            if value['target_account'] != grant['channel_id']:
                raise RuntimeError('YOUTUBE_CHANNEL_MISMATCH')
            steps['publication_started'] = 'yes'
            steps['stage'] = 'publication'
            atomic(frozen, {**value['job'], 'privacy': 'public', 'schedule': None,
                            'aigc': True, 'automation_run_id': run_no, 'automation_steps': steps})
            client.receipt(run_no, steps)
            os.environ['THINKNOVA_RUN_LEASE'] = client.lease
            try:
                run_command([sys.executable, str(ROOT / 'publish/youtube/upload.py'), str(frozen), '--execute'],
                            directory, timeout=300)
            finally:
                os.environ.pop('THINKNOVA_RUN_LEASE', None)
        if not receipt_path.is_file():
            raise RuntimeError('PUBLICATION_OUTCOME_UNKNOWN')
        evidence = json.loads(receipt_path.read_text(encoding='utf-8'))
        video_id = evidence.get('video_id', '')
        if evidence.get('state') != 'verified' or evidence.get('channel_id') != grant['channel_id'] or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise RuntimeError('PUBLICATION_OUTCOME_UNKNOWN')
        steps.update(stage='complete', youtube_video_id=video_id)
        client.receipt(run_no, steps, 'succeeded')
        published = {'date': claim['usage_date'], 'status': 'published',
                     'video_url': f'https://youtube.com/shorts/{video_id}'}
    except Exception as exc:
        code = str(exc) if re.fullmatch(r'[A-Z0-9_]{1,64}', str(exc)) else 'PUBLICATION_FAILED'
        atomic(STATE / 'daily-reminder.json', {'date': claim['usage_date'], 'error_code': code})
        client.receipt(run_no, steps, 'waiting_user', code)
        raise RuntimeError(code) from exc


    try:
        from analytics import register
        register(argparse.Namespace(platform='youtube', content_id=video_id, content_url=None,
                                    published_at=datetime.now(timezone.utc).isoformat(), controlled=True))
    except (OSError, RuntimeError, ValueError):
        published['analytics_error'] = 'ANALYTICS_REGISTRATION_FAILED'
    atomic(STATE / 'daily-reminder.json', published)


def daily_schedule_status():
    marker = STATE / 'schedule-install.json'
    installed = 0
    system = platform.system()
    if system not in ('Windows', 'Darwin'):
        return 'unsupported'
    for phase in ('produce', 'publish'):
        command = (['schtasks', '/Query', '/TN', f'ThinkNova-Store-{phase}'] if system == 'Windows'
                   else ['launchctl', 'print', f'gui/{os.getuid()}/top.thinknova.store-{phase}'])
        try:
            installed += subprocess.run(command, capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return 'unknown'
    if not CREDENTIALS.is_file() or (STATE / 'paused.json').exists():
        return 'awaiting_authorization'
    if installed == 2:
        return 'ready'
    if installed:
        return 'partial'
    if marker.is_file():
        return 'failed'
    return 'not_installed'


def schedule_error(exc):
    import locale
    raw = exc.stderr or exc.stdout or b''
    for encoding in dict.fromkeys(['utf-8', locale.getpreferredencoding(False), 'oem' if os.name == 'nt' else 'utf-8']):
        try:
            details = raw.decode(encoding) if isinstance(raw, bytes) else raw
            break
        except (UnicodeError, LookupError):
            details = raw.decode('utf-8', errors='replace')
    details = re.sub(r'(?i)https?://\S+|\b[a-f0-9]{64}\b|Bearer\s+\S+', '[redacted]', details)
    return f'SCHEDULE_INSTALL_FAILED ({exc.returncode}): {details.strip()[:600]}'


def install_daily_schedules():
    if (STATE / 'paused.json').exists():
        raise RuntimeError('AUTOMATION_PAUSED')
    grant = authorization()
    if grant.get('status') != 'available' or not grant.get('project_key'):
        raise RuntimeError('AUTOMATION_PROJECT_AUTHORIZATION_REQUIRED')
    if platform.system() not in ('Windows', 'Darwin'):
        raise RuntimeError('AUTOMATION_OS_UNSUPPORTED')
    with state_lock(STATE / 'schedule-install'):
        marker = STATE / 'schedule-install.json'
        try:
            _register_daily_schedules()
        except subprocess.CalledProcessError as exc:
            atomic(marker, {'status': 'failed'})
            raise RuntimeError(schedule_error(exc)) from None
        except OSError:
            atomic(marker, {'status': 'failed'})
            raise RuntimeError('SCHEDULE_INSTALL_OS_ERROR') from None
        marker.unlink(missing_ok=True)
    return {'status': 'ready'}


def _register_daily_schedules():
    for phase in ('produce', 'publish'):
        command = [sys.executable, str(ROOT / 'automation.py'), f'tick-{phase}']
        if platform.system() == 'Windows':
            subprocess.run(['schtasks', '/Create', '/F', '/TN', f'ThinkNova-Store-{phase}',
                            '/SC', 'MINUTE', '/MO', '5', '/IT', '/TR', subprocess.list2cmdline(command)],
                           check=True, capture_output=True)
        elif platform.system() == 'Darwin':
            label = f'top.thinknova.store-{phase}'
            path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
            path.parent.mkdir(parents=True, exist_ok=True)
            scope = f'gui/{os.getuid()}'
            if path.exists():
                subprocess.run(['launchctl', 'bootout', scope, str(path)], capture_output=True)
            path.write_bytes(plistlib.dumps({'Label': label, 'ProgramArguments': command,
                                            'StartInterval': 300, 'WorkingDirectory': str(ROOT),
                                            'LimitLoadToSessionType': 'Aqua',
                                            'EnvironmentVariables': {'PATH': os.environ.get('PATH', '/usr/bin:/bin:/opt/homebrew/bin')}}))
            path.chmod(0o600)
            subprocess.run(['launchctl', 'bootstrap', scope, str(path)], check=True, capture_output=True)



def tick():
    if platform.system() not in ('Windows','Darwin'):raise RuntimeError('AUTOMATION_OS_UNSUPPORTED')
    with state_lock(STATE/'runner'):
        if (STATE/'paused.json').exists(): return
        secrets=secure_state.load(CREDENTIALS);client=Client(secrets)
        os.environ['YT_TOKEN']=str(YOUTUBE_TOKEN)
        if not (YOUTUBE_TOKEN).is_file():raise RuntimeError('YOUTUBE_AUTH_REQUIRED')
        heartbeat=STATE/'heartbeat.json'
        last=json.loads(heartbeat.read_text(encoding='utf-8')) if heartbeat.exists() else {}
        if time.time()-last.get('time',0)>=900:
            full=time.time()-last.get('full_time',0)>=3600 or last.get('local_ready') is False
            result=connected_report(check_local=full)
            health_state=json.loads((STATE/'health.json').read_text(encoding='utf-8')) if (STATE/'health.json').exists() else {'state':'unknown'}
            if not result['automation_ready']:health_state={'state':'failed','error_code':'AUTOMATION_PREFLIGHT_INCOMPLETE'}
            elif health_state['state']=='unknown':health_state={'state':'normal'}
            client.post('/mcp/device/heartbeat',{**health_state,'full_check':full,'checks':result['checks'],**({'available_credits':result['available_credits']} if 'available_credits' in result else {})},execution=False)
            atomic(heartbeat,{'time':time.time(),'full_time':time.time() if full else last.get('full_time'),'local_ready':result.get('local_ready',last.get('local_ready'))})
            if not result['automation_ready']:raise RuntimeError('AUTOMATION_PREFLIGHT_INCOMPLETE')
        claim=client.claim()
        if claim.get('due'):
            execute(client,claim)
            atomic(STATE/'health.json',{'state':'normal'})


def connected_report(check_local: bool = True, require_codex: bool = True) -> dict:
    from health import report
    result=report() if check_local else {'schema_version':1,'checked_at':datetime.now(timezone.utc).isoformat(),'checks':[],'overall':'partial'}
    def status(name, state, remedy=''):
        for check in result['checks']:
            if check['name']==name:check.update(status=state,remedy=remedy);return
        result['checks'].append({'name':name,'status':state,'remedy':remedy})
    codex=shutil.which('codex')
    try:status('codex_login','pass' if codex and subprocess.run([codex,'login','status'],capture_output=True,timeout=15).returncode==0 else 'waiting_user','Sign in to Codex / 请登录 Codex')
    except Exception:status('codex_login','waiting_user','CODEX_LOGIN_REQUIRED')
    try:
        client=Client(secure_state.load(CREDENTIALS))
        config,_=client.post('/mcp/device/configuration',{})
        balance=client.tool('get_balance')
        result['available_credits']=int(balance.get('available_credits',0))
        status('server_quote','pass' if balance.get('quote_mode_supported') is True else 'waiting_user','Update ThinkNova API before enabling paid execution / 请先更新支持只读报价的 API')
        status('account','pass' if balance.get('generation_available') and balance.get('available_credits',0)>0 else 'waiting_user','Check plan and credits / 检查套餐和积分')
        project = (config.get('data') or {}).get('project_key')
        rules = client.tool('get_content_rules', {'project_key': project}) if project else client.tool('get_content_rules')
        status('rules','pass' if not rules.get('needs_onboarding') and rules.get('version')==config['data']['rules_version'] else 'waiting_user','Confirm current account rules / 确认当前账户规则')
        os.environ['YT_TOKEN']=str(YOUTUBE_TOKEN)
        sys.path.insert(0,str(ROOT/'publish/youtube'))
        import yt_common
        try:status('platform_authorization','pass' if yt_common.my_channel(yt_common.youtube())['id']==config['data']['channel_id'] else 'fail','YOUTUBE_CHANNEL_MISMATCH')
        except (Exception,SystemExit):status('platform_authorization','waiting_user','Run automation.py youtube-auth / 完成平台授权')
    except (Exception,SystemExit):status('account','waiting_user','Pair an active device/grant; no secrets in chat / 配对有效设备与授权')
    required=[c for c in result['checks'] if c['name'] in ('python','files','virtual_environment','git','ffmpeg','ffprobe','libass','cjk_font','codex_login','account','rules','platform_authorization','server_quote')]
    if not require_codex:
        required = [check for check in required if check['name'] != 'codex_login']
    result['automation_ready']=all(c['status']=='pass' for c in required)
    result['overall']='partial' if result['automation_ready'] else 'blocked'
    return result


def doctor_command(as_json):
    from health import display
    print('Checking local dependencies, device authorization and YouTube / 正在检查本机依赖、设备授权和 YouTube', file=sys.stderr, flush=True)
    if as_json:
        try:
            probe = subprocess.run(
                [sys.executable, '-c',
                 'import automation, contextlib, json, sys; '
                 'redirect = contextlib.redirect_stdout(sys.stderr); '
                 'redirect.__enter__(); result = automation.connected_report(); '
                 'redirect.__exit__(None, None, None); print(json.dumps(result, ensure_ascii=True))'],
                cwd=ROOT, capture_output=True, timeout=150, encoding='utf-8', errors='replace',
            )
            if probe.returncode != 0:
                raise ValueError('AUTOMATION_DOCTOR_PROBE_FAILED')
            result = json.loads(probe.stdout)
        except subprocess.TimeoutExpired:
            result = {'schema_version': 1, 'automation_ready': False, 'overall': 'blocked',
                      'checks': [{'name': 'connected_probe', 'status': 'unknown',
                                  'remedy': 'AUTOMATION_DOCTOR_TIMEOUT: check local doctor, authorization and YouTube separately'}]}
        except (OSError, ValueError):
            result = {'schema_version': 1, 'automation_ready': False, 'overall': 'blocked',
                      'checks': [{'name': 'connected_probe', 'status': 'unknown', 'remedy': 'AUTOMATION_DOCTOR_PROBE_FAILED'}]}
    else:
        result = connected_report()
    display(result, as_json)
    return 0 if result['automation_ready'] else 2


def installation_preflight():
    if not connected_report()['automation_ready']:raise RuntimeError('AUTOMATION_PREFLIGHT_INCOMPLETE')


SCHEDULE_LABEL='top.thinknova.controlled-automation'

def schedule_path():
    return Path.home()/'Library/LaunchAgents'/(SCHEDULE_LABEL+'.plist')


def install_runner():
    command=[sys.executable,str(ROOT/'automation.py'),'tick']
    if platform.system()=='Windows':
        subprocess.run(['schtasks','/Create','/F','/TN','ThinkNova-Controlled-Automation','/SC','MINUTE','/MO','5','/IT','/TR',subprocess.list2cmdline(command)],check=True,capture_output=True)
    else:
        path=schedule_path();path.parent.mkdir(parents=True,exist_ok=True)
        value={'Label':SCHEDULE_LABEL,'ProgramArguments':command,'StartInterval':300,'RunAtLoad':True,
               'WorkingDirectory':str(ROOT),'LimitLoadToSessionType':'Aqua',
               'EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin')}}
        path.write_bytes(plistlib.dumps(value));path.chmod(0o600)
        subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True,capture_output=True)


def uninstall_daily_schedules():
    for phase in ('produce', 'publish'):
        if platform.system() == 'Windows':
            subprocess.run(['schtasks', '/Delete', '/F', '/TN', f'ThinkNova-Store-{phase}'], capture_output=True)
        elif platform.system() == 'Darwin':
            path = Path.home() / 'Library/LaunchAgents' / f'top.thinknova.store-{phase}.plist'
            if path.exists():
                subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(path)], capture_output=True)
                path.unlink()


def uninstall_runner():
    uninstall_daily_schedules()
    if platform.system()=='Windows':
        subprocess.run(['schtasks','/Delete','/F','/TN','ThinkNova-Controlled-Automation'],check=True,capture_output=True)
    else:
        path=schedule_path()
        if path.exists():
            subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}',str(path)],check=True,capture_output=True)
            path.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['pair','youtube-auth','doctor','tick','tick-produce','tick-publish','install-daily-schedules','install','uninstall','pause','revoke']);parser.add_argument('--user-confirmed',action='store_true');parser.add_argument('--json',action='store_true');args=parser.parse_args()
    try:
        if platform.system() not in ('Windows','Darwin'):raise RuntimeError('AUTOMATION_OS_UNSUPPORTED')
        if args.command=='pair':
            secrets={key:getpass.getpass(key+' (hidden): ') for key in ('telemetry_token','execution_token')}
            if not all(re.fullmatch('[a-f0-9]{64}',v) for v in secrets.values()):raise RuntimeError('INVALID_DEVICE_CREDENTIALS')
            secure_state.save(CREDENTIALS,secrets)
            if (STATE/'paused.json').exists(): (STATE/'paused.json').unlink()
            print('Credentials protected with OS storage (DPAPI/Keychain). 凭据已安全保存，不会启用计划任务。')
        elif args.command in ('pause','revoke'):
            status='paused' if args.command=='pause' else 'revoked'
            Client(secure_state.load(CREDENTIALS)).post('/mcp/device/stop',{'status':status})
            atomic(STATE/'paused.json',{'status':status,'time':time.time()})
            print('Server authorization stopped; existing paid tasks retain normal settlement/refund handling. 服务端已停止授权，已建任务按正常账务收尾。')
        elif args.command=='youtube-auth':
            os.environ['YT_TOKEN']=str(YOUTUBE_TOKEN)
            subprocess.run([sys.executable,str(ROOT/'publish/youtube/auth.py')],check=True)
        elif args.command=='doctor':
            return doctor_command(args.json)
        elif args.command=='tick':tick()
        elif args.command in ('tick-produce', 'tick-publish'):
            scheduled_store_day(args.command.removeprefix('tick-'))
        elif args.command == 'install-daily-schedules':
            install_daily_schedules()
        elif args.command=='install':
            if not args.user_confirmed:raise RuntimeError('SCHEDULE_CONFIRMATION_REQUIRED')
            installation_preflight()
            install_runner()
        else: uninstall_runner()

        return 0
    except Exception as exc:
        if isinstance(exc, LocalStateBusy):
            print('Another local runner is active; skipped. 已有运行实例，本次跳过。')
            return 0
        code=str(exc) if re.fullmatch('[A-Z0-9_]{1,64}',str(exc)) else 'AUTOMATION_ACTION_FAILED'
        if args.command=='tick':
            atomic(STATE/'health.json',{'state':'failed','error_code':code})
            try:Client(secure_state.load(CREDENTIALS)).post('/mcp/device/heartbeat',{'state':'failed','error_code':code},execution=False)
            except Exception:pass
        print(str(exc) if args.command == 'install-daily-schedules' and str(exc).startswith('SCHEDULE_INSTALL_FAILED (') else code, file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
