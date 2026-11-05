# -*- coding: utf-8 -*-
"""Post a video to TikTok via the TikTok Studio web uploader (browser automation).

    python publish.py ../../job.example.json --dry    # fill everything, do NOT post (always try this first)
    python publish.py ../../job.example.json          # post (or schedule, if "schedule" is set)

Options:
    --profile DIR      browser profile folder (default ./_profile, created by login.py)
    --no-dupcheck      skip the "same caption already posted" check
    --dry-wait SEC     how long to keep the window open after --dry (default 15)

Job fields used (top level, or overridden in "platforms.tiktok"):
    video             path to the mp4 (required)
    caption           post text, without hashtags (required)
    tags              hashtags without "#"; each is typed and the first suggestion picked
    cover             optional cover image (jpg/png); failures here are logged, not fatal
    aigc              true -> switch on "AI-generated content" (default true); post is
                      aborted if the switch cannot be verified ON
    brand_disclosure  true -> "Disclose post content" -> "Your brand" (promoting your own
                      business). Default false. "Branded content" (paid partnership) is
                      never ticked by this script; do that by hand if it applies to you.
    schedule          optional "YYYY-MM-DD HH:MM" in the browser's local time; minutes must
                      be a multiple of 5, at least ~20 minutes ahead and within 10 days

Design rules (learned the hard way; keep them if you modify this script):
  1. Debug with --dry only. Never iterate on the real posting flow.
  2. Upload files with set_input_files (no OS file dialog).
  3. Viewport size: trust innerWidth/innerHeight (page.viewport_size is None here).
  4. Buttons that will not click: scroll + real click -> force=True -> pixel fallback.
  5. Success means "the next expected thing appeared", not "we clicked".
  6. Abort != not posted. After any abort, look at TikTok Studio -> Posts before re-running.
Login is never automated: run login.py and log in yourself.

WARNING: this is browser automation of a website. It can break whenever TikTok changes
its page, and automated posting may be against the platform's terms. Use at your own risk.
"""
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402
from common.browser import Abort, log  # noqa: E402
import tt_schedule  # noqa: E402

jobfile.setup_console()
LOGS = os.path.join(HERE, "_logs")
UPLOAD = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
CONTENT = "https://www.tiktok.com/tiktokstudio/content?lang=en"
LOGIN_MARKS = ["Log in to TikTok", "Sign up for TikTok"]

JS_AI_STATE = r"""() => {
    const lab = [...document.querySelectorAll('span,div,p,label')].find(e =>
        /^(AI-generated content|AI 生成的内容|AI生成内容)$/.test((e.textContent || '').trim()));
    if (!lab) return null;
    const lr = lab.getBoundingClientRect(), cy = lr.top + lr.height / 2;
    const sw = [...document.querySelectorAll('[role=switch], input[type=checkbox]')]
      .find(e => { const r = e.getBoundingClientRect();
                   return r.width > 0 && Math.abs(r.top + r.height / 2 - cy) < 30 && r.left > lr.left; });
    return sw ? (sw.getAttribute('aria-checked') === 'true' || sw.checked === true) : null;
}"""

# Find the switch/checkbox on the same row as a label (closest vertically, then
# horizontally) -> {state, x, y}. Rows like "Your brand" / "Branded content" are only
# ~36 px apart, so vertical distance must be compared first.
JS_ROW_SWITCH = r"""(re_src) => {
  const rx = new RegExp(re_src, 'i');
  const lab = [...document.querySelectorAll('span,div,p,label')].find(e =>
      e.childElementCount === 0 && rx.test((e.textContent || '').trim()) && e.getBoundingClientRect().width > 0);
  if (!lab) return {state: 'no-label'};
  const lr = lab.getBoundingClientRect(), cy = lr.top + lr.height / 2;
  const sws = [...document.querySelectorAll('[role=switch], input[type=checkbox]')]
    .map(e => [e, e.getBoundingClientRect()])
    .filter(([e, r]) => Math.abs(r.top + r.height / 2 - cy) < 30);
  if (!sws.length) return {state: 'no-switch'};
  const d = ([e, r]) => [Math.round(Math.abs(r.top + r.height / 2 - cy) / 6), Math.abs(r.left - lr.left)];
  sws.sort((a, b) => { const x = d(a), y = d(b); return x[0] - y[0] || x[1] - y[1]; });
  const sw = sws[0][0];
  sw.scrollIntoView({block: 'center'});
  let r = sw.getBoundingClientRect();
  if (r.width < 4) r = lab.getBoundingClientRect();
  return {state: (sw.getAttribute('aria-checked') === 'true' || sw.checked === true) ? 'on' : 'off',
          x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)};
}"""
RX_DISCLOSE = r"^(Disclose post content|Disclose video content|Content disclosure)$"
RX_YOURBRAND = r"^Your brand$"
RX_BRANDED = r"^Branded content$"

