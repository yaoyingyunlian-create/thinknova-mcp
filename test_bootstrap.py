"""Offline installation/update regressions. No installs, accounts or publishing."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bootstrap
import toolkit


class BootstrapTests(unittest.TestCase):
    def test_missing_runtime_is_repaired(self):
        available = {'git': '/git', 'node': '/node', 'ffmpeg': None, 'ffprobe': None}
        def install(name):
            self.assertEqual(name, 'ffmpeg')
            available['ffmpeg'] = '/ffmpeg'; available['ffprobe'] = '/ffprobe'
        with patch.object(bootstrap, 'refresh_path'), patch.object(bootstrap.shutil, 'which', side_effect=lambda name: available.get(name)), patch.object(bootstrap.subprocess, 'check_output', return_value='v22.0.0'), patch.object(bootstrap, 'install_missing', side_effect=install) as repair:
            bootstrap.repair_runtime()
            repair.assert_called_once_with('ffmpeg')

    def test_failed_runtime_repair_never_reports_ready(self):
        with patch.object(bootstrap, 'refresh_path'), patch.object(bootstrap.shutil, 'which', return_value=None), patch.object(bootstrap, 'install_missing'):
            with self.assertRaisesRegex(RuntimeError, 'REPAIR_NOT_EFFECTIVE'):
                bootstrap.repair_runtime()

    def test_restore_only_missing_tracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'AGENTS.md').write_text('customer edits', encoding='utf-8')
            with patch.object(bootstrap, 'ROOT', root), patch.object(bootstrap, 'git', side_effect=['AGENTS.md\0missing.py', '']) as git:
                bootstrap.repair_files()
                self.assertEqual(git.call_args_list[-1].args, ('restore', '--source=HEAD', '--worktree', '--', 'missing.py'))
                self.assertEqual((root / 'AGENTS.md').read_text(encoding='utf-8'), 'customer edits')

    def test_update_requires_confirmation(self):
        with patch.object(bootstrap, 'check', return_value={'update_available': True}), patch.object(bootstrap, 'git') as git:
            with self.assertRaisesRegex(RuntimeError, 'Ask the user'):
                bootstrap.update(False)
            git.assert_not_called()

    def test_local_changes_block_update(self):
        with patch.object(bootstrap, 'check', return_value={'update_available': True}), patch.object(bootstrap, 'git', return_value=' M AGENTS.md') as git:
            with self.assertRaisesRegex(RuntimeError, 'Local source changes'):
                bootstrap.update(True)
            self.assertEqual(git.call_count, 1)

    def test_confirmed_update_fast_forwards(self):
        with patch.object(bootstrap, 'check', return_value={'update_available': True, 'latest_commit': 'abc'}), patch.object(bootstrap, 'git', return_value='') as git, patch.object(bootstrap, 'setup') as setup:
            bootstrap.update(True)
            self.assertEqual(git.call_args_list[-1].args, ('merge', '--ff-only', 'abc'))
            setup.assert_called_once()

    def test_network_failure_is_not_latest(self):
        with patch.object(bootstrap, 'git', side_effect=[bootstrap.REPOSITORY, 'abc', RuntimeError('offline')]):
            with self.assertRaisesRegex(RuntimeError, 'offline'): bootstrap.check()

    def test_first_init_preserves_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / 'memory.md'
            with patch.object(toolkit, 'MEMORY', memory):
                toolkit.init()
                memory.write_text('Customer memory', encoding='utf-8')
                toolkit.init()
                self.assertEqual(memory.read_text(encoding='utf-8'), 'Customer memory')


if __name__ == '__main__': unittest.main()
