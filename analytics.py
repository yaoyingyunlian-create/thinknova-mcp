# -*- coding: utf-8 -*-
"""Read-only 24/48 hour performance collection for YouTube and TikTok.

Usage: python analytics.py register --platform youtube --content-id VIDEO_ID --published-at 2026-11-01T10:00:00+08:00
       python analytics.py collect
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = ROOT / "analytics_targets.json"
MEMORY = ROOT / "memory.md"


def load_targets() -> list[dict]:
    if not TARGETS.exists(): return []
    return json.loads(TARGETS.read_text(encoding="utf-8"))


def save_targets(items: list[dict]) -> None:
    TARGETS.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_memory(line: str) -> None:
    if not MEMORY.exists():
        print("memory.md is missing; run python toolkit.py init first.", file=sys.stderr)
        return
    with MEMORY.open("a", encoding="utf-8") as stream:
        stream.write("\n- " + line + "\n")


def youtube_metrics(content_id: str) -> dict:
    sys.path.insert(0, str(ROOT / "publish" / "youtube"))
    import yt_common
    from googleapiclient.discovery import build
    yt = yt_common.youtube(interactive=False)
    item = (yt.videos().list(part="statistics", id=content_id).execute().get("items") or [None])[0]
    if not item: raise RuntimeError("YouTube video was not found or is unavailable to this account.")
    return {"views": item["statistics"].get("viewCount"), "likes": item["statistics"].get("likeCount"), "comments": item["statistics"].get("commentCount")}


def tiktok_metrics(url: str) -> dict:
    if not url.startswith("https://"):
        raise RuntimeError("TikTok collection requires the published https URL.")
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(ROOT / "publish"))
    from common import browser as browser_helper
    with sync_playwright() as playwright:
        profile = ROOT / "publish" / "tiktok" / "_profile"
        if not profile.exists(): raise RuntimeError("TikTok local login profile is missing; run publish/tiktok/login.py first.")
        browser, page = browser_helper.launch(playwright, str(profile), locale="en-US")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = page.locator("body").inner_text()
        finally:
            browser.close()
    # TikTok's page is frequently localized; keep the raw visible counters instead of guessing a schema.
    return {"visible_summary": " ".join(text.split())[:800]}


def collect() -> int:
    now = datetime.now(timezone.utc)
    changed = False
    items = load_targets()
    for item in items:
        published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        age = now - published.astimezone(timezone.utc)
        samples = item.setdefault("collected_samples", {})
        due = "24h" if timedelta(hours=24) <= age < timedelta(hours=48) and "24h" not in samples else "48h" if age >= timedelta(hours=48) and "48h" not in samples else ""
        if not due: continue
        try:
            data = youtube_metrics(item["content_id"]) if item["platform"] == "youtube" else tiktok_metrics(item["content_url"])
            samples[due] = {"collected_at": now.isoformat(), "metrics": data}
            append_memory("%s %s 数据：%s" % (item["platform"], due, json.dumps(data, ensure_ascii=False)))
        except Exception as exc:
            item["last_error"] = str(exc)[:300]; item["last_attempt_at"] = now.isoformat()
            append_memory("%s %s 数据采集失败：%s（未重发内容）" % (item["platform"], due, item["last_error"]))
        changed = True
    if changed: save_targets(items)
    return 0


def register(args: argparse.Namespace) -> int:
    if args.platform == "tiktok" and not args.content_url:
        raise SystemExit("TikTok requires --content-url.")
    published = datetime.fromisoformat(args.published_at.replace("Z", "+00:00")).isoformat()
    items = load_targets()
    items.append({"platform": args.platform, "content_id": args.content_id, "content_url": args.content_url or "", "published_at": published})
    save_targets(items); print("Registered read-only 24/48 hour collection target.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register"); reg.add_argument("--platform", choices=["youtube", "tiktok"], required=True); reg.add_argument("--content-id", required=True); reg.add_argument("--content-url"); reg.add_argument("--published-at", required=True)
    sub.add_parser("collect"); args = parser.parse_args()
    return collect() if args.command == "collect" else register(args)


if __name__ == "__main__": sys.exit(main())
