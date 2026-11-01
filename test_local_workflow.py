"""Offline regressions for memory retention, read-only publishing and metrics traceability."""
import argparse
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import analytics
import toolkit

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('youtube_upload_under_test', ROOT / 'publish/youtube/upload.py')
youtube = importlib.util.module_from_spec(spec)
spec.loader.exec_module(youtube)


class MemoryTests(unittest.TestCase):
    def test_migration_preserves_old_content_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); memory = root / 'memory.md'
            original = '# Customer\nSecret-free local preference\n## 历史事件\n- old event\n'
            memory.write_text(original, encoding='utf-8')
            with patch.object(toolkit, 'MEMORY', memory), patch.object(toolkit, 'ARCHIVE', root / 'archive'):
                toolkit.migrate_memory()
                first = memory.read_text(encoding='utf-8')
                toolkit.migrate_memory()
                self.assertEqual(memory.read_text(encoding='utf-8'), first)
                self.assertIn('Secret-free local preference', first)
                self.assertIn('- old event', first)
                self.assertLess(first.index('## 生成任务与积分'), first.index('## 历史事件'))
                self.assertEqual(len(list((root / 'archive').iterdir())), 1)

    def test_archive_preserves_every_active_section(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); memory = root / 'memory.md'; archive = root / 'memory_archive'
            protected = '# Memory\n## Goal\nCafe\n## Pending\n- [ ] Post tomorrow\n## Published\nvideo123\n## Approval\nnot approved\n'
            original = protected + '## 历史事件\n' + '\n'.join('event %s' % i for i in range(400))
            memory.write_text(original, encoding='utf-8')
            with patch.object(toolkit, 'MEMORY', memory), patch.object(toolkit, 'ARCHIVE', archive): toolkit.archive()
            result = memory.read_text(encoding='utf-8')
            self.assertTrue(result.startswith(protected))
            self.assertIn('event 399', result)
            self.assertNotIn('event 0\n', result)
            self.assertEqual(next(archive.iterdir()).read_text(encoding='utf-8'), original)

    def test_legacy_memory_is_never_truncated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); memory = root / 'memory.md'
            original = 'legacy\n' * 400
            memory.write_text(original, encoding='utf-8')
            with patch.object(toolkit, 'MEMORY', memory), patch.object(toolkit, 'ARCHIVE', root / 'archive'): toolkit.archive()
            self.assertEqual(memory.read_text(encoding='utf-8'), original)

    def test_schedule_runs_actual_maintenance(self):
        self.assertEqual(toolkit.metrics_command()[-1], 'maintenance')
        self.assertEqual(Path(toolkit.metrics_command()[1]).name, 'toolkit.py')


class PublishTests(unittest.TestCase):
    def test_youtube_dry_never_accesses_account(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'test.mp4'; video.write_bytes(b'test fixture')
            job = {'video': str(video), 'title': 'test', 'privacy': 'public', 'schedule': '2030-01-01 10:00'}
            with patch.object(youtube.sys, 'argv', ['upload.py', 'job.json', '--dry']), patch.object(youtube.jobfile, 'load_job', return_value=job), patch.object(youtube, 'run_check', return_value=0), patch.object(youtube.yt_common, 'youtube') as api:
                self.assertEqual(youtube.main(), 0)
                api.assert_not_called()

    def test_youtube_without_execute_does_nothing(self):
        with patch.object(youtube.sys, 'argv', ['upload.py', 'job.json']), patch.object(youtube.jobfile, 'load_job') as load:
            self.assertEqual(youtube.main(), 1)
            load.assert_not_called()

    def test_missing_checker_stops_upload(self):
        with patch.object(youtube, 'CHECK', '/this/toolkit/checker/does/not/exist'):
            self.assertEqual(youtube.run_check('video.mp4', None), 2)


class MetricsTests(unittest.TestCase):
    def test_sample_contains_target_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); memory = root / 'memory.md'; targets = root / 'targets.json'
            memory.write_text('# Memory\n', encoding='utf-8')
            item = {'platform': 'youtube', 'content_id': 'video123', 'published_at': (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()}
            targets.write_text(json.dumps([item]), encoding='utf-8')
            with patch.object(analytics, 'MEMORY', memory), patch.object(analytics, 'TARGETS', targets), patch.object(analytics, 'youtube_metrics', return_value={'views': '9'}):
                self.assertEqual(analytics.collect(), 0)
                self.assertEqual(analytics.collect(), 0)
            text = memory.read_text(encoding='utf-8')
            self.assertIn('content_id=video123', text); self.assertIn(item['published_at'], text)
            self.assertEqual(text.count('content_id=video123'), 1)
            self.assertIn('24h', json.loads(targets.read_text()) [0]['collected_samples'])

    def test_failed_collection_does_not_mark_success_or_repost(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); memory = root / 'memory.md'; targets = root / 'targets.json'
            memory.write_text('# Memory\n', encoding='utf-8')
            item = {'platform': 'youtube', 'content_id': 'failed123', 'published_at': (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()}
            targets.write_text(json.dumps([item]), encoding='utf-8')
            with patch.object(analytics, 'MEMORY', memory), patch.object(analytics, 'TARGETS', targets), patch.object(analytics, 'youtube_metrics', side_effect=RuntimeError('login expired')):
                self.assertEqual(analytics.collect(), 2)
            saved = json.loads(targets.read_text())[0]
            self.assertEqual(saved['collected_samples'], {})
            self.assertIn('failed123', memory.read_text(encoding='utf-8'))

    def test_invalid_tiktok_url_is_rejected_before_browser(self):
        for url in ('https://example.com/video/123', 'https://www.tiktok.com/login', 'https://www.tiktok.com.evil.test/@a/video/123'):
            with self.assertRaises(RuntimeError): analytics.tiktok_metrics(url)

    def test_registration_requires_timezone_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(analytics, 'TARGETS', Path(directory) / 'targets.json'):
                args = argparse.Namespace(platform='youtube', content_id='v1', content_url=None, published_at='2026-11-01T10:00:00')
                with self.assertRaises(SystemExit): analytics.register(args)
                args.published_at += '+08:00'
                analytics.register(args); analytics.register(args)
                self.assertEqual(len(analytics.load_targets()), 1)


if __name__ == '__main__': unittest.main()
