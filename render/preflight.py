"""Exercise the local media and speech pipeline before starting a paid film."""
from pathlib import Path
import re
import subprocess
import tempfile

from render.assemble import Stop, probe, tool


def film_preflight():
    try:
        ffmpeg, ffprobe = tool('ffmpeg'), tool('ffprobe')
    except Stop:
        return {'status': 'blocked', 'stage': 'media', 'error': 'FILM_MEDIA_TOOLS_MISSING'}
    with tempfile.TemporaryDirectory(prefix='thinknova-film-preflight-') as work:
        folder = Path(work)
        (folder / 'test.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nCheck\n', encoding='utf-8')
        fixture = folder / 'check.mp4'
        try:
            subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=blue:s=180x320:d=1.5', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=1.5', '-vf', 'subtitles=test.srt',
                            '-c:v', 'libx264', '-c:a', 'aac', str(fixture)],
                           cwd=folder, capture_output=True, check=True, timeout=25)
            duration, _, has_audio = probe(ffprobe, str(fixture))
            if duration < 1 or not has_audio:
                raise ValueError('invalid test media')
        except (OSError, subprocess.SubprocessError, Stop, ValueError):
            return {'status': 'blocked', 'stage': 'media', 'error': 'FILM_MEDIA_PIPELINE_UNAVAILABLE'}
        # A test tone exercises model loading, native inference and decoding without synthesizing dialogue.
        from render.speech_review import recognize
        try:
            try:
                recognize(fixture, 'small', 'en', ffmpeg, word_timestamps=True, vad_filter=False)
            except RuntimeError as exc:
                if not str(exc).startswith('SPEECH_MODEL_UNAVAILABLE:'):
                    raise
                from speech_recovery import recognize as repair_and_recognize
                repair_and_recognize(fixture, 'small', 'en', ffmpeg, word_timestamps=True, vad_filter=False)
        except (RuntimeError, ImportError) as exc:
            code = str(exc).split(':', 1)[0]
            return {'status': 'blocked', 'stage': 'speech', 'error': code if re.fullmatch(r'SPEECH_[A-Z_]+', code)
                    else 'SPEECH_RUNTIME_UNAVAILABLE'}
    return {'status': 'ready', 'stage': 'complete'}


def require_film_preflight(steps):
    if steps.get('local_film_preflight') != 'passed':
        result = film_preflight()
        if result['status'] != 'ready':
            raise RuntimeError(result['error'])
        steps['local_film_preflight'] = 'passed'
