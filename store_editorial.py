"""Deterministic validation for store plans and publication copy."""
from datetime import date
from itertools import combinations
import re
import unicodedata
from difflib import SequenceMatcher

FORMATS = ('customer_thoughts', 'story', 'themed_story', 'shop_visit', 'behind_the_scenes',
           'before_after', 'qa', 'product_closeup', 'promotion', 'day_in_life')
FILM_V3_FORMATS = ('shop_visit', 'behind_the_scenes', 'before_after', 'product_intro', 'problem_solution', 'story', 'qa')
COPY_FIELDS = ('audience_or_pain', 'solution', 'verified_fact', 'next_step')
DEFAULT_DENY = ('虚构', 'AI 生成', 'fictional', 'not a real', 'a story about')
XHS_DENY = ('主页', '私信', '联系', '预约方式', '链接', '电话', 'whatsapp', '微信')
ACTIONS = ('预约', '到店', '留言', '评论', '问我', '私信', '咨询', 'book', 'visit', 'comment', 'reserve')


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def validate_rotation(rows, history, profile, schema_version=1):
    v3 = schema_version == 3
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
        if (day - start).days != index or row['format'] not in (FILM_V3_FORMATS if v3 else FORMATS):
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
            if not 0 < age < (14 if v3 else 56):
                continue
            same = tuple(field for field in ('row', 'col', 'format') if row[field] == old[field])
            if age == 1 and ('format' in same or (not v3 and same)):
                raise ValueError(f'PLAN_CONSECUTIVE_REPEAT: {row["date"]} {", ".join(same)}')
            same_cell = 'row' in same and 'col' in same
            if (same_cell and ((not v3 and age < 28) or 'format' in same)
                    or (v3 and row.get('visual_batch') and row['visual_batch'] == old.get('visual_batch'))
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

SCRIPT_TEMPLATES = {
    'customer_thoughts': ('pain', 'process', 'change', 'service'),
    'real_question': ('question', 'process', 'fact', 'service'),
    'process_only': ('action', 'detail', 'result', 'service'),
}
VOICE_FLAT = re.compile(r'语速平稳|声音温和|平静|monotone|steady pace|gentle voice', re.I)
REPORT_WORDS = ('了解', '安排', '问清楚', '记下', '项目', '预约问题')


def validate_dialogue_v3(plan):
    script = plan.get('script')
    customer = plan.get('customer_identity')
    overlay = plan.get('closing_overlay')
    purpose = plan.get('film_purpose')
    expected_overlay = plan['shop_name'] if purpose == 'service' else plan['featured_service']
    if (purpose not in ('product', 'service') or not isinstance(script, dict)
            or script.get('template') != 'two_person_dialogue'
            or not isinstance(script.get('voice_identity'), str) or not script['voice_identity'].strip()
            or not isinstance(customer, str) or not customer.strip() or len(customer.encode('utf-8')) > 120
            or not isinstance(overlay, list) or not 1 <= len(overlay) <= 2
            or not all(isinstance(line, str) and line.strip() and len(line.encode('utf-8')) <= 120 for line in overlay)
            or overlay[0] != expected_overlay):
        raise ValueError('FILM_DIALOGUE_PROFILE_INVALID')
    revision21 = plan.get('dialogue_rules_revision') == '2.1'
    if revision21:
        dialogue_v21_lines(plan)
    for index, segment in enumerate(plan['segments'], 1):
        dialogue = segment.get('dialogue')
        if (not isinstance(dialogue, list) or len(dialogue) not in (3, 4)
                or re.search(r'旁白|画外音|不对口型|narration|voice[ -]?over|对着镜头|^\s*\d+(?:[.,]\d+)?\s*[-–—~～至到]\s*\d+(?:[.,]\d+)?\s*(?:s\b|秒)', str(segment.get('prompt', '')), re.I | re.M)):
            raise ValueError(f'FILM_DIALOGUE_LINES_INVALID: {index}')
        speakers = set()
        spoken = []
        for line in dialogue:
            if not isinstance(line, dict) or line.get('speaker') not in ('staff', 'customer'):
                raise ValueError(f'FILM_DIALOGUE_SPEAKER_INVALID: {index}')
            speaker = line['speaker']
            speakers.add(speaker)
            if (line.get('listener') != ('customer' if speaker == 'staff' else 'staff')
                    or not all(isinstance(line.get(field), str) and line[field].strip()
                               and len(line[field].encode('utf-8')) <= 240 for field in ('action', 'emotion', 'text'))
                    or re.search(r'网上搜|去.{0,10}平台搜', line['text'])):
                raise ValueError(f'FILM_DIALOGUE_LINE_INVALID: {index}')
            spoken.append(line['text'])
        actual = ''.join(char for char in ''.join(spoken) if unicodedata.category(char)[0] in 'LN')
        length = len(actual)
        if len(speakers) != 2 or not 60 <= length <= 70:
            raise ValueError(f'FILM_DIALOGUE_WORD_COUNT: segment {index}, got {length}; expected 60–70 with both speakers')
        captions = segment.get('subs')
        if not isinstance(captions, list) or not all(isinstance(item, str) for item in captions):
            raise ValueError(f'FILM_DIALOGUE_CAPTIONS_MISMATCH: {index}')
        if actual != ''.join(char for char in ''.join(captions) if unicodedata.category(char)[0] in 'LN'):
            raise ValueError(f'FILM_DIALOGUE_CAPTIONS_MISMATCH: {index}')


def dialogue_v21_lines(plan, previous_lines=()):
    used = set(previous_lines)
    lines = []
    for index, segment in enumerate(plan['segments'], 1):
        previous = None
        answered = False
        for line in segment.get('dialogue', ()):
            kind = line.get('kind') if isinstance(line, dict) else None
            text = line.get('text') if isinstance(line, dict) else None
            if (kind not in ('question', 'answer', 'statement') or not isinstance(text, str)
                    or (kind == 'question' and not text.strip().endswith(('?', '？')))):
                raise ValueError(f'FILM_DIALOGUE_TURN_INVALID: {index}')
            normalized_line = ''.join(char for char in text if unicodedata.category(char)[0] in 'LN')
            if normalized_line in used:
                raise ValueError(f'FILM_DIALOGUE_LINE_REPEATED: {index}')
            used.add(normalized_line)
            lines.append(normalized_line)
            if (kind == 'answer' and previous is not None and previous['kind'] == 'question'
                    and previous.get('speaker') != line.get('speaker')):
                answered = True
            previous = line
        if not answered:
            raise ValueError(f'FILM_DIALOGUE_QUESTION_ANSWER_REQUIRED: {index}')
    return lines


def validate_script(plan):
    if plan.get('schema_version') == 3:
        return validate_dialogue_v3(plan)
    """Validate a structured script before its plan can reach a quote."""
    script = plan.get('script')
    if script is None:
        return
    if (not isinstance(script, dict) or not isinstance(script.get('template'), str)
            or script['template'] not in SCRIPT_TEMPLATES):
        raise ValueError('SCRIPT_TEMPLATE_REQUIRED')
    beats = SCRIPT_TEMPLATES[script['template']]
    identity = script.get('voice_identity')
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError('VOICE_IDENTITY_REQUIRED')
    if VOICE_FLAT.search(identity):
        raise ValueError('VOICE_FLAT_DIRECTION')
    used = []
    patterns = {}
    segments = plan['segments']
    for index, segment in enumerate(segments):
        lines = segment.get('dialogue')
        if (not isinstance(lines, list) or len(lines) < 2
                or (len(segments) > 4 and segment.get('duration_seconds', 0) <= 6)):
            raise ValueError(f'FILM_ONE_LINE_PER_CLIP: {index + 1}')
        if plan.get('schema_version') == 2:
            prompt = str(segment.get('prompt', ''))
            if re.search(r'旁白|画外音|不对口型|narration|voice[ -]?over|talking to camera|对着镜头', prompt, re.I):
                raise ValueError('VOICE_NARRATION_NOT_DIALOGUE')
            if re.search(r'从\s*\d+(?:\.\d+)?\s*秒\s*(?:开始)?\s*(?:说|念|持续)|持续到\s*\d+\s*秒', prompt):
                raise ValueError('VOICE_FORCED_TIMING')
            if len(lines) > 4:
                raise ValueError('DIALOGUE_LINE_LIMIT')
        if VOICE_FLAT.search(str(segment.get('prompt', ''))):
            raise ValueError(f'VOICE_FLAT_DIRECTION: {index + 1}')
        emotion = segment.get('voice_emotion')
        if not isinstance(emotion, str) or not emotion.strip() or VOICE_FLAT.search(emotion):
            raise ValueError(f'VOICE_FLAT_DIRECTION: {index + 1}')
        for line in lines:
            if not isinstance(line, dict) or line.get('beat') not in beats:
                raise ValueError(f'SCRIPT_BEAT_INVALID: {index + 1}')
            if plan.get('schema_version') == 2 and not all(
                    isinstance(line.get(field), str) and line[field].strip()
                    for field in ('speaker', 'listener', 'emotion')):
                raise ValueError('DIALOGUE_SPEAKER_MISSING')
            content = line.get('text')
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f'SCRIPT_LINE_REQUIRED: {index + 1}')
            used.append((line['beat'], content.strip()))
            opening = re.sub(r'[\W_]+', '', normalized(content))
            pattern = '我先…再' if re.match(r'我先.+再', opening) else opening[:4]
            if pattern:
                patterns[pattern] = patterns.get(pattern, 0) + 1
                if patterns[pattern] >= 3:
                    raise ValueError('SCRIPT_REPEATED_PATTERN')
    if tuple(dict.fromkeys(beat for beat, _ in used)) != beats:
        raise ValueError('SCRIPT_BEATS_INCOMPLETE')
    if used and sum(any(term in content for term in REPORT_WORDS) for _, content in used) > len(used) / 2:
        raise ValueError('SCRIPT_REPORT_TONE')

def scripted_segment(segment, script, shop):
    if script is None:
        return segment
    identity = shop.get('voice_identity')
    if not isinstance(identity, str) or identity != script['voice_identity']:
        raise ValueError('VOICE_IDENTITY_PROFILE_MISMATCH')
    if all('speaker' in line for line in segment['dialogue']):
        dialogue = '\n'.join(f'{line["speaker"]}（{line.get("action", "")} {line["emotion"]}）对{line["listener"]}说：「{line["text"].strip()}」'
                             for line in segment['dialogue'])
        return {**segment, 'prompt': segment['prompt'].rstrip()
                + f'\nIn-scene dialogue:\n{dialogue}\nVoice identity: {identity}'}
    dialogue = ' '.join(line['text'].strip() for line in segment['dialogue'])
    return {**segment, 'prompt': segment['prompt'].rstrip()
            + f'\nUse only this approved dialogue: 「{dialogue}」'
            + f'\nVoice identity: {identity}\nVoice performance: {segment["voice_emotion"]}'}
