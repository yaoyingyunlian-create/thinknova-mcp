"""Persist and report browser publication evidence."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from automation import atomic
from local_state import state_lock
from render.assemble import Stop, file_digest, tool

PLATFORMS = {'instagram', 'tiktok', 'facebook', 'youtube', 'xiaohongshu', 'douyin', 'x', 'linkedin'}
STATES = {'pending', 'submitted', 'published', 'crop_incorrect', 'login_required', 'failed',
          'outcome_unknown', 'skipped'}
FIELDS = {'status', 'post_url', 'published_at', 'portrait', 'sound', 'subject_visible', 'failure_reason', 'retried'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def check_media(film):
    try:
        info = subprocess.run([tool('ffprobe'), '-v', 'error', '-show_streams',
                               '-of', 'json', str(film)], capture_output=True, check=True, timeout=30)
        streams = json.loads(info.stdout)['streams']
    except (OSError, Stop, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise ValueError('BROWSER_PUBLICATION_MEDIA_UNREADABLE') from exc
    video = next((stream for stream in streams if stream.get('codec_type') == 'video'), {})
    width, height = video.get('width', 0), video.get('height', 0)
    if width < 720 or height < 1280 or width * 16 != height * 9:
        raise ValueError('BROWSER_PUBLICATION_PORTRAIT_REQUIRED')
    if not any(stream.get('codec_type') == 'audio' for stream in streams):
        raise ValueError('BROWSER_PUBLICATION_AUDIO_REQUIRED')


def initialize(path, film, plan):
    digest = file_digest(film)
    proof = read(Path(str(film) + '.film.json'))
    if proof.get('machine_check') != 'pass' or proof.get('sha256') != digest:
        raise ValueError('BROWSER_PUBLICATION_FILM_CHECK_REQUIRED')
    check_media(film)
    local_date = plan['local_date']
    if date.fromisoformat(local_date).isoformat() != local_date:
        raise ValueError('BROWSER_PUBLICATION_DATE_INVALID')
    targets = plan['targets']
    if not isinstance(targets, dict) or not targets or set(targets) - PLATFORMS or not all(
            isinstance(account, str) and re.fullmatch(r'[@. :\w-]{1,100}', account)
            and account.strip() for account in targets.values()):
        raise ValueError('BROWSER_PUBLICATION_TARGET_INVALID')
    project = plan['project_key']
    if not isinstance(project, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,47}', project):
        raise ValueError('BROWSER_PUBLICATION_PROJECT_INVALID')
    value = {'project_key': project, 'local_date': local_date, 'film_sha256': digest, 'revision': 1,
             'platforms': {name: {'target_account': account, 'status': 'pending'} for name, account in targets.items()}}
    if proof.get('quality_policy_version') in ('58', 'native_dialogue_v1'):
        codes = [item['code'] for item in proof.get('warnings', [])
                 if isinstance(item, dict) and re.fullmatch(r'[A-Za-z0-9_]{1,64}', item.get('code', ''))]
        for row in value['platforms'].values():
            row['quality'] = {'version':proof['quality_policy_version'], 'speech_status':proof.get('speech_status', 'unknown'), 'warning_codes':list(dict.fromkeys(codes))[:32]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with state_lock(path):
        if path.exists():
            existing = read(path)
            prior_targets = {name: row['target_account'] for name, row in existing['platforms'].items()}
            if any(existing[key] != value[key] for key in ('project_key', 'local_date', 'film_sha256')) or prior_targets != targets:
                raise ValueError('BROWSER_PUBLICATION_RECEIPT_CONFLICT')
            return existing
        atomic(path, value)
    return value


def record(path, platform, event):
    with state_lock(path):
        value = read(path)
        rows = value['platforms']
        if platform not in rows or not isinstance(event, dict) or set(event) - FIELDS or event.get('status') not in STATES:
            raise ValueError('BROWSER_PUBLICATION_RESULT_INVALID')
        if event['status'] == 'published' and (not all(event.get(key) is True for key in (
                'portrait', 'sound', 'subject_visible')) or not event.get('post_url') or not event.get('published_at')):
            raise ValueError('BROWSER_PUBLICATION_EVIDENCE_REQUIRED')
        reason = event.get('failure_reason')
        if reason is not None and (not isinstance(reason, str) or len(reason.encode('utf-8')) > 600
                                   or re.search(r'https?:|bearer\s|(?:token|cookie|password)\s*[:=]|[\r\n]', reason, re.I)):
            raise ValueError('BROWSER_PUBLICATION_REASON_INVALID')
        if event['status'] in ('crop_incorrect', 'failed', 'skipped', 'login_required') and not (reason or '').strip():
            raise ValueError('BROWSER_PUBLICATION_REASON_REQUIRED')
        previous = rows[platform]
        current = {'target_account': previous['target_account'], **event}
        if 'quality' in previous:
            current['quality'] = previous['quality']
        if previous['status'] == 'published' and event['status'] not in ('published', 'crop_incorrect'):
            raise ValueError('BROWSER_PUBLICATION_ALREADY_RECORDED')
        if previous.get('retried'):
            current['retried'] = True
        if current == previous:
            return value
        rows[platform] = current
        value['revision'] += 1
        atomic(path, value)
    return value


def sync(value):
    try:
        from automation_client import Client
        from monitoring import TOKEN
        import secure_state
        if not TOKEN.is_file():
            return {'sync': 'local_only', 'reason_code': 'MONITORING_CREDENTIAL_REQUIRED'}
        response, _ = Client(secure_state.load(TOKEN)).post('/mcp/device/browser-publication', value, execution=False)
        data = response.get('data') or {}
        receipt_id = data.get('receipt_id')
        if data.get('accepted') is True and isinstance(receipt_id, str) and re.fullmatch(r'[a-f0-9]{64}', receipt_id):
            return {'sync': 'synced', 'receipt_id': receipt_id}
    except RuntimeError as exc:
        if re.fullmatch(r'DEVICE_HTTP_\d{3}', str(exc)):
            return {'sync': 'queued', 'reason_code': str(exc)}
    except (OSError, ValueError, KeyError):
        pass
    return {'sync': 'queued', 'reason_code': 'BROWSER_PUBLICATION_SYNC_PENDING'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    start = commands.add_parser('init')
    start.add_argument('receipt', type=Path)
    start.add_argument('film', type=Path)
    start.add_argument('plan', type=Path)
    update = commands.add_parser('record')
    update.add_argument('receipt', type=Path)
    update.add_argument('platform', choices=sorted(PLATFORMS))
    update.add_argument('event', type=Path)
    resend = commands.add_parser('sync')
    resend.add_argument('receipt', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'init':
            value = initialize(args.receipt, args.film, read(args.plan))
        elif args.action == 'record':
            value = record(args.receipt, args.platform, read(args.event))
        else:
            value = read(args.receipt)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'Could not record receipt: {exc}\n')
    result = sync(value)
    print(json.dumps({**result, 'receipt': str(args.receipt), 'platforms': value['platforms'], 'upload_report': {'action': 'receipt', 'data': value}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
