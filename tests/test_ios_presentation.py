import copy
import hashlib
from pathlib import Path
import re
import struct
import tracemalloc

import pytest

from idoly_local import ios_presentation as p


def signed_branch_target(source, instruction):
    assert instruction >> 26 == 0b000101
    value = instruction & 0x3FFFFFF
    if value & (1 << 25):
        value -= 1 << 26
    return source + value * 4


@pytest.mark.parametrize("delta", [-(1 << 27), -4, 0, 4, (1 << 27) - 4])
def test_branch_roundtrips_signed_extremes(delta):
    source = 0x10000000
    assert signed_branch_target(source, p.branch(source, source + delta)) == source + delta


@pytest.mark.parametrize("delta", [-(1 << 27) - 4, (1 << 27), 1, -1])
def test_branch_rejects_range_and_alignment(delta):
    with pytest.raises(ValueError):
        p.branch(0x10000000, 0x10000000 + delta)


def test_gateway_proves_null_fallback_and_original_continuation():
    # LDAR pointer, CBZ skips BR to displaced SUB, then B to original+4.
    code = p.gateway(0x10000, 0x220008, 0x20000, bytes.fromhex("ff0301d1"))
    words = struct.unpack("<7I", code)
    assert words[2:5] == (0xC8DFFE10, 0xB4000050, 0xD61F0200)
    assert 0x10000 + 12 + ((words[3] >> 5) & 0x7FFFF) * 4 == 0x10000 + 20
    assert code[20:24] == bytes.fromhex("ff0301d1")
    assert signed_branch_target(0x10000 + 24, words[6]) == 0x20004


@pytest.mark.parametrize("word", [0x90000000, 0x10000000, 0x58000000, 0x14000000,
                                  0x94000000, 0xD65F03C0, 0xF9400200])
def test_gateway_rejects_pc_relative_control_flow_and_x16_input(word):
    with pytest.raises(ValueError):
        p.gateway(0x10000, 0x220008, 0x20000, struct.pack("<I", word))


def test_canonical_ios_plan_binds_formal_header_and_zero_fill_slots():
    plan, profile = p.make_plan(), p.load_profile()
    header = p.render_header(plan)
    assert hashlib.sha256(header).hexdigest() == "4c83244481923fdaa2f97ad31118f4f1dd545aa1177ed1327d8d4085f99feea3"
    assert header == (p.PROFILE.parent / "ios_profile.hpp").read_bytes()
    assert len(profile["aliases"]) == 111 and len(plan["entries"]) == 41
    data = profile["segments"]["__DATA"]
    for name, entry in plan["entries"].items():
        assert entry["slot"] >= max(data["section_end"], data["rva"] + data["filesize"])
        assert entry["slot"] + 8 <= data["rva"] + data["vmsize"]
        assert entry["original_callable"] == entry["gateway"] + 20
        words = struct.unpack("<7I", bytes.fromhex(entry["gateway_hex"]))
        assert struct.pack("<I", words[5]).hex() == entry["original16"][:8]
        assert signed_branch_target(entry["rva"], int.from_bytes(bytes.fromhex(entry["patched_entry"]), "little")) == entry["gateway"]
        assert profile["aliases"][name]["rva"] == entry["rva"]


def test_desktop_orientation_contract_preserves_original_task_and_input_getters():
    profile, plan = p.load_profile(), p.make_plan()
    aliases = profile["aliases"]
    for name in ("rotation_wait", "rotation_wait_label", "rotation_wait_simple", "rotation_wait_preview"):
        assert aliases[name]["return_type"] == "Cysharp.Threading.Tasks.UniTask"
        assert aliases[name]["parameters"][-1]["type_name"] == "System.Threading.CancellationToken"
        assert name in plan["entries"]
    assert aliases["rotation_wait_label"]["parameters"][1]["type_name"] == "System.String"
    assert aliases["rotation_wait_simple"]["parameters"][1]["type_name"] == "System.Boolean"
    assert aliases["rotation_wait_preview"]["parameters"][1]["type_name"] == "System.Boolean"
    assert aliases["orientation_token_cancelled"]["return_type"] == "System.Boolean"
    assert aliases["orientation_internal_move"]["name"].endswith("<InternalSetOrientationAsync>d__24.MoveNext")
    assert all(name not in plan["entries"] for name in ("screen_width", "screen_height", "orientation_set_async"))
    assert not any("Input.get_deviceOrientation" in a["name"] for a in aliases.values())
    assert profile["orientation_adapter"]["minimum_original_Unity_frames_before_ready"] == 2
    assert aliases["aspect_reset"]["name"] == "UnityEngine.Camera.ResetAspect"
    assert aliases["mv_ui_initialize"]["name"] == "Solis.OutGame.LivePlayerUIView.Initialize"
    assert aliases["mv_ui_hide"]["parameter_count"] == 2


