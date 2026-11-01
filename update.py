"""Install an approved MCP download into a NEW folder; never overwrite local data."""
import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path


def install(url, expected_sha, destination):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'api.thinknova.top' or parsed.path != '/api/v1/mcp/toolkit/download':
        raise ValueError('Use the short-lived download URL returned by ThinkNova MCP.')
    destination = Path(destination).resolve()
    if destination.exists(): raise ValueError('Choose a new folder; existing installations are preserved.')
    with tempfile.TemporaryDirectory(prefix='thinknova-update-') as staging:
        archive_path = Path(staging) / 'toolkit.zip'
        with urllib.request.urlopen(url, timeout=60) as response, archive_path.open('wb') as stream:
            if urllib.parse.urlsplit(response.url).hostname != 'api.thinknova.top': raise ValueError('Unexpected download redirect.')
            size = 0
            while True:
                chunk = response.read(65536)
                if not chunk: break
                size += len(chunk)
                if size > 100 * 1024 * 1024: raise ValueError('Package exceeds the download limit.')
                stream.write(chunk)
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != expected_sha.lower(): raise ValueError('Package SHA-256 mismatch.')
        extracted = Path(staging) / 'package'
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                path = (extracted / info.filename).resolve()
                if '\\' in info.filename or not path.is_relative_to(extracted.resolve()) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Unsafe archive path.')
            if sum(info.file_size for info in archive.infolist()) > 300 * 1024 * 1024: raise ValueError('Expanded package is too large.')
            archive.extractall(extracted)
        manifest = json.loads((extracted / 'manifest.json').read_text(encoding='utf-8'))
        for entry in manifest['files']:
            path = (extracted / entry['path']).resolve()
            if not path.is_relative_to(extracted.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('Manifest verification failed.')
        shutil.copytree(extracted, destination)
    print('Verified package installed at %s. Existing memory and sessions remain in the previous folder.' % destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True); parser.add_argument('--sha256', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--user-confirmed', action='store_true', required=True)
    args = parser.parse_args()
    install(args.url, args.sha256, args.destination)
