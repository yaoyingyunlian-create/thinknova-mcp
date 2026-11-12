import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent / 'render'))
from speech_review import evaluate

class SpeechReviewTests(unittest.TestCase):
    def test_isolated_worker_errors(self):
        import subprocess
        from unittest.mock import patch
        from render.speech_review import recognize

        cases = [
            (subprocess.CompletedProcess([], 3221225477, '', ''), 'SPEECH_WORKER_CRASH'),
            (subprocess.TimeoutExpired([], 150), 'SPEECH_WORKER_TIMEOUT'),
            (subprocess.CompletedProcess([], 2, '{"error":"SPEECH_MODEL_UNAVAILABLE"}', ''), 'SPEECH_MODEL_UNAVAILABLE'),
        ]
        for result, expected in cases:
            with patch('render.speech_review.subprocess.run', side_effect=[result]):
                with self.assertRaisesRegex(RuntimeError, expected):
                    recognize('source.mp4', 'small', 'zh')



    def test_known_wrong_term_blocks(self):
        report=evaluate([{'start':0,'end':6,'text':'你们有没有小城厨'}],['小程序'])
        self.assertEqual(report['status'],'speech_mismatch')
        self.assertEqual(report['missing_terms'],['小程序'])
        self.assertFalse(report['publication_ready'])
    def test_match_is_not_pronunciation_approval(self):
        report=evaluate([{'start':0,'end':2,'text':'你们有没有小程序？'}],['小程序'])
        self.assertEqual(report['status'],'needs_listening_review')
        self.assertFalse(report['pronunciation_verified'])
        self.assertFalse(report['publication_ready'])
    def test_terms_across_segments_and_punctuation(self):
        report=evaluate([{'text':'小'},{'text':'程，序'}],['小程序'])
        self.assertEqual(report['missing_terms'],[])


class QualityPromptTests(unittest.TestCase):
    def test_small_program_pronunciation_only_for_spoken_video(self):
        from generation_quality import prepare_prompt
        self.assertIn('xiao3 cheng2 xu4',prepare_prompt('说：小程序','video'))
        self.assertNotIn('xiao3',prepare_prompt('门店照片','video'))
        self.assertNotIn('xiao3',prepare_prompt('小程序海报','image'))
    def test_anatomy_constraint_keeps_original_request(self):
        from generation_quality import prepare_prompt
        result=prepare_prompt('人物举手打招呼','image')
        self.assertTrue(result.startswith('人物举手打招呼'))
        self.assertIn('no extra/fused digits',result)


class AutomationQualityTests(unittest.TestCase):
    def test_new_plan_gets_constraints_without_paid_calls(self):
        import automation
        import tempfile
        import json
        import subprocess
        from unittest.mock import patch
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            def fake_plan(*args,**kwargs):
                (directory/'plan.json').write_text(json.dumps({'title':'test','description':'test','shots':[{'prompt':'说小程序'}]}),encoding='utf-8')
                return subprocess.CompletedProcess([],0)
            with patch.object(automation.shutil,'which',return_value='codex'), patch.object(automation.subprocess,'run',side_effect=fake_plan):
                result=automation.make_plan(directory,{})
            self.assertIn('xiao3 cheng2 xu4',result['shots'][0]['prompt'])
            self.assertIn('five total fingers',result['shots'][0]['prompt'])


class SpeechGateTests(unittest.TestCase):
    def test_mismatch_stops_runner_and_no_media_is_rewritten(self):
        import automation
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            media=Path(folder)/'sample.mp4';media.write_bytes(b'fixture')
            with patch('render.speech_review.transcribe',return_value=[{'text':'你们有没有小城厨'}]):
                with self.assertRaisesRegex(RuntimeError,'SPEECH_CONTENT_MISMATCH'):
                    automation.review_spoken_terms(media,'说小程序')
            self.assertEqual(media.read_bytes(),b'fixture')
            self.assertTrue(media.with_suffix('.speech-review.json').exists())
    def test_missing_runtime_stops_runner(self):
        import automation
        from unittest.mock import patch
        with patch('render.speech_review.transcribe',side_effect=RuntimeError('missing cache')):
            with self.assertRaisesRegex(RuntimeError,'SPEECH_REVIEW_UNAVAILABLE'):
                automation.review_spoken_terms(Path('fixture'),'小程序')
