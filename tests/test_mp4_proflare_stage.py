"""Actual shipping PF helpers with explicit engine/IL2CPP/hardware models.

These host tests check finite ownership/cleanup and orchestration. They neither
execute ARM originals nor establish device rendering or successful MP4 export.
The unimplemented post-prewarm reset remains a diagnostic refusal.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mp4_proflare_stage"
BLOCKS = {
    "proflare-cache-host.cpp": "PROFLARE_CACHE_HOST",
    "proflare-registry-host.cpp": "PROFLARE_REGISTRY_HOST",
    "proflare-data-birth-host.cpp": "PROFLARE_DATA_BIRTH_HOST",
    "proflare-data-retirement-host.cpp": "PROFLARE_DATA_RETIREMENT_HOST",
    "source-plan-host.inc": "PROFLARE_SOURCE_PLAN_HOST",
    "access-host.inc": "PROFLARE_ACCESS_HOST",
    "scalar-schema-pins.inc": "PROFLARE_SCALAR_SCHEMA_PINS",
    "scalar-image-host.inc": "PROFLARE_SCALAR_IMAGE_HOST",
    "sub-element-image-host.inc": "PROFLARE_SUB_ELEMENT_IMAGE_HOST",
    "frontends-host.inc": "PROFLARE_FRONTENDS_HOST",
    "capture-witness-host.inc": "PROFLARE_CAPTURE_WITNESS_HOST",
    "equipment-source-plan-host.inc": "PROFLARE_EQUIPMENT_SOURCE_PLAN_HOST",
    "psyllium-program-host.inc": "PSYLLIUM_PROGRAM_HOST",
    "stage-graphics-program-host.inc": "STAGE_GRAPHICS_PROGRAM_HOST",
}
HEADER_BLOCKS = {
    "proflare-registry-scope.hpp.inc": "PROFLARE_REGISTRY_SCOPE",
    "proflare-storage-promotion.hpp.inc": "PROFLARE_STORAGE_PROMOTION",
}


def block(source: str, name: str) -> str:
    start = source.index("// BEGIN_MP4_" + name)
    stop = source.index("// END_MP4_" + name, start)
    return source[start:stop] + "\n"


def extract(tmp_path: Path) -> None:
    source = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    header = (ROOT / "client-presentation/native/mp4_stage_state.hpp").read_text()
    for filename, marker in BLOCKS.items():
        (tmp_path / filename).write_text(block(source, marker))
    for filename, marker in HEADER_BLOCKS.items():
        (tmp_path / filename).write_text(block(header, marker))
    # Fixtures model the original callable setters; execute the entire actual
    # reference/ownership implementation following its immutable pin table.
    ref = block(source, "PROFLARE_PASS_REFERENCE_HOST")
    (tmp_path / "proflare-pass-reference-test-body.inc").write_text(
        ref[ref.index("struct Mp4ProFlarePassReferences"):])
    coordinator = block(source, "PROFLARE_COORDINATOR_HOST")
    cuts = {
        "coordinator-types.inc": ("// BEGIN_MP4_PROFLARE_COORDINATOR_HOST", "bool mp4_proflare_owner_identity()"),
        "coordinator-capture.inc": ("Mp4SceneResult mp4_proflare_capture()", "Mp4SceneResult mp4_proflare_retire_gpu()"),
        "coordinator-empty-lease.inc": ("bool mp4_proflare_empty_data_lease(", "bool mp4_proflare_quiet()"),
        "coordinator-sequence.inc": ("Mp4SceneResult mp4_proflare_retire_gpu()", "bool mp4_proflare_renderer_data_reference"),
        "coordinator-batch-late.inc": ("using Mp4ProFlareBatchLate", "bool mp4_proflare_backend_hooks()"),
        "coordinator-release.inc": ("Mp4SceneResult mp4_proflare_release(bool owned)", "void mp4_proflare_batch_disable_invoke"),
    }
    for filename, (start, end) in cuts.items():
        left = coordinator.index(start)
        (tmp_path / filename).write_text(coordinator[left:coordinator.index(end, left)] + "\n")
    (tmp_path / "coordinator-batch-disable.inc").write_text(
        coordinator[coordinator.index("void mp4_proflare_batch_disable_invoke"):])
    for fixture in FIXTURES.glob("*.cpp"):
        shutil.copyfile(fixture, tmp_path / fixture.name)


def scenarios(name: str, source: str) -> list[str]:
    if name == "check-proflare-cache":
        return list(dict.fromkeys(re.findall(r'std::strcmp\(c, "([^"]+)"\)', source)))
    if name == "check-proflare-registry":
        return ["normal"]
    if name == "check-proflare-registry-host":
        return "normal restore no_operation no_restore source_lost wrong_field wrong_entry wrong_element wrong_array wrong_owner".split()
    if name == "check-proflare-pass-reference":
        return "normal populated nonempty source_member setter birth no_birth restore not_quiet no_op weak removed changed_source release_wait nullable_existing nullable_existing_restore active_empty_image".split()
    if name == "check-proflare-data-registry":
        return "normal no_callback no_origin unknown_retire existing null_result wrong_result grow wrong_token wrong_array prefix tail version list_identity registry_mutation uncompleted lost_origin lost_source exception retire retire_reorder retire_version wrong_camera restored_birth abandon abandon_wait abandon_appended abandon_prefix abandon_token abandon_registry abandon_version abandon_wrong_operation".split()
    if name == "check-proflare-data-birth":
        return list(dict.fromkeys(["normal"] + re.findall(r'mode=="([^"]+)"', source)))
    if name == "check-proflare-data-retirement":
        return "normal original_exception partial_init after_init after_append cancel bad_fresh gpu_wait passes_wait no_operation no_method not_held job_wait dispose_throw foreign_list".split()
    return []


@pytest.mark.parametrize("platform", ["android", "ios"])
@pytest.mark.parametrize("fixture", sorted(path.name for path in FIXTURES.glob("*.cpp")))
def test_shipping_proflare_host(tmp_path: Path, platform: str, fixture: str) -> None:
    compiler = shutil.which("c++")
    assert compiler
    extract(tmp_path)
    target = tmp_path / fixture
    binary = tmp_path / "host"
    command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
               "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-g"]
    if platform == "ios":
        command.append("-DIDOLY_DARWIN_BRIDGE=1")
    built = subprocess.run(command + [str(target), "-o", str(binary)], capture_output=True, text=True)
    assert built.returncode == 0, (platform, fixture, built.stderr)
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    cases = scenarios(target.stem, target.read_text())
    for case in cases or [None]:
        result = subprocess.run([str(binary)] + ([case] if case else []), capture_output=True, text=True, env=env)
        assert result.returncode == 0, (platform, fixture, case, result.stdout, result.stderr)