# Count visible, enabled <button>s whose text is exactly one of the labels.
JS_ONE_BUTTON = r"""(labels) => {
    const bs = [...document.querySelectorAll('button')]
        .filter(b => labels.includes(b.textContent.trim()) && !b.disabled
                     && b.getBoundingClientRect().width > 0);
    if (bs.length !== 1) return {n: bs.length};
    bs[0].scrollIntoView({block: 'center'});
    const r = bs[0].getBoundingClientRect();
    return {n: 1, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
}"""


def brand_ok(pg):
    """Disclosure ON + Your brand ticked + Branded content NOT ticked."""
    s = [pg.evaluate(JS_ROW_SWITCH, rx).get("state") for rx in (RX_DISCLOSE, RX_YOURBRAND, RX_BRANDED)]
    ok = s[0] == "on" and s[1] == "on" and s[2] != "on"
    if not ok:
        log("  read-back disclosure / your brand / branded = %s" % "/".join(map(str, s)))
    return ok


def set_your_brand(pg):
    for r in range(3):
        d = pg.evaluate(JS_ROW_SWITCH, RX_DISCLOSE)
        if d.get("state") == "off":
            pg.mouse.click(d["x"], d["y"])        # React only accepts trusted events
            pg.wait_for_timeout(2500)
        elif d.get("state") != "on":
            raise Abort("'Disclose post content' switch not found (%s)" % d.get("state"))
        y = pg.evaluate(JS_ROW_SWITCH, RX_YOURBRAND)
        if y.get("state") == "off":
            pg.mouse.click(y["x"], y["y"])
            pg.wait_for_timeout(2000)
        if brand_ok(pg):
            log("  content disclosure: Your brand OK (attempt %d)" % (r + 1))
            return
        log("  attempt %d did not stick, retrying" % (r + 1))
    raise Abort("Could not tick 'Your brand'; not posting")


def parse_schedule(s):
    try:
        dt = datetime.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
    except Exception:
        raise Abort("schedule must be 'YYYY-MM-DD HH:MM', got %r" % s)
    if dt.minute % 5:
        raise Abort("TikTok minutes come in 5-minute steps; %s is not selectable" % s)
    now = datetime.datetime.now()
    if dt < now + datetime.timedelta(minutes=20):
        raise Abort("schedule %s is less than 20 minutes from now" % s)
    if dt > now + datetime.timedelta(days=10):
        raise Abort("schedule %s is more than 10 days ahead" % s)
    return dt


def caption_key(caption):
    # 48 characters: shorter keys produced false "duplicate" hits on similar openings
    return re.sub(r"\s+", " ", caption.strip())[:48]


def dup_check(pg, key):
    """Look for an existing post whose caption starts the same. Returns context or ''."""
    pg.goto(CONTENT, wait_until="domcontentloaded", timeout=120000)
    pg.wait_for_timeout(12000)
    body = pg.inner_text("body")
    if key in body:
        i = body.index(key)
        return body[max(0, i - 60): i + 160].replace("\n", " | ")
    return ""


