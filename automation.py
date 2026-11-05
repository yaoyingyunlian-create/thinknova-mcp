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
import urllib.parse
import urllib.request
from local_state import state_lock, LocalStateBusy
from automation_client import Client, NoRedirect
import secure_state

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
        if not isinstance(shot,dict) or set(shot)!={'prompt'} or not isinstance(shot['prompt'],str) or not 1<=len(shot['prompt'])<=3500:raise RuntimeError('INVALID_CONTENT_PLAN')
    return value


def run_command(args: list[str], cwd: Path, timeout=300, stdout=None):
    result=subprocess.run(args, cwd=cwd, capture_output=stdout is None, stdout=stdout, stderr=subprocess.PIPE if stdout else None, timeout=timeout, text=True, encoding='utf-8', errors='replace')
    if result.returncode:raise RuntimeError('LOCAL_COMMAND_FAILED')
    return result


def make_plan(directory: Path, rules: dict) -> dict:
    codex=shutil.which('codex')
    if not codex:raise RuntimeError('CODEX_UNAVAILABLE')
    output=directory/'plan.json'
    # Only a constrained content plan is consumed. No model-provided commands or paths.
    prompt='Create one YouTube video content plan matching these account rules. Return only the requested JSON. No commands, tool calls, purchases or publication. Do not claim unsupported facts. Rules: '+json.dumps(rules,ensure_ascii=False)
    command=[codex,'exec','--ignore-user-config','--ephemeral','--sandbox','read-only','--skip-git-repo-check','-C',str(directory),'--output-schema',str(ROOT/'automation_plan.schema.json'),'--output-last-message',str(output),'-']
    # Do not inherit device/platform tokens through subprocess environment.
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN','SECRET','PASSWORD','YT_','THINKNOVA_'))}
    started=time.monotonic()
    result=subprocess.run(command,input=prompt,cwd=directory,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
    atomic(directory/'client_usage.json',{'client':'codex','elapsed_seconds':round(time.monotonic()-started,3),'model_tokens':'unknown','tool_calls':'unknown','note':'No client quota or subscription consumption is inferred.'})
    if result.returncode or not output.is_file():raise RuntimeError('CODEX_PLAN_FAILED')
    return validate_plan(json.loads(output.read_text(encoding='utf-8')))


def download(url: str, path: Path):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='api.thinknova.top' or parsed.username or parsed.password:raise RuntimeError('UNSAFE_DELIVERY_URL')
    if not re.fullmatch(r'/api/v1/assets/asset_[A-Za-z0-9]+/media',parsed.path):raise RuntimeError('UNSAFE_DELIVERY_URL')
    query=[(k,v) for k,v in urllib.parse.parse_qsl(parsed.query,keep_blank_values=True) if k!='download']+[('download','1')]
    url=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urllib.parse.urlencode(query),''))
    request=urllib.request.Request(url,headers={'User-Agent':'ThinkNova-Controlled-Runner/1.0'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=60) as response, path.with_suffix('.tmp').open('wb') as stream:
        if not response.headers.get('Content-Type','').lower().startswith(('video/','application/octet-stream')):raise RuntimeError('INVALID_DELIVERY_TYPE')
        total=0
        while chunk:=response.read(1024*1024):
            total+=len(chunk)
            if total>256*1024*1024:raise RuntimeError('DELIVERY_TOO_LARGE')
            stream.write(chunk)
    os.replace(path.with_suffix('.tmp'),path)


def compose(directory: Path, count: int, progress=lambda: None) -> Path:
    progress()
    output=directory/'final.mp4'
    if output.exists(): return output
    job=directory/'assemble.json'
    atomic(job, {'out':'final.mp4','clips':[{'file':f'shot{i}.mp4','fit':'contain'} for i in range(count)]})
    run_command([sys.executable,str(ROOT/'render/assemble.py'),str(job),'--json'],directory)
    progress()
    return output


def execute(client: Client, claim: dict):
    run_no=claim['run_no'];grant=claim['grant']
    if not re.fullmatch(r'run_[a-f0-9]{24}',run_no):raise RuntimeError('INVALID_RUN_ID')
    directory=STATE/'runs'/run_no;directory.mkdir(parents=True,exist_ok=True)
    state_path=directory/'state.json';steps=dict(claim.get('steps') or {})
    if state_path.exists():steps.update(json.loads(state_path.read_text(encoding='utf-8')))
    def checkpoint(status='running',error=None):
        atomic(state_path,steps);client.receipt(run_no,steps,status,error)
    try:
        if not connected_report()['automation_ready']:raise RuntimeError('AUTOMATION_PREFLIGHT_INCOMPLETE')
        rules=client.tool('get_content_rules')
        if rules['version']!=grant['rules_version'] or rules.get('needs_onboarding'):raise RuntimeError('RULES_CHANGED')
        balance=client.tool('get_balance')
        if not balance.get('generation_available') or balance.get('available_credits',0)<=0:raise RuntimeError('CREDITS_OR_PLAN_REQUIRED')
        plan_path=directory/'content.json'
        steps['stage']='planning';checkpoint()
        if plan_path.exists():plan=validate_plan(json.loads(plan_path.read_text(encoding='utf-8')))
        else:plan=make_plan(directory,rules['effective_rules']);atomic(plan_path,plan)
        steps['stage']='generation'
        for index,shot in enumerate(plan['shots']):
            key=f'task_{index}'
            if key not in steps:
                checkpoint()
                created=client.tool('generate_video',{'prompt':shot['prompt'],'client_request_id':f'{run_no}:shot:{index}','automation_run_id':run_no})
                steps[key]=created['task_id'];checkpoint()
            deadline=time.monotonic()+900
            while True:
                task=client.tool('get_task',{'task_id':steps[key]})
                if task['status']=='succeeded':break
                if task['status'] in ('failed','canceled','cancelled'):raise RuntimeError('GENERATION_TERMINAL_FAILURE')
                if time.monotonic()>deadline:raise RuntimeError('GENERATION_STILL_RUNNING')
                checkpoint();time.sleep(20)
            path=directory/f'shot{index}.mp4'
            if not path.exists():
                result=client.tool('get_result',{'task_id':steps[key]})
                assets=[a for a in result.get('assets',[]) if a.get('type')=='video']
                if not assets:raise RuntimeError('VIDEO_DELIVERY_MISSING')
                download(assets[0]['download_url'],path)
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


def connected_report(check_local: bool = True) -> dict:
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
        status('account','pass' if balance.get('generation_available') and balance.get('available_credits',0)>0 else 'waiting_user','Check plan and credits / 检查套餐和积分')
        rules=client.tool('get_content_rules')
        status('rules','pass' if not rules.get('needs_onboarding') and rules.get('version')==config['data']['rules_version'] else 'waiting_user','Confirm current account rules / 确认当前账户规则')
        os.environ['YT_TOKEN']=str(YOUTUBE_TOKEN)
        sys.path.insert(0,str(ROOT/'publish/youtube'))
        import yt_common
        try:status('platform_authorization','pass' if yt_common.my_channel(yt_common.youtube())['id']==config['data']['channel_id'] else 'fail','YOUTUBE_CHANNEL_MISMATCH')
        except (Exception,SystemExit):status('platform_authorization','waiting_user','Run automation.py youtube-auth / 完成平台授权')
    except (Exception,SystemExit):status('account','waiting_user','Pair an active device/grant; no secrets in chat / 配对有效设备与授权')
    required=[c for c in result['checks'] if c['name'] in ('python','files','virtual_environment','git','ffmpeg','ffprobe','libass','cjk_font','codex_login','account','rules','platform_authorization')]
    result['automation_ready']=all(c['status']=='pass' for c in required)
    result['overall']='partial' if result['automation_ready'] else 'blocked'
    return result


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


def uninstall_runner():
    if platform.system()=='Windows':
        subprocess.run(['schtasks','/Delete','/F','/TN','ThinkNova-Controlled-Automation'],check=True,capture_output=True)
    else:
        path=schedule_path()
        if path.exists():
            subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}',str(path)],check=True,capture_output=True)
            path.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['pair','youtube-auth','doctor','tick','install','uninstall','pause','revoke']);parser.add_argument('--user-confirmed',action='store_true');parser.add_argument('--json',action='store_true');args=parser.parse_args()
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
            from health import display
            result=connected_report();display(result,args.json)
            return 0 if result['automation_ready'] else 2
        elif args.command=='tick':tick()
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
        print(code,file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
