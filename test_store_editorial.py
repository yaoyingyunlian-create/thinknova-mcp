from datetime import date, timedelta
from types import SimpleNamespace
import unittest

from render.speech_review import pace_factor, speech_pace
from store_editorial import FORMATS, prepare_copy, validate_rotation, validate_platform_copy


class EditorialTests(unittest.TestCase):
    def test_week_rotation_and_history_windows(self):
        profile = {'audiences': ['a', 'b', 'c'], 'scenes': ['s1', 's2', 's3'],
                   'pain_points': ['p1', 'p2', 'p3'], 'features': ['f1', 'f2', 'f3'],
                   'questions': [{'id': f'q{i}', 'count': 4 - i} for i in range(1, 4)]}
        start = date(2026, 11, 12)
        coords = [(0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (2, 0), (0, 2)]
        rows = [{'date': (start + timedelta(days=i)).isoformat(), 'row': profile['audiences'][r],
                 'col': profile['features'][c], 'scene': 's1', 'format': FORMATS[i % 4],
                 'opening': f'opening {i}', 'opening_visual': f'frame_{i}', 'question': f'q{i % 3 + 1}'}
                for i, (r, c) in enumerate(coords)]
        self.assertEqual(validate_rotation(rows, [], profile), rows)
        old = dict(rows[0], date=(start - timedelta(days=40)).isoformat())
        with self.assertRaisesRegex(ValueError, 'PLAN_HISTORY_REPEAT'):
            validate_rotation(rows, [old], profile)
        changed = dict(old, format='qa', opening='Another line', opening_visual='old')
        self.assertEqual(validate_rotation(rows, [changed], profile), rows)
        changed['date'] = (start - timedelta(days=20)).isoformat()
        with self.assertRaisesRegex(ValueError, 'PLAN_HISTORY_REPEAT'):
            validate_rotation(rows, [changed], profile)

    def test_copy_requires_fields_and_rejects_platform_prohibitions(self):
        variant = {'title': '下班后想放松的新加坡顾客', 'tags': ['新加坡', '头疗'],
                   'marketing_copy': {'audience_or_pain': '下班总是很累？', 'solution': 'Miorae 做头疗',
                                      'verified_fact': '汤每天现熬', 'next_step': '评论区问我'}}
        self.assertIn('汤每天现熬', prepare_copy('xiaohongshu', variant))
        with self.assertRaisesRegex(ValueError, 'COPY_FORBIDDEN_TERM: xiaohongshu.next_step'):
            prepare_copy('xiaohongshu', dict(variant, marketing_copy={**variant['marketing_copy'], 'next_step': '请去主页留言'}))
        with self.assertRaisesRegex(ValueError, 'COPY_VARIANTS_TOO_SIMILAR'):
            validate_platform_copy({'youtube': variant, 'facebook': variant})

    def test_speech_pace_respects_limit(self):
        words = [SimpleNamespace(word='你好世界', start=0, end=1.25)]
        segments = [SimpleNamespace(text='你好世界', start=0, end=1.25, words=words)]
        rate = speech_pace(segments, 'zh')
        self.assertEqual(rate, 3.2)
        self.assertEqual(pace_factor(rate, 'zh'), 1.25)
        self.assertLess(rate * pace_factor(rate, 'zh'), 4.2)
        self.assertEqual(pace_factor(4.5, 'zh'), 1.0)
        self.assertLess(pace_factor(6.0, 'zh'), 1.0)

    def test_unknown_publication_does_not_upload_again(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import hashlib
        from unittest.mock import Mock, patch
        import automation

        run_no = 'run_' + 'a' * 24
        with TemporaryDirectory() as temp:
            state = Path(temp)
            run_dir = state / 'runs' / run_no
            run_dir.mkdir(parents=True)
            job = run_dir / 'publish.json'
            job.write_text('{}', encoding='utf-8')
            claim = {'run_no': run_no, 'usage_date': '2026-11-12',
                     'grant': {'auto_publish': True, 'project_key': 'store', 'channel_id': 'UC' + 'b' * 22},
                     'steps': {'publication_started': 'yes',
                               'publish_job_hash': hashlib.sha256(job.read_bytes()).hexdigest()}}
            client = Mock()
            with patch.object(automation, 'STATE', state), patch.object(automation, 'run_command') as upload:
                with self.assertRaisesRegex(RuntimeError, 'PUBLICATION_OUTCOME_UNKNOWN'):
                    automation.publish_store_day(client, claim)
            upload.assert_not_called()
            self.assertEqual(client.receipt.call_args.args[2:], ('waiting_user', 'PUBLICATION_OUTCOME_UNKNOWN'))
