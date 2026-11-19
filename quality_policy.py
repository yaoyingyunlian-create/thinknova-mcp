"""Versioned store-film decisions. Unknown recognition is a warning under policy 58."""
HARD_CODES = {'S1', 'S1a', 'S1b', 'S1d', 'FILM_STORE_RESOLUTION', 'FILM_DURATION',
              'MEDIA_DECODE_FAILED', 'MEDIA_BLACK', 'S3_NEAR_SILENT', 'FILM_DIALOGUE_MISMATCH'}


def enabled(value):
    return isinstance(value, dict) and value.get('version') == '58'


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
