#!/usr/bin/env python3
"""Audit all appended iOS scene gateways against whole pinned original inputs.

Only small derived evidence is written. Neither original executable nor a
patched executable is published. This does not execute an iOS application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from idoly_local import ios_presentation as p
from idoly_local.native_bootstrap import patch_native
from audit_mp4_ios_game import Original

OLD_PROFILE_SHA256 = '09c3106f3aef9f04ca6464b224455cb5a5ffa27ab8ded24d182a65c891242cdc'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def preserved_ranges(before, after, entries):
    ranges = []
    for row in entries.values():
        ranges += [(row['rva'], row['rva'] + 4),
                   (row['gateway'], row['gateway'] + len(bytes.fromhex(row['gateway_hex'])))]
        if 'relay_in' in row:
            ranges += [(row['relay_in'], row['relay_in'] + 4),
                       (row['relay_out'], row['relay_out'] + 4)]
    cursor, compared = 0, 0
    left, right = memoryview(before), memoryview(after)
    for lo, hi in sorted(ranges):
        assert cursor <= lo < hi <= len(before), 'overlapping_or_invalid_write'
        assert left[cursor:lo] == right[cursor:lo], 'unrelated_native_bytes_changed'
        compared += lo - cursor
        cursor = hi
    assert left[cursor:] == right[cursor:], 'unrelated_native_tail_changed'
    return compared + len(before) - cursor


def audit(native_path, metadata_path):
    native, metadata = Path(native_path).read_bytes(), Path(metadata_path).read_bytes()
    original = Original(metadata, native)  # Whole SHA + metadata version + registrations.
    profile, plan = p.load_profile(), p.make_plan()
    old = json.loads(json.dumps(profile))
    from audit_mp4_scene_aliases import SELECTIONS,DERIVED_ALIASES
    appended=('mp4_native_time','mp4_brain_update','mp4_shader_set','mp4_shader_reset','mp4_actor_process','mp4_actor_burst','mp4_fixed_loop_condition',*SELECTIONS,*DERIVED_ALIASES)
    for name in appended:
        del old['aliases'][name]
        old['hook_names'].remove(name)
    old['gateway_region']['bytes'] -= len(appended)*32
    old['slot_region']['bytes'] -= len(appended)*8
    del old['native_relay_region']
    del old['native_extra_relay_regions']
    assert digest((json.dumps(old, indent=2) + '\n').encode()) == OLD_PROFILE_SHA256
    clock = json.loads((ROOT / 'client-presentation/native/mp4_engine_clock_profile.json').read_text())['platforms']['ios']
    update = clock['bindings']['update']
    address, body = int(update['rva'], 16), bytes.fromhex(update['body'])
    assert clock['source']['native_sha256'] == digest(native)
    assert native[original.offset(address):original.offset(address) + len(body)] == body
    assert profile['aliases']['mp4_native_time']['rva'] == address
    assert profile['aliases']['mp4_native_time']['prefix16'] == body[:16].hex()
    assert profile['aliases']['mp4_native_time']['registration_pointer_slot_rva'] is None
    brain = original.method('Cinemachine.CinemachineBrain', 'ManualUpdate', 0)
    brain_row = profile['aliases']['mp4_brain_update']
    tid = original.type_id(brain['type'])
    method = struct.unpack_from('<7I4H', metadata, original.h[12] + brain['metadata_method_index'] * 36)
    assert brain_row == {
        'name': brain['type'] + '.' + brain['name'], 'module': brain['module'],
        'type_definition_index': tid, 'metadata_method_index': brain['metadata_method_index'],
        'token_row': brain['token_row'], 'rva': int(brain['rva'], 16),
        'return_type_index': method[2], 'parameters': [], 'parameter_count': 0,
        'method_flags': method[7], 'return_type': brain['return'],
        'registration_pointer_slot_rva': int(brain['registration_pointer_slot'], 16),
        'prefix16': brain['prefix']}
    from audit_mp4_scene_aliases import derive,SELECTIONS
    for alias in (*SELECTIONS,*DERIVED_ALIASES):assert profile['aliases'][alias]==derive(original,'ios',alias)
    from audit_mp4_world import build as world_profile
    world=world_profile(Path(native_path).parent,'ios')
    fixed=world['native']['fixed_condition'];row=profile['aliases']['mp4_fixed_loop_condition']
    assert row['rva']==int(fixed['rva'],16) and row['prefix16']==fixed['prefix']
    assert row['native_abi']=='bool(void)' and row['registration_pointer_slot_rva'] is None
    assert (ROOT / 'client-presentation/ios/ios_profile.hpp').read_bytes() == p.render_header(plan)
    p._validate_native_relay(native, profile)
    patched, original_report = p.patch_presentation(native, plan)
    unchanged_original = preserved_ranges(native, patched, plan['entries'])
    del patched
    bootstrap, bootstrap_report = patch_native(native, 'ios', mutable_output=True)
    assert type(bootstrap) is bytearray and digest(bootstrap) == p.BOOTSTRAP_SHA256
    p._validate_native_relay(bootstrap, profile)
    # Keep one original snapshot for exact unrelated-byte comparison; use the
    # in-place path required by the memory-bounded IPA packager.
    bootstrap_before = bytes(bootstrap)
    output, composed_report = p.patch_presentation(bootstrap, plan,
        bootstrap_report=bootstrap_report, in_place=True)
    assert output is bootstrap
    unchanged_bootstrap = preserved_ranges(bootstrap_before, output, plan['entries'])
    return {
        'schema': 1, 'source_native_sha256': digest(native),
        'source_metadata_sha256': digest(metadata), 'native_bytes': len(native),
        'profile_sha256': p.PROFILE_SHA256, 'header_sha256': plan['profile_header_sha256'],
        'old_profile_sha256_unchanged': OLD_PROFILE_SHA256,
        'aliases': len(profile['aliases']), 'hooks': len(plan['entries']),
        'original_native_update_body_bytes': len(body),
        'original_native_update_body_sha256': digest(body),
        'native_update_abi': clock['native_abi'],
        'brain_original_metadata_method_index': brain['metadata_method_index'],
        'native_time_gateway': plan['entries']['mp4_native_time'],
        'brain_update_gateway': plan['entries']['mp4_brain_update'],
        'original_patch': original_report, 'bootstrap_composition': composed_report,
        'unrelated_original_bytes_preserved': unchanged_original,
        'unrelated_bootstrap_bytes_preserved': unchanged_bootstrap,
        'original_and_bootstrap_rx_relay_gap_zero': True,
        'all_previous_56_gateway_mappings_unchanged': True,
        'patched_executables_published': False, 'runtime_device_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--metadata', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.native, args.metadata)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'output_sha256': digest(args.output.read_bytes()),
                      'aliases': report['aliases'], 'hooks': report['hooks']}))


if __name__ == '__main__':
    main()
