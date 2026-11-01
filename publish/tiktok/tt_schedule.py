# -*- coding: utf-8 -*-
"""TikTok Studio "Schedule" control: sets the scheduled date/time. Used by publish.py.

This module never submits the post; it only sets the schedule and reads it back.

How the control behaves (observed on the web uploader; may change without notice):
 1. "Schedule" is a radio input[value="schedule"]. JS .click() is ignored (React only
    accepts trusted events), so a real mouse click at its coordinates is used.
 2. Ticking it may open a permission dialog ("Allow TikTok to save your video for
    scheduling?"). Until "Allow" is clicked, a modal overlay covers the page and every
    click lands on the overlay. Only the button whose text is exactly "Allow" is clicked.
 3. Two UI versions exist:
    - older: two read-only text inputs (HH:MM and YYYY-MM-DD) that open pickers;
    - newer: two Picker dropdowns ("Select date" / "Select time").
    Both are handled; read-back works for both.
 4. Older calendar: cells are span.day in date order and today's cell has "selected".
    Target index = today's index + day difference (robust across month ends, where the
    trailing cells 1/2/3 belong to the next month). If the target is off-screen, the
    "next month" arrow is clicked and the month's day-1 cell is used as the anchor.
    Time picker: left column hours 00-23, right column minutes 00-55 in 5-minute
    steps; columns are told apart by x position (both columns contain e.g. "20").
"""
import datetime
import re


class ScheduleError(Exception):
    pass


JS_RADIO_BOX = """() => {
    const i = document.querySelector('input[value="schedule"]');
    if (!i) return null;
    i.scrollIntoView({block: 'center'});
    const r = i.getBoundingClientRect();
    return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
            checked: i.checked};
}"""

JS_ALLOW = """() => {
    // English UI says "Allow", Chinese UI says the Chinese word for it
    const bs = [...document.querySelectorAll('button')]
        .filter(b => ['\u5141\u8bb8', 'Allow'].includes(b.textContent.trim())
                     && b.getBoundingClientRect().width > 0);
    if (bs.length !== 1) return {n: bs.length};
    const r = bs[0].getBoundingClientRect();
    return {n: 1, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
}"""

JS_OVERLAY = "() => !!document.querySelector('.TUXModal-overlay')"

JS_CHECKED = """() => {
    const i = document.querySelector('input[value="schedule"]');
    return i ? i.checked : false;
}"""

JS_BOX = """(kind) => {
    // date box shows either "2026-10-22" (older UI) or "Oct 22, 2026" (newer UI)
    const pat = kind === 'date' ? /^(\\d{4}-\\d{1,2}-\\d{1,2}|[A-Z][a-z]{2,8} \\d{1,2}, \\d{4})$/ : /^\\d{1,2}:\\d{2}$/;
    const i = [...document.querySelectorAll('input')].find(x => pat.test(x.value || ''));
    if (!i) return null;
    const r = i.getBoundingClientRect();
    return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), val: i.value};
}"""

# calendar cells in DOM order, flagged selected / valid
JS_DAYS = """() => {
    const cells = [...document.querySelectorAll('span.day')]
        .filter(e => e.getBoundingClientRect().width > 0);
    return cells.map((e, n) => {
        const r = e.getBoundingClientRect();
        return {n: n, t: e.textContent.trim(),
                sel: /(^|\\s)selected(\\s|$)/.test(e.className),
                valid: /(^|\\s)valid(\\s|$)/.test(e.className),
                x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
    });
}"""

