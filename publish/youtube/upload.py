# -*- coding: utf-8 -*-
"""Upload one video to YouTube with the official YouTube Data API v3.

    python upload.py ../../job.example.json --dry       # LOCAL checks only, no API calls
    python upload.py ../../job.example.json --execute   # real upload after user confirmation

Order of steps (do not reorder):
    1. render/check.py on the video; a FAIL or missing checker stops the upload
    2. videos.insert (resumable upload)
    3. replace {{VIDEO_ID}} in the description with the real id (if present)
    4. set the "altered or synthetic content" flag when "aigc" is true
    5. read the video back and compare title / privacy / schedule
    6. append one line to upload_log.csv next to this script

Job fields used (top level, or overridden in "platforms.youtube"):
    video        path to the mp4 (required)
    title        video title (required)
    description  description text; falls back to "caption"
    tags         list of tags (no "#")
    privacy      "private" (default) | "unlisted" | "public"
    publishAt    RFC3339 UTC time, e.g. "2026-11-01T11:00:00Z" (forces private until then)
    schedule     "YYYY-MM-DD HH:MM" in THIS computer's local time; used if publishAt is absent
    categoryId   YouTube category id, default 22 (People & Blogs)
    lang         e.g. "en", "zh-Hans" (optional)
    aigc         true -> declare altered/synthetic content (default true)
    made_for_kids  default false
    srt          optional subtitle file passed to render/check.py

Notes:
  * The synthetic-content flag (status.containsSyntheticMedia) can be WRITTEN by the API,
    but reading it back through the API has been observed to return nothing. Verify it
    once in YouTube Studio (video -> Details -> Show more -> Altered content).
  * A vertical video of a few minutes or less is usually classified as a Short
    automatically; check once in Studio.
"""
import csv
import datetime
import io
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import yt_common  # noqa: E402
from common import jobfile  # noqa: E402

CHECK = os.path.normpath(os.path.join(HERE, "..", "..", "render", "check.py"))
LOG_CSV = os.path.join(HERE, "upload_log.csv")
ID_TOKEN = "{{VIDEO_ID}}"


def log(m):
    print(u"[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def run_check(video, srt):
    if not os.path.isfile(CHECK):
        log("render/check.py not found; repair the toolkit before uploading.")
        return 2
    cmd = [sys.executable, CHECK, video]
    if srt:
        cmd += ["--srt", srt]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, env=env, capture_output=True)
    print((p.stdout or b"").decode("utf-8", "replace"))
    return p.returncode


def local_to_utc_rfc3339(s):
    dt = datetime.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
    utc = dt.astimezone(datetime.timezone.utc)   # naive -> interpreted as local time
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def append_log(row):
    new = not os.path.isfile(LOG_CSV)
    with io.open(LOG_CSV, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "title", "videoId", "privacy", "publishAt", "check", "file"])
        w.writerow(row)


