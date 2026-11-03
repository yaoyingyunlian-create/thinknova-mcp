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


if __name__=='__main__':unittest.main()
