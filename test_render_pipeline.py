"""Real local media smoke using synthetic video/audio only."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import automation


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Local media tools unavailable')
class RenderTests(unittest.TestCase):
    def test_normalize_concat_loudness_and_quality_gate(self):
        with tempfile.TemporaryDirectory(prefix='thinknova-local-render-') as directory:
            root=Path(directory).resolve()
            self.assertTrue(root.name.startswith('thinknova-local-render-'))
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=160x284:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3','-c:v','libx264','-c:a','aac','-shortest',str(root/'shot0.mp4')],check=True,capture_output=True,timeout=30)
            result=automation.compose(root,1)
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=width,height,codec_type','-of','json',str(result)]))
            video=next(x for x in probe['streams'] if x['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(1080,1920))
            self.assertTrue(any(x['codec_type']=='audio' for x in probe['streams']))


    def test_pending_preview_recheck(self):
        from render import assemble
        from publish.dispatch import film_review
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video, output = root / 'render.mp4', root / 'final.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=64x64:rate=12', '-t', '1', '-c:v', 'libx264', str(video)],
                           check=True, capture_output=True, timeout=20)
            settings = {'outro_start': 0.8, 'speech_language': 'zh', 'max_dur': 40}
            with patch.object(assemble, 'emit') as emit:
                self.assertEqual(assemble.save_pending(shutil.which('ffmpeg'), str(video), None,
                                 str(root / 'missing.jpg'), str(output), settings, {}, [], 'speech crash'), 2)
            preview = Path(emit.call_args.args[0]['preview'])
            receipt = Path(emit.call_args.args[0]['pending_receipt'])
            self.assertFalse(output.exists())
            self.assertEqual(preview.read_bytes(), video.read_bytes())
            with self.assertRaisesRegex(RuntimeError, 'FILM_CHECK_REQUIRED'):
                film_review(root / 'publish.json', {'job': {}, 'artifacts': [
                    {'role': 'video', 'file': str(preview), 'sha256': assemble.file_digest(preview)}]})
            preview.write_bytes(b'changed')
            with patch.object(assemble, 'run_delivery_check') as check:
                with self.assertRaisesRegex(assemble.Stop, 'PREVIEW_DIGEST_MISMATCH'):
                    assemble.recheck(str(receipt), False)
                check.assert_not_called()
            preview.write_bytes(video.read_bytes())

            def passed(_ff, _fp, rendered, _srt, options):
                self.assertEqual(options, settings)
                sheet = Path(rendered).with_name('delivery_sheet.jpg')
                sheet.write_bytes(b'test contact sheet')
                return True, [], str(sheet), ''

            with patch.object(assemble, 'run_delivery_check', side_effect=passed), patch.object(assemble, 'emit'):
                self.assertEqual(assemble.recheck(str(receipt), False), 0)
            proof = json.loads((root / 'final.mp4.film.json').read_text(encoding='utf-8'))
            self.assertEqual(proof['sha256'], assemble.file_digest(output))
            self.assertEqual(proof['machine_check'], 'pass')



if __name__=='__main__':unittest.main()
