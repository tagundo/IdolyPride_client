"""Shipping PS native CPU/source policy; engine originals are explicit models.

These tests exercise the extracted Bridge implementations. They do not execute
ARM originals or assert device/GPU/MP4 correctness. Renderer repair-programme
capability remains separate from fresh physical read/drain and hardware receipts.
"""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mp4_particle_native"
BLOCKS = {
    "particle-manager-scope.hpp.inc": "PARTICLE_MANAGER_SCOPE",
    "particle-manager-host.cpp.inc": "PARTICLE_MANAGER_HOST",
    "particle-state-image.hpp.inc": "PARTICLE_STATE_IMAGE",
    "particle-state-host.cpp.inc": "PARTICLE_STATE_HOST",
    "particle-native-finish-receipt-host.cpp.inc": "PARTICLE_NATIVE_FINISH_RECEIPT_HOST",
    "particle-source-policy-host.inc": "PARTICLE_SOURCE_POLICY_HOST",
    "particle-mutation-exclusion-host.inc": "PARTICLE_MUTATION_EXCLUSION_HOST",
    "particle-mutation-hooks.inc": "PARTICLE_MUTATION_HOOKS",
    "renderer-scene-order.hpp.inc": "RENDERER_SCENE_ORDER",
    "renderer-scene-order-pins.inc": "RENDERER_SCENE_ORDER_PINS",
    "renderer-scene-order-host.cpp.inc": "RENDERER_SCENE_ORDER_HOST",
    "renderer-registration-state.hpp.inc": "RENDERER_REGISTRATION_STATE",
    "renderer-registration-pins.inc": "RENDERER_REGISTRATION_PINS",
    "renderer-registration-host.cpp.inc": "RENDERER_REGISTRATION_HOST",
    "actor-global-mpb-presence-host.inc": "ACTOR_GLOBAL_MPB_PRESENCE_HOST",
    "particle-renderer-bounds-host.inc": "PARTICLE_RENDERER_BOUNDS_HOST",
    "particle-renderer-presentation-host.inc": "PARTICLE_RENDERER_PRESENTATION_HOST",
    "particle-source-program-host.inc": "PARTICLE_SOURCE_PROGRAM_HOST",
    "particle-native-coordinator-host.inc": "PARTICLE_NATIVE_COORDINATOR_HOST",
    "particle-native-coordinator-cache-host.inc": "PARTICLE_NATIVE_COORDINATOR_HOST",
    "particle-renderer-reader-host.inc": "PARTICLE_RENDERER_READER_HOST",
    "particle-data-image-host.inc": "PARTICLE_DATA_IMAGE_HOST",
    "particle-renderer-invalidate-host.inc": "PARTICLE_RENDERER_INVALIDATE_HOST",
    "particle-retained-worker-inventory-host.inc": "PARTICLE_RETAINED_WORKER_INVENTORY_HOST",
    "particle-operation-finish-host.inc": "PARTICLE_OPERATION_FINISH_HOST",
    "particle-operation-rw-host.inc": "PARTICLE_OPERATION_RW_HOST",
    "particle-retained-image-receipt-host.inc": "PARTICLE_RETAINED_IMAGE_RECEIPT_HOST",
    "particle-native-coordinator-normal-host.inc": "PARTICLE_NATIVE_COORDINATOR_HOST",
    "particle-source-bootstrap-adapter.inc": "PARTICLE_SOURCE_BOOTSTRAP_ADAPTER",
    "source-control-ps-plan.inc": "SOURCE_CONTROL_PS_PLAN",
    "particle-cache-gate.inc": "PARTICLE_RENDERER_SOURCE_CACHE_GATE",
}


def test_shipping_particle_native_hosts(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    assert compiler
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    for filename, block in BLOCKS.items():
        start = source.index("// BEGIN_MP4_" + block)
        stop = source.index("// END_MP4_" + block, start)
        (tmp_path / filename).write_text(source[start:stop] + "\n")
    # The four immutable normal-programme blocks share one shipping wrapper.
    start = source.index("// BEGIN_MP4_PARTICLE_NORMAL_RENDERER_PROGRAM")
    stop = source.index("// END_MP4_PARTICLE_NORMAL_RENDERER_PROGRAM", start)
    normal = source[start:stop]
    tokens = ["struct Mp4ParticleNormalProgramCode", "// Actual source normal geometry programme",
              "struct Mp4ParticleDescriptorResetPins", "// Force the real normal geometry path"]
    positions = [normal.index(token) for token in tokens] + [len(normal)]
    names = ["particle-normal-program-pins.inc", "particle-normal-program-host.inc",
             "particle-renderer-descriptor-reset-pins.inc", "particle-renderer-descriptor-reset-host.inc"]
    for index, name in enumerate(names):
        (tmp_path / name).write_text(normal[positions[index]:positions[index + 1]] + "\n")
    shutil.copyfile(ROOT / "client-presentation/native/mp4_stage_state.hpp", tmp_path / "mp4_stage_state.hpp")
    for fixture in FIXTURES.glob("*.cpp"):
        shutil.copyfile(fixture, tmp_path / fixture.name)
    for model in FIXTURES.glob("*.inc"):
        shutil.copyfile(model, tmp_path / model.name)
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    for platform in ("android", "ios"):
        for fixture in sorted(FIXTURES.glob("*.cpp")):
            binary = tmp_path / (fixture.stem + "-" + platform)
            command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-pthread",
                       "-fno-pie", "-no-pie", "-g"]
            if platform == "ios":
                command.append("-DIDOLY_DARWIN_BRIDGE=1")
            built = subprocess.run(command + [str(tmp_path / fixture.name), "-o", str(binary)],
                                   capture_output=True, text=True)
            assert built.returncode == 0, (platform, fixture.name, built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, env=env)
            assert result.returncode == 0, (platform, fixture.name, result.stdout, result.stderr)
