"""Exercise the exact shipping Audio bank, channels, Gate and receipt helpers.

116 bounded cases compile production sections/header under explicit engine/GC
fixtures. These verify host ordering/lifetime/error semantics, not an Android/
iOS MV run, a DSP backend, encoder output, GPU completion, or native ARM execution.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "client-presentation/native"
FIXTURES = ROOT / "tests/fixtures"
BRIDGE = NATIVE / "bridge.cpp"

CASES = {
    "outer": (
        "bank_null_hooks bank_oom bank_reuse admit admit_clip admit_channels "
        "admit_route capture_rollback capture_exception before_untrusted "
        "rebuild_uninvoked unchanged_graph private_voice private_filter "
        "recipe_change mixed_failure fallback_exception retired wrong_restore_time "
        "logical_checkpoint logical_time_change before_detach paused natural "
        "two_sources same_source moving_callback ordinary_clip_stop nonplaying "
        "ordinary_playstate_change early_natural_during_cleanup paused_early_natural "
        "capture_retry post_arm_retry post_before_checkpoint root_identity "
        "source_handoff canonical_exception process_exception foreign_thread "
        "release_wait reuse output_admission"
    ).split(),
    "receipts": (
        "begin_no_active begin_wrong_epoch begin_wrong_director begin_clock_open "
        "begin_phase begin_flag invoke_missing invoke_wrong_version "
        "evaluate_outside_epoch evaluate_nested evaluate_future_time "
        "evaluate_exception complete_wrong_time complete_wrong_epoch consume_phase "
        "consume_wrong_transaction consume_once"
    ).split(),
    "camera_audio": (
        "missing_api unowned_active active paused_fast logical_reject "
        "direct_unchanged property_reject inactive"
    ).split(),
    "gate": (
        "ordinary mixed private unrelated restore empty bounds null_data "
        "null_vector null_entry duplicate reject bad_route pre post source thread "
        "abandon handoff exception release original_missing outcome_pre outcome_post "
        "outcome_private outcome_throw"
    ).split(),
}


def section(source, start, end):
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    compiler = os.environ.get("CXX") or shutil.which("c++")
    if not compiler:
        pytest.skip("C++17 compiler required")
    output = tmp_path_factory.mktemp("shipping-audio")
    source = BRIDGE.read_text()
    # The core begins after concrete channel helpers in its production marker.
    marker = section(
        source, "// BEGIN_MP4_AUDIO_OUTER_HOST", "// END_MP4_AUDIO_OUTER_HOST"
    )
    chunks = {
        "shipping-outer.inc": marker[
            marker.index("namespace mp4audio = idoly_mp4_native_audio_output;"):
        ],
        "shipping-late.inc": section(
            source, "struct Mp4AudioEvaluationReceipt {",
            "[[maybe_unused]] void *mp4_audio_source_clip"
        ),
        "shipping-channel.inc": section(
            marker, "struct Mp4AudioSharedPin {",
            "#ifndef IDOLY_DARWIN_BRIDGE\n#include <algorithm>"
        ),
        "shipping-channel-pins.inc": section(
            marker, "struct Mp4AudioChannelPins",
            "// Shared-only exact Timeline AudioSource channels."
        ),
        "shipping-gate.inc": section(
            source,
            "// Bounded adapter for the source-pinned AudioPlayableOutput category-5 callback.",
            "} // namespace idoly_mp4_native_audio_output"
        ) + "} // namespace idoly_mp4_native_audio_output\n",
    }
    for filename, body in chunks.items():
        (output / filename).write_text(body)
    receipt = {
        "bridge_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "extract_sha256": {
            name: hashlib.sha256(body.encode()).hexdigest()
            for name, body in chunks.items()
        },
        "fixture_scope": __doc__,
    }
    (output / "source-receipt.json").write_text(json.dumps(receipt, indent=2))
    sanitizer = os.environ.get("MP4_AUDIO_SANITIZERS") == "1"
    compiled = {}
    for name in [*CASES, "channel"]:
        cpp = output / f"{name}.cpp"
        cpp.write_text((FIXTURES / f"mp4_audio_{name}_host.cpp.inc").read_text())
        binary = output / name
        command = [
            compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
            "-I", str(NATIVE), str(cpp), "-o", str(binary),
        ]
        if sanitizer:
            command[1:1] = [
                "-fsanitize=address,undefined", "-fno-pie", "-no-pie"
            ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        compiled[name] = binary
    return compiled


@pytest.mark.parametrize(
    "group,case",
    [(group, case) for group, cases in CASES.items() for case in cases],
)
def test_shipping_audio_protocol(binaries, group, case):
    result = subprocess.run(
        [str(binaries[group]), case],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shipping_audio_distinct_channel_roles(binaries):
    result = subprocess.run(
        [str(binaries["channel"])],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "22 cases passed" in result.stdout
