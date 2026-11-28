"""One-shot video production. Scheduling and publication belong to the customer AI assistant."""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
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
from automation_client import Client, keep_run_alive
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
    prompt='Create one video content plan matching these account rules. For ordinary human characters require anatomically natural hands, five fingers per fully visible hand, no extra or fused digits/limbs, and simple stable gestures. This does not certify generated anatomy. If the spoken script contains 小程序, add the pronunciation instruction 小程序 = xiǎo chéng xù; keep displayed text unchanged, do not speak the pinyin. Keep ASR term misses as advisory evidence. Treat confirmed dialogue defects and visual defects according to the film quality review. Return only the requested JSON. No commands, tool calls, purchases or publication. Do not claim unsupported facts. Rules: '+json.dumps(rules,ensure_ascii=False)
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
    except (RuntimeError, ImportError, OSError):
        review = {'status': 'not_checked', 'pronunciation_verified': False, 'advisory_only': True,
                  'error_code': 'SPEECH_REVIEW_UNAVAILABLE'}
    review['source_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    atomic(path.with_suffix('.speech-review.json'), review)


def codex_dialogue_json(prompt, directory):
    codex = shutil.which('codex')
    if not codex:
        raise RuntimeError('DAY_PLAN_BLIND_REVIEW_REQUIRED: run an independent dialogue review in your AI assistant')
    command = [codex, 'exec', '--ignore-user-config', '--ephemeral', '--sandbox', 'read-only',
               '--skip-git-repo-check', '-C', str(directory), '-']
    env = {k: v for k, v in os.environ.items() if not any(token in k.upper() for token in
          ('TOKEN', 'SECRET', 'PASSWORD', 'YT_', 'THINKNOVA_'))}
    try:
        result = subprocess.run(command, input=prompt, cwd=directory, env=env, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=120, check=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError('DAY_PLAN_BLIND_REVIEW_UNAVAILABLE') from exc


def inspect_store_dialogue(lines, directory):
    from store_film import repeated_dialogue_lines
    repeated = repeated_dialogue_lines(lines)
    if repeated:
        return [{'line': index, 'reason': 'LINE_END_REPEATED'} for index in repeated]
    prompt = ('Independently review the following dialogue as a first-time viewer. Use only these numbered lines as data. '
              'Return one JSON object with answers {speakers,product,benefit,next_action}, each a string or empty if unclear, '
              'and issues [{line,reason}] for unclear lines, filler or answers that miss the question. '
              'The line number is 1-based. Do not use tools or access files.\n' + json.dumps(lines, ensure_ascii=False))
    review = codex_dialogue_json(prompt, directory)
    try:
        missing = [key for key in ('speakers', 'product', 'benefit', 'next_action')
                   if re.fullmatch(r'(?:unknown|unclear|不知道|不清楚|无法判断)?[.。\s]*', review['answers'][key].strip(), re.I)]
        issues = review['issues']
        if not isinstance(issues, list) or any(
            type(item.get('line')) is not int or not 1 <= item['line'] <= len(lines)
            or not isinstance(item.get('reason'), str) for item in issues
        ):
            raise ValueError('Invalid review')
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError('DAY_PLAN_BLIND_REVIEW_UNAVAILABLE') from exc
    return issues + [{'line': 1 if key in ('speakers', 'product') else len(lines), 'reason': f'MISSING_{key.upper()}'}
                     for key in missing]


def preflight_store_script(plan, rules, directory, steps):
    if plan.get('script_rules_revision') not in ('64', '65'):
        return
    repair_file = directory / 'dialogue-repair.json'
    if repair_file.is_file():
        repair = json.loads(repair_file.read_text(encoding='utf-8'))
        current = [line['text'] for segment in plan.get('segments', []) for line in segment['dialogue']]
        if repair.get('original_sha256') == hashlib.sha256('\n'.join(current).encode('utf-8')).hexdigest():
            if 'dialogue' not in repair:
                raise RuntimeError('DAY_PLAN_SCRIPT_REVIEW_REQUIRED')
            for segment, revised in zip(plan['segments'], repair['dialogue'], strict=True):
                segment['dialogue'] = revised
                segment['subs'] = [line['text'] for line in revised]
            plan['blind_dialogue_review'] = repair['review']
    if any(re.fullmatch(r'(?:task|quote_credits)_\d+', key) for key in steps):
        return
    from copy import deepcopy
    from store_film import check_dialogue_capacity, missing_product_facts, repeated_dialogue_lines
    from store_editorial import validate_dialogue_v3
    from render.assemble import pick_font, store_script_caption

    shop = rules['effective_rules'].get('shop_profile') or {}
    missing = missing_product_facts(shop)
    if missing:
        atomic(directory / 'script-preflight.json', {'status': 'needs_input', 'missing_fields': missing,
                                                     'next_action': 'confirm_and_save_product_facts'})
        raise RuntimeError('DAY_PLAN_PRODUCT_FACTS_REQUIRED: ' + ', '.join(missing))

    def checked_lines(candidate):
        validate_dialogue_v3(candidate)
        for clip, segment in enumerate(candidate['segments'], 1):
            check_dialogue_capacity(segment, clip, candidate.get('speech_language'), revision=candidate.get('script_rules_revision'),
                                    require_fill=candidate.get('story_narrative') is not True)
            if re.search(r'\b(?:invent no|make no|demonstration only)\b', segment.get('prompt', ''), re.I):
                raise ValueError(f'FILM_PROMPT_UNSUPPORTED_RESTRICTION: segment {clip}')
            for index, line in enumerate(segment['dialogue'], 1):
                try:
                    store_script_caption(line['text'], pick_font(candidate, line['text']))
                except ValueError as exc:
                    raise ValueError(f'FILM_SUBTITLE_SPLIT_REQUIRED: clip {clip}, line {index}') from exc
        return [line['text'] for segment in candidate['segments'] for line in segment['dialogue']]

    review_file = directory / 'blind-dialogue-review.json'
    lines = checked_lines(plan)
    digest = hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()
    review = plan.get('blind_dialogue_review') or {}
    if review.get('sha256') == digest and review.get('issues') == [] and not repeated_dialogue_lines(lines):
        return
    if review_file.is_file():
        previous = json.loads(review_file.read_text(encoding='utf-8'))
        if previous.get('sha256') == digest and previous.get('issues') == []:
            return

    issues = inspect_store_dialogue(lines, directory)
    atomic(review_file, {'sha256': digest, 'issues': issues})
    if not issues:
        return
    atomic(repair_file, {'original_sha256': digest, 'issues': issues})
    prompt = ('Repair only the numbered dialogue lines listed in issues. Return JSON {lines:[all lines in original order]}. '
              'Keep every other line unchanged. Use only the confirmed facts and preserve each line’s role and original language. '
              'Keep the product, concrete benefit and next action understandable. Do not use tools.\n' + json.dumps(
                  {'lines': lines, 'issues': issues, 'product': shop.get('featured_service') or shop.get('products'),
                   'confirmed_facts': shop.get('confirmed_facts'), 'next_action': shop.get('viewer_action')}, ensure_ascii=False))
    candidate = deepcopy(plan)
    revised = codex_dialogue_json(prompt, directory)
    amended = revised.get('lines') if isinstance(revised, dict) else None
    changed = {item['line'] for item in issues}
    if not isinstance(amended, list) or len(amended) != len(lines) or any(
        not isinstance(line, str) or not line.strip() or (index not in changed and line != lines[index-1])
        for index, line in enumerate(amended, 1)
    ):
        raise RuntimeError('DAY_PLAN_SCRIPT_REVIEW_REQUIRED')
    revised_lines = iter(amended)
    for segment in candidate['segments']:
        for line in segment['dialogue']:
            line['text'] = next(revised_lines)
        segment['subs'] = [line['text'] for line in segment['dialogue']]
    try:
        checked_lines(candidate)
    except ValueError as exc:
        raise RuntimeError('DAY_PLAN_SCRIPT_REVIEW_REQUIRED: ' + str(exc)) from exc
    issues = inspect_store_dialogue(amended, directory)
    if issues:
        atomic(repair_file, {'original_sha256': digest, 'issues': issues})
        raise RuntimeError('DAY_PLAN_SCRIPT_REVIEW_REQUIRED: ' + ', '.join(str(item['line']) for item in issues))
    candidate['blind_dialogue_review'] = {'sha256': hashlib.sha256('\n'.join(amended).encode('utf-8')).hexdigest(), 'issues': []}
    atomic(repair_file, {'original_sha256': digest, 'dialogue': [segment['dialogue'] for segment in candidate['segments']],
                         'review': candidate['blind_dialogue_review']})
    plan.update(candidate)


def quoted_generation_args(client, tool, args, balance, require_duration=False, dialogue_check=None):
    from dialogue_encoding import validate_text
    args = {key: value for key, value in args.items() if key not in ('quote_fingerprint', 'max_credits')}
    if 'prompt' in args:
        validate_text(args['prompt'], args.get('dialogue_language'))
    # Quotes always use a read-only tool. Old/mixed deployments can omit the quote, but cannot create paid work.
    if balance.get('quote_mode_supported') is not True:raise RuntimeError('MCP_QUOTE_NOT_SUPPORTED')
    response=client.tool('get_balance',{'quote_request':{'tool':tool,'arguments':args}})
    quote=response.get('generation_quote') or {}
    credits=quote.get('estimated_credits')
    if quote.get('quote_only') is not True or quote.get('creates_task') is not False or quote.get('reserves_credits') is not False or type(credits) is not int or credits<0:
        raise RuntimeError('MCP_QUOTE_INVALID_RESPONSE')
    if tool in ('animate_image', 'generate_video') and 'ratio' in args:
        specification = quote.get('configured_video_specification') or quote.get('specification') or {}
        if not isinstance(specification, dict) or specification.get('ratio') != args['ratio']:
            raise RuntimeError('MCP_VIDEO_QUOTE_RATIO_MISMATCH')
        if dialogue_check:
            if type(specification.get('duration_seconds')) is not int:
                raise RuntimeError('MCP_VIDEO_QUOTE_DURATION_UNAVAILABLE')
            from store_film import check_dialogue_capacity
            check_dialogue_capacity(*dialogue_check[:3], revision=dialogue_check[3] if len(dialogue_check) > 3 else None,
                                    duration=specification['duration_seconds'], require_fill=args.get('story_narrative') is not True)
        if require_duration and specification.get('duration_seconds') != args['duration_seconds']:
            raise RuntimeError('MCP_VIDEO_QUOTE_DURATION_MISMATCH')
    if 'reference_roles' in args and quote.get('applied_reference_asset_ids') != args['reference_asset_ids']:
        raise RuntimeError('MCP_FILM_QUOTE_REFERENCE_MISMATCH')
    creation = {**args, 'max_credits': credits}
    if quote.get('quote_fingerprint'):
        creation['quote_fingerprint'] = quote['quote_fingerprint']
    return creation


@keep_run_alive
def execute(client: Client, claim: dict, day_plan=None, budget=None):
    run_no=claim['run_no'];grant=claim['grant']
    if not re.fullmatch(r'run_[a-f0-9]{24}',run_no):raise RuntimeError('INVALID_RUN_ID')
    directory=STATE/'runs'/run_no;directory.mkdir(parents=True,exist_ok=True)
    state_path=directory/'state.json';steps=dict(claim.get('steps') or {})
    if state_path.exists():steps.update(json.loads(state_path.read_text(encoding='utf-8')))
    def checkpoint(status='running',error=None):
        atomic(state_path,steps);client.receipt(run_no,steps,status,error)
    try:
        resuming_paid_plan = bool(day_plan and day_plan.get('segments')) and all(
            steps.get(f'task_{index}') and f'quote_credits_{index}' in steps
            for index in range(len(day_plan['segments']))
        )
        if not resuming_paid_plan:
            preflight = connected_report(require_codex=day_plan is None, require_publication=False)
            if not preflight['automation_ready']:
                raise RuntimeError('AUTOMATION_PREFLIGHT_INCOMPLETE')
        project = grant.get('project_key')
        rules = client.tool('get_content_rules', {'project_key': project}) if project else client.tool('get_content_rules')
        if rules['version'] != grant['rules_version']:
            raise RuntimeError('RULES_CHANGED')
        if rules.get('needs_onboarding') and not rules.get('defaults_revision'):
            raise RuntimeError('CREATION_PROFILE_INCOMPLETE')
        balance = {}
        if not resuming_paid_plan:
            balance = client.tool('get_balance')
            if not balance.get('generation_available') or balance.get('available_credits', 0) <= 0:
                raise RuntimeError('CREDITS_OR_PLAN_REQUIRED')
            if balance.get('quote_mode_supported') is not True:
                raise RuntimeError('MCP_QUOTE_NOT_SUPPORTED')
        if day_plan is not None:
            preflight_store_script(day_plan, rules, directory, steps)
            from store_film import check_dialogue_capacity
            for index, segment in enumerate(day_plan['segments']):
                if not steps.get(f'task_{index}') and f'quote_credits_{index}' not in steps:
                    check_dialogue_capacity(segment, index + 1, day_plan.get('speech_language'), revision=day_plan.get('script_rules_revision'),
                                            require_fill=day_plan.get('story_narrative') is not True)
            if (not resuming_paid_plan and day_plan.get('script_rules_revision') in ('59', '60', '64', '65')
                    and day_plan.get('asset_preparation')
                    and len(day_plan.get('asset_bindings') or {}) < len(day_plan['asset_preparation'])):
                from day_preparation import prepare_assets
                if any(not steps.get(f'task_{i}') for i in range(len(day_plan['segments']))):
                    from render.preflight import require_film_preflight
                    require_film_preflight(steps)
                day_plan = prepare_assets(client, claim, day_plan, directory, budget,
                                          quoted_generation_args, atomic)
                steps.update(claim.get('steps') or {})
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
        steps['stage']='review';checkpoint('waiting_user')
        review={'status':'awaiting_review','output':str(output),'run_no':run_no,
                'title':plan['title'],'description':plan['description'],
                'publication_executor':'customer_ai_assistant','browser':'ego_lite'}
        atomic(directory/'review-ready.json',review)
        return review
    except Exception as exc:
        code=str(exc) if re.fullmatch('[A-Z0-9_]{1,64}',str(exc)) else 'LOCAL_RUN_FAILED'
        if code in ('RECOVERY_TASK_PENDING', 'DAY_PLAN_ASSET_PENDING'):
            checkpoint('pending', code)
            return {'status':'running', 'stage':'recovery', 'run_no':run_no}
        receipt_path=directory/'job.json.receipt.json'
        if receipt_path.exists():
            receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
            if isinstance(receipt.get('video_id'),str) and re.fullmatch('[A-Za-z0-9_-]{11}',receipt['video_id']):steps['youtube_video_id']=receipt['video_id']
        try:client.post('/mcp/device/heartbeat',{'state':'failed','platform':'youtube','stage':steps.get('stage','unknown'),'error_code':code},execution=False)
        except Exception:pass
        checkpoint('waiting_user',code)
        raise RuntimeError(code) from None


def render_store_candidate(job_path):
    """Retry temporary checks once on the existing preview, without generating or rendering again."""
    directory = job_path.parent
    report_path = directory / 'film-check.json'
    from file_integrity import sha256
    from film_recovery import can_rebuild_caption_timeline

    job_bytes = job_path.read_bytes()
    job = json.loads(job_bytes)
    toolkit_version = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))['version']
    digest = hashlib.sha256(toolkit_version.encode('utf-8') + b'\0' + job_bytes)
    for clip in job['clips']:
        source = directory / clip['file']
        if source.is_file():
            digest.update(bytes.fromhex(sha256(source)))
    input_digest = digest.hexdigest()
    try:
        saved = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        saved = {}
    rebuild = False
    if isinstance(saved, dict) and saved.get('render_input_sha256') == input_digest and saved.get('render_failed'):
        if not can_rebuild_caption_timeline(saved) or saved.get('caption_rebuild_attempted'):
            return saved
        rebuild = True
        # Persist the retry before rendering so a killed process does not loop.
        atomic(report_path, {**saved, 'caption_rebuild_attempted': True})

    def render(args):
        try:
            result = subprocess.run([sys.executable, str(ROOT / 'render/assemble.py'), *args, '--json'],
                                    cwd=directory, env=dict(os.environ, THINKNOVA_REVIEW_PREVIEW='1',
                                                            THINKNOVA_RESUME_CAPTIONS='1' if rebuild else '0'),
                                    capture_output=True, encoding='utf-8', errors='replace', timeout=900)
            report = json.loads(result.stdout)
            if isinstance(report, dict):
                return result.returncode, report
        except subprocess.TimeoutExpired:
            return 2, {'diagnostics': [{'code': 'FILM_CHECK_TIMEOUT'}]}
        except (OSError, ValueError):
            pass
        return 2, {'diagnostics': [{'code': 'FILM_RENDER_REPORT_UNAVAILABLE'}]}

    code, report = render([str(job_path)])
    if rebuild:
        report['caption_rebuild_attempted'] = True
    if not code:
        atomic(report_path, {**report, 'render_input_sha256': input_digest})
        return report

    transient = {'SPEECH_CHECK_PENDING', 'FILM_PACE_UNAVAILABLE', 'FILM_CHECK_TIMEOUT', 'CONTACT_SHEET_FAILED'}
    codes = {item.get('code') for item in report.get('diagnostics', [])}
    receipt = report.get('pending_receipt')
    if isinstance(receipt, str) and codes and codes <= transient:
        path = Path(receipt).resolve()
        if path.name == 'preview.mp4.film.json' and path.parent.name.startswith('film_pending_') and path.parent.parent == directory.resolve() and path.is_file():
            report.update(render_input_sha256=input_digest, automatic_recheck='started', render_failed=True)
            atomic(report_path, report)
            code, checked = render(['--recheck', str(path)])
            if not code:
                atomic(report_path, {**checked, 'render_input_sha256': input_digest, 'automatic_recheck': 'passed'})
                return checked
            report.update(checked, automatic_recheck='failed')

    report.setdefault('next_action', 'recheck_after_local_fix' if codes and codes <= transient else 'fix_render_input_before_retry')
    report.update(render_input_sha256=input_digest, render_failed=True)
    atomic(report_path, report)
    return report


