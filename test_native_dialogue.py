"""Original-audio delivery policy; all remote/ASR operations are simulated."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import quality_policy
from render import check, assemble


class NativeDialogueTests(unittest.TestCase):
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
