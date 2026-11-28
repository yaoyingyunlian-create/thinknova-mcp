"""Prepare and reserve authorized browser publication in the customer workspace."""
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from automation import atomic
from browser_receipt import PLATFORMS, initialize, read
from file_integrity import sha256
from local_state import state_lock


class PublicationInputError(ValueError):
    def __init__(self, code, field):
        super().__init__(code)
        self.field = field


def read_input(path, field):
    prefix = 'PUBLICATION_PLAN' if field == 'plan' else 'PUBLICATION_PACKAGE'
    try:
        value = read(path)
    except FileNotFoundError as exc:
        raise PublicationInputError(prefix + '_MISSING', field) from exc
    except OSError as exc:
        raise PublicationInputError(prefix + '_UNREADABLE', field) from exc
    except ValueError as exc:
        raise PublicationInputError(prefix + '_INVALID', field) from exc
    if not isinstance(value, dict):
        raise PublicationInputError(prefix + '_INVALID', field)
    return value


def timestamp(value, field):
    try:
        if isinstance(value, str) and value.endswith('Z'):
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is not None:
                return stamp
    except ValueError:
        pass
    raise PublicationInputError('PUBLICATION_WINDOW_INVALID', field)


def schedule_requests(plan):
    project, day, targets = (plan.get(key) for key in ('project_key', 'local_date', 'targets'))
    if not isinstance(project, str) or not project.strip():
        raise PublicationInputError('PUBLICATION_PLAN_INVALID', 'project_key')
    try:
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError as exc:
        raise PublicationInputError('PUBLICATION_PLAN_INVALID', 'local_date') from exc
    if not isinstance(targets, dict) or not targets or set(targets) - PLATFORMS:
        raise PublicationInputError('PUBLICATION_PLAN_INVALID', 'targets')
    requests = []
    for platform, target in targets.items():
        field = f'targets.{platform}'
        if not isinstance(target, dict):
            raise PublicationInputError('PUBLICATION_PLAN_INVALID', field)
        if not isinstance(target.get('target_account'), str) or not target['target_account'].strip():
            raise PublicationInputError('PUBLICATION_PLAN_INVALID', field + '.target_account')
        if type(target.get('confirmed')) is not bool:
            raise PublicationInputError('PUBLICATION_AUTHORIZATION_UNKNOWN', field + '.confirmed')
        due = timestamp(target.get('due_at'), field + '.due_at')
        ends = timestamp(target.get('window_ends_at'), field + '.window_ends_at')
        if not due < ends:
            raise PublicationInputError('PUBLICATION_WINDOW_INVALID', field + '.window_ends_at')
        data = {key: target[key] for key in ('target_account', 'confirmed', 'due_at', 'window_ends_at')}
        data.update(project_key=project, local_date=day, platform=platform)
        if plan.get('run_id'):
            data['run_id'] = plan['run_id']
        requests.append({'action': 'schedule', 'data': data})
    return requests


def reserve(workspace, package_path, plan, platform, observed_account, verified_absent=False, now=None):
    requests = {item['data']['platform']: item['data'] for item in schedule_requests(plan)}
    if not platform or platform not in requests:
        raise PublicationInputError('PUBLICATION_TARGET_NOT_SCHEDULED', 'platform')
    target = requests[platform]
    if not target['confirmed']:
        return {'status': 'authorization_required'}
    if observed_account != target['target_account']:
        return {'status': 'login_required'}
    package = read_input(package_path, 'package')
    if not isinstance(package.get('video'), str) or not package['video'].strip():
        raise PublicationInputError('PUBLICATION_PACKAGE_INVALID', 'package.video')
    if ((package.get('project_key') and package['project_key'] != plan['project_key'])
            or (plan.get('run_id') and package.get('run_id') != plan['run_id'])):
        return {'status': 'publication_scope_conflict'}
    video = Path(package['video'])
    if not video.is_absolute():
        video = package_path.parent / video
    proof_path = Path(str(video) + '.film.json')
    if not video.is_file() or not proof_path.is_file():
        return {'status': 'quality_blocked'}
    try:
        proof = read(proof_path)
        digest = sha256(video)
    except (ValueError, OSError):
        return {'status': 'quality_blocked', 'reason_code': 'PUBLICATION_PROOF_UNREADABLE'}
    if not isinstance(proof, dict):
        return {'status': 'quality_blocked', 'reason_code': 'PUBLICATION_PROOF_UNREADABLE'}
    if proof.get('machine_check') != 'pass' or digest != proof.get('sha256') or digest != package.get('sha256'):
        return {'status': 'quality_blocked'}
    copy = (package.get('platforms') or {}).get(platform)
    if not isinstance(copy, dict):
        return {'status': 'copy_required'}
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
    if not permitted:
        return {'status': 'awaiting_review', 'film_sha256': digest, 'copy_sha256': copy_digest,
                'reason_code': 'PUBLICATION_REVIEW_REQUIRED'}
    speech_pending = proof.get('speech_status', 'unknown') in ('unknown', 'degraded') or any(
        isinstance(item, dict) and item.get('code') == 'FILM_DIALOGUE_REVIEW_REQUIRED'
        for item in proof.get('warnings', [])
    )
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
        if not timestamp(target['due_at'], 'due_at') <= now < timestamp(target['window_ends_at'], 'window_ends_at'):
            return {'status': 'outside_window'}
        receipt = directory / (digest + '.json')
        value = initialize(receipt, video, {'project_key': plan['project_key'], 'local_date': plan['local_date'],
                                           'targets': {platform: observed_account}})
        atomic(claim_path, {'film_sha256': digest, 'retried': bool(grant), 'claimed_at': now.isoformat()})
        return {'status': 'ready_to_publish', 'receipt': str(receipt), 'video': str(video),
                'film_sha256': digest, 'copy_sha256': copy_digest, 'retried': bool(grant),
                **({'warnings': ['SPEECH_VERIFICATION_PENDING']} if speech_pending else {}),
                'upload_report': {'action': 'receipt', 'data': value}}
