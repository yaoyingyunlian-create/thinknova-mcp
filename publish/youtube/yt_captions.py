# -*- coding: utf-8 -*-
"""List / download the caption tracks of a video on YOUR OWN channel (official API).

    python yt_captions.py VIDEO_ID              # list tracks
    python yt_captions.py VIDEO_ID --get        # download every track as .srt into ./captions/

Useful when you want word-timed subtitles of a video you already published (for example
to cut clips or re-use the timing in a HyperFrames template). Needs the youtube.force-ssl
scope (already in yt_common.SCOPES). Works only for videos you own.
Note: auto-generated tracks are sometimes not downloadable through the API.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import yt_common  # noqa: E402

OUT = os.path.join(HERE, "captions")


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    get = "--get" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    vid = args[0]
    yt = yt_common.youtube()

    items = yt.captions().list(part="snippet", videoId=vid).execute().get("items") or []
    if not items:
        print("This video has no caption tracks visible to the API.")
        return 2

    print("%d track(s):" % len(items))
    for it in items:
        s = it["snippet"]
        print("  id=%s  language=%s  kind=%s  name=%s  updated=%s"
              % (it["id"], s.get("language"), s.get("trackKind"),
                 s.get("name") or "(none)", (s.get("lastUpdated") or "")[:19]))
    if not get:
        print("\nAdd --get to download.")
        return 0

    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for it in items:
        s = it["snippet"]
        tag = "%s_%s_%s" % (vid, s.get("language") or "xx", s.get("trackKind") or "std")
        try:
            data = yt.captions().download(id=it["id"], tfmt="srt").execute()
        except Exception as e:
            print("  %s could not be downloaded: %s" % (tag, str(e)[:160]))
            continue
        if isinstance(data, str):
            data = data.encode("utf-8")
        p = os.path.join(OUT, tag + ".srt")
        with open(p, "wb") as f:
            f.write(data)
        print("  saved %s (%d bytes)" % (p, len(data)))
        ok += 1
    print("\nDownloaded %d track(s)." % ok)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