def dismiss_tips(pg):
    """Close 'Got it' style tips that pop up a few seconds after the editor loads."""
    for _ in range(10):
        for txt in ["Got it", u"知道了", u"我知道了"]:
            try:
                loc = pg.get_by_text(txt, exact=True)
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=4000, force=True)
                    log("  closed a tip (%s)" % txt)
                    pg.wait_for_timeout(800)
            except Exception:
                pass
        pg.wait_for_timeout(1000)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)


def upload_cover(pg, cov):
    """Best effort: any missing step is logged and skipped, the post continues."""
    try:
        if not os.path.exists(cov):
            raise Abort("Cover file not found: %s" % cov)
        opened = False
        for sel in ["text=Edit cover", u"text=编辑封面", "text=Select cover", u"text=选择封面"]:
            if pg.locator(sel).count():
                b = pg.locator(sel).first
                b.scroll_into_view_if_needed(timeout=8000)
                b.click(timeout=10000, force=True)
                pg.wait_for_timeout(2500)
                opened = True
                log("  opened cover editor (%s)" % sel)
                break
        if not opened:
            log("  cover entry not found; skipping cover")
            browser.shot(pg, LOGS, "cover_noentry")
            return
        for sel in ["text=Upload cover", u"text=上传封面", "text=Upload"]:
            if pg.locator(sel).count():
                pg.locator(sel).first.click(timeout=8000, force=True)
                pg.wait_for_timeout(1500)
                break
        accepts = pg.evaluate("() => [...document.querySelectorAll('input[type=file]')].map(e => e.accept || '')")
        idx = next((i for i, a in enumerate(accepts) if "image" in a or ".jpg" in a or ".png" in a), None)
        if idx is None:
            log("  no image file input in the cover dialog; skipping cover")
            browser.shot(pg, LOGS, "cover_noinput")
        else:
            pg.locator("input[type=file]").nth(idx).set_input_files(cov)
            pg.wait_for_timeout(4000)
            done = False
            for sel in ["text=Confirm", u"text=确认", "text=Save", u"text=保存", "text=Done", u"text=完成"]:
                loc = pg.locator(sel)
                if loc.count() and loc.last.is_visible():
                    loc.last.click(timeout=8000, force=True)
                    pg.wait_for_timeout(3000)
                    log("  cover confirmed (%s)" % sel)
                    done = True
                    break
            if not done:
                log("  cover confirm button not found")
                browser.shot(pg, LOGS, "cover_noconfirm")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(800)
    except Abort:
        raise
    except Exception as e:
        log("  cover step error (continuing): %s" % str(e)[:200])
        try:
            pg.keyboard.press("Escape")
        except Exception:
            pass


def set_ai_label(pg):
    """'Show more' -> 'AI-generated content' switch ON; verified by read-back."""
    try:
        for sel in ["text=Show more", u"text=显示更多", u"text=更多选项"]:
            if pg.locator(sel).count():
                b = pg.locator(sel).first
                try:
                    b.scroll_into_view_if_needed(timeout=8000)
                    b.click(timeout=10000)
                except Exception:
                    b.click(timeout=10000, force=True)
                pg.wait_for_timeout(2500)
                break
        # Locate the switch geometrically: same row as the label, to its right.
        # (Picking "the first switch" once hit an unrelated "High-quality uploads" switch.)
        state = pg.evaluate(r"""() => {
            const lab = [...document.querySelectorAll('span,div,p,label')].find(e =>
                /^(AI-generated content|AI 生成的内容|AI生成内容)$/.test((e.textContent || '').trim()));
            if (!lab) return 'no-label';
            const lr = lab.getBoundingClientRect();
            const cy = lr.top + lr.height / 2;
            const sws = [...document.querySelectorAll('[role=switch], input[type=checkbox]')]
              .map(e => [e, e.getBoundingClientRect()])
              .filter(([e, r]) => r.width > 0 && Math.abs(r.top + r.height / 2 - cy) < 30 && r.left > lr.left);
            if (!sws.length) return 'no-switch';
            sws.sort((a, b) => a[1].left - b[1].left);
            const sw = sws[0][0];
            const isOn = () => sw.getAttribute('aria-checked') === 'true' || sw.checked === true;
            if (isOn()) return 'already-on';
            sw.click();
            return 'clicked';
        }""")
        log("  AI-generated content: %s" % state)
        pg.wait_for_timeout(2500)
        for sel in ["button:has-text('Turn on')", u"button:has-text('开启')"]:
            if pg.locator(sel).count():
                pg.locator(sel).last.click(timeout=5000)
                log("  confirmed 'Turn on'")
                break
        pg.wait_for_timeout(1500)
        on = pg.evaluate(JS_AI_STATE)
        log("  read-back AI switch: %s" % {True: "ON", False: "OFF", None: "not found"}[on])
        if on is not True:
            raise Abort("AI-generated content label is not ON; not posting")
    except Abort:
        raise
    except Exception as e:
        raise Abort("AI label step failed, not posting: %s" % str(e)[:120])