def main():
    pos, flags, _ = jobfile.parse_args(sys.argv[1:], flags=("--skip-check", "--dry", "--execute"))
    if not pos or ("--dry" in flags) == ("--execute" in flags):
        print(__doc__)
        return 1
    if "--skip-check" in flags:
        log("--skip-check is no longer supported. Fix failed checks before uploading.")
        return 2
    job = jobfile.load_job(pos[0], "youtube")
    if not job.get("description") and job.get("caption"):
        job["description"] = job["caption"]
    jobfile.require(job, "video", "title")
    video = job["video"]
    if not os.path.isfile(video):
        log("Video file not found: %s" % video)
        return 1

    # 1. pre-upload check
    log("Running render/check.py ...")
    rc = run_check(video, job.get("srt"))
    if rc != 0:
        log("Check FAILED (exit code %s). Not uploading. Fix the video first." % rc)
        return 2
    check_note = "pass"

    snippet = {
        "title": job["title"],
        "description": job.get("description", ""),
        "tags": job.get("tags", []),
        "categoryId": str(job.get("categoryId", 22)),
    }
    if job.get("lang"):
        snippet["defaultLanguage"] = job["lang"]
        snippet["defaultAudioLanguage"] = job["lang"]
    status = {
        "privacyStatus": job.get("privacy", "private"),
        "selfDeclaredMadeForKids": bool(job.get("made_for_kids", False)),
        "containsSyntheticMedia": bool(job.get("aigc", True)),
    }
    if status['privacyStatus'] not in ('private', 'unlisted', 'public'):
        log('Invalid privacy value; not uploading.')
        return 2
    publish_at = job.get("publishAt")
    if not publish_at and job.get("schedule"):
        publish_at = local_to_utc_rfc3339(job["schedule"])
        log("schedule %s (local) -> publishAt %s (UTC)" % (job["schedule"], publish_at))
    if publish_at:
        status["privacyStatus"] = "private"      # scheduled videos must be private until publishAt
        status["publishAt"] = publish_at
    intended_privacy = status['privacyStatus']
    if job.get('automation_run_id') and not publish_at:
        status['privacyStatus'] = 'private'  # Stage privately before the final live authorization check.
    body = {"snippet": snippet, "status": status}

    if "--dry" in flags:
        log("LOCAL DRY RUN passed. No OAuth, upload or scheduling request was made. Intended privacy: %s; schedule: %s" % (status['privacyStatus'], status.get('publishAt', 'none')))
        return 0

    # Only explicit --execute reaches account access or upload.
    from googleapiclient.http import MediaFileUpload

    yt = yt_common.youtube()
    ch = yt_common.my_channel(yt)
    expected_channel = job.get('expected_channel_id')
    if expected_channel and ch['id'] != expected_channel:
        log('Channel does not match the authorized channel. Not uploading.')
        return 2
    receipt_path = job['_job_path'] + '.receipt.json' if job.get('automation_run_id') else None
    if receipt_path:
        if not expected_channel:
            log('Controlled automation requires an explicit channel.')
            return 2
        # Exclusive marker before any upload. Unknown outcomes require reconciliation.
        try:
            with open(receipt_path, 'x', encoding='utf-8') as marker:
                json.dump({'state':'uploading','channel_id':expected_channel}, marker)
        except FileExistsError:
            log('An upload was already attempted. Reconcile the existing receipt; do not re-upload.')
            return 2
    log("Channel: %s (%s) | subscribers %s | videos %s"
        % (ch["title"], ch["handle"] or "no handle", ch["subs"], ch["videos"]))

    size_mb = os.path.getsize(video) / 1024.0 / 1024.0
    log("Uploading %s (%.1f MB) ..." % (os.path.basename(video), size_mb))
    media = MediaFileUpload(video, chunksize=4 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, last = None, -1
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            pct = int(st.progress() * 100)
            if pct >= last + 10:
                last = pct
                log("  %d%%" % pct)
    vid = resp["id"]
    if receipt_path:
        with open(receipt_path + '.tmp', 'w', encoding='utf-8') as marker:
            json.dump({'state':'uploaded','video_id':vid,'channel_id':expected_channel}, marker)
        os.replace(receipt_path + '.tmp', receipt_path)
    log("Upload finished. videoId=%s" % vid)

    # 3. fill {{VIDEO_ID}} in the description (the id only exists after upload)
    if ID_TOKEN in (snippet.get("description") or ""):
        snippet["description"] = snippet["description"].replace(ID_TOKEN, vid)
        yt.videos().update(part="snippet", body={"id": vid, "snippet": snippet}).execute()
        # Read endpoints lag behind writes; poll instead of reading once.
        d = ""
        for _ in range(6):
            back = yt.videos().list(part="snippet", id=vid).execute()
            d = back["items"][0]["snippet"]["description"]
            if ID_TOKEN not in d:
                break
            time.sleep(5)
        log("%s replaced %s with %s" % ("OK" if ID_TOKEN not in d else "NOT", ID_TOKEN, vid))

    # 4. synthetic / altered content flag
    if job.get("aigc", True):
        try:
            cur = yt.videos().list(part="status", id=vid).execute()["items"][0]["status"]
            st2 = dict(cur)
            st2["containsSyntheticMedia"] = True
            yt.videos().update(part="status", body={"id": vid, "status": st2}).execute()
            log("Altered/synthetic content flag written. Verify once in YouTube Studio.")
        except Exception as e:
            msg = str(e)
            if "insufficient" in msg.lower():
                log("Could not set the flag: token lacks youtube.force-ssl. Run auth.py again.")
            else:
                log("Could not set the flag: %s" % msg[:150])
            log("Set 'Altered content' by hand in YouTube Studio for this video.")

    # 5. read back (an OK response is not proof that it took effect)
    time.sleep(4)
    items = yt.videos().list(part="snippet,status", id=vid).execute().get("items") or []
    if not items:
        log("Could not read the video back. Do not assume success; check YouTube Studio.")
        return 3
    it = items[0]
    got_title = it["snippet"]["title"]
    got_priv = it["status"]["privacyStatus"]
    got_at = it["status"].get("publishAt", "")
    log("Read-back: title '%s' | privacy %s | publishAt %s" % (got_title, got_priv, got_at or "none"))
    if got_title != job["title"]:
        log("Title does not match the job. Check it in Studio.")
        return 3
    if got_priv != status['privacyStatus'] or got_at != status.get('publishAt', ''):
        log('Privacy/schedule read-back mismatch. Content may already exist; inspect Studio before any retry.')
        return 3

    if receipt_path:
        if job.get('aigc', True) and it['status'].get('containsSyntheticMedia') is not True:
            log('Synthetic content declaration could not be verified. Do not retry the upload.')
            return 3
        if intended_privacy != status['privacyStatus']:
            from pathlib import Path
            sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
            from automation import STATE
            from automation_client import Client
            import secure_state
            control = Client(secure_state.load(STATE / 'credentials.dpapi'))
            control.lease = os.environ.get('THINKNOVA_RUN_LEASE', '')
            control.receipt(job['automation_run_id'], job.get('automation_steps', {}))
            yt.videos().update(part='status', body={'id':vid, 'status':{'privacyStatus':intended_privacy,'selfDeclaredMadeForKids':bool(job.get('made_for_kids',False)),'containsSyntheticMedia':bool(job.get('aigc',True))}}).execute()
            final = yt.videos().list(part='status', id=vid).execute().get('items') or []
            if not final or final[0]['status'].get('privacyStatus') != intended_privacy:
                log('Final publication not verified; do not re-upload.')
                return 3
        with open(receipt_path + '.tmp', 'w', encoding='utf-8') as marker:
            json.dump({'state':'verified','video_id':vid,'channel_id':expected_channel}, marker)
        os.replace(receipt_path + '.tmp', receipt_path)
    print("\nLink: https://youtube.com/shorts/%s" % vid)
    append_log([time.strftime("%Y-%m-%d %H:%M"), job["title"], vid, got_priv,
                got_at or "", check_note, os.path.basename(video)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
