# -*- coding: utf-8 -*-
"""ThinkNova 工具包本地维护命令。不会读取 MCP Token、不会生成或发布内容。"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import importlib.util
import re
from datetime import datetime
from pathlib import Path
from local_state import LocalStateBusy, state_lock
from file_integrity import manifest_mismatches

ROOT = Path(__file__).resolve().parent
MEMORY = ROOT / "memory.md"
TEMPLATE = ROOT / "memory.template.md"
ARCHIVE = ROOT / "memory_archive"
MANIFEST = ROOT / "manifest.json"
JOB_NAME = "thinknova-toolkit-metrics"


def init() -> int:
    with state_lock(MEMORY): return _init()


def _init() -> int:
    if MEMORY.exists():
        print("memory.md already exists; it was not changed.")
        return 0
    shutil.copyfile(TEMPLATE, MEMORY)
    print("Created memory.md from memory.template.md.")
    return 0


def archive(max_lines: int = 300, max_chars: int = 15000) -> int:
    if not MEMORY.exists(): return init()
    with state_lock(MEMORY): return _archive(max_lines, max_chars)


def _archive(max_lines: int = 300, max_chars: int = 15000) -> int:
    if not MEMORY.exists():
        return init()
    text = MEMORY.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) <= max_lines and len(text) <= max_chars:
        print("memory.md is within the archive threshold.")
        return 0
    marker = "## 历史事件"
    keep_from = text.find(marker)
    ARCHIVE.mkdir(exist_ok=True)
    target = ARCHIVE / ("memory_%s.md" % datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    with target.open('x', encoding='utf-8') as stream: stream.write(text)
    if keep_from < 0:
        print("Legacy memory snapshot saved to %s; content preserved in full. Add a history section before automatic compaction." % target)
        return 0
    protected = text[:keep_from]
    history = text[keep_from + len(marker):].splitlines()
    updated = protected + marker + "\n\n> 完整历史快照：memory_archive/" + target.name + "\n" + "\n".join(history[-60:]) + "\n"
    temporary = MEMORY.with_name('.memory.md.tmp')
    temporary.write_text(updated, encoding='utf-8')
    temporary.replace(MEMORY)
    print("Archived history to %s; all active sections were retained." % target)
    return 0


def migrate_memory() -> int:
    if not MEMORY.exists(): return init()
    with state_lock(MEMORY):
        original = MEMORY.read_text(encoding='utf-8')
        template = TEMPLATE.read_text(encoding='utf-8')
        sections = re.findall(r'(?ms)^## [^\n]+\n.*?(?=^## |\Z)', template)
        missing = [section.rstrip() for section in sections if section.splitlines()[0] not in original.splitlines() and not section.startswith('## 历史事件\n')]
        if not missing and '## 历史事件' in original: return 0
        ARCHIVE.mkdir(exist_ok=True)
        backup = ARCHIVE / ('memory_migration_%s.md' % datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        with backup.open('x', encoding='utf-8') as stream: stream.write(original)
        before, marker, after = original.partition('## 历史事件')
        updated = before.rstrip() + '\n\n' + '\n\n'.join(missing) + '\n\n## 历史事件' + after
        temporary = MEMORY.with_name('.memory.md.tmp')
        temporary.write_text(updated.rstrip() + '\n', encoding='utf-8')
        temporary.replace(MEMORY)
        print('Memory migration added missing sections only; prior content is retained and backed up in %s.' % backup)
    return 0


def verify() -> int:
    if not MANIFEST.exists():
        print("manifest.json is unavailable; download a fresh toolkit package through MCP.", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = manifest_mismatches(ROOT, manifest)
    if bad:
        print("Toolkit verification failed: " + ", ".join(bad), file=sys.stderr)
        return 2
    print("Toolkit verification passed for version %s." % manifest.get("version", "unknown"))
    return 0


def metrics_command() -> list[str]:
    return [sys.executable, str(ROOT / "toolkit.py"), "maintenance"]


def maintenance() -> int:
    init()
    archive()
    pending = [line for line in MEMORY.read_text(encoding='utf-8').splitlines() if line.lstrip().startswith('- [ ]')]
    (ROOT / 'reminders.txt').write_text('Local pending work / 本机待办\n' + '\n'.join(pending) + '\n', encoding='utf-8')
    print('Read-only maintenance finished. See reminders.txt. No AI session, generation or publication was started.')
    return 0


def doctor() -> int:
    from health import report, display
    result = report()
    display(result)
    return 0 if result['local_ready'] else 2


def install_schedule() -> int:
    from delivery_boundary import handoff, SCHEDULING_MOVED
    print(json.dumps(handoff(SCHEDULING_MOVED),ensure_ascii=False))
    return 2


def uninstall_schedule() -> int:
    system = platform.system()
    if system == "Windows":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", JOB_NAME], check=False)
    elif system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / (JOB_NAME + ".plist")
        subprocess.run(["launchctl", "unload", str(plist)], check=False)
        plist.unlink(missing_ok=True)
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", JOB_NAME + ".timer"], check=False)
        for suffix in (".timer", ".service"):
            (Path.home() / ".config" / "systemd" / "user" / (JOB_NAME + suffix)).unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print("Removed the local metrics task.")
    return 0


def film_review(job_path, recheck=False, existing=False):
    from file_integrity import sha256
    from automation import atomic
    from publish.dispatch import PLATFORMS
    job_path = job_path.resolve()
    job = json.loads(job_path.read_text(encoding='utf-8-sig'))
    from quality_policy import check_film_audio_inputs
    check_film_audio_inputs({**job, 'film': True})
    variants = job.get('platforms') or {}
    review = {}
    copy_pending = []
    if not isinstance(variants, dict):
        copy_pending.append('unknown')
        variants = {}
    for platform_name, copy in variants.items():
        if platform_name not in PLATFORMS or not isinstance(copy, dict):
            copy_pending.append(platform_name)
            continue
        title = copy.get('title')
        body = copy.get('description') or copy.get('caption') or copy.get('body')
        tags = copy.get('tags', [])
        if (not all(isinstance(value, str) and value.strip() for value in (title, body))
                or not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
            copy_pending.append(platform_name)
            continue
        review[platform_name] = {
            'title': title, 'description': body, 'tags': tags,
            'target_account': copy.get('target_account') or copy.get('expected_channel_id'),
            'publish_time': copy.get('publishAt') or copy.get('schedule'),
            'status': 'platform_rules_pending' if copy.get('platform_rules_status') == 'draft' else 'platform_review_required',
        }
    from film_recovery import delivery_context, render_film
    if existing:
        video = (job_path.parent / job['out']).resolve()
        proof_path = Path(str(video) + '.film.json')
        sheet = video.with_name(video.stem + '_sheet.jpg')
        result = {'output': str(video), 'film_receipt': str(proof_path),
                  'contact_sheet': str(sheet) if sheet.is_file() else None}
    else:
        code, result = render_film(ROOT, job_path, job, recheck)
        if code or result.get('machine_check') != 'pass' or not result.get('film_receipt'):
            return {**result, 'status': 'blocked',
                    'delivery_status': 'preview_available' if result.get('preview') else 'technical_fix_required'}
    video = Path(result['output'])
    if not video.is_file() or not Path(result['film_receipt']).is_file():
        raise ValueError('FILM_REVIEW_OUTPUT_OR_RECEIPT_MISSING')
    receipt = json.loads(Path(result['film_receipt']).read_text(encoding='utf-8'))
    digest = sha256(video)
    if receipt.get('machine_check') != 'pass' or receipt.get('sha256') != digest:
        raise ValueError('FILM_REVIEW_RECEIPT_INVALID')
    if existing:
        result['run_id'], result['diagnostic_events'] = delivery_context(job_path, digest)
    supplied_cover = job.get('cover')
    cover = job_path.parent / supplied_cover if isinstance(supplied_cover, str) else None
    if cover is None or not cover.is_file():
        cover = video.with_name(video.stem + '.' + digest[:12] + '.cover.jpg')
        ff = shutil.which('ffmpeg')
        if ff and not cover.is_file():
            try:
                subprocess.run([ff, '-nostdin', '-v', 'error', '-n', '-i', str(video),
                                '-frames:v', '1', str(cover)], capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                pass
    speech_warnings = [item for item in receipt.get('warnings', []) if isinstance(item, dict)
                       and item.get('code') in {'SPEECH_CHECK_PENDING', 'FILM_DIALOGUE_REVIEW_REQUIRED',
                                                'FILM_CAPTION_ALIGNMENT_PENDING'}]
    speech = receipt.get('speech_status', 'unknown')
    package = {'status': 'awaiting_review', 'delivery_status': 'delivered', 'machine_check': 'pass',
               'publication_status': 'copy_required' if copy_pending or not review else 'authorization_and_review_pending',
               'review_requirements': {'speech_status': speech, 'speech_items': speech_warnings,
                                       'visual_review': 'pending', 'copy_required_for': copy_pending},
               'film_receipt': str(Path(result['film_receipt'])), 'video': str(video), 'sha256': digest,
               'cover': str(cover) if cover.is_file() else None,
               'contact_sheet': result.get('contact_sheet'), 'platforms': review, 'run_id': result['run_id'], 'project_key': job.get('project_key')}
    output = video.with_name(video.stem + '.review-package.json')
    if 'edit_timeline' in result:
        package['edit_timeline'] = result['edit_timeline']
    if 'native_dialogue' in result:
        package['native_dialogue'] = result['native_dialogue']
    atomic(output, package)
    return {**package, 'review_package': str(output), 'diagnostic_events': result.get('diagnostic_events', []), 'run_id': result['run_id']}


def prepare_reference(source: Path, output: Path, min_edge: int = 256, max_edge: int = 5760) -> dict:
    """Prepare a derived image without modifying or uploading the original."""
    from io import BytesIO
    from PIL import Image, ImageOps

    formats = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}
    max_bytes = 10 * 1024 * 1024
    if not 1 <= min_edge <= max_edge <= 5760:
        raise ValueError('INVALID_REFERENCE_EDGE_LIMITS')
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError('REFERENCE_OUTPUT_EXISTS')
    with Image.open(source) as original:
        if original.format not in formats.values() or getattr(original, 'n_frames', 1) != 1:
            raise ValueError('REFERENCE_IMAGE_UNSUPPORTED')
        image = ImageOps.exif_transpose(original)
        width, height = image.size
        result = {'status': 'ready', 'source': str(source.resolve()), 'original_width': width, 'original_height': height}
        if min_edge <= min(width, height) and max(width, height) <= max_edge and source.stat().st_size <= max_bytes:
            return {**result, 'path': str(source.resolve()), 'width': width, 'height': height, 'derived': False}
        if max(width, height) > max_edge:
            raise ValueError('REFERENCE_EDGE_TOO_LARGE')
        if min(width, height) >= min_edge:
            raise ValueError('REFERENCE_UPLOAD_TOO_LARGE')
        size = tuple((edge * min_edge + min(width, height) - 1) // min(width, height) for edge in (width, height))
        if max(size) > max_edge:
            raise ValueError('REFERENCE_ASPECT_RATIO_CANNOT_BE_PRESERVED')
        encoding = formats.get(output.suffix.lower())
        if not encoding:
            raise ValueError('REFERENCE_OUTPUT_FORMAT_INVALID')
        image = image.resize(size, Image.Resampling.LANCZOS)
        if encoding == 'JPEG':
            image = image.convert('RGB')
        buffer = BytesIO()
        image.save(buffer, format=encoding)
        if buffer.tell() > max_bytes:
            raise ValueError('REFERENCE_UPLOAD_TOO_LARGE')
        with output.open('xb') as stream:
            stream.write(buffer.getvalue())
        return {**result, 'path': str(output.resolve()), 'width': size[0], 'height': size[1], 'derived': True}


def main() -> int:
    if sys.argv[1:2] == ['enable-production']:
        from automation import assistant_schedule
        print(json.dumps(assistant_schedule(), ensure_ascii=False))
        return 0
    if len(sys.argv)>1 and (sys.argv[1] in ('install-schedule','enable-youtube') or '--install-schedules' in sys.argv):
        from delivery_boundary import handoff, SCHEDULING_MOVED
        print(json.dumps(handoff(SCHEDULING_MOVED if sys.argv[1] != 'enable-youtube' else 'PUBLICATION_MOVED_TO_ASSISTANT_EGO'),ensure_ascii=False))
        return 2
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init"); sub.add_parser("verify"); doctor_parser = sub.add_parser("doctor"); doctor_parser.add_argument('--json', action='store_true'); doctor_parser.add_argument('--online', action='store_true'); sub.add_parser("migrate-memory"); sub.add_parser("maintenance"); sub.add_parser("uninstall-schedule")
    archive_parser = sub.add_parser("archive"); archive_parser.add_argument("--max-lines", type=int, default=300); archive_parser.add_argument("--max-chars", type=int, default=15000)
    reference_parser = sub.add_parser("prepare-reference", help="Resize an undersized reference image locally without overwriting it")
    reference_parser.add_argument("source", type=Path)
    reference_parser.add_argument("--output", required=True, type=Path)
    reference_parser.add_argument("--min-edge", type=int, default=256)
    reference_parser.add_argument("--max-edge", type=int, default=5760)
    film_events_parser = sub.add_parser("film-events", help="List pending film diagnostics or acknowledge delivered events")
    film_events_parser.add_argument("job", type=Path)
    film_events_parser.add_argument("--ack", action="append", default=[])
    film_events_parser.add_argument("--segment", type=int)
    film_events_parser.add_argument("--record-stage", choices=("preflight", "generation", "download", "assembly", "captions", "quality", "recheck"))
    film_events_parser.add_argument("--outcome", choices=("started", "passed", "failed"))
    film_events_parser.add_argument("--code", default="")
    film_events_parser.add_argument("--task-no")
    replacement_parser = sub.add_parser("film-replacement", help="Prepare one authorized, quoted replacement request")
    replacement_parser.add_argument("job", type=Path)
    replacement_parser.add_argument("decision", type=Path)
    replacement_parser.add_argument("--quoted-credits", type=int)
    handoff_parser = sub.add_parser("publication-handoff", help="Prepare an authorized Ego Lite browser handoff")
    handoff_parser.add_argument("workspace", type=Path)
    handoff_parser.add_argument("plan", type=Path)
    handoff_parser.add_argument("--package", type=Path)
    handoff_parser.add_argument("--platform")
    handoff_parser.add_argument("--observed-account")
    handoff_parser.add_argument("--verified-absent", action="store_true")
    film_preflight_parser = sub.add_parser("film-preflight", help="Test local rendering, captions and speech before creating paid jobs")
    film_preflight_parser.add_argument('job', type=Path, nargs='?', help='Film job path for queuing diagnostic events')
    film_parser = sub.add_parser("film", help="Render and prepare a local film for review")
    film_parser.add_argument("job", type=Path)
    film_mode = film_parser.add_mutually_exclusive_group()
    film_mode.add_argument("--recheck", action="store_true")
    film_mode.add_argument("--existing", action="store_true", help="Package the existing checked output without rendering")
    daily_film_parser = sub.add_parser("daily-film", help="Use today's authorized server store-film plan")
    daily_film_parser.add_argument("--project", required=True)
    daily_film_parser.add_argument("--date", required=True)
    daily_film_parser.add_argument("--work-slot", type=int, choices=range(1, 6), default=1)
    run_day_parser = sub.add_parser("run-day", description="Run an approved schema_version=1 day plan JSON with date, project_key, rules_version, opening, segments and platforms. Uses --max-credits as the budget cap. Exit 2 if blocked.")
    run_day_parser.add_argument("plan", type=Path)
    run_day_parser.add_argument("--max-credits", required=True, type=int)
    authorization_parser = sub.add_parser("authorization", description="Read the paired project grant. Exit 2 on authorization or installation failure.")
    sub.add_parser("assistant-schedule", help="Describe how to schedule production through the existing MCP connection")
    sub.add_parser("platform-capabilities", description="Print JSON showing ordinary publishing, unattended scheduling, and receipt verification by platform.")
    week_parser = sub.add_parser("validate-week", description="Validate weekly rotation, opening and supplied platform copy. JSON: {schema_version: 3, rows: [...], history: [...], shop_profile: {...}, platforms: {...}}. Exit 2 if invalid.")
    week_parser.add_argument("input", type=Path)
    args = parser.parse_args()
    if args.command == "film-preflight":
        from render.preflight import film_preflight
        from film_recovery import film_run_id, pending_events, record_external_event
        job_path = args.job.resolve() if args.job else None
        run_id = None
        if job_path:
            try:
                run_id = film_run_id(job_path)
            except (OSError, ValueError, LocalStateBusy):
                pass
        try:
            result = film_preflight()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            result = {'status': 'blocked', 'stage': 'media', 'error': 'FILM_LOCAL_PREFLIGHT_FAILED'}
        if job_path:
            try:
                if not run_id:
                    raise ValueError('FILM_EVENTS_UNAVAILABLE')
                result['run_id'] = run_id
                if result['status'] != 'ready':
                    record_external_event(ROOT, job_path, 'preflight', 'failed', result['error'])
                result['diagnostic_events'] = pending_events(job_path)
            except (OSError, ValueError, LocalStateBusy):
                result['diagnostic_status'] = 'FILM_EVENTS_UNAVAILABLE'
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "ready" else 2
    if args.command == "prepare-reference":
        try:
            result = prepare_reference(args.source, args.output, args.min_edge, args.max_edge)
        except (OSError, ValueError, ImportError) as exc:
            detail = str(exc)
            result = {'status': 'blocked', 'error': detail if re.fullmatch(r'[A-Z0-9_]+', detail)
                      else 'REFERENCE_IMAGE_PREPARATION_FAILED'}
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'ready' else 2
    if args.command == "film-replacement":
        from browser_receipt import read
        from film_recovery import replacement_request
        from local_state import LocalStateBusy
        try:
            result = replacement_request(args.job.resolve(), read(args.decision), args.quoted_credits)
        except (OSError, ValueError, KeyError, TypeError, LocalStateBusy):
            print('{"status":"blocked","error":"FILM_REPLACEMENT_UNAVAILABLE"}')
            return 2
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "publication-handoff":
        from browser_receipt import read
        from local_state import LocalStateBusy
        from publication_handoff import reserve, schedule_requests
        try:
            plan = read(args.plan)
            result = (reserve(args.workspace.resolve(), args.package.resolve(), plan, args.platform,
                              args.observed_account, args.verified_absent) if args.package
                      else {'reports': schedule_requests(plan)})
        except (OSError, ValueError, KeyError, TypeError, LocalStateBusy):
            print('{"status":"blocked","error":"PUBLICATION_HANDOFF_UNAVAILABLE"}')
            return 2
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "film-events":
        from film_recovery import film_run_id, pending_events, record_external_event
        from local_state import LocalStateBusy
        try:
            if args.record_stage:
                record_external_event(ROOT, args.job.resolve(), args.record_stage, args.outcome,
                                      args.code, args.task_no, segment=args.segment)
            events = pending_events(args.job.resolve(), set(args.ack))
            print(json.dumps({'run_id': film_run_id(args.job.resolve()), 'events': events}, ensure_ascii=False))
            return 0
        except (OSError, ValueError, LocalStateBusy):
            print('{"error":"FILM_EVENTS_UNAVAILABLE"}')
            return 2
    if args.command == "film":
        try:
            result = film_review(args.job, args.recheck, args.existing)
        except LocalStateBusy:
            result = {'status': 'blocked', 'error': 'FILM_RUN_BUSY'}
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
            result = {'status': 'blocked', 'delivery_status': 'technical_fix_required',
                      'error': str(exc) if isinstance(exc, ValueError) else 'FILM_REVIEW_PREPARATION_FAILED'}
        from film_recovery import film_run_id, pending_events, record_external_event
        job_path = args.job.resolve()
        try:
            result['run_id'] = film_run_id(job_path)
            if result.get('delivery_status') == 'delivered':
                record_external_event(ROOT, job_path, 'delivery', 'passed', 'FILM_DELIVERED', fingerprint=result['sha256'])
            elif not any(event['outcome'] == 'failed' for event in result.get('diagnostic_events', [])):
                code = str(result.get('error', '')).split(':', 1)[0]
                safe_code = code if re.fullmatch(r'[A-Z0-9_]{2,64}', code) else 'FILM_REVIEW_PREPARATION_FAILED'
                record_external_event(ROOT, job_path, 'recheck' if args.recheck else 'quality', 'failed', safe_code)
            result['diagnostic_events'] = pending_events(job_path)
        except (OSError, ValueError, LocalStateBusy):
            result['diagnostic_status'] = 'FILM_EVENTS_UNAVAILABLE'
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'awaiting_review' else 2
    if args.command == "assistant-schedule":
        from automation import assistant_schedule
        print(json.dumps(assistant_schedule(), ensure_ascii=False))
        return 0
    if args.command == "authorization":
        from automation import authorization
        try:
            result = authorization()
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except (RuntimeError, OSError, KeyError) as exc:
            error = str(exc) if isinstance(exc, RuntimeError) else 'AUTOMATION_AUTHORIZATION_UNAVAILABLE'
            print(json.dumps({'status': 'unavailable', 'error': error}, ensure_ascii=False))
            return 2
    if args.command == "platform-capabilities":
        from publish.dispatch import PLATFORMS
        print(json.dumps({platform: {
            'publisher_available': False,
            'unattended': 'external_ai_assistant_ego_lite',
            'scheduled': 'customer_ai_assistant',
            'receipt_verification': 'external_platform_readback'
        } for platform in PLATFORMS}))
        return 0
    if args.command == "validate-week":
        from store_editorial import validate_rotation, validate_plan_copy
        try:
            value = json.loads(args.input.read_text(encoding='utf-8-sig'))
            validate_rotation(value['rows'], value.get('history', []), value['shop_profile'], value.get('schema_version', 1))
            validate_plan_copy(value)
            for row in value['rows']:
                validate_plan_copy(row, targets=value.get('platforms', ()))
            print(json.dumps({'status': 'valid', 'days': len(value['rows'])}))
            return 0
        except (ValueError, KeyError, OSError, TypeError) as exc:
            print(json.dumps({'status': 'invalid', 'error': str(exc)}, ensure_ascii=False))
            return 2
    if args.command == "daily-film":
        from automation import daily_film
        try:
            result = daily_film(args.project, args.date, args.work_slot)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get('status') in ('awaiting_review', 'ready_to_publish', 'not_due') else 2
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
            return 2
    if args.command == "run-day":
        from automation import run_day
        try:
            print(json.dumps(run_day(args.plan, args.max_credits), ensure_ascii=False))
            return 0
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
            return 2
    if args.command == "init": return init()
    if args.command == "verify": return verify()
    if args.command == "doctor":
        from health import report, display
        result = report(online=args.online); display(result, args.json)
        return 0 if result['local_ready'] else 2
    if args.command == "archive": return archive(args.max_lines, args.max_chars)
    if args.command == "maintenance": return maintenance()
    if args.command == "migrate-memory": return migrate_memory()
    if args.command == "install-schedule": return install_schedule()
    return uninstall_schedule()


if __name__ == "__main__":
    sys.exit(main())
