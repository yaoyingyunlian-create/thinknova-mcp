"""Windows current-user DPAPI storage; no plaintext fallback."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
import hashlib
import platform
import subprocess
import base64
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != 'nt': raise RuntimeError('WINDOWS_DPAPI_REQUIRED')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))); target = Blob()
    library = ctypes.windll.crypt32
    if decrypt:
        ok = library.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = library.CryptProtectData(ctypes.byref(source), 'ThinkNova local automation', None, None, None, 1, ctypes.byref(target))
    if not ok: raise RuntimeError('DPAPI_FAILED')
    try: return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.memset(target.data, 0, target.size)
        ctypes.windll.kernel32.LocalFree(target.data)


def save(path: Path, value: dict):
    raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
    if platform.system() == 'Darwin':
        account = hashlib.sha256(str(path.resolve()).encode('utf-8')).hexdigest()
        # Interactive security command via stdin: no secret in argv, environment or files.
        command = 'add-generic-password -U -a %s -s ThinkNova.Automation -w %s\n' % (account, base64.b64encode(raw).decode('ascii'))
        result = subprocess.run(['/usr/bin/security', '-i'], input=command, capture_output=True, text=True, timeout=30)
        if result.returncode: raise RuntimeError('KEYCHAIN_SAVE_FAILED')
        verify=subprocess.run(['/usr/bin/security','find-generic-password','-a',account,'-s','ThinkNova.Automation','-w'],capture_output=True,timeout=30)
        if verify.returncode or verify.stdout.strip()!=base64.b64encode(raw): raise RuntimeError('KEYCHAIN_SAVE_FAILED')
        data = b'THINKNOVA_KEYCHAIN_V1'
    else:
        data = crypt(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp'); temp.write_bytes(data); os.replace(temp, path)


def load(path: Path) -> dict:
    if platform.system() == 'Darwin':
        if path.read_bytes() != b'THINKNOVA_KEYCHAIN_V1': raise RuntimeError('INVALID_KEYCHAIN_MARKER')
        account = hashlib.sha256(str(path.resolve()).encode('utf-8')).hexdigest()
        result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-a', account, '-s', 'ThinkNova.Automation', '-w'], capture_output=True, timeout=30)
        if result.returncode: raise RuntimeError('KEYCHAIN_AUTH_REQUIRED')
        return json.loads(base64.b64decode(result.stdout.strip(), validate=True).decode('utf-8'))
    return json.loads(crypt(path.read_bytes(), True).decode('utf-8'))
