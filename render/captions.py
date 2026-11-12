# -*- coding: utf-8 -*-
"""Subtitles: transcribe -> SRT, burn SRT into a video, or feed SRT into the HyperFrames template.

    python captions.py transcribe voice.mp4 out.srt --lang en [--max-chars 32] [--model small]
    python captions.py burn video.mp4 subs.srt out.mp4 [--font "Noto Sans SC"] [--size 72] [--bottom 28]
    python captions.py tohtml subs.srt hyperframes/vertical-slideshow/index.html

transcribe  Local speech-to-text with faster-whisper (pip install faster-whisper). Words are
            grouped into one-line cues of at most --max-chars characters; a pause longer than
            --pause seconds (default 0.6) or a sentence end also starts a new cue.
            Always proof-read the SRT: names, numbers and product words are often wrong.
            Use --lang zh / ja / ko for CJK languages (no spaces between words).
burn        Hard-burns subtitles with ffmpeg. The SRT is converted to an .ass file whose
            canvas equals the video size, so --size is in real pixels. --bottom is the
            distance of the text baseline from the bottom edge, in % of the height
            (default 28 = above the area most apps cover with buttons and captions).
            --font must be installed on this computer (for Chinese e.g. "Noto Sans SC").
tohtml      Writes the cues into the HyperFrames template (between CAPTIONS:BEGIN and
            CAPTIONS:END markers), so the template shows them in sync.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CJK = ("zh", "ja", "ko", "yue")
END_PUNCT = u".!?。！？…"
STRIP_PUNCT = u"，。、,.!?！？；;：:"


def opts(argv, defaults):
    o, pos, i = dict(defaults), [], 0
    while i < len(argv):
        if argv[i] in o and i + 1 < len(argv):
            o[argv[i]] = argv[i + 1]
            i += 2
        elif argv[i].startswith("--"):
            raise SystemExit("Unknown option: %s" % argv[i])
        else:
            pos.append(argv[i])
            i += 1
    return pos, o


def ts(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def parse_srt(path):
    txt = io.open(path, encoding="utf-8-sig").read().replace("\r", "")
    cues = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = [x for x in block.split("\n") if x.strip()]
        tl = [x for x in lines if "-->" in x]
        if not tl:
            continue
        a, b = [x.strip() for x in tl[0].split("-->")]

        def sec(v):
            h, m, rest = v.replace(".", ",").split(":")
            s, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
        body = [x.strip() for x in lines[lines.index(tl[0]) + 1:]]
        cues.append({"start": sec(a), "end": sec(b.split()[0]), "text": " ".join(body)})
    return cues


def write_srt(cues, path):
    with io.open(path, "w", encoding="utf-8") as f:
        for n, c in enumerate(cues, 1):
            f.write(u"%d\n%s --> %s\n%s\n\n" % (n, ts(c["start"]), ts(c["end"]), c["text"]))


# transcribe ---------------------------------------------------------------------
def cmd_transcribe(argv):
    pos, o = opts(argv, {"--lang": None, "--max-chars": None, "--model": "small", "--pause": "0.6", "--ffmpeg": None})
    if len(pos) < 2:
        print(__doc__)
        return 1
    from speech_review import recognize
    src, out = pos
    lang = o["--lang"]
    cjk = (lang or "").split("-")[0] in CJK
    max_chars = int(o["--max-chars"] or (14 if cjk else 32))
    pause = float(o["--pause"])
    joiner = u"" if cjk else u" "
    try:
        segs, info = recognize(src, o["--model"], lang, o["--ffmpeg"], word_timestamps=True, vad_filter=True)
    except (RuntimeError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    words = [w for s in segs for w in (s.words or [])]
    print("language %s, %d words" % (getattr(info, "language", lang), len(words)))
    cues, cur = [], []

    def flush():
        if not cur:
            return
        text = joiner.join(w.word.strip() for w in cur).strip()
        if cjk:
            text = text.strip(STRIP_PUNCT)
        if text:
            cues.append({"start": cur[0].start, "end": cur[-1].end, "text": text})
        del cur[:]

    for w in words:
        word = w.word.strip()
        if not word:
            continue
        if cur:
            gap = w.start - cur[-1].end
            length = len(joiner.join(x.word.strip() for x in cur + [w]))
            if gap > pause or length > max_chars:
                flush()
        cur.append(w)
        if word[-1] in END_PUNCT:
            flush()
    flush()
    write_srt(cues, out)
    print("Wrote %d cues to %s - proof-read it before use." % (len(cues), out))
    return 0


# burn ---------------------------------------------------------------------------
def probe_size(video):
    fp = os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"
    p = subprocess.run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "json", video], capture_output=True)
    s = json.loads((p.stdout or b"{}").decode("utf-8", "replace"))["streams"][0]
    return int(s["width"]), int(s["height"])


def ass_time(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, cs)


def safe_subtitle_text(text, width, height, size, bottom, outline=8, max_lines=2, allow_shrink=True):
    """Conservative two-line ASS layout; never silently crop unreadable cues."""
    import math
    values = [width, height, size, bottom, outline]
    if not all(math.isfinite(float(value)) for value in values) or width <= 120 or size < 24 or outline < 0 or not 0 <= bottom < height:
        raise ValueError('SUBTITLE_LAYOUT_INVALID: invalid canvas, size or margins')
    # One em per character is intentionally conservative for Latin and CJK fonts.
    clean = text.replace('\\', ' ').replace('{', '(').replace('}', ')')
    top = min(int(size), int(height / 8))
    for fitted in range(top, 23 if allow_shrink else top - 1, -1):
        capacity = int((width - 120 - 2 * outline) / (fitted * 1.15))
        if capacity < 1: continue
        lines = []
        for paragraph in clean.splitlines() or ['']:
            paragraph = paragraph.strip()
            while len(paragraph) > capacity:
                cut = paragraph.rfind(' ', 0, capacity + 1)
                if cut < capacity // 2: cut = capacity
                lines.append(paragraph[:cut].strip())
                paragraph = paragraph[cut:].strip()
            if paragraph: lines.append(paragraph)
        if len(lines) <= max_lines and len(lines) * fitted * 1.4 + outline * 2 < height - bottom - 60:
            return '{\\fs%d}' % fitted + r'\N'.join(lines)
    raise ValueError('SUBTITLE_TOO_LONG: split this cue into shorter timed cues; text does not fit two readable lines')


def cmd_burn(argv):
    pos, o = opts(argv, {"--font": "Arial", "--size": "72", "--bottom": "28",
                         "--outline": "8", "--ffmpeg": None})
    if len(pos) < 3:
        print(__doc__)
        return 1
    video, srt, out = [os.path.abspath(x) for x in pos]
    w, h = probe_size(video)
    margin_v = int(h * float(o["--bottom"]) / 100.0)
    head = (u"[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n\n"
            u"[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            u"BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
            u"Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            u"Style: Default,%s,%s,&H00FFFFFF,&H00FFFFFF,&H00141414,&H00000000,-1,0,0,0,100,100,0,0,1,%s,0,2,60,60,%d,1\n\n"
            u"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (w, h, o["--font"], o["--size"], o["--outline"], margin_v))
    lines = [u"Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (ass_time(c["start"]), ass_time(c["end"]),
                                                        safe_subtitle_text(c["text"], w, h, float(o["--size"]), margin_v, float(o["--outline"])))
             for c in parse_srt(srt)]
    ass_dir = os.path.dirname(out) or "."
    ass_name = os.path.splitext(os.path.basename(out))[0] + "_subs.ass"
    with io.open(os.path.join(ass_dir, ass_name), "w", encoding="utf-8") as f:
        f.write(head + u"\n".join(lines) + u"\n")
    ff = o["--ffmpeg"] or os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
    # Run inside the .ass folder and pass a bare file name: avoids escaping drive letters
    # and backslashes inside the ffmpeg filter string.
    p = subprocess.run([ff, "-hide_banner", "-y", "-i", video, "-vf", "ass=%s" % ass_name,
                        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "copy", "-movflags", "+faststart", out], cwd=ass_dir, capture_output=True)
    if p.returncode != 0:
        print((p.stderr or b"").decode("utf-8", "replace")[-1500:])
        return 2
    print("Done: %s (style file %s kept next to it)" % (out, ass_name))
    return 0


# tohtml -------------------------------------------------------------------------
BEGIN, END = "/* CAPTIONS:BEGIN */", "/* CAPTIONS:END */"


def cmd_tohtml(argv):
    pos, _ = opts(argv, {})
    if len(pos) < 2:
        print(__doc__)
        return 1
    srt, html = pos
    cues = [{"start": round(c["start"], 3), "end": round(c["end"], 3), "text": c["text"]} for c in parse_srt(srt)]
    s = io.open(html, encoding="utf-8").read()
    a, b = s.find(BEGIN), s.find(END)
    if a < 0 or b < a:
        print("Markers %s ... %s not found in %s" % (BEGIN, END, html))
        return 2
    block = BEGIN + "\n      const CAPTIONS = " + json.dumps(cues, ensure_ascii=False, indent=2) + ";\n      " + END
    s = s[:a] + block + s[b + len(END):]
    io.open(html, "w", encoding="utf-8", newline="\n").write(s)
    print("Wrote %d cues into %s. Make sure the root data-duration covers the last cue (%.2fs)."
          % (len(cues), html, cues[-1]["end"] if cues else 0))
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("transcribe", "burn", "tohtml"):
        print(__doc__)
        return 1
    return {"transcribe": cmd_transcribe, "burn": cmd_burn, "tohtml": cmd_tohtml}[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
