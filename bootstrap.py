"""First installation and safe fast-forward toolkit updates are automatic."""
from __future__ import annotations
import argparse
import json
import re
import os
import subprocess
import sys
import venv
import platform
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'https://github.com/yaoyingyunlian-create/thinknova-mcp.git'
GITEE_REPOSITORY = 'https://gitee.com/zhongjianghua_admin/thinknova-mcp.git'
TRUSTED_ORIGINS = (REPOSITORY, 'git@github.com:yaoyingyunlian-create/thinknova-mcp.git', GITEE_REPOSITORY)
SETUP_PHASE = 'not_started'


def refresh_path():
    if os.name == 'nt':
        import winreg
        paths = [os.environ.get('PATH', '')]
        for hive, key in ((winreg.HKEY_CURRENT_USER, 'Environment'), (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    paths.append(os.path.expandvars(winreg.QueryValueEx(handle, 'Path')[0]))
            except OSError: pass
        paths.append(str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/WinGet/Links'))
        os.environ['PATH'] = os.pathsep.join(paths)


def install_missing(name):
    """Use the host's existing package manager; never download an unofficial installer."""
    system = platform.system()
    if system == 'Windows' and shutil.which('winget'):
        package = {'git': 'Git.Git', 'node': 'OpenJS.NodeJS.LTS', 'ffmpeg': 'Gyan.FFmpeg'}[name]
        command = ['winget', 'install', '--exact', '--id', package, '--silent', '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity']
    elif system == 'Darwin' and shutil.which('brew'):
        command = ['brew', 'install', {'git': 'git', 'node': 'node', 'ffmpeg': 'ffmpeg'}[name]]
    elif system == 'Linux' and shutil.which('apt-get'):
        prefix = [] if os.geteuid() == 0 else ['sudo', '-n']
        subprocess.run(prefix + ['apt-get', 'update'], check=True, timeout=300)
        command = prefix + ['apt-get', 'install', '-y', {'git': 'git', 'node': 'nodejs', 'ffmpeg': 'ffmpeg'}[name]]
    elif system == 'Linux' and shutil.which('dnf'):
        command = ([] if os.geteuid() == 0 else ['sudo', '-n']) + ['dnf', 'install', '-y', name if name != 'node' else 'nodejs']
    elif system == 'Darwin':
        raise RuntimeError('DEPENDENCY_REPAIR_UNAVAILABLE: missing %s; first install Homebrew from https://brew.sh, then rerun python3 bootstrap.py setup / 请先按 Homebrew 官网说明安装，再重新运行 setup。' % name)
    else:
        raise RuntimeError('DEPENDENCY_REPAIR_UNAVAILABLE: missing %s; no supported package manager (winget, brew, apt-get, dnf). Install a package manager or grant installation permission, then rerun setup.' % name)
    result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=600)
    refresh_path()
    if result.returncode:
        raise RuntimeError('DEPENDENCY_REPAIR_FAILED: %s; command=%s; exit=%s; details=%s' % (name, command, result.returncode, (result.stderr or result.stdout)[-2000:]))


def repair_runtime():
    refresh_path()
    for name in ('git', 'node', 'ffmpeg'):
        missing = shutil.which(name) is None
        if name == 'ffmpeg': missing = missing or shutil.which('ffprobe') is None
        if name == 'node' and not missing:
            version = subprocess.check_output(['node', '--version'], text=True).strip()
            missing = int(version.lstrip('v').split('.')[0]) < 18
        if missing:
            print('Repairing missing or outdated dependency: ' + name)
            try: install_missing(name)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                if name != 'node': raise
                print('OPTIONAL_DEPENDENCY_PENDING: node; core media workflows do not require Node.js. Install it before workflows that do.', file=sys.stderr)
                continue
        if shutil.which(name) is None or (name == 'ffmpeg' and shutil.which('ffprobe') is None):
            raise RuntimeError('DEPENDENCY_REPAIR_NOT_EFFECTIVE: %s still unavailable after installation; check package-manager output and PATH.' % name)


def repair_files():
    """Restore only missing tracked files at the INSTALLED commit; preserve edits and user data."""
    paths = git('ls-files', '-z').split('\0')
    missing = [name for name in paths if name and not (ROOT / name).exists()]
    if missing:
        git('restore', '--source=HEAD', '--worktree', '--', *missing)
        print('Restored missing toolkit files: ' + ', '.join(missing))


def git(*args, timeout=60):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=ROOT,
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if result.returncode: raise RuntimeError(result.stderr.strip() or 'Git command failed; update status unknown.')
    return result.stdout.rstrip('\r\n')


def check():
    origin = git('remote', 'get-url', 'origin')
    if origin not in TRUSTED_ORIGINS:
        raise RuntimeError('Unexpected toolkit remote; no update was applied.')
    current = git('rev-parse', 'HEAD')
    for repository in (REPOSITORY, GITEE_REPOSITORY):
        try:
            remote = git('ls-remote', '--exit-code', repository, 'refs/heads/main', timeout=12).split()
        except (RuntimeError, subprocess.TimeoutExpired):
            continue
        if len(remote) != 2 or remote[1] != 'refs/heads/main' or not re.fullmatch(r'[0-9a-f]{40}', remote[0]):
            continue
        result = {'installed_commit': current, 'latest_commit': remote[0], 'update_available': current != remote[0],
                  'source': repository, 'github_verified': repository == REPOSITORY}
        print(json.dumps(result))
        return result
    raise RuntimeError('GitHub and Gitee main branches are unavailable; update status unknown.')


def update_blockers():
    # NUL-separated status keeps whitespace and Unicode filenames intact.
    return [entry for entry in git('status', '--porcelain', '-z', '--untracked-files=all').split('\0')
            if entry and entry != '?? AGENTS.local.md']


def prepare_legacy_update():
    if git('ls-files', '--', 'AGENTS.local.md'):
        raise RuntimeError('AGENTS.local.md is tracked; preserve the source change manually before updating.')
    exclude = Path(git('rev-parse', '--git-path', 'info/exclude'))
    if not exclude.is_absolute(): exclude = ROOT / exclude
    previous = exclude.read_text(encoding='utf-8') if exclude.exists() else ''
    if '/AGENTS.local.md' not in previous.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(('\n' if previous and not previous.endswith('\n') else '') + '/AGENTS.local.md\n')
    print('Local instructions preserved. Run update to apply available changes automatically. 本地规矩已保留，运行update自动更新。')


def update(confirmed=False, *, quiet=False):
    status = check()
    if not status['update_available']: return status
    changes = update_blockers()
    if changes: raise RuntimeError('Local source changes detected; preserve these files before updating / 请先保留以下文件修改:\n' + '\n'.join(changes))
    source = status['source']
    git('fetch', source, 'refs/heads/main')
    if git('rev-parse', 'FETCH_HEAD') != status['latest_commit']:
        raise RuntimeError('Toolkit remote changed while fetching; check the version again.')
    # An older mirror or divergent source may not replace the installed release.
    try:
        git('merge-base', '--is-ancestor', status['installed_commit'], status['latest_commit'])
    except RuntimeError as exc:
        raise RuntimeError('Toolkit source is older or divergent; update status unknown.') from exc
    git('merge', '--ff-only', status['latest_commit'])
    # The running module still contains OLD code after merge. Start the updated entrypoint.
    subprocess.run([sys.executable, str(ROOT / 'bootstrap.py'), 'setup'], check=True,
                   **({'stdout': sys.stderr} if quiet else {}))
    return status


def write_workspace_json(path, report):
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, ensure_ascii=False)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def workspace_runtime(root, repair=False):
    python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    try:
        check_args = [str(python), str(root / 'toolkit.py'), 'doctor']
        if python.is_file() and subprocess.run(check_args, stdout=sys.stderr, timeout=100).returncode == 0:
            return str(python)
        if repair:
            subprocess.run([sys.executable, str(root / 'bootstrap.py'), 'setup'], check=True,
                           stdout=sys.stderr, timeout=1800)
            return str(python)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def workspace_update(workspace):
    import contextlib
    try:
        with contextlib.redirect_stdout(sys.stderr):
            remote = update(quiet=True)
        python = workspace_runtime(ROOT, repair=not remote['update_available'])
        if python:
            return {'status': 'ready', 'version_status': 'current', 'active_toolkit': str(ROOT),
                    'python': python, 'recovery': 'fast_forward' if remote['update_available'] else 'current'}
    except (RuntimeError, OSError, subprocess.SubprocessError):
        pass
    return recovery_report(workspace)


def preserve_customer_state(source, candidate):
    from file_integrity import sha256

    paths = [source / name for name in (
        'memory.md', 'reminders.txt', 'AGENTS.local.md', 'video-content-rules.md',
        'memory_archive', 'publication_history.json', 'publication_attempts', 'analytics_targets.json',
    )]
    for platform in (source / 'publish').glob('*'):
        if platform.is_dir():
            paths.extend(platform / name for name in ('_profile', 'token.json', 'oauth_client.json'))
    for item in paths:
        if not item.exists() and not item.is_symlink():
            continue
        files = [item, *item.rglob('*')] if item.is_dir() else [item]
        for original in files:
            relative = original.relative_to(source)
            if original.is_symlink() or getattr(original, 'is_junction', lambda: False)():
                raise RuntimeError(f'TOOLKIT_CUSTOMER_STATE_LINK: {relative}')
            destination = candidate / relative
            if original.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not original.is_file() or destination.exists():
                raise RuntimeError(f'TOOLKIT_CUSTOMER_STATE_CONFLICT: {relative}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
            if sha256(original) != sha256(destination):
                raise RuntimeError(f'TOOLKIT_CUSTOMER_STATE_COPY_FAILED: {relative}')


def remove_failed_candidate(candidate, parent):
    import stat

    if (candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)()
            or candidate.resolve().parent != parent or not candidate.name.startswith('tn-')
            or not (candidate / '.tn-recovery-failed').is_file()):
        raise OSError('Unsafe recovery cleanup target')

    def retry_readonly(operation, filename, error):
        path = Path(filename)
        if (os.name != 'nt' or not isinstance(error[1], PermissionError)
                or candidate not in path.resolve().parents or path.is_symlink() or not path.is_file()):
            raise error[1]
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
        operation(filename)

    shutil.rmtree(candidate, onerror=retry_readonly)


def recovery_report(workspace):
    import tempfile
    from file_integrity import manifest_mismatches

    def failures(root):
        try:
            return manifest_mismatches(root, json.loads((root / 'manifest.json').read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError, KeyError):
            return ['manifest.json']

    report = {'status': 'blocked', 'version_status': 'unknown', 'active_toolkit': None}
    mismatches = failures(ROOT)
    report['missing'] = [name for name in mismatches if not (ROOT / name).is_file()]
    report['integrity_mismatches'] = mismatches
    try:
        changed = git('diff', 'HEAD', '--name-only', '-z').split('\0')
        substantive = set(git('diff', 'HEAD', '--ignore-cr-at-eol', '--name-only', '-z').split('\0'))
        report['source_changes'] = sorted(substantive - {''} - set(report['missing']))
        report['line_ending_changes'] = [name for name in changed if name and name not in substantive]
    except (OSError, RuntimeError, subprocess.SubprocessError):
        report['git_status'] = 'unknown'
    try:
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            remote = check()
        report['version_status'] = 'update_available' if remote['update_available'] else 'current'
    except (OSError, RuntimeError, subprocess.SubprocessError):
        remote = None

    if not mismatches and not (remote and remote['update_available']):
        python = workspace_runtime(ROOT, repair=True)
        if python:
            return {**report, 'status': 'ready', 'active_toolkit': str(ROOT), 'python': python}
        return {**report, 'error': 'TOOLKIT_LOCAL_RUNTIME_NOT_READY'}

    if remote:
        candidate = None
        candidate_parent = (Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'tn-kit').resolve()
        try:
            candidate_parent.mkdir(parents=True, exist_ok=True)
            for abandoned in candidate_parent.glob('tn-*'):
                if (abandoned / '.tn-recovery-failed').is_file():
                    try:
                        remove_failed_candidate(abandoned, candidate_parent)
                    except OSError:
                        report['candidate_cleanup'] = 'failed'
            workspace.mkdir(parents=True, exist_ok=True)
            candidate = Path(tempfile.mkdtemp(prefix='tn-', dir=candidate_parent))
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
            subprocess.run(['git', '-c', 'core.autocrlf=false', 'clone', '--branch', 'main', '--single-branch',
                            remote['source'], str(candidate)], env=env, capture_output=True, check=True, timeout=120)
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=candidate, timeout=15).decode().strip()
            if head != remote['latest_commit'] or failures(candidate):
                raise RuntimeError('TOOLKIT_CANDIDATE_INTEGRITY_FAILED')
            setup_result = subprocess.run([sys.executable, str(candidate / 'bootstrap.py'), 'setup', '--json'],
                                          capture_output=True, timeout=1800)
            if setup_result.returncode:
                detail = (setup_result.stderr or b'').decode('utf-8', errors='replace').lower()
                report['setup_failure'] = 'WINDOWS_PATH_TOO_LONG' if any(x in detail for x in ('winerror 206', 'long path', 'filename or extension is too long')) else 'TOOLKIT_CANDIDATE_SETUP_FAILED'
                raise RuntimeError(report['setup_failure'])
            if failures(candidate):
                raise RuntimeError('TOOLKIT_CANDIDATE_SETUP_FAILED')
            memory = candidate / 'memory.md'
            template = candidate / 'memory.template.md'
            if ((ROOT / 'memory.md').is_file() and memory.is_file() and template.is_file()
                    and memory.read_bytes() == template.read_bytes()):
                memory.unlink()
            preserve_customer_state(ROOT, candidate)
            if failures(candidate):
                raise RuntimeError('TOOLKIT_CANDIDATE_INTEGRITY_FAILED')
            python = workspace_runtime(candidate)
            if not python:
                raise RuntimeError('TOOLKIT_LOCAL_RUNTIME_NOT_READY')
            write_workspace_json(workspace / '.thinknova-toolkit.json',
                                 {'toolkit': str(candidate), 'commit': head, 'python': python})
            return {**report, 'status': 'ready', 'active_toolkit': str(candidate), 'version_status': 'current',
                    'recovery': 'clean_copy', 'python': python}
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            report['recovery'] = 'clean_copy_failed'
            reason = str(exc)
            if reason.startswith('TOOLKIT_CUSTOMER_STATE_'):
                report['state_failure'] = reason
            if candidate and candidate.resolve().parent == candidate_parent and candidate.name.startswith('tn-'):
                try:
                    (candidate / '.tn-recovery-failed').touch()
                    remove_failed_candidate(candidate, candidate_parent)
                except OSError:
                    report['candidate_cleanup'] = 'failed'
    if not mismatches:
        python = workspace_runtime(ROOT)
        if python:
            return {**report, 'status': 'ready', 'active_toolkit': str(ROOT), 'python': python}
        return {**report, 'error': 'TOOLKIT_LOCAL_RUNTIME_NOT_READY'}
    report['error'] = 'TOOLKIT_INTEGRITY_RECOVERY_REQUIRED'
    return report


def setup(json_output=False):
    global SETUP_PHASE
    SETUP_PHASE = 'python'
    if sys.version_info < (3, 10):
        raise RuntimeError('PYTHON_TOO_OLD: use install.ps1 on Windows or install.sh on macOS/Linux to automatically install Python 3.10+ and resume setup.')
    SETUP_PHASE = 'runtime_dependencies'; repair_runtime()
    SETUP_PHASE = 'tracked_files'; repair_files()
    def run(phase, command):
        global SETUP_PHASE
        SETUP_PHASE = phase
        subprocess.run(command, check=True, stdout=sys.stderr if json_output else None)
    # Verify all shipped files before running dependency installation.
    run('integrity', [sys.executable, str(ROOT / 'toolkit.py'), 'verify'])
    environment = ROOT / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    SETUP_PHASE = 'virtual_environment'
    if not python.exists(): venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    run('python_dependencies', [str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')])
    run('memory_init', [str(python), str(ROOT / 'toolkit.py'), 'init'])
    run('memory_migration', [str(python), str(ROOT / 'toolkit.py'), 'migrate-memory'])
    print('Ego Lite belongs to the customer AI assistant publishing workflow; video setup does not install a browser. / 视频制作安装不安装发布浏览器。', file=sys.stderr)
    run('local_runtime_check', [str(python), str(ROOT / 'toolkit.py'), 'doctor'])
    SETUP_PHASE = 'complete'
    print('Video setup completed; check ThinkNova access and rules. Publishing uses the customer AI assistant and Ego Lite. 本机制作准备完成；发布使用客户AI助理与Ego Lite。')


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='recover checks the official version, prepares a verified short-path copy when needed, preserves customer state, then updates the workspace pointer.')
    parser.add_argument('command', choices=['setup', 'repair', 'check', 'update', 'prepare-update', 'recover'])
    parser.add_argument('--workspace', type=Path, help='Customer workspace for automatic recovery if updating is blocked')
    parser.add_argument('--user-confirmed', action='store_true')
    parser.add_argument('--json', action='store_true', help='Emit a structured setup result; installation logs go to stderr')
    args = parser.parse_args()
    try:
        if args.command in ('setup', 'repair'):
            import contextlib
            try:
                with contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext(): setup(json_output=args.json)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                if not args.json: raise
                print(json.dumps({'schema_version': 1, 'overall': 'blocked', 'local_ready': False, 'failed_stage': SETUP_PHASE, 'failure': type(exc).__name__, 'error_code': str(exc).split(':',1)[0] if re.fullmatch('[A-Z0-9_]{1,64}',str(exc).split(':',1)[0]) else 'LOCAL_SETUP_FAILED', 'remedy': 'Resolve the failed stage shown in stderr; rerun setup. 请修复失败阶段后重试。'}))
                return 2
            if args.json:
                python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
                subprocess.run([str(python), str(ROOT / 'health.py'), '--json'], check=True)
        elif args.command == 'recover' or (args.command == 'update' and args.workspace is not None):
            workspace = (args.workspace or Path.cwd()).resolve()
            report = recovery_report(workspace) if args.command == 'recover' else workspace_update(workspace)
            if report['status'] == 'blocked':
                write_workspace_json(workspace / 'thinknova-recovery.json', report)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report['status'] == 'ready' else 2
        elif args.command == 'check': check()
        elif args.command == 'prepare-update': prepare_legacy_update()
        else: update(args.user_confirmed)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
