#!/usr/bin/env bash
# Prepare this repository's virtual environment on Termux or macOS.
set -euo pipefail

IDOLY_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$IDOLY_PROJECT_DIR"

if [[ -n "${TERMUX_VERSION:-}" || "${PREFIX:-}" == *com.termux* ]]; then
  pkg install python python-grpcio capstone clang make
  IDOLY_PYTHON="${IDOLY_PYTHON:-python}"
  "$IDOLY_PYTHON" -c 'import sys; sys.exit("Python 3.12 or later is required") if sys.version_info < (3, 12) else None'
  # Use Termux's packaged grpcio instead of trying to build it with pip.
  "$IDOLY_PYTHON" -m venv --system-site-packages .venv
  .venv/bin/python -c 'import grpc; print("Using installed Termux grpcio " + grpc.__version__)'
elif [[ "$(uname -s)" == "Darwin" ]]; then
  IDOLY_PYTHON="${IDOLY_PYTHON:-python3}"
  if ! command -v "$IDOLY_PYTHON" >/dev/null 2>&1; then
    echo "Install Python 3.12 or later first, then run this script again." >&2
    exit 1
  fi
  "$IDOLY_PYTHON" -c 'import sys; sys.exit("Python 3.12 or later is required; select it with IDOLY_PYTHON") if sys.version_info < (3, 12) else None'
  if [[ ! -x .venv/bin/python ]]; then
    "$IDOLY_PYTHON" -m venv .venv
  fi
else
  echo "This setup helper supports Termux and macOS. Other systems can use uv sync --extra extract." >&2
  exit 1
fi

.venv/bin/python -c 'import sys; sys.exit("The existing .venv needs Python 3.12 or later") if sys.version_info < (3, 12) else None'
.venv/bin/python -m pip install -e "${IDOLY_PROJECT_DIR}[extract]"
echo "Setup complete. Run .venv/bin/python tools/run_local_server.py --help for the first-run command."
