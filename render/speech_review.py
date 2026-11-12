"""Read-only local spoken-term audit. ASR agreement never certifies pronunciation."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
from types import SimpleNamespace
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


def recognize_local(path, model_name, language, ffmpeg=None, **options):
    print("SPEECH_PHASE:model_load", file=sys.stderr, flush=True)
    try:
        model = ensure_runtime(model_name)
    except Exception as exc:
        raise RuntimeError('SPEECH_MODEL_UNAVAILABLE: prepare faster-whisper and the local model cache') from exc
    print("SPEECH_PHASE:audio_decode", file=sys.stderr, flush=True)
    audio = decode_audio(path, ffmpeg)
    print("SPEECH_PHASE:transcription", file=sys.stderr, flush=True)
    try:
        segments, info = model.transcribe(audio, language=language, **options)
        return list(segments), info
    except Exception as exc:
        raise RuntimeError('SPEECH_TRANSCRIPTION_FAILED: inspect audio and language settings') from exc


def recognize(path, model_name, language, ffmpeg=None, **options):
    payload = json.dumps([str(path), model_name, language, ffmpeg, options])
    try:
        run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
                             input=payload, capture_output=True, encoding='utf-8', errors='replace', timeout=150)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('SPEECH_WORKER_TIMEOUT') from exc
    if run.returncode < 0 or run.returncode >= 128:
        phases = re.findall(r'^SPEECH_PHASE:(model_load|audio_decode|transcription)$', run.stderr, re.M)
        phase = phases[-1] if phases else 'startup'
        raise RuntimeError(f'SPEECH_WORKER_CRASH: {phase}, exit code {run.returncode}')
    try:
        result = json.loads(run.stdout)
    except ValueError as exc:
        raise RuntimeError(f'SPEECH_WORKER_FAILED: exit code {run.returncode}') from exc
    if run.returncode:
        raise RuntimeError(result.get('error', 'SPEECH_WORKER_FAILED'))
    segments = []
    for segment in result['segments']:
        segment['words'] = [SimpleNamespace(**word) for word in segment['words']]
        segments.append(SimpleNamespace(**segment))
    return segments, SimpleNamespace(language=result['language'])


def worker():
    path, model, language, ffmpeg, options = json.load(sys.stdin)
    try:
        segments, info = recognize_local(path, model, language, ffmpeg, **options)
        result = {'language': info.language, 'segments': [
            {'start': segment.start, 'end': segment.end, 'text': segment.text,
             'words': [{'start': word.start, 'end': word.end, 'word': word.word}
                       for word in (segment.words or [])]}
            for segment in segments
        ]}
        code = 0
    except (RuntimeError, ImportError) as exc:
        result, code = {'error': str(exc)}, 2
    print(json.dumps(result))
    return code



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

if __name__ == '__main__': raise SystemExit(worker() if sys.argv[1:] == ['--worker'] else main())
