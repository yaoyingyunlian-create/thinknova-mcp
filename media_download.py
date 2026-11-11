"""Download managed video assets with bounded retries and validated Range recovery."""
import http.client
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

class MediaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

MAX_BYTES = 256 * 1024 * 1024


def validate_media(path):
    try:
        subprocess.run([os.getenv('FFMPEG') or 'ffmpeg', '-v', 'error', '-xerror',
                        '-i', str(path), '-map', '0:v:0', '-map', '0:a:0?', '-f', 'null', '-'],
                       check=True, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('DELIVERY_DECODE_FAILED') from exc


def open_media(opener, url, headers):
    try:
        return opener.open(urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code not in (302, 303, 307, 308):
            raise
        target = exc.headers.get('Location', '')
        exc.close()
        destination = urllib.parse.urlsplit(target)
        if (destination.scheme != 'https'
                or destination.netloc != 'thinknova-previews.oss-ap-southeast-1.aliyuncs.com'
                or not destination.path.startswith('/generated-assets/')
                or not destination.query):
            raise RuntimeError('UNSAFE_DELIVERY_REDIRECT') from None
    return opener.open(urllib.request.Request(target, headers=headers), timeout=60)

def download(url: str, path: Path, task_id=None):
    parsed = urllib.parse.urlsplit(url)
    asset = re.fullmatch(r'/api/v1/assets/(asset_[A-Za-z0-9]+)/media', parsed.path)
    if (parsed.scheme != 'https' or parsed.hostname != 'api.thinknova.top'
            or parsed.username or parsed.password or not asset):
        raise RuntimeError('UNSAFE_DELIVERY_URL')
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
             if key != 'download']
    direct_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ''))
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                  urllib.parse.urlencode(query + [('download', '1')]), ''))
    partial = path.with_suffix('.part')
    failure = path.with_suffix('.download-error.json')
    partial.unlink(missing_ok=True)
    total = None
    opener = urllib.request.build_opener(MediaRedirectHandler())
    evidence = {'task_id': task_id, 'asset_id': asset.group(1), 'attempts': []}
    try:
        for attempt in range(3):
            start = partial.stat().st_size if partial.exists() else 0
            headers = {'User-Agent': 'ThinkNova-Controlled-Runner/1.0'}
            if start:
                headers['Range'] = f'bytes={start}-'
            row = {'status': None, 'declared_bytes': total, 'received_bytes': start, 'request_id': None}
            evidence['attempts'].append(row)
            try:
                with open_media(opener, url, headers) as response:
                    row.update(status=response.status, request_id=response.headers.get('X-Request-ID'))
                    if not response.headers.get('Content-Type', '').lower().startswith(('video/', 'application/octet-stream')):
                        raise RuntimeError('INVALID_DELIVERY_TYPE')
                    length = response.headers.get('Content-Length', '')
                    if length and not length.isdecimal():
                        raise RuntimeError('INVALID_DELIVERY_LENGTH')
                    if response.status == 206:
                        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                        if not start or not match:
                            raise RuntimeError('INVALID_DELIVERY_RANGE')
                        low, high, declared = map(int, match.groups())
                        if (low != start or declared != total or not low <= high < declared
                                or (length and int(length) != high - low + 1)):
                            raise RuntimeError('INVALID_DELIVERY_RANGE')
                        end = high + 1
                    elif response.status == 200 and length:
                        start, total = 0, int(length)
                        end = total
                    else:
                        raise RuntimeError('INVALID_DELIVERY_LENGTH')
                    row.update(declared_bytes=total, received_bytes=start)
                    if not 0 < total <= MAX_BYTES:
                        raise RuntimeError('DELIVERY_TOO_LARGE' if total else 'INVALID_DELIVERY_LENGTH')
                    received = start
                    with partial.open('ab' if start else 'wb') as stream:
                        while True:
                            interrupted = False
                            try:
                                chunk = response.read(1024 * 1024)
                            except http.client.IncompleteRead as exc:
                                chunk = exc.partial
                                interrupted = True
                            if not chunk:
                                break
                            received += len(chunk)
                            row['received_bytes'] = received
                            if received > end:
                                raise RuntimeError('INVALID_DELIVERY_LENGTH')
                            stream.write(chunk)
                            if interrupted:
                                break
                    if received != total:
                        row['error'] = 'DELIVERY_INCOMPLETE'
                        continue
                validate_media(partial)
                os.replace(partial, path)
                failure.unlink(missing_ok=True)
                return
            except urllib.error.HTTPError as exc:
                row.update(status=exc.code, request_id=exc.headers.get('X-Request-ID'))
                if exc.fp is not None:
                    exc.close()
                if exc.code != 500:
                    raise RuntimeError(f'DELIVERY_HTTP_{exc.code}') from None
                row['error'] = 'DELIVERY_HTTP_500'
                url = direct_url
            except (OSError, http.client.HTTPException):
                row['error'] = 'DELIVERY_INTERRUPTED'
        raise RuntimeError(evidence['attempts'][-1]['error'])
    except RuntimeError as exc:
        evidence['error'] = str(exc)
        failure.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
    finally:
        partial.unlink(missing_ok=True)
