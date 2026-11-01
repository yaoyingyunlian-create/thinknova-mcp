# -*- coding: utf-8 -*-
"""Shared job.json loader for every publisher in this toolkit.

One job file can describe the same video for several platforms:

    {
      "video": "renders/final.mp4",
      "title": "...", "caption": "...", "tags": ["a", "b"],
      "aigc": true,
      "schedule": "2026-11-01 19:00",
      "platforms": {
        "youtube":     {"privacy": "private"},
        "tiktok":      {"brand_disclosure": false},
        "xiaohongshu": {"type": "video"},
        "douyin":      {}
      }
    }

Rules:
  * Keys inside "platforms.<name>" override the top-level keys for that platform.
  * Relative file paths are resolved against the folder that contains the job file
    (not against the folder you run the command from).
  * Keys starting with "_" are comments and are ignored.
See README.md for the full field list.
"""
import io
import json
import os
import sys

PATH_KEYS = ("video", "srt", "cover")
PATH_LIST_KEYS = ("images",)


def setup_console():
    """Force UTF-8 console output (Windows consoles often default to a legacy code page)."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _resolve(base, p):
    if not p:
        return p
    p = os.path.expanduser(str(p))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def load_job(path, platform=None):
    """Read a job file and return a flat dict for one platform."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise SystemExit("Job file not found: %s" % path)
    with io.open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    job = {k: v for k, v in raw.items() if not k.startswith("_") and k != "platforms"}
    if platform:
        over = (raw.get("platforms") or {}).get(platform) or {}
        for k, v in over.items():
            if not k.startswith("_"):
                job[k] = v
    base = os.path.dirname(path)
    for k in PATH_KEYS:
        if job.get(k):
            job[k] = _resolve(base, job[k])
    for k in PATH_LIST_KEYS:
        if job.get(k):
            job[k] = [_resolve(base, x) for x in job[k]]
    job["_job_path"] = path
    return job


def require(job, *keys):
    """Exit with a clear message if any required key is missing or empty."""
    miss = [k for k in keys if not job.get(k)]
    if miss:
        raise SystemExit("Job is missing required field(s): %s" % ", ".join(miss))


def parse_args(argv, flags=(), options=()):
    """Tiny argument parser: returns (positional, set_of_flags, dict_of_options)."""
    pos, on, opt = [], set(), {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in options and i + 1 < len(argv):
            opt[a] = argv[i + 1]
            i += 2
            continue
        if a in flags:
            on.add(a)
        elif a.startswith("--"):
            raise SystemExit("Unknown option: %s" % a)
        else:
            pos.append(a)
        i += 1
    return pos, on, opt
