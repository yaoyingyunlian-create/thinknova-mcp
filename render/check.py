# -*- coding: utf-8 -*-
"""Pre-publish check for a finished video. Exit code 0 = no FAIL, 2 = at least one FAIL.

    python check.py final.mp4
    python check.py final.mp4 --srt final.srt               # also check subtitle lines
    python check.py final.mp4 --sheet out_dir                # also write a 1-frame-per-second contact sheet
    python check.py final.mp4 --speech --lang en             # also transcribe and find long gaps without speech
    python check.py final.mp4 --film --outro-start 29 --lang zh

Options (defaults suit vertical short video):
    --width 1080 --height 1920   expected resolution (other vertical sizes = WARN, landscape = FAIL)
    --max-dur SEC                FAIL if longer (default: no limit; e.g. 60 / 180 for your platform)
    --min-fps 24
    --lufs -14 --lufs-tol 2      target integrated loudness (WARN outside the tolerance)
    --max-tp -1                  max true peak in dBTP (WARN above)
    --max-silence-pct 10         WARN if silent parts (< -40 dB for >= 0.6 s) exceed this share
    --min-cuts 3                 WARN if fewer scene changes are detected (0 disables)
    --max-chars N                subtitle: max characters per line (WARN above);
                                 default 16 for lines with CJK characters, 32 otherwise
    --max-lines 1                subtitle: max lines per cue (WARN above)
    --max-gap 3                  with --speech: WARN above this many seconds without speech
    --max-tail 4.5               with --speech: WARN above this many seconds after the last word
    --ffmpeg PATH                ffmpeg executable (default: "ffmpeg" on PATH or $FFMPEG)

What is checked:
  S1 spec        resolution, duration, frame rate, audio track present
  S2 opening     first 1.5 s is not a flat colour / near-black title card
  S3 audio       mean volume, share of silence, integrated loudness, true peak
  S4 cuts        number of scene changes (a single static shot is usually a weak short)
  S5 subtitles   (with --srt) characters per line, lines per cue
  S6 speech      (with --speech, needs faster-whisper) longest gap without speech, tail gap
  sheet          (with --sheet) contact sheet JPG for a quick visual review

FAIL (exit code 2) is reserved for technical problems: no video/audio stream, wrong
orientation, too long for --max-dur, frame rate too low, practically silent audio.
Everything about style (opening, cuts, silence share, subtitles, speech gaps) is only a WARN.
All thresholds are starting points. Tune them for your own platform and style.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILS, WARNS, INFO = [], [], []


def fail(code, msg):
    FAILS.append((code, msg))


def warn(code, msg):
    WARNS.append((code, msg))


def run(cmd):
    p = subprocess.run(cmd, capture_output=True)
    return (p.stdout or b"").decode("utf-8", "replace"), (p.stderr or b"").decode("utf-8", "replace")


def find_tool(name, given):
    if given:
        return given
    env = os.environ.get(name.upper())
    if env:
        return env
    return shutil.which(name) or name


def get_opts(argv):
    o = {"--width": "1080", "--height": "1920", "--max-dur": None, "--min-fps": "24",
         "--lufs": "-14", "--lufs-tol": "2", "--max-tp": "-1", "--max-silence-pct": "10",
         "--min-cuts": "3", "--max-chars": None, "--max-lines": "1", "--max-gap": "3",
         "--max-tail": "4.5", "--ffmpeg": None, "--ffprobe": None, "--srt": None,
         "--sheet": None, "--lang": None, "--model": "small", "--outro-start": None}
    flags = {"--speech", "--allow-silent", "--film"}
    pos, on, i = [], set(), 0
    while i < len(argv):
        a = argv[i]
        if a in o and i + 1 < len(argv):
            o[a] = argv[i + 1]
            i += 2
            continue
        if a in flags:
            on.add(a)
        elif a.startswith("--"):
            raise SystemExit("Unknown option: %s" % a)
        else:
            pos.append(a)
        i += 1
    return pos, on, o


# S1 ---------------------------------------------------------------------------
def s1_spec(meta, o):
    v = [s for s in meta.get("streams", []) if s.get("codec_type") == "video"]
    a = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
    if not v:
        fail("S1", "no video stream")
        return 0.0
    v = v[0]
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    dur = float(meta.get("format", {}).get("duration") or 0)
    try:
        num, den = v.get("r_frame_rate", "0/1").split("/")
        fps = float(num) / float(den or 1)
    except Exception:
        fps = 0.0
    INFO.append("resolution %dx%d | duration %.1fs | %.0f fps | audio %s" % (w, h, dur, fps, "yes" if a else "no"))
    ew, eh = int(o["--width"]), int(o["--height"])
    if (w, h) != (ew, eh):
        if (h > w) == (eh > ew):
            warn("S1a", "resolution %dx%d is not the expected %dx%d" % (w, h, ew, eh))
        else:
            fail("S1a", "orientation is wrong (%dx%d, expected %dx%d)" % (w, h, ew, eh))
    if o["--max-dur"] and dur > float(o["--max-dur"]):
        fail("S1b", "duration %.1fs exceeds the limit %ss" % (dur, o["--max-dur"]))
    if dur <= 0:
        fail("S1b", "duration could not be read")
    if fps < float(o["--min-fps"]):
        fail("S1c", "frame rate %.1f < %s fps" % (fps, o["--min-fps"]))
    if not a:
        fail("S1d", "no audio track")
    return dur


# S2 ---------------------------------------------------------------------------
def s2_opening(ff, path):
    """Pixel std-dev of 3 frames in the first 1.5 s. Flat colour -> low std-dev;
    a dark title card -> low brightness although white text raises the std-dev."""
    stats = []
    for t in (0.2, 0.7, 1.2):
        p = subprocess.run([ff, "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
                            "-vf", "scale=160:-1,format=gray", "-f", "rawvideo", "-"], capture_output=True)
        raw = p.stdout or b""
        if not raw:
            continue
        vals = list(raw)
        mean = sum(vals) / float(len(vals))
        std = (sum((x - mean) ** 2 for x in vals) / float(len(vals))) ** 0.5
        stats.append((t, mean, std))
    if not stats:
        warn("S2", "could not read the opening frames")
        return
    INFO.append("opening frames brightness/std-dev: " +
                " ".join("%.1fs(%.0f/%.0f)" % s for s in stats))
    flat = [s for s in stats if s[2] < 18]
    dark = [s for s in stats if s[1] < 25 and s not in flat]
    if flat:
        warn("S2a", "flat colour screen in the first 1.5 s at %s - viewers decide in the first second"
             % ", ".join("%.1fs" % s[0] for s in flat))
    if dark:
        warn("S2b", "near-black frame with only text at %s (dark title card opening)"
             % ", ".join("%.1fs" % s[0] for s in dark))


# S3 ---------------------------------------------------------------------------
def s3_audio(ff, path, dur, o):
    _, err = run([ff, "-v", "info", "-i", path, "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", err)
    if m:
        mean = float(m.group(1))
        INFO.append("mean volume %.1f dB" % mean)
        if mean < -30:
            (warn if o.get("allow_silent") else fail)("S3a", "mean volume %.1f dB is below -30 dB (practically silent)" % mean)
    else:
        warn("S3a", "could not read the volume")

    _, err = run([ff, "-v", "info", "-i", path, "-af", "silencedetect=n=-40dB:d=0.6", "-f", "null", "-"])
    total = sum(float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", err))
    if dur > 0:
        pct = total / dur * 100.0
        INFO.append("silence %.1fs = %.1f%%" % (total, pct))
        if pct >= float(o["--max-silence-pct"]):
            warn("S3b", "silence is %.1f%% of the video (limit %s%%)" % (pct, o["--max-silence-pct"]))

    _, err = run([ff, "-v", "info", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"])
    lu = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
    if lu:
        i_lufs = float(lu[-1])
        INFO.append("integrated loudness %.1f LUFS%s" % (i_lufs, (" | true peak %s dBTP" % tp[-1]) if tp else ""))
        target, tol = float(o["--lufs"]), float(o["--lufs-tol"])
        if abs(i_lufs - target) > tol:
            warn("S3c", "loudness %.1f LUFS is outside %.0f +/- %.0f; run render/loudnorm.py" % (i_lufs, target, tol))
    if tp and float(tp[-1]) > float(o["--max-tp"]):
        warn("S3d", "true peak %s dBTP is above %s dBTP (risk of clipping after platform re-encode)"
             % (tp[-1], o["--max-tp"]))


# S4 ---------------------------------------------------------------------------
def s4_cuts(ff, path, dur, o):
    need = 6 if o.get("film") else int(o["--min-cuts"])
    if need <= 0:
        return
    result = subprocess.run([ff, "-v", "info", "-i", path, "-vf", "select='gt(scene,0.3)',showinfo",
                             "-f", "null", "-"], capture_output=True)
    if result.returncode and o.get("film"):
        fail("FILM_CUT_CHECK_FAILED", "could not detect cuts")
        return
    err = result.stderr.decode("utf-8", "replace")
    cuts = err.count("pts_time:")
    INFO.append("scene changes detected: %d (threshold scene>0.3)" % cuts)
    if cuts < need:
        (fail if o.get("film") else warn)("S4", "only %d scene change(s); a single static shot rarely holds attention (min %d)" % (cuts, need))
    elif dur and cuts / dur < 0.12:
        warn("S4b", "low cut density %.2f per second" % (cuts / dur))


# S5 ---------------------------------------------------------------------------
def s5_subs(srt, o):
    try:
        txt = open(srt, "rb").read().decode("utf-8-sig", "replace")
    except Exception as e:
        warn("S5", "subtitle file unreadable: %s" % str(e)[:80])
        return
    max_lines = int(o["--max-lines"])
    cjk = re.compile(u"[぀-ヿ㐀-鿿가-힯]")

    def limit(line):
        if o["--max-chars"]:
            return int(o["--max-chars"])
        return 16 if cjk.search(line) else 32
    long_lines, multi = [], []
    for block in txt.replace("\r", "").split("\n\n"):
        lines = [x for x in block.split("\n") if x.strip()]
        body = [x.strip() for x in lines if "-->" not in x and not x.strip().isdigit()]
        if not body:
            continue
        if len(body) > max_lines:
            multi.append(" / ".join(body)[:40])
        for b in body:
            if len(b) > limit(b):
                long_lines.append("%d chars (limit %d): %s" % (len(b), limit(b), b[:30]))
    if multi:
        warn("S5a", "%d cue(s) have more than %d line(s), e.g. %s" % (len(multi), max_lines, multi[0]))
    if long_lines:
        warn("S5b", "%d subtitle line(s) too long (split the cue instead of wrapping), e.g. %s"
             % (len(long_lines), long_lines[0]))


# S6 ---------------------------------------------------------------------------
def speech_gaps(words, end):
    cursor = 0.0
    gaps = []
    for word in sorted(words, key=lambda word: word.start):
        if word.start >= end:
            break
        if word.end <= 0:
            continue
        if word.start > cursor:
            gaps.append((cursor, word.start))
        cursor = max(cursor, min(end, word.end))
    if end > cursor:
        gaps.append((cursor, end))
    return gaps


def s6_speech(ff, path, dur, o):
    from speech_review import recognize
    film = o.get("film")
    try:
        segments, _ = recognize(path, o["--model"], o["--lang"], ff,
                                word_timestamps=True, vad_filter=True)
    except (RuntimeError, ImportError) as exc:
        (fail if film else warn)("SPEECH_CHECK_PENDING", str(exc))
        return
    words = [word for segment in segments for word in (segment.words or []) if word.word.strip()]
    INFO.append("speech: %d words transcribed" % len(words))
    if film:
        worst = max(speech_gaps(words, o["outro_start"]), key=lambda gap: gap[1] - gap[0], default=(0, 0))
        if not words or worst[1] - worst[0] > 2:
            fail("FILM_SPEECH_GAP", "no recognized speech for %.2fs before outro (%.2f–%.2fs)" %
                 (worst[1] - worst[0], *worst))
        return
    if not words:
        warn("S6", "no speech detected")
        return
    spoken_end = max(word.end for word in words)
    worst = max(speech_gaps(words, spoken_end), key=lambda gap: gap[1] - gap[0], default=(0, 0))
    if worst[1] - worst[0] > float(o["--max-gap"]):
        warn("S6a", "%.2fs without speech at %.1f-%.1fs (limit %ss)" %
             (worst[1] - worst[0], *worst, o["--max-gap"]))
    if dur - spoken_end > float(o["--max-tail"]):
        warn("S6b", "%.2fs after the last spoken word (limit %ss)" % (dur - spoken_end, o["--max-tail"]))


def contact_sheet(ff, path, dur, out_dir):
    sheet = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + "_sheet.jpg")
    with tempfile.TemporaryDirectory(prefix='thinknova_frames_', dir=out_dir) as fr:
        n = max(1, int(dur))
        for i in range(n):
            position = min(i + 0.5, max(0, dur / 2 if dur < 1 else dur - 0.05))
            frame = os.path.join(fr, "%03d.jpg" % i)
            result = subprocess.run([ff, '-v', 'error', '-y', '-ss', str(position), '-i', path,
                                     '-frames:v', '1', '-vf', 'scale=216:-2', frame], capture_output=True)
            if result.returncode or not os.path.isfile(frame) or os.path.getsize(frame) == 0:
                fail('CONTACT_SHEET_FAILED', 'Could not extract review frame'); return
        result = subprocess.run([ff, '-v', 'error', '-y', '-i', os.path.join(fr, '%03d.jpg'),
                                 '-vf', 'tile=9x%d' % ((n + 8) // 9), '-frames:v', '1', sheet], capture_output=True)
        if result.returncode or not os.path.isfile(sheet) or not os.path.getsize(sheet):
            fail('CONTACT_SHEET_FAILED', 'Could not generate contact sheet'); return
    INFO.append('contact sheet: %s' % sheet)


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return 0
    pos, on, o = get_opts(sys.argv[1:])
    if not pos:
        print(__doc__)
        return 1
    path = pos[0]
    if not os.path.isfile(path):
        print("File not found: %s" % path)
        return 1
    ff = find_tool("ffmpeg", o["--ffmpeg"])
    fp = find_tool("ffprobe", o["--ffprobe"] or (os.path.join(os.path.dirname(ff), "ffprobe") if o["--ffmpeg"] else None))
    if not shutil.which(ff) and not os.path.isfile(ff):
        print("ffmpeg not found. Install it or pass --ffmpeg PATH.")
        return 1

    print("=" * 60)
    print("Pre-publish check: %s" % os.path.basename(path))
    print("=" * 60)
    out, _ = run([fp, "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    try:
        meta = json.loads(out)
    except Exception:
        print("ffprobe could not read the file.")
        return 1
    dur = s1_spec(meta, o)
    o["film"] = "--film" in on
    if o["film"]:
        if not 30 <= dur <= 40:
            fail("FILM_DURATION", "duration %.2fs is outside 30–40s" % dur)
        try:
            o["outro_start"] = float(o["--outro-start"])
        except (TypeError, ValueError):
            o["outro_start"] = 0
        if not 0 < o["outro_start"] < dur:
            fail("FILM_OUTRO_REQUIRED", "pass the actual outro start in seconds")
            o["outro_start"] = dur
    s2_opening(ff, path)
    o["allow_silent"] = "--allow-silent" in on
    s3_audio(ff, path, dur, o)
    s4_cuts(ff, path, dur, o)
    if o["--srt"]:
        s5_subs(o["--srt"], o)
    if "--speech" in on or o["film"]:
        s6_speech(ff, path, dur, o)
    if o["--sheet"]:
        os.makedirs(o["--sheet"], exist_ok=True)
        contact_sheet(ff, path, dur, o["--sheet"])

    print("\n-- measured --")
    for i in INFO:
        print("  %s" % i)
    if WARNS:
        print("\n-- WARN (shown, does not block) --")
        for c, m in WARNS:
            print("  [%s] %s" % (c, m))
    print("\n-- also look with your own eyes --")
    print("  [ ] the first second shows something happening (not a still or a plain title card)")
    print("  [ ] key text is not hidden under the platform's buttons / caption area (bottom ~25%, right edge)")
    print("  [ ] subtitles match the voice and are readable on a phone")
    if FAILS:
        print("\n-- FAIL --")
        for c, m in FAILS:
            print("  [%s] %s" % (c, m))
        print("\nResult: %d FAIL(s). Fix before publishing." % len(FAILS))
        return 2
    print("\nResult: no FAIL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
