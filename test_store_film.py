import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from automation import execute_store_day
from file_integrity import manifest_mismatches, sha256
from store_film import generation_arguments, validate_beats


class StoreFilmTests(unittest.TestCase):
    def test_browser_receipt_preserves_each_platform_and_is_idempotent(self):
        from browser_receipt import initialize, record
        from render.assemble import file_digest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            film = root / 'final.mp4'
            film.write_bytes(b'checked video fixture')
            proof = Path(str(film) + '.film.json')
            proof.write_text(json.dumps({'machine_check': 'pass', 'sha256': file_digest(film)}), encoding='utf-8')
            receipt = root / 'receipt.json'
            plan = {'project_key': 'shop', 'local_date': '2026-11-17',
                    'targets': {'instagram': '@shop', 'tiktok': '@shop'}}
            with unittest.mock.patch('browser_receipt.check_media'):
                initialize(receipt, film, plan)
                with self.assertRaisesRegex(ValueError, 'BROWSER_PUBLICATION_RECEIPT_CONFLICT'):
                    initialize(receipt, film, dict(plan, targets={'instagram': '@other'}))
                film.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'BROWSER_PUBLICATION_FILM_CHECK_REQUIRED'):
                    initialize(receipt, film, plan)
            record(receipt, 'tiktok', {'status': 'login_required', 'failure_reason': 'Session expired'})
            with self.assertRaisesRegex(ValueError, 'BROWSER_PUBLICATION_EVIDENCE_REQUIRED'):
                record(receipt, 'instagram', {'status': 'published'})
            event = {'status': 'published', 'post_url': 'https://www.instagram.com/reel/test/',
                     'published_at': '2026-11-17T22:00:00+08:00', 'portrait': True,
                     'sound': True, 'subject_visible': True}
            value = record(receipt, 'instagram', event)
            self.assertEqual(value['platforms']['tiktok']['status'], 'login_required')
            self.assertEqual(value['revision'], 3)
            self.assertEqual(record(receipt, 'instagram', event), value)

    def test_browser_receipt_reports_verified_server_ack_and_safe_failure(self):
        from browser_receipt import sync
        from unittest.mock import patch

        with patch('monitoring.TOKEN') as token, patch('secure_state.load'), patch('automation_client.Client') as client:
            token.is_file.return_value = False
            self.assertEqual(sync({}), {'sync': 'local_only', 'reason_code': 'MONITORING_CREDENTIAL_REQUIRED'})
            token.is_file.return_value = True
            endpoint = client.return_value.post
            endpoint.side_effect = RuntimeError('DEVICE_HTTP_422')
            self.assertEqual(sync({}), {'sync': 'queued', 'reason_code': 'DEVICE_HTTP_422'})
            endpoint.side_effect = None
            receipt_id = 'a' * 64
            endpoint.return_value = ({'data': {'accepted': True, 'receipt_id': receipt_id}}, {})
            self.assertEqual(sync({}), {'sync': 'synced', 'receipt_id': receipt_id})

    def test_new_film_checks_keep_brand_name_whole_and_require_full_hd(self):
        from render import check
        from render.assemble import split_text

        self.assertEqual(split_text('\u6211\u628a\u8fd9\u4efd\u793c\u7269\u9001\u5230\u9752\u5c71\u82b1\u5e97', cjk_limit=9,
                                    protected=('\u9752\u5c71\u82b1\u5e97',)), ['\u6211\u628a\u8fd9\u4efd\u793c\u7269\u9001\u5230', '\u9752\u5c71\u82b1\u5e97'])
        _, _, options = check.get_opts(['--store-boundaries', '[15]'])
        metadata = {'streams': [{'codec_type': 'video', 'width': 720, 'height': 1280, 'r_frame_rate': '30/1'}],
                    'format': {'duration': '30'}}
        with unittest.mock.patch.object(check, 'fail') as failure, unittest.mock.patch.object(check, 'INFO', []):
            check.s1_spec(metadata, options)
        failure.assert_any_call('FILM_STORE_RESOLUTION', 'expected 1080x1920; got 720x1280')

    def test_gap_across_segment_boundary_uses_one_second_limit(self):
        from types import SimpleNamespace
        from render import check

        words = [SimpleNamespace(word='first', start=0, end=14.3),
                 SimpleNamespace(word='second', start=15.7, end=30)]
        segments = [SimpleNamespace(words=[word], start=word.start, end=word.end) for word in words]
        _, _, options = check.get_opts(['--planned-film-seconds', '30'])
        options.update(film=True, store_film=True, outro_start=30, segment_boundaries=[15])
        with unittest.mock.patch('speech_review.recognize', return_value=(segments, SimpleNamespace(language='zh'))), \
             unittest.mock.patch('speech_review.speech_pace', return_value=4.5), \
             unittest.mock.patch.object(check, 'INFO', []), unittest.mock.patch.object(check, 'fail') as failure:
            check.s6_speech('ffmpeg', 'fixture.mp4', 30, options)
        self.assertEqual(failure.call_args.args[0], 'FILM_SEGMENT_SPEECH_GAP')

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

    def test_caption_alignment_tolerates_chinese_variants_and_uses_audio_windows(self):
        from types import SimpleNamespace
        from render.assemble import align_captions, recognized_caption_windows

        def speech(text):
            return [SimpleNamespace(words=[SimpleNamespace(word=text, start=0.5, end=2.5)])]

        cases = [('新车吗', '新車嗎'), ('头奖', '投獎'), ('欢迎来做头疗', '欢迎来做头')]
        for original, heard in cases:
            with self.subTest(script=original, heard=heard):
                self.assertEqual(align_captions([original], speech(heard), 3)[0]['text'], original)
        self.assertIsNone(align_captions(['顾客想了解头疗'], speech('明天天气非常不错'), 0))
        self.assertEqual(recognized_caption_windows(speech('明天天气非常不错'), 2), [(0.5, 2)])
        self.assertEqual(recognized_caption_windows([], 2), [])
        without_timestamp = [SimpleNamespace(words=[SimpleNamespace(word='头疗', start=None, end=None)])]
        self.assertIsNone(align_captions(['头疗'], without_timestamp, 0))
        self.assertEqual(recognized_caption_windows(without_timestamp, 2), [])

    def test_product_photo_aliases_share_one_reference_slot(self):
        segment = {'prompt': 'Show the product', 'duration_seconds': 15, 'first_frame_asset_id': 'asset_first',
                   'customer_product': True, 'reference_roles': ['first_frame', 'staff', 'product'],
                   'reference_boards': {'staff': 'asset_staff', 'product': 'asset_product'}}
        assets = {'asset_first', 'asset_staff', 'asset_product'}
        for field in ('product_photo_asset_id', 'product_sheet_asset_id'):
            used = generation_arguments(dict(segment, **{field: 'asset_product'}), {}, assets)
            self.assertEqual(used['reference_asset_ids'], ['asset_first', 'asset_staff', 'asset_product'])
        self.assertEqual(generation_arguments(segment, {}, assets)['reference_asset_ids'],
                         ['asset_first', 'asset_staff', 'asset_product'])
        with self.assertRaisesRegex(ValueError, 'FILM_PRODUCT_PHOTO_CONFLICT'):
            generation_arguments(dict(segment, product_photo_asset_id='asset_other'), {}, assets)
        with self.assertRaisesRegex(ValueError, 'FILM_PRODUCT_PHOTO_NOT_AUTHORIZED'):
            generation_arguments(segment, {}, assets - {'asset_product'})
        service = dict(segment, customer_product=False, reference_roles=None)
        self.assertEqual(generation_arguments(service, {}, assets)['reference_asset_ids'], ['asset_first'])

    def test_explainer_render_uses_supported_segment_combinations(self):
        from render.assemble import Stop, validate_job

        job = {'out': 'film.mp4', 'film': True, 'film_type': 'explainer', 'closing_overlay': ['ThinkNova']}
        for durations in ([15, 15, 15], [10, 11, 12, 12], [15] * 4):
            validate_job(dict(job, clips=[{'file': 'shot.mp4', 'dur': duration} for duration in durations]))
        for durations in ([15, 15, 14], [10] * 5, [9, 15, 15, 15]):
            with self.assertRaisesRegex(Stop, 'FILM_EXPLAINER_DURATION_INVALID'):
                validate_job(dict(job, clips=[{'file': 'shot.mp4', 'dur': duration} for duration in durations]))

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

    def test_explainer_checks_remaining_budget_after_all_quotes(self):
        client = Mock()
        client.tool.return_value = {'generation_quote': {
            'quote_only': True, 'creates_task': False, 'reserves_credits': False, 'estimated_credits': 60,
            'configured_video_specification': {'ratio': '9:16', 'duration_seconds': 15},
        }}
        client.post.return_value = ({'data': {'remaining_credits': 179}}, {})
        day = '2026-11-18'
        segment = {'prompt': 'A store scene', 'duration_seconds': 15, 'first_frame_asset_id': 'asset_first'}
        claim = {'grant': {'daily_budget': 250}, 'run_no': 'run_test', 'usage_date': day}
        plan = {'date': day, 'rules_version': 2, 'film_type': 'explainer',
                'shop_name': 'Store', 'featured_service': 'Flowers', 'segments': [segment] * 3}
        rules = {'version': 2, 'effective_rules': {'authorized_asset_ids': ['asset_first'],
                 'shop_profile': {'name': 'Store', 'featured_service': 'Flowers'}}}
        checkpoint = Mock()
        with self.assertRaisesRegex(RuntimeError, 'DAY_PLAN_OVER_BUDGET'):
            execute_store_day(client, claim, plan, 250, rules, {'quote_mode_supported': True, 'available_credits': 250},
                              None, {}, checkpoint)
        self.assertEqual([call.args[0] for call in client.tool.call_args_list], ['get_balance'] * 3)
        checkpoint.assert_not_called()

    def test_explainer_resume_passes_each_planned_duration_to_assembly(self):
        import hashlib
        from unittest.mock import patch

        day = '2026-11-18'
        durations = [10, 11, 12, 12]
        segments = [{'prompt': 'A store scene', 'duration_seconds': duration,
                     'first_frame_asset_id': 'asset_first', 'dialogue': [{'text': 'Welcome to our shop.'}]}
                    for duration in durations]
        plan = {'date': day, 'rules_version': 2, 'film_type': 'explainer', 'schema_version': 3,
                'dialogue_rules_revision': '2.4', 'film_purpose': 'service', 'shop_name': 'Store',
                'featured_service': 'Flowers', 'segments': segments}
        steps = {}
        claim = {'grant': {'daily_budget': 250}, 'run_no': 'run_test', 'usage_date': day}
        rules = {'version': 2, 'effective_rules': {'authorized_asset_ids': ['asset_first'],
                 'shop_profile': {'name': 'Store', 'featured_service': 'Flowers'}}}
        client = Mock()
        client.tool.return_value = {'status': 'succeeded'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, segment in enumerate(segments):
                segment['reference_boards'] = {'customer': 'asset_customer', 'staff': 'asset_staff'}
                steps[f'task_{index}'] = f'task_old_{index}'
                steps[f'quote_credits_{index}'] = '40'
                (root / f'shot{index}.mp4').touch()
            rules['effective_rules']['authorized_asset_ids'].extend(('asset_customer', 'asset_staff'))
            steps['day_plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True,
                                                               ensure_ascii=False).encode('utf-8')).hexdigest()
            with patch('automation.validate_media'), patch('render.assemble.probe', return_value=(15.0, (768, 1344), True)), \
                    patch('render.native_dialogue.inspect', return_value={'status': 'aligned'}) as dialogue_inspect, \
                    patch('automation.subprocess.run',
                    return_value=Mock(returncode=2, stdout='{}')):
                with self.assertRaisesRegex(RuntimeError, 'FILM_CHECK_FAILED'):
                    execute_store_day(client, claim, plan, 250, rules, {'available_credits': 0}, root, steps, Mock())
            self.assertEqual([call.args[7] for call in dialogue_inspect.call_args_list],
                             [f'task_old_{index}' for index in range(4)])
            job = json.loads((root / 'assemble.json').read_text(encoding='utf-8'))
            self.assertEqual([clip['planned_seconds'] for clip in job['clips']], durations)
            self.assertEqual(job['short_dialogue_seconds'], 45)
            self.assertEqual([clip['dialogue'] for clip in job['clips']],
                             [segment['dialogue'] for segment in segments])
            self.assertEqual([call.args[0] for call in client.tool.call_args_list], ['get_task'] * 4)
            client.reset_mock()
            steps.pop('task_3')
            with patch('automation.validate_media'), \
                    patch('render.assemble.probe', return_value=(15.0, (768, 1344), True)), \
                    patch('render.native_dialogue.inspect', return_value={
                        'status': 'silent_audio', 'code': 'FILM_NATIVE_AUDIO_SILENT'}), \
                    patch('automation.quoted_generation_args', return_value={'max_credits': 40}), \
                    patch('render.preflight.require_film_preflight') as readiness:
                client.post.return_value = ({'data': {'remaining_credits': 100}}, {})
                result = execute_store_day(client, claim, plan, 250, rules, {'available_credits': 100}, root, steps, Mock())
            self.assertEqual(result['status'], 'waiting_user')
            self.assertEqual(len(result['native_audio_issues']), 3)
            self.assertEqual([call.args[0] for call in client.tool.call_args_list], ['get_task'] * 3)
            readiness.assert_not_called()
            client.reset_mock()
            with patch('automation.validate_media'), \
                    patch('render.assemble.probe', return_value=(15.0, (768, 1344), True)), \
                    patch('render.native_dialogue.inspect', return_value={'status': 'aligned'}), \
                    patch('automation.quoted_generation_args', return_value={'max_credits': 40}), \
                    patch('render.preflight.require_film_preflight', side_effect=RuntimeError('SPEECH_WORKER_CRASH')):
                with self.assertRaisesRegex(RuntimeError, 'SPEECH_WORKER_CRASH'):
                    execute_store_day(client, claim, plan, 250, rules, {'available_credits': 100}, root, steps, Mock())
            self.assertEqual([call.args[0] for call in client.tool.call_args_list], ['get_task'] * 3)
