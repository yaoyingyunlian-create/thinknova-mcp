from pathlib import Path
import hashlib

def sha256(path: Path, normalize_text: bool = False) -> str:
    if normalize_text and (path.name == ".gitignore" or path.suffix in {
        ".html", ".json", ".md", ".ps1", ".py", ".sh", ".txt",
    }):
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_mismatches(root, manifest):
    root = root.resolve()
    entries = manifest.get('files')
    if not isinstance(entries, list) or not entries:
        return ['manifest.json']
    normalize = manifest.get('text_line_endings') == 'lf'
    failures = []
    for entry in entries:
        name = entry['path']
        path = (root / name).resolve()
        if (root not in path.parents or not path.is_file()
                or sha256(path, normalize_text=normalize) != entry.get('sha256')):
            failures.append(name)
    return failures