def reviewed_store_segment(client, args, segment, index, prior, plan, budget, directory, steps, checkpoint):
    from render.preflight import require_film_preflight

    key = f'task_{index}'
    last_task = steps.get(key)
    attempt = 1
    defect = None
    if last_task:
        task = client.tool('get_task', {'task_id': last_task})
        if task['status'] in ('failed', 'canceled', 'cancelled'):
            raise RuntimeError('GENERATION_TERMINAL_FAILURE')
        review = task.get('segment_review') or {}
        if task['status'] != 'succeeded' or review.get('status') == 'pending':
            return None, 'pending'
        if review.get('status') == 'pass':
            return review, 'pass'
        defect = review.get('code')
        if review.get('status') != 'fail' or defect not in (
            'FILM_VISUAL_DEFORMATION', 'FILM_VISUAL_IDENTITY_SWAP', 'FILM_VISUAL_RATIO_INVALID',
            'FILM_VISUAL_DIALOGUE_MISMATCH',
        ):
            return None, defect or 'FILM_REVIEW_UNAVAILABLE'
        attempt = int(review.get('attempt_number', 1)) + 1
        if attempt > 3:
            return None, 'FILM_VISUAL_RETAKES_EXHAUSTED'
    require_film_preflight(steps)
    argument_file = directory / f'.story-segment-{index}-{attempt}.json'
    if argument_file.is_file():
        request = json.loads(argument_file.read_text(encoding='utf-8'))
    else:
        request = dict(args)
        if prior and prior[0] == segment['shop_location']:
            tail = prior[1].get('tail_asset_id')
            if not tail:
                return None, 'FILM_TAIL_FRAME_UNAVAILABLE'
            request['reference_asset_ids'] = [tail, *request['reference_asset_ids'][1:]]
        if attempt > 1:
            request['client_request_id'] += f':retry:{attempt - 1}'
            request['retake_of_task_id'] = last_task
            if attempt == 3 and defect == steps.get(f'story_first_defect_{index}'):
                direction = {
                    'FILM_VISUAL_DEFORMATION': 'Use a stable waist-up shot showing hands naturally at rest; keep the actual action visible.',
                    'FILM_VISUAL_IDENTITY_SWAP': 'Use a single stable camera and keep both approved faces clearly visible; preserve costume and identity.',
                    'FILM_VISUAL_RATIO_INVALID': 'Frame at native 9:16 with no optical squeeze; use a centred, undistorted medium shot.',
                    'FILM_VISUAL_DIALOGUE_MISMATCH': 'Keep the action described for each spoken line visible in a simple medium shot.',
                }[defect]
                request['prompt'] += '\nChange camera and blocking for this replacement. ' + direction
        try:
            request = quoted_generation_args(client, 'animate_image', request, client.tool('get_balance'),
                                             require_duration=True)
        except RuntimeError as error:
            code = str(error).split(':', 1)[0]
            if code not in ('MCP_STORE_RETAKE_NOT_AUTHORIZED', 'MCP_STORE_RETAKE_INVALID',
                            'MCP_STORE_RETAKE_VISUAL_CHANGE_REQUIRED'):
                raise
            return None, code
        already_quoted = sum(int(value) for name, value in steps.items() if name.startswith('story_quoted_'))
        if already_quoted + request['max_credits'] + int(plan.get('preparation_credits', 0)) > budget:
            return None, 'DAY_PLAN_OVER_BUDGET'
        atomic(argument_file, request)
    steps[f'story_quoted_{index}_{attempt}'] = str(request['max_credits'])
    if attempt == 2:
        steps[f'story_first_defect_{index}'] = defect
    checkpoint()
    try:
        created = client.tool('animate_image', request)
    except RuntimeError as error:
        if str(error).split(':', 1)[0] not in ('MCP_STORE_RETAKE_NOT_AUTHORIZED', 'MCP_STORE_RETAKE_INVALID',
                                            'MCP_STORE_RETAKE_VISUAL_CHANGE_REQUIRED'):
            raise
        return None, str(error).split(':', 1)[0]
    steps[key] = created['task_id']
    checkpoint()
    return None, 'pending'


