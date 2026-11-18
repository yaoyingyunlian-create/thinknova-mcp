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

    def test_v3_dialogue_and_exact_history_window(self):
        from store_editorial import FILM_V3_FORMATS, validate_dialogue_v3
        profile = {'audiences': ['a', 'b', 'c'], 'scenes': ['s1', 's2', 's3'],
                   'pain_points': ['p1', 'p2', 'p3'], 'features': ['f1', 'f2', 'f3'],
                   'questions': [{'id': f'q{i}', 'count': 4 - i} for i in range(1, 4)]}
        start = date(2026, 11, 16)
        week = [{'date': (start + timedelta(days=i)).isoformat(), 'row': profile['audiences'][i % 3],
                 'col': profile['features'][i % 3], 'scene': 's1', 'format': format_code,
                 'opening': f'opening {i}', 'opening_visual': f'frame_{i}', 'question': f'q{i % 3 + 1}'}
                for i, format_code in enumerate(FILM_V3_FORMATS)]
        self.assertEqual(validate_rotation(week, [dict(week[0], date='2026-11-02')], profile, 3), week)
        with self.assertRaisesRegex(ValueError, 'PLAN_HISTORY_REPEAT'):
            validate_rotation(week, [dict(week[0], date='2026-11-03')], profile, 3)
        lines = [{'speaker': speaker, 'listener': 'staff' if speaker == 'customer' else 'customer',
                  'action': 'chooses a flower', 'emotion': 'curious', 'text': '花' * 21}
                 for speaker in ('customer', 'staff', 'customer')]
        segment = {'dialogue': lines, 'subs': ['花' * 7] * 9}
        plan = {'script': {'template': 'two_person_dialogue', 'voice_identity': 'voice'},
                'film_purpose': 'service', 'shop_name': '花店', 'featured_service': '鲜花',
                'closing_overlay': ['花店'], 'customer_identity': 'short-hair', 'segments': [segment, segment]}
        validate_dialogue_v3(plan)
        segment['subs'] = segment['subs'][:-1]
        with self.assertRaisesRegex(ValueError, 'CAPTIONS_MISMATCH'):
            validate_dialogue_v3(plan)
        lines[0]['text'] = '短'
        with self.assertRaisesRegex(ValueError, 'WORD_COUNT'):
            validate_dialogue_v3(plan)

    def test_v21_requires_answer_and_rejects_reused_dialogue(self):
        from store_editorial import dialogue_v21_lines
        question = {'kind': 'question', 'speaker': 'customer', 'text': '鞋底还能补吗？'}
        answer = {'kind': 'answer', 'speaker': 'staff', 'text': '可以补。'}
        plan = {'segments': [{'dialogue': [question, answer]}]}
        self.assertEqual(dialogue_v21_lines(plan), ['鞋底还能补吗', '可以补'])
        with self.assertRaisesRegex(ValueError, 'LINE_REPEATED'):
            dialogue_v21_lines(plan, ['鞋底还能补吗'])
        with self.assertRaisesRegex(ValueError, 'QUESTION_ANSWER_REQUIRED'):
            dialogue_v21_lines({'segments': [{'dialogue': [question, dict(answer, speaker='customer')]}]})

    def test_v52_requires_exact_quotes_and_allows_solo_explainer(self):
        from store_editorial import validate_dialogue_v3

        segments = []
        for index, chars in enumerate(('花草叶', '开合关', '香色瓣')):
            lines = []
            for turn, char in enumerate(chars):
                speaker = 'customer' if index == 0 and turn == 0 else 'staff'
                kind = ('question', 'answer', 'statement')[turn] if index == 0 else 'statement'
                lines.append({'speaker': speaker, 'listener': ('staff' if speaker == 'customer' else 'customer')
                              if index == 0 else 'camera', 'kind': kind, 'action': 'holds product',
                              'emotion': 'interested', 'text': char * 20 + ('？' if kind == 'question' else '。'),
                              'classification': '好处或原因', 'source_ref': 'F1', 'visual': 'Face visible',
                              'camera': 'Medium shot'})
            segments.append({'duration_seconds': 15, 'dialogue': lines, 'subs': [line['text'] for line in lines],
                             'prompt': '对着镜头讲解' if index else 'Two people chat'})
        quote = segments[0]['dialogue'][0]
        quote.update(classification='原话', source_ref='Q1')
        plan = {'script_rules_revision': '52', 'dialogue_rules_revision': '2.4',
                'film_type': 'explainer', 'film_purpose': 'product', 'shop_name': '花店', 'featured_service': '鲜花',
                'script': {'template': 'two_person_dialogue', 'voice_identity': 'voice'}, 'customer_identity': 'short-hair',
                'closing_overlay': ['鲜花'], 'segments': segments, 'week_rows': [{'format': 'explainer'}],
                'script_sources': {'Q1': quote['text'], 'F1': '包装明确标注用法'}, 'category_direction': '食品｜包装',
                'dialogue_classification_counts': {'麻烦': 0, '好处或原因': 8, '原话': 1, '情境': 0}}
        validate_dialogue_v3(plan)
        plan['script_sources']['Q1'] = '不是已核实的原话'
        with self.assertRaisesRegex(ValueError, 'DAY_PLAN_CUSTOMER_QUOTE_INVALID'):
            validate_dialogue_v3(plan)

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
