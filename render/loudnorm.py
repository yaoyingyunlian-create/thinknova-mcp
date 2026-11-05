# -*- coding: utf-8 -*-
"""Normalise a video's loudness to -14 LUFS (the common target for short-video platforms)
with ffmpeg's two-pass loudnorm filter. The video stream is copied untouched.

    python loudnorm.py in.mp4 out.mp4
    python loudnorm.py in.mp4 out.mp4 --lufs -14 --tp -1 --lra 11 --ffmpeg PATH

Pass 1 measures the file; pass 2 applies a linear correction using those measurements
(more accurate than a single pass). Audio is re-encoded to AAC 192 kbps, 48 kHz.

One-line alternative (single pass, slightly less accurate):
    ffmpeg -i in.mp4 -c:v copy -af loudnorm=I=-14:TP=-1:LRA=11 -c:a aac -b:a 192k -ar 48000 out.mp4

Check the result with:  python check.py out.mp4
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys


def main():
    args = sys.argv[1:]
    opts = {"--lufs": "-14", "--tp": "-1", "--lra": "11", "--ffmpeg": None}
    pos, i = [], 0
    while i < len(args):
        if args[i] in opts and i + 1 < len(args):
            opts[args[i]] = args[i + 1]
            i += 2
        else:
            pos.append(args[i])
            i += 1
    if len(pos) < 2:
        print(__doc__)
        return 1
    src, dst = pos[0], pos[1]
    if not os.path.isfile(src):
        print("Input not found: %s" % src)
        return 1
    if os.path.abspath(src) == os.path.abspath(dst):
        print("Output must be a different file from the input.")
        return 1
    ff = opts["--ffmpeg"] or os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
    I, TP, LRA = opts["--lufs"], opts["--tp"], opts["--lra"]

    print("Pass 1/2: measuring ...")
    p = subprocess.run([ff, "-hide_banner", "-i", src, "-af",
                        "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json" % (I, TP, LRA),
                        "-f", "null", "-"], capture_output=True)
    err = (p.stderr or b"").decode("utf-8", "replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        print("Could not read loudnorm measurements (does the file have an audio track?).")
        return 2
    meas = json.loads(m.group(0))
    print("  measured: I=%s LUFS, TP=%s dBTP, LRA=%s LU" % (meas["input_i"], meas["input_tp"], meas["input_lra"]))

    print("Pass 2/2: applying ...")
    if not math.isfinite(float(meas['input_i'])):
        print('SILENT_AUDIO: preserving silence; loudness normalization is not applicable.')
        result = subprocess.run([ff, '-hide_banner', '-y', '-i', src, '-c', 'copy', '-movflags', '+faststart', dst], capture_output=True)
        return 0 if result.returncode == 0 else 3
    af = ("loudnorm=I=%s:TP=%s:LRA=%s:measured_I=%s:measured_TP=%s:measured_LRA=%s:"
          "measured_thresh=%s:offset=%s:linear=true:print_format=summary"
          % (I, TP, LRA, meas["input_i"], meas["input_tp"], meas["input_lra"],
             meas["input_thresh"], meas["target_offset"]))
    p2 = subprocess.run([ff, "-hide_banner", "-y", "-i", src, "-map", "0:v?", "-map", "0:a:0",
                         "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                         "-movflags", "+faststart", dst], capture_output=True)
    if p2.returncode != 0:
        print((p2.stderr or b"").decode("utf-8", "replace")[-1500:])
        print("ffmpeg failed.")
        return 3
    print("Done: %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
