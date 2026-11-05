"""Local publication manifest, seven-day duplicate guard and explicit script dispatch."""
from __future__ import annotations
import argparse
import contextlib
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_state import state_lock
from automation import atomic
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common.jobfile import load_job, local_preflight

ROOT=Path(__file__).resolve().parents[1]
HISTORY=ROOT/'publication_history.json'
ATTEMPTS=ROOT/'publication_attempts'
PLATFORMS=('youtube','tiktok','xiaohongshu','douyin','facebook','instagram','x','linkedin')

def normalize(text):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(text)).casefold()).strip()


def validate_variants(raw):
    variants=raw.get('platforms') or {}
    if not isinstance(variants,dict):raise RuntimeError('INVALID_PLATFORM_VARIANTS')
    seen={}
    for platform, override in variants.items():
        if platform not in PLATFORMS or not isinstance(override,dict):raise RuntimeError('INVALID_PLATFORM_VARIANTS')
        merged={**raw,**override}
        caption=merged.get('description',merged.get('caption',merged.get('body','')))
        if isinstance(caption,list):caption='\n'.join(caption)
        tags=merged.get('tags') or []
        if not isinstance(tags,list) or not all(isinstance(t,str) for t in tags):raise RuntimeError('INVALID_PUBLICATION_TAGS')
        signature=(normalize(merged.get('title','')),normalize(caption),tuple(tags))
        if signature in seen:raise RuntimeError('PLATFORM_COPY_VARIATION_REQUIRED')
        seen[signature]=platform


def snapshot(path, platform):
    raw=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    validate_variants(raw)
    job=load_job(str(path),platform)
    account=job.get('target_account') or job.get('expected_channel_id') or job.get('page_name')
    if platform=='youtube':
        account=job.get('expected_channel_id') or job.get('target_account')
        if not isinstance(account,str) or not re.fullmatch('UC[A-Za-z0-9_-]{22}',account):raise RuntimeError('YOUTUBE_CHANNEL_ID_REQUIRED')
        job['expected_channel_id']=account
    if not isinstance(account,str) or not account.strip():raise RuntimeError('TARGET_ACCOUNT_REQUIRED')
    files_to_check=[job[k] for k in ('video','cover','srt') if job.get(k)]+list(job.get('images') or [])
    if any(not Path(p).is_file() for p in files_to_check):raise RuntimeError('LOCAL_FILE_MISSING')
    title=job.get('title','');caption=job.get('description',job.get('caption',job.get('body','')))
    if isinstance(caption,list):caption='\n'.join(caption)
    if not isinstance(title,str) or not isinstance(caption,str) or not isinstance(job.get('tags',[]),list):raise RuntimeError('INVALID_PUBLICATION_TEXT')
    files=[(k,job[k]) for k in ('video','cover') if job.get(k)] + [('image',p) for p in (job.get('images') or [])]
    artifacts=[{'role':role,'file':str(Path(p).resolve()),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()} for role,p in files]
    flat={k:v for k,v in job.items() if not k.startswith('_')}
    value={'platform':platform,'target_account':account,'title':title,'caption':caption,'tags':job.get('tags',[]),
           'artifacts':artifacts,'job':flat,'actual_readback':'pending'}
    value['manifest_sha256']=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    return value


def duplicate(candidate, history, clock=None):
    cutoff=(clock or datetime.now(timezone.utc))-timedelta(days=7)
    for old in history:
        if old.get('platform')!=candidate['platform'] or old.get('target_account')!=candidate['target_account']:continue
        if old.get('state') not in ('verified','outcome_unknown','submitted_unverified','executing'):continue
        current_media=[a['sha256'] for a in candidate['artifacts'] if a.get('role')!='cover']
        old_media=[a['sha256'] for a in old.get('artifacts',[]) if a.get('role')!='cover']
        same_video=bool(current_media) and current_media==old_media
        same_text=bool(normalize(candidate['caption'])) and normalize(candidate['caption'])==normalize(old.get('caption',''))
        same_title=bool(normalize(candidate['title'])) and normalize(candidate['title'])==normalize(old.get('title',''))
        if same_video or same_text or same_title:
            if old.get('state')!='verified' or datetime.fromisoformat(old['attempted_at'])>=cutoff:return True
    return False


def dispatch(path, platform, execute=False, confirmed=False):
    if platform not in PLATFORMS:raise RuntimeError('PLATFORM_NOT_SUPPORTED')
    value=snapshot(path,platform)
    script=ROOT/'publish'/platform/('upload.py' if platform=='youtube' else 'publish.py')
    preflight=subprocess.run([sys.executable,str(script),str(path.resolve()),'--dry'],capture_output=True,timeout=120)
    if preflight.returncode:raise RuntimeError('PUBLISHER_LOCAL_PREFLIGHT_FAILED')
    if not execute:return value
    if not confirmed:raise RuntimeError('PUBLICATION_CONFIRMATION_REQUIRED')
    ATTEMPTS.mkdir(exist_ok=True)
    value['attempt_id']=uuid.uuid4().hex
    marker=ATTEMPTS/(value['attempt_id']+'.json')
    with state_lock(HISTORY):
        history=json.loads(HISTORY.read_text(encoding='utf-8')) if HISTORY.exists() else []
        if duplicate(value,history) or marker.exists():raise RuntimeError('RECENT_DUPLICATE_OR_UNKNOWN_ATTEMPT')
        value.update(state='executing',attempted_at=datetime.now(timezone.utc).isoformat())
        with marker.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False)
        history.append(value);atomic(HISTORY,history)
    # Freeze the exact merged payload; publisher consumes this same file, not a mutable original.
    frozen=ATTEMPTS/(value['attempt_id']+'.job.json');atomic(frozen,value['job'])
    script=ROOT/'publish'/platform/('upload.py' if platform=='youtube' else 'publish.py')
    command=[sys.executable,str(script),str(frozen),'--execute']
    try:
        result=subprocess.run(command,timeout=1200)
        receipt=Path(str(frozen)+'.receipt.json')
        evidence=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
        value['state']='verified' if result.returncode==0 and evidence.get('state')=='verified' else ('submitted_unverified' if result.returncode==0 else 'outcome_unknown')
        value['actual_readback']=evidence if evidence else 'pending'
    except Exception:
        value['state']='outcome_unknown'
    finally:
        atomic(marker,value)
        with state_lock(HISTORY):
            history=json.loads(HISTORY.read_text(encoding='utf-8'))
            history=[value if row.get('attempt_id')==value['attempt_id'] else row for row in history]
            atomic(HISTORY,history)
    try:
        import monitoring
        monitoring.event(platform,'publication',None if value['state']=='verified' else 'PUBLICATION_OUTCOME_UNVERIFIED')
    except Exception:pass
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('job',type=Path);p.add_argument('--platform',choices=PLATFORMS,required=True);m=p.add_mutually_exclusive_group(required=True);m.add_argument('--dry',action='store_true');m.add_argument('--execute',action='store_true');p.add_argument('--user-confirmed',action='store_true');a=p.parse_args()
    try:
        value=dispatch(a.job,a.platform,a.execute,a.user_confirmed);print(json.dumps(value,ensure_ascii=False));return 0 if value.get('state') in (None,'verified') else 2
    except Exception as exc:
        code=str(exc) if re.fullmatch('[A-Z0-9_]{1,64}',str(exc)) else 'PUBLICATION_PREFLIGHT_FAILED'
        print(json.dumps({'status':'failed','error':code}));return 2

if __name__=='__main__':sys.exit(main())
