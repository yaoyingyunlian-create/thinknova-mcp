"""One bounded local speech-runtime repair per run directory; never creates media tasks."""
import json
import os
from pathlib import Path
import subprocess
import sys


def recognize(path, model, language, ffmpeg, **options):
    from render.speech_review import recognize as raw_recognize
    try:
        return raw_recognize(path, model, language, ffmpeg, **options)
    except (RuntimeError, ImportError) as first:
        marker = Path(path).parent / 'speech-runtime-recovery.json'
        if marker.exists():
            raise RuntimeError('SPEECH_CHECK_PENDING: local runtime repair already attempted') from first
        marker.write_text(json.dumps({'attempted': True, 'status': 'repairing'}), encoding='utf-8')
        command = ("import importlib.util; "
                   "import subprocess,sys; "
                   "missing=importlib.util.find_spec('faster_whisper') is None; "
                   "subprocess.run([sys.executable,'-m','pip','install','faster-whisper'],check=True,timeout=120) if missing else None; "
                   "from faster_whisper.utils import download_model; download_model(sys.argv[1])")
        env = {**os.environ, 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'PYTHONIOENCODING': 'utf-8'}
        try:
            repaired = subprocess.run([sys.executable, '-c', command, model], capture_output=True,
                                      env=env, timeout=150)
            marker.write_text(json.dumps({'attempted': True, 'status': 'retried', 'exit_code': repaired.returncode}), encoding='utf-8')
            return raw_recognize(path, model, language, ffmpeg, **options)
        except (RuntimeError, ImportError, OSError, subprocess.SubprocessError) as last:
            marker.write_text(json.dumps({'attempted': True, 'status': 'unknown'}), encoding='utf-8')
            raise RuntimeError('SPEECH_CHECK_PENDING: local runtime unavailable after bounded repair') from last