def test_shared_preview_UI_default_is_scoped_to_original_bind_and_reactive_model():
    profile, plan = p.load_profile(), p.make_plan()
    aliases = profile["aliases"]
    assert aliases["preview_ui_bind"]["name"] == "Solis.Photography.PhotographyPreviewContentPresenter.Bind"
    assert aliases["preview_ui_bind"]["parameter_count"] == 0
    assert "preview_ui_bind" in plan["entries"]
    assert aliases["preview_ui_get"]["name"] == "Solis.Photography.PhotographyPreviewContentModel.get_IsUIActive"
    assert aliases["preview_ui_set"]["name"] == "Solis.Photography.PhotographyPreviewContentModel.set_IsUIActive"
    assert aliases["preview_ui_set"]["parameters"][0]["type_name"] == "System.Boolean"
    assert "preview_ui_get" not in plan["entries"] and "preview_ui_set" not in plan["entries"]
    assert profile["preview_default_off"]["UI_On_and_Off_original_handlers_retained"] is True
    assert profile["preview_default_off"]["paid_capture_and_selection_menus_changed"] is False


def test_costume_sort_uses_original_typed_method_and_appends_one_static_gateway():
    profile, plan = p.load_profile(), p.make_plan()
    aliases = profile["aliases"]
    for name, rva, row in (("costume_sorted", 0x1DDCE78, 61471),
                           ("costume_order_sorted", 0x1DDCF98, 61472)):
        method = aliases[name]
        assert method["rva"] == rva and method["token_row"] == row
        assert method["type_definition_index"] == 12828
        assert method["parameter_count"] == 1 and method["method_flags"] & 0x10 == 0
        assert method["parameters"] == [{"name": "characterId", "metadata_type_index": 74127,
                                           "type_name": "System.String"}]
        assert method["return_type_index"] == 25377
        assert method["prefix16"] == "f85fbca9f65701a9f44f02a9fd7b03a9"
    assert "costume_sorted" in plan["entries"] and "costume_order_sorted" not in plan["entries"]
    hook = plan["entries"]["costume_sorted"]
    assert hook["gateway"] == profile["gateway_region"]["rva"] + 31 * 32
    assert hook["slot"] == profile["slot_region"]["rva"] + 31 * 8
    assert profile["gateway_region"]["bytes"] == 41 * 32
    assert profile["slot_region"]["bytes"] == 41 * 8
    assert profile["media_costume_sort"]["same_character_predicate"] is True
    assert profile["media_costume_sort"]["account_data_or_acquisition_timestamps_changed"] is False
    installer = (p.PROFILE.parent / "static_install.hpp").read_text()
    installed = re.findall(r"HOOK\((\w+),", installer)
    assert set(installed) - {"entry"} == set(plan["entries"])


def test_plan_mutation_and_unrecognized_native_are_rejected_before_patch():
    original = p.make_plan()
    for mutate in (lambda x: x["entries"]["q_set"].update(slot=1),
                   lambda x: x.update(schema=True), lambda x: x.update(unknown=True),
                   lambda x: x.update(source_unity_sha256="0" * 64)):
        changed = copy.deepcopy(original)
        mutate(changed)
        with pytest.raises(ValueError):
            p.validate_plan(changed)
    with pytest.raises(ValueError, match="requires the original"):
        p.patch_presentation(b"not a UnityFramework", original)


