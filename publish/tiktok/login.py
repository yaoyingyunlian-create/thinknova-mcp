# -*- coding: utf-8 -*-
"""TikTok login - YOU log in once by hand; publish.py then reuses this browser profile.

    python login.py
    python login.py --profile ~/tiktok_profile             # custom profile folder

What it does:
  1. opens a separate, visible browser profile on the TikTok Studio upload page
  2. waits while you log in yourself (QR code / email / phone)
  3. checks every 5 seconds whether the upload screen is reachable (max 6 minutes)

The script never types passwords and never handles captchas.
The profile folder (default: ./_profile) contains your login session. Keep it private,
never share or commit it. Delete it to log out; run this script again to log back in.
"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402

jobfile.setup_console()
UPLOAD = "https://www.tiktok.com/tiktokstudio/upload?lang=en"


def main():
    _, _, opt = jobfile.parse_args(sys.argv[1:], options=("--profile",))
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="en-US")
        pg.goto(UPLOAD, wait_until="domcontentloaded", timeout=120000)
        print("")
        print("Browser is open on the TikTok upload page.")
        print("-> Log in yourself in that window (QR code / email / phone).")
        print("   No need to press Enter: the script checks every 5 s, up to 6 minutes.")
        print("")
        ok = False
        for i in range(72):
            pg.wait_for_timeout(5000)
            try:
                body = pg.inner_text("body")
            except Exception:
                continue
            hit_up = any(k in body for k in
                         ["Select video", "Select file", "Upload video", u"上传视频", u"选择视频"])
            hit_login = any(k in body for k in
                            ["Log in to TikTok", "Sign up for TikTok", "Use QR code", u"扫码登录"])
            if hit_up and not hit_login:
                ok = True
                break
            if i % 6 == 0:
                print("  ...still on the login page (%d s)" % ((i + 1) * 5))
        print("")
        if ok:
            print("Logged in. Session saved in: %s" % profile)
            print("Next: python publish.py <job.json> --dry")
        else:
            print("No upload screen within 6 minutes.")
            print("  Either login is not finished, or the platform blocked this browser.")
            print("  If your phone says the QR login succeeded but nothing happens here, it is the second case.")
        browser.shot(pg, os.path.join(HERE, "_logs"), "login_check")
        ctx.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
