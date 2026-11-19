"""Bounded speech recovery; original videos and local transcript evidence are retained."""
import json
from pathlib import Path
import subprocess
import time

from render.speech_review import caption_agreement


def inspect_speech(path, expected, language=None):
    from speech_recovery import recognize
    segments, _ = recognize(path, 'small', language, None, word_timestamps=True, vad_filter=True)
    text = ''.join(segment.text for segment in segments)
    return {'agreement': caption_agreement(expected, text), 'transcript': text}


def recover_clip(client, claim, plan, index, args, path, steps, checkpoint, quote, download, atomic, budget_used, budget_limit=None):
    if (plan.get('quality_policy') or {}).get('version') != '58':
        return path, {}
    expected = ''.join(plan['segments'][index].get('subs') or [])
    evidence = Path(path).with_suffix('.speech-attempts.json')
    record = json.loads(evidence.read_text(encoding='utf-8')) if evidence.exists() else {'expected': expected, 'attempts': []}
    if record.get('selected'):
        selected = Path(path).parent / record['selected']
        if selected.is_file():
            return selected, record
    try:
        # Verify the mismatch twice locally, not with a second paid generation.
        while len(record['attempts']) < 2:
            assessment = inspect_speech(path, expected, plan.get('speech_language'))
            record['attempts'].append(assessment)
            atomic(evidence, record)
            if assessment['agreement'] >= 0.3:
                return path, record
    except (RuntimeError, ImportError):
        record.update(speech_status='unknown', warning='SPEECH_CHECK_PENDING')
        atomic(evidence, record)
        return path, record
    repaired_path = Path(path).with_name(Path(path).stem + '-recovery.mp4')
    task_key, price_key = f'recovery_task_{index}', f'recovery_cost_{index}'
    if task_key not in steps:
        argument_file = Path(path).with_suffix('.recovery-request.json')
        if argument_file.exists():
            # The prior request may already be charged. Recover its exact intent first.
            changed = json.loads(argument_file.read_text(encoding='utf-8'))
        else:
            changed = dict(args)
            changed.update(client_request_id=args['client_request_id'] + ':retry:1')
            language = args.get('dialogue_language') or plan.get('speech_language')
            changed['prompt'] += ('\nRecovery delivery: preserve the approved dialogue language and verified meaning. '
                                  'Speak clearly and conversationally; use supplied pronunciation directions. '
                                  'Do not translate the dialogue or invent facts, new claims, subtitles or music.')
            if language == 'zh':
                changed['prompt'] += (' Read numbers and English abbreviations as natural spoken Chinese; '
                                      'use the supplied Chinese name pronunciation, without speaking pinyin.')
            changed = quote(client, 'animate_image', changed, client.tool('get_balance'))
            limit = min(int(claim['grant']['daily_budget']), budget_limit) if budget_limit is not None else int(claim['grant']['daily_budget'])
            if budget_used + changed['max_credits'] > limit:
                record['warning'] = 'RECOVERY_BUDGET_INSUFFICIENT'
                record['recovery_status'] = 'skipped_budget'
                changed = None
            else:
                atomic(argument_file, changed)
        if changed is not None:
            created = client.tool('animate_image', changed)
            steps[task_key] = created['task_id']
            steps[price_key] = str(changed['max_credits'])
            checkpoint()
    if task_key in steps:
        deadline = time.monotonic() + 900
        while True:
            task = client.tool('get_task', {'task_id': steps[task_key]})
            if task['status'] in ('succeeded', 'failed', 'canceled', 'cancelled'):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('RECOVERY_TASK_PENDING')
            checkpoint()
            time.sleep(5)
        if task['status'] == 'succeeded':
            if not repaired_path.exists():
                result = client.tool('get_result', {'task_id': steps[task_key]})
                asset = next(item for item in result['assets'] if item['type'] == 'video')
                download(asset['download_url'], repaired_path, task_id=steps[task_key])
            try:
                assessment = inspect_speech(repaired_path, expected, plan.get('speech_language'))
                record['attempts'].append(assessment)
                if assessment['agreement'] >= 0.3:
                    record['selected'] = repaired_path.name
                    atomic(evidence, record)
                    return repaired_path, record
            except (RuntimeError, ImportError):
                record.update(selected=repaired_path.name, speech_status='unknown', warning='SPEECH_CHECK_PENDING')
                atomic(evidence, record)
                return repaired_path, record
    # A local silent shot + the approved captions is the final per-shot fallback.
    # The complete film still has to pass its non-silent audio and mismatch checks.
    muted = Path(path).with_name(Path(path).stem + '-caption-only.mp4')
    if not muted.exists():
        command = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(path), '-f', 'lavfi', '-i',
                   'anullsrc=r=48000:cl=stereo', '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-shortest', str(muted)]
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    record.update(selected=muted.name, warning='CAPTION_ONLY_SHOT', speech_status='degraded')
    atomic(evidence, record)
    return muted, record
