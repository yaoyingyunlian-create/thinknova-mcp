"""Run bounded local repairs and keep a replayable, structured event journal."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from file_integrity import sha256
from local_state import LocalStateBusy, state_lock

TRANSIENT = {'FILM_CHECK_TIMEOUT', 'CONTACT_SHEET_FAILED', 'SPEECH_CHECK_PENDING', 'FILM_PACE_UNAVAILABLE'}
CAPTION = {'FILM_CAPTIONS_REQUIRED', 'FILM_SUBTITLE_SPLIT_REQUIRED', 'FILM_DIALOGUE_CHECK_PENDING'}
RECOVERY_ACTIONS = {'captions': 'THINKNOVA_FILM_REPAIR_CAPTIONS', 'recheck': 'THINKNOVA_FILM_REPAIR_RECHECK'}


def failure_codes(report):
    values = [report.get('error', '').split(':', 1)[0]]
    values.extend(item.get('code', '') for item in report.get('diagnostics', []) if isinstance(item, dict) and item.get('severity') != 'warning')
    return {value for value in values if isinstance(value, str) and re.fullmatch(r'[A-Z0-9_]{2,64}', value)} - {'CHECK_FAILED'}


def caption_repair(job):
    if job.get('srt') or any(clip.get('subs2') for clip in job.get('clips', [])):
        return None
    from render.assemble import Stop, split_text
    terms = tuple(term for term in (job.get('shop_name'), job.get('featured_service')) if isinstance(term, str) and term)
    clips = []
    for clip in job.get('clips', []):
        lines = clip.get('subs') or ([clip['text']] if clip.get('text') else [])
        if not lines:
            lines = [line['text'] for line in clip.get('dialogue', [])
                     if isinstance(line, dict) and isinstance(line.get('text'), str) and line['text'].strip()]
        try:
            pieces = [part for line in lines for part in split_text(line, cjk_limit=6, protected=terms)]
        except Stop:
            return None
        clips.append({**clip, 'subs': pieces})
    if clips != job.get('clips') and any(clip['subs'] for clip in clips):
        return {**job, 'clips': clips, 'align_subtitles': True, 'require_caption_alignment': True}
    return None


def render_film(root, job_path, job, recheck=False):
    from automation import atomic
    state_path = job_path.with_name('.' + job_path.name + '.film-state.json')
    try:
        with state_lock(state_path):
            return _render(root, job_path, job, recheck, state_path, atomic)
    except LocalStateBusy:
        return 2, {'status': 'blocked', 'error': 'FILM_RUN_BUSY'}


def record_external_event(root, job_path, stage, outcome, code, task_no):
    from automation import atomic
    if stage not in ('generation', 'download', 'quality') or outcome not in ('started', 'passed', 'failed'):
        raise ValueError('FILM_EVENT_INVALID')
    if not re.fullmatch(r'[A-Z0-9_]{0,64}', code) or (outcome == 'failed' and not code):
        raise ValueError('FILM_EVENT_INVALID')
    if task_no and not re.fullmatch(r'task_[a-f0-9]{12}', task_no):
        raise ValueError('FILM_EVENT_INVALID')
    state_path = job_path.with_name('.' + job_path.name + '.film-state.json')
    with state_lock(state_path):
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            state = {'run_id': uuid.uuid4().hex, 'events': []}
        version = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))['version']
        item = {'event_id': uuid.uuid4().hex, 'run_id': state['run_id'], 'stage': stage,
                'outcome': outcome, 'code': code, 'toolkit_version': version, 'rule_version': 'default', 'occurred_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
        if task_no:
            item['task_no'] = task_no
        state['events'].append(item)
        atomic(state_path, state)


def pending_events(job_path, acknowledged=()):
    from automation import atomic
    state_path = job_path.with_name('.' + job_path.name + '.film-state.json')
    with state_lock(state_path):
        if not state_path.is_file():
            return []
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if acknowledged:
            state['events'] = [event for event in state['events'] if event['event_id'] not in acknowledged]
            atomic(state_path, state)
        return state['events'][:50]


def _render(root, job_path, job, recheck, state_path, atomic):
    if not recheck and job.get('film') is not True and job.get('film_profile') != 'store_v2':
        raise ValueError('FILM_REVIEW_PROFILE_REQUIRED')
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        state = {'run_id': uuid.uuid4().hex, 'events': []}
    toolkit_version = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))['version']
    digest = hashlib.sha256(json.dumps([toolkit_version, job], sort_keys=True).encode())
    for entry in [job.get('music'), job.get('srt'), *(clip.get('file') for clip in job.get('clips', [])),
                  *(clip.get('cutaway', {}).get('file') for clip in job.get('clips', []) if isinstance(clip.get('cutaway'), dict))]:
        if isinstance(entry, str):
            path = job_path.parent / entry
            digest.update(sha256(path).encode() if path.is_file() else b'missing')
    fingerprint = digest.hexdigest()
    if state.get('input_digest') != fingerprint:
        state.update(input_digest=fingerprint, repairs=[], code=None, result={}, operation=None)
    rule_version = str(job.get('film_rules_revision') or job.get('film_schema_version') or 'default')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', rule_version):
        rule_version = 'default'

    def event(stage, outcome, code='', details=None):
        state['events'].append({'event_id': uuid.uuid4().hex, 'run_id': state['run_id'], 'stage': stage,
                                'outcome': outcome, 'code': code, 'toolkit_version': toolkit_version,
                                'rule_version': rule_version, 'occurred_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                **(details or {})})
        atomic(state_path, state)

    def execute(operation):
        checkpoint = job_path.parent / ('.film-render-' + operation['id'] + '.json')
        if checkpoint.is_file():
            report = json.loads(checkpoint.read_text(encoding='utf-8'))
            return report.get('exit_code', 0 if report.get('status') == 'succeeded' else 2), report
        try:
            process = subprocess.run([sys.executable, str(root / 'render' / 'assemble.py'), *operation['args'], '--json'],
                cwd=job_path.parent, env=dict(os.environ, THINKNOVA_REVIEW_PREVIEW='1', THINKNOVA_RENDER_CHECKPOINT=str(checkpoint)),
                stdout=subprocess.PIPE, stderr=sys.stderr, encoding='utf-8', errors='replace', timeout=1800)
            report = json.loads(process.stdout)
            if isinstance(report, dict):
                return process.returncode, report
        except subprocess.TimeoutExpired:
            return 2, {'error': 'FILM_CHECK_TIMEOUT'}
        except (OSError, ValueError):
            pass
        return 2, {'error': 'FILM_RENDER_REPORT_UNAVAILABLE'}

    def record(code, report, stage):
        state.update(code=code, result=report, operation=None)
        codes = sorted(failure_codes(report)) if code else []
        for reason in (codes or ['FILM_CHECK_FAILED' if code else '']):
            details = {}
            if code:
                for diagnostic in report.get('diagnostics', []):
                    if not isinstance(diagnostic, dict) or diagnostic.get('code') != reason:
                        continue
                    match = re.search(r'\(([0-9]+(?:\.[0-9]+)?)[–-]([0-9]+(?:\.[0-9]+)?)s\)$',
                                      str(diagnostic.get('message', '')))
                    if match:
                        start, end = (round(float(value) * 1000) for value in match.groups())
                        if 0 <= start <= end <= 3600000:
                            details = {'start_ms': start, 'end_ms': end}
                            break
            event(stage, 'failed' if code else 'passed', reason if code else '', details)

    def run_stage(stage, args):
        state['operation'] = {'id': uuid.uuid4().hex, 'stage': stage, 'args': args}
        event(stage, 'started')
        return resume_stage()

    def resume_stage():
        operation = state['operation']
        code, checked = execute(operation)
        if checked.get('error') == 'FILM_RUN_BUSY':
            return code, checked
        if code and operation['stage'] in ('captions', 'recheck'):
            checked = {**state['result'], **checked}
        record(code, checked, operation['stage'])
        (job_path.parent / ('.film-render-' + operation['id'] + '.json')).unlink(missing_ok=True)
        return code, checked

    if state.get('operation'):
        code, result = resume_stage()
    elif recheck:
        code, result = run_stage('quality', ['--recheck', str(job_path.parent / job['pending_receipt'])])
    elif state['code'] is None:
        code, result = run_stage('quality', [str(job_path)])
    else:
        code, result = state['code'], state['result']
    repair_policy = job.get('repair_policy') or {}
    for _ in range(2):
        if not code or len(state['repairs']) >= 2:
            break
        codes = failure_codes(result)
        repair = None
        receipt = result.get('pending_receipt')
        if codes and codes <= TRANSIENT and isinstance(receipt, str):
            path = Path(receipt).resolve()
            if job_path.parent in path.parents and path.name == 'preview.mp4.film.json' and path.is_file():
                repair, args = 'recheck', ['--recheck', str(path)]
        elif codes & CAPTION and os.environ.get(RECOVERY_ACTIONS['captions'], '1') != '0':
            revised = caption_repair(job)
            if revised:
                candidate = job_path.with_name('.' + job_path.name + '.caption-repair.json')
                atomic(candidate, revised)
                repair, args = 'captions', [str(candidate)]
        if (repair is None or repair in state['repairs'] or repair_policy.get(repair) is False
                or os.environ.get(RECOVERY_ACTIONS[repair], '1') == '0'):
            break
        state['repairs'].append(repair)
        code, result = run_stage(repair, args)
    return code, {**result, 'diagnostic_events': state['events'][:50], 'run_id': state['run_id']}

def replacement_request(job_path, decision, quoted=None):
    """Prepare one idempotent, quoted opt-in replacement. The MCP host submits it."""
    from automation import atomic

    job = json.loads(job_path.read_text(encoding='utf-8-sig'))
    if (job.get('repair_policy') or {}).get('paid_retake') is not True or decision.get('authorized') is not True:
        return {'status': 'authorization_required'}
    limit = decision.get('remaining_approved_credits')
    index = decision.get('segment_index')
    args = decision.get('arguments')
    if (type(limit) is not int or limit <= 0 or type(index) is not int or index < 0
            or index >= len(job.get('clips', [])) or not isinstance(args, dict)
            or not isinstance(args.get('prompt'), str)
            or decision.get('reason_code') not in ('MEDIA_BLACK', 'FILM_DIALOGUE_MISMATCH', 'S3_NEAR_SILENT')):
        raise ValueError('FILM_REPLACEMENT_INVALID')
    tool = decision.get('tool')
    if tool not in ('animate_image', 'generate_video'):
        raise ValueError('FILM_REPLACEMENT_INVALID')

    state_path = job_path.with_name('.' + job_path.name + '.film-state.json')
    with state_lock(state_path):
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if not state.get('code') or decision['reason_code'] not in failure_codes(state['result']):
            return {'status': 'qualification_required'}
        previous = state.get('replacement')
        options = {key: value for key, value in args.items()
                   if key not in ('client_request_id', 'max_credits', 'automation_run_id', 'quote_only')}
        options['client_request_id'] = 'film-' + state['run_id'] + '-retake-1'
        intent = {'tool': tool, 'arguments': options, 'segment_index': index}
        if previous and previous['intent'] != intent:
            return {'status': 'replacement_already_reserved'}
        if previous and previous.get('limit') is not None:
            if previous['limit'] > limit:
                return {'status': 'budget_blocked'}
            return {'status': 'ready_to_submit', 'tool': tool,
                    'arguments': {**options, 'max_credits': previous['limit']}}
        if quoted is None:
            state['replacement'] = {'intent': intent}
            atomic(state_path, state)
            return {'status': 'quote_required', 'arguments': {'quote_request': {'tool': tool, 'arguments': options}}}
        if not previous or type(quoted) is not int or quoted <= 0 or quoted > limit:
            return {'status': 'budget_blocked'}
        state['replacement'] = {'intent': intent, 'limit': quoted}
        atomic(state_path, state)
        return {'status': 'ready_to_submit', 'tool': tool, 'arguments': {**options, 'max_credits': quoted}}
