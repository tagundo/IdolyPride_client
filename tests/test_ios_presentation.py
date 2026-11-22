import copy
import hashlib
from pathlib import Path
import re
import struct
import tracemalloc

import pytest

from idoly_local import ios_presentation as p

SCENE_APPENDED=('mp4_psyllium_execute','mp4_fixed_loop_condition','mp4_particle_simulate','mp4_live_particle_simulate','mp4_presenter_end','mp4_actor_update','mp4_actor_late','mp4_actor_eye_late','mp4_actor_face_late','mp4_actor_foot_apply','mp4_particle_control_simulate','mp4_actor_derived_late_ref','mp4_actor_derived_late_shared','mp4_equipment_late','mp4_photography_is_end','mp4_player_is_end','mp4_render_stack','mp4_render_camera','mp4_vlb_draw','mp4_selected_renderer','mp4_volume_update','mp4_material_ctor_shader','mp4_render_library_ctor','mp4_cine_apply','mp4_cine_game_object_ctor','mp4_cine_volume_enable','mp4_mirror_late','mp4_mirror_parameters','mp4_mirror_destroy','mp4_fog_enable','mp4_fog_disable','mp4_fog_late','mp4_context_submit','mp4_control_create','mp4_srp_add_precull','mp4_srp_invoke_precull','mp4_srp_begin_frame','mp4_shader_memory_sync','mp4_shader_memory_async','mp4_shader_file_async','mp4_shader_bundle_result','mp4_capture_update','mp4_capture_wrapper_ctor','mp4_capture_texture_ctor','mp4_capture_request','mp4_source_timeline_factory')


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
                                  0x94000000, 0xD65F03C0, 0xF9400200,
                                  0xB4000010, 0xB5000011])
def test_gateway_rejects_pc_relative_control_flow_and_x16_input(word):
    with pytest.raises(ValueError):
        p.gateway(0x10000, 0x220008, 0x20000, struct.pack("<I", word))


@pytest.mark.parametrize("opcode", [0x34000000, 0x35000000, 0xB4000000, 0xB5000000])
@pytest.mark.parametrize("immediate", [-(1 << 18), -1, 0, 4, (1 << 18) - 1])
def test_compare_branch_gateway_preserves_taken_and_fallthrough_targets(opcode, immediate):
    # The original conditional target is outside CBZ's range from the gateway.
    # A local conditional plus two unconditional branches preserves both paths.
    target, cave = 0x6E9F1E0, 0x97885B0
    word = opcode | ((immediate & 0x7FFFF) << 5) | 3
    code = p.gateway(cave, 0xAB8DA08, target, struct.pack("<I", word))
    words = struct.unpack("<8I", code)
    assert words[2:5] == (0xC8DFFE10, 0xB4000050, 0xD61F0200)
    assert words[5] & ~(0x7FFFF << 5) == word & ~(0x7FFFF << 5)
    assert cave + 20 + ((words[5] >> 5) & 0x7FFFF) * 4 == cave + 28
    assert signed_branch_target(cave + 24, words[6]) == target + 4
    assert signed_branch_target(cave + 28, words[7]) == target + immediate * 4


@pytest.mark.parametrize("item_pointer", [0, 0x10004000])
def test_original_cache_conditional_gateway_executes_both_paths(item_pointer):
    unicorn = pytest.importorskip("unicorn")
    from unicorn.arm64_const import UC_ARM64_REG_X3
    target, cave = 0x6E9F1E0, 0x97885B0
    code = p.gateway(cave, 0xAB8DA08, target, bytes.fromhex("830000b4"))
    engine = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    engine.ctl_set_tcg_buffer_size(16 * 1024 * 1024)
    for page in {target & ~4095, cave & ~4095}:
        engine.mem_map(page, 4096)
    engine.mem_write(cave, code)
    engine.reg_write(UC_ARM64_REG_X3, item_pointer)
    reached = []

    def stop(current, pc, _size, _data):
        if pc in (target + 4, target + 16):
            reached.append(pc)
            current.emu_stop()

    engine.hook_add(unicorn.UC_HOOK_CODE, stop)
    engine.emu_start(cave + 20, 0, count=8)
    assert reached == [target + (4 if item_pointer else 16)]
    assert engine.reg_read(UC_ARM64_REG_X3) == item_pointer


