"""Deterministic validation for store plans and publication copy."""
from datetime import date
from itertools import combinations
import re
import unicodedata
from difflib import SequenceMatcher

FORMATS = ('customer_thoughts', 'story', 'themed_story', 'shop_visit', 'behind_the_scenes',
           'before_after', 'qa', 'product_closeup', 'promotion', 'day_in_life')
FILM_V3_FORMATS = ('shop_visit', 'behind_the_scenes', 'before_after', 'product_intro', 'problem_solution', 'story', 'qa')
FILM_V52_FORMATS = tuple(name for name in FILM_V3_FORMATS if name != 'story') + ('explainer',)
COPY_FIELDS = ('audience_or_pain', 'solution', 'verified_fact', 'next_step')
DEFAULT_DENY = ('虚构', 'AI 生成', 'fictional', 'not a real', 'a story about')
XHS_DENY = ('主页', '私信', '联系', '预约方式', '链接', '电话', 'whatsapp', '微信')
ACTIONS = ('预约', '到店', '留言', '评论', '问我', '私信', '咨询', 'book', 'visit', 'comment', 'reserve')


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def validate_rotation(rows, history, profile, schema_version=1, script_rules_revision=None, warnings=None, *, story_narrative=False):
    warnings = warnings if warnings is not None else []
    def repeat(message):
        if script_rules_revision in ('59', '60', '64', '65'):
            warnings.append(message)
        else:
            raise ValueError(message)
    v3 = schema_version == 3
    minimal = script_rules_revision in ('54', '59', '60', '64', '65')
    formats = FILM_V52_FORMATS if script_rules_revision in ('52', '54', '59', '60', '64', '65') else FILM_V3_FORMATS if v3 else FORMATS
    for field in ('audiences', 'scenes', 'pain_points', 'features', 'questions'):
        values = profile.get(field)
        if not isinstance(values, list) or (not minimal and len(values) < 3):
            raise ValueError(f'SHOP_LIST_INCOMPLETE: {field}')
    questions = sorted(profile['questions'], key=lambda item: -item['count'])
    hot = {item['id'] for item in questions[:3]}
    if len(rows) != (1 if minimal else 7) or (not minimal and len({row['format'] for row in rows}) < 4):
        raise ValueError('WEEK_REQUIRES_SEVEN_DAYS_AND_FOUR_FORMATS')
    if not minimal and len({row.get('question') for row in rows} & hot) < 2:
        raise ValueError('WEEK_REQUIRES_TWO_POPULAR_QUESTIONS')
    if not minimal and (len({row['row'] for row in rows}) != 3 or len({row['col'] for row in rows}) != 3):
        raise ValueError('WEEK_REQUIRES_THREE_ROWS_AND_COLUMNS')
    allowed_rows = set(profile['audiences']) | set(profile['pain_points']) | {item['id'] for item in questions}
    seen = sorted(history, key=lambda old: old['date'])
    start = date.fromisoformat(rows[0]['date'])
    for index, row in enumerate(rows):
        day = date.fromisoformat(row['date'])
        if (day - start).days != index or row['format'] not in formats:
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
            if not story_narrative and age == 1 and ('format' in same or (not v3 and same)):
                repeat(f'PLAN_CONSECUTIVE_REPEAT: {row["date"]} {", ".join(same)}')
            same_cell = 'row' in same and 'col' in same
            if (not minimal and same_cell and ((not v3 and age < 28) or 'format' in same)
                    or (v3 and row.get('visual_batch') and row['visual_batch'] == old.get('visual_batch'))
                    or normalized(row['opening']) == normalized(old['opening'])
                    or row['opening_visual'] == old['opening_visual']):
                repeat(f'PLAN_HISTORY_REPEAT: {row["date"]}')
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


def validate_story_turns(segments):
    speakers = set()
    exchange = False
    for segment in segments:
        previous = None
        for line in segment.get('dialogue') or []:
            if not isinstance(line, dict) or line.get('speaker') not in ('staff', 'customer'):
                raise ValueError('FILM_DIALOGUE_LINE_INVALID')
            speakers.add(line['speaker'])
            if (previous and previous.get('kind') == 'question' and line.get('kind') == 'answer'
                    and previous.get('speaker') != line.get('speaker')):
                exchange = True
            previous = line
    if not {'staff', 'customer'} <= speakers or not exchange:
        raise ValueError('FILM_STORY_DIALOGUE_REQUIRED: include an in-scene exchange between staff and customer')