def execute_store_day(client, claim, plan, budget, rules, balance, directory, steps, checkpoint):
    from store_film import generation_arguments
    from store_editorial import scripted_segment

    grant = claim['grant']
    if (plan['rules_version'] != rules['version'] or plan['date'] != claim.get('usage_date')
            or plan.get('project_key') != grant.get('project_key')):
        raise RuntimeError('DAY_PLAN_STALE')
    identity_plan = {key:value for key,value in plan.items() if key not in ('preparation_credits','preparation_costs')}
    digest = hashlib.sha256(json.dumps(identity_plan, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    if steps.get('day_plan_sha256') not in (None, digest):
        raise RuntimeError('DAY_PLAN_CHANGED')
    authorized = set(rules['effective_rules'].get('authorized_asset_ids') or [])
    if plan.get('script_rules_revision') in ('59', '60', '64', '65'):
        authorized.update((plan.get('asset_bindings') or {}).values())
    shop = dict(rules['effective_rules'].get('shop_profile') or {})
    if plan.get('script_rules_revision') in ('59', '60', '64', '65'):
        shop['name'] = shop.get('name') or ''
        shop['featured_service'] = shop.get('featured_service') or shop.get('products') or ''
        shop['voice_identity'] = shop.get('voice_identity') or plan.get('script', {}).get('voice_identity', '')
    shop_assets = dict(shop.get('location_assets') or {})
    if plan.get('script_rules_revision') in ('59', '60', '64', '65'):
        for segment in plan['segments']:
            shop_assets.setdefault(segment.get('shop_location', 'generic'), []).append(segment['first_frame_asset_id'])
    if shop.get('name') != plan['shop_name'] or shop.get('featured_service') != plan['featured_service']:
        raise RuntimeError('DAY_PLAN_SHOP_PROFILE_MISMATCH')
    editorial_row = None
    copy_policies = {}
    if grant.get('project_key'):
        from store_editorial import dialogue_v21_lines, validate_plan_copy, validate_rotation
        rows = plan.get('week_rows')
        if not isinstance(rows, list):
            raise RuntimeError('DAY_PLAN_WEEK_REQUIRED')
        slot = plan.get('work_slot', 1)
        history_path = STATE / f"topics-{grant['channel_id']}-{grant['project_key']}.json"
        history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.is_file() else []
        history = [row for row in history if (row['date'], row.get('work_slot', 1)) != (plan['date'], slot)]
        if plan.get('schema_version') == 3:
            rows = [dict(row) for row in rows]
            selected = next((row for row in rows if row['date'] == plan['date']), None)
            if selected:
                selected.update(visual_batch=plan['visual_batch'], customer_identity=plan['customer_identity'])
                preceding = [row for row in history if row['date'] < plan['date'] and row.get('customer_identity')]
                previous = max(preceding, key=lambda row: (row['date'], row.get('work_slot', 1)), default={})
                if (previous.get('customer_identity') == plan['customer_identity']
                        or any(row['date'] == plan['date'] and row.get('customer_identity') == plan['customer_identity']
                               for row in history)):
                    if plan.get('script_rules_revision') not in ('59', '60', '64', '65'):
                        raise RuntimeError('FILM_CUSTOMER_REPEATED')
                    plan.setdefault('warnings', []).append('SCRIPT_CHARACTER_ROTATION_ADVICE_UNMET')
        editorial = plan.get('editorial_profile') if plan.get('script_rules_revision') in ('54', '59', '60', '64', '65') else shop.get('editorial')
        validate_rotation(rows, history, editorial or {}, plan.get('schema_version', 1),
                          plan.get('script_rules_revision'), plan.setdefault('warnings', []),
                          story_narrative=plan.get('story_narrative') is True)
        editorial_row = next((row for row in rows if row['date'] == plan['date']), None)
        if not editorial_row or editorial_row['opening'] != plan['opening']:
            raise RuntimeError('DAY_PLAN_TOPIC_MISMATCH')
        editorial_row['work_slot'] = slot
        if plan.get('dialogue_rules_revision') in ('2.1', '2.4'):
            day = date.fromisoformat(plan['date'])
            recent_lines = [line for row in history if 0 <= (day - date.fromisoformat(row['date'])).days <= 7
                            for line in row.get('dialogue_lines', [])]
            editorial_row['dialogue_lines'] = dialogue_v21_lines(plan, recent_lines)
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
    story = plan.get('script_rules_revision') == '65' and plan.get('story_narrative') is True
    for index, segment in enumerate(plan['segments']):
        if plan.get('dialogue_rules_revision') in ('2.1', '2.4') and plan.get('script_rules_revision') not in ('59', '60', '64', '65'):
            roles = ['first_frame', 'cast', 'product'] if segment.get('featured_product_visible', plan['film_purpose'] == 'product') else ['first_frame', 'customer', 'staff']
            segment = {**segment, 'reference_roles': roles,
                       'reference_boards': {**(shop.get('reference_boards') or {}), **(segment.get('reference_boards') or {})}}
        revision65 = plan.get('script_rules_revision') == '65'
        prepared_segment = segment if revision65 else scripted_segment(segment, plan.get("script"), shop)
        if plan.get('script_rules_revision') in ('64', '65'):
            voice = ('Use natural scene ambience only. No spoken lines or music.' if story and not segment['dialogue']
                     else 'Speak the approved dialogue exactly. Preserve its product names and confirmed facts.')
            prepared_segment = {**prepared_segment, 'prompt': prepared_segment['prompt'] + '\n' + voice}
        args = generation_arguments(prepared_segment, shop_assets, authorized)
        if plan.get('dialogue_rules_revision') == '2.4':
            args['film_rules_revision'] = '2.4'
        if plan.get('script_rules_revision') in ('59', '60', '64', '65'):
            args['dialogue_language'] = 'zh' if re.search(r'[\u3400-\u9fff]', ''.join(segment.get('subs', []))) else plan.get('speech_language', 'en')
        if plan.get('script_rules_revision') in ('64', '65') and (story or segment.get('dialogue')):
            args['dialogue'] = [{key: line[key] for key in ('speaker', 'text')} for line in segment['dialogue']]
        if story:
            args.update(story_narrative=True, visual_lines=[line['visual'] for line in segment['dialogue']])
            if 'story_plan' in plan:
                args['story_plan'] = plan['story_plan']
        if revision65:
            from film_recovery import film_run_id
            boards = segment.get('reference_boards') or {}
            args.update(film_run_id=film_run_id(directory / 'assemble.json'),
                        film_segment_count=len(plan['segments']), film_segment_number=index + 1)
            if len(plan['segments']) > 1:
                args['continuity_asset_id'] = boards.get('cast') or boards.get('staff')
                if not args['continuity_asset_id']:
                    raise ValueError('FILM_CONTINUITY_BOARD_REQUIRED')
            args['reference_asset_ids'] = args['reference_asset_ids'][:1]
            args.pop('reference_roles', None)
            args.pop('film_rules_revision', None)
        args.update(client_request_id=f'{run_no}:store:{index}', automation_run_id=run_no)
        if grant.get('project_key'):
            args['project_key'] = grant['project_key']
        price_key = f'quote_credits_{index}'
        if story:
            args['max_credits'] = 0  # A downstream quote must use the actual reviewed frame.
        elif f'task_{index}' in steps and price_key in steps:
            args['max_credits'] = int(steps[price_key])
        else:
            args = quoted_generation_args(client, 'animate_image', args, balance,
                                          require_duration=plan.get('film_type') == 'explainer',
                                          dialogue_check=None if not segment.get('dialogue') or price_key in steps or f'task_{index}' in steps else
                                          (segment, index + 1, plan.get('speech_language'), plan.get('script_rules_revision')))
        requests.append(args)
    total = sum(args['max_credits'] for args in requests)
    if total + int(plan.get('preparation_credits', 0)) > min(budget, int(grant['daily_budget'])):
        raise RuntimeError('DAY_PLAN_OVER_BUDGET')
    new_total = sum(args['max_credits'] for index, args in enumerate(requests) if f'task_{index}' not in steps)
    if new_total > int(balance.get('available_credits', 0)):
        raise RuntimeError('DAY_PLAN_INSUFFICIENT_CREDITS')
    if plan.get('film_type') == 'explainer' and new_total:
        if all(type(balance.get(k)) is int for k in ('daily_limit', 'daily_used_or_reserved')):
            if new_total > balance['daily_limit'] - balance['daily_used_or_reserved']:
                raise RuntimeError('DAY_PLAN_OVER_BUDGET')
        current, _ = client.post('/mcp/device/configuration', {})
        remaining = (current.get('data') or {}).get('remaining_credits')
        if type(remaining) is not int:
            raise RuntimeError('DAY_PLAN_BUDGET_UNAVAILABLE')
        if new_total > remaining:
            raise RuntimeError('DAY_PLAN_OVER_BUDGET')
    steps['stage'] = 'generation'
    checkpoint()
    clips, native_issues = [], []
    prior = None
    for index, (segment, args) in enumerate(zip(plan['segments'], requests)):
        key = f'task_{index}'
        if story:
            if native_issues:
                checkpoint('waiting_user', 'FILM_NATIVE_AUDIO_REVIEW_REQUIRED')
                return {'status': 'waiting_user', 'stage': 'native_dialogue', 'run_no': run_no,
                        'native_audio_issues': native_issues}
            review, status = reviewed_store_segment(client, args, segment, index, prior, plan,
                                                    min(budget, int(grant['daily_budget'])), directory, steps, checkpoint)
            if status != 'pass':
                if status != 'pending':
                    checkpoint('waiting_user', status)
                return {'status': 'running' if status == 'pending' else 'waiting_user', 'stage': 'visual_review',
                        'run_no': run_no, 'segment': index + 1, 'task_id': steps.get(key), 'reason_code': status}
            prior = (segment['shop_location'], review)
        if key not in steps:
            if native_issues:
                checkpoint('waiting_user', 'FILM_NATIVE_AUDIO_REVIEW_REQUIRED')
                return {'status': 'waiting_user', 'stage': 'native_dialogue', 'run_no': run_no,
                        'native_audio_issues': native_issues}
            from render.preflight import require_film_preflight
            require_film_preflight(steps)
            steps[f'quote_credits_{index}'] = str(args['max_credits'])
            checkpoint()
            created = client.tool('animate_image', args)
            steps[key] = created['task_id']
            applied = created.get('applied_reference_asset_ids')
            if isinstance(applied, list) and applied and all(
                    isinstance(ref, str) and re.fullmatch(r'asset_[A-Za-z0-9_-]{1,32}', ref) for ref in applied):
                steps[f'applied_refs_{index}'] = ':'.join(applied[:3])
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
        path = directory / (f'shot{index}-{steps[key]}.mp4' if story else f'shot{index}.mp4')
        if path.is_file():
            validate_media(path)
        else:
            result = client.tool('get_result', {'task_id': steps[key]})
            assets = [asset for asset in result.get('assets', []) if asset.get('type') == 'video']
            if not assets:
                raise RuntimeError('VIDEO_DELIVERY_MISSING')
            download(assets[0]['download_url'], path, task_id=steps[key])
        if (plan.get('quality_policy') or {}).get('version') == '58' and (
            f'recovery_task_{index}' in steps or path.with_suffix('.recovery-request.json').is_file()
        ):
            from clip_recovery import recover_clip
            budget_used = total + int(plan.get('preparation_credits', 0)) + sum(
                int(value) for key, value in steps.items() if key.startswith('recovery_cost_'))
            path, assessment = recover_clip(client, claim, plan, index, args, path, steps, checkpoint,
                                            quoted_generation_args, download, atomic, budget_used, budget_limit=budget)
            if assessment.get('warning'):
                plan.setdefault('warnings', []).append({'code':assessment['warning'], 'clip':index})
        selected_task = steps.get(f'recovery_task_{index}') if path.name.endswith('-recovery.mp4') else steps[key]
        clip = {'file': path.name, 'fit': 'cover', 'task_id': selected_task, **{
            key: segment[key] for key in ('beats', 'dialogue', 'subs', 'subs2') if key in segment}}
        if story:
            clip['segment_review'] = review
        from render.assemble import probe, tool
        from render.native_dialogue import inspect, script_lines
        source_seconds, _, has_audio = probe(tool('ffprobe'), str(path))
        dialogue = inspect(path, script_lines(clip), plan.get('speech_language'), tool('ffmpeg'), source_seconds,
                           has_audio, directory / '.native-dialogue', selected_task, resume=True)
        if (not story or script_lines(clip)) and dialogue['status'] in ('missing_audio', 'silent_audio', 'dialogue_mismatch'):
            native_issues.append({'clip': index + 1, 'task_no': selected_task, 'code': dialogue['code']})
        if plan.get('film_type') == 'explainer':
            clip['planned_seconds'] = segment['duration_seconds']
        clips.append(clip)
    steps['stage'] = 'render'
    checkpoint()
    output = directory / 'final.mp4'
    job_path = directory / 'assemble.json'
    from quality_policy import store_policy
    render_policy = store_policy(plan.get('quality_policy'))
    if render_policy.get('version') == 'legacy' and rules.get('quality_policy', {}).get('version') == 'native_dialogue_v1':
        render_policy = rules['quality_policy']
    job = {'out': output.name, 'film_profile': 'store_v2', 'film_type': plan['film_type'],
           'shop_name': plan['shop_name'], 'featured_service': plan['featured_service'], 'clips': clips,
           'script_rules_revision': plan.get('script_rules_revision'), 'quality_policy': render_policy}
    if plan.get('story_narrative') is True:
        job['story_narrative'] = True
        if 'story_plan' in plan:
            job['story_plan'] = plan['story_plan']
    if plan.get('speech_language'):
        job['speech_language'] = plan['speech_language']
    if plan['schema_version'] in (2, 3):
        job['short_dialogue_seconds'] = sum(segment['duration_seconds'] for segment in plan['segments'])
        job['closing_overlay'] = plan.get('closing_overlay') or [plan['shop_name'], plan['featured_service']]
        job['dialogue_segment_count'] = len(plan['segments'])
        job['film_schema_version'] = plan['schema_version']
        if plan.get('dialogue_rules_revision') == '2.4':
            job['film_rules_revision'] = '2.4'
    elif set(plan['platforms']) == {'xiaohongshu'}:
        job['platform'] = 'xiaohongshu'
    else:
        job['end_card'] = plan['end_card']
    atomic(job_path, job)
    inventory_file = directory / 'inventory-source.json'
    inventory = json.loads(inventory_file.read_text(encoding='utf-8')) if inventory_file.exists() else None
    if inventory:
        from film_inventory import copy_artifacts
        copy_artifacts(inventory['video'], output)
        plan['platforms'] = inventory['platforms']
    if not output.exists():
        report = render_store_candidate(job_path)
        if report.get('render_failed') or not output.is_file():
            from film_recovery import can_rebuild_caption_timeline
            if report.get('native_audio_issues'):
                checkpoint('waiting_user', 'FILM_NATIVE_AUDIO_REVIEW_REQUIRED')
                return {'status': 'preview_available', 'stage': 'native_dialogue', 'run_no': run_no,
                        'preview': report.get('preview'), 'native_audio_issues': report['native_audio_issues'],
                        'report': str(directory / 'film-check.json'), 'next_action': report.get('next_action')}
            if can_rebuild_caption_timeline(report):
                retry_pending = not report.get('caption_rebuild_attempted')
                checkpoint('pending' if retry_pending else 'waiting_user', 'FILM_CAPTION_ALIGNMENT_PENDING')
                return {'status': 'running' if retry_pending else 'preview_available', 'stage': 'caption_alignment',
                        'run_no': run_no, 'preview': report.get('preview'), 'report': str(directory / 'film-check.json'),
                        'missing_caption_lines': report['missing_caption_lines'], 'next_action': report.get('next_action')}
            if (plan.get('quality_policy') or {}).get('version') == '58':
                from film_inventory import reserve, copy_artifacts
                inventory = reserve(STATE, grant['project_key'], plan['date'], plan['platforms'], run_no, plan['rules_version'])
                if inventory:
                    atomic(inventory_file, inventory)
                    copy_artifacts(inventory['video'], output)
                    plan['platforms'] = inventory['platforms']
                    steps['inventory_source_run'] = inventory['source_run_no']
                    checkpoint()
            if not inventory:
                raise RuntimeError('FILM_CHECK_FAILED')
    from publish.dispatch import film_review
    film_review(job_path, {'job': {'film': True}, 'artifacts': [
        {'role': 'video', 'file': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}],
        'platform': next(iter(plan['platforms'])), 'manifest_sha256': ''})
    steps['film_check'] = 'pass'
    try:
        measured = run_command([shutil.which('ffprobe') or 'ffprobe', '-v', 'error',
                                '-show_entries', 'format=duration', '-of', 'csv=p=0', str(output)],
                               directory, timeout=10)
        steps['film_duration_ms'] = str(round(float(measured.stdout.strip()) * 1000))
    except (OSError, ValueError, OverflowError, RuntimeError, subprocess.TimeoutExpired):
        pass  # Optional monitoring metadata; the production gate already ran.
    publish_job = directory / 'publish.json'
    publish_payload = {'video': str(output), 'film': True, 'platforms': plan['platforms']}
    if editorial_row is not None:
        publish_payload.update(marketing_standard='store_v2', copy_policies=copy_policies)
        atomic(history_path, sorted([*history, editorial_row], key=lambda row: (row['date'], row.get('work_slot', 1)))[-120:])
    atomic(publish_job, publish_payload)
    summary = {'status': 'awaiting_review', 'output': str(output), 'publish_job': str(publish_job),
               'project_key':grant.get('project_key'), 'source_date':plan['date'], 'rules_version':plan['rules_version'],
               'activity_content':bool((plan.get('editorial_profile') or {}).get('activity')),
               'valid_until':((plan.get('editorial_profile') or {}).get('activity') or {}).get('end'),
               'run_no': run_no, 'quoted_credits': total + int(plan.get('preparation_credits', 0)) + sum(
                   int(value) for key, value in steps.items() if key.startswith('recovery_cost_')),
               'contact_sheet': str(output.with_name(output.stem + '_sheet.jpg')),
               'check_report': str(output) + '.check.txt' if Path(str(output) + '.check.txt').is_file() else None,
               'segments': [{'task_id': steps[f'task_{index}'],
                             'dialogue': segment.get('dialogue'), 'subtitles': segment.get('subs', []),
                             'applied_reference_asset_ids': steps[f'applied_refs_{index}'].split(':')
                             if f'applied_refs_{index}' in steps else None}
                            for index, segment in enumerate(plan['segments'])]}
    if 'script_intent' in plan:
        summary['script_intent'] = plan['script_intent']
    if 'script_review' in plan:
        summary['script_review'] = plan['script_review']
    if 'missing_information' in plan:
        summary['missing_information'] = plan['missing_information']
    if 'dialogue_classification_counts' in plan:
        summary['dialogue_classification_counts'] = plan['dialogue_classification_counts']
        summary['category_direction'] = plan['category_direction']
    if 'content_angle' in plan:
        summary['content_angle'] = plan['content_angle']
        summary['first_frame_prompts'] = [segment.get('first_frame_prompt') for segment in plan['segments']]
    if inventory:
        summary.update(delivery_source='inventory', source_run_no=inventory['source_run_no'],
                       source_date=inventory['review']['source_date'], segments=inventory['review'].get('segments', []))
    summary['quality_policy'] = render_policy
    proof_file = Path(str(output) + '.film.json')
    proof = json.loads(proof_file.read_text(encoding='utf-8'))
    summary['warnings'] = [*plan.get('warnings', []), *proof.get('warnings', [])]
    summary['speech_status'] = proof.get('speech_status', 'unknown')
    atomic(directory / 'review-ready.json', summary)
    steps['stage'] = 'review'
    checkpoint('waiting_user')
    return summary


def assistant_schedule():
    return {'status': 'assistant_workflow', 'scheduler': 'customer_ai_assistant',
            'production': {'connection': 'existing_thinknova_mcp_oauth',
                           'device_pairing_required': False,
                           'local_command': 'python .thinknova-run.py film job.json',
                           'connection_check': 'If the ThinkNova connector reports a missing link_id, reconnect it in the affected assistant and verify get_balance, get_content_rules and existing task IDs before starting new generation.',
                           'migration': {'update_existing_tasks': True, 'preserve_schedule_and_chat': True,
                                         'replace_legacy_commands': ['enable-production', 'produce-once',
                                                                     'run-day', 'daily-film'],
                                         'reuse_existing_task_ids_before_generation': True},
                           'steps': ['get_content_rules', 'get_balance.quote_request',
                                     'generate_with_max_credits', 'get_task', 'get_result', 'toolkit.py film']},
            'publication': {'executor': 'customer_ai_assistant', 'browser': 'ego_lite',
                            'toolkit_publisher': False}}


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
              'timezone', 'expires_at', 'project_key', 'weekly_budget', 'production_time', 'auto_publish')
    return {'status': 'available', 'platform': 'thinknova_production',
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
        if not CREDENTIALS.is_file():
            raise RuntimeError('AUTOMATION_AUTHORIZATION_REQUIRED')
        client = Client(secure_state.load(CREDENTIALS))
        preflight_plan_copy(client, plan)
        claim = client.claim('produce')
        if not claim.get('due'):
            raise RuntimeError('DAY_PLAN_RUN_NOT_DUE')
        return execute(client, claim, day_plan=plan, budget=budget)


def day_plan_request_version(grant):
    for version in (11, 10, 9):
        if version in grant.get('supported_day_plan_request_versions', []):
            return version
    return grant['day_plan_request_version'] if grant.get('day_plan_request_version') in (5, 6, 7, 8) else 4


def daily_film(project, day, work_slot=1):
    from store_film import validate_day_plan
    with state_lock(STATE / 'runner'):
        if (STATE / 'paused.json').exists():
            raise RuntimeError('AUTOMATION_PAUSED')
        if not CREDENTIALS.is_file():
            raise RuntimeError('AUTOMATION_AUTHORIZATION_REQUIRED')
        client = Client(secure_state.load(CREDENTIALS))
        payload, _ = client.post('/mcp/device/configuration', {})
        grant = payload.get('data') or {}
        if project != grant.get('project_key') or day != grant.get('local_date'):
            raise RuntimeError('DAY_PLAN_SCOPE_CHANGED')
        payload, _ = client.post('/mcp/device/day-plan', {'work_slot': work_slot, 'schema_version':
            day_plan_request_version(grant)})
        result = payload.get('data') or {}
        if result.get('status') not in ('ready', 'preparing'):
            return result
        plan = validate_day_plan(result['plan']) if result['status'] == 'ready' else result['plan']
        if (plan['date'], plan.get('project_key'), plan['rules_version']) != (day, project, grant['rules_version']):
            raise RuntimeError('DAY_PLAN_SCOPE_CHANGED')
        if plan.get('work_slot', 1) != work_slot:
            raise RuntimeError('DAY_PLAN_SCOPE_CHANGED')
        preflight_plan_copy(client, plan)
        claim = client.claim('produce', work_slot)
        if not claim.get('due'):
            return {'status': 'not_due'}
        return execute(client, claim, day_plan=plan, budget=int(grant['daily_budget']))


def scheduled_store_day(phase):
    if phase != 'produce':
        raise RuntimeError('PUBLICATION_MOVED_TO_ASSISTANT_EGO')
    """Poll a due phase for each work authorized on the device."""

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
        for slot in range(1, int(grant.get('daily_work_count', 1)) + 1):
            reminder = STATE / ('daily-reminder.json' if slot == 1 else f'daily-reminder-{slot}.json')
            try:
                scheduled_store_work(client, phase, grant, day, slot, reminder)
            except (RuntimeError, OSError, ValueError) as exc:
                code = str(exc) if re.fullmatch(r'[A-Z0-9_]{1,64}', str(exc)) else 'DAY_PLAN_SLOT_FAILED'
                atomic(reminder, {'date': day, 'work_slot': slot, 'error_code': code})


def scheduled_store_work(client, phase, grant, day, slot, reminder):
    from store_film import validate_day_plan
    if phase != 'produce':
        raise RuntimeError('PUBLICATION_MOVED_TO_ASSISTANT_EGO')
    if phase == 'produce':
        if grant.get('local_time', '') < grant.get('production_time', '10:00'):
            return
        path = STATE / 'plans' / grant['project_key'] / (f'{day}.json' if slot == 1 else f'{day}-{slot}.json')
        if path.is_file():
            try:
                from dialogue_encoding import read_json
                raw_plan = read_json(path)
            except (OSError, ValueError):
                atomic(reminder, {'date': day, 'error_code': 'DAY_PLAN_FILE_INVALID'})
                return
        else:
            try:
                response, _ = client.post('/mcp/device/day-plan', {'work_slot': slot, 'schema_version':
                    day_plan_request_version(grant)})
            except (RuntimeError, OSError) as exc:
                code = str(exc) if re.fullmatch(r'[A-Z0-9_]{1,64}', str(exc)) else 'DAY_PLAN_CONNECTION_FAILED'
                atomic(reminder, {'date': day, 'error_code': code})
                return
            result = response.get('data') or {}
            status = result.get('status')
            if status == 'preparing':
                claim = client.claim('produce', slot)
                if not claim.get('due'):
                    return
                from day_preparation import prepare_assets
                directory = STATE / 'runs' / claim['run_no']
                directory.mkdir(parents=True, exist_ok=True)
                if result['plan'].get('script_rules_revision') in ('64', '65'):
                    execute(client, claim, day_plan=result['plan'], budget=int(grant['daily_budget']))
                    return
                from render.preflight import require_film_preflight
                require_film_preflight(claim.setdefault('steps', {}))
                raw_plan = prepare_assets(client, claim, result['plan'], directory, int(grant['daily_budget']), quoted_generation_args, atomic)
                plan = validate_day_plan(raw_plan)
                atomic(path, plan)
                execute(client, claim, day_plan=plan, budget=int(grant['daily_budget']))
                return
            if status != 'ready':
                if status not in ('processing', 'not_due'):
                    atomic(reminder, {
                        'date': day, 'error_code': result.get('error_code') or 'DAY_PLAN_INPUT_REQUIRED',
                        'missing_fields': result.get('missing_fields', []),
                        'next_action': result.get('next_action'),
                        'script_context': result.get('script_context'),
                        'issues': result.get('issues', []),
                    })
                return
            raw_plan = result.get('plan')
        try:
            plan = validate_day_plan(raw_plan)
        except ValueError as exc:
            atomic(reminder, {'date': day, 'error_code': str(exc)})
            return
        if (plan['date'] != day or plan['rules_version'] != grant['rules_version']
                or plan.get('project_key') != grant['project_key'] or plan.get('work_slot', 1) != slot):
            atomic(reminder, {'date': day, 'error_code': 'DAY_PLAN_SCOPE_CHANGED'})
            return
        try:
            preflight_plan_copy(client, plan)
        except (ValueError, RuntimeError) as exc:
            atomic(reminder, {'date': day, 'error_code': str(exc)})
            return
        claim = client.claim('produce', slot)
        if claim.get('due'):
            try:
                execute(client, claim, day_plan=plan, budget=int(grant['daily_budget']))
            except RuntimeError as exc:
                atomic(reminder, {'date': day, 'error_code': str(exc)})
                raise
    else:
        raise RuntimeError('PUBLICATION_MOVED_TO_ASSISTANT_EGO')


def publish_store_day(client, claim):
    raise RuntimeError('PUBLICATION_MOVED_TO_ASSISTANT_EGO')


def daily_schedule_status():
    return 'external_ai_assistant'


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
    raise RuntimeError('SYSTEM_SCHEDULING_REMOVED_USE_ASSISTANT')


def _register_daily_schedules():
    raise RuntimeError('SYSTEM_SCHEDULING_REMOVED_USE_ASSISTANT')



def tick():
    return scheduled_store_day('produce')


def connected_report(check_local: bool = True, require_codex: bool = True, require_publication: bool = False) -> dict:
    from health import report
    result=report() if check_local else {'schema_version':1,'checked_at':datetime.now(timezone.utc).isoformat(),'checks':[],'overall':'partial'}
    def status(name, state, remedy=''):
        for check in result['checks']:
            if check['name']==name:check.update(status=state,remedy=remedy);return
        result['checks'].append({'name':name,'status':state,'remedy':remedy})
    if require_codex:
        codex=shutil.which('codex')
        try:status('codex_login','pass' if codex and subprocess.run([codex,'login','status'],capture_output=True,timeout=15).returncode==0 else 'waiting_user','Sign in to Codex / 请登录 Codex')
        except Exception:status('codex_login','waiting_user','CODEX_LOGIN_REQUIRED')
    else:
        status('codex_login','not_applicable','Use the customer assistant plan or the server day plan')
    try:
        client=Client(secure_state.load(CREDENTIALS))
        config,_=client.post('/mcp/device/configuration',{})
        balance=client.tool('get_balance')
        result['available_credits']=int(balance.get('available_credits',0))
        status('server_quote','pass' if balance.get('quote_mode_supported') is True else 'waiting_user','Update ThinkNova API before enabling paid execution / 请先更新支持只读报价的 API')
        status('account','pass' if balance.get('generation_available') and balance.get('available_credits',0)>0 else 'waiting_user','Check plan and credits / 检查套餐和积分')
        project = (config.get('data') or {}).get('project_key')
        rules = client.tool('get_content_rules', {'project_key': project}) if project else client.tool('get_content_rules')
        status('rules', 'pass' if (not rules.get('needs_onboarding') or rules.get('defaults_revision'))
               and rules.get('version') == config['data']['rules_version'] else 'waiting_user',
               'Use creation defaults and current rules / 使用创作默认值与当前规则')
        status('platform_authorization','not_applicable','Publishing is owned by the customer AI assistant and Ego Lite')
    except (Exception,SystemExit):status('account','waiting_user','Pair an active device/grant; no secrets in chat / 配对有效设备与授权')
    required=[c for c in result['checks'] if c['name'] in ('python','files','virtual_environment','git','ffmpeg','ffprobe','libass','cjk_font','codex_login','account','rules','platform_authorization','server_quote')]
    required = [check for check in required if check['name'] != 'platform_authorization']
    if not require_codex:
        required = [check for check in required if check['name'] != 'codex_login']
    result['automation_ready']=all(c['status']=='pass' for c in required)
    result['overall']='partial' if result['automation_ready'] else 'blocked'
    return result


def doctor_command(as_json):
    from health import display
    print('Checking local production and ThinkNova access / 正在检查本机制作及 ThinkNova 访问', file=sys.stderr, flush=True)
    if as_json:
        try:
            probe = subprocess.run(
                [sys.executable, '-c',
                 'import automation, contextlib, json, sys; '
                 'redirect = contextlib.redirect_stdout(sys.stderr); '
                 'redirect.__enter__(); result = automation.connected_report(require_codex=False); '
                 'redirect.__exit__(None, None, None); print(json.dumps(result, ensure_ascii=True))'],
                cwd=ROOT, capture_output=True, timeout=150, encoding='utf-8', errors='replace',
            )
            if probe.returncode != 0:
                raise ValueError('AUTOMATION_DOCTOR_PROBE_FAILED')
            result = json.loads(probe.stdout)
        except subprocess.TimeoutExpired:
            result = {'schema_version': 1, 'automation_ready': False, 'overall': 'blocked',
                      'checks': [{'name': 'connected_probe', 'status': 'unknown',
                                  'remedy': 'AUTOMATION_DOCTOR_TIMEOUT: check local production and ThinkNova access separately'}]}
        except (OSError, ValueError):
            result = {'schema_version': 1, 'automation_ready': False, 'overall': 'blocked',
                      'checks': [{'name': 'connected_probe', 'status': 'unknown', 'remedy': 'AUTOMATION_DOCTOR_PROBE_FAILED'}]}
    else:
        result = connected_report(require_codex=False)
    display(result, as_json)
    return 0 if result['automation_ready'] else 2


def installation_preflight():
    raise RuntimeError('SYSTEM_SCHEDULING_REMOVED_USE_ASSISTANT')


SCHEDULE_LABEL='top.thinknova.controlled-automation'

def schedule_path():
    return Path.home()/'Library/LaunchAgents'/(SCHEDULE_LABEL+'.plist')


def install_runner():
    raise RuntimeError('SYSTEM_SCHEDULING_REMOVED_USE_ASSISTANT')


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
    if len(sys.argv)>1 and sys.argv[1] in ('youtube-auth','tick','tick-produce','tick-publish','install-daily-schedules','install'):
        from delivery_boundary import handoff, SCHEDULING_MOVED
        print(json.dumps(handoff(SCHEDULING_MOVED if sys.argv[1] != 'youtube-auth' and sys.argv[1] != 'tick-publish' else 'PUBLICATION_MOVED_TO_ASSISTANT_EGO'),ensure_ascii=False))
        return 2
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['pair','doctor','produce-once','uninstall','pause','revoke']);parser.add_argument('--user-confirmed',action='store_true');parser.add_argument('--json',action='store_true');args=parser.parse_args()
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
        elif args.command=='doctor':
            return doctor_command(args.json)
        elif args.command=='produce-once':
            if not CREDENTIALS.is_file():
                print(json.dumps({**assistant_schedule(), 'status': 'migration_required',
                                  'reason_code': 'USE_EXISTING_MCP_CONNECTION'}))
                return 2
            scheduled_store_day('produce')
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
