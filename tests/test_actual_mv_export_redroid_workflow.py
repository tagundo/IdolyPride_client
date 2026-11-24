"""The redroid MV export workflow is a separate, pinned, native ARM64 scope."""
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/verify-actual-mv-export-redroid.yml"
X86_WORKFLOW = ROOT / ".github/workflows/verify-actual-mv-export.yml"


def text():
    return WORKFLOW.read_text()


def job(name):
    source = text()
    start = source.index("\n  " + name + ":\n")
    following = re.search(r"\n  [A-Za-z0-9_-]+:\n", source[start + 1:])
    return source[start:start + 1 + following.start()] if following else source[start:]


def test_registration_push_is_limited_to_this_definition_on_the_work_branch():
    source = text()
    assert re.search(r"push:\n\s+branches: \[ccr-135ccacf-oukoym\]\n\s+paths: "
                     r"\[\.github/workflows/verify-actual-mv-export-redroid\.yml\]\n", source)
    assert "workflow_dispatch:" in source and "default: Bittersweet Echo" in source
    assert "permissions:\n  contents: read\n" in source
    for forbidden in ("gh release", "upload_draft", "secrets.", "contents: write", "reactivecircus", "/dev/kvm",
                      "--record-root", "hide_error_dialogs", "ro.secure"):
        assert forbidden not in source


def test_build_job_is_the_existing_x86_current_input_build():
    build, x86 = job("current-input"), X86_WORKFLOW.read_text()
    assert "runs-on: ubuntu-24.04\n" in build
    for command in ("client-presentation/native/build_native.py", "tools/package_android_unified.py --prototype",
                    "tools/package_qa_ui_client.py", "--input-profile unified-current --emulator-only",
                    "qa-game-ui/native/build_native.py", "tools/emulator_environment_probe/build.py",
                    "tools/stage_shared_preview.py fetch", "sdkmanager 'platforms;android-34'"):
        assert command in build and command in x86
    assert "name: redroid-actual-mv-runner-input-${{ github.sha }}-${{ github.run_attempt }}" in build
    tests = re.search(r"python -B -m pytest -q -p no:cacheprovider ([^\n]+)", build).group(1).split()
    assert {"tests/test_actual_mv_export_qa.py", "tests/test_actual_mv_export_redroid_workflow.py",
            "tools/emulator_environment_probe/test_driver.py"} <= set(tests)
    assert all((ROOT / name).is_file() for name in tests)
    assert "qa-game-ui/tests/test_emulator_indicators.py" in build


def case_table():
    raw = re.search(r"CASE_TABLE: >-\n((?:\s{12}.+\n)+)", job("current-input")).group(1)
    return json.loads(" ".join(line.strip() for line in raw.splitlines()))


def test_case_matrix_starts_with_one_small_direct_export_and_is_extensible():
    rows = case_table()
    assert rows[0] == {"case": "direct-30", "fps": 30, "width": 256, "height": 144, "extra": ""}
    assert len({row["case"] for row in rows}) == len(rows)
    for row in rows:
        assert row["fps"] in (30, 60) and 16 <= row["width"] <= 4096 and 16 <= row["height"] <= 4096
        assert not row["width"] % 2 and not row["height"] % 2 and row["extra"] in ("", "--queue-replay")
    options = re.search(r"options: \[(direct-30[^\]]*)\]", text()).group(1).split(", ")
    assert options == [row["case"] for row in rows] + ["all"]
    assert "SELECTED: ${{ inputs.cases || 'direct-30' }}" in text()
    assert "include: ${{ fromJSON(needs.current-input.outputs.cases) }}" in job("actual-game-redroid")


