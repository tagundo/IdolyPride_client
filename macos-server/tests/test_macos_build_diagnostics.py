"""Fixed child checkpoints and bounded redaction; never run native build tools."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote, quote_plus

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_app
from test_build_app import app_build

SPEC = importlib.util.spec_from_file_location(
    "mac_failure_release_builds", Path(__file__).resolve().parents[2] / "tools/release_platform_builds.py")
builds = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builds)


@pytest.mark.parametrize("phase", ["pyinstaller", "swift", "sign", "engine_smoke"])
def test_real_child_checkpoints_identify_failed_native_stage_without_error_text(app_build, monkeypatch, phase):
    payload, output, archive, evidence, commands = app_build
    previous = build_app.run
    original = subprocess.CalledProcessError(7, ["private-command-canary"], output="private-output-canary")

    def failing(arguments, **kwargs):
        values = list(map(str, arguments))
        match = {"pyinstaller": "PyInstaller" in values, "swift": "swiftc" in values,
                 "sign": values[0] == "/usr/bin/codesign",
                 "engine_smoke": "--smoke" in values}[phase]
        if match:
            assert json.loads((evidence / "mac-build-phase.json").read_text())["phase"] == phase
            raise original
        return previous(arguments, **kwargs)

    monkeypatch.setattr(build_app, "run", failing)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        build_app.build(payload, output, archive, evidence, "0.3.36", smoke=phase == "engine_smoke")
    assert caught.value is original
    report = (evidence / "mac-build-phase.json").read_bytes()
    assert len(report) <= 1024 and b"canary" not in report
    assert json.loads(report) == {"schema": 1, "status": "FAIL", "phase": phase,
        "error_class": "CalledProcessError", "exitcode": 7, "error_code": "mac_build_" + phase + "_failed"}


def test_success_checkpoint_and_unknown_error_names_are_fixed(app_build):
    payload, output, archive, evidence, _ = app_build
    build_app.build(payload, output, archive, evidence, "0.3.36", smoke=False)
    assert json.loads((evidence / "mac-build-phase.json").read_text()) == {
        "schema": 1, "status": "PASS", "phase": "complete"}
    private_error = type("private_name_canary", (Exception,), {})("private_message_canary")
    checkpoint = build_app.BuildDiagnostics(evidence)
    checkpoint.checkpoint("relocated_app", private_error)
    assert "canary" not in checkpoint.path.read_text()
    assert json.loads(checkpoint.path.read_text())["error_class"] == "Exception"


def test_checkpoint_write_failure_does_not_replace_build_failure(tmp_path, monkeypatch):
    checkpoint = build_app.BuildDiagnostics(tmp_path)
    monkeypatch.setattr(Path, "write_bytes", lambda *_: (_ for _ in ()).throw(PermissionError("canary")))
    checkpoint.checkpoint("engine_smoke", RuntimeError("original canary"))


def test_mac_log_masks_all_sensitive_environment_forms_and_auth_urls(tmp_path, capsys):
    raw, output = tmp_path / "raw.log", tmp_path / "output"
    output.mkdir()
    password = 'space @ "canary"/한글'
    token = "token-canary-123"
    key = "private-line-one\nprivate-line-two"
    values = (password, quote(password, safe=""), quote_plus(password),
              json.dumps(password, ensure_ascii=True)[1:-1], token, *key.splitlines())
    raw.write_text("\n".join(values) + "\nAuthorization: Basic unknown-auth-canary\n"
        "prefix Bearer unknown-bearer-canary\n"
        "https://host/path?X-Amz-Credential=unknown-query-canary&X-Amz-Signature=hidden\n"
        "https://user:unknown-url-password@host/path\n"
        'api_key = unknown-key-canary\n{"password": "unknown-password-canary"}\n'
        "-----BEGIN PRIVATE KEY-----\nunknown-pem-canary\n-----END PRIVATE KEY-----\n"
        "ValueError: actual public build failure\n", encoding="utf-8")
    result = builds.retain_mac_build_failure(raw, output, environ={
        "CI_TOKEN": token, "Signing_Key": key, "app_password": password, "OTHER": "public"})
    retained = result.read_text()
    printed = capsys.readouterr().err
    for value in values + ("unknown-auth-canary", "unknown-bearer-canary", "unknown-query-canary",
                          "unknown-url-password", "unknown-key-canary", "unknown-password-canary", "unknown-pem-canary"):
        assert value not in retained and value not in printed
    assert "ValueError: actual public build failure" in retained
    assert "[REDACTED" in retained and result.stat().st_size <= 16 * 1024
    assert raw.read_text().startswith(password)  # Raw owned source is never rewritten or uploaded.


def test_mac_log_tail_is_bounded_and_discards_partial_opening_line(tmp_path):
    raw, output = tmp_path / "raw.log", tmp_path / "output"
    output.mkdir()
    raw.write_text("first-long-line-canary" * 2000 + "\nValueError: known failure\n")
    retained = builds.retain_mac_build_failure(raw, output, environ={}).read_text()
    assert retained == "ValueError: known failure\n"
    assert len(retained.encode()) <= 16 * 1024


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_mac_log_refuses_nonregular_files_without_reading(tmp_path, kind):
    raw, output = tmp_path / "raw.log", tmp_path / "output"
    output.mkdir()
    if kind == "fifo":
        os.mkfifo(raw)
    else:
        target = tmp_path / "private.log"
        target.write_text("canary")
        raw.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        builds.retain_mac_build_failure(raw, output, environ={})
    assert not list(output.iterdir())


def test_mac_wrapper_retains_sanitized_child_failure_and_reraises_same_error(tmp_path, monkeypatch):
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir(); output.mkdir()
    monkeypatch.setattr(builds.sys, "platform", "darwin")
    monkeypatch.setattr(builds.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(builds, "fetch_public_inputs", lambda *args: {})
    monkeypatch.setattr(builds, "build_go", lambda *args: (tmp_path / "library.dylib", {}))
    monkeypatch.setenv("CI_BUILD_TOKEN", "private-wrapper-canary")
    original = builds.BuildError("remote_build_step_failed")

    def fail(arguments, log, guard):
        Path(log).write_text("private-wrapper-canary\nValueError: public error\n")
        raise original

    monkeypatch.setattr(builds, "run", fail)
    with pytest.raises(builds.BuildError) as caught:
        builds.build_macos(work, output, "a" * 40, {}, object())
    assert caught.value is original
    retained = (output / "mac-native-build.sanitized.log").read_text()
    assert "private-wrapper-canary" not in retained and "ValueError: public error" in retained


def test_workflow_retains_only_sanitized_mac_log_and_fixed_failure_report():
    source = (Path(__file__).resolve().parents[2] / ".github/workflows/release-all-platforms.yml").read_text()
    block = source.split("name: optimized-release-macos-diagnostics-", 1)[1].split("\n  ios-unified:", 1)[0]
    assert "/idoly-macos-work/**/*.json" in block
    assert "/idoly-macos-final/build-failure.json" in block
    assert "/idoly-macos-final/mac-native-build.sanitized.log" in block
    assert "/mac-native-build.log" not in block
