import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import media_download
from publish import dispatch
from render import check


class Response(io.BytesIO):
    def __init__(self, body, length, status=200, content_range=None):
        super().__init__(body)
        self.status = status
        self.headers = {'Content-Type': 'video/mp4', 'Content-Length': str(length), 'X-Request-ID': 'trace'}
        if content_range:
            self.headers['Content-Range'] = content_range


class DownloadTests(unittest.TestCase):
    url = 'https://api.thinknova.top/api/v1/assets/asset_A/media?signature=hidden'

    def run_download(self, responses, error=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'shot.mp4'
            opener = Mock()
            opener.open.side_effect = responses
            with patch.object(media_download.urllib.request, 'build_opener', return_value=opener), patch.object(media_download.subprocess, 'run') as decode:
                if error:
                    with self.assertRaisesRegex(RuntimeError, error):
                        media_download.download(self.url, path, 'task_test')
                    self.assertFalse(path.exists())
                    decode.assert_not_called()
                    log = path.with_suffix('.download-error.json').read_text(encoding='utf-8')
                    self.assertNotIn('hidden', log)
                    self.assertEqual(json.loads(log)['asset_id'], 'asset_A')
                else:
                    media_download.download(self.url, path, 'task_test')
                    self.assertEqual(path.read_bytes(), b'abcd')
                    decode.assert_called_once()
                self.assertFalse(path.with_suffix('.part').exists())
            return opener

    def test_complete_and_500_recovery(self):
        self.run_download([Response(b'abcd', 4)])
        self.run_download([HTTPError(self.url, 500, '', {}, None), Response(b'abcd', 4)])

    def test_managed_redirect_and_500_fallback(self):
        target = 'https://thinknova-previews.oss-ap-southeast-1.aliyuncs.com/generated-assets/fixture.mp4?Signature=hidden'
        redirect = HTTPError(self.url, 302, '', {'Location': target}, io.BytesIO())
        opener = self.run_download([HTTPError(self.url, 500, '', {}, None), redirect, Response(b'abcd', 4)])
        self.assertNotIn('download=1', opener.open.call_args_list[1].args[0].full_url)
        self.assertEqual(opener.open.call_args.args[0].full_url, target)
        invalid = HTTPError(self.url, 302, '', {'Location': 'https://example.com/generated-assets/file.mp4?x=1'}, io.BytesIO())
        self.run_download([invalid], 'UNSAFE_DELIVERY_REDIRECT')
    def test_short_response_resumes_and_checks_range(self):
        opener = self.run_download([Response(b'ab', 4), Response(b'cd', 2, 206, 'bytes 2-3/4')])
        self.assertEqual(opener.open.call_args.args[0].get_header('Range'), 'bytes=2-')
        self.run_download([Response(b'ab', 4), Response(b'cd', 2, 206, 'bytes 1-2/4')], 'INVALID_DELIVERY_RANGE')
        self.run_download([Response(b'ab', 4), Response(b'abcd', 4)])

    def test_unauthorized_and_exhausted_retries(self):
        self.run_download([HTTPError(self.url, 401, '', {}, None)], 'DELIVERY_HTTP_401')
        self.run_download([HTTPError(self.url, 500, '', {}, None) for _ in range(3)], 'DELIVERY_HTTP_500')
        self.run_download([Response(b'a', 4) for _ in range(3)], 'DELIVERY_INCOMPLETE')


class FilmTests(unittest.TestCase):
    def test_speech_gap_includes_opening_and_pre_outro_tail(self):
        words = [SimpleNamespace(start=0.4, end=2), SimpleNamespace(start=4.3, end=5)]
        self.assertEqual(check.speech_gaps(words, 8), [(0, 0.4), (2, 4.3), (5, 8)])
        self.assertEqual(check.speech_gaps(words, 3), [(0, 0.4), (2, 3)])

    def test_film_review_binds_platform_version_and_blocks_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.json'
            video = Path(directory) / 'film.mp4'
            video.with_suffix('.mp4.film.json').write_text(json.dumps({'machine_check': 'pass', 'sha256': 'good'}), encoding='utf-8')
            value = {'platform':'youtube', 'job':{}, 'manifest_sha256':'approved-version',
                     'artifacts':[{'role':'video','file':str(video),'sha256':'good'}]}
            with patch.object(dispatch, 'snapshot', return_value=value), patch.object(dispatch.subprocess, 'run') as publisher:
                with self.assertRaisesRegex(RuntimeError, 'FILM_REVIEW_REQUIRED'):
                    dispatch.dispatch(path, 'youtube', execute=True, confirmed=True)
                publisher.assert_not_called()
                self.assertEqual(dispatch.film_review(path, value, 'approved-version', True), 'approved')
                self.assertEqual(dispatch.film_review(path, value), 'approved')
                self.assertEqual(dispatch.film_review(path, {**value, 'manifest_sha256':'changed-title'}), 'awaiting_review')
                self.assertEqual(dispatch.film_review(path, {**value, 'platform':'tiktok'}), 'awaiting_review')
