# -*- coding: utf-8 -*-
"""Xiaohongshu (RED) login - YOU log in once by hand in the opened window.

    python login.py
    python login.py --profile DIR --base https://creator.xiaohongshu.com

The script only opens the Creator platform in a separate browser profile. Log in yourself
(QR code with the app is quickest). When you can see the "upload video / upload image"
page, come back to the terminal and press Enter. The script then checks the login.

The profile folder (default ./_profile) contains your session: keep it private, never share
or commit it. If the session expires, run this script again.
"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402
import xhs_urls  # noqa: E402

jobfile.setup_console()


def main():
    _, _, opt = jobfile.parse_args(sys.argv[1:], options=("--profile", "--base"))
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    urls = xhs_urls.urls(opt.get("--base"))
    with sync_playwright() as p:
        ctx, page = browser.launch(p, profile, locale="zh-CN", stealth=False,
                                   viewport={"width": 1440, "height": 900})
        page.goto(urls["publish"], wait_until="domcontentloaded", timeout=120000)
        print("")
        print("=" * 58)
        print("  Browser is open. Log in to the Creator platform yourself.")
        print("  When you see the upload page, come back here and press Enter.")
        print("=" * 58)
        input()
        logged_in = False
        try:
            page.goto(urls["publish"], wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(6000)
            txt = page.inner_text("body")
            # UI text on the Chinese-language creator page: "upload video" / "log in"
            logged_in = (u"上传视频" in txt) and ("/login" not in page.url)
        except Exception as e:
            print("Check failed: %s" % str(e)[:120])
        ctx.close()
    if logged_in:
        print("\nLogin saved in: %s" % profile)
        print("Next: python publish.py <job.json> --dry")
        return 0
    print("\nDid not see the logged-in upload page; the session may not be saved. Run again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
