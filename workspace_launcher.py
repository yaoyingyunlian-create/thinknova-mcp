# ThinkNova managed workspace launcher
"""Update and dispatch local toolkit commands from the customer workspace."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def install(workspace, root):
    target = workspace / '.thinknova-run.py'
    source = root / 'workspace_launcher.py'
    content = source.read_bytes()
    workspace.mkdir(parents=True, exist_ok=True)
    if target.exists():
        previous = target.read_bytes()
        if previous == content:
            return target
        if previous.splitlines()[:1] != [b'# ThinkNova managed workspace launcher']:
            raise RuntimeError('TOOLKIT_LAUNCHER_CONFLICT: preserve the existing .thinknova-run.py')
    with tempfile.NamedTemporaryFile(dir=workspace, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def active_install(workspace):
    pointer = json.loads((workspace / '.thinknova-toolkit.json').read_text(encoding='utf-8'))
    root = Path(pointer['toolkit'])
    if not root.is_absolute() or not (root / 'bootstrap.py').is_file():
        raise RuntimeError('TOOLKIT_ACTIVE_INSTALL_MISSING: rerun bootstrap.py update --workspace')
    return root.resolve()


def dispatch(workspace, arguments):
    root = active_install(workspace)
    report_process = subprocess.run(
        [sys.executable, str(root / 'bootstrap.py'), 'update', '--workspace', str(workspace), '--json'],
        cwd=workspace, stdout=subprocess.PIPE, encoding='utf-8',
    )
    report = json.loads(report_process.stdout or '{}')
    if report_process.returncode or report.get('status') != 'ready':
        raise RuntimeError(report.get('error') or 'TOOLKIT_UPDATE_FAILED: see the update diagnostics')
    active = Path(report['active_toolkit'])
    python = Path(report['python'])
    if not active.is_absolute() or not python.is_absolute() or not python.is_file() or not (active / 'toolkit.py').is_file():
        raise RuntimeError('TOOLKIT_ACTIVE_RUNTIME_INVALID')
    print(f'ThinkNova toolkit: {active} ({report.get("version_status", "unknown")})', file=sys.stderr)
    if arguments == ['check-update']:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if report.get('version_status') == 'update_available':
        raise RuntimeError('TOOLKIT_UPDATE_REQUIRED: the newer release could not be activated')
    return subprocess.run([str(python), str(active / 'toolkit.py'), *arguments], cwd=workspace).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__, usage='%(prog)s check-update | TOOLKIT_COMMAND [ARGS ...]')
    if len(sys.argv) == 1 or sys.argv[1] in ('-h', '--help'):
        parser.print_help()
        return 0
    try:
        return dispatch(Path(__file__).resolve().parent, sys.argv[1:])
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