def test_runtime_runs_pinned_redroid_natively_on_the_arm_runner():
    runtime = job("actual-game-redroid")
    assert "runs-on: ubuntu-24.04-arm\n" in runtime and "timeout-minutes: 300\n" in runtime
    assert "needs: current-input" in runtime and "artifact-ids: ${{ needs.current-input.outputs.artifact_id }}" in runtime
    assert "sudo modprobe binder_linux devices=binder,hwbinder,vndbinder" in runtime
    assert runtime.index("sudo modprobe binder_linux") < runtime.index("docker run -d --name redroid")
    assert "15.0.0_64only-250627) DIGEST=sha256:b51bde9cef80f7bd7581148192f2b2f4d41f23c6344cfe88eceeb8ddd67490ee" in runtime
    assert "14.0.0_64only-240527) DIGEST=sha256:0a611199ba2e0b5d60af39b3327a517f6407231f4352114ed3bd3cbfe2be69aa" in runtime
    assert 'IMAGE="redroid/redroid:$REDROID_TAG@$DIGEST"' in runtime
    assert "test \"$(docker image inspect -f '{{.Architecture}}' \"$IMAGE\")\" = arm64" in runtime
    for argument in ("androidboot.redroid_gpu_mode=guest", "androidboot.use_memfd=true", "--privileged",
                     '-p "127.0.0.1:${REDROID_SERIAL##*:}:5555"', 'androidboot.redroid_width="$WIDTH"'):
        assert argument in runtime
    assert "--rm" not in runtime and "--network host" not in runtime
    assert "sudo apt-get install -y --no-install-recommends adb ffmpeg" in runtime
    assert "setup-android" not in runtime and "emulator-runner" not in runtime


def test_redroid_serial_is_loopback_and_outside_the_adb_emulator_scan_range():
    serial = re.search(r"REDROID_SERIAL: (\S+)", job("actual-game-redroid")).group(1)
    host, port = serial.split(":")
    assert host == "127.0.0.1" and not 5555 <= int(port) <= 5585


def test_probe_never_blocks_the_game_and_both_use_the_explicit_redroid_guest():
    runtime = job("actual-game-redroid")
    probe = runtime[runtime.index("id: probe"):runtime.index("id: game")]
    assert "continue-on-error: true" in probe
    assert 'run_probe.py --serial "$REDROID_SERIAL" --guest redroid' in probe
    game = runtime[runtime.index("id: game"):runtime.index("Collect bounded container")]
    assert "continue-on-error" not in game and "timeout-minutes: 240" in game
    assert 'run_actual_mv_export_qa.py --guest redroid --serial "$REDROID_SERIAL"' in game
    assert "--fps '${{ matrix.fps }}' --width '${{ matrix.width }}' --height '${{ matrix.height }}'" in game
    assert "--startup-timeout 3600 --export-timeout 7200 ${{ matrix.extra }}" in game


def test_environment_evidence_and_bounded_redacted_logs_are_always_retained():
    runtime = job("actual-game-redroid")
    for evidence in ('getprop > "$R/getprop.txt"', "ro.product.cpu.abilist", "dumpsys SurfaceFlinger",
                     "cmd gpu vkjson", "wm size", "dumpsys media.audio_flinger", "com.android.documentsui",
                     "docker logs", "dmesg", "logcat -d -b all", 'grep -viE "$REDACT"', "tail -c 8388608"):
        assert evidence in runtime
    uploads = re.findall(r"- name: [^\n]+\n\s+if: always\(\)\n\s+uses: actions/upload-artifact@v4\n\s+with:\n\s+name: ([^\n]+)", runtime)
    assert uploads == ["redroid-actual-mv-proof-${{ matrix.case }}-${{ github.sha }}-${{ github.run_attempt }}",
                       "redroid-actual-mv-movie-${{ matrix.case }}-${{ github.sha }}-${{ github.run_attempt }}"]
    assert "!${{ runner.temp }}/redroid-mv-evidence/video/" in runtime
    assert runtime.index("Remove the disposable container") > runtime.index("Retain the bounded actual-game movie")


def test_existing_translated_emulator_workflow_is_not_redirected_to_redroid():
    x86 = X86_WORKFLOW.read_text()
    assert "redroid" not in x86 and "--guest" not in x86
    assert "runs-on: ubuntu-24.04\n    timeout-minutes: 360" in x86
    assert "name: actual-mv-proof-${{ matrix.case }}" in x86


def test_workflow_is_valid_yaml_when_a_parser_is_available():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(text())
    triggers = data[True]
    assert triggers["push"]["branches"] == ["ccr-135ccacf-oukoym"]
    assert set(data["jobs"]) == {"current-input", "actual-game-redroid"}
    assert data["jobs"]["actual-game-redroid"]["runs-on"] == "ubuntu-24.04-arm"
