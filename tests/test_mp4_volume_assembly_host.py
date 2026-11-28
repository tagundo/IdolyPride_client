"""Exercise shipping Volume field, constructor and existing-manager guards.

Typed metadata/GC/native-query boundaries are explicit fixtures. This is not
Unity rendering, native decoder, GPU completion, or device MP4 proof.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIELDS = "static_field wrong_offset wrong_enum lost_root readonly_slot wrong_reference_type reference_barrier mode_value manager_alias camera_alias unpublished wrong_source unobserved_submit inflight orphaned gpu_wait cached_actual_fence next_unpublished withdraw_requires_no_alias final_job_epoch partial_readonly_capture partial_factory_not_unpublished".split()
CALLBACKS = "all32 bytes_tampered foreign_hook own_hook lost_source context_lost wrong_ctor derived_enable unknown_cctor wrong_reflection bad_slot slot_method_owner wrong_param_type static_param_field".split()
DETACH = "empty capture_only unpublished_refused checkpoint bad_checkpoint checkpoint_globals_pending first_current_raw same_pointer_new_init lost_source_without_receipt partial_raw_throw already_detached uncertain_globals".split()
MANAGER = "baseline state_pending state_faulted manager_uninitialized no_existing_value wrong_closed_value_type open_generic_zero_offset foreign_lazy not_static_readonly wrong_factory root_failure".split()


def section(source, begin, end):
    left = source.index(begin)
    return source[left:source.index(end, left)]


def function(source, name):
    match = re.search(r"(?:bool|void|Mp4SceneResult|Mp4VolumeAssemblyField \*)\s*" + name + r"\(", source)
    assert match, name
    pos = source.index("{", match.start())
    level, end = 1, pos + 1
    while level:
        level += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end] + "\n"


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ host compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    actual = section(bridge, "// BEGIN_MP4_VOLUME_ASSEMBLY_HOST", "// END_MP4_VOLUME_ASSEMBLY_HOST")
    factory = section(bridge, "// BEGIN_MP4_VOLUME_FACTORY_HOST", "namespace mp4pv =")
    pins = section(actual, "struct Mp4VolumeAssemblyPins", "// Exact two-platform ctor/callback closure pins.")
    guard = section(actual, "// Exact two-platform ctor/callback closure pins.", "// Existing-only VolumeManager lookup.")
    existing = section(actual, "// Existing-only VolumeManager lookup.", "// Shared-only final Volume assembly.")
    definitions = section(actual, "struct Mp4VolumeAssemblyField", "bool mp4_volume_assembly_raw_roots")
    names = ["mp4_volume_assembly_raw_roots", "mp4_volume_assembly_field", "mp4_volume_assembly_slot", "mp4_volume_assembly_ref", "mp4_volume_assembly_ref_set", "mp4_volume_assembly_mode", "mp4_volume_assembly_mode_set", "mp4_volume_assembly_no_alias", "mp4_volume_assembly_draw_fenced", "mp4_volume_assembly_final_fenced", "mp4_volume_assembly_withdrawn"]
    detach = definitions + "\n".join(function(actual, n) for n in ("mp4_volume_assembly_before_source_change", "mp4_volume_assembly_abandon", "mp4_volume_assembly_detach_natural", "mp4_volume_assembly_detach"))
    fields = definitions + "\n".join(function(actual, n) for n in names)
    base = (ROOT / "tests/fixtures/mp4_volume_factory_host.cpp.inc").read_text().split("struct FakeCurve")[0]
    result = {}
    folder = tmp_path_factory.mktemp("volume-assembly")
    for kind, body in (("fields", fields), ("callback_guard", guard), ("existing_manager", existing), ("detach", detach)):
        prefix = "" if kind == "detach" else base
        fixture = (ROOT / f"tests/fixtures/mp4_volume_{'assembly_fields' if kind == 'fields' else kind}.cpp.inc").read_text()
        if kind == "callback_guard":
            prefix = prefix.replace("bool mp4_hook_was_statically_verified(const mp4game::Binding &) { return false; }", "")
            prefix = prefix.replace("descriptors[reinterpret_cast<uintptr_t>(p)]", "descriptors[reinterpret_cast<uintptr_t>(p) - image_base]")
            body = factory + body
        fixture = fixture.replace("// SHIPPING_VOLUME_ASSEMBLY_DETACH", body)
        fixture = fixture.replace("// SHIPPING_VOLUME_ASSEMBLY_FIELDS", body)
        fixture = fixture.replace("// SHIPPING_VOLUME_CALLBACK_GUARD", body)
        fixture = fixture.replace("// SHIPPING_VOLUME_ASSEMBLY_PINS", pins)
        fixture = fixture.replace("// SHIPPING_VOLUME_EXISTING_MANAGER", body)
        source, binary = folder / f"{kind}.cpp", folder / kind
        source.write_text(prefix + fixture)
        built = subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)], capture_output=True, text=True, timeout=90)
        assert built.returncode == 0, built.stdout + built.stderr
        result[kind] = binary
    return result


@pytest.mark.parametrize("kind,mode", [("fields", m) for m in FIELDS] + [("callback_guard", m) for m in CALLBACKS] + [("existing_manager", m) for m in MANAGER] + [("detach", m) for m in DETACH])
def test_shipping_volume_assembly_guard(binaries, kind, mode):
    run = subprocess.run([str(binaries[kind]), mode], capture_output=True, text=True, timeout=20, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"})
    assert run.returncode == 0, run.stdout + run.stderr
