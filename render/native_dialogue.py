"""Compare a generated clip to its script and keep reusable local timing evidence."""
import hashlib
import json
import re
import subprocess

from file_integrity import sha256
from render.speech_review import caption_agreement, caption_chars, caption_match


def script_lines(clip):
    dialogue = [line['text'] for line in clip.get('dialogue', [])
                if isinstance(line, dict) and isinstance(line.get('text'), str) and line['text'].strip()]
    return dialogue or clip.get('subs') or ([clip['text']] if clip.get('text') else [])


def partial_cues(lines, words, duration):
    actual, timings = [], []
    for word in words:
        text = caption_chars(word.word)
        if not text or not 0 <= word.start < word.end <= duration + 0.05:
            continue
        end = min(word.end, duration)
        if end <= word.start or (timings and word.start < timings[-1][1] - 0.001):
            continue
        width = (end - word.start) / len(text)
        actual.extend(text)
        timings.extend((word.start + i * width, word.start + (i + 1) * width) for i in range(len(text)))
    expected = [caption_chars(line) for line in lines]
    matcher = caption_match([char for line in expected for char in line], actual)
    positions = {a + i: b + i for a, b, size in matcher.get_matching_blocks() for i in range(size)}
    result, left = {}, 0
    for index, line in enumerate(expected):
        right = left + len(line)
        matches = [positions[i] for i in range(left, right) if i in positions]
        if matches and len(matches) / len(line) >= 0.8:
            result[str(index)] = [timings[matches[0]][0], timings[matches[-1]][1]]
        left = right
    return result, matcher.ratio()


def acoustic_silence(path, ffmpeg, start, duration):
    run = subprocess.run([ffmpeg, '-nostdin', '-v', 'info', '-ss', str(start), '-i', str(path), '-t', str(duration),
                          '-map', '0:a:0', '-af', 'silencedetect=n=-40dB:d=0.25', '-f', 'null', '-'],
                         capture_output=True, encoding='utf-8', errors='replace', timeout=30)
    silent = sum(float(value) for value in re.findall(r'silence_duration:\s*([\d.]+)', run.stderr))
    return run.returncode == 0 and silent >= duration * 0.95


def inspect(path, lines, language, ffmpeg, duration, has_audio, cache, task_id=None, start=0, *, resume=False):
    from automation import atomic
    from local_state import state_lock
    from speech_recovery import recognize

    start, duration = round(float(start), 6), round(float(duration), 6)
    digest = sha256(path)
    identity = [digest, lines, language, task_id, start, duration]
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    record = cache / (key + '.json')
    with state_lock(record):
        return inspect_cached(path, lines, language, ffmpeg, duration, has_audio, record,
                              task_id, start, digest, resume, atomic, recognize)


def inspect_cached(path, lines, language, ffmpeg, duration, has_audio, record,
                   task_id, start, digest, resume, atomic, recognize):
    try:
        previous = json.loads(record.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict) or previous.get('source_sha256') != digest or 'status' not in previous:
        previous = {}
    if previous and (not resume or previous['status'] not in ('timing_pending', 'transcription_unavailable')):
        return previous
    report = {'task_id': task_id, 'source_sha256': digest, 'duration_seconds': duration, 'cues': {}}
    if not has_audio:
        report.update(status='missing_audio', code='FILM_NATIVE_AUDIO_MISSING')
    else:
        try:
            silent = acoustic_silence(path, ffmpeg, start, duration)
        except (OSError, subprocess.SubprocessError):
            silent = False
        if silent:
            report.update(status='silent_audio', code='FILM_NATIVE_AUDIO_SILENT')
        elif not lines:
            report.update(status='script_unavailable', code='FILM_DIALOGUE_SCRIPT_UNAVAILABLE')
        else:
            try:
                check_lines(path, lines, language, ffmpeg, start, duration, report, previous, recognize)
            except (RuntimeError, ImportError) as exc:
                report.update(status='transcription_unavailable', code='SPEECH_CHECK_PENDING',
                              cause=str(exc).split(':', 1)[0], missing_lines=unmatched_lines(lines, report['cues']))
    atomic(record, report)
    return report


def unmatched_lines(lines, cues):
    return [index + 1 for index in range(len(lines)) if str(index) not in cues]


def check_lines(path, lines, language, ffmpeg, start, duration, report, previous, recognize):
    cues = report['cues'] = {**previous.get('cues', {})}
    expected = ''.join(lines)
    if previous.get('primary_completed'):
        first_text = previous['primary_text']
        first_score = previous['primary_agreement']
    else:
        segments, _ = recognize(path, 'small', language, ffmpeg, word_timestamps=True, vad_filter=True,
                                audio_window=[start, duration])
        words = [word for span in segments for word in span.words or ()]
        first_text = ''.join(word.word for word in words)
        aligned, first_score = partial_cues(lines, words, duration)
        cues.update(aligned)
    report.update(primary_completed=True, primary_agreement=first_score, primary_text=first_text)
    missing = unmatched_lines(lines, cues)
    ranges = []
    for index in (item - 1 for item in missing):
        if ranges and ranges[-1][1] == index - 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    checked = report['checked_windows'] = dict(previous.get('checked_windows', {}))
    for lo, hi in sorted(ranges, key=lambda pair: (
        -int(pair[1] == len(lines) - 1 or any(
            re.search(r'\d|地址|预约|私信|电话|WhatsApp', line, re.I) for line in lines[pair[0]:pair[1] + 1])),
        pair[0],
    )):
        left = cues.get(str(lo - 1), [0, 0])[1]
        right = cues.get(str(hi + 1), [duration, duration])[0]
        window_key = f'{lo}:{hi}'
        if right - left < 0.25 or window_key in checked:
            continue
        second, _ = recognize(path, 'small', language, ffmpeg, word_timestamps=True, vad_filter=False,
                              beam_size=5, audio_window=[start + left, right - left])
        second_words = [word for span in second for word in span.words or ()]
        second_text = ''.join(word.word for word in second_words)
        subset, score = partial_cues(lines[lo:hi + 1], second_words, right - left)
        checked[window_key] = {'text': second_text, 'agreement': score, 'seconds': [left, right]}
        for index, (begin, end) in subset.items():
            target = str(lo + int(index))
            if 0 <= begin < end <= right - left:
                cues.setdefault(target, [left + begin, left + end])
        reason = None
        if (lo == 0 and hi == len(lines) - 1 and first_text.strip() and second_text.strip()
                and first_score < 0.3 and score < 0.3 and caption_agreement(first_text, second_text) >= 0.75):
            reason = 'two_consistent_wrong_transcripts'
        elif lo == hi and 0 < lo < len(lines) - 1 and not second_text.strip() and right - left >= 0.75:
            try:
                if acoustic_silence(path, ffmpeg, start + left, right - left):
                    reason = 'silent_gap_between_aligned_lines'
            except (OSError, subprocess.SubprocessError):
                pass
        if reason:
            report.update(status='dialogue_mismatch', code='FILM_DIALOGUE_MISMATCH',
                          missing_lines=unmatched_lines(lines, cues), evidence=reason)
            return
    missing = unmatched_lines(lines, cues)
    report.update(status='timing_pending' if missing else 'aligned',
                  code='FILM_CAPTION_ALIGNMENT_PENDING' if missing else '', missing_lines=missing)
