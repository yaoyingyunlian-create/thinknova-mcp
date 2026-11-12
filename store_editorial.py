"""Deterministic validation for store plans and publication copy."""
from datetime import date
from itertools import combinations
import re
import unicodedata
from difflib import SequenceMatcher

FORMATS = ('customer_thoughts', 'story', 'themed_story', 'shop_visit', 'behind_the_scenes',
           'before_after', 'qa', 'product_closeup', 'promotion', 'day_in_life')
COPY_FIELDS = ('audience_or_pain', 'solution', 'verified_fact', 'next_step')
DEFAULT_DENY = ('虚构', 'AI 生成', 'fictional', 'not a real', 'a story about')
XHS_DENY = ('主页', '私信', '联系', '预约方式', '链接', '电话', 'whatsapp', '微信')
ACTIONS = ('预约', '到店', '留言', '评论', '问我', 'book', 'visit', 'comment', 'reserve')


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def validate_rotation(rows, history, profile):
    for field in ('audiences', 'scenes', 'pain_points', 'features', 'questions'):
        values = profile.get(field)
        if not isinstance(values, list) or len(values) < 3:
            raise ValueError(f'SHOP_LIST_INCOMPLETE: {field}')
    questions = sorted(profile['questions'], key=lambda item: -item['count'])
    hot = {item['id'] for item in questions[:3]}
    if len(rows) != 7 or len({row['format'] for row in rows}) < 4:
        raise ValueError('WEEK_REQUIRES_SEVEN_DAYS_AND_FOUR_FORMATS')
    if len({row.get('question') for row in rows} & hot) < 2:
        raise ValueError('WEEK_REQUIRES_TWO_POPULAR_QUESTIONS')
    if len({row['row'] for row in rows}) != 3 or len({row['col'] for row in rows}) != 3:
        raise ValueError('WEEK_REQUIRES_THREE_ROWS_AND_COLUMNS')
    allowed_rows = set(profile['audiences']) | set(profile['pain_points']) | {item['id'] for item in questions}
    seen = sorted(history, key=lambda old: old['date'])
    start = date.fromisoformat(rows[0]['date'])
    for index, row in enumerate(rows):
        day = date.fromisoformat(row['date'])
        if (day - start).days != index or row['format'] not in FORMATS:
            raise ValueError(f'PLAN_DATE_OR_FORMAT_INVALID: {row["date"]}')
        if row['row'] not in allowed_rows or row['col'] not in profile['features'] or row['scene'] not in profile['scenes']:
            raise ValueError(f'PLAN_TOPIC_NOT_IN_PROFILE: {row["date"]}')
        if not normalized(row['opening']) or not row['opening_visual'].strip():
            raise ValueError(f'PLAN_OPENING_REQUIRED: {row["date"]}')
        if row['format'] == 'promotion' or row.get('price') is not None:
            activity = profile.get('activity') or {}
            if not activity or not date.fromisoformat(activity['start']) <= day <= date.fromisoformat(activity['end']):
                raise ValueError(f'PLAN_ACTIVITY_INACTIVE: {row["date"]}')
        for old in seen:
            age = (day - date.fromisoformat(old['date'])).days
            if not 0 < age < 56:
                continue
            same = tuple(field for field in ('row', 'col', 'format') if row[field] == old[field])
            if age == 1 and same:
                raise ValueError(f'PLAN_CONSECUTIVE_REPEAT: {row["date"]} {", ".join(same)}')
            same_cell = 'row' in same and 'col' in same
            if (same_cell and (age < 28 or 'format' in same)
                    or normalized(row['opening']) == normalized(old['opening'])
                    or row['opening_visual'] == old['opening_visual']):
                raise ValueError(f'PLAN_HISTORY_REPEAT: {row["date"]}')
        seen.append(row)
    return rows


def prepare_copy(platform, variant, policy=None):
    policy = policy or {}
    title = variant.get('title')
    if not isinstance(title, str) or not title.strip() or re.search(r'[|｜]', title):
        raise ValueError(f'COPY_TITLE_INVALID: {platform}')
    fields = variant.get('marketing_copy')
    if not isinstance(fields, dict):
        raise ValueError(f'COPY_FIELDS_REQUIRED: {platform}')
    for field in COPY_FIELDS:
        text = fields.get(field)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f'COPY_FIELD_REQUIRED: {platform}.{field}')
    action = normalized(fields['next_step'])
    if not any((re.search(r'\b' + word + r'\b', action) if word.isascii() else word in action) for word in ACTIONS):
        raise ValueError(f'COPY_ACTION_REQUIRED: {platform}.next_step')
    deny = [*DEFAULT_DENY, *policy.get('forbidden_terms', [])]
    if platform == 'xiaohongshu':
        deny.extend(XHS_DENY)
    for field, text in [('title', title), *((key, fields[key]) for key in COPY_FIELDS)]:
        for word in deny:
            if normalized(word) and normalized(word) in normalized(text):
                raise ValueError(f'COPY_FORBIDDEN_TERM: {platform}.{field} ({word})')
    tags = variant.get('tags', [])
    bounds = {'xiaohongshu': (2, 2), 'instagram': (5, 8), 'tiktok': (3, 5)}
    if platform in bounds and not bounds[platform][0] <= len(tags) <= bounds[platform][1]:
        raise ValueError(f'COPY_TAG_COUNT: {platform}')
    separator = ' ' if platform in ('x', 'tiktok') else '\n'
    return separator.join(fields[key].strip() for key in COPY_FIELDS)


def validate_plan_copy(plan, policies=None, targets=()):
    policies = policies or {}
    variants = plan.get('platforms') or {}
    if not isinstance(variants, dict):
        raise ValueError('COPY_PLATFORMS_INVALID')
    date_label = plan.get('date', 'week')
    opening = plan.get('opening')
    if opening is not None:
        for platform in sorted(set(variants) | set(targets)) or ['general']:
            deny = [*DEFAULT_DENY, *policies.get(platform, {}).get('forbidden_terms', [])]
            if platform == 'xiaohongshu':
                deny.extend(XHS_DENY)
            if any(normalized(term) and normalized(term) in normalized(opening) for term in deny):
                raise ValueError(f'COPY_FORBIDDEN_TERM: {date_label} {platform}.opening')
    if variants:
        try:
            validate_platform_copy(variants, policies)
        except ValueError as exc:
            raise ValueError(f'{date_label}: {exc}') from exc


def validate_platform_copy(variants, policies=None):
    bodies = {}
    for platform, variant in variants.items():
        bodies[platform] = prepare_copy(platform, variant, (policies or {}).get(platform))
    for left, right in combinations(variants, 2):
        parts = [normalized(' '.join(variants[key]['marketing_copy'][field] for field in COPY_FIELDS[1:]))
                 for key in (left, right)]
        if SequenceMatcher(None, *parts, autojunk=False).ratio() >= 0.85:
            raise ValueError(f'COPY_VARIANTS_TOO_SIMILAR: {left}, {right}')
    return bodies
