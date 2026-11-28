"""Validation for the versioned store-film workflow."""
from __future__ import annotations

import re

BEATS = ('pain', 'process', 'change', 'service')
ASSET = re.compile(r'asset_[A-Za-z0-9]{1,58}')


def missing_product_facts(shop):
    product = (shop.get('featured_service') or '').strip() or (shop.get('products') or '').strip()
    normalize = lambda value: ''.join(char for char in value.lower() if char.isalnum())
    names = {normalize(value or '') for value in (product, shop.get('name'), shop.get('products'))}
    facts = shop.get('confirmed_facts') or {}
    independent = {normalize(fact) for key in ('methods_and_reasons', 'visible_details')
                   for fact in facts.get(key, []) if isinstance(fact, str)} - names - {''}
    missing = []
    if not product:
        missing.append('shop_profile.featured_service')
    if not independent:
        missing.append('shop_profile.confirmed_facts')
    action = shop.get('viewer_action_spec') or {}
    visit = isinstance(action, dict) and action.get('mode') == 'visit' and bool(action.get('location'))
    message = (isinstance(action, dict) and action.get('mode') == 'message'
               and action.get('channel') in ('dm', 'pm', 'whatsapp') and bool(action.get('keyword')))
    if not (shop.get('viewer_action') or '').strip() and not (visit or message):
        missing.append('shop_profile.viewer_action')
    return missing


def repeated_dialogue_lines(lines):
    prior = ''
    repeated = []
    for index, line in enumerate(lines, 1):
        head = line.lower().strip()
        tail = re.sub(r'[^\w]+$', '', prior)
        english = re.search(r'[a-z0-9]+$', tail)
        han = re.search(r'[\u3400-\u9fff]{2,6}$', tail)
        if (english and re.match(re.escape(english[0]) + r'(?![a-z0-9])', head)
                or han and any(head.startswith(han[0][-size:]) for size in range(2, len(han[0]) + 1))):
            repeated.append(index)
        prior = head
    return repeated if len(repeated) >= 2 else []


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
    roles = segment.get('reference_roles')
    if roles is not None and not isinstance(roles, list):
        raise ValueError('FILM_REFERENCE_ROLES_INVALID')
    boards = segment.get('reference_boards') or {}
    if not isinstance(boards, dict):
        raise ValueError('FILM_REFERENCE_BOARDS_INVALID')
    photos = {field: value for field, value in (
        ('product_photo_asset_id', segment.get('product_photo_asset_id')),
        ('product_sheet_asset_id', segment.get('product_sheet_asset_id')),
        ('reference_boards.product', boards.get('product')),
    ) if value is not None}
    product_board = next(iter(photos.values()), None) if (roles and 'product' in roles
                    or segment.get('customer_product') or any('.' not in field for field in photos)) else None
    if product_board is not None:
        if any(value != product_board for value in photos.values()):
            raise ValueError('FILM_PRODUCT_PHOTO_CONFLICT: ' + ', '.join(photos))
        if (not isinstance(product_board, str) or not ASSET.fullmatch(product_board)
                or product_board not in authorized_assets):
            raise ValueError('FILM_PRODUCT_PHOTO_NOT_AUTHORIZED: ' + next(iter(photos)))
        if product_board in (first, board):
            raise ValueError('FILM_PRODUCT_PHOTO_MUST_BE_DISTINCT')
    if (segment.get('customer_product') or (roles and 'product' in roles)) and not product_board:
        raise ValueError('FILM_PRODUCT_PHOTO_REQUIRED')
    if roles is not None:
        if roles not in (['first_frame', 'customer', 'staff'], ['first_frame', 'customer', 'product'],
                          ['first_frame', 'staff', 'product'], ['first_frame', 'cast', 'product'],
                          ['first_frame', 'customer', 'subject'], ['first_frame', 'staff', 'subject'],
                          ['first_frame', 'cast', 'subject']):
            raise ValueError('FILM_REFERENCE_ROLES_INVALID')
        if 'product' in roles:
            boards = {**boards, 'product': product_board}
        missing = [role for role in roles[1:] if not boards.get(role)]
        if missing:
            raise ValueError('FILM_REFERENCE_BOARD_REQUIRED: ' + ', '.join(missing))
        refs = [boards[role] for role in roles[1:]]
        if any(not isinstance(ref, str) or not ASSET.fullmatch(ref) for ref in refs) or len(set([first, *refs])) != 3:
            raise ValueError('FILM_REFERENCE_BOARDS_MUST_BE_DISTINCT')
        prompt += ('\nKeep the first frame and reference identities consistent. '
                   'Keep existing product packaging print; do not add scene text.')
        if len(prompt.encode('utf-8')) > 3500:
            raise ValueError('FILM_PROMPT_TOO_LONG')
    if product_board is not None and (roles is None or 'product_sheet_asset_id' in photos):
        prompt += (
            ' Preserve the product shape, color, logo and existing packaging print from the reference. '
            'Do not add unrelated text or invent a usage action.'
        )
        length = len(prompt.encode('utf-8'))
        if length > 3500:
            raise ValueError(f'FILM_PROMPT_TOO_LONG: {length}/3500 UTF-8 bytes')
    extras = [asset for asset in (board, product_board) if asset]
    refs = list(dict.fromkeys([first, *refs, *extras] if roles is not None else [first, *extras, *refs]))
    if len(refs) > 3:
        raise ValueError('FILM_REFERENCE_LIMIT_EXCEEDED: first frame and each sheet count toward the three-image limit')
    if any(ref not in authorized_assets for ref in refs):
        raise ValueError('FILM_REFERENCE_NOT_AUTHORIZED')
    location = segment.get('shop_location')
    if location and not set(refs).intersection(shop_assets.get(location, [])):
        raise ValueError('FILM_SHOP_REFERENCE_REQUIRED')
    result = {'prompt': prompt, 'duration_seconds': seconds, 'reference_asset_ids': refs,
            'visual_subject': segment.get('visual_subject') or ('customer_identity' if location or product_board or segment.get('customer_identity') else 'generic'),
            'film_profile': 'store_v2', 'ratio': '9:16'}
    if roles is not None:
        if len(refs) != 3:
            raise ValueError('FILM_REFERENCE_ROLES_INVALID')
        result['reference_roles'] = roles
    if location:
        result['shop_location'] = location
    return result