# Calendar header ("September / 2026" or the Chinese "YYYY<year>M<month>" form) and the
# "next month" arrow, found geometrically: same row as the header, to its right,
# within the horizontal span of the day cells.
JS_CAL_HEAD = """() => {
    const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const days = [...document.querySelectorAll('span.day')].filter(vis);
    if (!days.length) return {err: 'no days'};
    const rs = days.map(e => e.getBoundingClientRect());
    const top = Math.min(...rs.map(r => r.top));
    const left = Math.min(...rs.map(r => r.left)) - 40;
    const right = Math.max(...rs.map(r => r.right)) + 40;
    const re = /^([A-Za-z]+)\\s*\\/\\s*(\\d{4})$|^(\\d{4})\\s*\u5e74\\s*(\\d{1,2})\\s*\u6708$/;
    let best = null;
    for (const e of document.querySelectorAll('div,span,p,h1,h2,h3,h4,button,strong')) {
        const t = (e.textContent || '').replace(/\\s+/g, ' ').trim();
        if (!re.test(t)) continue;
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.bottom > top || top - r.bottom > 200) continue;
        if (r.left < left || r.right > right) continue;
        const a = r.width * r.height;
        if (!best || a < best.a) best = {r: r, t: t, a: a};
    }
    if (!best) return {err: 'no title'};
    const cy = best.r.top + best.r.height / 2;
    let arrow = null;
    for (const e of document.querySelectorAll('*')) {
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.height === 0 || r.width > 60 || r.height > 60) continue;
        if (Math.abs(r.top + r.height / 2 - cy) > 15) continue;
        if (r.left < best.r.right || r.right > right) continue;
        const a = r.width * r.height;
        if (!arrow || a > arrow.a) arrow = {a: a, x: Math.round(r.left + r.width / 2),
            y: Math.round(r.top + r.height / 2), tag: e.tagName};
    }
    return {title: best.t, next: arrow};
}"""

# newer UI: Picker dropdowns (first = date, second = time)
JS_PICKERS = """() => [...document.querySelectorAll('.schedule-picker .Picker__value, .scheduled-picker .Picker__value')]
    .map(v => { const t = v.closest('[role=combobox]') || v.parentElement; const r = t.getBoundingClientRect();
                return {t: (v.textContent || '').trim(), x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
                        exp: t.getAttribute('aria-expanded')}; })"""

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}


