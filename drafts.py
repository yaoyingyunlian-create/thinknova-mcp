# -*- coding: utf-8 -*-
"""本地草稿候选清单；不会在平台网页上删除草稿。

AI 助手应先运行 list，把候选项和平台页面链接展示给用户；只有用户明确确认后，才可用
purge --confirm <id> 删除本地候选记录。平台上的草稿仍须由用户在平台页面确认并手动删除。
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "draft_candidates.json"

def load() -> list[dict]:
    return json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []

def save(items: list[dict]) -> None:
    STORE.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    purge = sub.add_parser("purge"); purge.add_argument("--confirm", required=True, help="candidate id explicitly approved by the user")
    args = parser.parse_args(); items = load()
    if args.command == "list":
        print(json.dumps(items, ensure_ascii=False, indent=2)); return 0
    kept = [item for item in items if str(item.get("id")) != args.confirm]
    if len(kept) == len(items): raise SystemExit("No matching local draft candidate; nothing changed.")
    save(kept); print("Removed the local candidate record. Confirm/delete the platform draft manually.")
    return 0

if __name__ == "__main__": raise SystemExit(main())
