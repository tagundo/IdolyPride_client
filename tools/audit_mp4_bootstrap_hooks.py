#!/usr/bin/env python3
"""Check shipping hook source24 pins against both whole-verified original cohorts.

This audit reads external original inputs; it does not package native binaries,
modify profiles, install hooks, run the engine or certify runtime MP4 output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

from audit_mp4_scene_aliases import SELECTIONS
from audit_mp4_world import DIRECTOR_NATIVE, whole

NATIVE_ROLES = {
    'enqueue': 'enqueue', 'append_a': 'deferred_append_a',
    'append_b': 'deferred_append_b', 'collect': 'collect',
    'deferred_a': 'deferred_a', 'deferred_b': 'deferred_b',
    'graph_create': 'graph_create',
}
SCENE_OBSERVERS = ('mp4_scene_shader_loaded', 'mp4_scene_shader_unloaded',
                   'mp4_scene_shader_bundle_unload', 'mp4_scene_shader_load')

MANAGED_EXTRA = (
    'mp4_capture_request', 'mp4_capture_update', 'mp4_capture_wrapper_ctor',
    'mp4_capture_texture_ctor', 'mp4_shader_memory_sync', 'mp4_shader_memory_async',
    'mp4_shader_file_async', 'mp4_shader_bundle_result',
)


def source_pins(text: str, array: str, expected_count: int = 8):
    found = re.findall(r'\b' + re.escape(array) + r'\s*\[' + str(expected_count) + r'\]\s*=\s*\{(.*?)\};', text, re.S)
    if len(found) != 1:
        raise ValueError(f'{array}: expected exactly one finite source array')
    rows = re.findall(r'\{\s*BootstrapRole::(\w+)\s*,\s*BootstrapImage::(\w+)\s*,\s*(0x[0-9a-fA-F]+)\s*,\s*\{([^{}]+)\}\s*\}', found[0])
    if len(rows) != expected_count:
        raise ValueError(f'{array}: expected exactly {expected_count} source specs')
    out = []
    for role, image, rva, data in rows:
        parts = [part.strip() for part in data.split(',') if part.strip()]
        if len(parts) != 24:
            raise ValueError(f'{array}/{role}: expected actual 24-byte source pin')
        out.append((role, image, int(rva, 0), bytes(int(part, 0) for part in parts)))
    return out


def audit(originals: Path, bridge: Path | None = None):
    source = (bridge or ROOT / 'client-presentation/native/bridge.cpp').read_text()
    checked = {'native_factory': 0, 'shader_capture': 0, 'scene_observers': 0}
    for platform in ('android', 'ios'):
        original, engine, offset = whole(originals, platform)
        primary = source_pins(source, platform + '_bootstrap_pins')
        for (role, native_name), (actual_role, image, rva, pin) in zip(NATIVE_ROLES.items(), primary[:7], strict=True):
            expected = DIRECTOR_NATIVE[platform]['entries'][native_name][0]
            if (actual_role, image, rva) != (role, 'engine', expected):
                raise ValueError(f'{platform}/{role}: native source selector changed')
            at = offset(expected)
            if engine[at:at + 24] != pin:
                raise ValueError(f'{platform}/{role}: immutable original prologue mismatch')
            checked['native_factory'] += 1
        factory = original.method('UnityEngine.Timeline.TimelineAsset', 'CreatePlayable', 2,
                                  ('UnityEngine.Playables.PlayableGraph', 'UnityEngine.GameObject'))
        if factory['static'] or factory['return'] != 'UnityEngine.Playables.Playable':
            raise ValueError(f'{platform}/factory: actual managed factory signature changed')
        role, image, rva, pin = primary[7]
        if (role, image, rva) != ('factory', 'game', int(factory['rva'], 16)):
            raise ValueError(f'{platform}/factory: actual managed factory source selector changed')
        at = original.offset(rva)
        if original.b[at:at + 24] != pin:
            raise ValueError(f'{platform}/factory: immutable original prologue mismatch')
        checked['native_factory'] += 1
        extras = source_pins(source, platform + '_managed_extra_pins')
        for alias, (role, image, rva, pin) in zip(MANAGED_EXTRA, extras, strict=True):
            method = original.method(*SELECTIONS[alias])
            if (role, image, rva) != ('factory', 'game', int(method['rva'], 16)):
                raise ValueError(f'{platform}/{alias}: actual managed source selector changed')
            at = original.offset(rva)
            if original.b[at:at + 24] != pin:
                raise ValueError(f'{platform}/{alias}: immutable original prologue mismatch')
            checked['shader_capture'] += 1
        scenes = source_pins(source, platform + '_scene_managed_pins', 4)
        for alias, (role, image, rva, pin) in zip(SCENE_OBSERVERS, scenes, strict=True):
            method = original.method(*SELECTIONS[alias])
            if (role, image, rva) != ('factory', 'game', int(method['rva'], 16)):
                raise ValueError(f'{platform}/{alias}: actual scene observer selector changed')
            at = original.offset(rva)
            if original.b[at:at + 24] != pin:
                raise ValueError(f'{platform}/{alias}: immutable scene prologue mismatch')
            checked['scene_observers'] += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals', required=True, type=Path)
    parser.add_argument('--bridge', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.originals, args.bridge), sort_keys=True))


if __name__ == '__main__':
    main()
