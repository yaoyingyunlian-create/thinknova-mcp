"""Read-only installation diagnostics. No login, downloads, generation or publication."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from file_integrity import manifest_mismatches
import importlib.util
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def chromium_probe() -> bool:
    # Run out-of-process so a hung browser cannot hang the installation report.
    script = """from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        page = browser.new_page()
        page.set_content('<title>ThinkNova local check</title><p id="ok">ready</p>')
        assert page.locator('#ok').inner_text() == 'ready'
    finally:
        browser.close()
"""
    return subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=30).returncode == 0


def libass_probe():
    result = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
    return result.returncode == 0 and any(' ass ' in line for line in result.stdout.splitlines())


def font_probe():
    system = platform.system()
    if system == 'Windows':
        return any((Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / x).is_file() for x in ('msyh.ttc', 'msyh.ttf', 'simhei.ttf'))
    if system == 'Darwin':
        return any(Path(x).is_file() for x in ('/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Light.ttc'))
    if not shutil.which('fc-match'): return False
    result = subprocess.run(['fc-match', 'Noto Sans CJK SC', '-f', '%{family}'], capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and any(x in result.stdout for x in ('CJK', 'WenQuanYi', 'Source Han'))


def capabilities(checks):
    states = {c['name']: c['status'] for c in checks}
    def state(names):
        values = [states.get(name, 'unknown') for name in names]
        return 'fail' if 'fail' in values else ('pass' if all(x == 'pass' for x in values) else 'unknown')
    core = ['python', 'files', 'virtual_environment', 'git', 'ffmpeg', 'ffprobe', 'libass', 'cjk_font']
    return {'core_production': state(core),
            'browser_publishing': state(core + ['playwright', 'chromium_runtime']),
            'ai_browser': state(['ego_runtime']),
            'platform_authorization': state(['account', 'platform_authorization']),
            'automation': state(core + ['account', 'rules', 'platform_authorization', 'codex_login'])}


def verify_files(root: Path) -> bool:
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    return not manifest_mismatches(root, manifest)


def report(root: Path = ROOT, online: bool = False) -> dict:
    checks = []
    def check(name, action, remedy):
        try:
            ok = action()
            checks.append({'name': name, 'status': 'pass' if ok else 'fail', 'remedy': '' if ok else remedy})
        except (Exception, SystemExit):
            # Do not persist arbitrary subprocess messages, URLs or credentials.
            checks.append({'name': name, 'status': 'fail', 'remedy': remedy})
    check('python', lambda: sys.version_info >= (3, 10), 'Use Python 3.10+ / 请使用 Python 3.10+')
    check('files', lambda: verify_files(root), 'Run bootstrap.py repair; preserve local edits / 修复缺项并保留本地改动')
    check('virtual_environment', lambda: (root / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')).is_file(), 'Run bootstrap.py setup / 完成初始化')
    for binary in ('git', 'ffmpeg', 'ffprobe'):
        check(binary, lambda b=binary: shutil.which(b) is not None, 'Run bootstrap.py repair / 修复依赖')
    check('libass', libass_probe, 'Install an FFmpeg build with libass / 安装包含 libass 的 FFmpeg')
    check('cjk_font', font_probe, 'Install a licensed CJK font / 安装有授权的中文字体')
    check('node', lambda: int(subprocess.check_output(['node', '--version'], text=True, timeout=10).strip().lstrip('v').split('.')[0]) >= 18, 'Install Node.js 18+ / 安装 Node.js 18+')
    check('playwright', lambda: importlib.util.find_spec('playwright') is not None, 'Install requirements in .venv / 在虚拟环境安装依赖')
    check('chromium_runtime', chromium_probe, 'Run .venv Python -m playwright install chromium; inspect system restrictions / 检查浏览器安装和系统权限')
    import ego_runtime
    check('ego_runtime', ego_runtime.probe, 'Open ego lite and complete onboarding, then rerun bootstrap.py setup / 打开 ego lite 完成首次引导后重新检查')
    version = {'name': 'github_version', 'status': 'unknown', 'update_available': None, 'remedy': 'Run bootstrap.py check when online / 联网检查版本'}
    if online:
        try:
            import bootstrap
            current = bootstrap.git('rev-parse', 'HEAD')
            origin = bootstrap.git('remote', 'get-url', 'origin')
            if origin not in (bootstrap.REPOSITORY, 'git@github.com:yaoyingyunlian-create/thinknova-mcp.git'):
                raise ValueError('Unexpected source')
            remote = bootstrap.git('ls-remote', bootstrap.REPOSITORY, 'refs/heads/main').split()
            if not remote: raise ValueError('Unknown remote version')
            version.update(status='pass', installed_commit=current, latest_commit=remote[0], update_available=current != remote[0], remedy='')
        except (Exception, SystemExit): pass
    checks.append(version)
    from automation import daily_schedule_status
    schedule = daily_schedule_status()
    checks.append({'name': 'daily_schedules', 'status': schedule,
                   'remedy': '' if schedule in ('ready', 'unsupported') else
                   'Confirm the sample, authorize and pair the device, then run toolkit.py authorization --install-schedules / 确认样片、授权和配对后安装每日任务'})
    for name in ('account', 'rules', 'platform_authorization'):
        checks.append({'name': name, 'status': 'unknown', 'remedy': 'Check through authenticated MCP or platform flow / 通过授权接口核实'})
    readiness = capabilities(checks)
    local_ready = readiness['core_production'] == 'pass'
    return {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(), 'local_ready': local_ready,
            'capabilities': readiness, 'overall': 'partial' if local_ready else 'blocked', 'checks': checks}



def display(result: dict, as_json: bool = False):
    if as_json: print(json.dumps(result, ensure_ascii=False))
    else:
        for item in result['checks']: print(f"{item['status'].upper()} {item['name']}: {item.get('remedy', '')}")
        print('Local environment / 本机环境: ' + ('ready; account/platform still require verification' if result['local_ready'] else 'incomplete / 未完成'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true'); parser.add_argument('--online', action='store_true')
    args = parser.parse_args(); result = report(online=args.online); display(result, args.json)
    return 0 if result['local_ready'] else 2


if __name__ == '__main__': sys.exit(main())