def test_canonical_ios_plan_binds_formal_header_and_zero_fill_slots():
    plan, profile = p.make_plan(), p.load_profile()
    header = p.render_header(plan)
    assert hashlib.sha256(header).hexdigest() == "b26e91b84ba1d5a5f2e3a616173512e5dd97579c373a79b0d507f3ec38ab2d82"
    assert header == (p.PROFILE.parent / "ios_profile.hpp").read_bytes()
    assert len(profile["aliases"]) == 183 and len(plan["entries"]) == 108
    data = profile["segments"]["__DATA"]
    for name, entry in plan["entries"].items():
        assert entry["slot"] >= max(data["section_end"], data["rva"] + data["filesize"])
        assert entry["slot"] + 8 <= data["rva"] + data["vmsize"]
        assert entry["original_callable"] == entry["gateway"] + 20
        code = bytes.fromhex(entry["gateway_hex"])
        words = struct.unpack("<" + str(len(code) // 4) + "I", code)
        if name == "shared_is_cached":
            assert len(code) == 32 and words[5] == 0xB4000043
            assert signed_branch_target(entry["gateway"] + 28, words[7]) == entry["rva"] + 16
        else:
            assert len(code) == 28
            assert struct.pack("<I", words[5]).hex() == entry["original16"][:8]
        assert signed_branch_target(entry["rva"], int.from_bytes(bytes.fromhex(entry["patched_entry"]), "little")) == entry.get("relay_in", entry["gateway"])
        assert signed_branch_target(entry["gateway"] + 24, words[6]) == entry.get("relay_out", entry["rva"] + 4)
        assert profile["aliases"][name]["rva"] == entry["rva"]


def test_two_new_gateways_preserve_every_previous_profile_byte_and_mapping():
    profile, plan = p.load_profile(), p.make_plan()
    appended=('mp4_native_time','mp4_brain_update','mp4_shader_set','mp4_shader_reset','mp4_actor_process','mp4_actor_burst',*SCENE_APPENDED)
    assert set(appended).issubset(profile['hook_names'])
    old = copy.deepcopy(profile)
    for name in appended:
        del old['aliases'][name]
        old['hook_names'].remove(name)
    old['gateway_region']['bytes'] -= len(appended)*32
    old['slot_region']['bytes'] -= len(appended)*8
    del old['native_relay_region']
    del old['native_extra_relay_regions']
    import json
    assert hashlib.sha256((json.dumps(old, indent=2) + '\n').encode()).hexdigest() == '09c3106f3aef9f04ca6464b224455cb5a5ffa27ab8ded24d182a65c891242cdc'
    for index, name in enumerate(old['hook_names']):
        entry, row = plan['entries'][name], old['aliases'][name]
        assert 'relay_in' not in entry
        assert entry['gateway'] == old['gateway_region']['rva'] + 32 * index
        assert entry['slot'] == old['slot_region']['rva'] + 8 * index
        assert entry['gateway_hex'] == p.gateway(entry['gateway'], entry['slot'], row['rva'], bytes.fromhex(row['prefix16'][:8])).hex()


def test_native_time_uses_native_abi_two_range_checked_relays_and_no_managed_slot():
    profile, plan = p.load_profile(), p.make_plan()
    row, entry = profile['aliases']['mp4_native_time'], plan['entries']['mp4_native_time']
    assert row['rva'] == 0xcad01c and row['prefix16'] == '086440f908050091086400f908d040b9'
    assert row['native_parameter_registers'] == {'manager': 'X0', 'nativeWallTimestamp': 'D0'}
    assert row['registration_pointer_slot_rva'] is None and row['module'] is None
    assert {'metadata_method_index', 'type_definition_index', 'token_row', 'method_flags'}.isdisjoint(row)
    assert entry['gateway'] == 0x9788750 and entry['slot'] == 0xab8da78
    assert (entry['relay_in'], entry['relay_out']) == (0x8610a44, 0x8610a48)
    assert signed_branch_target(entry['relay_in'], int.from_bytes(bytes.fromhex(entry['relay_in_hex']), 'little')) == entry['gateway']
    assert signed_branch_target(entry['relay_out'], int.from_bytes(bytes.fromhex(entry['relay_out_hex']), 'little')) == row['rva'] + 4
    with pytest.raises(ValueError, match='out of range'):
        p.branch(row['rva'], entry['gateway'])
    with pytest.raises(ValueError, match='out of range'):
        p.branch(entry['gateway'] + 24, row['rva'] + 4)
    brain = profile['aliases']['mp4_brain_update']
    assert brain['rva'] == 0x33e8410 and brain['metadata_method_index'] == 194079
    assert brain['type_definition_index'] == 28296 and brain['method_flags'] == 134
    assert brain['parameter_count'] == 0 and brain['return_type'] == 'System.Void'
    assert brain['registration_pointer_slot_rva'] == 0xa32a0d0


@pytest.mark.parametrize('field,value', [('relay_in', 0x8610a48), ('relay_out', 0x8610a4c),
                                        ('relay_in_hex', '00000014'), ('relay_out_hex', '00000014')])
def test_forged_native_relays_are_rejected_by_complete_plan_validation(field, value):
    plan = p.make_plan()
    plan['entries']['mp4_native_time'][field] = value
    with pytest.raises(ValueError, match='pinned original'):
        p.validate_plan(plan)


def relay_macho_fixture():
    raw = bytearray(1024)
    uuid = bytes(range(16))
    struct.pack_into('<II', raw, 0, 0xfeedfacf, 0x0100000c)
    struct.pack_into('<II', raw, 16, 2, 24 + 72 + 160)
    struct.pack_into('<II16s', raw, 32, 0x1b, 24, uuid)
    struct.pack_into('<II16s4Q4I', raw, 56, 0x19, 232, b'__TEXT', 0, 1024, 0, 1024, 5, 5, 2, 0)
    for index, (name, start, size) in enumerate(((b'__gcc_except_tab', 700, 100), (b'__const', 900, 100))):
        struct.pack_into('<16s16sQQ', raw, 128 + index * 80, name, b'__TEXT', start, size)
    profile = {'target': {'uuid': uuid.hex()}, 'native_relay_region': {
        'name':'mp4_native_time','original_zero':True,'rva': 800, 'bytes': 8, 'gap_begin': 800, 'gap_end': 900,
        'after_section': '__gcc_except_tab', 'before_section': '__const'}}
    return raw, profile


def test_native_relay_requires_original_uuid_rx_mapping_and_excluded_zero_gap():
    raw, profile = relay_macho_fixture()
    p._validate_native_relay(raw, profile)


@pytest.mark.parametrize('kind', ['uuid', 'protection', 'overlap', 'gap_boundary', 'nonzero', 'sections_bound', 'command_bound'])
def test_bad_relay_mapping_rejected_before_any_owned_buffer_write(monkeypatch, kind):
    raw, profile = relay_macho_fixture()
    if kind == 'uuid':
        raw[40] ^= 1
    elif kind == 'protection':
        struct.pack_into('<I', raw, 56 + 60, 3)
    elif kind == 'overlap':
        struct.pack_into('<Q', raw, 128 + 40, 108)
    elif kind == 'gap_boundary':
        profile['native_relay_region']['gap_end'] = 899
    elif kind == 'nonzero':
        raw[804] = 1
    elif kind == 'sections_bound':
        struct.pack_into('<I', raw, 56 + 64, 128)
    else:
        struct.pack_into('<I', raw, 56 + 4, 4096)
    profile['aliases'] = {}
    profile['gateway_region'] = {'rva': 1000, 'bytes': 24}
    monkeypatch.setattr(p, 'validate_plan', lambda _: None)
    monkeypatch.setattr(p, 'load_profile', lambda: profile)
    monkeypatch.setattr(p, 'SOURCE_SHA256', hashlib.sha256(raw).hexdigest())
    before = bytes(raw)
    with pytest.raises(ValueError):
        p.patch_presentation(raw, {'entries': {}, 'profile_header_sha256': 'a' * 64}, in_place=True)
    assert bytes(raw) == before


def test_shared_cache_hooks_preserve_real_settings_and_loader_boundaries():
    profile, plan = p.load_profile(), p.make_plan()
    aliases = profile["aliases"]
    hooks = {"shared_setup", "shared_is_cached", "shared_file_path",
             "shared_pre_download", "shared_downloader_update"}
    binds = {"shared_settings_set", "shared_bundle_item", "shared_resource_item",
             "shared_resource_filename", "shared_string_new"}
    assert hooks <= plan["entries"].keys()
    assert binds.isdisjoint(plan["entries"])
    assert aliases["shared_setup"]["parameters"][0]["type_name"] == "Octo.OctoFullSettings"
    assert aliases["shared_settings_set"]["rva"] == 0x6E7F580
    assert aliases["shared_settings_set"]["prefix16"].startswith("01e00039c0035fd6")
    assert aliases["shared_pre_download"]["parameters"][1]["type_name"] == "System.Action<Octo.DownloadError>"
    assert aliases["shared_pre_download"]["parameters"][3]["type_name"] == "System.Boolean"
    assert aliases["shared_resource_filename"]["name"] == "Octo.Loader.OctoResourceLoader.GetStorageFileName"
    assert aliases["shared_string_new"]["export_trie_and_symtab_agree"] is True
    installer = (p.PROFILE.parent / "static_install.hpp").read_text()
    assert installer.index("load_calls();") < installer.index("shared_cache_load_calls();")
    assert installer.index("shared_cache_load_calls();") < installer.index("__atomic_store_n")
    assert profile["shared_resource_cache"]["settings_caching_type_width_bytes"] == 1
    assert profile["shared_resource_cache"]["runtime_device_validation"] is False


def test_offline_mv_hooks_append_only_and_preserve_final_camera_value_type_abi():
    profile, plan = p.load_profile(), p.make_plan()
    hooks = ("mp4_presenter_update", "mp4_capture_pass", "mp4_end_camera")
    assert tuple(profile["hook_names"][46:49]) == hooks
    expected = ((0x30F1EE4, False, []),
                (0x76798D8, False, ["UnityEngine.Rendering.ScriptableRenderContext",
                                   "UnityEngine.Rendering.Universal.RenderingData&"]),
                (0x7884124, True, ["UnityEngine.Rendering.ScriptableRenderContext",
                                 "UnityEngine.Camera"]))
    for index, (name, (rva, is_static, parameters)) in enumerate(zip(hooks, expected), 46):
        method, gate = profile["aliases"][name], plan["entries"][name]
        assert method["rva"] == rva
        assert bool(method["method_flags"] & 0x10) is is_static
        assert [row["type_name"] for row in method["parameters"]] == parameters
        assert method["return_type"] == "System.Void"
        assert gate["gateway"] == profile["gateway_region"]["rva"] + index * 32
        assert gate["slot"] == profile["slot_region"]["rva"] + index * 8
        assert len(bytes.fromhex(gate["gateway_hex"])) == 28
    assert profile["offline_mv_export"]["runtime_device_validation"] is False


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
    assert profile["gateway_region"]["bytes"] == 108 * 32
    assert profile["slot_region"]["bytes"] == 108 * 8
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
    assert original["gateway_region"]["bytes"] == 108 * 32
    assert original["slot_region"]["bytes"] == 108 * 8
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


def test_new_stage_and_fixed_aliases_preserve_previous_sixty_two_mappings():
    profile,plan=p.load_profile(),p.make_plan();old=copy.deepcopy(profile)
    for name in SCENE_APPENDED:
        del old['aliases'][name];old['hook_names'].remove(name)
    old['gateway_region']['bytes']-=len(SCENE_APPENDED)*32;old['slot_region']['bytes']-=len(SCENE_APPENDED)*8
    del old['native_extra_relay_regions']
    import json
    assert hashlib.sha256((json.dumps(old,indent=2)+'\n').encode()).hexdigest()=='60ecc264edd253ed482519c1035264647c8e67b960fe5b3b99e1c909d9a309b0'
    for index,name in enumerate(old['hook_names']):
        assert plan['entries'][name]['gateway']==old['gateway_region']['rva']+32*index
        assert plan['entries'][name]['slot']==old['slot_region']['rva']+8*index
    fixed=profile['aliases']['mp4_fixed_loop_condition'];gate=plan['entries']['mp4_fixed_loop_condition']
    assert fixed['native_abi']=='bool(void)' and fixed['native_parameter_registers']=={}
    assert fixed['rva']==0xccc210 and fixed['registration_pointer_slot_rva'] is None
    assert (gate['relay_in'],gate['relay_out'])==(0x8610a4c,0x8610a50)
    assert profile['aliases']['mp4_psyllium_execute']['native_abi']=='void(void*,ScriptableRenderContext8,void*,const MethodInfo*)'
    assert profile['aliases']['mp4_particle_simulate']['native_abi']=='void(void*,float,bool,bool,bool,const MethodInfo*)'


@pytest.mark.parametrize('alias', list(SCENE_APPENDED))
def test_selected_stage_and_fixed_gateways_preserve_actual_native_argument_registers(alias):
    """Execute packaged replacement dispatch with real pointer/float ABI lanes."""
    unicorn=pytest.importorskip('unicorn')
    from unicorn import arm64_const as r
    profile,plan=p.load_profile(),p.make_plan();entry=plan['entries'][alias]
    handler=0x10001000;stack=0x10010000
    machine=unicorn.Uc(unicorn.UC_ARCH_ARM64,unicorn.UC_MODE_ARM)
    machine.ctl_set_tcg_buffer_size(16*1024*1024)
    pages={entry['rva']&~4095,entry['gateway']&~4095,entry['slot']&~4095,handler&~4095,stack}
    if 'relay_in' in entry:pages.add(entry['relay_in']&~4095)
    for page in pages:machine.mem_map(page,4096)
    machine.mem_write(entry['rva'],bytes.fromhex(entry['patched_entry']))
    machine.mem_write(entry['gateway'],bytes.fromhex(entry['gateway_hex']))
    machine.mem_write(entry['slot'],struct.pack('<Q',handler))
    if 'relay_in' in entry:
        for key in ('relay_in','relay_out'):machine.mem_write(entry[key],bytes.fromhex(entry[key+'_hex']))
    pointers=[0x22334400+index*0x100 for index in range(8)]
    vectors=[(0x1234567812345678<<64)|0x3f400000+index for index in range(8)]
    for index,value in enumerate(pointers):machine.reg_write(getattr(r,'UC_ARM64_REG_X'+str(index)),value)
    for index,value in enumerate(vectors):machine.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(index)),value)
    machine.reg_write(r.UC_ARM64_REG_SP,stack+4096)
    observed=[]
    def entered(current,pc,_size,_data):
        if pc==handler:
            observed.append(pc);current.emu_stop()
    machine.hook_add(unicorn.UC_HOOK_CODE,entered)
    machine.emu_start(entry['rva'],0,count=12)
    assert observed==[handler]
    for index,value in enumerate(pointers):assert machine.reg_read(getattr(r,'UC_ARM64_REG_X'+str(index)))==value
    for index,value in enumerate(vectors):assert machine.reg_read(getattr(r,'UC_ARM64_REG_Q'+str(index)))==value
    assert machine.reg_read(r.UC_ARM64_REG_SP)==stack+4096
