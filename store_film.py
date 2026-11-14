"""Validation for the versioned store-film workflow."""
from __future__ import annotations

import re

BEATS = ('pain', 'process', 'change', 'service')
ASSET = re.compile(r'asset_[A-Za-z0-9]{1,58}')


def validate_beats(segments, film_type):
    if film_type not in ('story', 'showcase'):
        raise ValueError('FILM_TYPE_INVALID')
    if film_type == 'story':
        beats = []
        for segment in segments:
            values = segment.get('beats')
            if not isinstance(values, list) or not values or any(beat not in BEATS for beat in values):
                raise ValueError('FILM_BEATS_REQUIRED')
            for beat in values:
                if not beats or beats[-1] != beat:
                    beats.append(beat)
        if tuple(beats) != BEATS:
            raise ValueError('FILM_BEATS_REQUIRED: pain, process, change, service')


def generation_arguments(segment, shop_assets, authorized_assets):
    prompt = segment.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('FILM_PROMPT_REQUIRED')
    from generation_quality import prepare_prompt
    prompt = prepare_prompt(prompt.strip(), 'video', segment.get('negative_prompt'))
    board = segment.get('character_sheet_asset_id')
    if segment.get('recurring_character') and not board:
        raise ValueError('FILM_CHARACTER_SHEET_REQUIRED')
    if board is not None:
        if not isinstance(board, str) or not ASSET.fullmatch(board) or board not in authorized_assets:
            raise ValueError('FILM_CHARACTER_SHEET_NOT_AUTHORIZED')
        if board == segment.get('first_frame_asset_id'):
            raise ValueError('FILM_CHARACTER_SHEET_CANNOT_BE_FIRST_FRAME')
        prompt += (
            '\nContinue from the actual shot first frame. Preserve the same character face, hair and clothing. '
            'Avoid identity drift, wardrobe changes and extra or fused fingers.'
        )
    length = len(prompt.encode('utf-8'))
    if length > 3500:
        raise ValueError(f'FILM_PROMPT_TOO_LONG: {length}/3500 UTF-8 bytes')
    seconds = segment.get('duration_seconds')
    if type(seconds) is not int or not 6 <= seconds <= 15:
        raise ValueError('FILM_DURATION_REQUIRED: specify an integer from 6 to 15')
    first = segment.get('first_frame_asset_id')
    refs = segment.get('reference_asset_ids', [])
    if not isinstance(refs, list) or len(refs) > 3 or any(not isinstance(ref, str) or not ASSET.fullmatch(ref) for ref in refs):
        raise ValueError('FILM_REFERENCE_INVALID')
    if not isinstance(first, str) or not ASSET.fullmatch(first):
        raise ValueError('FILM_FIRST_FRAME_REQUIRED')
    refs = list(dict.fromkeys([first, *([board] if board else []), *refs]))
    if len(refs) > 3 or any(ref not in authorized_assets for ref in refs):
        raise ValueError('FILM_REFERENCE_NOT_AUTHORIZED')
    location = segment.get('shop_location')
    if location and not set(refs).intersection(shop_assets.get(location, [])):
        raise ValueError('FILM_SHOP_REFERENCE_REQUIRED')
    result = {'prompt': prompt, 'duration_seconds': seconds, 'reference_asset_ids': refs,
            'visual_subject': 'customer_identity' if location or segment.get('customer_identity') else 'generic',
            'film_profile': 'store_v2'}
    if location:
        result['shop_location'] = location
    return result



def validate_day_plan(plan):
    from datetime import date

    if not isinstance(plan, dict) or plan.get('schema_version') != 1:
        raise ValueError('DAY_PLAN_SCHEMA_UNSUPPORTED')
    day = plan.get('date')
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or type(plan.get('rules_version')) is not int:
        raise ValueError('DAY_PLAN_DATE_OR_RULES_INVALID')
    for field in ('shop_name', 'featured_service', 'opening', 'visual_batch'):
        if not isinstance(plan.get(field), str) or not plan[field].strip():
            raise ValueError(f'DAY_PLAN_REQUIRED: {field}')
    segments = plan.get('segments')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 12 or any(not isinstance(s, dict) for s in segments):
        raise ValueError('DAY_PLAN_SEGMENTS_INVALID')
    validate_beats(segments, plan.get('film_type'))
    for segment in segments:
        lines = segment.get('subs')
        if not isinstance(lines, list) or not lines or any(not isinstance(line, str) or not line.strip() for line in lines):
            raise ValueError('DAY_PLAN_CAPTIONS_REQUIRED')
    platforms = plan.get('platforms')
    if not isinstance(platforms, dict) or not platforms:
        raise ValueError('DAY_PLAN_PLATFORMS_REQUIRED')
    from publish.dispatch import validate_variants
    validate_variants({'platforms': platforms})
    from store_editorial import validate_plan_copy
    if plan.get('project_key'):
        validate_plan_copy(plan)
    else:
        validate_plan_copy({'opening': plan['opening'], 'date': day}, targets=platforms)
    for name, variant in platforms.items():
        fields = ('title',) if plan.get('project_key') else ('title', 'description')
        if not all(isinstance(variant.get(key), str) and variant[key].strip() for key in fields):
            raise ValueError(f'DAY_PLAN_PUBLICATION_COPY_REQUIRED: {name}')
    durations = [segment.get('duration_seconds') for segment in segments]
    if any(type(seconds) is not int or not 6 <= seconds <= 15 for seconds in durations):
        raise ValueError('FILM_DURATION_REQUIRED: specify an integer from 6 to 15')
    total = sum(durations)
    if set(platforms) != {'xiaohongshu'}:
        card = plan.get('end_card')
        if not isinstance(card, dict) or not card.get('lines'):
            raise ValueError('DAY_PLAN_END_CARD_REQUIRED')
        outro = card.get('dur', 2.2)
        if type(outro) not in (int, float) or not 0 < outro <= 10:
            raise ValueError('DAY_PLAN_END_CARD_DURATION_INVALID')
        total += outro
    if not 30 <= total <= 40:
        raise ValueError('DAY_PLAN_FILM_DURATION: target 30–40 seconds including the end card')
    return plan
