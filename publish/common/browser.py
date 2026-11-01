# -*- coding: utf-8 -*-
"""Shared browser helpers for the browser-automation publishers (TikTok / Xiaohongshu / Douyin).

What this does:
  * Opens a *persistent* Chromium profile folder, so you log in once (by hand) and
    later runs reuse that login state. The profile folder holds your session data:
    keep it on your own machine, never share it, never commit it to git.
  * Removes the most obvious automation fingerprints. Without this, some platforms
    silently refuse QR-code login inside an automated browser.
  * Small helpers: timestamped log lines and screenshots into a local _logs folder.

It never types passwords and never touches captchas. Logging in is always done by
you, in the visible browser window, via login.py.
"""
import os
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
ARGS = [
    "--start-maximized",
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
]
STEALTH = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "window.chrome = window.chrome || {runtime:{}};"
)


def log(msg):
    print(u"[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def launch(p, profile, locale="en-US", stealth=True, viewport=None):
    """Launch a visible persistent Chromium context.

    Use the SAME settings for login.py and publish.py of a platform; otherwise the
    platform may treat the publish run as a new device and ask you to log in again.
    """
    profile = os.path.abspath(os.path.expanduser(profile))
    os.makedirs(profile, exist_ok=True)
    kw = dict(headless=False, args=list(ARGS), locale=locale,
              ignore_default_args=["--enable-automation"])
    if viewport:
        kw["viewport"] = viewport
    else:
        kw["no_viewport"] = True
    if stealth:
        kw["user_agent"] = UA
    ctx = p.chromium.launch_persistent_context(profile, **kw)
    if stealth:
        ctx.add_init_script(STEALTH)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def shot(page, logs_dir, tag, full_page=False):
    """Save a screenshot to logs_dir; never raises."""
    os.makedirs(logs_dir, exist_ok=True)
    fp = os.path.join(logs_dir, "%s_%s.png" % (time.strftime("%Y%m%d_%H%M%S"), tag))
    try:
        page.screenshot(path=fp, full_page=full_page)
        log(u"  screenshot: %s" % fp)
    except Exception as e:
        log(u"  screenshot failed: %s" % str(e)[:80])
    return fp


ZERO_WIDTH = u"​‌‍﻿ "


def norm_text(s):
    """Remove whitespace and zero-width characters, for exact read-back comparisons."""
    return "".join(ch for ch in (s or "") if not ch.isspace() and ch not in ZERO_WIDTH)


class Abort(Exception):
    """Raised when a step cannot be verified. The run stops and nothing is submitted."""
    pass


def check_readback(want, got, tags):
    """The text typed into the editor must read back exactly (ignoring whitespace),
    and every hashtag must be present. Otherwise abort instead of posting."""
    if norm_text(want) not in norm_text(got):
        raise Abort(u"Caption read-back does not match | wanted: %s | got: %s"
                    % (want.replace("\n", " ")[:120], got.replace("\n", " ")[:120]))
    miss = [w for w in (tags or []) if ("#" + w) not in got]
    if miss:
        raise Abort(u"Hashtag(s) missing after typing: %s" % " ".join("#" + w for w in miss))


def click_by_pixel(page, rgb_lo, band=(0.55, 1.0), xrange=(0.0, 1.0)):
    """Find a button by its colour in a screenshot and click its centre.

    Last-resort fallback for buttons inside custom elements / closed shadow roots,
    which DOM selectors cannot see. rgb_lo = (min_red, max_green, max_blue).
    """
    from PIL import Image
    import io as _io
    vp = page.evaluate("() => ({w: innerWidth, h: innerHeight})")
    im = Image.open(_io.BytesIO(page.screenshot())).convert("RGB")
    sw, sh = im.size
    kx, ky = sw / float(vp["w"]), sh / float(vp["h"])
    px = im.load()
    pts = []
    for y in range(int(sh * band[0]), int(sh * band[1]) - 1, 2):
        for x in range(int(sw * xrange[0]), int(sw * xrange[1]) - 1, 2):
            r, g, b = px[x, y]
            if r >= rgb_lo[0] and g <= rgb_lo[1] and b <= rgb_lo[2]:
                pts.append((x, y))
    if not pts:
        return None
    cx = int(sum(q[0] for q in pts) / len(pts) / kx)
    cy = int(sum(q[1] for q in pts) / len(pts) / ky)
    page.mouse.click(cx, cy)
    return (cx, cy, len(pts))