def wait_content_check(pg):
    """Before scheduling, wait for TikTok's optional pre-check to finish (max 12 min).
    Submitting during the check pops 'post now anyway?' which a scheduled post must not take."""
    for i in range(72):
        t = pg.inner_text("body")
        if not re.search(u"Checking in progress|in progress|正在检查|This may take|大约需要", t, re.I):
            break
        if i and i % 6 == 0:
            log("  ...content check still running (%d min)" % (i // 6))
        pg.wait_for_timeout(10000)
    else:
        raise Abort("Content check did not finish within 12 minutes; not forcing a submit")
    # The optional "Content check lite" sometimes fails with "Something went wrong".
    # Retry up to 3 times; then switch the optional pre-check off (normal review still applies).
    for attempt in range(3):
        if "Something went wrong" not in pg.inner_text("body"):
            break
        log("  pre-check error, clicking Retry (%d)" % (attempt + 1))
        try:
            pg.get_by_text("Retry", exact=True).last.click(timeout=8000)
        except Exception:
            pass
        for _w in range(18):
            pg.wait_for_timeout(10000)
            t = pg.inner_text("body")
            if "Something went wrong" in t:
                break
            if not re.search(u"Checking in progress|in progress|正在检查", t, re.I):
                break
    if "Something went wrong" in pg.inner_text("body"):
        sw = pg.evaluate(JS_ROW_SWITCH, r"^Content check lite$")
        log("  pre-check keeps failing; switching 'Content check lite' off (now %s)" % sw.get("state"))
        if sw.get("state") == "on":
            pg.mouse.click(sw["x"], sw["y"])
            pg.wait_for_timeout(2500)
            for sel in ["button:has-text('Turn off')", u"button:has-text('关闭')"]:
                if pg.locator(sel).count():
                    pg.locator(sel).last.click(timeout=5000)
                    pg.wait_for_timeout(1500)
                    break
        if pg.evaluate(JS_ROW_SWITCH, r"^Content check lite$").get("state") != "off":
            raise Abort("Pre-check keeps failing and cannot be switched off; not forcing a submit")


def main():
    pos, flags, opt = jobfile.parse_args(sys.argv[1:], flags=("--dry", "--execute", "--no-dupcheck"),
                                         options=("--profile", "--dry-wait"))
    if not pos:
        print(__doc__)
        return 1
    dry = "--dry" in flags
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    if ('--dry' in flags) == ('--execute' in flags):
        print('Choose exactly one mode: --dry (local only) or --execute / 必须明确选择执行模式')
        return 1
    job = jobfile.load_job(pos[0], "tiktok")
    jobfile.require(job, "video", "caption")
    video = job["video"]
    if not os.path.isfile(video):
        log("Video file not found: %s" % video)
        return 1
    aigc = job.get("aigc", True)
    brand = bool(job.get("brand_disclosure", False))
    sched = (job.get("schedule") or "").strip()
    if sched:
        try:
            parse_schedule(sched)
        except Abort as e:
            log(str(e))
            return 1

    if '--dry' in flags:
        return jobfile.local_preflight(job)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("Playwright is not installed. Run: pip install -r requirements.txt, then python -m playwright install chromium")
        return 2

    log("Job: %s (%.1f MB, %s%s)" % (os.path.basename(video), os.path.getsize(video) / 1048576.0,
                                    "schedule " + sched if sched else "post now",
                                    ", DRY RUN" if dry else ""))

    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="en-US")
        try:
            key = caption_key(job["caption"])
            if "--no-dupcheck" not in flags:
                log("Duplicate check on the Posts page ...")
                hit = dup_check(pg, key)
                if any(k in pg.inner_text("body") for k in LOGIN_MARKS):
                    raise Abort("Not logged in -> run `python login.py` and log in yourself")
                if hit:
                    log("  found: %s" % hit)
                    raise Abort("A post with the same caption already exists; not posting again")
                log("  none found")

            log("Opening the upload page ...")
            pg.goto(UPLOAD, wait_until="domcontentloaded", timeout=120000)
            pg.wait_for_timeout(8000)
            if any(k in pg.inner_text("body") for k in LOGIN_MARKS):
                raise Abort("Not logged in -> run `python login.py` and log in yourself")

            log("Attaching the video file ...")
            fi = None
            for _ in range(40):
                if pg.locator("input[type=file]").count():
                    fi = pg.locator("input[type=file]").first
                    break
                pg.wait_for_timeout(500)
            if fi is None:
                raise Abort("File input never appeared")
            fi.set_input_files(video)

            log("Waiting for processing / editor (up to 5 min) ...")
            for _ in range(200):
                t = pg.inner_text("body")
                if any(k in t for k in ["Caption", "Cover", "Who can watch", "Post"]):
                    break
                pg.wait_for_timeout(1500)
            else:
                raise Abort("Upload done but the editor never appeared")
            pg.wait_for_timeout(4000)
            dismiss_tips(pg)

            log("Typing the caption ...")
            ed = pg.locator('[contenteditable="true"]').first
            try:
                ed.click(timeout=8000)
            except Exception:
                ed.click(timeout=8000, force=True)
            pg.keyboard.press("Control+A")
            pg.keyboard.press("Delete")
            head = job["caption"].strip()
            tags = job.get("tags") or []
            pg.keyboard.type(head, delay=14)
            for w in tags:
                pg.keyboard.type(" #" + w, delay=40)
                pg.wait_for_timeout(4500)      # give the suggestion list time on slow machines
                pg.keyboard.press("Enter")     # pick the first suggestion
                pg.wait_for_timeout(600)
            pg.wait_for_timeout(1500)
            got = pg.eval_on_selector('[contenteditable="true"]', "e => e.innerText")
            log("  read-back: %s" % got.replace("\n", " ")[:90])
            browser.check_readback(head, got, tags)
            log("  caption read-back matches")

            if job.get("cover"):
                upload_cover(pg, job["cover"])

            if aigc:
                set_ai_label(pg)

            if brand:
                log("Content disclosure ...")
                set_your_brand(pg)
                if aigc and pg.evaluate(JS_AI_STATE) is not True:     # layout shifts; re-verify
                    raise Abort("AI label no longer ON after disclosure; not posting")

            if sched:
                log("Setting schedule %s ..." % sched)
                try:
                    tt_schedule.apply(pg, sched, log)
                except tt_schedule.ScheduleError as e:
                    raise Abort("Schedule not set: %s" % e)
                rb = tt_schedule.readback(pg)
                radio = pg.evaluate(tt_schedule.JS_CHECKED)
                log("  read-back: schedule radio=%s time=%s" % (radio, rb))
                if not radio or rb != sched:
                    raise Abort("Schedule read-back mismatch (wanted %s); not posting" % sched)
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(800)
                if aigc and pg.evaluate(JS_AI_STATE) is not True:
                    raise Abort("AI label no longer ON after scheduling; not posting")
                if brand and not brand_ok(pg):
                    raise Abort("Your brand read-back wrong after scheduling; not posting")
                browser.shot(pg, LOGS, "sched")

            if dry:
                browser.shot(pg, LOGS, "dry")
                log("--dry: everything filled in, NOT posting. Closing soon.")
                pg.wait_for_timeout(int(float(opt.get("--dry-wait", 15)) * 1000))
                return 0

            if sched:
                log("Waiting for the content check ...")
                wait_content_check(pg)
                if tt_schedule.readback(pg) != sched:
                    raise Abort("Schedule changed before submit")
                if aigc and pg.evaluate(JS_AI_STATE) is not True:
                    raise Abort("AI label not ON before submit")
                if brand and not brand_ok(pg):
                    raise Abort("Your brand not OK before submit")
                # Use the locator (waits for stable layout, trusted click) rather than
                # stale coordinates: the page grows after toggling disclosure.
                sbtn = pg.locator("button").filter(has_text=re.compile(u"^\\s*(Schedule|预约发布)\\s*$"))
                if sbtn.count() != 1:
                    raise Abort("Found %d 'Schedule' buttons (expected 1); not guessing" % sbtn.count())
                sbtn.first.scroll_into_view_if_needed(timeout=10000)
                pg.wait_for_timeout(1200)
                sbtn.first.click(timeout=15000)
                log("  clicked 'Schedule'")
                pg.wait_for_timeout(12000)
                browser.shot(pg, LOGS, "after_click")
                if pg.evaluate("() => !!document.querySelector('.TUXModal-overlay')"):
                    c = pg.evaluate(JS_ONE_BUTTON, ["Cancel", u"取消"])
                    if c.get("n") == 1:
                        pg.mouse.click(c["x"], c["y"])
                        pg.wait_for_timeout(2000)
                    raise Abort("A confirmation dialog appeared after submit (often 'post now?'); "
                                "cancelled. A scheduled post must not be posted immediately.")
                on_content = "tiktokstudio/content" in pg.url
                hit = dup_check(pg, caption_key(job["caption"]))
                if hit:
                    log("Scheduled. Seen on the Posts page: %s" % hit)
                    return 0
                if on_content:
                    log("Submitted (redirected to Posts page), but the caption was not found in "
                        "the list text. Check by hand; do NOT re-run.")
                    return 0
                raise Abort("Clicked Schedule but saw no success sign. It may still have been "
                            "scheduled: check the Posts page before re-running.")

            log("Submitting ...")
            if brand and not brand_ok(pg):
                raise Abort("Your brand not OK before submit")
            posted = False
            for sel in ["button:has-text('Post')", u"button:has-text('发布')"]:
                try:
                    b = pg.locator(sel).last
                    if b.count():
                        b.scroll_into_view_if_needed()
                        pg.wait_for_timeout(400)
                        b.click(timeout=8000)
                        posted = True
                        break
                except Exception:
                    continue
            if not posted:
                hit = browser.click_by_pixel(pg, (200, 90, 120), band=(0.60, 1.0))   # TikTok red
                if not hit:
                    raise Abort("Post button not found (DOM and pixel search both failed)")
                log("  clicked Post by pixel at (%d,%d), %d red pixels" % hit)
            pg.wait_for_timeout(12000)
            if "tiktokstudio/content" in pg.url:
                log("Posted (redirected to the Posts page).")
                return 0
            t = pg.inner_text("body")
            if not any(k in t for k in ["Your video is being uploaded", "Manage your posts",
                                        "View profile", "Posted"]):
                raise Abort("Clicked Post but saw no success sign; current page %s" % pg.url)
            log("Posted.")
            return 0

        except Abort as e:
            log("ABORTED: %s" % e)
            log("Reminder: an abort does not prove nothing was posted. Check TikTok Studio before re-running.")
            browser.shot(pg, LOGS, "abort")
            return 2
        except Exception as e:
            log("ERROR: %s: %s" % (type(e).__name__, str(e)[:300]))
            browser.shot(pg, LOGS, "error")
            return 3
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
