"""No downloads or installation side effects."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ego_runtime


class EgoTests(unittest.TestCase):
    def test_existing_runtime_does_not_download(self):
        with patch.object(ego_runtime, 'command', return_value='ego-browser'), patch.object(ego_runtime, 'probe', return_value=True), patch.object(ego_runtime.urllib.request, 'build_opener') as download:
            ego_runtime.prepare()
            download.assert_not_called()

    def test_broken_runtime_is_not_ready(self):
        with patch.object(ego_runtime, 'command', return_value='ego-browser'), patch.object(ego_runtime, 'probe', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'EGO_RUNTIME_FAILED'): ego_runtime.prepare()

    def test_redirect_must_remain_official_https(self):
        handler = ego_runtime.OfficialRedirect()
        for url in ('http://cdn.ego.app/file', 'https://example.com/setup.exe'):
            with self.assertRaisesRegex(RuntimeError, 'UNSAFE_DOWNLOAD'): handler.redirect_request(None, None, 302, '', {}, url)

    def test_onboarding_does_not_repeat_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'ThinkNova'/'installers'; cache.mkdir(parents=True)
            (cache/'ego-install-started').write_text('started', encoding='utf-8')
            with patch.dict(ego_runtime.os.environ, {'LOCALAPPDATA':directory}), patch.object(ego_runtime, 'command', return_value=None), patch.object(ego_runtime.platform, 'system', return_value='Windows'), patch.object(ego_runtime.platform, 'machine', return_value='AMD64'), patch.object(ego_runtime.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(RuntimeError, 'ONBOARDING_REQUIRED'): ego_runtime.prepare()
                launch.assert_not_called()
