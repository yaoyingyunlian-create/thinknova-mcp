"""Read-only local spoken-term audit. ASR agreement never certifies pronunciation."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def normalize(text):
    return re.sub(r"[\W_]", "", text, flags=re.UNICODE).casefold()


def evaluate(segments, required):
    transcript = "".join(segment['text'] for segment in segments)
    missing = [term for term in required if normalize(term) not in normalize(transcript)]
    return {'status': 'speech_mismatch' if missing else 'needs_listening_review',
            'missing_terms': missing, 'segments': segments,
            'pronunciation_verified': False, 'publication_ready': False,
            'next_action': 'Listen to the source audio and verify the intended words; never fix speech by changing subtitle spelling.'}


def ensure_runtime(model_name='small'):
    import numpy
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device='cpu', compute_type='int8', local_files_only=True)


def decode_audio(path, ffmpeg=None):
    import numpy as np
    import os
    ffmpeg = ffmpeg or os.getenv('FFMPEG') or 'ffmpeg'
    try:
        result = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-vn', '-ac', '1',
                                 '-ar', '16000', '-f', 'f32le', 'pipe:1'],
                                check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('SPEECH_DECODE_FAILED') from exc
    if not result.stdout:
        raise RuntimeError('SPEECH_AUDIO_MISSING')
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def recognize(path, model_name, language, ffmpeg=None, **options):
    try:
        model = ensure_runtime(model_name)
    except Exception as exc:
        raise RuntimeError('SPEECH_MODEL_UNAVAILABLE: prepare faster-whisper and the local model cache') from exc
    audio = decode_audio(path, ffmpeg)
    try:
        segments, info = model.transcribe(audio, language=language, **options)
        return list(segments), info
    except Exception as exc:
        raise RuntimeError('SPEECH_TRANSCRIPTION_FAILED: inspect audio and language settings') from exc


def transcribe(path, model_name='small', language='zh'):
    segments, _ = recognize(path, model_name, language, beam_size=5)
    return [{'start':round(segment.start,2),'end':round(segment.end,2),'text':segment.text} for segment in segments]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('media', type=Path)
    parser.add_argument('--required', action='append', required=True, help='Exact intended spoken term; repeat for several terms')
    parser.add_argument('--model', default='small')
    parser.add_argument('--lang', default='zh')
    args = parser.parse_args()
    if any(not normalize(term) for term in args.required): parser.error('required terms must contain letters or numbers')
    try:
        digest = hashlib.sha256(args.media.read_bytes()).hexdigest()
        report = evaluate(transcribe(args.media,args.model,args.lang),args.required)
        report['source_sha256'] = digest
        print(json.dumps(report,ensure_ascii=False))
        return 2 if report['missing_terms'] else 0
    except (Exception, SystemExit) as exc:
        print(json.dumps({'status':'not_checked','pronunciation_verified':False,'publication_ready':False,
                          'error_code':'SPEECH_REVIEW_UNAVAILABLE','failure':type(exc).__name__,
                          'next_action':'Check FFmpeg, faster-whisper and its local model cache. No model is downloaded automatically.'}))
        return 3

if __name__ == '__main__': raise SystemExit(main())
