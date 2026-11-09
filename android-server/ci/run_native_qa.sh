#!/usr/bin/env bash
set -euo pipefail
uv run --locked python android-server/ci/qa_emulator.py \
  --apk data/dist/IdolyPride-Local-Server-Android-x86_64-QA.apk \
  --descriptor-set data/protocol/idolypride-6.1.1.pb \
  --artifacts data/android-server-qa --startup-timeout 600
uv run --locked python android-server/ci/qa_diagnostics.py \
  --server-apk data/dist/IdolyPride-Local-Server-Android-x86_64-QA.apk \
  --probe-apk data/dist/IdolyPride-Diagnostics-Probe.apk \
  --descriptor-set data/protocol/idolypride-6.1.1.pb \
  --artifacts data/android-diagnostics-qa --startup-timeout 600
