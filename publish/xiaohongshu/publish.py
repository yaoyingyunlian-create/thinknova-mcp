# -*- coding: utf-8 -*-
"""Post a note to Xiaohongshu (RED) via the Creator web platform (browser automation).

    python publish.py ../../job.example.json --dry    # fill everything, do NOT post (try this first)
    python publish.py ../../job.example.json          # post (scheduled if "schedule" is set)

Options:
    --profile DIR     browser profile (default ./_profile, created by login.py)
    --base URL        creator host (see xhs_urls.py)
    --dry-wait SEC    keep the window open this long after --dry (default 600)

Job fields used (top level, or overridden in "platforms.xiaohongshu"):
    type      "video" or "image"; default: "video" if "video" is set, else "image"
    video     mp4 path (type=video)
    images    list of image paths (type=image); the first one is the cover
    title     note title (required; the platform limits it to about 20 characters)
    body      list of paragraphs (one Enter between them); a string is split on new lines;
              falls back to "caption"
    tags      topics without "#"; each must be picked from the platform's suggestion list
    aigc      true -> content declaration "contains AI-generated content" (default true);
              the post is aborted if the declaration cannot be verified
    schedule  optional "YYYY-MM-DD HH:MM" (browser local time) -> scheduled post

Design rules:
  1. Locate elements by selector / text, never by fixed coordinates (viewport and
     screenshot sizes differ). Pixel search is only a last resort for the submit button,
     which lives in a closed shadow root.
  2. Upload with set_input_files (no OS file dialog).
  3. Topic suggestions are flaky: delete two characters, retype, wait, and only click an
     exact match. A topic left as plain text aborts the run.
  4. Every step is read back; any mismatch saves a screenshot in _logs and exits non-zero.
  5. Abort != not posted. After an abort or error the script re-reads Note Manager and
     tells you whether the note exists anyway. Never re-run blindly.
The UI strings matched below are the Chinese labels of the creator page.

WARNING: browser automation of a website. It can break when the platform changes its page,
and automated posting may be against the platform's rules. Use at your own risk.
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402
from common.browser import Abort, log  # noqa: E402
import dupcheck  # noqa: E402
import xhs_urls  # noqa: E402

jobfile.setup_console()
LOGS = os.path.join(HERE, "_logs")

# Chinese UI labels used on the creator page
L_UPLOAD_VIDEO = u"上传视频"          # "upload video"
L_UPLOAD_IMAGE = u"上传图文"          # "upload image note"
L_TITLE_PH = u"标题"                  # title placeholder contains "title"
L_SCHEDULE = u"定时发布"              # "scheduled publish" (switch label AND submit button)
L_PUBLISH = u"发布"                   # "publish"
L_DECL = u"添加内容类型声明"          # "add content type declaration"
L_AI_OPT = u"笔记含AI合成内容"        # "note contains AI-generated content"
L_LOGIN_QR = u"扫码登录"
L_LOGIN_PHONE = u"手机号登录"

MARK_JS = """
(args) => {
  const [txt, mark, excludeSel] = args;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while (n = w.nextNode()) {
    if (n.nodeValue.trim() !== txt) continue;
    const el = n.parentElement;
    if (!el || !el.offsetParent) continue;
    if (excludeSel && el.closest(excludeSel)) continue;
    el.setAttribute(mark, '1');
    return true;
  }
  return false;
}
"""

PICKER_OPEN_JS = ("() => !document.querySelector('.d-picker-panel,[class*=picker-panel],"
                  "[class*=date-panel],[class*=calendar]')")


def click_text(page, txt, mark, exclude=None, timeout=40000):
    """Click the element whose visible text is exactly txt (real click; JS fallback)."""
    if not page.evaluate(MARK_JS, [txt, mark, exclude]):
        raise Abort(u"No clickable element with text '%s'" % txt)
    try:
        page.click("[%s]" % mark, timeout=timeout)
    except Exception:
        # Some tabs are visible but swallow real clicks; dispatch pointer events on the
        # element and two ancestors (the handler is often on an ancestor).
        page.evaluate("""(m)=>{
            const el=document.querySelector('['+m+']'); if(!el) return false;
            let n=el;
            for(let i=0;i<3&&n;i++,n=n.parentElement){
              for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])
                n.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}));
            }
            return true;
        }""", mark)
        page.wait_for_timeout(1200)
    page.evaluate("(m)=>document.querySelectorAll('['+m+']').forEach(e=>e.removeAttribute(m))", mark)


def file_input(page, kind):
    want = ".jpg" if kind == "image" else ".mp4"
    for _ in range(40):
        vals = page.eval_on_selector_all("input[type=file]", "els => els.map(e => e.accept || '')")
        for i, acc in enumerate(vals):
            if want in acc:
                return page.locator("input[type=file]").nth(i)
        page.wait_for_timeout(500)
    raise Abort("No file input accepting %s" % want)


def add_tag(page, word, rounds=6):
    """Insert one topic; if the suggestion does not show, delete two chars and retype."""
    editor = page.locator('[contenteditable="true"]').first
    editor.click()
    # Ctrl+End, not End: End only goes to the end of the clicked line, which inserted
    # the topic in the middle of a multi-line body.
    page.keyboard.press("Control+End")
    page.click("button.topic-btn")
    page.wait_for_timeout(1200)
    page.keyboard.type(word, delay=60)
    target = u"#" + word
    for r in range(rounds):
        for k in range(24):
            page.wait_for_timeout(1000)
            items = page.eval_on_selector_all(
                ".items .item", "els => els.map(e => (e.innerText||'').trim().split('\\n')[0].trim())")
            if target in items:
                page.locator(".items .item").nth(items.index(target)).click()
                page.wait_for_timeout(1200)
                tail = page.locator('[contenteditable="true"]').first.inner_text()
                if (word + u"[") in tail[-80:] or (target + u"[") in tail[-80:]:
                    log(u"  topic %s OK (round %d)" % (target, r + 1))
                    return True
                log(u"  topic %s clicked but did not become a topic, retrying" % target)
                break
            if items and r == 0 and k == 5:
                log("  suggestions are default recommendations, not search results; refreshing")
                break
        log(u"  topic %s: no suggestion, retyping (round %d)" % (target, r + 1))
        page.keyboard.press("Backspace")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(3000)
        page.keyboard.type(word[-2:], delay=80)
    raise Abort(u"Topic '%s' never appeared in suggestions after %d rounds; not posting" % (target, rounds))


def set_ai_declaration(page):
    """Content settings -> add content type declaration -> contains AI-generated content.
    Success is judged only by read-back."""
    def picked():
        return page.evaluate("""(t) => Array.from(document.querySelectorAll(
            '[class*=d-select-descripti],.permission-info-text'))
            .some(e => (e.textContent || '').trim() === t)""", L_AI_OPT)

    log("Content declaration: AI-generated ...")
    if picked():
        log("  already set")
        return
    for r in range(3):
        if not page.evaluate(MARK_JS, [L_DECL, "data-aidecl", None]):
            raise Abort("Content declaration dropdown not found (page changed?)")
        dd = page.locator("[data-aidecl]").first
        dd.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        dd.click()
        page.wait_for_timeout(1800)
        page.evaluate("()=>document.querySelectorAll('[data-aidecl]').forEach(e=>e.removeAttribute('data-aidecl'))")
        if page.evaluate(MARK_JS, [L_AI_OPT, "data-aiopt", "[class*=d-select-descripti]"]):
            page.locator("[data-aiopt]").first.click()
            page.wait_for_timeout(1800)
            page.evaluate("()=>document.querySelectorAll('[data-aiopt]').forEach(e=>e.removeAttribute('data-aiopt'))")
        if picked():
            log("  AI declaration set (attempt %d)" % (r + 1))
            return
        log("  attempt %d did not stick, retrying" % (r + 1))
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
    raise Abort("AI declaration could not be set; not posting")


def set_schedule(page, when):
    """Turn on the schedule switch (several click strategies, verified by the date box
    appearing), then type the time and read it back."""
    def sched_on():
        return page.eval_on_selector_all("input", "els => els.some(e => /^20\\d\\d-/.test(e.value||''))")

    found = page.evaluate("""(lb) => {
        const sp = Array.from(document.querySelectorAll('span,div,label'))
            .find(e => e.childElementCount === 0 && e.textContent.trim() === lb);
        if (!sp) return null;
        const wrap = sp.closest('.custom-switch-wrapper') || sp.parentElement.parentElement || sp.parentElement;
        const sw = wrap.querySelector('.d-switch') || wrap.querySelector('[class*=switch]') ||
                   wrap.querySelector('input[type=checkbox]');
        if (!sw) return null;
        sw.setAttribute('data-sched-sw','1');
        return sw.className || sw.tagName;
    }""", L_SCHEDULE)
    log("  schedule switch: %s" % (found or "NOT FOUND"))
    for how in ("scroll+click", "force-click", "js-dispatch", "wrapper-click"):
        if sched_on():
            break
        try:
            loc = page.locator("[data-sched-sw]").first
            if how == "scroll+click":
                loc.scroll_into_view_if_needed()
                page.wait_for_timeout(400)
                loc.click(timeout=4000)
            elif how == "force-click":
                loc.click(force=True, timeout=4000)
            else:
                page.evaluate("""(wrapper) => {
                    let el=document.querySelector('[data-sched-sw]'); if(!el) return;
                    if (wrapper) { el = el.parentElement; if (!el) return; }
                    for(const t of ['pointerdown','mousedown','pointerup','mouseup','click'])
                      el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}));
                }""", how == "wrapper-click")
        except Exception as e:
            log("  %s failed: %s" % (how, str(e).splitlines()[0][:60]))
        page.wait_for_timeout(1800)
        log("  %s -> date box visible=%s" % (how, sched_on()))
    page.wait_for_timeout(800)
    idx = page.eval_on_selector_all("input", "els => els.findIndex(e => /^20\\d\\d-/.test(e.value||''))")
    if idx is None or idx < 0:
        raise Abort("Schedule switch on, but no date/time input appeared")
    box = page.locator("input").nth(idx)
    box.click()
    box.fill(when)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(1500)
    now = page.locator("input").nth(idx).input_value()
    if not now.startswith(when[:16]):
        raise Abort("Schedule not set: wanted %s, got %s" % (when, now))


def close_pickers(page):
    """The calendar popup stays open after typing the time and covers the submit bar."""
    for _ in range(4):
        if page.evaluate(PICKER_OPEN_JS):
            break
        page.keyboard.press("Escape")
        page.mouse.click(180, 400)          # empty area on the left
        page.wait_for_timeout(700)


def click_submit(page, label):
    """Find and click the bottom submit button. It sits in a custom element with a closed
    shadow root, so: DOM search (incl. open shadow roots) -> hit-test scan -> pixel search."""
    found = page.evaluate("""(lb) => {
        const all = [];
        (function collect(root){
            root.querySelectorAll('*').forEach(e => { all.push(e); if (e.shadowRoot) collect(e.shadowRoot); });
        })(document);
        const hit = all.filter(e => e.childElementCount === 0 && e.textContent.trim() === lb &&
                                    !(e.closest && e.closest('.custom-switch-wrapper')));
        let best = null, by = -1;
        for (const e of hit) {
            const r = e.getBoundingClientRect();
            if (r.width < 20 || r.height < 10) continue;
            if (r.top > by) { by = r.top; best = e; }
        }
        if (!best) return 0;
        let n = best;
        for (let i = 0; i < 3 && n.parentElement; i++) {
            if (getComputedStyle(n).cursor === 'pointer') break;
            n = n.parentElement;
        }
        n.setAttribute('data-submit-btn','1');
        return hit.length;
    }""", label)
    if found and page.locator("[data-submit-btn]").count():
        btn = page.locator("[data-submit-btn]").first
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        try:
            btn.click(timeout=8000)
        except Exception:
            btn.click(force=True, timeout=8000)
        page.wait_for_timeout(9000)
        return True

    vp = page.evaluate("() => ({width: innerWidth, height: innerHeight})")
    hit = page.evaluate("""([lb, W, H]) => {
        for (let y = H - 8; y > H - 140; y -= 6) {
            for (let x = Math.round(W*0.25); x < Math.round(W*0.80); x += 8) {
                const el = document.elementFromPoint(x, y);
                if (!el) continue;
                const t = (el.textContent || '').trim();
                if (t === lb && !el.closest('.custom-switch-card') && !el.closest('.custom-switch-wrapper'))
                    return {x: x, y: y};
            }
        }
        return null;
    }""", [label, vp["width"], vp["height"]])
    if hit:
        log("    hit-test found the button at (%d,%d)" % (hit["x"], hit["y"]))
        page.mouse.click(hit["x"], hit["y"])
        page.wait_for_timeout(9000)
        return True

    host = page.evaluate("""() => {
        const h = document.querySelector('xhs-publish-btn');
        if (!h) return null;
        const r = h.getBoundingClientRect();
        return {top: r.top, h: r.height};
    }""")
    if not host:
        return False
    from PIL import Image
    im = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    sw, sh = im.size
    kx, ky = sw / float(vp["width"]), sh / float(vp["height"])
    y0 = int(host["top"] * ky) + 4
    y1 = min(sh - 2, int((host["top"] + host["h"]) * ky) - 4)
    yy = (y0 + y1) // 2
    px = im.load()
    xs = [x for x in range(sw) if px[x, yy][0] > 200 and px[x, yy][1] < 90 and px[x, yy][2] < 110]
    if not xs:
        log("    no red button pixels in the submit bar (y=%d)" % yy)
        return False
    cx, cy = int(sum(xs) / len(xs) / kx), int(yy / ky)
    log("    pixel search found the red button at (%d,%d)" % (cx, cy))
    page.mouse.click(cx, cy)
    page.wait_for_timeout(9000)
    return True


def after_failure_check(page, title, base=None):
    """After an abort/error, find out whether the note exists online anyway."""
    try:
        left = dupcheck.fetch_titles(page=page, base=base)
        if left is None:
            log("Could not read the note list. Do NOT assume nothing was posted; run dupcheck.py first.")
            return None
        n = len([t for t, _ in left if dupcheck.norm(t) == dupcheck.norm(title)])
        if n:
            log(u"The run stopped, but %d note(s) titled '%s' already exist online. Do NOT re-run; "
                u"check that note first." % (n, title))
            return n
        log("Checked: the note is not online. Safe to fix and run again.")
        return 0
    except Exception as e:
        log("Post-failure check itself failed (%s). Run dupcheck.py before re-running." % type(e).__name__)
        return None


def run(job, dry, profile, urls, dry_wait):
    kind = job["type"]
    files = [job["video"]] if kind == "video" else list(job.get("images") or [])
    if not files:
        raise Abort("No files: set 'video' (type=video) or 'images' (type=image)")
    for f in files:
        if not os.path.isfile(f):
            raise Abort("File not found: %s" % f)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Abort("Playwright is not installed. Run: pip install -r requirements.txt, then python -m playwright install chromium")

    with sync_playwright() as p:
        ctx, page = browser.launch(p, profile, locale="zh-CN", stealth=False,
                                   viewport={"width": 1440, "height": 900})
        page.set_default_timeout(30000)
        try:
            # The only source of truth for "already posted?" is Note Manager online,
            # never a local list. Check before every post.
            log("Duplicate check: reading Note Manager ...")
            existing = dupcheck.fetch_titles(page=page, base=urls["base"])
            ok, why = dupcheck.check_before_publish(job["title"], existing)
            log("  " + why)
            if not ok:
                raise Abort("Duplicate check did not pass")

            log("Opening the publish page ...")
            page.goto(urls["publish"], wait_until="domcontentloaded", timeout=120000)
            body = u""
            for _ in range(15):          # wait until loaded (max ~75 s), do not rely on a fixed sleep
                page.wait_for_timeout(5000)
                try:
                    body = page.inner_text("body")
                except Exception:
                    continue
                if L_UPLOAD_VIDEO in body:
                    break
            if L_UPLOAD_VIDEO not in body:
                out = ("/login" in page.url) or (L_LOGIN_QR in body) or (L_LOGIN_PHONE in body)
                raise Abort("Publish page not reached (%s)" % (
                    "logged out -> run login.py" if out else "no logout signs; page did not load, try again"))

            if kind == "image":
                log("Switching to the image-note tab ...")
                click_text(page, L_UPLOAD_IMAGE, "data-tab-img")
                page.wait_for_timeout(6000)

            log("Uploading %d file(s) ..." % len(files))
            file_input(page, kind).set_input_files(files)
            page.wait_for_selector('[contenteditable="true"]', timeout=180000)
            page.wait_for_timeout(10000)

            log("Title ...")
            ti = page.locator("input[placeholder*='%s']" % L_TITLE_PH).first
            ti.click()
            ti.fill(job["title"])
            if ti.input_value() != job["title"]:
                raise Abort(u"Title did not stick: wanted '%s', got '%s'" % (job["title"], ti.input_value()))

            body_paras = job["body"]
            log("Body, %d paragraph(s) ..." % len(body_paras))
            editor = page.locator('[contenteditable="true"]').first
            editor.click()                   # a real click is needed for focus / Enter to split paragraphs
            for para in body_paras:
                page.keyboard.type(para, delay=12)
                page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            paras = page.eval_on_selector('[contenteditable="true"]',
                                          "e => Array.from(e.children).map(c => c.innerText)")
            real = [x for x in paras if x.strip()]
            if len(real) < len(body_paras):
                raise Abort("Paragraph count mismatch: wanted %d, got %d" % (len(body_paras), len(real)))
            for i, para in enumerate(body_paras):
                if para not in real[i]:
                    raise Abort(u"Paragraph %d mismatch:\n  wanted %s\n  got    %s" % (i + 1, para, real[i]))

            tags = job.get("tags") or []
            log(u"Topics: %s" % u" ".join(tags))
            for w in tags:
                add_tag(page, w)

            if job.get("aigc", True):
                set_ai_declaration(page)

            if job.get("schedule"):
                log("Schedule %s ..." % job["schedule"])
                set_schedule(page, job["schedule"])

            if dry:
                browser.shot(page, LOGS, "dry", full_page=True)
                log("--dry: everything filled in, NOT posting. Close the window when you are done looking.")
                page.wait_for_timeout(int(float(dry_wait) * 1000))
                return 0

            log("Submitting ...")
            close_pickers(page)
            label = L_SCHEDULE if job.get("schedule") else L_PUBLISH
            if not click_submit(page, label):
                raise Abort("Submit button not found at the bottom of the page")
            if not (("published=true" in page.url) or ("/publish/success" in page.url)):
                raise Abort("Clicked submit but no success page; current %s" % page.url)
            log("Submitted.")

            log("Verifying in Note Manager ...")
            page.goto(urls["manager"], wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(12000)
            mgr = page.inner_text("body")
            if job["title"] not in mgr:
                raise Abort("Note not found in Note Manager; the submit may not have been saved")
            log(u"Found in the list: %s" % job["title"])
            if job.get("schedule") and job["schedule"][:16] not in mgr:
                log("Scheduled time %s not visible in the list; please confirm by hand." % job["schedule"])
            after = dupcheck.fetch_titles(page=page, base=urls["base"])
            if after is not None:
                same = [t for t, _ in after if dupcheck.norm(t) == dupcheck.norm(job["title"])]
                if len(same) > 1:
                    log(u"%d notes titled '%s' are online now. Please delete the extra one by hand."
                        % (len(same), job["title"]))
                    return 4
                log("Post-check: exactly one note with this title (%d notes total)." % len(after))
            return 0

        except Abort as e:
            log("ABORTED: %s" % e)
            browser.shot(page, LOGS, "abort", full_page=True)
            return 5 if after_failure_check(page, job["title"], urls["base"]) else 2
        except Exception as e:
            log("ERROR: %s: %s" % (type(e).__name__, str(e)[:300]))
            browser.shot(page, LOGS, "error", full_page=True)
            return 5 if after_failure_check(page, job["title"], urls["base"]) else 3
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def main():
    pos, flags, opt = jobfile.parse_args(sys.argv[1:], flags=("--dry",),
                                         options=("--profile", "--base", "--dry-wait"))
    if not pos:
        print(__doc__)
        return 1
    job = jobfile.load_job(pos[0], "xiaohongshu")
    job.setdefault("type", "video" if job.get("video") else "image")
    if not job.get("body"):
        job["body"] = job.get("caption", "")
    if isinstance(job["body"], str):
        job["body"] = [x.strip() for x in job["body"].split("\n") if x.strip()]
    jobfile.require(job, "title", "body")
    log(u"Job: %s (%s, %d paragraph(s), %d topic(s), schedule %s)"
        % (job["title"], job["type"], len(job["body"]), len(job.get("tags") or []),
           job.get("schedule") or "none"))
    profile = opt.get("--profile") or os.path.join(HERE, "_profile")
    urls = xhs_urls.urls(opt.get("--base"))
    try:
        return run(job, "--dry" in flags, profile, urls, opt.get("--dry-wait", 600))
    except Abort as e:
        log("ABORTED: %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
