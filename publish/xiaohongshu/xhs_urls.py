# -*- coding: utf-8 -*-
"""Xiaohongshu Creator platform URLs.

The scripts were tested on the "creator.rednote.com" host. The same creator platform is
also served at "creator.xiaohongshu.com". Pass --base to any script (or set the
environment variable XHS_BASE) to use another host. Your login session belongs to the
host you logged in on, so use the same --base for login.py and publish.py.
"""
import os

DEFAULT_BASE = "https://creator.rednote.com"


def urls(base=None):
    b = (base or os.environ.get("XHS_BASE") or DEFAULT_BASE).rstrip("/")
    return {
        "base": b,
        "publish": b + "/publish/publish",
        "manager": b + "/new/note-manager",
    }
