# -*- coding: utf-8 -*-
"""Post a video to Douyin via the Creator Center web page (browser automation).

    python publish.py ../../job.example.json --dry    # fill everything, screenshot each step, do NOT post
    python publish.py ../../job.example.json          # post (scheduled if "schedule" is set)

Options:
    --profile DIR     browser profile (default ./_profile, created by login.py)
    --dry-wait SEC    keep the window open this long after --dry (default 180)

Job fields used (top level, or overridden in "platforms.douyin"):
    video     mp4 path (required)
    title     title (required; cut to 30 characters)
    desc      description without hashtags; falls back to "caption"
    tags      topics without "#"; each is typed and the first suggestion picked
    aigc      true -> self-declaration "content is AI-generated" (default true); aborts if
              the declaration cannot be set
    schedule  optional "YYYY-MM-DD HH:MM" (browser local time); empty = post now

Design rules:
  1. Run --dry first and look at the screenshots in _logs before the first real post.
  2. Upload with set_input_files (no OS file dialog).
  3. Every step is read back; success = the next expected screen appeared.
  4. Waits are generous on purpose (slow machines).
  5. Abort != not posted: after any abort, run check.py before re-running.
The UI strings matched below are the Chinese labels of the Douyin creator page.

WARNING: browser automation of a website. It can break when the platform changes its page,
and automated posting may be against the platform's rules. Use at your own risk.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402
from common.browser import Abort, log  # noqa: E402

jobfile.setup_console()
LOGS = os.path.join(HERE, "_logs")
UPLOAD = "https://creator.douyin.com/creator-micro/content/upload"


def first_visible(pg, sels, timeout_ms=4000):
    for s in sels:
        loc = pg.locator(s)
        try:
            if loc.count():
                loc.first.wait_for(state="visible", timeout=timeout_ms)
                return loc.first
        except Exception:
            continue
    return None


def set_ai_declaration(pg):
    """Self-declaration row -> choose "content is AI-generated" -> confirm; verified by read-back."""
    log("Self-declaration: AI-generated ...")
    try:
        opener = first_visible(pg, [u"text=请选择自主声明", u"text=自主声明", u"text=添加声明"], 8000)
        if not opener:
            raise Abort("Self-declaration entry not found")
        try:
            opener.click(timeout=10000, force=True)
        except Exception:
            # On slow machines the dialog may already be open although click() timed out
            pg.wait_for_timeout(2000)
            if u"请选择声明类型" not in pg.inner_text("body"):
                raise
            log("  (click timed out but the declaration dialog is open; continuing)")
        pg.wait_for_timeout(3000)
        browser.shot(pg, LOGS, "decl_open")
        opt = first_visible(pg, [u"text=内容由AI生成", u"text=内容由 AI 生成", u"text=AI生成"], 8000)
        if not opt:
            raise Abort("'AI-generated' option not found in the declaration dialog")
        opt.click(timeout=10000, force=True)
        pg.wait_for_timeout(1500)
        ok_btn = first_visible(pg, [u"button:has-text('确定')", u"button:has-text('确认')",
                                    u"button:has-text('完成')"], 4000)
        if ok_btn:
            ok_btn.click(timeout=10000, force=True)
            pg.wait_for_timeout(1500)
        browser.shot(pg, LOGS, "decl_after")
        if u"请选择自主声明" in pg.inner_text("body"):
            raise Abort("Declaration did not stick (still shows the empty placeholder)")
        log("  declaration set")
    except Abort:
        pg.keyboard.press("Escape")
        raise
    except Exception as e:
        pg.keyboard.press("Escape")
        raise Abort("Declaration step failed, not posting: %s" % str(e)[:120])
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(800)


def main():
    pos, flags, opt = jobfile.parse_args(sys.argv[1:], flags=("--dry", "--execute"),
                                         options=("--profile", "--dry-wait"))
    if not pos:
        print(__doc__)
        return 1
    dry = "--dry" in flags
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    if ('--dry' in flags) == ('--execute' in flags):
        print('Choose exactly one mode: --dry (local only) or --execute / 必须明确选择执行模式')
        return 1
    job = jobfile.load_job(pos[0], "douyin")
    if not job.get("desc"):
        job["desc"] = job.get("caption", "")
    jobfile.require(job, "video", "title")
    video = job["video"]
    if not os.path.isfile(video):
        log("Video file not found: %s" % video)
        return 2
    if '--dry' in flags:
        return jobfile.local_preflight(job)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("Playwright is not installed. Run: pip install -r requirements.txt, then python -m playwright install chromium")
        return 2
    log("Job: %s (%.1f MB, %s%s)" % (os.path.basename(video), os.path.getsize(video) / 1048576.0,
                                    "schedule " + job["schedule"] if job.get("schedule") else "post now",
                                    ", DRY RUN" if dry else ""))

    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile, locale="zh-CN")
        try:
            log("Opening the upload page ...")
            pg.goto(UPLOAD, wait_until="domcontentloaded", timeout=120000)
            fi = None
            for _ in range(60):
                pg.wait_for_timeout(1000)
                if "login" in pg.url or "passport" in pg.url:
                    raise Abort("Not logged in -> run `python login.py` and log in yourself")
                if pg.locator("input[type=file]").count():
                    fi = pg.locator("input[type=file]").first
                    break
            if fi is None:
                browser.shot(pg, LOGS, "no_input", True)
                raise Abort("Upload input never appeared (not logged in, or the page changed)")
            if dry:
                browser.shot(pg, LOGS, "1_upload_page", True)

            log("Attaching the video file ...")
            fi.set_input_files(video)

            log("Waiting for the editor (up to 3 min) ...")
            title_box = None
            for _ in range(120):
                pg.wait_for_timeout(1500)
                title_box = first_visible(pg, [u"input[placeholder*='标题']", u"input[placeholder*='作品标题']",
                                               u".semi-input[placeholder*='标题']"], 1500)
                if title_box:
                    break
            if not title_box:
                browser.shot(pg, LOGS, "no_editor", True)
                raise Abort("Upload done but the title box never appeared")
            if dry:
                browser.shot(pg, LOGS, "2_editor", True)

            log("Title ...")
            title = job["title"][:30]
            title_box.click()
            title_box.fill(title)
            if title_box.input_value().strip() != title.strip():
                raise Abort("Title read-back mismatch: %s" % title_box.input_value())

            log("Description + topics ...")
            ed = first_visible(pg, [u"[contenteditable='true'][data-placeholder*='简介']",
                                    ".zone-container[contenteditable='true']",
                                    "div[contenteditable='true']"], 8000)
            if not ed:
                raise Abort("Description editor not found")
            ed.click()
            pg.keyboard.type(job.get("desc", ""), delay=20)
            for w in job.get("tags") or []:
                pg.keyboard.type(" #" + w, delay=60)
                pg.wait_for_timeout(2500)             # wait for topic suggestions
                pg.keyboard.press("Enter")            # pick the first suggestion
                pg.wait_for_timeout(800)
            # the placeholder attribute disappears after typing -> read back with a generic selector
            pg.wait_for_timeout(1500)
            txt = pg.locator("div[contenteditable='true']").first.inner_text(timeout=15000)
            log("  read-back: %s" % txt.replace("\n", " ")[:100])
            browser.check_readback(job.get("desc", ""), txt, job.get("tags"))
            log("  description read-back matches")

            for _ in range(3):           # close "got it" tips
                kb = first_visible(pg, [u"button:has-text('我知道了')", u"text=我知道了"], 2000)
                if not kb:
                    break
                try:
                    kb.click(timeout=5000, force=True)
                    pg.wait_for_timeout(1000)
                except Exception:
                    break

            if job.get("aigc", True):
                set_ai_declaration(pg)

            if job.get("schedule"):
                log("Schedule %s ..." % job["schedule"])
                sw = first_visible(pg, [u"label:has-text('定时发布')", u"text=定时发布"], 8000)
                if not sw:
                    raise Abort("'Scheduled publish' option not found")
                sw.click(timeout=10000, force=True)
                pg.wait_for_timeout(2500)
                box = first_visible(pg, [u"input[placeholder*='日期']", u"input[placeholder*='时间']",
                                         ".semi-datepicker input"], 5000)
                if not box:
                    raise Abort("Schedule enabled but no date/time input appeared")
                box.click()
                pg.keyboard.press("Control+A")
                pg.keyboard.type(job["schedule"], delay=40)
                pg.keyboard.press("Enter")
                pg.wait_for_timeout(1000)
                now = box.input_value()
                if not now.startswith(job["schedule"][:16]):
                    raise Abort("Schedule not set: wanted %s, got %s" % (job["schedule"], now))
                pg.keyboard.press("Escape")       # the calendar popup stays open and covers the button
                pg.wait_for_timeout(1000)

            for _ in range(120):                  # wait for processing to finish
                body = pg.inner_text("body")
                if u"上传中" not in body and u"上传进度" not in body:
                    break
                pg.wait_for_timeout(1500)

            if dry:
                browser.shot(pg, LOGS, "3_filled", True)
                log("--dry: everything filled in, NOT posting. The draft is not saved.")
                pg.wait_for_timeout(int(float(opt.get("--dry-wait", 180)) * 1000))
                return 0

            log("Clicking publish ...")
            # Only a button whose text is EXACTLY "publish" (the bottom one). A looser match
            # hits the sidebar entry, which goes back to the upload page and leaves a draft.
            btn = None
            cand = pg.get_by_role("button", name=u"发布", exact=True)
            for k in range(cand.count()):
                try:
                    if cand.nth(k).is_visible():
                        btn = cand.nth(k)
                except Exception:
                    continue
            if btn is None:
                btn = first_visible(pg, [u"button:text-is('发布')"], 8000)
            if not btn:
                browser.shot(pg, LOGS, "no_publish_btn", True)
                raise Abort("Publish button not found")
            btn.scroll_into_view_if_needed()
            pg.wait_for_timeout(500)
            btn.click()
            pg.wait_for_timeout(3000)
            browser.shot(pg, LOGS, "just_clicked", True)
            ok = False
            for _ in range(40):
                pg.wait_for_timeout(1500)
                if "content/manage" in pg.url or u"发布成功" in pg.inner_text("body"):
                    ok = True
                    break
            if not ok:
                browser.shot(pg, LOGS, "after_publish", True)
                raise Abort("Clicked publish but saw no success sign (page %s). It may still have "
                            "been posted: run check.py." % pg.url)
            log("Published (or queued for the scheduled time).")
            browser.shot(pg, LOGS, "done", True)
            return 0

        except Abort as e:
            log("ABORTED: %s" % e)
            log("Reminder: an abort does not prove nothing was posted. Run check.py before re-running.")
            browser.shot(pg, LOGS, "abort", True)
            return 2
        except Exception as e:
            log("ERROR: %s: %s" % (type(e).__name__, str(e)[:300]))
            browser.shot(pg, LOGS, "error", True)
            return 3
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