def test_prepare_preserves_existing_output_and_dangling_links(tmp_path):
    header = tmp_path / "ios_profile.hpp"
    header.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="unused"):
        p.prepare_presentation(tmp_path / "unread-input.ipa", tmp_path / "plan.json", header)
    assert header.is_symlink() and not (tmp_path / "plan.json").exists()


def test_gateway_and_slot_declared_extents_cover_every_hook(monkeypatch):
    original = p.load_profile()
    assert original["gateway_region"]["bytes"] == 41 * 32
    assert original["slot_region"]["bytes"] == 41 * 8
    for region, length in (("gateway_region", 32 * 32), ("slot_region", 32 * 8)):
        changed = copy.deepcopy(original)
        changed[region]["bytes"] = length
        monkeypatch.setattr(p, "load_profile", lambda: changed)
        with pytest.raises(ValueError, match="Gateway would overlap"):
            p.make_plan()


def mutable_patch_fixture(monkeypatch, *, size=512):
    """Small typed-profile substitute to exercise write ownership and ordering."""
    raw = bytearray(b'\xaa' * size)
    raw[32:48] = bytes(range(16)); raw[64:80] = bytes(range(16, 32))
    struct.pack_into('<QQ', raw, 128, 32, 64)
    raw[192:256] = b'\0' * 64
    profile = {'aliases': {
        'first': {'rva': 32, 'prefix16': raw[32:48].hex(), 'registration_pointer_slot_rva': 128},
        'last': {'rva': 64, 'prefix16': raw[64:80].hex(), 'registration_pointer_slot_rva': 136},
    }, 'gateway_region': {'rva': 192, 'bytes': 64}}
    plan = {'entries': {
        name: {'rva': offset, 'patched_entry': '00000014', 'gateway': 192+32*n,
               'gateway_hex': bytes(range(28)).hex()}
        for n, (name, offset) in enumerate((('first', 32), ('last', 64)))
    }, 'profile_header_sha256': 'a' * 64}
    monkeypatch.setattr(p, 'validate_plan', lambda _: None)
    monkeypatch.setattr(p, 'load_profile', lambda: profile)
    monkeypatch.setattr(p, 'SOURCE_SHA256', hashlib.sha256(raw).hexdigest())
    return bytes(raw), profile, plan


def test_in_place_owned_output_matches_immutable_default_without_native_sized_copy(monkeypatch):
    raw, _, plan = mutable_patch_fixture(monkeypatch, size=1024*1024)
    original = bytearray(raw)
    expected, expected_report = p.patch_presentation(original, plan)
    assert type(expected) is bytes and original == raw
    owned = bytearray(raw)
    tracemalloc.start()
    result, report = p.patch_presentation(owned, plan, in_place=True)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result is owned and type(result) is bytearray
    assert result == expected and report == expected_report
    assert original == raw and peak < 64*1024


@pytest.mark.parametrize('kind', ['late_prefix', 'registration', 'slack', 'late_code', 'late_bounds'])
def test_in_place_rejections_leave_all_caller_owned_bytes_unchanged(monkeypatch, kind):
    raw, profile, plan = mutable_patch_fixture(monkeypatch)
    owned = bytearray(raw)
    if kind == 'late_prefix':
        profile['aliases']['last']['prefix16'] = '00' * 16
    elif kind == 'registration':
        profile['aliases']['last']['registration_pointer_slot_rva'] = 128
    elif kind == 'slack':
        owned[224] = 1
        monkeypatch.setattr(p, 'SOURCE_SHA256', hashlib.sha256(owned).hexdigest())
    elif kind == 'late_code':
        plan['entries']['last']['gateway_hex'] = 'not hex'
    else:
        plan['entries']['last']['gateway'] = len(owned) - 1
    before = bytes(owned)
    with pytest.raises(ValueError):
        p.patch_presentation(owned, plan, in_place=True)
    assert owned == before


def test_in_place_requires_explicit_boolean_and_owned_bytearray_before_validation():
    for value in (b'not owned', memoryview(b'not owned')):
        with pytest.raises(ValueError, match='owned bytearray'):
            p.patch_presentation(value, {}, in_place=True)
    for value in (1, 'yes', None):
        with pytest.raises(ValueError, match='boolean'):
            p.patch_presentation(bytearray(), {}, in_place=value)
