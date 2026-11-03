# -*- coding: utf-8 -*-
"""YouTube shared layer: OAuth credentials + API client. Other YouTube scripts import this.

Files in this folder (both are credentials - keep them private, never commit them):
  oauth_client.json   Your own OAuth client, downloaded from Google Cloud Console
                      (APIs & Services -> Credentials -> Create credentials ->
                      OAuth client ID -> Desktop app -> Download JSON, then rename).
  token.json          Created by auth.py after you click "Allow" in the browser.

You can point to other locations with environment variables:
  YT_OAUTH_CLIENT=/path/to/oauth_client.json   YT_TOKEN=/path/to/token.json
"""
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.environ.get("YT_OAUTH_CLIENT") or os.path.join(HERE, "oauth_client.json")
TOKEN = os.environ.get("YT_TOKEN") or os.path.join(HERE, "token.json")

# upload   = upload videos
# readonly = read your own channel / videos
# force-ssl = videos.update (set the AI / altered-content flag, change privacy) and captions.
#   Without force-ssl you can upload but not edit: updates fail with 403
#   "insufficient authentication scopes".
#   If you change this list, run auth.py again (it re-authorises automatically).
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _client_config():
    if not os.path.isfile(CLIENT):
        raise SystemExit(
            "OAuth client file not found: %s\n"
            "  Create one in Google Cloud Console (OAuth client ID -> Desktop app),\n"
            "  download the JSON and save it as oauth_client.json in this folder." % CLIENT)
    with io.open(CLIENT, encoding="utf-8") as f:
        return json.load(f)


def get_creds(interactive=False):
    """Return valid credentials. Opens a browser only when interactive=True."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    if os.path.isfile(TOKEN):
        try:
            if TOKEN.endswith('.dpapi'):
                from pathlib import Path
                sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
                import secure_state
                creds = Credentials.from_authorized_user_info(secure_state.load(Path(TOKEN)), SCOPES)
            else:
                creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
        except Exception as e:
            print("Saved token could not be read (%s); you need to authorise again." % str(e)[:60])
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception as e:
            print("Token refresh failed (%s); you need to authorise again." % str(e)[:80])

    if not interactive:
        raise SystemExit("No usable authorisation. Run once:  python auth.py")

    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    print("\nA browser window will open. Sign in with the Google account that owns "
          "your YouTube channel and click Allow.")
    creds = flow.run_local_server(port=0, prompt="consent",
                                  authorization_prompt_message="If it does not open, visit: {url}")
    _save(creds)
    return creds


def _save(creds):
    if TOKEN.endswith('.dpapi'):
        from pathlib import Path
        sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
        import secure_state
        secure_state.save(Path(TOKEN), json.loads(creds.to_json()))
        print('YouTube credentials protected with Windows DPAPI.')
        return
    with io.open(TOKEN, "wb") as f:
        f.write(creds.to_json().encode("utf-8"))
    try:
        os.chmod(TOKEN, 0o600)
    except Exception:
        pass
    print("Authorisation saved to %s (this is a credential: keep it private)." % os.path.basename(TOKEN))


def youtube(interactive=False):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=get_creds(interactive), cache_discovery=False)


def my_channel(yt):
    r = yt.channels().list(part="snippet,contentDetails,statistics", mine=True).execute()
    items = r.get("items") or []
    if not items:
        raise SystemExit("This Google account has no YouTube channel. Authorise with the account that owns the channel.")
    c = items[0]
    return {
        "id": c["id"],
        "title": c["snippet"]["title"],
        "handle": c["snippet"].get("customUrl", ""),
        "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"],
        "subs": c["statistics"].get("subscriberCount"),
        "videos": c["statistics"].get("videoCount"),
        "views": c["statistics"].get("viewCount"),
    }
