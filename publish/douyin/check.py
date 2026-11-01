# -*- coding: utf-8 -*-
"""Read-only: open Douyin's content management page and print the latest works with status.
Clicks nothing.

    python check.py [--profile DIR]

Use it after publish.py stopped with an error, to find out whether the video was posted
anyway (an abort does not prove that nothing was posted).
"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402

jobfile.setup_console()
MANAGE = "https://creator.douyin.com/creator-micro/content/manage"


def main():
    _, _, opt = jobfile.parse_args(sys.argv[1:], options=("--profile",))
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="zh-CN")
        try:
            pg.goto(MANAGE, wait_until="domcontentloaded", timeout=120000)
            pg.wait_for_timeout(15000)                      # generous wait for slow machines
            body = pg.inner_text("body")
            i = body.find(u"全部作品")                       # "all works" tab label
            print(body[i if i >= 0 else 0:][:1800])
            browser.shot(pg, os.path.join(HERE, "_logs"), "manage", full_page=True)
        finally:
            ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
