"""Versioned store-film decisions. Unknown recognition is a warning under policy 58."""
HARD_CODES = {'S1', 'S1a', 'S1b', 'S1d', 'FILM_STORE_RESOLUTION', 'FILM_DURATION',
              'MEDIA_DECODE_FAILED', 'MEDIA_BLACK', 'S3_NEAR_SILENT', 'FILM_DIALOGUE_MISMATCH'}
NATIVE_VERSION = 'native_dialogue_v1'
NATIVE_WARNINGS = {'FILM_PACE_OUTSIDE_LIMIT', 'FILM_PACE_UNAVAILABLE', 'FILM_SENTENCE_PAUSE',
                   'FILM_SPEECH_GAP', 'FILM_SEGMENT_SPEECH_GAP', 'SPEECH_CHECK_PENDING',
                   'FILM_DIALOGUE_REVIEW_REQUIRED', 'FILM_CAPTION_ALIGNMENT_PENDING'}


def native(value):
    return isinstance(value, dict) and value.get('version') == NATIVE_VERSION


def native_film(job):
    return job.get('film') is True or job.get('film_profile') == 'store_v2'


def check_film_audio_inputs(job):
    if not native_film(job):
        return
    for index, clip in enumerate(job.get('clips', []), 1):
        if isinstance(clip, dict) and (clip.get('voice') or clip.get('audio') == 'mute'):
            raise ValueError(f'FILM_NATIVE_AUDIO_REQUIRED: clip {index}; use the original generated video and its original audio')


def store_policy(value=None):
    if isinstance(value, dict) and (value.get('version') in ('58', NATIVE_VERSION)
                                  or value.get('audio_source') == 'legacy_processing'):
        return value
    return {'version': NATIVE_VERSION, 'audio_source': 'video_original', 'speech_unknown_action': 'warn'}


def enabled(value):
    return isinstance(value, dict) and value.get('version') in ('58', NATIVE_VERSION)


def agreement(score):
    if score is None:
        return 'warn', 'SPEECH_CHECK_PENDING'
    if score < 0.3:
        return 'fail', 'FILM_DIALOGUE_MISMATCH'
    return ('warn', 'FILM_DIALOGUE_REVIEW_REQUIRED') if score < 0.8 else ('pass', 'DIALOGUE_MATCH')


def receipt(policy, diagnostics):
    unknown = any(item['code'] in ('SPEECH_CHECK_PENDING', 'FILM_PACE_UNAVAILABLE', 'FILM_CHECK_TIMEOUT', 'FILM_CAPTION_ALIGNMENT_PENDING')
                  for item in diagnostics)
    return {'quality_policy_version': policy.get('version', 'legacy'), 'warnings': diagnostics,
            'speech_status': 'unknown' if unknown else 'checked', 'checks_completed': not unknown}