def validate_dialogue_v3(plan):
    story = plan.get('script_rules_revision') == '65' and plan.get('story_narrative') is True
    script = plan.get('script')
    customer = plan.get('customer_identity')
    overlay = plan.get('closing_overlay')
    purpose = plan.get('film_purpose')
    expected_overlay = plan['shop_name'] if purpose == 'service' and plan.get('shop_name') else plan['featured_service']
    if (purpose not in ('product', 'service') or not isinstance(script, dict)
            or script.get('template') != 'two_person_dialogue'
            or not isinstance(script.get('voice_identity'), str) or not script['voice_identity'].strip()
            or not isinstance(customer, str) or not customer.strip() or len(customer.encode('utf-8')) > 120
            or not isinstance(overlay, list) or not 1 <= len(overlay) <= 2
            or not all(isinstance(line, str) and line.strip() and len(line.encode('utf-8')) <= 120 for line in overlay)
            or (not story and overlay[0] != expected_overlay)):
        raise ValueError('FILM_DIALOGUE_PROFILE_INVALID')
    revision21 = plan.get('dialogue_rules_revision') in ('2.1', '2.4')
    final_rules = plan.get('script_rules_revision') in ('52', '54', '59', '60', '64', '65')
    if revision21:
        dialogue_v21_lines(plan)
    revision65 = plan.get('script_rules_revision') == '65'
    for index, segment in enumerate(plan['segments'], 1):
        final_cta = revision65 and index == len(plan['segments'])
        may_address_camera = not story and final_rules and plan.get('film_type') == 'explainer' and index > 1
        low, high = (55, 62) if plan.get('dialogue_rules_revision') == '2.4' else (60, 70)
        if plan.get('film_type') == 'explainer':
            seconds = segment.get('duration_seconds')
            if type(seconds) is not int or not 10 <= seconds <= 15:
                raise ValueError('FILM_EXPLAINER_DURATION_INVALID')
            low, high = (low * seconds + 14) // 15, high * seconds // 15
        dialogue = segment.get('dialogue')
        prompt = str(segment.get('prompt', ''))
        if (not isinstance(dialogue, list) or len(dialogue) not in (range(9) if story else {'65': range(4, 9), '64': range(4, 7), '60': range(5, 9)}.get(plan.get('script_rules_revision'), (3, 4)))
                or re.search(r'旁白|画外音|不对口型|narration|voice[ -]?over|^\s*\d+(?:[.,]\d+)?\s*[-–—~～至到]\s*\d+(?:[.,]\d+)?\s*(?:s\b|秒)', prompt, re.I | re.M)
                or (not may_address_camera and not final_cta and re.search(r'对着镜头|talking to camera', prompt, re.I))):
            raise ValueError(f'FILM_DIALOGUE_LINES_INVALID: {index}')
        speakers = set()
        spoken = []
        for position, line in enumerate(dialogue):
            if not isinstance(line, dict) or line.get('speaker') not in ('staff', 'customer'):
                raise ValueError(f'FILM_DIALOGUE_SPEAKER_INVALID: {index}')
            speaker = line['speaker']
            speakers.add(speaker)
            if ((line.get('listener') != ('customer' if speaker == 'staff' else 'staff')
                 and not (line.get('listener') == 'camera' and (may_address_camera or (
                     final_cta and position == len(dialogue) - 1 and speaker == 'staff'
                     and line.get('classification') == '行动指引'))))
                    or not all(isinstance(line.get(field), str) and line[field].strip()
                               and len(line[field].encode('utf-8')) <= 240 for field in ('action', 'emotion', 'text'))
                    or re.search(r'网上搜|去.{0,10}平台搜', line['text'])):
                raise ValueError(f'FILM_DIALOGUE_LINE_INVALID: {index}')
            spoken.append(line['text'])
        actual = ''.join(char for char in ''.join(spoken) if unicodedata.category(char)[0] in 'LN')
        length = len(actual)
        solo = may_address_camera and all(line.get('listener') == 'camera' for line in dialogue)
        if plan.get('script_rules_revision') not in ('59', '60', '64', '65') and (len(speakers) != (1 if solo else 2) or not low <= length <= high):
            raise ValueError(f'FILM_DIALOGUE_WORD_COUNT: segment {index}, got {length}; expected {low}–{high}')
        captions = segment.get('subs')
        if not isinstance(captions, list) or not all(isinstance(item, str) for item in captions):
            raise ValueError(f'FILM_DIALOGUE_CAPTIONS_MISMATCH: {index}')
        if plan.get('script_rules_revision') in ('64', '65') and captions != spoken:
            raise ValueError(f'FILM_DIALOGUE_CAPTIONS_MISMATCH: {index}')
        if actual != ''.join(char for char in ''.join(captions) if unicodedata.category(char)[0] in 'LN'):
            raise ValueError(f'FILM_DIALOGUE_CAPTIONS_MISMATCH: {index}')
        if plan.get('script_rules_revision') in ('60', '64', '65'):
            streak, previous = 0, None
            for line in dialogue:
                size = len(''.join(c for c in line['text'] if unicodedata.category(c)[0] in 'LN'))
                streak = streak + 1 if previous == line['speaker'] else 1
                previous = line['speaker']
                if (size < 3 and not short_reaction(line['text'])) or (not revision65 and size > 12) or streak > 2:
                    code = f'SCRIPT_CONVERSATION_ADVICE_UNMET:{index - 1}'
                    if code not in plan.setdefault('warnings', []): plan['warnings'].append(code)

    if story:
        validate_story_turns(plan['segments'])
        closing = plan['segments'][-1]['dialogue']
        if not closing or overlay != [closing[-1]['text']]:
            raise ValueError('DAY_PLAN_VIEWER_ACTION_INVALID')
    if final_rules:
        validate_script_evidence(plan)


