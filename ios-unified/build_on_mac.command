#!/bin/bash
set -euo pipefail
task_source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
for task_python in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do
  if [ -x "$task_python" ]; then
    exec "$task_python" -B "$task_source_dir/build_on_mac.py"
  fi
done
if command -v python3.13 >/dev/null 2>&1; then
  exec python3.13 -B "$task_source_dir/build_on_mac.py"
fi
echo 'Python 3.13을 설치해 주세요: brew install python@3.13' >&2
exit 1
