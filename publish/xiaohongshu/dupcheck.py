# -*- coding: utf-8 -*-
"""Xiaohongshu duplicate check - READ ONLY (never deletes, edits or posts).

Two uses:
  1. Standalone:  python dupcheck.py [--profile DIR] [--base URL]
     Reads every note title in Note Manager (published + scheduled + drafts) and prints
     groups of identical or very similar titles.
  2. Imported by publish.py: blocks a post whose title already exists, and re-checks
     after posting / after an abort ("abort" does not mean "not posted").

Similarity = character-set overlap after removing punctuation and spaces. A high score is a
hint for a human to look at, never a reason to delete anything automatically.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from common import jobfile, browser  # noqa: E402
import xhs_urls  # noqa: E402

SIM_WARN = 0.72

PUNCT = re.compile(u"[\\s，。！？、；：（）()\\[\\]「」『』…—－\\-~～·,.!?;:\"'’“”]+")
# video duration badges ("00:13") and pure numbers are not titles
DUR = re.compile(u"^(\\d{1,2}:\\d{2}(:\\d{2})?|\\d+)$")
# status badges printed before the title on note cards (Chinese UI text):
# only-me, scheduled, under review, rejected, published, review failed, partly visible,
# private, draft
BADGE = set([u"仅自己可见", u"定时发布", u"审核中", u"未通过", u"已发布",
             u"审核未通过", u"部分可见", u"私密", u"草稿"])
DATE = re.compile(u"^\\d{4}-\\d{2}-\\d{2}")


def norm(s):
    return PUNCT.sub(u"", (s or u"").strip())


def sim(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) * 1.0 / len(sa | sb)


def fetch_titles(page=None, profile=None, base=None):
    """Return [(title, status)] from Note Manager, or None if nothing could be read."""
    from playwright.sync_api import sync_playwright
    mgr = xhs_urls.urls(base)["manager"]

    def _scrape(pg):
        pg.goto(mgr, wait_until="domcontentloaded", timeout=120000)
        pg.wait_for_timeout(12000)
        # Infinite scroll lives on the inner div.content, not on window.
        # Scroll until the card count stops growing.
        last, stall = 0, 0
        for _ in range(80):
            n = len(pg.query_selector_all(".note-card"))
            if n == last:
                stall += 1
                if stall >= 4:
                    break
            else:
                stall, last = 0, n
            pg.evaluate("""() => {
              const c = document.querySelector('div.content');
              if (c) c.scrollTop = c.scrollHeight;
              else window.scrollTo(0, document.body.scrollHeight);
            }""")
            pg.wait_for_timeout(1600)
        els = pg.query_selector_all(".note-card")
        if not els:
            return None
        out = []
        for e in els:
            lines = [x.strip() for x in (e.inner_text() or u"").split("\n") if x.strip()]
            real = [x for x in lines if not DUR.match(x) and x not in BADGE and not DATE.match(x)]
            if not real:
                continue
            badge = [x for x in lines if x in BADGE or DATE.match(x)]
            out.append((real[0], u" ".join(badge[:3])[:46]))
        try:
            m = re.search(u"全部\\s*(\\d+)", pg.inner_text("body"))     # "All N" counter
            if m and len(out) < int(m.group(1)):
                print("Warning: page says %s notes, only %d were read; the result covers "
                      "only those." % (m.group(1), len(out)))
        except Exception:
            pass
        return out

    if page is not None:
        return _scrape(page)
    with sync_playwright() as p:
        ctx, pg = browser.launch(p, profile or os.path.join(HERE, "_profile"), locale="zh-CN",
                                 stealth=False, viewport={"width": 1440, "height": 900})
        try:
            return _scrape(pg)
        finally:
            ctx.close()


def find_dups(titles):
    hits = []
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            a, b = titles[i], titles[j]
            na, nb = norm(a[0]), norm(b[0])
            if not na or not nb:
                continue
            if na == nb:
                hits.append(("identical", a, b, 1.0))
            else:
                s = sim(na, nb)
                if s >= SIM_WARN:
                    hits.append(("similar", a, b, s))
    hits.sort(key=lambda x: -x[3])
    return hits


def check_before_publish(title, existing):
    """Return (allowed, message). If the list cannot be read, posting is NOT allowed."""
    if existing is None:
        return False, "Could not read the note list; cannot check for duplicates -> not posting"
    nt = norm(title)
    for t, st in existing:
        if norm(t) == nt:
            return False, u"A note titled '%s' (%s) already exists -> not posting" % (t, st)
    near = [(t, sim(nt, norm(t))) for t, _ in existing]
    near = sorted([x for x in near if x[1] >= SIM_WARN], key=lambda x: -x[1])
    if near:
        return True, (u"Similar title exists: '%s' (%.0f%% overlap). Posting, but please look "
                      u"after it is done." % (near[0][0], near[0][1] * 100))
    return True, "Duplicate check passed (%d notes online, none identical or similar)" % len(existing)


def main():
    jobfile.setup_console()
    _, _, opt = jobfile.parse_args(sys.argv[1:], options=("--profile", "--base"))
    titles = fetch_titles(profile=opt.get("--profile"), base=opt.get("--base"))
    if titles is None:
        print("Could not read any note cards (page layout may have changed). "
              "This does NOT mean there are no duplicates.")
        return 2
    print("Read %d notes:\n" % len(titles))
    for t, st in titles:
        print(u"  - %-38s | %s" % (t[:38], st[:40]))
    hits = find_dups(titles)
    print("")
    if not hits:
        print("No identical titles and no pairs above %.0f%% similarity." % (SIM_WARN * 100))
        return 0
    print("%d pair(s) to review:\n" % len(hits))
    for lvl, a, b, s in hits:
        print(u"  [%s %.0f%%]" % (lvl, s * 100))
        print(u"     A: %s  %s" % (a[0], a[1][:40]))
        print(u"     B: %s  %s" % (b[0], b[1][:40]))
    print("\n'similar' is a hint, not a verdict. You decide what to delete; this script never deletes.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
