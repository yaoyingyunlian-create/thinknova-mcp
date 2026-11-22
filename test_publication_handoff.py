from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation import atomic
from browser_receipt import record
from file_integrity import sha256
from publication_handoff import reserve, schedule_requests


class PublicationHandoffTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.video = self.root / 'film.mp4'
        self.video.write_bytes(b'synthetic')
        self.proof = Path(str(self.video) + '.film.json')
        self.digest = sha256(self.video)
        atomic(self.proof, {'machine_check': 'pass', 'sha256': self.digest, 'speech_status': 'checked'})
        self.package = self.root / 'review.json'
        atomic(self.package, {'video': str(self.video), 'sha256': self.digest, 'project_key': 'shop',
                              'platforms': {'youtube': {'title': 'One', 'target_account': '@right'}}})
        self.now = datetime(2026, 11, 22, 18, tzinfo=timezone.utc)
        self.plan = {'project_key': 'shop', 'local_date': '2026-11-22', 'targets': {
            'youtube': {'target_account': '@right', 'confirmed': True, 'due_at': '2026-11-22T17:20:00Z',
                        'window_ends_at': '2026-11-22T19:00:00Z',
                        'approval': {'scope': 'standing', 'first_film_reviewed': True,
                                     'requires_per_version_review': False, 'content_review_pending': False}}}}

    def test_first_review_replacement_and_time_window(self):
        self.assertEqual(schedule_requests(self.plan)[0]['data']['target_account'], '@right')
        approval = self.plan['targets']['youtube'].pop('approval')
        self.assertEqual(reserve(self.root, self.package, self.plan, 'youtube', '@right', now=self.now)['status'],
                         'awaiting_review')
        self.plan['targets']['youtube']['approval'] = approval
        self.assertEqual(reserve(self.root, self.package, self.plan, 'youtube', '@other', now=self.now)['status'],
                         'login_required')
        closing = datetime(2026, 11, 22, 19, tzinfo=timezone.utc)
        self.assertEqual(reserve(self.root, self.package, self.plan, 'youtube', '@right', now=closing)['status'],
                         'outside_window')
        self.video.write_bytes(b'replaced')
        self.assertEqual(reserve(self.root, self.package, self.plan, 'youtube', '@right', now=self.now)['status'],
                         'quality_blocked')

    def test_unknown_is_reconciled_and_cannot_upload_twice(self):
        with patch('browser_receipt.check_media'):
            first = reserve(self.root, self.package, self.plan, 'youtube', '@right', now=self.now)
            self.assertEqual(first['status'], 'ready_to_publish')
            self.assertEqual(reserve(self.root, self.package, self.plan, 'youtube', '@right', now=self.now)['status'],
                             'submitted_unverified')
            retry = reserve(self.root, self.package, self.plan, 'youtube', '@right', verified_absent=True, now=self.now)
            self.assertTrue(retry['retried'])
            repeated = reserve(self.root, self.package, self.plan, 'youtube', '@right', verified_absent=True, now=self.now)
            self.assertEqual(repeated['status'], 'submitted_unverified')
            record(Path(retry['receipt']), 'youtube', {'status': 'published', 'post_url': 'https://youtu.be/abcdefghijk',
                   'published_at': '2026-11-22T18:00:00Z', 'portrait': True, 'sound': True, 'subject_visible': True})
            self.assertEqual(reserve(self.root, self.package, self.plan, 'youtube', '@right', now=self.now)['status'],
                             'published')
