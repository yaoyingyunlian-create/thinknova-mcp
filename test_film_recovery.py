import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from film_recovery import caption_repair, pending_events, render_film
from local_state import state_lock


class FilmRecoveryTests(unittest.TestCase):
    def test_captions_keep_existing_dialogue(self):
        job = {'clips': [{'dialogue': [{'text': '这是一个需要拆分的字幕测试'}]}]}
        revised = caption_repair(job)
        self.assertEqual(''.join(revised['clips'][0]['subs']), job['clips'][0]['dialogue'][0]['text'])
        self.assertTrue(all(len(line) <= 6 for line in revised['clips'][0]['subs']))
        self.assertTrue(revised['align_subtitles'])
        self.assertIsNone(caption_repair({'clips': [{'file': 'clip.mp4'}]}))

    def test_preview_recheck_and_offline_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_path = root / 'job.json'
            receipt_dir = root / 'film_pending_test'
            receipt_dir.mkdir()
            receipt = receipt_dir / 'preview.mp4.film.json'
            receipt.touch()
            job = {'film': True, 'clips': []}
            (root / 'manifest.json').write_text('{"version":"test"}', encoding='utf-8')
            failed = {'error': 'CHECK_FAILED', 'pending_receipt': str(receipt),
                      'diagnostics': [{'code': 'FILM_CHECK_TIMEOUT'}]}
            passed = {'machine_check': 'pass', 'film_receipt': 'tested'}
            with patch('film_recovery.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 2, json.dumps(failed)),
                subprocess.CompletedProcess([], 0, json.dumps(passed)),
            ]) as execute:
                code, result = render_film(root, job_path, job)
                self.assertEqual(code, 0)
                self.assertIn('--recheck', execute.call_args.args[0])
                self.assertEqual(execute.call_count, 2)
                self.assertEqual(render_film(root, job_path, job)[1]['run_id'], result['run_id'])
                self.assertEqual(execute.call_count, 2)
            events = pending_events(job_path)
            self.assertEqual([(e['stage'], e['outcome']) for e in events],
                             [('quality', 'started'), ('quality', 'failed'), ('recheck', 'started'), ('recheck', 'passed')])
            self.assertEqual(events, pending_events(job_path))
            self.assertEqual(pending_events(job_path, {events[0]['event_id']}), events[1:])
            self.assertNotIn(str(root), json.dumps(events))

    def test_interrupted_parent_uses_completed_preview_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = root / 'film_pending_test' / 'preview.mp4.film.json'
            receipt.parent.mkdir()
            receipt.touch()
            (root / 'manifest.json').write_text('{"version":"test"}', encoding='utf8')
            job_path = root / 'job.json'
            job = {'film': True, 'clips': []}
            failed = {'error': 'CHECK_FAILED', 'pending_receipt': str(receipt),
                      'diagnostics': [{'code': 'FILM_CHECK_TIMEOUT'}]}

            def child(args, **kwargs):
                if '--recheck' not in args:
                    return subprocess.CompletedProcess(args, 2, json.dumps(failed))
                checkpoint = Path(kwargs['env']['THINKNOVA_RENDER_CHECKPOINT'])
                checkpoint.write_text(json.dumps({'status': 'succeeded', 'machine_check': 'pass'}), encoding='utf8')
                raise KeyboardInterrupt

            with patch('film_recovery.subprocess.run', side_effect=child) as execute:
                with self.assertRaises(KeyboardInterrupt):
                    render_film(root, job_path, job)
                code, result = render_film(root, job_path, job)
                self.assertEqual(code, 0)
                self.assertEqual(result['machine_check'], 'pass')
                self.assertEqual(execute.call_count, 2)
            self.assertEqual([(e['stage'], e['outcome']) for e in pending_events(job_path)],
                             [('quality', 'started'), ('quality', 'failed'), ('recheck', 'started'), ('recheck', 'passed')])

    def test_second_run_does_not_start_during_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with state_lock(root / '.job.json.film-state.json'):
                with patch('film_recovery.state_lock', side_effect=lambda path: state_lock(path, timeout=0)), patch('film_recovery.subprocess.run') as run:
                    self.assertEqual(render_film(root, root / 'job.json', {})[1]['error'], 'FILM_RUN_BUSY')
                    run.assert_not_called()
