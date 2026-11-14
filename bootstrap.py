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


def git(*args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=ROOT,
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
    if result.returncode: raise RuntimeError(result.stderr.strip() or 'Git command failed; update status unknown.')
    return result.stdout.rstrip('\r\n')


def check():
    origin = git('remote', 'get-url', 'origin')
    if origin not in (REPOSITORY, 'git@github.com:yaoyingyunlian-create/thinknova-mcp.git'):
        raise RuntimeError('Unexpected toolkit remote; no update was applied.')
    current = git('rev-parse', 'HEAD')
    remote = git('ls-remote', REPOSITORY, 'refs/heads/main').split()
    if not remote: raise RuntimeError('GitHub main branch unavailable; update status unknown.')
    result = {'installed_commit': current, 'latest_commit': remote[0], 'update_available': current != remote[0]}
    print(json.dumps(result))
    return result


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


def update(confirmed=False):
    status = check()
    if not status['update_available']: return
    changes = update_blockers()
    if changes: raise RuntimeError('Local source changes detected; preserve these files before updating / 请先保留以下文件修改:\n' + '\n'.join(changes))
    git('fetch', 'origin', 'main')
    git('merge', '--ff-only', status['latest_commit'])
    # The running module still contains OLD code after merge. Start the updated entrypoint.
    subprocess.run([sys.executable, str(ROOT / 'bootstrap.py'), 'setup'], check=True)


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
        return {**report, 'status': 'ready', 'active_toolkit': str(ROOT)}

    if remote:
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            candidate = Path(tempfile.mkdtemp(prefix='thinknova-toolkit-', dir=ROOT.parent))
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
            subprocess.run(['git', '-c', 'core.autocrlf=false', 'clone', '--branch', 'main', '--single-branch',
                            REPOSITORY, str(candidate)], env=env, capture_output=True, check=True, timeout=120)
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=candidate, timeout=15).decode().strip()
            if head != remote['latest_commit'] or failures(candidate):
                raise RuntimeError('TOOLKIT_CANDIDATE_INTEGRITY_FAILED')
            setup_result = subprocess.run([sys.executable, str(candidate / 'bootstrap.py'), 'setup', '--json'],
                                          capture_output=True, timeout=1800)
            if setup_result.returncode or failures(candidate):
                raise RuntimeError('TOOLKIT_CANDIDATE_SETUP_FAILED')
            from automation import atomic
            atomic(workspace / '.thinknova-toolkit.json', {'toolkit': str(candidate), 'commit': head})
            return {**report, 'status': 'ready', 'active_toolkit': str(candidate), 'version_status': 'current',
                    'recovery': 'clean_copy'}
        except (OSError, RuntimeError, subprocess.SubprocessError):
            report['recovery'] = 'clean_copy_failed'
    if not mismatches:
        return {**report, 'status': 'ready', 'active_toolkit': str(ROOT)}
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
    run('chromium_install', [str(python), '-m', 'playwright', 'install', 'chromium'])
    run('memory_init', [str(python), str(ROOT / 'toolkit.py'), 'init'])
    run('memory_migration', [str(python), str(ROOT / 'toolkit.py'), 'migrate-memory'])
    SETUP_PHASE = 'ego_browser'; refresh_path()
    import ego_runtime
    if platform.system() == 'Windows':
        try: ego_runtime.prepare()
        except RuntimeError as exc:
            print('AI_BROWSER_PENDING: ego lite requires installation/onboarding; core preparation continues. ' + str(exc), file=sys.stderr)
    elif shutil.which('ego-browser'):
        try: ego_runtime.prepare()
        except RuntimeError: print('AI_BROWSER_PENDING: complete ego lite onboarding separately.', file=sys.stderr)
    else:
        print('AI_BROWSER_NOT_CONFIGURED: optional for API/script workflows; required for ego browser work. / 非 ego 工作流不受阻塞。', file=sys.stderr)
    run('local_runtime_check', [str(python), str(ROOT / 'toolkit.py'), 'doctor'])
    SETUP_PHASE = 'complete'
    print('Local setup completed; verify MCP account, rules and platform authorization separately. 本机准备完成，账户、规则和平台授权仍需核实。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
        elif args.command == 'recover':
            from automation import atomic
            workspace = (args.workspace or Path.cwd()).resolve()
            report = recovery_report(workspace)
            if report['status'] == 'blocked':
                atomic(workspace / 'thinknova-recovery.json', report)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report['status'] == 'ready' else 2
        elif args.command == 'check': check()
        elif args.command == 'prepare-update': prepare_legacy_update()
        else:
            try:
                update(args.user_confirmed)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                if args.workspace is None:
                    raise
                report = recovery_report(args.workspace.resolve())
                if report['status'] == 'blocked':
                    from automation import atomic
                    atomic(args.workspace.resolve() / 'thinknova-recovery.json', report)
                print(json.dumps(report, ensure_ascii=False))
                return 0 if report['status'] == 'ready' else 2
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
