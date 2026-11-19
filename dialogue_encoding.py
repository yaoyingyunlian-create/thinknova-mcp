"""Strict text checks before quote/create. Never guess a repair for damaged source text."""
import json
import re
from pathlib import Path


def validate_text(prompt, language=None):
    if not isinstance(prompt, str):
        raise ValueError('DIALOGUE_ENCODING_INVALID')
    try:
        prompt.encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise ValueError('DIALOGUE_ENCODING_INVALID') from exc
    if '\ufffd' in prompt:
        raise ValueError('DIALOGUE_ENCODING_INVALID')
    match = re.search(r'(?:Exact Mandarin dialogue|中文台词|普通话对白)\s*[:：]\s*(.+)', prompt, re.I | re.S)
    if match:
        text = re.split(r'\n\s*\n', match[1])[0]
        if not re.search(r'[\u3400-\u9fff]', text) and any(ord(char) > 127 for char in text):
            raise ValueError('DIALOGUE_ENCODING_INVALID')
    if language == 'zh':
        for text in re.findall(r'[「“]([^」”]+)[」”]', prompt):
            if not re.search(r'[\u3400-\u9fff]', text) and any(ord(char) > 127 for char in text):
                raise ValueError('DIALOGUE_ENCODING_INVALID')
    return prompt


def read_json(path):
    """One strict reread from the original file; no GBK guessing or replacement decoding."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode('utf-8-sig', errors='strict')
        validate_text(text)
        return json.loads(text)
    except (UnicodeError, ValueError) as exc:
        raise ValueError('DAY_PLAN_UTF8_SOURCE_INVALID') from exc
