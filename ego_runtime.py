"""Official ego lite preparation. First-run GUI onboarding remains user controlled."""
from __future__ import annotations
import os
from pathlib import Path
import platform
import shutil
import subprocess
import urllib.request

WINDOWS_URL = 'https://cdn.ego.app/setup/windows/x64/egoliteSetup.exe'


def command():
    found = shutil.which('ego-browser')
    if found:
        return found
    # Onboarding updates PATH for future processes; refresh before calling this helper.
    return None


def probe():
    executable = command()
    if not executable:
        return False
    script = "const t=await taskSpace('ThinkNova local browser check');const p=t.page('p1');try{await p.goto('about:blank');const ok=await p.evaluate(()=>{document.body.textContent='ThinkNova ready';return document.body.textContent==='ThinkNova ready'});if(!ok)throw Error('EGO_PAGE_CHECK_FAILED')}finally{await t.finish({keep:[]})}"
    return subprocess.run([executable, 'nodejs', '-e', script], capture_output=True, timeout=45).returncode == 0


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        target = urlsplit(newurl)
        if target.scheme != 'https' or target.hostname != 'cdn.ego.app':
            raise RuntimeError('EGO_UNSAFE_DOWNLOAD_REDIRECT')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def prepare():
    if command():
        if not probe():
            raise RuntimeError('EGO_RUNTIME_FAILED: open ego lite, complete onboarding, then rerun setup / 请打开浏览器完成引导后重试')
        return
    # No undocumented silent-install switches or privilege elevation.
    if platform.system() != 'Windows' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('EGO_INSTALL_REQUIRED: install the matching build from https://lite.ego.app/download and complete onboarding / 请安装对应版本并完成引导')
    cache = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ThinkNova' / 'installers'
    cache.mkdir(parents=True, exist_ok=True)
    installer = cache / 'egoliteSetup.exe'
    marker = cache / 'ego-install-started'
    if marker.exists():
        raise RuntimeError('EGO_ONBOARDING_REQUIRED: finish the previously opened installer/onboarding, open a new terminal and rerun setup / 请完成安装与首次引导；若安装失败，检查后删除 ego-install-started 标记再重试')
    partial = installer.with_suffix('.download')
    try:
        with urllib.request.build_opener(OfficialRedirect()).open(WINDOWS_URL, timeout=60) as response, partial.open('wb') as stream:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 512 * 1024 * 1024:
                    raise RuntimeError('EGO_INSTALLER_TOO_LARGE')
                stream.write(chunk)
        with partial.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise RuntimeError('EGO_INSTALLER_INVALID')
        os.replace(partial, installer)
        # Require a trusted Authenticode signature before opening downloaded code.
        script = "$s=Get-AuthenticodeSignature -LiteralPath '" + str(installer).replace("'", "''") + "'; if($s.Status -ne 'Valid'){exit 1}"
        if subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, timeout=60).returncode:
            raise RuntimeError('EGO_INSTALLER_SIGNATURE_INVALID')
        subprocess.Popen([str(installer)])
        marker.write_text('Complete GUI installation and onboarding; setup never reports ready at this stage.\n', encoding='utf-8')
    except Exception:
        if partial.exists():
            partial.unlink()
        raise
    raise RuntimeError('EGO_ONBOARDING_REQUIRED: official installer opened; finish installation/onboarding, then rerun setup / 官方安装器已打开，请完成安装和首次引导后重试')
