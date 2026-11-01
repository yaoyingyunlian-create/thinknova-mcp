# -*- coding: utf-8 -*-
"""Change the scheduled time of a Xiaohongshu note that is still "scheduled".
Only the time is changed: the note is never deleted and its text is never edited.

    python reschedule.py "<exact note title>" "2026-11-05 20:00" --dry
        opens the note editor, sets the new time, takes a screenshot, does NOT submit
    python reschedule.py "<exact note title>" "2026-11-05 20:00" --run
        same, then submits and re-reads the time in Note Manager

Options: --profile DIR, --base URL (same as publish.py)

Note cards have three icon buttons (pin / edit / delete). The script hovers each one and
only clicks the one whose tooltip text is exactly the Chinese word for "edit"; the delete
button is skipped by its class name.
"""
import io
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402
from common.browser import log  # noqa: E402
import xhs_urls  # noqa: E402

jobfile.setup_console()
LOGS = os.path.join(HERE, "_logs")
L_EDIT = u"编辑"          # "edit" tooltip
L_SCHEDULED = u"定时"     # card status contains "scheduled"


def main():
    pos, flags, opt = jobfile.parse_args(sys.argv[1:], flags=("--dry", "--run"),
                                         options=("--profile", "--base"))
    if len(pos) < 2 or not (flags & {"--dry", "--run"}):
        print(__doc__)
        return 1
    title, new = pos[0], pos[1]
    if not (len(new) == 16 and new[4] == "-" and new[13] == ":"):
        print("Time must look like 2026-11-05 20:00")
        return 1
    run = "--run" in flags
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    urls = xhs_urls.urls(opt.get("--base"))
    card_sel = '.note-card:has(.note-card__title:text-is("%s"))' % title.replace('"', '\\"')

    def find_card(pg):
        for _ in range(25):
            c = pg.locator(card_sel)
            if c.count():
                return c.first
            pg.evaluate("() => { const c = document.querySelector('div.content'); if (c) c.scrollTop += 1500; }")
            pg.wait_for_timeout(1200)
        return None

    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="zh-CN", stealth=False,
                                 viewport={"width": 1440, "height": 900})
        try:
            pg.goto(urls["manager"], wait_until="domcontentloaded", timeout=120000)
            pg.wait_for_timeout(12000)
            card = find_card(pg)
            if not card:
                log(u"Note '%s' not found in Note Manager" % title)
                return 2
            old = card.locator(".note-card__time").inner_text()
            log("Current schedule: %s" % old)
            if L_SCHEDULED not in card.inner_text():
                log("This note is not in 'scheduled' state; leaving it alone")
                return 2
            card.scroll_into_view_if_needed()
            card.hover()
            pg.wait_for_timeout(1000)
            btns = card.locator(".note-card__action-btn")
            edit = None
            for i in range(btns.count()):
                b = btns.nth(i)
                if "--del" in (b.get_attribute("class") or ""):
                    continue
                b.hover()
                pg.wait_for_timeout(900)
                tips = pg.evaluate("() => Array.from(document.querySelectorAll('[role=tooltip], .d-tooltip, .d-popover'))"
                                   ".map(e=>(e.innerText||'').trim()).filter(Boolean)")
                if tips and tips[-1] == L_EDIT:
                    edit = b
                    break
            if not edit:
                log("Edit button (by tooltip) not found")
                return 2
            edit.click()
            pg.wait_for_timeout(12000)
            idx = pg.eval_on_selector_all("input", "els => els.findIndex(e => /^20\\d\\d-/.test(e.value||''))")
            if idx is None or idx < 0:
                log("No schedule time box in the editor")
                return 2
            box = pg.locator("input").nth(idx)
            log("Editor schedule: %s" % box.input_value())
            box.click()
            box.fill(new)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2000)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(1200)
            now = pg.locator("input").nth(idx).input_value()
            log("Time box now: %s" % now)
            if not now.startswith(new):
                log("Time did not stick")
                return 2
            for _ in range(4):
                if pg.evaluate("() => !document.querySelector('.d-picker-panel,[class*=picker-panel],[class*=date-panel],[class*=calendar]')"):
                    break
                pg.keyboard.press("Escape")
                pg.mouse.click(180, 400)
                pg.wait_for_timeout(700)
            browser.shot(pg, LOGS, "resched")
            if not run:
                log("--dry: not submitting.")
                return 0
            # Submit: the bottom button is inside a closed shadow root -> pixel search for the red button.
            from PIL import Image
            vp = pg.evaluate("() => ({width: innerWidth, height: innerHeight})")
            host = pg.evaluate("() => { const h = document.querySelector('xhs-publish-btn'); if (!h) return null;"
                               " const r = h.getBoundingClientRect(); return {top:r.top, h:r.height}; }")
            if not host:
                log("Submit bar not found")
                return 2
            im = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
            sw, sh = im.size
            kx, ky = sw / float(vp["width"]), sh / float(vp["height"])
            yy = int((host["top"] + host["h"] / 2) * ky)
            px = im.load()
            xs = [x for x in range(sw) if px[x, yy][0] > 200 and px[x, yy][1] < 90 and px[x, yy][2] < 110]
            if not xs:
                log("No red submit button found in the bar")
                return 2
            cx, cy = int(sum(xs) / len(xs) / kx), int(yy / ky)
            log("Clicking the submit button at (%d,%d)" % (cx, cy))
            pg.mouse.click(cx, cy)
            pg.wait_for_timeout(9000)
            pg.goto(urls["manager"], wait_until="domcontentloaded", timeout=120000)
            pg.wait_for_timeout(12000)
            c = find_card(pg)
            t = c.locator(".note-card__time").inner_text() if c else None
            n = pg.locator(card_sel).count()
            log("Read-back: %d note(s) with this title, schedule %s" % (n, t))
            if n != 1 or not (t or "").startswith(new):
                log("Read-back does not match (expected exactly 1 note at %s)" % new)
                return 3
            log("Rescheduled: %s -> %s" % (old, new))
            return 0
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
