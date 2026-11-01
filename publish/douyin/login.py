# -*- coding: utf-8 -*-
"""Douyin login - YOU log in once by hand; publish.py then reuses this browser profile.

    python login.py
    python login.py --profile DIR

Opens the Douyin Creator Center upload page in a separate browser profile and waits while
you log in yourself (scanning the QR code with the Douyin app is quickest). It checks every
5 seconds and stops by itself once you are logged in (max 6 minutes).

The script never types passwords and never handles captchas.
The profile folder (default ./_profile) contains your session: keep it private, never share
or commit it. Delete it to log out.
"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402

jobfile.setup_console()
UPLOAD = "https://creator.douyin.com/creator-micro/content/upload"
# Chinese UI text visible only when logged in: upload video / click to upload / publish video / drag video here
LOGGED_IN = [u"上传视频", u"点击上传", u"发布视频", u"拖拽视频到此"]


def main():
    _, _, opt = jobfile.parse_args(sys.argv[1:], options=("--profile",))
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="zh-CN")
        pg.goto(UPLOAD, wait_until="domcontentloaded", timeout=120000)
        print("\nBrowser is open on the Douyin Creator Center.")
        print("-> Log in yourself in that window (QR code with the Douyin app is quickest).")
        print("   No need to press Enter: the script checks every 5 s, up to 6 minutes.\n")
        ok = False
        for _ in range(72):
            pg.wait_for_timeout(5000)
            try:
                if "creator-micro" in pg.url and "login" not in pg.url:
                    if any(k in pg.inner_text("body") for k in LOGGED_IN):
                        ok = True
                        break
            except Exception:
                continue
        print("Logged in. Session saved in: %s" % profile if ok
              else "No login detected within 6 minutes. Run login.py again.")
        pg.wait_for_timeout(2000)
        ctx.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