def short_reaction(text):
    return re.fullmatch(r'(?:啊|真的|泡的|哦|嗯|好|是吗|对吗|这样啊|原来如此|哈哈|哇)[？?！!。，,、\s]*', text.strip()) is not None


def validate_script_evidence(plan):
    sources = plan.get('script_sources')
    if not isinstance(sources, dict) or not str(plan.get('category_direction') or '').strip():
        raise ValueError('DAY_PLAN_SCRIPT_LINE_EVIDENCE_REQUIRED')
    week = plan.get('week_rows') or []
    format_name = week[0].get('format') if week else None
    explainer = plan.get('film_type') == 'explainer'
    if (format_name == 'explainer') != explainer:
        raise ValueError('DAY_PLAN_SCRIPT_FORMAT_MISMATCH')
    if plan.get('script_rules_revision') not in ('59', '60', '64', '65') and (not week or (format_name != 'shop_visit'
                    and plan['segments'][0]['dialogue'][0].get('classification') not in ('麻烦', '原话'))):
        raise ValueError('DAY_PLAN_SCRIPT_OPENING_INVALID')
    counts = dict.fromkeys(('麻烦', '好处或原因', '原话', '情境'), 0)
    if plan.get('script_rules_revision') == '65':
        counts.update({'行动指引': 0, '短接话': 0})
    quote_ids = []
    for segment_index, segment in enumerate(plan['segments']):
        used_quotes = set()
        for line_index, line in enumerate(segment['dialogue']):
            category, source = line.get('classification'), line.get('source_ref', '')
            free_line = category in ('情境', '短接话')
            if (not isinstance(category, str) or category not in counts or not isinstance(source, str)
                    or not all(isinstance(line.get(field), str) and line[field].strip()
                               and len(line[field].encode('utf-8')) <= limit
                               for field, limit in (('visual', 480), ('camera', 240)))
                    or (free_line and source)
                    or (not free_line and source not in sources)):
                raise ValueError('DAY_PLAN_SCRIPT_LINE_EVIDENCE_REQUIRED')
            if category == '短接话' and not short_reaction(line['text']):
                raise ValueError('DAY_PLAN_SCRIPT_LINE_EVIDENCE_REQUIRED')
            if category == '行动指引' and (
                segment_index != len(plan['segments']) - 1 or line_index != len(segment['dialogue']) - 1
                or line.get('speaker') != 'staff' or not str(sources[source]).startswith('viewer_action: ')
            ):
                raise ValueError('DAY_PLAN_VIEWER_ACTION_INVALID')
            if category == '原话':
                if not source.startswith('Q') or line['text'] != sources[source]:
                    raise ValueError('DAY_PLAN_CUSTOMER_QUOTE_INVALID')
                used_quotes.add(source)
            elif not free_line and not source.startswith('F') and not (category == '麻烦' and source.startswith('B')):
                raise ValueError('DAY_PLAN_SCRIPT_LINE_EVIDENCE_REQUIRED')
            if not (plan.get('script_rules_revision') in ('60', '64', '65') and category == '情境' and short_reaction(line['text'])):
                counts[category] += 1
        quote_ids.append(used_quotes)
    if plan.get('script_rules_revision') not in ('59', '60', '64', '65') and (counts['情境'] > 2 or counts['好处或原因'] < 2 or (
            any(source.startswith('Q') for source in sources) and counts['原话'] < 1)):
        raise ValueError('DAY_PLAN_SCRIPT_COUNTS_INVALID')
    if plan.get('script_rules_revision') not in ('59', '60', '64', '65') and explainer and (not quote_ids[0] or (plan['film_purpose'] == 'service' and not quote_ids[-1] - quote_ids[0])):
        raise ValueError('DAY_PLAN_EXPLAINER_QUOTES_REQUIRED')
    if plan.get('script_rules_revision') == '65' and counts['行动指引'] != 1:
        raise ValueError('DAY_PLAN_VIEWER_ACTION_INVALID')
    if counts != plan.get('dialogue_classification_counts'):
        raise ValueError('DAY_PLAN_SCRIPT_COUNTS_MISMATCH')
    if plan.get('script_rules_revision') in ('54', '59', '60', '64', '65'):
        angle = plan.get('content_angle') or {}
        if not angle.get('id') or angle.get('source_ref') not in sources:
            raise ValueError('DAY_PLAN_SCRIPT_ANGLE_REQUIRED')
        for segment in plan['segments']:
            if not all(isinstance(segment.get(field), str) and segment[field].strip()
                       for field in ('scene_life', 'first_frame_prompt')):
                raise ValueError('DAY_PLAN_LIVING_SCENE_REQUIRED')


