"""Run before each toolkit commit; generate deterministic tracked-source revision."""
import hashlib
import json
import subprocess
from pathlib import Path
from file_integrity import sha256

root = Path(__file__).resolve().parent
paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root).decode('utf-8').split('\0')
files = []
for name in sorted(set(filter(None, paths))):
    if name == 'manifest.json': continue
    path = root / name
    if path.is_file():
        files.append({'path': name, 'sha256': sha256(path, normalize_text=True)})
hashes = {item['path']: item['sha256'] for item in files}
revision = hashlib.sha256(json.dumps(hashes, separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest()
(root / 'manifest.json').write_text(json.dumps({'version': 'thinknova-automation-toolkit-v3.1.11', 'text_line_endings': 'lf', 'revision': revision, 'files': files}, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
print(revision)