def _parse_head(t):
    """'September / 2026' or the Chinese year/month header -> (2026, 9); None if unknown."""
    m = re.match(r"^([A-Za-z]+)\s*/\s*(\d{4})$", t or "")
    if m and m.group(1).lower() in _MONTHS:
        return int(m.group(2)), _MONTHS[m.group(1).lower()]
    m = re.match(u"^(\\d{4})\\s*\u5e74\\s*(\\d{1,2})\\s*\u6708$", t or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


JS_CAL_OPEN = """() => [...document.querySelectorAll('span.day')]
    .filter(e => e.getBoundingClientRect().width > 0).length > 0"""

# A collapsed time picker keeps its width but has height 0, and there can be several
# containers on the page. Treat it as open if any container is visible with height,
# or if at least 5 time options with height are inside the viewport.
JS_TIME_OPEN = """() => {
    const cs = [...document.querySelectorAll('[class*="time-picker-container"]')];
    if (cs.some(c => !/timepicker-invisible/.test(c.className) && c.getBoundingClientRect().height > 0)) return true;
    const vis = [...document.querySelectorAll('span.tiktok-timepicker-option-text')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.height > 0 && r.bottom > 0 && r.top < innerHeight; });
    return vis.length >= 5;
}"""

# Returns click coordinates of the option row AFTER scrolling it into view; the list
# re-flows after each click, so coordinates are re-read right before clicking.
JS_OPT_INDEX = """([col, text]) => {
    const all = [...document.querySelectorAll('span.tiktok-timepicker-option-text')];
    const xs = [...new Set(all.map(e => Math.round(e.getBoundingClientRect().x)))]
        .sort((a, b) => a - b);
    if (xs.length < 2) return {err: 'columns=' + xs.length};
    const wantX = xs[col];
    for (const e of all) {
        if (e.textContent.trim() !== text) continue;
        if (Math.abs(Math.round(e.getBoundingClientRect().x) - wantX) >= 12) continue;
        if (/is-active/.test(e.className)) return {active: true};
        // click the whole option row, not the inner text span
        const row = e.closest('[class*="timepicker-option"]:not([class*="option-text"])') || e;
        row.scrollIntoView({block: 'center'});
        const r = row.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return {err: 'row has no box'};
        return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
    }
    return {err: 'not found'};
}"""

JS_DAYBTN = """(label) => {
    const b = [...document.querySelectorAll('button.DatePicker__day')].find(x => (x.getAttribute('aria-label') || '').endsWith(label));
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
            dis: b.getAttribute('aria-disabled') === 'true' || b.disabled, lab: b.getAttribute('aria-label')};
}"""

JS_NEXTMONTH = """() => {
    const b = [...document.querySelectorAll('button.DatePicker__nav')].find(x => x.getAttribute('aria-label') === 'Next month');
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
}"""

JS_TIMEITEM = """([col, text]) => {
    const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const items = [...document.querySelectorAll('button.TimePicker__item')].filter(vis);
    const xs = [...new Set(items.map(e => Math.round(e.getBoundingClientRect().x)))].sort((a, b) => a - b);
    if (xs.length < 2) return {err: 'columns=' + xs.length};
    const want = xs[col];
    const hit = items.filter(e => Math.abs(Math.round(e.getBoundingClientRect().x) - want) < 12 && e.textContent.trim() === text);
    if (!hit.length) return {err: 'not found'};
    const b = hit[0];
    if (b.getAttribute('aria-selected') === 'true') return {active: true};
    b.scrollIntoView({block: 'center'});
    const r = b.getBoundingClientRect();
    return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
}"""

JS_TIMEPANEL_OPEN = """() => [...document.querySelectorAll('button.TimePicker__item')].some(e => e.getBoundingClientRect().height > 0)"""


def _norm_date(v):
    """Date box value -> 'YYYY-MM-DD' (accepts 'Oct 22, 2026'); returns input if unknown."""
    for f in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime((v or "").strip(), f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return v


def _click(pg, pt, wait=1200):
    pg.mouse.click(pt["x"], pt["y"])
    pg.wait_for_timeout(wait)


def ensure_schedule_mode(pg, log=print):
    """Tick "Schedule" and accept the scheduling permission dialog if it appears."""
    if pg.evaluate(JS_CHECKED):
        return
    b = pg.evaluate(JS_RADIO_BOX)
    if not b:
        raise ScheduleError("No 'Schedule' option on the page")
    _click(pg, b, 2500)
    if pg.evaluate(JS_OVERLAY):
        a = pg.evaluate(JS_ALLOW)
        if a.get("n") != 1:
            raise ScheduleError("Permission dialog opened, but found %s visible 'Allow' buttons "
                                "(expected exactly 1). Stopping." % a.get("n"))
        log("    permission dialog: clicking 'Allow'")
        _click(pg, a, 3000)
    if not pg.evaluate(JS_CHECKED):
        raise ScheduleError("'Schedule' is still not selected after clicking")


def _flip_to_month(pg, target, log=print):
    """Click 'next month' until the header equals the target month (max 2 times).
    Returns (cells, index_of_target). Uses the month's day-1 cell as anchor."""
    want = (target.year, target.month)
    for _ in range(2):
        h = pg.evaluate(JS_CAL_HEAD)
        if h.get("err"):
            raise ScheduleError("Calendar header not found (%s)" % h["err"])
        cur = _parse_head(h.get("title"))
        if not cur:
            raise ScheduleError("Calendar header '%s' not understood" % h.get("title"))
        if cur == want:
            break
        if cur > want:
            raise ScheduleError("Calendar shows %s, already past target %s" % (h.get("title"), target))
        nx = h.get("next")
        if not nx:
            raise ScheduleError("No 'next month' arrow next to '%s'" % h.get("title"))
        log("    calendar '%s' -> next month" % h.get("title"))
        _click(pg, nx, 2000)
    h = pg.evaluate(JS_CAL_HEAD)
    if h.get("err") or _parse_head(h.get("title")) != want:
        raise ScheduleError("After flipping, header is '%s', not %d-%02d"
                            % (h.get("title") or h.get("err"), want[0], want[1]))
    cells = pg.evaluate(JS_DAYS)
    ones = [c["n"] for c in cells if c["t"] == "1"]
    if not ones:
        raise ScheduleError("No day 1 on this calendar page")
    idx = ones[0] + target.day - 1
    if idx >= len(cells):
        raise ScheduleError("Computed calendar index out of range")
    return cells, idx


def _ordinal(n):
    return "%d%s" % (n, "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def set_date_v2(pg, target, log=print):
    """Newer UI: open the date dropdown, click the day by aria-label, read back."""
    pk = pg.evaluate(JS_PICKERS)
    if len(pk) < 2:
        raise ScheduleError("Newer schedule UI: expected 2 dropdowns, got %s" % pk)
    if _norm_date(pk[0]["t"]) == target.strftime("%Y-%m-%d"):
        log("    date already %s" % pk[0]["t"])
        return
    _click(pg, pk[0], 2200)
    label = "%s %s, %d" % (target.strftime("%B"), _ordinal(target.day), target.year)
    btn = None
    for _ in range(3):
        btn = pg.evaluate(JS_DAYBTN, label)
        if btn:
            break
        nx = pg.evaluate(JS_NEXTMONTH)
        if not nx:
            raise ScheduleError("'%s' not in calendar and no 'Next month' button" % label)
        _click(pg, nx, 1500)
    if not btn:
        raise ScheduleError("'%s' not found after 3 month flips" % label)
    if btn["dis"]:
        raise ScheduleError("'%s' is disabled (platform does not allow it)" % btn["lab"])
    _click(pg, btn, 2000)
    got = pg.evaluate(JS_PICKERS)
    if not got or _norm_date(got[0]["t"]) != target.strftime("%Y-%m-%d"):
        raise ScheduleError("Date dropdown still shows %s" % (got[0]["t"] if got else None))
    log("    date -> %s" % got[0]["t"])


def set_date(pg, target, log=print):
    """target = datetime.date"""
    box = pg.evaluate(JS_BOX, "date")
    if not box:
        if pg.evaluate(JS_PICKERS):
            log("    newer schedule UI detected")
            return set_date_v2(pg, target, log)
        raise ScheduleError("Date box not found")
    if _norm_date(box["val"]) == target.strftime("%Y-%m-%d"):
        log("    date already %s" % box["val"])
        return
    today = datetime.datetime.strptime(_norm_date(box["val"]), "%Y-%m-%d").date()
    # The picker toggles: clicking it while open closes it. Check before clicking.
    if not pg.evaluate(JS_CAL_OPEN):
        _click(pg, box, 2500)
    if not pg.evaluate(JS_CAL_OPEN):
        _click(pg, box, 2500)
    if not pg.evaluate(JS_CAL_OPEN):
        raise ScheduleError("Calendar does not open")
    cells = pg.evaluate(JS_DAYS)
    sel = [c for c in cells if c["sel"]]
    if len(sel) != 1:
        raise ScheduleError("%d calendar cells marked selected; cannot anchor" % len(sel))
    delta = (target - today).days
    idx = sel[0]["n"] + delta
    if idx < 0 or idx >= len(cells):
        if delta < 0:
            raise ScheduleError("Target date is in the past (%d days)" % delta)
        cells, idx = _flip_to_month(pg, target, log)
    cell = cells[idx]
    if cell["t"] != str(target.day):
        raise ScheduleError("Computed cell shows '%s' but target day is %d; not clicking"
                            % (cell["t"], target.day))
    if not cell["valid"]:
        raise ScheduleError("%s is not selectable" % target)
    _click(pg, cell, 2000)
    got = pg.evaluate(JS_BOX, "date")
    if not got or _norm_date(got["val"]) != target.strftime("%Y-%m-%d"):
        raise ScheduleError("Date box still shows %s" % (got or {}).get("val"))
    log("    date -> %s" % got["val"])


def set_time_v2(pg, hh, mm, log=print):
    """Newer UI: open the time dropdown, click hour (left) and minute (right), read back."""
    want = "%s:%s" % (hh, mm)
    pk = pg.evaluate(JS_PICKERS)
    if pk[1]["t"] == want:
        log("    time already %s" % want)
        return
    for col, text, what in ((0, hh, "hour"), (1, mm, "minute")):
        if not pg.evaluate(JS_TIMEPANEL_OPEN):
            _click(pg, pg.evaluate(JS_PICKERS)[1], 2000)
        if not pg.evaluate(JS_TIMEPANEL_OPEN):
            raise ScheduleError("Time dropdown does not open")
        r = pg.evaluate(JS_TIMEITEM, [col, text])
        if r.get("err"):
            raise ScheduleError("%s '%s' not found (%s)" % (what, text, r["err"]))
        if r.get("active"):
            log("    %s already %s" % (what, text))
            continue
        pg.wait_for_timeout(600)
        r = pg.evaluate(JS_TIMEITEM, [col, text])     # re-read after scrolling
        if r.get("err"):
            raise ScheduleError("%s '%s' lost after scrolling (%s)" % (what, text, r["err"]))
        if not r.get("active"):
            _click(pg, r, 1500)
        log("    %s -> %s" % (what, text))
    if pg.evaluate(JS_TIMEPANEL_OPEN):
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(800)
    got = pg.evaluate(JS_PICKERS)[1]["t"]
    if got != want:
        raise ScheduleError("Time not set: wanted %s, dropdown shows %s" % (want, got))
    log("    time -> %s" % got)


def set_time(pg, hh, mm, log=print):
    box = pg.evaluate(JS_BOX, "time")
    if not box and pg.evaluate(JS_PICKERS):
        return set_time_v2(pg, hh, mm, log)
    if not box:
        raise ScheduleError("Time box not found")
    if box["val"] == "%s:%s" % (hh, mm):
        log("    time already %s" % box["val"])
        return
    # Right after setting the date the calendar may still be open; clicking the time
    # box would only close the calendar. Close it first.
    if pg.evaluate(JS_CAL_OPEN):
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(800)
    if pg.evaluate(JS_CAL_OPEN):
        pg.mouse.click(700, 250)      # click empty space
        pg.wait_for_timeout(1000)
    for _ in range(3):
        if pg.evaluate(JS_TIME_OPEN):
            break
        b = pg.evaluate(JS_BOX, "time") or box
        _click(pg, b, 2500)
        # toggle: wait a little before clicking again (another click would close it)
        for _w in range(3):
            if pg.evaluate(JS_TIME_OPEN):
                break
            pg.wait_for_timeout(1000)
    if not pg.evaluate(JS_TIME_OPEN):
        raise ScheduleError("Time picker does not open")
    for col, text, what in ((0, hh, "hour"), (1, mm, "minute")):
        if not pg.evaluate(JS_TIME_OPEN):      # it may collapse after the hour click
            b2 = pg.evaluate(JS_BOX, "time")
            if b2:
                _click(pg, b2, 2000)
        r = pg.evaluate(JS_OPT_INDEX, [col, text])
        if r.get("err"):
            raise ScheduleError("%s '%s' not found (%s)" % (what, text, r["err"]))
        if r.get("active"):
            log("    %s already %s" % (what, text))
            continue
        pg.wait_for_timeout(500)
        r2 = pg.evaluate(JS_OPT_INDEX, [col, text])
        if r2.get("active"):
            continue
        if r2.get("err"):
            raise ScheduleError("%s '%s' lost after scrolling (%s)" % (what, text, r2["err"]))
        _click(pg, r2, 1800)
        log("    %s -> %s" % (what, text))
    got = pg.evaluate(JS_BOX, "time")
    want = "%s:%s" % (hh, mm)
    if not got or got["val"] != want:
        raise ScheduleError("Time not set: wanted %s, now %s" % (want, (got or {}).get("val")))
    log("    time -> %s" % got["val"])


def readback(pg):
    """Both UI versions: return 'YYYY-MM-DD HH:MM', or None if unreadable."""
    gd = pg.evaluate(JS_BOX, "date")
    gt = pg.evaluate(JS_BOX, "time")
    if gd and gt:
        return "%s %s" % (_norm_date(gd["val"]), gt["val"])
    pk = pg.evaluate(JS_PICKERS)
    if len(pk) >= 2:
        return "%s %s" % (_norm_date(pk[0]["t"]), pk[1]["t"])
    return None


def apply(pg, when, log=print):
    """when = 'YYYY-MM-DD HH:MM' in the browser's local time. Raises ScheduleError on failure."""
    d, t = when.split(" ")
    target = datetime.datetime.strptime(d, "%Y-%m-%d").date()
    hh, mm = t.split(":")
    if int(mm) % 5 != 0:
        raise ScheduleError("TikTok minutes come in 5-minute steps; %s is not selectable" % t)
    ensure_schedule_mode(pg, log)
    set_date(pg, target, log)
    set_time(pg, hh, mm, log)
    rb = readback(pg)
    if rb != when:
        raise ScheduleError("Final read-back %s does not match %s" % (rb, when))
    return True
