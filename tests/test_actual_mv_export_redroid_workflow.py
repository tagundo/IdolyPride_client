"""The redroid MV export workflow is a separate, pinned, native ARM64 scope."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/verify-actual-mv-export-redroid.yml"
X86_WORKFLOW = ROOT / ".github/workflows/verify-actual-mv-export.yml"
spec = importlib.util.spec_from_file_location("redroid_gapps_context", ROOT / "tools/redroid_gapps_context.py")
gapps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gapps)
GAPPS_RELEASE = "MindTheGapps-15.0.0-arm64-20260915_032013"
GAPPS_SHA256 = "e979601ef70b03d9214ea24ca7a103cb408ab102718fff38ec170a6ca03e263d"
PINNED_BASE = "redroid/redroid:15.0.0_64only-250627@sha256:b51bde9cef80f7bd7581148192f2b2f4d41f23c6344cfe88eceeb8ddd67490ee"


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
    assert triggers["workflow_dispatch"]["inputs"]["gapps"] == {
        "description": "Google Play services in the guest (QA environment only; the game is unchanged)",
        "required": True, "default": "mindthegapps", "type": "choice", "options": ["mindthegapps", "none"]}
    runtime = data["jobs"]["actual-game-redroid"]
    assert runtime["env"]["REDROID_GAPPS"] == "${{ inputs.gapps || 'mindthegapps' }}"
    boot = next(step for step in runtime["steps"] if step.get("id") == "boot")
    assert boot["env"] == {"GAPPS_RELEASE": GAPPS_RELEASE, "GAPPS_SHA256": GAPPS_SHA256,
                           "GAPPS_URL": "https://github.com/MindTheGapps/15.0.0-arm64/releases/download/"
                                        + GAPPS_RELEASE + "/" + GAPPS_RELEASE + ".zip"}
    names = [step.get("name", "") for step in runtime["steps"]]
    settle = next(step for step in runtime["steps"] if step.get("name", "").startswith("Let Google Play services settle"))
    assert settle["if"] == "env.REDROID_GAPPS == 'mindthegapps'" and settle["continue-on-error"] is True
    assert names.index(boot["name"]) < names.index(settle["name"]) < names.index(
        next(step["name"] for step in runtime["steps"] if step.get("id") == "probe"))


def boot_step():
    runtime = job("actual-game-redroid")
    return runtime[runtime.index("id: boot"):runtime.index("- name: Let Google Play services settle")]


def test_google_play_services_are_on_by_default_for_dispatch_and_push():
    assert re.search(r"\n      gapps:\n        description: [^\n]+\n        required: true\n"
                     r"        default: mindthegapps\n        type: choice\n        options: \[mindthegapps, none\]\n", text())
    assert "REDROID_GAPPS: ${{ inputs.gapps || 'mindthegapps' }}" in job("actual-game-redroid")


def test_gapps_zip_is_downloaded_from_the_pinned_url_and_rejected_unless_its_sha256_matches():
    boot = boot_step()
    assert "GAPPS_RELEASE: " + GAPPS_RELEASE + "\n" in boot
    assert ("GAPPS_URL: https://github.com/MindTheGapps/15.0.0-arm64/releases/download/" + GAPPS_RELEASE + "/"
            + GAPPS_RELEASE + ".zip\n") in boot
    assert "GAPPS_SHA256: " + GAPPS_SHA256 + "\n" in boot
    download = boot.index('curl -fsSL --connect-timeout 30 --max-time 1200 -o "$G/gapps.zip" "$GAPPS_URL"')
    assert boot.rindex("for attempt in 1 2 3 4 5; do", 0, download) > boot.index("mindthegapps)")
    check = boot.index("""if ! printf '%s  %s\\n' "$GAPPS_SHA256" "$G/gapps.zip" | sha256sum -c --quiet -; then""")
    assert "is not the pinned $GAPPS_SHA256\"\n                exit 1\n" in boot[check:]
    helper = boot.index('python -B tools/redroid_gapps_context.py --zip "$G/gapps.zip" --sha256 "$GAPPS_SHA256"')
    build = boot.index('docker build --pull=false --platform linux/arm64 -t "$RUN_IMAGE" "$G/context"')
    assert download < check < helper < build < boot.index("docker run -d --name redroid")
    assert '--base-image "$IMAGE" --context "$G/context" > "$R/gapps-context.json"' in boot
    # The package's GmsCore needs API 35: the Android 14 image fails closed instead of booting without it.
    assert 'if [ "$REDROID_TAG" != 15.0.0_64only-250627 ]; then' in boot
    assert "none) printf '%s\\n' gapps=none" in boot and '*) echo "::error::unsupported gapps choice"; exit 1 ;;' in boot


def test_derived_image_is_local_from_the_pinned_digest_and_boots_with_the_same_properties():
    boot = boot_step()
    assert 'RUN_IMAGE="$IMAGE"\n' in boot and 'RUN_IMAGE="redroid-qa-gapps:$REDROID_TAG"\n' in boot
    for forbidden in ("docker push", "docker login", "docker tag", "# syntax=", "--entrypoint", "update-binary"):
        assert forbidden not in text()
    assert "test \"$(docker image inspect -f '{{.Architecture}}' \"$RUN_IMAGE\")\" = arm64" in boot
    assert '"${BASE_LAYERS%]},"*) ;;' in boot
    assert "test \"$(docker image inspect -f '{{json .Config.Entrypoint}}' \"$RUN_IMAGE\")\" = \\" in boot
    assert 'docker cp "gapps-check:/system/$path" - | tar --numeric-owner -tvf -' in boot
    assert "if grep -vE '^(drwxr-xr-x|-rw-r--r--) 0/0 ' \"$R/gapps-image-files.txt\"; then" in boot
    run = boot[boot.index("docker run -d --name redroid"):boot.index("androidboot.use_redroid_c2=1") + 30]
    assert '\n            "$RUN_IMAGE" \\\n' in run and '"$IMAGE"' not in run
    for argument in ("androidboot.redroid_gpu_mode=guest", "androidboot.use_memfd=true", "androidboot.redroid_fps=30",
                     'androidboot.redroid_dpi="$DPI"', '-v "$REDROID_DATA:/data"'):
        assert argument in run
    settings = boot[boot.index('if [ "$REDROID_GAPPS" = mindthegapps ]; then'):]
    for setting in ("'global verifier_verify_adb_installs 0'", "'global package_verifier_enable 0'",
                    "'global heads_up_notifications_enabled 0'"):
        assert setting in settings[:settings.index("fi\n")]


def test_google_play_services_settle_is_bounded_recorded_and_never_blocks_the_game():
    runtime = job("actual-game-redroid")
    settle = runtime[runtime.index("- name: Let Google Play services settle"):runtime.index("- name: Record redroid environment")]
    assert "if: env.REDROID_GAPPS == 'mindthegapps'\n        continue-on-error: true\n        timeout-minutes: 10\n" in settle
    assert "LIMIT=180" in settle and 'while [ $((SECONDS - start)) -lt "$LIMIT" ]; do' in settle
    assert "pm path com.google.android.gms 2> /dev/null" in settle and "pidof com.google.android.gms.persistent" in settle
    assert "for package in com.google.android.gms com.google.android.gsf com.android.vending; do" in settle
    for evidence in ('"$R/gms-packages.txt"', '"$R/gms-dumpsys.txt"', '"$R/gms-processes.txt"', '"$R/gms-settle.txt"',
                     "dumpsys package \"$package\"", "versionName=", '"gms_version_name=${VERSION:-none}"',
                     '"gms_persistent_process_after_seconds=$running"', "grep -m1 -oE 'Accounts: [0-9]+'",
                     "getprop ro.com.google.gmsversion", "pm list packages -d"):
        assert evidence in settle
    assert "set -uo pipefail" in settle and "set -e" not in settle and settle.rstrip().endswith("exit 0")
    assert runtime.index("- name: Let Google Play services settle") > runtime.index("id: boot")
    assert runtime.index("- name: Let Google Play services settle") < runtime.index("id: probe") < runtime.index("id: game")


def fake_gapps_zip(path, members, extra=()):
    with zipfile.ZipFile(path, "w") as archive:
        for name in list(members) + list(extra):
            archive.writestr(name, ("content of " + name).encode())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_pins(members):
    return {name: (package, hashlib.sha256(("content of " + name).encode()).hexdigest(), len("content of " + name))
            for name, (package, _, _) in members.items()}


def test_gapps_context_takes_only_the_allowlist_with_root_modes_and_a_pinned_from(tmp_path):
    excluded = ("META-INF/com/google/android/update-binary", "toybox", "system/addon.d/addond_head",
                "system/system_ext/priv-app/SetupWizard/SetupWizard.apk", "system/product/priv-app/Velvet/Velvet.apk",
                "system/product/overlay/GmsSetupWizardOverlay.apk", "system/product/lib64/libjni_latinimegoogle.so")
    members = list(gapps.PACKAGE_APKS) + list(gapps.SUPPORT_FILES)
    digest = fake_gapps_zip(tmp_path / "gapps.zip", members, excluded)
    context = tmp_path / "context"
    receipt = gapps.prepare(tmp_path / "gapps.zip", digest, PINNED_BASE, context, apk_pins=fake_pins(gapps.PACKAGE_APKS))
    assert (context / "Dockerfile").read_text() == "FROM " + PINNED_BASE + "\nCOPY --chown=0:0 system/ /system/\n"
    found = sorted(str(path.relative_to(context)) for path in context.rglob("*") if path.is_file())
    assert found == sorted(members + [gapps.INITIAL_STATE_FILE, "Dockerfile"])
    for path in (context / "system").rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644)
    assert set(receipt["packages"]) == {"com.google.android.gms", "com.google.android.gsf", "com.android.vending"}
    assert receipt["packages"]["com.google.android.gms"]["path"] == "/system/product/priv-app/GmsCore/GmsCore.apk"
    assert receipt["zip_sha256"] == digest and receipt["base_image"] == PINNED_BASE
    state = (context / gapps.INITIAL_STATE_FILE).read_text()
    for package in receipt["packages"]:
        assert '<initial-package-state package="%s" stopped="false"/>' % package in state
    assert gapps.INITIAL_STATE_FILE == "system/etc/sysconfig/qa-google-initial-package-state.xml"


def test_gapps_context_pins_the_three_google_packages_and_leaves_setup_and_optional_apps_out():
    assert {package for package, _, _ in gapps.PACKAGE_APKS.values()} == {
        "com.google.android.gms", "com.google.android.gsf", "com.android.vending"}
    assert gapps.PACKAGE_APKS["system/product/priv-app/GmsCore/GmsCore.apk"][1:] == (
        "38eb121872076788b3e2cba8006032ca4eaee569514403cf159d49f47a526d4d", 168192577)
    assert gapps.PACKAGE_APKS["system/product/priv-app/Phonesky/Phonesky.apk"][1:] == (
        "63192a372c0f5ff74219872a472371fb0d2eb5f7bf719d890bb8213d2ade6a9f", 79449783)
    assert gapps.PACKAGE_APKS["system/system_ext/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk"][1:] == (
        "748a7b1eb1edf2ca7928fe9f1e1f69df16f913755da7b657e62f38a55f0bbff7", 5335582)
    assert "system/product/overlay/GmsOverlay.apk" in gapps.SUPPORT_FILES
    for name in list(gapps.PACKAGE_APKS) + list(gapps.SUPPORT_FILES):
        assert name.startswith(("system/product/", "system/system_ext/")) and ".." not in name
        assert not re.search(r"SetupWizard|GooglePartnerSetup|GoogleRestore|Velvet|update-binary|toybox|addon\.d", name)


@pytest.mark.parametrize("defect", ["zip_sha256", "unpinned_base", "apk_pin", "missing", "symlink", "nonempty"])
def test_gapps_context_fails_closed(tmp_path, defect):
    members = list(gapps.PACKAGE_APKS) + list(gapps.SUPPORT_FILES)
    pins, base, context = fake_pins(gapps.PACKAGE_APKS), PINNED_BASE, tmp_path / "context"
    if defect == "missing":
        members.remove("system/product/priv-app/Phonesky/Phonesky.apk")
    digest = fake_gapps_zip(tmp_path / "gapps.zip", members)
    if defect == "symlink":
        with zipfile.ZipFile(tmp_path / "gapps.zip") as source, zipfile.ZipFile(tmp_path / "link.zip", "w") as target:
            for info in source.infolist():
                if info.filename == "system/product/etc/init/gapps.rc":
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                target.writestr(info, source.read(info.filename))
        (tmp_path / "link.zip").replace(tmp_path / "gapps.zip")
        digest = hashlib.sha256((tmp_path / "gapps.zip").read_bytes()).hexdigest()
    if defect == "zip_sha256":
        digest = "0" * 64
    if defect == "unpinned_base":
        base = "redroid/redroid:15.0.0_64only-250627"
    if defect == "apk_pin":
        pins = dict(gapps.PACKAGE_APKS)
    if defect == "nonempty":
        context.mkdir()
        (context / "stale").write_text("x")
    expected = {"zip_sha256": "differs from the pinned", "unpinned_base": "digest-pinned", "apk_pin": "pinned 38eb1218",
                "missing": "zip has no system/product/priv-app/Phonesky", "symlink": "not a regular file",
                "nonempty": "not empty"}[defect]
    with pytest.raises(SystemExit, match=re.escape(expected)):
        gapps.prepare(tmp_path / "gapps.zip", digest, base, context, apk_pins=pins)


def uv_lock_wheel_hashes(package):
    """Every wheel uv.lock pins for one package, by hash, with its locked version."""
    lock = (ROOT / "uv.lock").read_text()
    block = re.search(r'\n\[\[package\]\]\nname = "' + re.escape(package) + r'"\nversion = "([^"]+)"\n(.*?)(?=\n\[\[package\]\]|\Z)',
                      lock, re.S)
    return block.group(1), {digest: wheel for wheel, digest in
                            re.findall(r'/([^/"]+)\.whl", hash = "sha256:([0-9a-f]{64})"', block.group(2))}


def installs_on_the_arm_runner(wheel):
    """True for a wheel pip takes on CPython 3.13, Linux aarch64 (the setup-python job)."""
    python, abi, platform = wheel.split("-")[-3:]
    if (python, abi, platform) == ("py3", "none", "any"):
        return True
    arm = all(tag.endswith("_aarch64") and tag.startswith("manylinux") for tag in platform.split("."))
    if abi == "abi3":
        return arm and python.startswith("cp3") and python[3:].isdigit() and int(python[3:]) <= 13
    return arm and python == abi == "cp313"


def runtime_steps():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(text())["jobs"]["actual-game-redroid"]["steps"]


def test_fixture_rpc_packages_are_the_uv_lock_pins_hash_checked_and_binary_only():
    runtime = job("actual-game-redroid")
    step = runtime[runtime.index("- name: Install the pinned host RPC packages"):runtime.index("- uses: actions/download-artifact@v4")]
    requirements = re.findall(r"^ {10}([a-z-]+)==(\S+) --hash=sha256:([0-9a-f]{64})$", step, re.M)
    assert len(requirements) == 4
    assert {name for name, _, _ in requirements} == {"grpcio", "protobuf", "pycryptodome", "typing-extensions"}
    for name, version, digest in requirements:
        locked, wheels = uv_lock_wheel_hashes(name)
        assert version == locked and digest in wheels, name
        # The pinned wheel itself must install on the runner, not just any wheel of the package.
        assert installs_on_the_arm_runner(wheels[digest]), wheels[digest]
    assert "python -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes \\" in step
    assert '-r "$RUNNER_TEMP/profile-fixture-requirements.txt"' in step and "cat > \"$RUNNER_TEMP/profile-fixture-requirements.txt\" <<'EOF'" in step
    # The driver's real fixture import is proven here, before the long redroid setup.
    assert ("python -B -c 'import sys; sys.path.insert(0, \"tools\"); import run_actual_mv_export_qa as q; "
            "print(q.load_fixture_boot().prepare_completed_opening.__name__)'") in step
    # After Python is set up and before anything uses it.
    assert runtime.index("uses: actions/setup-python@v5") < runtime.index("- name: Install the pinned host RPC packages")
    assert runtime.index("- name: Install the pinned host RPC packages") < runtime.index("id: game")


def test_fixture_inputs_come_from_the_tested_apk_before_the_game_and_outside_the_evidence():
    runtime = job("actual-game-redroid")
    assert '"FIXTURE_DIR=$RUNNER_TEMP/actual-mv-fixture"' in runtime
    step = runtime[runtime.index("- name: Extract the profile fixture inputs"):runtime.index("- name: Host gate")]
    assert 'python -B tools/actual_mv_fixture_inputs.py --apk "$INPUT_DIR/current-unified-observer.apk" \\' in step
    assert '--output "$FIXTURE_DIR" --receipt "$EVIDENCE_DIR/profile-fixture-inputs.json"' in step
    assert runtime.index("- name: Verify exact input checkout") < runtime.index("- name: Extract the profile fixture inputs")
    assert runtime.index("- name: Extract the profile fixture inputs") < runtime.index("id: game")
    # The large master tables never enter the uploaded proof or the transport artifact.
    fixture = re.search(r'"FIXTURE_DIR=([^"]+)"', runtime).group(1)
    evidence = re.search(r'"EVIDENCE_DIR=([^"]+)"', runtime).group(1)
    assert not fixture.startswith(evidence) and not fixture.startswith(re.search(r'"INPUT_DIR=([^"]+)"', runtime).group(1))
    assert "actual-mv-fixture" not in job("current-input")
    assert runtime.index("- name: Install the pinned host RPC packages") < runtime.index("- name: Extract the profile fixture inputs")


def test_fixture_steps_are_real_steps_in_order():
    names = [step.get("name", "") for step in runtime_steps()]
    extract = next(name for name in names if name.startswith("Extract the profile fixture inputs"))
    install = next(name for name in names if name.startswith("Install the pinned host RPC packages"))
    game = next(step["name"] for step in runtime_steps() if step.get("id") == "game")
    assert names.index(install) < names.index(extract) < names.index(game)


def test_game_step_prepares_the_completed_opening_fixture_and_the_x86_workflow_does_not():
    runtime = job("actual-game-redroid")
    game = runtime[runtime.index("id: game"):runtime.index("Collect bounded container")]
    command = game[game.index("python -B tools/run_actual_mv_export_qa.py"):]
    setup = game[game.index('case "$PROFILE_SETUP" in'):game.index("esac")]
    assert '"${SETUP[@]}" --no-orientation-wait' in command and "viewing-mode) SETUP=(--viewing-mode)" in setup
    for argument in ("--prepare-completed-opening", '--descriptor-set "$FIXTURE_DIR/protocol/idolypride-6.1.1.pb"',
                     '--master-dir "$FIXTURE_DIR/master-json"'):
        assert setup.count(argument) == 1, argument
    assert "PROFILE_SETUP: ${{ inputs.profile_setup || 'viewing-mode' }}" in WORKFLOW.read_text()
    assert "--startup-timeout 3600 --export-timeout 7200 ${{ matrix.extra }}" in command
    x86 = X86_WORKFLOW.read_text()
    for absent in ("--prepare-completed-opening", "--descriptor-set", "--master-dir", "actual_mv_fixture_inputs", "grpcio"):
        assert absent not in x86
