"""Actual shipping Volume producer/snapshot bodies; engine/fence leaves are modeled."""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODES = ['baseline','foreign_component','nonleaf','light_volume_unclosed','wrong_exposed_target','wrong_parent','wrong_post','admission_userdata','playing_without_capture','capture_root_lost','fence_wait','source_lost','authored_target_retarget','untrusted_rebuild','saved_eval_missing','field_type_changed','postrestore_go_changed','postrestore_history_changed','light_volume','source_plan_only','native_identity_changed','source_image_missing','clip_snapshot','mixer_snapshot','source_capture_changed','source_invocation_changed','dispatcher_target_unclosed','light_owners','wrong_compiled','wrong_runtime_element','duplicate_parent_edge','bootstrap_plan','restore_plan_before_saved_eval','final_without_saved_eval']


def section(source, marker):
    begin = source.index('// BEGIN_' + marker)
    end = source.index('// END_' + marker, begin) + len('// END_' + marker)
    return source[begin:end].replace('#pragma once', '') + '\n'


@pytest.fixture(scope='module')
def binaries(tmp_path_factory):
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    header = (ROOT / 'client-presentation/native/mp4_camera_owner.hpp').read_text()
    scope = section(header, 'MP4_SOURCE_VOLUME_INPUT')
    types = scope[scope.index('namespace idoly_mp4_volume_source {'):scope.index('class Scope {')] + '\n}\n'
    snippets = {'SHIPPING_SOURCE_VOLUME_SCOPE': scope, 'SHIPPING_SOURCE_VOLUME_TYPES': types}
    for name in ('PINS', 'HOST', 'ENDPOINTS'):
        snippets['SHIPPING_WORLD_VOLUME_' + name] = section(bridge, 'MP4_WORLD_VOLUME_' + name)
    snippets['SHIPPING_WORLD_VOLUME_EARLY_FENCE'] = section(bridge, 'MP4_VOLUME_SOURCE_EARLY_FENCE')
    folder = tmp_path_factory.mktemp('world-volume-common')
    result = {}
    for kind, variants in [('world-volume', ('android', 'ios')), ('source-scope', ('host',)), ('early-fence', ('host',))]:
        fixture = (ROOT / f'tests/fixtures/mp4_world_volume/{kind}-fixture.cpp.inc').read_text()
        for platform in variants:
            actual = fixture
            for token, replacement in snippets.items():
                actual = actual.replace('// ' + token, replacement)
            source, binary = folder / f'{kind}-{platform}.cpp', folder / f'{kind}-{platform}'
            source.write_text(actual)
            cmd = ['g++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
            if platform == 'ios':
                cmd.append('-DIDOLY_DARWIN_BRIDGE=1')
            subprocess.run([*cmd, str(source), '-o', str(binary)], check=True)
            result[kind, platform] = binary
    return result


@pytest.mark.parametrize('platform,mode', [(p, m) for p in ('android', 'ios') for m in MODES])
def test_actual_volume_producer_body(binaries, platform, mode):
    subprocess.run([str(binaries['world-volume', platform]), mode], check=True, timeout=30)


@pytest.mark.parametrize('case', range(38))
def test_actual_source_scope_image(binaries, case):
    subprocess.run([str(binaries['source-scope', 'host']), str(case)], check=True, timeout=30)


def test_actual_early_volume_fence(binaries):
    subprocess.run([str(binaries['early-fence', 'host'])], check=True, timeout=30)
