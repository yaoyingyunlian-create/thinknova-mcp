"""Validate the revision 65 story plan used by MCP quotes and local film jobs."""

import re
import unicodedata

BEATS = ('concern', 'explanation', 'process', 'result', 'action')
LINE_KEYS = ('speaker', 'text', 'kind', 'visual')


def validate_story_plan(plan, closing=None):
    def text(value, limit):
        return (isinstance(value, str) and 0 < len(value) <= limit and value == value.strip()
                and all(unicodedata.category(char) not in ('Cc', 'Zl', 'Zp') for char in value))

    def invalid(field, segment=None):
        suffix = f' (segment {segment})' if segment is not None else ''
        raise ValueError(f'FILM_STORY_PLAN_INVALID: {field}{suffix}')

    if (not isinstance(plan, dict) or set(plan) != {'version', 'concern', 'segments', 'beats'}
            or type(plan['version']) is not int or plan['version'] != 1 or not text(plan['concern'], 240)):
        invalid('story_plan')
    segments, beats = plan['segments'], plan['beats']
    if not isinstance(segments, list) or len(segments) not in (3, 4):
        invalid('story_plan.segments')
    if not isinstance(beats, list) or len(beats) != len(BEATS):
        invalid('story_plan.beats')
    exchange = False
    for index, segment in enumerate(segments, 1):
        if (not isinstance(segment, dict) or set(segment) != {'duration_seconds', 'dialogue'}
                or type(segment['duration_seconds']) is not int or not 10 <= segment['duration_seconds'] <= 15
                or not isinstance(segment['dialogue'], list) or len(segment['dialogue']) > 8):
            invalid('story_plan.segments', index)
        previous = None
        for line in segment['dialogue']:
            if (not isinstance(line, dict) or set(line) != set(LINE_KEYS)
                    or line['speaker'] not in ('staff', 'customer')
                    or line['kind'] not in ('question', 'answer', 'statement')
                    or not text(line['text'], 120) or not text(line['visual'], 480)):
                invalid('story_plan.segments.dialogue', index)
            if previous and previous['kind'] == 'question' and line['kind'] == 'answer' and previous['speaker'] != line['speaker']:
                exchange = True
            previous = line
    if not exchange:
        invalid('story_plan.dialogue_exchange')
    previous_position = (0, 0)
    for kind, beat in zip(BEATS, beats):
        if (not isinstance(beat, dict) or set(beat) != {'type', 'segment', 'line', 'visual'}
                or beat['type'] != kind or type(beat['segment']) is not int or not 1 <= beat['segment'] <= len(segments)
                or type(beat['line']) is not int or not text(beat['visual'], 480)):
            invalid(f'story_plan.beats.{kind}')
        segment, line = beat['segment'], beat['line']
        dialogue = segments[segment - 1]['dialogue']
        position = (segment, line)
        valid_line = ((not dialogue and kind in ('process', 'result')) if line == 0 else 1 <= line <= len(dialogue))
        if position < previous_position or not valid_line:
            invalid(f'story_plan.beats.{kind}', segment)
        previous_position = position
    last = segments[-1]['dialogue']
    if (not last or previous_position != (len(segments), len(last)) or last[-1]['speaker'] != 'staff'
            or (closing is not None and closing != [last[-1]['text']])):
        invalid('story_plan.beats.action', len(segments))
    for index, segment in enumerate(segments, 1):
        if not segment['dialogue'] and not any(beat['segment'] == index for beat in beats):
            invalid('story_plan.visual_only', index)
        for offset, line in enumerate(segment['dialogue'], 1):
            direct_action = re.search(r'^(?:请|欢迎|记得)?\s*(?:到店|来店|私信|WhatsApp|PM\b|DM\b)|'
                                      r'^(?:please\s+)?(?:visit us|visit the shop|send us|message us|contact us)|'
                                      r'想.{0,12}(?:就|可)\s*(?:到店|来店|私信)', line['text'], re.I)
            if (re.search(r'评论区|留言区|評論區|留言區|comment below|leave (?:a |your )?comment|in the comments', line['text'], re.I)
                    or ((index, offset) != previous_position and (line['text'] == last[-1]['text'] or direct_action))):
                invalid('story_plan.viewer_action', index)
    source = sum(segment['duration_seconds'] for segment in segments)
    return {'source_seconds': source, 'estimated_final_seconds': round(source / 1.25, 2), 'playback_rate': 1.25,
            'duration_advisory': ('BELOW_TARGET_BEFORE_TRIMMING' if source < 38 else
                                  'TRIM_TO_TARGET_WITHOUT_CUTTING_DIALOGUE' if source > 50 else None)}


def check_story_segments(plan, segments):
    if not isinstance(segments, list) or len(segments) != len(plan['segments']):
        raise ValueError('FILM_STORY_PLAN_INVALID: story_plan.segments')
    for index, (approved, actual) in enumerate(zip(plan['segments'], segments), 1):
        dialogue = actual.get('dialogue') if isinstance(actual, dict) else None
        if (not isinstance(dialogue, list) or any(not isinstance(line, dict) for line in dialogue)
                or [{key: line.get(key) for key in LINE_KEYS} for line in dialogue] != approved['dialogue']
                or actual.get('duration_seconds', actual.get('planned_seconds')) != approved['duration_seconds']):
            raise ValueError(f'FILM_STORY_PLAN_INVALID: story_plan.segments (segment {index})')
