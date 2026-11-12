import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from automation import execute_store_day
from file_integrity import manifest_mismatches, sha256
from store_film import generation_arguments, validate_beats


class StoreFilmTests(unittest.TestCase):
    def test_manifest_uses_same_text_and_binary_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text, binary = root / 'example.py', root / 'image.jpg'
            text.write_bytes(b'one\r\ntwo\r\n')
            binary.write_bytes(b'\x00\r\n')
            entries = [{'path': file.name, 'sha256': sha256(file, normalize_text=True)} for file in (text, binary)]
            self.assertEqual(manifest_mismatches(root, {'files': entries, 'text_line_endings': 'lf'}), [])
            self.assertEqual(manifest_mismatches(root, {'files': entries}), ['example.py'])
            text.write_bytes(b'one\ntwo\n')
            binary.write_bytes(b'\x00\n')
            self.assertEqual(manifest_mismatches(root, {'files': entries, 'text_line_endings': 'lf'}), ['image.jpg'])

    def test_structure_and_generation_preflight(self):
        validate_beats([{'beats': ['pain', 'process']}, {'beats': ['change', 'service']}], 'story')
        with self.assertRaisesRegex(ValueError, 'FILM_BEATS_REQUIRED'):
            validate_beats([{'beats': ['pain', 'service']}], 'story')
        segment = {'prompt': '顾客进店', 'duration_seconds': 10,
                   'first_frame_asset_id': 'asset_first', 'reference_asset_ids': ['asset_shop'],
                   'shop_location': 'front'}
        args = generation_arguments(segment, {'front': ['asset_shop']}, {'asset_first', 'asset_shop'})
        self.assertEqual(args['reference_asset_ids'], ['asset_first', 'asset_shop'])
        self.assertEqual(args['shop_location'], 'front')
        with self.assertRaisesRegex(ValueError, 'FILM_SHOP_REFERENCE_REQUIRED'):
            generation_arguments(segment, {}, {'asset_first', 'asset_shop'})
        with self.assertRaisesRegex(ValueError, 'FILM_PROMPT_TOO_LONG'):
            generation_arguments(dict(segment, prompt='长' * 1300), {}, set())

    def test_day_quotes_all_segments_before_budget_rejection(self):
        from datetime import datetime, timezone
        client = Mock()
        client.tool.return_value = {'generation_quote': {'quote_only': True, 'creates_task': False,
                                                         'reserves_credits': False, 'estimated_credits': 40}}
        segment = {'prompt': 'A store scene', 'duration_seconds': 10, 'first_frame_asset_id': 'asset_first'}
        claim = {'grant': {'timezone': 'UTC', 'daily_budget': 100}, 'run_no': 'run_test', 'usage_date': datetime.now(timezone.utc).date().isoformat()}
        plan = {'date': datetime.now(timezone.utc).date().isoformat(), 'rules_version': 2,
                'shop_name': 'Store', 'featured_service': 'Flowers', 'segments': [segment, segment]}
        rules = {'version': 2, 'effective_rules': {'authorized_asset_ids': ['asset_first'],
                 'shop_profile': {'name': 'Store', 'featured_service': 'Flowers'}}}
        checkpoint = Mock()
        with self.assertRaisesRegex(RuntimeError, 'DAY_PLAN_OVER_BUDGET'):
            execute_store_day(client, claim, plan, 75, rules, {'quote_mode_supported': True},
                              None, {}, checkpoint)
        self.assertEqual([call.args[0] for call in client.tool.call_args_list], ['get_balance', 'get_balance'])
        checkpoint.assert_not_called()
