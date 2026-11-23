from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from render.native_dialogue import inspect, script_lines


def transcript(*words):
    return [SimpleNamespace(words=[SimpleNamespace(word=text, start=start, end=end)
                                   for text, start, end in words])], None


class NativeClipDialogueTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / 'original.mp4'
        self.source.write_bytes(b'source fixture')
        self.cache = self.source.parent / '.native-dialogue'
        self.lines = ['Meet our team.', 'Try a free fitting.', 'Book today!']
        self.asr = self.enterContext(patch('speech_recovery.recognize'))
        self.silence = self.enterContext(patch('render.native_dialogue.acoustic_silence', return_value=False))

    def check(self, *, audio=True, resume=False, start=0, task='task_0123456789ab'):
        return inspect(self.source, self.lines, 'en', 'ffmpeg', 8, audio, self.cache, task, start, resume=resume)

    def test_script_and_source_identity_are_reused(self):
        self.assertEqual(script_lines({'dialogue': [{'text': 'Book today!'}], 'subs': ['else']}), ['Book today!'])
        self.asr.return_value = transcript(('Meet our team', 0.1, 1.2), ('Try a free fitting', 2, 3.5), ('Book today', 5, 6))
        first = self.check()
        self.assertEqual(first['status'], 'aligned')
        self.assertEqual(first, self.check(start=0.0, resume=True))
        self.asr.assert_called_once()
        self.check(task='task_aaaaaaaaaaaa')
        self.source.write_bytes(b'changed fixture')
        third = self.check()
        self.assertNotEqual(first['source_sha256'], third['source_sha256'])
        self.assertEqual(self.asr.call_count, 3)

    def test_recovery_only_recognizes_missing_window_and_keeps_other_cues(self):
        self.asr.side_effect = [
            transcript(('Meet our team', 0.1, 1.2), ('Book today', 5, 6)),
            RuntimeError('SPEECH_WORKER_CRASHED: local runtime'),
            transcript(('Try a free fitting', 0.8, 2.3)),
        ]
        first = self.check()
        self.assertEqual(first['status'], 'transcription_unavailable')
        self.assertEqual(first['missing_lines'], [2])
        self.assertEqual(first, self.check())
        repaired = self.check(resume=True)
        self.assertEqual(repaired['status'], 'aligned')
        self.assertEqual(repaired['cues']['0'], first['cues']['0'])
        self.assertEqual(repaired['cues']['2'], first['cues']['2'])
        for call in self.asr.call_args_list[1:]:
            self.assertEqual(call.kwargs['audio_window'], [1.2, 3.8])
        self.assertEqual(repaired['cues']['1'], [2, 3.5])

    def test_consistent_unrelated_greeting_is_a_mismatch(self):
        self.asr.return_value = transcript(('Howdy folks', 0.4, 1.2))
        report = self.check()
        self.assertEqual(report['status'], 'dialogue_mismatch')
        self.assertEqual(report['evidence'], 'two_consistent_wrong_transcripts')

    def test_disagreeing_transcripts_are_not_a_generation_defect(self):
        self.asr.side_effect = [transcript(('Howdy folks', 0.4, 1.2)), transcript(('ZZZZ', 0.4, 1.2))]
        report = self.check()
        self.assertEqual(report['status'], 'timing_pending')
        self.assertEqual(report, self.check(resume=True))
        self.assertEqual(self.asr.call_count, 2)

    def test_skipped_line_requires_a_silent_gap(self):
        first = transcript(('Meet our team', 0.1, 1.2), ('Book today', 5, 6))
        self.asr.side_effect = [first, transcript(), first, transcript()]
        self.silence.side_effect = [False, False, False, True]
        self.assertEqual(self.check()['status'], 'timing_pending')
        report = self.check(task='task_aaaaaaaaaaaa')
        self.assertEqual(report['evidence'], 'silent_gap_between_aligned_lines')
        self.assertEqual(report['missing_lines'], [2])

    def test_missing_track_and_objective_silence_skip_asr(self):
        self.assertEqual(self.check(audio=False)['status'], 'missing_audio')
        self.silence.return_value = True
        self.assertEqual(self.check(task='task_aaaaaaaaaaaa')['status'], 'silent_audio')
        self.asr.assert_not_called()


if __name__ == '__main__':
    unittest.main()
