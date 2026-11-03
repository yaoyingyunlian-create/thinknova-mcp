"""First installation is automatic. Existing installations update only after confirmation."""
from __future__ import annotations
import argparse
import json
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
            install_missing(name)
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
    return result.stdout.strip()


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


def update(confirmed=False):
    status = check()
    if not status['update_available']: return
    if not confirmed: raise RuntimeError('Update available. Ask the user, then rerun update --user-confirmed.')
    if git('status', '--porcelain'): raise RuntimeError('Local source changes detected; preserve them before updating.')
    git('fetch', 'origin', 'main')
    git('merge', '--ff-only', status['latest_commit'])
    # The running module still contains OLD code after merge. Start the updated entrypoint.
    subprocess.run([sys.executable, str(ROOT / 'bootstrap.py'), 'setup'], check=True)


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
    run('local_runtime_check', [str(python), str(ROOT / 'toolkit.py'), 'doctor'])
    SETUP_PHASE = 'complete'
    print('Local setup completed; verify MCP account, rules and platform authorization separately. 本机准备完成，账户、规则和平台授权仍需核实。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'repair', 'check', 'update'])
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
                print(json.dumps({'schema_version': 1, 'overall': 'blocked', 'local_ready': False, 'failed_stage': SETUP_PHASE, 'failure': type(exc).__name__, 'remedy': 'Resolve the failed stage shown in stderr; rerun setup. 请修复失败阶段后重试。'}))
                return 2
            if args.json:
                python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
                subprocess.run([str(python), str(ROOT / 'health.py'), '--json'], check=True)
        elif args.command == 'check': check()
        else: update(args.user_confirmed)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
