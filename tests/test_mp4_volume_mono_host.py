"""Shipping finite Mono producer and concrete host extraction.

Original Unity/GC/query calls have explicit modeled fixtures. These cases prove
collector/lease/restore guards, not Unity/GPU behavior or device MP4 output.
"""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCOPE_MODES = "mirror fog mirror_unproved_mesh unclosed_profile held_late unowned_forward fog_lifecycle revoke clone_throw late_throw gpu_wait zero_inventory unconfigured_inventory mirror_null foreign_profile foreign_cache foreign_block owner_changed mirror_mask_retarget abandon_forward unauthorized_lifecycle failed_lifecycle_detach reentrant mirror_nested_parameters postrestore_forward fog_dormant mirror_dormant raw_handoff raw_handoff_superseded capture_fence_lost raw_handoff_cleanup raw_handoff_cleanup_alias pending_revoke stale_consumed_tick grant_requires_prepare consumed_nonheld mirror_unpublished_detach fog_unpublished_detach completion_after_revoke revoked_before_consumption inactive_revoked_completion zero_committed_completion light light_dormant light_nonfinite light_second_foreign light_foreign_after_prepare".split()
HOST_MODES = "zero baseline dormant mirror mirror_unprotected duplicate_producer unknown_producer unknown_profile_component unknown_lifecycle stage_changed asset_changed membership_changed target_changed private_component_alias private_param_alias private_flat_clone curve_profile profile_layout24 light cache_role private_cleanup private_cleanup_parent_dead private_cleanup_component_dead private_cleanup_source_alias private_cleanup_native_replaced private_cleanup_list_changed private_cleanup_throw world_inventory_missing".split()


def marker(source, name):
    begin = source.index("// BEGIN_" + name)
    end = source.index("// END_" + name, begin)
    return source[begin:end]


@pytest.fixture(scope="module")
def binaries(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("Host C++ compiler required")
    bridge = (ROOT / "client-presentation/native/bridge.cpp").read_text()
    scope = marker(bridge, "MP4_VOLUME_MONO_SCOPE")
    factory = marker(bridge, "MP4_VOLUME_FACTORY_HOST").split("namespace mp4pv =")[0]
    pins = marker(bridge, "MP4_VOLUME_SOURCE_PINS")
    host = marker(bridge, "MP4_VOLUME_MONO_HOST")
    split = host.index("// Shared-only concrete adapter")
    pins_exports, adapter = host[:split], host[split:]
    # Query fixtures supply actual typed callable addresses. The source pins
    # and production collector are unchanged apart from mutable test copies of
    # those explicit direct-call binding tables.
    pins = pins.replace("constexpr auto&mp4_source_volume_pins=", "auto mp4_source_volume_pins=")
    pins_exports = pins_exports.replace("constexpr auto&mp4_volume_mono_bindings=", "auto mp4_volume_mono_bindings=")
    folder = tmp_path_factory.mktemp("volume-mono-host")
    result = {}
    for kind in ("scope", "host"):
        fixture = (ROOT / f"tests/fixtures/mp4_volume_mono_{kind}.cpp.inc").read_text()
        actual = fixture.replace("// SHIPPING_VOLUME_MONO_SCOPE", scope)
        if kind == "host":
            actual = actual.replace("// SHIPPING_VOLUME_FACTORY_SCHEMAS", factory)
            actual = actual.replace("// SHIPPING_VOLUME_SOURCE_PINS", pins)
            actual = actual.replace("// SHIPPING_VOLUME_MONO_PINS_EXPORTS", pins_exports)
            actual = actual.replace("// SHIPPING_VOLUME_MONO_ADAPTER", adapter)
        source = folder / (kind + ".cpp")
        source.write_text(actual)
        binary = folder / kind
        compiled = subprocess.run(
            [compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
             "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
             "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
            text=True, capture_output=True, timeout=90,
        )
        assert compiled.returncode == 0, compiled.stdout + compiled.stderr
        result[kind] = binary
    return result


@pytest.mark.parametrize("mode", SCOPE_MODES)
def test_shipping_volume_mono_scope(binaries, mode):
    run(binaries["scope"], mode)


@pytest.mark.parametrize("mode", HOST_MODES)
def test_shipping_volume_mono_host(binaries, mode):
    run(binaries["host"], mode)


def run(binary, mode):
    result = subprocess.run(
        [str(binary), mode], text=True, capture_output=True, timeout=10,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
