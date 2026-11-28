#!/usr/bin/env python3
"""Pin original VideoPlayer transfer/update and queued callback drain entries.

The source-native ARM fixtures establish transfer/event/drain CPU ordering.
These pins do not claim a codec/GPU/MP4 result or authorize arbitrary players.
"""
from pathlib import Path
import argparse
import hashlib
import json
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from audit_mp4_world import whole

START = '// BEGIN_MP4_VIDEO_NATIVE_PINS'
END = '// END_MP4_VIDEO_NATIVE_PINS'
ENTRIES = {'android': {'update': 0xb7adc8, 'drain': 0xb7f944, 'transfer': 0xb78364, 'stop':0xb7b9c0},
           'ios': {'update': 0x114af88, 'drain': 0x114fd7c, 'transfer':0x11479a0, 'stop':0x114bc18}}


def build(originals, platform):
    _, raw, offset = whole(originals, platform)
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    methods = {}
    for name, address in ENTRIES[platform].items():
        code = raw[offset(address):offset(address) + (0x1e0 if name == 'update' else 0x8c)]
        rows = [{'rva':hex(i.address), 'bytes':i.bytes.hex(), 'asm':i.mnemonic + ' ' + i.op_str} for i in decoder.disasm(code, address)]
        methods[name] = {'rva':hex(address), 'prefix':code[:16].hex(), 'native_abi':('void(void*,uint8_t*)' if name == 'update' else 'bool(void*,void*,int64_t*,uint8_t*)' if name == 'transfer' else 'void(void*)'), 'instructions':rows}
        if name == 'update':
            assert any(i['asm'] == 'strb wzr, [x1]' for i in rows[:8])
            assert any(i['asm'] == 'mov x3, x20' for i in rows)
    # Update's final call drains scripting invocations after its transfer and
    # backend post-update branches. Source changes must be investigated anew.
    drain = ENTRIES[platform]['drain']
    assert any(i['asm'] == 'bl #' + hex(drain) for i in methods['update']['instructions'])
    assert any('[x19, #0x98]' in i['asm'] or '[x20, #0x98]' in i['asm'] for i in methods['drain']['instructions'])
    calls = {}
    for name in ('transfer','drain'):
        matches = [i for i in methods['update']['instructions'] if i['asm'] == 'bl #' + hex(ENTRIES[platform][name])]
        assert len(matches) == 1
        calls[name] = {'return_rva':hex(int(matches[0]['rva'],16)+4), 'bytes':matches[0]['bytes']}
    return {'native_sha256':hashlib.sha256(raw).hexdigest(), 'methods':methods, 'calls':calls,
            'layout':{'cached_ptr':16, 'backend':0x40, 'queue_begin':0x98, 'queue_end':0xa0, 'queue_stride':0x130}}


def render(profiles):
    lines = [START, 'struct Mp4VideoNativePins {const char*sha256;mp4camp::Binding update,drain,transfer,stop;uintptr_t transfer_return,drain_return;};']
    for platform in ('android','ios'):
        row = profiles[platform]
        bindings = []
        for name in ('update','drain','transfer','stop'):
            method = row['methods'][name]
            bindings.append('{' + method['rva'] + ',{' + ','.join(hex(v) for v in bytes.fromhex(method['prefix'])) + '}}')
        lines.append('[[maybe_unused]] inline constexpr Mp4VideoNativePins mp4_video_' + platform + '_native_pins={' + json.dumps(row['native_sha256']) + ',' + ','.join(bindings) + ',' + row['calls']['transfer']['return_rva'] + ',' + row['calls']['drain']['return_rva'] + '};')
    lines += ['#ifdef IDOLY_DARWIN_BRIDGE', 'constexpr const auto&mp4_video_native_pins=mp4_video_ios_native_pins;',
              '#else','constexpr const auto&mp4_video_native_pins=mp4_video_android_native_pins;','#endif',END]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    profiles = {p:build(args.originals,p) for p in ('android','ios')}
    args.evidence.write_text(json.dumps(profiles,indent=2)+'\n')
    args.output.write_text(render(profiles))
    print('PASS original Video update/drain pins; no codec/GPU/export runtime claim')


if __name__ == '__main__':
    main()
