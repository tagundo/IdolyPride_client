#!/usr/bin/env python3
"""Reproduce the finite Timeline Actor source pins from both unchanged clients.

No game execution or callback/state ownership is inferred from this static audit.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    'track': 'VL.Timeline.VLAnimationClipPlayerTimelineTrack',
    'asset': 'VL.Timeline.VLAnimationClipPlayerTimelineAsset',
    'track_playable': 'VL.Timeline.VLAnimationClipPlayerTimelineTrackPlayable',
    'mixer': 'VL.Timeline.VLAnimationClipPlayerTimelineMixerPlayable',
    'clip': 'VL.Timeline.VLAnimationClipPlayerTimelineClipPlayable',
}
EXTRA = [
    ('VL.Core.VLActorController', 'SetTimelineWeight', 1),
    ('VL.Core.VLActorController', 'ResetModel', 0),
    *[('VL.VLAnimationClipPlayer', name, count) for name, count in [
        ('GetTimelinePlayable', 0), ('CreateTimelineMixer', 1),
        ('CreateTimelineClip', 3), ('DestroyTimelineMixer', 0),
        ('GetTimelineWeight', 0), ('SetTimelineWeight', 1),
        ('SetTimelineDelay', 1), ('Setup', 0)]],
    ('Solis.Common.SolisActorController', 'ResetModel', 0),
    ('VL.VLActorActorSwing', 'Reset', 0),
]

def derive(originals: Path, platform: str):
    from audit_mp4_world import whole
    from audit_mp4_actor_state import runtime_type
    original, _, _ = whole(originals, platform)
    methods = []
    types = {}
    for role, owner in ROLES.items():
        types[role] = runtime_type(original, owner, 18)
        row = original.types[original.type_id(owner)][1]
        for mid in range(row[9], row[9] + row[16]):
            method = struct.unpack_from('<7I4H', original.m, original.h[12] + mid * 36)
            methods.append(original.method(owner, original.string(method[0]), method[10]))
    for owner, name, count in EXTRA:
        methods.append(original.method(owner, name, count))
    methods = list({m['rva']: m for m in methods}.values())
    assert len(methods) == 40, 'timeline_actor_callback_cohort_changed'
    fields = {name: original.fields(name) for name in ROLES.values()}
    assert fields[ROLES['track_playable']]['_player']['offset'] == 16
    assert fields[ROLES['track_playable']]['_playerPlayable']['offset'] == 24
    assert fields[ROLES['asset']]['motion']['offset'] == 24
    assert fields[ROLES['asset']]['exposedMotion']['offset'] == 32
    assert fields[ROLES['asset']]['applyFootIK']['offset'] == 48
    assert original.fields('Solis.Common.SolisActorController')['_actorSwing']['offset'] == 376
    metadata = 0x96dd758 if platform == 'android' else 0x9c1deb8
    registration = [original.qword(metadata + i * 8) for i in range(16)]
    slot = 0x9a09bc0 if platform == 'android' else 0xa454888
    usage = original.qword(slot) if platform == 'android' else slot
    encoded = original.qword(usage)
    index = (encoded & 0x1fffffff) >> 1
    assert (encoded >> 29) & 7 == 6 and index < registration[8]
    spec = struct.unpack_from('<3i', original.b, original.offset(registration[9]) + index * 12)
    instance = original.qword(registration[3] + spec[2] * 8)
    argc = struct.unpack_from('<I', original.b, original.offset(instance))[0]
    args = original.qword(instance + 8)
    arguments = [original.decode(original.qword(args + i * 8)) for i in range(argc)]
    assert arguments == ['VL.Core.VLActorController'], 'timeline_actor_seek_receiver_changed'
    slots = {}
    for name, owner, argc in [('Setup', 'VL.VLAnimationClipPlayer', 0), ('SetTimelineWeight', 'VL.VLAnimationClipPlayer', 1), ('ResetModel', 'VL.Core.VLActorController', 0)]:
        method = original.method(owner, name, argc)
        row = struct.unpack_from('<7I4H', original.m, original.h[12] + method['metadata_method_index'] * 36)
        slots[name] = 0x138 + 16 * row[9]
    assert slots == {'Setup': 0x178, 'SetTimelineWeight': 0x1c8, 'ResetModel': 0x408}
    return {
        'sources': {'metadata_sha256': hashlib.sha256(original.m).hexdigest(), 'native_sha256': hashlib.sha256(original.b).hexdigest()},
        'callbacks': methods, 'types': types, 'fields': fields,
        'seek_receiver': {'input_slot': hex(slot), 'usage_cell': hex(usage),
                          'encoded': hex(encoded), 'method_spec_index': index,
                          'method_spec': list(spec), 'arguments': arguments},
        'virtual_offsets': slots,
    }

def verify_bridge(proof, bridge):
    for platform, row in proof['platforms'].items():
        marker = 'mp4_timeline_actor_' + platform + '_callbacks'
        block = bridge[bridge.index(marker):]
        block = block[block.index('=') + 1:block.index(';')]
        actual = {(int(rva, 16), bytes(int(v, 16) for v in re.findall(r'0x[0-9a-f]+', prefix)))
                  for rva, prefix in re.findall(r'\{\s*(0x[0-9a-f]+)\s*,\s*\{([^}]+)\}\}', block)}
        expected = {(int(m['rva'], 16), bytes.fromhex(m['prefix'])) for m in row['callbacks']}
        assert actual == expected, 'timeline_actor_shipping_pins_differ:' + platform

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-bridge', type=Path)
    args = parser.parse_args()
    result = {'schema': 1, 'scope': 'immutable-source-only; not callback/state execution proof',
              'platforms': {p: derive(args.originals, p) for p in ('android', 'ios')}}
    if args.verify_bridge:
        verify_bridge(result, args.verify_bridge.read_text())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Both original Timeline Actor cohorts and closed seek receiver verified.')

if __name__ == '__main__':
    main()
