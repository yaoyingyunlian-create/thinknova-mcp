# -*- coding: utf-8 -*-
"""Assemble finished shots into one vertical video with one command.
Same spec for every shot, joined, subtitled, loudness-normalised, then checked by check.py.

    python assemble.py job.json
    python assemble.py --clips s1.mp4 s2.mp4 s3.mp4 --out final.mp4

Do not write your own rendering code for this. Only ffmpeg (with ffprobe) and the scripts in
this folder are needed. Copy assemble.example.json, change the file names and lines, run it.

job.json fields (paths are relative to job.json):
  out            output file (required)
  clips          list of shots (required), each one:
    file           video or image (required)
    start          seconds to skip at the start of the file (default 0)
    dur            seconds to use (default: rest of the video / voice length + tail / 3 s for an image)
    audio          "keep" the clip's own sound (default) or "mute"
    voice          audio file to use as this shot's sound instead (replaces the clip's sound)
    tail           seconds to hold after the voice file ends (default 0.3)
    fit            "cover" crops to fill the frame (default); "contain" keeps the whole picture on a blurred background
    subs           subtitle lines for this shot, one per screen, e.g. ["Line one", "Line two"]
    text           or one string, split at punctuation into lines automatically
  music          background music file (optional; without it the video simply has no music)
  music_db       music level in dB (default -22)
  end_card       {"lines": ["ThinkNova", "..."], "dur": 2.2, "color": "F3ECDF"} plain closing card (optional)
  badge          small text at the top left, e.g. "AI generated" (optional)
  font           font name (optional; default picked for this system and language)
  font_size      subtitle size in pixels (default 72)
  subtitle_bottom  subtitle height from the bottom edge in % (default 28)
  max_dur        check.py fails if the video is longer than this many seconds (optional)

Exit code: 0 = done and check.py found no FAIL; 1 = bad input; 2 = check.py FAIL; 3 = ffmpeg failed.
"""
import io
import hashlib
import math
import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STAGE = 'input'
REPORT_STREAM = sys.stdout
def emit(value):
    print(json.dumps(value, ensure_ascii=False), file=REPORT_STREAM)


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from captions import ass_time, write_srt, parse_srt, safe_subtitle_text  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, 48000
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
CJK = re.compile(u"[぀-ヿ㐀-鿿가-힯]")
SPLIT = re.compile(u"(?<=[，。！？；、,.!?;])\\s*")
STRIP = u"，。、,.!?！？；;：:"
MAX_CJK, MAX_LATIN = 14, 30
FONTS = {"Windows": ("Microsoft YaHei", "Arial"), "Darwin": ("PingFang SC", "Helvetica"), "Linux": ("Noto Sans CJK SC", "DejaVu Sans")}


class Stop(Exception):
    def __init__(self, msg, code=1):
        Exception.__init__(self, msg)
        self.code = code


def tool(name):
    p = os.environ.get(name.upper()) or shutil.which(name)
    if not p:
        raise Stop("%s not found. Install ffmpeg (includes ffprobe) and make sure it is on PATH." % name)
    return p


def run_ff(ff, args, what, cwd=None):
    global STAGE
    STAGE = what
    p = subprocess.run([ff, "-hide_banner", "-y"] + args, capture_output=True, cwd=cwd, timeout=600)
    err = (p.stderr or b"").decode("utf-8", "replace")
    if p.returncode != 0:
        raise Stop("ffmpeg failed at: %s\n%s" % (what, err[-1200:]), 3)
    return err


def probe(fp, path):
    p = subprocess.run([fp, "-v", "error", "-show_streams", "-show_format", "-of", "json", path], capture_output=True, timeout=30)
    try:
        m = json.loads((p.stdout or b"").decode("utf-8", "replace"))
        has_v = any(s.get("codec_type") == "video" for s in m.get("streams", []))
        has_a = any(s.get("codec_type") == "audio" for s in m.get("streams", []))
        return float(m.get("format", {}).get("duration") or 0), has_v, has_a
    except Exception:
        raise Stop("Cannot read this file (is it a real video, image or audio file?): %s" % path)


def resolve(base, path):
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


