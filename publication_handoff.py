"""Prepare and reserve authorized browser publication in the customer workspace."""
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from automation import atomic
from browser_receipt import PLATFORMS, initialize, read
from file_integrity import sha256
from local_state import state_lock


def timestamp(value):
    stamp = datetime.fromisoformat(value)
    if not value.endswith('Z') or stamp.tzinfo is None:
        raise ValueError('PUBLICATION_WINDOW_INVALID')
    return stamp


def schedule_requests(plan):
    project, day = plan['project_key'], plan['local_date']
    date.fromisoformat(day)
    targets = plan['targets']
    if not targets or set(targets) - PLATFORMS:
        raise ValueError('PUBLICATION_PLAN_INVALID')
    requests = []
    for platform, target in targets.items():
        if type(target.get('confirmed')) is not bool:
            raise ValueError('PUBLICATION_AUTHORIZATION_UNKNOWN')
        due, ends = timestamp(target['due_at']), timestamp(target['window_ends_at'])
        if not due < ends:
            raise ValueError('PUBLICATION_WINDOW_INVALID')
        data = {key: target[key] for key in ('target_account', 'confirmed', 'due_at', 'window_ends_at')}
        data.update(project_key=project, local_date=day, platform=platform)
        if plan.get('run_id'):
            data['run_id'] = plan['run_id']
        requests.append({'action': 'schedule', 'data': data})
    return requests


def reserve(workspace, package_path, plan, platform, observed_account, verified_absent=False, now=None):
    requests = {item['data']['platform']: item['data'] for item in schedule_requests(plan)}
    target = requests[platform]
    if not target['confirmed']:
        return {'status': 'authorization_required'}
    if observed_account != target['target_account']:
        return {'status': 'login_required'}
    package = read(package_path)
    if ((package.get('project_key') and package['project_key'] != plan['project_key'])
            or (plan.get('run_id') and package.get('run_id') != plan['run_id'])):
        return {'status': 'publication_scope_conflict'}
    video = Path(package['video'])
    if not video.is_absolute():
        video = package_path.parent / video
    proof_path = Path(str(video) + '.film.json')
    if not video.is_file() or not proof_path.is_file():
        return {'status': 'quality_blocked'}
    proof = read(proof_path)
    digest = sha256(video)
    if proof.get('machine_check') != 'pass' or digest != proof.get('sha256') or digest != package.get('sha256'):
        return {'status': 'quality_blocked'}
    copy = package['platforms'][platform]
    copy_digest = hashlib.sha256(json.dumps(copy, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    approved = plan['targets'][platform].get('approval') or {}
    if approved.get('scope') == 'version':
        permitted = approved.get('film_sha256') == digest and approved.get('copy_sha256') == copy_digest
    elif approved.get('scope') == 'standing':
        permitted = all(approved.get(key) is value for key, value in
                        [('first_film_reviewed', True), ('requires_per_version_review', False),
                         ('content_review_pending', False)])
    else:
        permitted = False
    if proof.get('speech_status') in ('unknown', 'degraded') and approved.get('scope') != 'version':
        permitted = False
    if not permitted:
        return {'status': 'awaiting_review', 'film_sha256': digest, 'copy_sha256': copy_digest}
    if copy.get('target_account') and copy['target_account'] != observed_account:
        return {'status': 'authorization_required'}
    now = now or datetime.now(timezone.utc)
    slot = hashlib.sha256(json.dumps([plan['project_key'], plan['local_date'], platform, observed_account],
                                    ensure_ascii=False).encode()).hexdigest()
    directory = workspace / '.thinknova-publication' / slot
    directory.mkdir(parents=True, exist_ok=True)
    claim_path = directory / 'claim.json'
    with state_lock(claim_path):
        grant = read(claim_path) if claim_path.exists() else {}
        previous_receipt = directory / (grant.get('film_sha256', digest) + '.json')
        previous = read(previous_receipt)['platforms'][platform] if previous_receipt.is_file() else {}
        if previous.get('status') == 'published':
            return {'status': 'published', 'reason_code': 'ALREADY_PUBLISHED'}
        if previous.get('status') in ('crop_incorrect', 'skipped'):
            return {'status': previous['status']}
        if grant and (not verified_absent or grant.get('retried')):
            return {'status': 'submitted_unverified', 'receipt': str(previous_receipt)}
        if not timestamp(target['due_at']) <= now < timestamp(target['window_ends_at']):
            return {'status': 'outside_window'}
        receipt = directory / (digest + '.json')
        value = initialize(receipt, video, {'project_key': plan['project_key'], 'local_date': plan['local_date'],
                                           'targets': {platform: observed_account}})
        atomic(claim_path, {'film_sha256': digest, 'retried': bool(grant), 'claimed_at': now.isoformat()})
        return {'status': 'ready_to_publish', 'receipt': str(receipt), 'video': str(video),
                'film_sha256': digest, 'copy_sha256': copy_digest, 'retried': bool(grant),
                'upload_report': {'action': 'receipt', 'data': value}}