def check_dialogue_capacity(segment, index, language=None, duration=None, revision=None, *, require_fill=True):
    """Check the spoken script against the requested or quoted video duration."""
    lines = segment.get('dialogue') or []
    seconds = segment.get('duration_seconds') if duration is None else duration
    if not lines or type(seconds) is not int or not all(
        isinstance(line, dict) and isinstance(line.get('text'), str) for line in lines
    ):
        return
    spoken = ' '.join(line['text'] for line in lines)
    cjk = len(re.findall(r'[\u3400-\u9fff]', spoken))
    english = len(re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*", spoken))
    if language and language.split('-')[0].lower() not in ('zh', 'en') and not cjk:
        return
    switches = sum(first.get('speaker') != second.get('speaker') for first, second in zip(lines, lines[1:]))
    required = cjk / 4.6 + english / 2.8 + switches * 0.25 + 0.4
    if revision == '65':
        minimum, maximum = seconds * 0.8 if require_fill else 0, seconds * (14 / 15)
        if not minimum <= required <= maximum:
            raise ValueError(f'FILM_DIALOGUE_CAPACITY: segment {index}, needs {required:.2f}s, '
                             f'target {minimum:.2f}–{maximum:.2f}s of quoted {seconds}s')
    elif required > seconds + 1e-9:
        raise ValueError(f'FILM_DIALOGUE_OVER_CAPACITY: segment {index}, needs {required:.2f}s, available {seconds}s')


def validate_day_plan(plan):
    from datetime import date

    if not isinstance(plan, dict) or plan.get('schema_version') not in (1, 2, 3):
        raise ValueError('DAY_PLAN_SCHEMA_UNSUPPORTED')
    day = plan.get('date')
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or type(plan.get('rules_version')) is not int:
        raise ValueError('DAY_PLAN_DATE_OR_RULES_INVALID')
    for field in (('featured_service', 'opening', 'visual_batch') if plan.get('script_rules_revision') in ('59', '60', '64', '65')
                  else ('shop_name', 'featured_service', 'opening', 'visual_batch')):
        if not isinstance(plan.get(field), str) or not plan[field].strip():
            raise ValueError(f'DAY_PLAN_REQUIRED: {field}')
    segments = plan.get('segments')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 12 or any(not isinstance(s, dict) for s in segments):
        raise ValueError('DAY_PLAN_SEGMENTS_INVALID')
    if plan['schema_version'] != 3:
        validate_beats(segments, plan.get('film_type'))
    from store_editorial import validate_script
    validate_script(plan)
    story = plan.get('script_rules_revision') == '65' and plan.get('story_narrative') is True
    if story and 'story_plan' in plan:
        from story_plan import check_story_segments, validate_story_plan
        validate_story_plan(plan['story_plan'], plan.get('closing_overlay', []))
        check_story_segments(plan['story_plan'], segments)
    for segment in segments:
        lines = segment.get('subs')
        if (not isinstance(lines, list) or (not story and not lines)
                or any(not isinstance(line, str) or not line.strip() for line in lines)):
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
    if plan['schema_version'] == 3:
        if plan.get('film_type') == 'explainer':
            if plan.get('dialogue_rules_revision') != '2.4':
                raise ValueError('DAY_PLAN_SCHEMA_UNSUPPORTED')
            validate_explainer_durations(durations, minimum=30 if plan.get('story_narrative') is True else 45)
            return plan
        expected = [15, 15] if plan['film_purpose'] == 'service' or plan.get('dialogue_rules_revision') == '2.4' else [15]
        if plan.get('script_rules_revision') == '65' and (len(durations) == 1 or durations == [15, 15]):
            return plan
        if durations != expected:
            raise ValueError('FILM_DIALOGUE_SEGMENTS_INVALID')
        return plan
    if plan['schema_version'] == 2:
        if (len(segments) not in (1, 2) or not plan.get('script')
                or (len(segments) == 2 and durations != [15, 15])):
            raise ValueError('FILM_DIALOGUE_SEGMENTS_INVALID')
        return plan
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


def validate_explainer_durations(durations, minimum=45):
    if (len(durations) not in (3, 4)
            or any(type(value) is not int or not 10 <= value <= 15 for value in durations)
            or not minimum <= sum(durations) <= 60):
        raise ValueError(f'FILM_EXPLAINER_DURATION_INVALID: 3–4 segments, 10–15 seconds each, {minimum}–60 source seconds')
