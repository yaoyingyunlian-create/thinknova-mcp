#!/bin/sh
# Run from a local-execution-capable assistant. Never publish or change account login state.
set -eu
destination=${1:-thinknova-toolkit}
install_dependency() {
  if command -v brew >/dev/null 2>&1; then
    package="$1"
    [ "$package" != python3 ] || package=python
    brew install "$package"
  elif command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
      apt-get update && apt-get install -y "$1" python3-venv
    else
      sudo -n apt-get update && sudo -n apt-get install -y "$1" python3-venv
    fi
  elif [ "$(uname -s)" = Darwin ]; then
    echo "DEPENDENCY_REPAIR_UNAVAILABLE: missing $1; install Homebrew from https://brew.sh, then rerun this installer. 请先按 Homebrew 官网说明安装，再重跑本安装器。" >&2
    exit 2
  else
    echo "DEPENDENCY_REPAIR_UNAVAILABLE: missing $1; no supported package manager. Check installation permissions." >&2
    exit 2
  fi
}
command -v git >/dev/null 2>&1 || install_dependency git
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  install_dependency python3
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else "PYTHON_REPAIR_NOT_EFFECTIVE: repository Python is older than 3.10")'
repository=https://github.com/yaoyingyunlian-create/thinknova-mcp.git
if [ ! -e "$destination" ]; then
  git -c core.autocrlf=false clone "$repository" "$destination"
elif [ "$(git -C "$destination" remote get-url origin)" != "$repository" ]; then
  echo 'DESTINATION_CONFLICT: existing directory preserved.' >&2
  exit 2
fi
python3 "$destination/bootstrap.py" setup
