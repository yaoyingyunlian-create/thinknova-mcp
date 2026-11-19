"""Reuse only scoped, checked and locally unattempted films; reserve before delivery."""
import hashlib
import json
from pathlib import Path
from local_state import state_lock


def reserve(root, project, day, platforms, run_no, rules_version=None):
    root = Path(root)
    ledger_path = root / 'inventory-reservations.json'
    with state_lock(root / 'inventory'):
        ledger = json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {}
        for file in sorted((root / 'runs').glob('*/review-ready.json'), reverse=True):
            try:
                item = json.loads(file.read_text(encoding='utf-8'))
                if item.get('project_key') != project or not item.get('source_date') or item['source_date'] >= day:
                    continue
                if rules_version is not None and item.get('rules_version') != rules_version:
                    continue
                if item.get('activity_content') and (not item.get('valid_until') or item['valid_until'] < day):
                    continue
                if item.get('delivery_source') == 'inventory':
                    continue
                folder = file.parent
                if any(folder.glob('*.receipt.json')):
                    continue  # Includes ambiguous submission receipts; never assume not published.
                state_file = folder / 'state.json'
                state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
                if state.get('publication_started') or state.get('publication_id'):
                    continue
                video = Path(item['output'])
                if not video.resolve().is_relative_to(folder.resolve()) or not video.is_file():
                    continue
                proof = json.loads(Path(str(video) + '.film.json').read_text(encoding='utf-8'))
                with video.open('rb') as stream:
                    digest = hashlib.sha256(stream.read()).hexdigest()
                if proof.get('machine_check') != 'pass' or proof.get('sha256') != digest:
                    continue
                job_path = Path(item['publish_job'])
                if not job_path.resolve().is_relative_to(folder.resolve()):
                    continue
                job = json.loads(job_path.read_text(encoding='utf-8'))
                variants = job.get('platforms', {})
                if set(variants) != set(platforms) or any(
                    variants[name].get('expected_channel_id', variants[name].get('target_account'))
                    != value.get('expected_channel_id', value.get('target_account')) for name, value in platforms.items()):
                    continue
                if not all(value.get('expected_channel_id') or value.get('target_account') for value in variants.values()):
                    continue
                key = project + ':' + digest
                if key in ledger and ledger[key]['run_no'] != run_no:
                    continue
                ledger[key] = {'run_no': run_no, 'date': day, 'status': 'reserved', 'platforms': list(platforms)}
                temporary = ledger_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(ledger,ensure_ascii=False),encoding='utf-8')
                temporary.replace(ledger_path)
                return {'review':item,'video':str(video),'platforms':variants,'source_run_no':folder.name}
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return None


def copy_artifacts(source, output):
    import shutil
    original, output = Path(source), Path(output)
    for source_path, target in [(original,output), (Path(str(original)+'.film.json'),Path(str(output)+'.film.json')),
                                (original.with_suffix('.srt'),output.with_suffix('.srt')),
                                (original.with_name(original.stem+'_sheet.jpg'),output.with_name(output.stem+'_sheet.jpg')),
                                (Path(str(original)+'.check.txt'),Path(str(output)+'.check.txt'))]:
        if source_path.is_file():
            if target.exists():
                if target.read_bytes() != source_path.read_bytes(): raise RuntimeError('INVENTORY_OUTPUT_EXISTS')
                continue
            temporary = target.with_name(target.name + '.inventory-part')
            shutil.copyfile(source_path, temporary)
            temporary.replace(target)
