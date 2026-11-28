#!/usr/bin/env python3
"""Pin the original Video Creator's property calls and private Sync/Step sites.

These are original authored-programme call identities, not proof of a current
selected root, fresh script birth, decoder readiness or successful MP4 export.
"""
from pathlib import Path
import argparse
import hashlib
import json
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original, need

START = '// BEGIN_MP4_VIDEO_CREATOR_PINS'
END = '// END_MP4_VIDEO_CREATOR_PINS'
CALLS = (
    ('creator_skip', 'Solis.Timeline.SolisVideoPlayerTrack', 'CreateTrackMixer', 3, 'UnityEngine.Video.VideoPlayer', 'set_skipOnDrop'),
    ('creator_wait', 'Solis.Timeline.SolisVideoPlayerTrack', 'CreateTrackMixer', 3, 'UnityEngine.Video.VideoPlayer', 'set_waitForFirstFrame'),
    ('creator_awake', 'Solis.Timeline.SolisVideoPlayerTrack', 'CreateTrackMixer', 3, 'UnityEngine.Video.VideoPlayer', 'set_playOnAwake'),
    ('creator_loop', 'Solis.Timeline.SolisVideoPlayerTrack', 'CreateTrackMixer', 3, 'UnityEngine.Video.VideoPlayer', 'set_isLooping'),
    ('sync_time', 'Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'SyncVideoToPlayable', 1, 'UnityEngine.Video.VideoPlayer', 'set_time'),
    ('sync_external', 'Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'SyncVideoToPlayable', 1, 'UnityEngine.Video.VideoPlayer', 'set_externalReferenceTime'),
    ('update_step', 'Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'UpdateVideo', 2, 'UnityEngine.Video.VideoPlayer', 'StepForward'),
    ('update_sync', 'Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'UpdateVideo', 2, 'Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'SyncVideoToPlayable'),
)
CALLBACKS = ('LoopPointReached', 'PrepareCompleted', 'SeekCompleted', 'ErrorReceived')


def body(original, method):
    count, table = original.module(method['module'])
    address = int(method['rva'], 16)
    following = min(p for i in range(count) if (p := original.qword(table + i * 8)) > address)
    code = original.b[original.offset(address):original.offset(address) + following - address]
    return list(Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN).disasm(code, address))


def build(original, platform):
    calls = {}
    for role, owner, method, argc, target_owner, target in CALLS:
        caller = original.method(owner, method, argc)
        callee = original.method(target_owner, target, 0 if role == 'update_step' else 1)
        target_address = int(callee['rva'], 16)
        instructions = body(original, caller)
        matches = [i for i in instructions if i.mnemonic == 'bl' and i.op_str == f'#{hex(target_address)}']
        tail = None
        if platform == 'android' and role.startswith('sync_'):
            intermediate = original.method(owner, 'set_VideoTime', 1)
            address = int(intermediate['rva'], 16)
            matches = [i for i in instructions if i.mnemonic == 'bl' and i.op_str == f'#{hex(address)}']
            tails = [i for i in body(original, intermediate) if i.mnemonic == 'b' and i.op_str == f'#{hex(target_address)}']
            need(len(tails) == 1, 'video_sync_tail_differs:' + role)
            tail = {'intermediate': intermediate['rva'], 'tail_rva': hex(tails[0].address), 'tail_bytes': tails[0].bytes.hex()}
        need(len(matches) == 1, 'video_exact_call_ambiguous:' + role)
        instruction = matches[0]
        calls[role] = {'caller': caller, 'callee': callee, 'call_rva': hex(instruction.address),
                       'return_rva': hex(instruction.address + 4), 'bytes': instruction.bytes.hex(), 'tail': tail}
    callbacks = [original.method('Solis.Timeline.SolisVideoPlayerTrackBehaviour', name, 2 if name == 'ErrorReceived' else 1) for name in CALLBACKS]
    return {'sources': {'metadata_sha256': hashlib.sha256(original.m).hexdigest(), 'native_sha256': hashlib.sha256(original.b).hexdigest()},
            'calls': calls, 'callbacks': callbacks}


def render(profiles):
    lines = [START, 'struct Mp4VideoCreatorPins {uintptr_t returns[8];uint32_t calls[8];mp4camp::Binding callbacks[4];};']
    for platform in ('android', 'ios'):
        row = profiles[platform]
        calls = [row['calls'][role] for role, *_ in CALLS]
        returns = ','.join(item['return_rva'] for item in calls)
        words = ','.join(hex(int.from_bytes(bytes.fromhex(item['bytes']), 'little')) for item in calls)
        callbacks = ','.join('{' + item['rva'] + ',{' + ','.join(hex(v) for v in bytes.fromhex(item['prefix'])) + '}}' for item in row['callbacks'])
        lines.append('[[maybe_unused]] inline constexpr Mp4VideoCreatorPins mp4_video_' + platform + '_creator_pins={{' + returns + '},{' + words + '},{' + callbacks + '}};')
    lines += ['#ifdef IDOLY_DARWIN_BRIDGE', 'constexpr const auto&mp4_video_creator_pins=mp4_video_ios_creator_pins;',
              '#else', 'constexpr const auto&mp4_video_creator_pins=mp4_video_android_creator_pins;', '#endif', END]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    profiles = {}
    for platform, cls, native in [('android', OriginalAndroid, 'android-native.so'), ('ios', Original, 'ios-native.bin')]:
        profiles[platform] = build(cls((args.originals / (platform + '-metadata.dat')).read_bytes(), (args.originals / native).read_bytes()), platform)
    args.evidence.write_text(json.dumps(profiles, indent=2) + '\n')
    args.output.write_text(render(profiles))
    print('PASS original Video Creator/Sync/Step callsites; no runtime export claim')


if __name__ == '__main__':
    main()