def split_text(text):
    """One string -> short one-line subtitles, cut at punctuation, then by length."""
    out = []
    for part in SPLIT.split(text.strip()):
        part = part.strip().rstrip(STRIP).strip()
        limit = MAX_CJK if CJK.search(part) else MAX_LATIN
        while len(part) > limit:
            cut = part.rfind(" ", 0, limit + 1)
            cut = cut if cut > 0 else limit
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


def speech_chunks(ff, audio_path, dur):
    """Stretches of sound in this shot, so subtitles follow the voice instead of running over pauses."""
    p = subprocess.run([ff, "-hide_banner", "-i", audio_path, "-af", "silencedetect=n=-38dB:d=0.25", "-f", "null", "-"], capture_output=True)
    err = (p.stderr or b"").decode("utf-8", "replace")
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", err)]
    chunks, pos = [], 0.0
    for i, st in enumerate(starts):
        if st > pos + 0.05:
            chunks.append((pos, st))
        pos = ends[i] if i < len(ends) else dur
    if pos < dur - 0.05:
        chunks.append((pos, dur))
    return chunks or [(0.0, dur)]


def time_subs(lines, chunks, offset):
    """Share the sound time between the lines by character count; each line stays up until the next one."""
    speech = sum(b - a for a, b in chunks)
    total = float(sum(max(1, len(x)) for x in lines))

    def at(frac):
        left = frac * speech
        for a, b in chunks:
            if left <= b - a:
                return a + left
            left -= b - a
        return chunks[-1][1]
    out, done = [], 0.0
    for ln in lines:
        st = at(done / total)
        done += max(1, len(ln))
        out.append({"start": offset + st, "end": offset + at(done / total), "text": ln.rstrip(STRIP)})
    for i in range(len(out) - 1):
        out[i]["end"] = out[i + 1]["start"]
    return out


def norm_shot(ff, fp, base, c, idx, wk):
    """One shot -> 1080x1920, 30 fps, 48 kHz stereo, exact length."""
    if not c.get("file"):
        raise Stop("Shot %d has no \"file\"." % (idx + 1))
    src = resolve(base, c["file"])
    if not os.path.isfile(src):
        raise Stop("Shot %d: file not found: %s" % (idx + 1, src))
    image = src.lower().endswith(IMAGE_EXT)
    voice = resolve(base, c["voice"]) if c.get("voice") else None
    if voice and not os.path.isfile(voice):
        raise Stop("Shot %d: voice file not found: %s" % (idx + 1, voice))
    start = float(c.get("start") or 0)
    sdur, has_v, has_a = (0.0, True, False) if image else probe(fp, src)
    if not has_v:
        raise Stop("Shot %d has no picture: %s" % (idx + 1, src))
    vdur = probe(fp, voice)[0] if voice else 0.0
    if c.get("dur"):
        dur = float(c["dur"])
    elif voice:
        dur = vdur + float(c.get("tail", 0.3))
    elif image:
        dur = 3.0
    else:
        dur = sdur - start
    if dur <= 0.1:
        raise Stop("Shot %d: length %.2fs is too short (check start and dur)." % (idx + 1, dur))
    if not image and start >= sdur:
        raise Stop("Shot %d: start %.2fs is past the end of the %.2fs file." % (idx + 1, start, sdur))

    inp = ["-loop", "1", "-t", "%.3f" % dur, "-i", src] if image else ["-ss", "%.3f" % start, "-i", src]
    if c.get("fit") == "contain":
        pic = ("[0:v]split=2[bg][fg];[bg]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=30:2[b];"
               "[fg]scale=%d:%d:force_original_aspect_ratio=decrease[f];[b][f]overlay=(W-w)/2:(H-h)/2" % (W, H, W, H, W, H))
    else:
        pic = "[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H)
    if not image and dur > sdur - start + 0.001:
        raise Stop("SHOT_TOO_SHORT: shot %d requests %.3fs; available %.3fs. Do not freeze the last frame." % (idx + 1, dur, sdur - start))
    pic += ",setsar=1,fps=%d,trim=duration=%.3f,setpts=PTS-STARTPTS,format=yuv420p[v]" % (FPS, dur)

    if voice:
        inp += ["-i", voice]
        snd = "[1:a]"
    elif has_a and c.get("audio", "keep") != "mute":
        snd = "[0:a]"
    else:
        inp += ["-f", "lavfi", "-t", "%.3f" % dur, "-i", "anullsrc=r=%d:cl=stereo" % SR]
        snd = "[1:a]"
    aud = "%saresample=%d,aformat=channel_layouts=stereo,apad,atrim=duration=%.3f,asetpts=PTS-STARTPTS[a]" % (snd, SR, dur)

    out = os.path.join(wk, "s%03d.mp4" % idx)
    run_ff(ff, inp + ["-filter_complex", pic + ";" + aud, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "18",
                      "-preset", "veryfast", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), out], "shot %d" % (idx + 1))
    return out, dur


