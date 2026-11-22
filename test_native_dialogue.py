"""Original-audio delivery policy; all remote/ASR operations are simulated."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import quality_policy
from render import check, assemble


class NativeDialogueTests(unittest.TestCase):
    def test_partial_trim_preserves_dialogue_and_prefers_longest_join(self):
        cuts = assemble.plan_dialogue_cuts([15, 15, 15], [[(0, 11)], [(2, 14.5)], [(1, 15)]], 2)
        self.assertAlmostEqual(sum(end - start for start, end in cuts), 43)
        self.assertGreaterEqual(cuts[0][1], 11.2)
        self.assertLessEqual(cuts[1][0], 1.8)
        self.assertEqual(cuts[1][1], 15)
        self.assertEqual(cuts[2], (0, 15))
        self.assertEqual(assemble.plan_dialogue_cuts([15, 15], [[(0, 11)], []], 2), [(0, 15), (0, 15)])

    def test_quote_checks_effective_capacity_without_creating(self):
        from automation import quoted_generation_args
        from store_film import check_dialogue_capacity
        segment = {'duration_seconds': 15, 'dialogue': [
            {'speaker': 'a', 'text': ' '.join(['word'] * 20)},
            {'speaker': 'b', 'text': ' '.join(['word'] * 8)},
        ]}
        check_dialogue_capacity(segment, 2, 'en')
        client = Mock()
        client.tool.return_value = {'generation_quote': {'quote_only': True, 'creates_task': False,
            'reserves_credits': False, 'estimated_credits': 60,
            'configured_video_specification': {'ratio': '9:16', 'duration_seconds': 10}}}
        with self.assertRaisesRegex(ValueError, r'segment 2, needs 10.65s, available 10s'):
            quoted_generation_args(client, 'animate_image', {'ratio': '9:16', 'duration_seconds': 15},
                                   {'quote_mode_supported': True}, dialogue_check=(segment, 2, 'en'))
        self.assertEqual([call.args[0] for call in client.tool.call_args_list], ['get_balance'])
        segment['dialogue'][0]['text'] = '测' * 67
        segment['dialogue'][1]['text'] = '对'
        with self.assertRaisesRegex(ValueError, 'FILM_DIALOGUE_OVER_CAPACITY'):
            check_dialogue_capacity(segment, 2, 'zh')

    def tearDown(self):
        check.NATIVE = check.RELAXED = False
        check.FAILS.clear();check.WARNS.clear()

    def test_local_default_and_legacy_preview_upgrade(self):
        for value in (None, {}, {'version':'legacy'}):
            self.assertTrue(quality_policy.native(quality_policy.store_policy(value)))
        rollback={'version':'legacy','audio_source':'legacy_processing'}
        self.assertEqual(quality_policy.store_policy(rollback),rollback)
        self.assertEqual(quality_policy.store_policy({'version':'58'})['version'],'58')

    def test_reported_rates_and_pauses_do_not_block(self):
        check.NATIVE = check.RELAXED = True
        for rate in (5.39,3.74): check.fail('FILM_PACE_OUTSIDE_LIMIT',str(rate))
        for gap in (3.94,2.89,2.40): check.fail('FILM_SPEECH_GAP',str(gap))
        self.assertEqual(check.FAILS,[]);self.assertEqual(len(check.WARNS),5)
        for code in ('MEDIA_DECODE_FAILED','MEDIA_BLACK','S1d','S3_NEAR_SILENT','FILM_DIALOGUE_MISMATCH','FILM_CAPTIONS_REQUIRED','FILM_STORE_RESOLUTION'):
            check.fail(code,'fixture')
        self.assertEqual(len(check.FAILS),7)

    def test_cutting_blank_must_not_make_film_too_short(self):
        with patch.object(assemble,'speech_chunks',return_value=[(5,14)]),patch.object(assemble,'run_ff') as ff:
            shot,duration,report=assemble.trim_store_blank('ff','original.mp4',15,'temp',1,3,max_trim=3)
        self.assertEqual((shot,duration,report),('original.mp4',15,None));ff.assert_not_called()

    def test_publisher_only_reuses_hash_matched_native_proof(self):
        from publish.common.jobfile import quality_check_args
        with tempfile.TemporaryDirectory() as directory:
            video=Path(directory)/'native.mp4';video.write_bytes(b'fixture')
            proof={'machine_check':'pass','quality_policy_version':'native_dialogue_v1','sha256':hashlib.sha256(video.read_bytes()).hexdigest()}
            Path(str(video)+'.film.json').write_text(json.dumps(proof),encoding='utf-8')
            self.assertEqual(quality_check_args(video),['--native-dialogue'])
            video.write_bytes(b'edited');self.assertEqual(quality_check_args(video),[])

    def test_unknown_asr_stays_unknown(self):
        receipt=quality_policy.receipt(quality_policy.store_policy(),[{'code':'SPEECH_CHECK_PENDING','message':'fixture'}])
        self.assertEqual(receipt['speech_status'],'unknown');self.assertFalse(receipt['checks_completed'])

    def test_transient_check_retries_using_the_same_preview(self):
        from automation import render_store_candidate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / 'assemble.json'
            job.write_text('{"clips":[]}', encoding='utf-8')
            folder = root / 'film_pending_fixture'
            folder.mkdir()
            receipt = folder / 'preview.mp4.film.json'
            receipt.touch()
            reports = [
                Mock(returncode=2, stdout=json.dumps({'pending_receipt': str(receipt),
                      'diagnostics': [{'code': 'FILM_CHECK_TIMEOUT'}]})),
                Mock(returncode=0, stdout='{"machine_check":"pass"}'),
            ]
            with patch('automation.subprocess.run', side_effect=reports) as run:
                self.assertEqual(render_store_candidate(job)['machine_check'], 'pass')
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-3:], ['--recheck', str(receipt), '--json'])
            self.assertEqual(json.loads((root/'film-check.json').read_text(encoding='utf-8'))['automatic_recheck'], 'passed')

    def test_content_failure_only_rerenders_after_input_changes(self):
        from automation import render_store_candidate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / 'assemble.json'
            job.write_text('{"clips":[{"file":"shot.mp4"}]}', encoding='utf-8')
            source = root / 'shot.mp4'
            source.write_bytes(b'original')
            failed = Mock(returncode=2, stdout='{"diagnostics":[{"code":"FILM_DIALOGUE_MISMATCH"}]}')
            with patch('automation.subprocess.run', return_value=failed) as run:
                self.assertTrue(render_store_candidate(job)['render_failed'])
                self.assertEqual(render_store_candidate(job)['next_action'], 'fix_render_input_before_retry')
                self.assertEqual(run.call_count, 1)
                source.write_bytes(b'revised')
                render_store_candidate(job)
                self.assertEqual(run.call_count, 2)

    def test_legacy_pending_preview_rechecks_without_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'film_pending_fixture';folder.mkdir()
            video=folder/'preview.mp4';video.write_bytes(b'private preview fixture')
            receipt=folder/'preview.mp4.film.json'
            receipt.write_text(json.dumps({'state':'pending_check','machine_check':'failed',
                'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'output':'final.mp4','result':{},
                'options':{'outro_start':30,'film_profile':'store_v2','caption_alignment_pending':True,
                           'quality_policy':{'version':'legacy'}}}),encoding='utf-8')
            with patch.object(assemble,'tool',return_value='fixture'), \
                 patch.object(assemble,'norm_shot',side_effect=AssertionError('Do not render again')), \
                 patch.object(assemble,'run_delivery_check',return_value=(True,[],str(folder/'sheet.jpg'),'fixture')) as check_run, \
                 patch.object(assemble,'deliver',return_value=0) as deliver:
                self.assertEqual(assemble.recheck(str(receipt),False),0)
            self.assertTrue(quality_policy.native(check_run.call_args.args[4]['quality_policy']))
            self.assertEqual(deliver.call_args.args[5]['subtitle_timing'],'estimated_unverified')
            self.assertEqual(video.read_bytes(),b'private preview fixture')


if __name__ == '__main__':unittest.main()
