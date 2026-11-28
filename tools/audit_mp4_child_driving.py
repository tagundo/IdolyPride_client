#!/usr/bin/env python3
"""Re-derive finite shipping DirectorControl ABI/source24 and nested branches.

Whole original cohorts are external audit inputs. This does not install hooks,
run native callbacks, certify source ownership, or claim a completed MP4.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

from audit_mp4_world import whole

ROOT = Path(__file__).resolve().parents[1]
CLASS = 'UnityEngine.Timeline.DirectorControlPlayable'
SELECT = (
    ('PrepareFrame', ('UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData')),
    ('OnBehaviourPlay', ('UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData')),
    ('OnBehaviourPause', ('UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData')),
    ('ProcessFrame', ('UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData', 'System.Object')),
    ('UpdateTime', ('UnityEngine.Playables.Playable',)),
    ('SyncStart', ('UnityEngine.Playables.PlayableGraph', 'System.Double')),
    ('SyncStop', ('UnityEngine.Playables.PlayableGraph', 'System.Double')),
)


def pins(text, platform):
    body = text.split('mp4_child_driving_hooks_' + platform + '={', 1)[1].split('\n};', 1)[0]
    rows = re.findall(r'\{(0x[0-9a-f]+),\{([^{}]+)\}\}', body)
    if len(rows) != 7:
        raise ValueError('Expected exactly seven finite method source pins')
    methods = [(int(rva, 0), bytes(int(x, 0) for x in data.split(','))) for rva, data in rows]
    if any(len(data) != 24 for _, data in methods):
        raise ValueError('Expected source24 for every typed original')
    edges = re.findall(r'\{(\d+),(\d+),(0x[0-9a-f]+),(0x[0-9a-f]+|0),(0x[0-9a-f]+),(true|false)\}', body)
    if len(edges) != 3:
        raise ValueError('Expected exactly three source nested edges')
    return methods, [(int(a), int(b), int(pc, 0), int(ret, 0), int(word, 0), tail == 'true') for a, b, pc, ret, word, tail in edges]


def audit(originals: Path, bridge: Path | None = None):
    source = (bridge or ROOT / 'client-presentation/native/bridge.cpp').read_text()
    checked = {'methods': 0, 'direct_bl': 0, 'tail_b': 0, 'layouts': 0}
    for platform in ('android', 'ios'):
        original, _, _ = whole(originals, platform)
        methods, edges = pins(source, platform)
        for (name, signature), (rva, data) in zip(SELECT, methods, strict=True):
            method = original.method(CLASS, name, len(signature), signature)
            if method['static'] or method['return'] != 'System.Void' or int(method['rva'], 0) != rva:
                raise ValueError(f'{platform}/{name}: immutable exact selector or ABI changed')
            at = original.offset(rva)
            if original.b[at:at + 24] != data:
                raise ValueError(f'{platform}/{name}: immutable original source24 mismatch')
            checked['methods'] += 1
        if [(a, b, tail) for a, b, _, _, _, tail in edges] != [(0, 5, True), (3, 4, False), (3, 6, False)]:
            raise ValueError('Only actual Prepare tail-SyncStart and Process BL nested edges are admitted')
        for parent, nested, pc, ret, word, tail in edges:
            if pc <= methods[parent][0]:
                raise ValueError('Source branch must be within its actual original body')
            actual = int.from_bytes(original.b[original.offset(pc):original.offset(pc) + 4], 'little')
            if actual != word or word & 0xfc000000 != (0x14000000 if tail else 0x94000000):
                raise ValueError('Source B/BL instruction changed')
            signed = word & 0x3ffffff
            if signed & 0x2000000:
                signed -= 0x4000000
            if pc + signed * 4 != methods[nested][0] or ret != (0 if tail else pc + 4):
                raise ValueError('Source target/continuation changed; a tail B has no branch+4 return capability')
            checked['tail_b' if tail else 'direct_bl'] += 1
        frame = original.struct_layout('UnityEngine.Playables.FrameData')
        playable = original.struct_layout('UnityEngine.Playables.Playable')
        graph = original.struct_layout('UnityEngine.Playables.PlayableGraph')
        if (frame['bytes'], frame['fields']['m_Flags'], frame['fields']['m_Output'], playable['bytes'], graph['bytes'], graph['fields']['m_Version']) != (64, 40, 48, 16, 16, 8):
            raise ValueError('Original FrameData/Playable/PlayableGraph aggregate ABI changed')
        checked['layouts'] += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals', type=Path, required=True)
    parser.add_argument('--bridge', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.originals, args.bridge), sort_keys=True))


if __name__ == '__main__':
    main()
