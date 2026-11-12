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
from local_state import state_lock
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
    result = subprocess.run([sys.executable, str(ROOT / 'analytics.py'), 'collect'], check=False)
    archive()
    pending = [line for line in MEMORY.read_text(encoding='utf-8').splitlines() if line.lstrip().startswith('- [ ]')]
    (ROOT / 'reminders.txt').write_text('Local pending work / 本机待办\n' + '\n'.join(pending) + '\n', encoding='utf-8')
    print('Read-only maintenance finished. See reminders.txt. No AI session, generation or publication was started.')
    return result.returncode


def doctor() -> int:
    from health import report, display
    result = report()
    display(result)
    return 0 if result['local_ready'] else 2


def install_schedule() -> int:
    command = metrics_command()
    system = platform.system()
    if system == "Windows":
        quoted = " ".join('"%s"' % item for item in command)
        subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", JOB_NAME, "/TR", quoted, "/ST", "10:00"], check=True)
    elif system == "Darwin":
        directory = Path.home() / "Library" / "LaunchAgents"; directory.mkdir(parents=True, exist_ok=True)
        plist = directory / (JOB_NAME + ".plist")
        values = "".join("<string>%s</string>" % item.replace("&", "&amp;") for item in command)
        plist.write_text("<?xml version=\"1.0\" encoding=\"UTF-8\"?><!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\"><plist version=\"1.0\"><dict><key>Label</key><string>%s</string><key>ProgramArguments</key><array>%s</array><key>StartCalendarInterval</key><dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict></dict></plist>" % (JOB_NAME, values), encoding="utf-8")
        subprocess.run(["launchctl", "load", str(plist)], check=True)
    else:
        unit_dir = Path.home() / ".config" / "systemd" / "user"; unit_dir.mkdir(parents=True, exist_ok=True)
        escaped = " ".join('"%s"' % item.replace('"', '\\"') for item in command)
        (unit_dir / (JOB_NAME + ".service")).write_text("[Service]\nType=oneshot\nExecStart=%s\n" % escaped, encoding="utf-8")
        (unit_dir / (JOB_NAME + ".timer")).write_text("[Timer]\nOnCalendar=*-*-* 10:00:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n", encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", JOB_NAME + ".timer"], check=True)
    print("Installed a daily read-only metrics task. It never generates or publishes.")
    return 0


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


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init"); sub.add_parser("verify"); doctor_parser = sub.add_parser("doctor"); doctor_parser.add_argument('--json', action='store_true'); doctor_parser.add_argument('--online', action='store_true'); sub.add_parser("migrate-memory"); sub.add_parser("maintenance"); sub.add_parser("install-schedule"); sub.add_parser("uninstall-schedule")
    archive_parser = sub.add_parser("archive"); archive_parser.add_argument("--max-lines", type=int, default=300); archive_parser.add_argument("--max-chars", type=int, default=15000)
    run_day_parser = sub.add_parser("run-day", description="Run an approved schema_version=1 day plan JSON with date, project_key, rules_version, opening, segments and platforms. Uses --max-credits as the budget cap. Exit 2 if blocked.")
    run_day_parser.add_argument("plan", type=Path)
    run_day_parser.add_argument("--max-credits", required=True, type=int)
    authorization_parser = sub.add_parser("authorization", description="Read the paired project grant. Exit 2 on authorization or installation failure.")
    authorization_parser.add_argument("--install-schedules", action="store_true", help="Register both local jobs after confirming the sample, authorizing and pairing the device")
    sub.add_parser("platform-capabilities", description="Print JSON showing ordinary publishing, unattended scheduling, and receipt verification by platform.")
    week_parser = sub.add_parser("validate-week", description="Validate weekly rotation, opening and supplied platform copy. JSON: {rows: [...], history: [...], shop_profile: {...}, platforms: {...}}. Exit 2 if invalid.")
    week_parser.add_argument("input", type=Path)
    args = parser.parse_args()
    if args.command == "authorization":
        from automation import authorization, install_daily_schedules
        try:
            result = install_daily_schedules() if args.install_schedules else authorization()
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except (RuntimeError, OSError, KeyError) as exc:
            error = str(exc) if args.install_schedules and isinstance(exc, RuntimeError) else 'AUTOMATION_AUTHORIZATION_UNAVAILABLE'
            print(json.dumps({'status': 'unavailable', 'error': error}, ensure_ascii=False))
            return 2
    if args.command == "platform-capabilities":
        from publish.dispatch import PLATFORMS
        print(json.dumps({platform: {
            'publisher_available': True,
            'unattended': 'controlled_pilot' if platform == 'youtube' else 'unavailable',
            'scheduled': 'controlled_pilot' if platform == 'youtube' else 'unverified',
            'receipt_verification': 'supported' if platform == 'youtube' else 'requires_platform_validation'
        } for platform in PLATFORMS}))
        return 0
    if args.command == "validate-week":
        from store_editorial import validate_rotation, validate_plan_copy
        try:
            value = json.loads(args.input.read_text(encoding='utf-8-sig'))
            validate_rotation(value['rows'], value.get('history', []), value['shop_profile'])
            validate_plan_copy(value)
            for row in value['rows']:
                validate_plan_copy(row, targets=value.get('platforms', ()))
            print(json.dumps({'status': 'valid', 'days': len(value['rows'])}))
            return 0
        except (ValueError, KeyError, OSError, TypeError) as exc:
            print(json.dumps({'status': 'invalid', 'error': str(exc)}, ensure_ascii=False))
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
