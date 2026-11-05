"""Offline installation/update regressions. No installs, accounts or publishing."""
import tempfile
import subprocess
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

    def test_update_without_confirmation_fast_forwards(self):
        with patch.object(bootstrap, 'check', return_value={'update_available': True, 'latest_commit': 'abc'}), patch.object(bootstrap, 'git', return_value='') as git, patch.object(bootstrap.subprocess, 'run') as setup:
            bootstrap.update(False)
            self.assertEqual(git.call_args_list[-1].args, ('merge', '--ff-only', 'abc'))
            setup.assert_called_once()

    def test_local_changes_block_update(self):
        with patch.object(bootstrap, 'check', return_value={'update_available': True}), patch.object(bootstrap, 'git', return_value=' M AGENTS.md') as git:
            with self.assertRaisesRegex(RuntimeError, 'Local source changes'):
                bootstrap.update(True)
            self.assertEqual(git.call_count, 1)

    def test_confirmed_update_fast_forwards(self):
        with patch.object(bootstrap, 'check', return_value={'update_available': True, 'latest_commit': 'abc'}), patch.object(bootstrap, 'git', return_value='') as git, patch.object(bootstrap.subprocess, 'run') as fresh_setup:
            bootstrap.update(True)
            self.assertEqual(git.call_args_list[-1].args, ('merge', '--ff-only', 'abc'))
            fresh_setup.assert_called_once_with([bootstrap.sys.executable, str(bootstrap.ROOT / 'bootstrap.py'), 'setup'], check=True)

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


class RealGitUpdateTests(unittest.TestCase):
    def test_local_instructions_and_source_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def run(*args):
                return subprocess.check_output(['git', *args], cwd=root).decode('utf-8').strip()
            run('init', '-q'); run('config', 'user.name', 'Fixture'); run('config', 'user.email', 'fixture@example.invalid')
            (root / 'source.txt').write_text('original', encoding='utf-8')
            run('add', 'source.txt'); run('commit', '-qm', 'fixture')
            local = root / 'AGENTS.local.md'; local.write_text('客户规矩', encoding='utf-8')
            exclude = root / '.git/info/exclude'
            before = exclude.read_text(encoding='utf-8')
            with patch.object(bootstrap, 'ROOT', root):
                self.assertEqual(bootstrap.update_blockers(), [])
                self.assertIn('?? AGENTS.local.md', run('status', '--porcelain'))
                bootstrap.prepare_legacy_update(); bootstrap.prepare_legacy_update()
                self.assertEqual(run('status', '--porcelain'), '')
                self.assertTrue(exclude.read_text(encoding='utf-8').startswith(before))
                self.assertEqual(exclude.read_text(encoding='utf-8').count('/AGENTS.local.md'), 1)
                self.assertEqual(local.read_text(encoding='utf-8'), '客户规矩')
                (root / 'source.txt').write_text('customer change', encoding='utf-8')
                (root / '客户 文件.txt').write_text('keep', encoding='utf-8')
                blockers = bootstrap.update_blockers()
                self.assertTrue(any('source.txt' in entry for entry in blockers))
                self.assertTrue(any('客户 文件.txt' in entry for entry in blockers))
                with patch.object(bootstrap, 'check', return_value={'update_available': True}):
                    with self.assertRaisesRegex(RuntimeError, 'source.txt'): bootstrap.update(True)
                run('add', '-f', 'AGENTS.local.md'); run('commit', '-qm', 'tracked-local')
                with self.assertRaisesRegex(RuntimeError, 'tracked'): bootstrap.prepare_legacy_update()
                local.write_text('tracked change', encoding='utf-8')
                self.assertTrue(any('AGENTS.local.md' in entry for entry in bootstrap.update_blockers()))


class RealGitFastForwardTests(unittest.TestCase):
    def test_update_preserves_customer_state_and_restarts_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); upstream = parent / 'upstream'; upstream.mkdir()
            def run(cwd, *args):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
            run(upstream, 'init', '-q', '-b', 'main'); run(upstream, 'config', 'user.name', 'Fixture'); run(upstream, 'config', 'user.email', 'fixture@example.invalid')
            (upstream / 'source.txt').write_text('old', encoding='utf-8')
            run(upstream, 'add', '.'); run(upstream, 'commit', '-qm', 'initial')
            customer = parent / 'customer'; run(parent, 'clone', '-q', str(upstream), str(customer))
            (customer / 'AGENTS.local.md').write_text('preserve customer', encoding='utf-8')
            (upstream / 'source.txt').write_text('new', encoding='utf-8'); run(upstream, 'add', 'source.txt'); run(upstream, 'commit', '-qm', 'update')
            latest = run(upstream, 'rev-parse', 'HEAD')
            original = subprocess.run
            with patch.object(bootstrap, 'ROOT', customer), patch.object(bootstrap, 'check', return_value={'update_available':True, 'latest_commit':latest}), patch.object(bootstrap.subprocess, 'run', wraps=subprocess.run) as processes:
                # Mock only setup, leaving every Git operation real.
                def execute(command, **kwargs):
                    if command[0] == bootstrap.sys.executable: return subprocess.CompletedProcess(command, 0)
                    return original(command, **kwargs)
                processes.side_effect = execute
                bootstrap.update()
                self.assertEqual((customer / 'source.txt').read_text(encoding='utf-8'), 'new')
                self.assertEqual((customer / 'AGENTS.local.md').read_text(encoding='utf-8'), 'preserve customer')
                self.assertEqual(processes.call_args_list[-1].args[0], [bootstrap.sys.executable, str(customer / 'bootstrap.py'), 'setup'])


if __name__ == '__main__': unittest.main()
