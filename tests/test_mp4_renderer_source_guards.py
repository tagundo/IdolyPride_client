"""Run actual shipping read-only source renderer/message/capture guards.

Fixtures make native/managed CAPI boundaries explicit; no game/GPU claim.
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _body(bridge, marker):
    start = bridge.index("// BEGIN_" + marker)
    end = bridge.index("// END_" + marker, start)
    return bridge[start:end]


@pytest.fixture(scope="module", params=("android", "ios"))
def source_guards(tmp_path_factory, request):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    folder = tmp_path_factory.mktemp("renderer-source-" + request.param)
    results = {}
    for name, harness, replacements in (
        ("messages", "mp4_renderer_message_guard_harness.cpp", {
            "// ACTUAL_CAPTURE_IDLE": _body(bridge, "MP4_RENDERER_CAPTURE_IDLE_HOST"),
            "// ACTUAL_MESSAGE_GUARD": _body(bridge, "MP4_RENDERER_MESSAGE_GUARD_HOST"),
        }),
        ("lookup", "mp4_original_renderer_source_harness.cpp", {
            "// ACTUAL_ORIGINAL_RENDERER_SOURCE": _body(bridge, "MP4_ORIGINAL_RENDERER_SOURCE_HOST"),
        }),
        ("owned_capture", "mp4_owned_capture_request_harness.cpp", {
            "// ACTUAL_CAPTURE_IDLE": _body(bridge, "MP4_RENDERER_CAPTURE_IDLE_HOST"),
            "// ACTUAL_OWNED_CAPTURE": _body(bridge, "MP4_RENDERER_OWNED_CAPTURE_HOST"),
            "// ACTUAL_MESSAGE_GUARD": _body(bridge, "MP4_RENDERER_MESSAGE_GUARD_HOST"),
        }),
        ("proflare", "mp4_renderer_proflare_source_harness.cpp", {
            "// ACTUAL_ORIGINAL_RENDERER_SOURCE": _body(bridge, "MP4_ORIGINAL_RENDERER_SOURCE_HOST"),
            "// ACTUAL_PROFLARE_SOURCE": _body(bridge, "MP4_RENDERER_PROFLARE_SOURCE_HOST"),
        }),
    ):
        fixture = (ROOT / "tests" / harness).read_text()
        for token, actual in replacements.items():
            fixture = fixture.replace(token, actual)
        source, binary = folder / (name + ".cpp"), folder / name
        source.write_text(fixture)
        command = [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-Wno-misleading-indentation", "-fsanitize=address,undefined",
                   "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
        if request.param == "ios":
            command.append("-DIDOLY_DARWIN_BRIDGE")
        built = subprocess.run(command + [str(source), "-o", str(binary)],
                               capture_output=True, text=True, timeout=45)
        assert built.returncode == 0, built.stdout + built.stderr
        results[name] = binary
    return results


@pytest.mark.parametrize("case", range(37))
def test_shipping_renderer_messages_capture_idle_and_vfx(source_guards, case):
    result = subprocess.run([str(source_guards["messages"]), str(case)], capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("case", range(24))
def test_shipping_readonly_existing_renderer_lookup(source_guards, case):
    result = subprocess.run([str(source_guards["lookup"]), str(case)], capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("case", range(24))
def test_shipping_owned_capture_request_all_slots_target_and_event(source_guards, case):
    result = subprocess.run([str(source_guards["owned_capture"]), str(case)], capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("case", range(20))
def test_shipping_proflare_selected_feature_pass_batch_data(source_guards, case):
    result = subprocess.run([str(source_guards["proflare"]), str(case)], capture_output=True,
                            text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
