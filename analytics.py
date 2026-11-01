# -*- coding: utf-8 -*-
"""Read-only 24/48 hour performance collection for YouTube and TikTok.

Usage: python analytics.py register --platform youtube --content-id VIDEO_ID --published-at 2026-11-01T10:00:00+08:00
       python analytics.py collect
"""
from __future__ import annotations

import argparse
import json
import sys
import re
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from pathlib import Path
from local_state import state_lock

ROOT = Path(__file__).resolve().parent
TARGETS = ROOT / "analytics_targets.json"
MEMORY = ROOT / "memory.md"


def load_targets() -> list[dict]:
    if not TARGETS.exists(): return []
    return json.loads(TARGETS.read_text(encoding="utf-8"))


def save_targets(items: list[dict]) -> None:
    temporary = TARGETS.with_name('.analytics_targets.json.tmp')
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(TARGETS)


def append_memory(line: str) -> None:
    with state_lock(MEMORY): _append_memory(line)


def _append_memory(line: str) -> None:
    if not MEMORY.exists():
        raise RuntimeError("memory.md is missing; run python toolkit.py init first.")
    text = MEMORY.read_text(encoding='utf-8')
    with MEMORY.open("a", encoding="utf-8") as stream:
        if '## 历史事件' not in text: stream.write('\n\n## 历史事件\n')
        stream.write("\n- " + line + "\n")


def youtube_metrics(content_id: str) -> dict:
    sys.path.insert(0, str(ROOT / "publish" / "youtube"))
    import yt_common
    yt = yt_common.youtube(interactive=False)
    item = (yt.videos().list(part="statistics", id=content_id).execute().get("items") or [None])[0]
    if not item: raise RuntimeError("YouTube video was not found or is unavailable to this account.")
    return {"views": item["statistics"].get("viewCount"), "likes": item["statistics"].get("likeCount"), "comments": item["statistics"].get("commentCount")}


def tiktok_metrics(url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.tiktok.com', 'tiktok.com', 'm.tiktok.com') or parsed.username or parsed.password or parsed.port not in (None, 443) or not re.fullmatch(r'/@[^/]+/video/\d+/?', parsed.path):
        raise RuntimeError("TikTok collection requires a published TikTok video URL.")
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(ROOT / "publish"))
    from common import browser as browser_helper
    with sync_playwright() as playwright:
        profile = ROOT / "publish" / "tiktok" / "_profile"
        if not profile.exists(): raise RuntimeError("TikTok local login profile is missing; run publish/tiktok/login.py first.")
        browser, page = browser_helper.launch(playwright, str(profile), locale="en-US")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if urlsplit(page.url).hostname not in ('www.tiktok.com', 'tiktok.com', 'm.tiktok.com') or '/login' in page.url:
                raise RuntimeError('TikTok login or unexpected redirect; user must check the account.')
            metrics = {}
            for field, selector in [('likes', 'like-count'), ('comments', 'comment-count'), ('shares', 'share-count')]:
                counters = page.locator('[data-e2e="%s"]' % selector)
                if counters.count() == 1:
                    value = counters.inner_text().strip()
                    if re.fullmatch(r'[\d.,\s]+[KMBkmb万亿]?', value): metrics[field] = value
            if not metrics: raise RuntimeError('TikTok counters unavailable; login, verification or page change requires inspection. No metrics were recorded.')
        finally:
            browser.close()
    return {'available_counters': metrics, 'units': 'platform_display_text', 'views': None}


def collect() -> int:
    with state_lock(TARGETS): return _collect()


def _collect() -> int:
    now = datetime.now(timezone.utc)
    changed = False
    items = load_targets()
    failed = False
    for item in items:
        published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None: raise RuntimeError('Published time must include a timezone; fix the target record.')
        age = now - published.astimezone(timezone.utc)
        samples = item.setdefault("collected_samples", {})
        due = "24h" if timedelta(hours=24) <= age < timedelta(hours=48) and "24h" not in samples else "48h" if age >= timedelta(hours=48) and "48h" not in samples else ""
        if not due: continue
        try:
            data = youtube_metrics(item["content_id"]) if item["platform"] == "youtube" else tiktok_metrics(item["content_url"])
            append_memory("%s | %s | content_id=%s | %s | published=%s | 数据：%s" % (now.isoformat(), item['platform'], item['content_id'], due, item['published_at'], json.dumps(data, ensure_ascii=False)))
            samples[due] = {"collected_at": now.isoformat(), "metrics": data}
            if due == '48h' and '24h' not in samples: item['missed_24h'] = True
        except Exception as exc:
            item["last_error"] = str(exc)[:300]; item["last_attempt_at"] = now.isoformat()
            failed = True
            append_memory("%s | %s | content_id=%s | %s 数据采集失败：%s（未重发内容）" % (now.isoformat(), item['platform'], item['content_id'], due, item['last_error']))
        changed = True
    if changed: save_targets(items)
    return 2 if failed else 0


def register(args: argparse.Namespace) -> int:
    with state_lock(TARGETS): return _register(args)


def _register(args: argparse.Namespace) -> int:
    if args.platform == "tiktok" and not args.content_url:
        raise SystemExit("TikTok requires --content-url.")
    moment = datetime.fromisoformat(args.published_at.replace("Z", "+00:00"))
    if moment.tzinfo is None: raise SystemExit('published-at must include a UTC offset or Z.')
    published = moment.isoformat()
    items = load_targets()
    if any(item['platform'] == args.platform and item['content_id'] == args.content_id for item in items):
        print('Target already registered; retained its collected samples.'); return 0
    items.append({"platform": args.platform, "content_id": args.content_id, "content_url": args.content_url or "", "published_at": published})
    save_targets(items); print("Registered read-only 24/48 hour collection target.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register"); reg.add_argument("--platform", choices=["youtube", "tiktok"], required=True); reg.add_argument("--content-id", required=True); reg.add_argument("--content-url"); reg.add_argument("--published-at", required=True)
    sub.add_parser("collect"); args = parser.parse_args()
    return collect() if args.command == "collect" else register(args)


if __name__ == "__main__": sys.exit(main())
