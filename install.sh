#!/usr/bin/env sh
# VideoPip installer for macOS / Linux
#   curl -fsSL https://raw.githubusercontent.com/zaindev97/videopip/main/install.sh | sh
set -e

say() { printf '\033[36m==>\033[0m %s\n' "$1"; }

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ is required. macOS: brew install python  |  Debian/Ubuntu: sudo apt install python3 python3-pip python3-venv"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then say "installing ffmpeg (brew)"; brew install ffmpeg
  elif command -v apt-get >/dev/null 2>&1; then say "installing ffmpeg (apt)"; sudo apt-get update && sudo apt-get install -y ffmpeg
  else say "ffmpeg not found - videopip setup will download a static build"
  fi
fi

if ! command -v pipx >/dev/null 2>&1; then
  say "installing pipx"
  if command -v brew >/dev/null 2>&1; then brew install pipx
  else "$PY" -m pip install --user pipx || sudo apt-get install -y pipx
  fi
  "$PY" -m pipx ensurepath || true
  export PATH="$HOME/.local/bin:$PATH"
fi

say "installing videopip"
pipx install --force "videopip[all]"

say "running videopip setup"
videopip setup --full

printf '\n\033[32mDone.\033[0m Try:  videopip demo\n'