def dialogue_v21_lines(plan, previous_lines=()):
    used = set(previous_lines)
    lines = []
    for index, segment in enumerate(plan['segments'], 1):
        final_rules = plan.get('script_rules_revision') in ('52', '54', '59', '60', '64', '65')
        previous = None
        answered = False
        for line in segment.get('dialogue', ()):
            kind = line.get('kind') if isinstance(line, dict) else None
            text = line.get('text') if isinstance(line, dict) else None
            if (kind not in ('question', 'answer', 'statement') or not isinstance(text, str)
                    or (kind == 'question' and not text.strip().endswith(('?', '？')))):
                raise ValueError(f'FILM_DIALOGUE_TURN_INVALID: {index}')
            normalized_line = ''.join(char for char in text if unicodedata.category(char)[0] in 'LN')
            if normalized_line in used and plan.get('script_rules_revision') not in ('60', '64', '65') and not (final_rules and line.get('classification') == '原话'):
                raise ValueError(f'FILM_DIALOGUE_LINE_REPEATED: {index}')
            used.add(normalized_line)
            lines.append(normalized_line)
            if (kind == 'answer' and previous is not None and previous['kind'] == 'question'
                    and previous.get('speaker') != line.get('speaker')):
                answered = True
            previous = line
        solo = (final_rules and plan.get('film_type') == 'explainer' and index > 1
                and all(line.get('listener') == 'camera' for line in segment.get('dialogue', ())))
        if not answered and not solo and plan.get('script_rules_revision') not in ('59', '60', '64', '65'):
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
                             + (f' Visual: {line["visual"]} Camera: {line["camera"]}' if 'visual' in line else '')
                             for line in segment['dialogue'])
        notes = ''
        if shop.get('name') and shop.get('name_pronunciation') and any(
            shop['name'] in line['text'] for line in segment['dialogue']
        ):
            notes = f"\nPronounce {shop['name']} as {shop['name_pronunciation']}. Do not read pronunciation notes aloud."
        return {**segment, 'prompt': segment['prompt'].rstrip()
                + f'\nIn-scene dialogue:\n{dialogue}\nVoice identity: {identity}' + notes}
    dialogue = ' '.join(line['text'].strip() for line in segment['dialogue'])
    return {**segment, 'prompt': segment['prompt'].rstrip()
            + f'\nUse only this approved dialogue: 「{dialogue}」'
            + f'\nVoice identity: {identity}\nVoice performance: {segment["voice_emotion"]}'}