def end_card(ff, card, idx, wk):
    color = str(card.get("color") or "F3ECDF").lstrip("#")
    dur = float(card.get("dur") or 2.2)
    out = os.path.join(wk, "s%03d.mp4" % idx)
    run_ff(ff, ["-f", "lavfi", "-t", "%.3f" % dur, "-i", "color=c=0x%s:s=%dx%d:r=%d" % (color, W, H, FPS),
                "-f", "lavfi", "-t", "%.3f" % dur, "-i", "anullsrc=r=%d:cl=stereo" % SR, "-c:v", "libx264", "-crf", "18",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out], "end card")
    return out, dur


def add_music(ff, joined, music, db, total, wk):
    out = os.path.join(wk, "with_music.mp4")
    fc = ("[1:a]aresample=%d,aformat=channel_layouts=stereo,volume=%sdB,afade=t=out:st=%.3f:d=0.8[m];"
          "[0:a][m]amix=inputs=2:duration=first:normalize=0[a]" % (SR, db, max(0.0, total - 0.8)))
    run_ff(ff, ["-i", joined, "-stream_loop", "-1", "-i", music, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", "%.3f" % total, out], "mixing music")
    return out


def pick_font(job, text):
    if job.get("font"):
        return job["font"]
    cjk, latin = FONTS.get(platform.system(), FONTS["Linux"])
    return cjk if CJK.search(text) else latin


def ass_escape(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(path, job, cues, card_span, font):
    size = int(job.get("font_size") or 72)
    bottom = int(H * float(job.get("subtitle_bottom") or 28) / 100.0)
    fmt = ("Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
           "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    style = u"Style: %s,{f},%d,%s,%s,%s,&H00000000,-1,0,0,0,100,100,0,0,1,%d,0,%d,60,60,%d,1\n"
    head = u"[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n\n[V4+ Styles]\nFormat: Name, %s\n" % (W, H, fmt)
    head += (style % ("Sub", size, "&H00FFFFFF", "&H00FFFFFF", "&H00141414", 7, 2, bottom)).replace("{f}", font)
    head += (style % ("Badge", 30, "&H00FFFFFF", "&H00FFFFFF", "&H00141414", 3, 7, 60)).replace("{f}", font)
    head += (style % ("Card", 110, "&H00232D3C", "&H00232D3C", "&H00FFFFFF", 0, 5, 0)).replace("{f}", font)
    head += u"\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    rows = [u"Dialogue: 0,%s,%s,Sub,,0,0,0,,%s" % (ass_time(c["start"]), ass_time(c["end"]), safe_subtitle_text(c["text"], W, H, size, bottom, 7)) for c in cues]
    if job.get("badge"):
        rows.append(u"Dialogue: 0,%s,%s,Badge,,0,0,0,,%s" % (ass_time(0), ass_time(card_span[0] if card_span else job["_total"]), ass_escape(job["badge"])))
    if card_span:
        lines = [ass_escape(x) for x in job["end_card"].get("lines", [])]
        if lines:
            rows.append(u"Dialogue: 0,%s,%s,Card,,0,0,0,,%s" % (ass_time(card_span[0]), ass_time(card_span[1]), u"\\N".join(lines)))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(head + u"\n".join(rows) + u"\n")


def burn(ff, src, wk, font):
    """Run inside the work folder with a bare file name: avoids escaping drive letters in the filter string."""
    out = os.path.join(wk, "burned.mp4")
    err = run_ff(ff, ["-v", "info", "-i", src, "-vf", "ass=subs.ass", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                      "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out], "burning subtitles (needs ffmpeg built with libass)", cwd=wk)
    used = sorted(set(re.findall(r"fontselect: \(([^,)]+)", err)))
    if used:
        print("  fonts used: %s (asked for %s). Look at the contact sheet to confirm the text is readable." % (", ".join(used), font))
    return out


def load_job(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        raise SystemExit(0 if argv else 1)
    if argv[0] == "--clips":
        if "--out" not in argv:
            raise Stop("--clips needs --out final.mp4")
        k = argv.index("--out")
        files = argv[1:k]
        if not files or k + 1 >= len(argv):
            raise Stop("Usage: python assemble.py --clips a.mp4 b.mp4 --out final.mp4")
        return {"out": argv[k + 1], "clips": [{"file": f} for f in files]}, os.getcwd()
    path = argv[0]
    if not os.path.isfile(path):
        raise Stop("Job file not found: %s" % path)
    try:
        job = json.loads(io.open(path, encoding="utf-8-sig").read())
    except ValueError as e:
        raise Stop("job file is not valid JSON: %s" % e)
    return job, os.path.dirname(os.path.abspath(path))


def validate_job(job):
    if not isinstance(job, dict) or not isinstance(job.get('out'), str) or not job['out']:
        raise Stop('INVALID_JOB: out must be a nonempty file path')
    if not isinstance(job.get('clips'), list) or not job['clips']:
        raise Stop('INVALID_JOB: clips must be a nonempty array')
    def number(value, field, minimum=0):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
            raise Stop('INVALID_JOB: %s must be a finite number >= %s' % (field, minimum))
    if 'film' in job and not isinstance(job['film'], bool):
        raise Stop('INVALID_JOB: film must be boolean')
    if job.get('film') and (not isinstance(job.get('end_card'), dict) or not job['end_card'].get('lines')):
        raise Stop('FILM_OUTRO_REQUIRED: supply a closing card with text')
    if 'speech_language' in job and not isinstance(job['speech_language'], str):
        raise Stop('INVALID_JOB: speech_language must be text')
    for index, clip in enumerate(job['clips']):
        prefix = 'clips[%d]' % index
        if not isinstance(clip, dict) or not isinstance(clip.get('file'), str) or not clip['file']:
            raise Stop('INVALID_JOB: %s.file must be a nonempty file path' % prefix)
        for key in ('start', 'tail', 'dur'):
            if key in clip: number(clip[key], prefix + '.' + key, 0.101 if key == 'dur' else 0)
        if clip.get('fit', 'cover') not in ('cover', 'contain') or clip.get('audio', 'keep') not in ('keep', 'mute'):
            raise Stop('INVALID_JOB: %s fit/audio is unsupported' % prefix)
        for key in ('voice', 'text'):
            if key in clip and not isinstance(clip[key], str): raise Stop('INVALID_JOB: %s.%s must be text' % (prefix, key))
        if 'subs' in clip and (not isinstance(clip['subs'], list) or not all(isinstance(x, str) and x.strip() for x in clip['subs'])):
            raise Stop('INVALID_JOB: %s.subs must contain nonempty text' % prefix)
    for key in ('font_size', 'subtitle_bottom', 'max_dur'):
        if key in job: number(job[key], key, 0.01)
    if job.get('subtitle_bottom', 28) >= 100: raise Stop('INVALID_JOB: subtitle_bottom must be below 100')
    if 'music_db' in job: number(job['music_db'], 'music_db', -100)
    for key in ('music', 'font', 'badge', 'srt'):
        if key in job and not isinstance(job[key], str): raise Stop('INVALID_JOB: %s must be text' % key)
    if 'end_card' in job:
        card = job['end_card']
        if not isinstance(card, dict) or not isinstance(card.get('lines', []), list) or not all(isinstance(x, str) for x in card.get('lines', [])):
            raise Stop('INVALID_JOB: invalid end_card')
        number(card.get('dur', 2.2), 'end_card.dur', 0.101)
        if not re.fullmatch(r'#?[0-9A-Fa-f]{6}', str(card.get('color', 'F3ECDF'))): raise Stop('INVALID_JOB: invalid end_card.color')


def delivery_targets(output):
    stem = os.path.splitext(output)[0]
    return output, stem + '.srt', stem + '_sheet.jpg', output + '.film.json'


def ensure_output_available(output, overwrite):
    if not overwrite and any(os.path.exists(path) for path in delivery_targets(output)):
        raise Stop('OUTPUT_EXISTS: use --overwrite to replace existing artifacts')


def run_delivery_check(ff, fp, video, srt, options):
    folder = os.path.dirname(video)
    cmd = [sys.executable, os.path.join(HERE, 'check.py'), video, '--sheet', folder,
           '--ffmpeg', ff, '--ffprobe', fp, '--allow-silent']
    if options['outro_start'] is not None:
        cmd += ['--film', '--outro-start', str(options['outro_start'])]
        if options['speech_language']:
            cmd += ['--lang', options['speech_language']]
    if srt:
        cmd += ['--srt', srt]
    if options['max_dur']:
        cmd += ['--max-dur', str(options['max_dur'])]
    try:
        checked = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
        report = checked.stdout + '\n' + checked.stderr
        code = checked.returncode
    except subprocess.TimeoutExpired:
        report, code = '  [FILM_CHECK_TIMEOUT] Film check timed out.', 2
    print(report, file=sys.stderr)
    diagnostics = [{'code': code, 'message': message}
                   for code, message in re.findall(r'^  \[([^]]+)\] (.+)$', report, re.M)]
    sheet = os.path.splitext(video)[0] + '_sheet.jpg'
    if code == 0 and not os.path.isfile(sheet):
        code = 2
        diagnostics.append({'code': 'CONTACT_SHEET_FAILED', 'message': 'No visual review artifact.'})
    if code and not diagnostics:
        diagnostics.append({'code': 'CHECK_FAILED', 'message': f'Film check exited with code {code}.'})
    return code == 0, diagnostics, sheet, report


def file_digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def deliver(video, srt, sheet, output, options, result, warnings, overwrite):
    ensure_output_available(output, overwrite)
    _, target_srt, target_sheet, target_receipt = delivery_targets(output)
    film = options['outro_start'] is not None
    receipt = os.path.join(os.path.dirname(video), 'delivery-receipt.json')
    if film:
        with open(receipt, 'w', encoding='utf-8') as stream:
            json.dump({'sha256': file_digest(video), 'state': 'awaiting_review',
                       'machine_check': 'pass', 'outro_start': options['outro_start']}, stream)
    # Clear any previous receipt before replacing the artifacts. A partial delivery
    # cannot inherit a passing receipt from an earlier output.
    if overwrite and os.path.isfile(target_receipt):
        os.remove(target_receipt)
    os.replace(video, output)
    if srt:
        os.replace(srt, target_srt)
    elif overwrite and os.path.isfile(target_srt):
        os.remove(target_srt)
    os.replace(sheet, target_sheet)
    if film:
        os.replace(receipt, target_receipt)
        result.update(delivery_state='awaiting_review', film_receipt=target_receipt)
    emit(dict(result, status='succeeded', output=output, machine_check='pass', visual_review='pending',
              warnings=warnings, contact_sheet=target_sheet))
    return 0


def save_pending(ff, video, srt, sheet, output, options, result, diagnostics, report):
    decoded = subprocess.run([ff, '-nostdin', '-v', 'error', '-xerror', '-i', video,
                              '-map', '0:v:0', '-map', '0:a:0?', '-f', 'null', '-'],
                             capture_output=True, timeout=180)
    if decoded.returncode:
        raise Stop('CHECK_FAILED: preview is not decodable', 2)
    folder = tempfile.mkdtemp(prefix='film_pending_', dir=os.path.dirname(output))
    preview = os.path.join(folder, 'preview.mp4')
    shutil.copyfile(video, preview)
    if srt:
        shutil.copyfile(srt, os.path.join(folder, 'preview.srt'))
    if os.path.isfile(sheet):
        shutil.copyfile(sheet, os.path.join(folder, 'preview_sheet.jpg'))
    receipt = preview + '.film.json'
    record = {'sha256': file_digest(preview), 'subtitle_sha256': file_digest(srt) if srt else None,
              'state': 'pending_check', 'machine_check': 'failed',
              'output': os.path.basename(output), 'options': options, 'result': result}
    with open(receipt, 'w', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False)
    return report_pending(preview, receipt, diagnostics, report)


def report_pending(preview, receipt, diagnostics, report):
    log = os.path.join(os.path.dirname(preview), 'check.log')
    with open(log, 'w', encoding='utf-8') as stream:
        stream.write(report)
    sheet = os.path.splitext(preview)[0] + '_sheet.jpg'
    emit({'status': 'failed', 'delivery_state': 'pending_check', 'machine_check': 'failed',
          'exit_code': 2, 'error': 'CHECK_FAILED', 'preview': preview, 'pending_receipt': receipt,
          'diagnostic_log': log, 'diagnostics': diagnostics,
          'contact_sheet': sheet if os.path.isfile(sheet) else None})
    return 2


def recheck(receipt, overwrite):
    receipt = os.path.abspath(receipt)
    folder = os.path.dirname(receipt)
    if os.path.basename(receipt) != 'preview.mp4.film.json' or not os.path.basename(folder).startswith('film_pending_'):
        raise Stop('INVALID_PENDING_RECEIPT')
    with open(receipt, encoding='utf-8') as stream:
        record = json.load(stream)
    if record.get('state') != 'pending_check' or record.get('machine_check') != 'failed':
        raise Stop('INVALID_PENDING_RECEIPT')
    preview = os.path.join(folder, 'preview.mp4')
    srt = os.path.join(folder, 'preview.srt')
    if not os.path.isfile(preview) or file_digest(preview) != record.get('sha256'):
        raise Stop('PREVIEW_DIGEST_MISMATCH', 2)
    if record.get('subtitle_sha256'):
        if not os.path.isfile(srt) or file_digest(srt) != record['subtitle_sha256']:
            raise Stop('SUBTITLE_DIGEST_MISMATCH', 2)
    else:
        srt = None
    name = record.get('output', '')
    options = record.get('options', {})
    outro = options.get('outro_start')
    if not name or os.path.basename(name) != name or name in ('.', '..') or not isinstance(outro, (int, float)) or not math.isfinite(outro) or outro <= 0:
        raise Stop('INVALID_PENDING_RECEIPT')
    output = os.path.join(os.path.dirname(folder), name)
    ensure_output_available(output, overwrite)
    ff, fp = tool('ffmpeg'), tool('ffprobe')
    # Validate a private copy so later edits cannot change what gets delivered.
    with tempfile.TemporaryDirectory(prefix='film_recheck_', dir=os.path.dirname(folder)) as work:
        video = os.path.join(work, 'delivery.mp4')
        shutil.copyfile(preview, video)
        if file_digest(video) != record['sha256']:
            raise Stop('PREVIEW_DIGEST_MISMATCH', 2)
        if srt:
            temp_srt = os.path.join(work, 'delivery.srt')
            shutil.copyfile(srt, temp_srt)
            if file_digest(temp_srt) != record['subtitle_sha256']:
                raise Stop('SUBTITLE_DIGEST_MISMATCH', 2)
        else:
            temp_srt = None
        passed, diagnostics, sheet, report = run_delivery_check(ff, fp, video, temp_srt, options)
        if not passed:
            if os.path.isfile(sheet):
                shutil.copyfile(sheet, os.path.splitext(preview)[0] + '_sheet.jpg')
            return report_pending(preview, receipt, diagnostics, report)
        return deliver(video, temp_srt, sheet, output, options, record['result'], diagnostics, overwrite)



def main():
    global STAGE
    argv = [a for a in sys.argv[1:] if a != '--json']
    overwrite = '--overwrite' in argv
    if overwrite: argv.remove('--overwrite')
    if argv[:1] == ['--recheck']:
        STAGE = 'check'
        if len(argv) != 2:
            raise Stop('Usage: assemble.py --recheck <preview.mp4.film.json> [--json] [--overwrite]')
        return recheck(argv[1], overwrite)
    job, base = load_job(argv)
    validate_job(job)
    if not job.get("out") or not job.get("clips"):
        raise Stop("job needs \"out\" and at least one entry in \"clips\".")
    ff, fp = tool("ffmpeg"), tool("ffprobe")
    out = resolve(base, job["out"])
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    targets = delivery_targets(out)
    ensure_output_available(out, overwrite)
    for clip in job['clips']:
        for key in ('file', 'voice'):
            if clip.get(key) and os.path.normcase(os.path.realpath(resolve(base, clip[key]))) in [os.path.normcase(os.path.realpath(p)) for p in targets]: raise Stop('OUTPUT_IS_INPUT: source must not be overwritten')
    music = resolve(base, job["music"]) if job.get("music") else None
    if music and not os.path.isfile(music):
        raise Stop("Music file not found: %s (remove \"music\" to make the video without music)" % music)
    wk = tempfile.mkdtemp(prefix="assemble_", dir=os.path.dirname(os.path.abspath(out)))
    final_out = out
    out = os.path.join(wk, 'delivery.mp4')
    try:
        parts, cues, t = [], [], 0.0
        for i, c in enumerate(job["clips"]):
            print("Shot %d/%d: %s" % (i + 1, len(job["clips"]), os.path.basename(c.get("file", "?"))))
            shot, dur = norm_shot(ff, fp, base, c, i, wk)
            parts.append(shot)
            lines = c.get("subs") or (split_text(c["text"]) if c.get("text") else [])
            if lines:
                cues += time_subs(lines, speech_chunks(ff, shot, dur), t)
            t += dur
        card_span = None
        if job.get("end_card"):
            shot, dur = end_card(ff, job["end_card"], len(parts), wk)
            parts.append(shot)
            card_span = (t, t + dur)
            t += dur
        job["_total"] = t
        if job.get('srt'):
            cues=parse_srt(resolve(base,job['srt']))
            if not cues or any(not (0 <= c['start'] < c['end'] <= t + 0.05) for c in cues):
                raise Stop('INVALID_SUBTITLE_TIMELINE: cues must fit the finished video')

        if job.get('film') and job.get('font_size') == 90:
            for index, cue in enumerate(cues, 1):
                if len(re.sub(r'\s+', '', cue['text'])) > 9:
                    raise Stop(f'FILM_SUBTITLE_SPLIT_REQUIRED: cue {index} exceeds 9 characters', 2)

        print("Joining %d parts, %.1f s ..." % (len(parts), t))
        lst = os.path.join(wk, "list.txt")
        with io.open(lst, "w", encoding="utf-8") as f:
            for p in parts:
                f.write(u"file '%s'\n" % os.path.basename(p))
        joined = os.path.join(wk, "joined.mp4")
        run_ff(ff, ["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4"], "joining", cwd=wk)
        cur = joined
        if music:
            print("Adding music ...")
            cur = add_music(ff, cur, music, job.get("music_db", -22), t, wk)
        srt = None
        words = u"".join(c["text"] for c in cues) + u"".join(job.get("end_card", {}).get("lines", [])) + (job.get("badge") or u"")
        if words:
            font = pick_font(job, words)
            print("Subtitles, font %s ..." % font)
            write_ass(os.path.join(wk, "subs.ass"), job, cues, card_span, font)
            cur = burn(ff, cur, wk, font)
            if cues:
                srt = os.path.splitext(out)[0] + ".srt"
                write_srt(cues, srt)

        STAGE = "loudness"
        print("Loudness ...")
        p = subprocess.run([sys.executable, os.path.join(HERE, "loudnorm.py"), cur, out, "--ffmpeg", ff], stdout=sys.stderr)
        if p.returncode != 0:
            raise Stop("loudnorm.py failed (see above).", 3)
        STAGE = "check"
        print("Checking ...")
        options = {'outro_start': card_span[0] if job.get('film') else None,
                   'speech_language': job.get('speech_language'), 'max_dur': job.get('max_dur')}
        result = {'duration_seconds': t, 'width': W, 'height': H, 'fps': FPS,
                  'subtitle_timing': 'provided' if job.get('srt') else ('estimated' if cues else 'not_applicable')}
        passed, diagnostics, sheet, report = run_delivery_check(ff, fp, out, srt, options)
        if not passed:
            if job.get('film'):
                return save_pending(ff, out, srt, sheet, final_out, options, result, diagnostics, report)
            raise Stop('CHECK_FAILED: do not publish this file', 2)
        return deliver(out, srt, sheet, final_out, options, result, diagnostics, overwrite)

    finally:
        shutil.rmtree(wk, ignore_errors=True)



if __name__ == "__main__":
    try:
        with contextlib.redirect_stdout(sys.stderr) if '--json' in sys.argv else contextlib.nullcontext():
            code = main()
        sys.exit(code)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as e:
        emit({"status": "failed", "error": "LOCAL_RENDER_FAILED", "failure": type(e).__name__, "stage": STAGE, "exit_code": 3})
        sys.exit(3)
    except Stop as e:
        emit({"status": "failed", "error": str(e), "stage": STAGE, "exit_code": e.code})
        sys.exit(e.code)
