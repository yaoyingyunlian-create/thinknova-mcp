"""Small process lock for local memory/metrics writes. Locks release on process exit."""
from contextlib import contextmanager
from pathlib import Path
import os
import time


class LocalStateBusy(RuntimeError):
    pass


@contextmanager
def state_lock(path, timeout=5):
    lock_path = Path(path).with_name('.' + Path(path).name + '.lock')
    with lock_path.open('a+b') as handle:
        if handle.tell() == 0: handle.write(b'0'); handle.flush()
        started = time.monotonic()
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - started >= timeout: raise LocalStateBusy('Local state is busy: %s. Retry later; no data was overwritten.' % path)
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
