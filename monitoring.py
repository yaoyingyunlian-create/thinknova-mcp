"""Independent, read-only device monitoring. Never invokes AI, generates or publishes."""
from __future__ import annotations
import argparse
import getpass
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys
import time
from automation_client import Client
from automation import STATE, ROOT, atomic
from local_state import state_lock, LocalStateBusy
import secure_state

TOKEN=STATE/('monitor.keychain' if platform.system()=='Darwin' else 'monitor.dpapi')
LABEL='top.thinknova.monitoring'

def post(value):
    return Client(secure_state.load(TOKEN)).post('/mcp/device/heartbeat',value,execution=False)


def event(platform_name, stage, code=None):
    if not all(re.fullmatch('[A-Za-z0-9_.:-]{1,64}',v or '') for v in (platform_name,stage)) or (code is not None and not re.fullmatch('[A-Z0-9_]{1,64}',code)):
        raise RuntimeError('INVALID_MONITOR_EVENT')
    pending=STATE/'monitor_pending.json'
    with state_lock(pending):
        events=json.loads(pending.read_text(encoding='utf-8')) if pending.exists() else {}
        # Legacy single-event state is migrated without leaking its raw contents.
        if 'state' in events:events={str(events.get('platform','unknown'))+':'+str(events.get('stage','unknown')):events}
        key=platform_name+':'+stage
        if code is None:events.pop(key,None)
        else:events[key]={'state':'failed','platform':platform_name,'stage':stage,'error_code':code}
        atomic(pending,dict(sorted(events.items())))
    value={'state':'failed' if events else 'normal','platform':platform_name,'stage':stage,'events':list(events.values())[:20]}
    if events:value.update(next(iter(events.values())))
    if TOKEN.is_file():
        try: post(value)
        except Exception:return False
    return True


def tick():
    with state_lock(STATE/'monitor'):
        previous=STATE/'monitor_last.json'
        last=json.loads(previous.read_text(encoding='utf-8')) if previous.exists() else {}
        full=time.time()-last.get('full_time',0)>=3600
        if full:
            from health import report
            result=report()
            value={'state':'normal' if result['local_ready'] else 'failed','full_check':True,'checks':result['checks']}
            if not result['local_ready']: value.update(stage='installation',error_code='LOCAL_PREFLIGHT_INCOMPLETE')
            atomic(STATE/'monitor_health.json',value)
        else:
            path=STATE/'monitor_health.json'
            value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'state':'unknown'}
            value['full_check']=False
        pending=STATE/'monitor_pending.json'
        if pending.exists():
            events=json.loads(pending.read_text(encoding='utf-8'))
            if 'state' in events:events={'legacy':events}
            if events:
                value.update(next(iter(events.values())))
                value['events']=list(events.values())[:20]
        post(value)
        atomic(previous,{'time':time.time(),'full_time':time.time() if full else last.get('full_time',0)})


def install():
    command=[sys.executable,str(ROOT/'monitoring.py'),'tick']
    if platform.system()=='Windows':
        subprocess.run(['schtasks','/Create','/F','/TN','ThinkNova-Monitoring','/SC','MINUTE','/MO','15','/IT','/TR',subprocess.list2cmdline(command)],capture_output=True,check=True)
    elif platform.system()=='Darwin':
        path=Path.home()/'Library/LaunchAgents'/(LABEL+'.plist');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(plistlib.dumps({'Label':LABEL,'ProgramArguments':command,'WorkingDirectory':str(ROOT),'StartInterval':900,'RunAtLoad':True,'LimitLoadToSessionType':'Aqua','EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin')}}));path.chmod(0o600)
        subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True,capture_output=True)
    else: raise RuntimeError('MONITOR_OS_UNSUPPORTED')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['pair','tick','install','uninstall','event','recover']);p.add_argument('--user-confirmed',action='store_true');p.add_argument('--platform');p.add_argument('--stage');p.add_argument('--code');a=p.parse_args()
    try:
        if a.command=='pair':
            token=getpass.getpass('Telemetry token (hidden): ')
            if not re.fullmatch('[a-f0-9]{64}',token):raise RuntimeError('INVALID_DEVICE_CREDENTIAL')
            secure_state.save(TOKEN,{'telemetry_token':token})
        elif a.command=='tick':tick()
        elif a.command=='event':event(a.platform,a.stage,a.code)
        elif a.command=='recover':event(a.platform,a.stage,None)
        elif a.command=='install':
            if not a.user_confirmed:raise RuntimeError('SCHEDULE_CONFIRMATION_REQUIRED')
            if not TOKEN.exists():raise RuntimeError('MONITOR_PAIR_REQUIRED')
            tick();install()
        else:
            if not a.user_confirmed:raise RuntimeError('SCHEDULE_CONFIRMATION_REQUIRED')
            if platform.system()=='Windows':subprocess.run(['schtasks','/Delete','/F','/TN','ThinkNova-Monitoring'],check=True,capture_output=True)
            elif platform.system()=='Darwin':
                path=Path.home()/'Library/LaunchAgents'/(LABEL+'.plist')
                if path.exists():
                    subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}',str(path)],check=True,capture_output=True);path.unlink()
        return 0
    except LocalStateBusy:return 0
    except Exception as exc:
        code=str(exc) if re.fullmatch('[A-Z0-9_]{1,64}',str(exc)) else 'MONITOR_ACTION_FAILED'
        print(code,file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
