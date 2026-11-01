# -*- coding: utf-8 -*-
"""ThinkNova 工具包本地维护命令。不会读取 MCP Token、不会生成或发布内容。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import importlib.util
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEMORY = ROOT / "memory.md"
TEMPLATE = ROOT / "memory.template.md"
ARCHIVE = ROOT / "memory_archive"
MANIFEST = ROOT / "manifest.json"
JOB_NAME = "thinknova-toolkit-metrics"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def init() -> int:
    if MEMORY.exists():
        print("memory.md already exists; it was not changed.")
        return 0
    shutil.copyfile(TEMPLATE, MEMORY)
    print("Created memory.md from memory.template.md.")
    return 0


def archive(max_lines: int = 300, max_chars: int = 15000) -> int:
    if not MEMORY.exists():
        return init()
    text = MEMORY.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) <= max_lines and len(text) <= max_chars:
        print("memory.md is within the archive threshold.")
        return 0
    marker = "## 偏好、拒绝与本机问题"
    keep_from = text.find(marker)
    retained = text[keep_from:] if keep_from >= 0 else "\n".join(lines[-80:])
    ARCHIVE.mkdir(exist_ok=True)
    target = ARCHIVE / ("memory_%s.md" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    target.write_text(text, encoding="utf-8")
    MEMORY.write_text("# ThinkNova 本地运营记忆\n\n> 已归档历史：%s\n\n%s\n" % (target.name, retained), encoding="utf-8")
    print("Archived memory to %s without deleting the current preference section." % target)
    return 0


def verify() -> int:
    if not MANIFEST.exists():
        print("manifest.json is unavailable; download a fresh toolkit package through MCP.", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = []
    for entry in manifest.get("files", []):
        path = ROOT / entry.get("path", "")
        if not path.is_file() or sha256(path) != entry.get("sha256"):
            bad.append(str(entry.get("path", "")))
    if bad:
        print("Toolkit verification failed: " + ", ".join(bad), file=sys.stderr)
        return 2
    print("Toolkit verification passed for version %s." % manifest.get("version", "unknown"))
    return 0


def metrics_command() -> list[str]:
    return [sys.executable, str(ROOT / "analytics.py"), "collect"]


def doctor() -> int:
    checks = {"Python >=3.10": sys.version_info >= (3, 10),
              "ffmpeg": shutil.which("ffmpeg") is not None, "ffprobe": shutil.which("ffprobe") is not None,
              "Node.js >=18": False, "playwright": importlib.util.find_spec("playwright") is not None}
    node = shutil.which("node")
    if node:
        version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
        checks["Node.js >=18"] = int(version.lstrip("v").split(".")[0]) >= 18
    for name, ok in checks.items(): print(("OK " if ok else "MISSING ") + name)
    for name in ("AGENTS.md", "memory.template.md", "requirements.txt", "analytics.py", "render/check.py"):
        checks[name] = (ROOT / name).is_file()
        print(("OK " if checks[name] else "MISSING ") + name)
    if checks["playwright"]:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            checks["Chromium"] = Path(p.chromium.executable_path).is_file()
            print(("OK " if checks["Chromium"] else "MISSING ") + "Chromium")
    return 0 if all(checks.values()) else 2


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
    sub.add_parser("init"); sub.add_parser("verify"); sub.add_parser("doctor"); sub.add_parser("install-schedule"); sub.add_parser("uninstall-schedule")
    archive_parser = sub.add_parser("archive"); archive_parser.add_argument("--max-lines", type=int, default=300); archive_parser.add_argument("--max-chars", type=int, default=15000)
    args = parser.parse_args()
    if args.command == "init": return init()
    if args.command == "verify": return verify()
    if args.command == "doctor": return doctor()
    if args.command == "archive": return archive(args.max_lines, args.max_chars)
    if args.command == "install-schedule": return install_schedule()
    return uninstall_schedule()


if __name__ == "__main__":
    sys.exit(main())
