# -*- coding: utf-8 -*-
"""One-time: authorise this toolkit to upload to YOUR YouTube channel.

    python auth.py

A browser opens; you sign in with the Google account that owns the channel and click
Allow. The refresh token is stored locally in token.json; upload.py reuses it.
The script never sees or stores your Google password.
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yt_common  # noqa: E402


def main():
    # If SCOPES changed since the last authorisation, the old token is still "valid"
    # but lacks permissions and would only fail later with 403. Move it aside and
    # authorise again.
    tok = yt_common.TOKEN
    if os.path.isfile(tok):
        try:
            with io.open(tok, encoding="utf-8") as f:
                have = set(json.load(f).get("scopes") or [])
        except Exception:
            have = set()
        missing = [x for x in yt_common.SCOPES if x not in have]
        if missing:
            bak = tok + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
            os.rename(tok, bak)
            print("The saved token lacks these scopes; it was moved to %s. Authorising again:"
                  % os.path.basename(bak))
            for m in missing:
                print("   - " + m)
            print()
    yt = yt_common.youtube(interactive=True)
    c = yt_common.my_channel(yt)
    print("\n" + "=" * 54)
    print("Authorised. Connected channel:")
    print("   name      %s" % c["title"])
    print("   handle    %s" % (c["handle"] or "(not set)"))
    print("   channelId %s" % c["id"])
    print("   subscribers %s | videos %s | views %s" % (c["subs"], c["videos"], c["views"]))
    print("=" * 54)
    print("\nIf this is not the channel you expected, delete token.json and run auth.py again "
          "with the right Google account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
