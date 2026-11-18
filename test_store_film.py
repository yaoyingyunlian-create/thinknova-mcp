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

    def test_fast_dialogue_retime_needs_edge_silence_and_preserves_length(self):
        from render.assemble import dialogue_pace_adjustment
        start, stop, factor = dialogue_pace_adjustment(5.6, 'zh', 15, [(0.5, 7), (7.8, 13.0)])
        self.assertAlmostEqual((stop - start) / factor, 15.0)
        self.assertLessEqual(5.6 * factor, 5.2)
        self.assertGreaterEqual(stop, 13.15)
        self.assertIsNone(dialogue_pace_adjustment(5.6, 'zh', 15, [(0, 14.8)]))
        start, stop, factor = dialogue_pace_adjustment(5.34, 'zh', 15, [(0, 15)], 15.45)
        self.assertLessEqual((stop - start) / factor, 15.45)
        self.assertLess(5.34 * factor, 5.2)
        self.assertEqual((start, stop), (0, 15))
        self.assertIsNone(dialogue_pace_adjustment(5.6, 'zh', 15, [(0, 15)], 15.45))
        self.assertIsNone(dialogue_pace_adjustment(4.8, 'zh', 15, [(0.5, 13)]))

    def test_delivery_keeps_original_quality_report(self):
        from render.assemble import deliver
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video, sheet, output = (root / name for name in ('checked.mp4', 'sheet.jpg', 'final.mp4'))
            video.write_bytes(b'video fixture')
            sheet.write_bytes(b'sheet fixture')
            with unittest.mock.patch('render.assemble.emit'):
                self.assertEqual(deliver(str(video), None, str(sheet), str(output),
                                         {'outro_start': 27.5}, {}, [], False,
                                         'Original machine check'), 0)
            self.assertEqual(Path(str(output) + '.check.txt').read_text(encoding='utf-8'), 'Original machine check')
            receipt = json.loads(Path(str(output) + '.film.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['machine_check'], 'pass')

    def test_store_source_accepts_aligned_portrait_but_rejects_wrong_ratio(self):
        from render.assemble import Stop, check_store_source
        for width, height, accepted in [(768, 1344, True), (720, 1280, True),
                                        (768, 1024, False), (1344, 768, False)]:
            measured = Mock(stdout=json.dumps({'streams': [{'width': width, 'height': height}]}))
            scan = Mock(returncode=0, stderr='')
            with self.subTest(size=(width, height)), unittest.mock.patch(
                    'render.assemble.subprocess.run', side_effect=[measured, scan]) as run:
                if accepted:
                    check_store_source('ffmpeg', 'ffprobe', 'video.mp4', 1)
                    self.assertEqual(run.call_count, 2)
                else:
                    with self.assertRaisesRegex(Stop, 'FILM_SOURCE_NOT_PORTRAIT'):
                        check_store_source('ffmpeg', 'ffprobe', 'video.mp4', 1)

    def test_v21_generation_requires_distinct_ordered_reference_boards(self):
        segment = {'prompt': 'Two people choose flowers', 'duration_seconds': 15,
                   'first_frame_asset_id': 'asset_first', 'shop_location': 'front',
                   'reference_roles': ['first_frame', 'customer', 'staff'],
                   'reference_boards': {'customer': 'asset_customer'}}
        allowed = {'asset_first', 'asset_customer', 'asset_staff'}
        with self.assertRaisesRegex(ValueError, 'BOARD_REQUIRED: staff'):
            generation_arguments(segment, {'front': ['asset_first']}, allowed)
        segment['reference_boards']['staff'] = 'asset_staff'
        args = generation_arguments(segment, {'front': ['asset_first']}, allowed)
        self.assertEqual(args['reference_asset_ids'], ['asset_first', 'asset_customer', 'asset_staff'])

    def test_reference_preparation_upscales_without_overwriting(self):
        from PIL import Image
        from toolkit import prepare_reference
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source.png', root / 'prepared.png'
            Image.new('RGB', (225, 300), 'red').save(source)
            original = source.read_bytes()
            result = prepare_reference(source, output)
            self.assertTrue(result['derived'])
            self.assertEqual((result['width'], result['height']), (256, 342))
            self.assertEqual(source.read_bytes(), original)
            with Image.open(output) as image:
                self.assertEqual(image.size, (256, 342))
            with self.assertRaisesRegex(ValueError, 'REFERENCE_OUTPUT_EXISTS'):
                prepare_reference(source, output)
            self.assertFalse(prepare_reference(output, root / 'not-needed.png')['derived'])

    def test_closing_overlay_valid_without_card_or_platform(self):
        from render.assemble import Stop, validate_job
        job = {'film': True, 'explainer_preview': True, 'out': 'film.mp4',
               'clips': [{'file': 'clip.mp4'}] * 5, 'closing_overlay': ['ThinkNova']}
        validate_job(job)
        validate_job({key: value for key, value in job.items() if key != 'closing_overlay'})
        with self.assertRaisesRegex(Stop, 'FILM_CLOSING_OVERLAY_INVALID'):
            validate_job(dict(job, end_card={'lines': ['Old card']}))

    def test_caption_alignment_preserves_text_and_gap(self):
        from types import SimpleNamespace
        from render.assemble import align_captions
        words = [SimpleNamespace(word='你好', start=0.2, end=0.8),
                 SimpleNamespace(word='再见', start=2.0, end=2.3)]
        spoken = [SimpleNamespace(words=words)]
        cues = align_captions(['你好！', '再见。'], spoken, 10)
        self.assertEqual(cues[0], {'text': '你好！', 'start': 10.2, 'end': 10.8})
        self.assertEqual(cues[1]['start'], 12.0)
        self.assertIsNone(align_captions(['你好！', '明天见。'], spoken, 10))

    def test_portrait_quote_rejects_silent_landscape(self):
        from automation import quoted_generation_args
        from unittest.mock import Mock
        client = Mock()
        client.tool.return_value = {'generation_quote': {'quote_only': True, 'creates_task': False,
            'reserves_credits': False, 'estimated_credits': 60, 'configured_video_specification': {'ratio': '21:9'}}}
        with self.assertRaisesRegex(RuntimeError, 'MCP_VIDEO_QUOTE_RATIO_MISMATCH'):
            quoted_generation_args(client, 'animate_image', {'ratio': '9:16'}, {'quote_mode_supported': True})

    def test_day_quotes_all_segments_before_budget_rejection(self):
        from datetime import datetime, timezone
        client = Mock()
        client.tool.return_value = {'generation_quote': {'quote_only': True, 'configured_video_specification': {'ratio': '9:16'}, 'creates_task': False,
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
