#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo 'Python 3.11+ is required. Set PYTHON to an existing Python executable.'
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  if ! "$PYTHON" -m venv .venv; then
    echo 'Could not create venv. If dependencies are already installed, use: /path/to/old/.venv/bin/python run.py'
    exit 1
  fi
fi
# Check pinned requirements locally; install only on first run or after updates.
if ! .venv/bin/python -c 'from importlib.metadata import version; from packaging.requirements import Requirement; from pathlib import Path; reqs=[Requirement(s.strip()) for s in Path("requirements.txt").read_text().splitlines() if s.strip() and not s.startswith("#")]; assert all(version(r.name) in r.specifier for r in reqs)' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python run.py --open-browser
