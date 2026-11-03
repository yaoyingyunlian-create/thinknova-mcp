"""Windows current-user DPAPI storage; no plaintext fallback."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
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
    data = crypt(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp'); temp.write_bytes(data); os.replace(temp, path)


def load(path: Path) -> dict:
    return json.loads(crypt(path.read_bytes(), True).decode('utf-8'))
