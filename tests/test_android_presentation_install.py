"""Execute the shipping Android installer with modeled loader/hook services."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def function(text, signature):
    first = text.index(signature)
    start = text.index('{', first)
    depth, end = 1, start + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[first:end]


@pytest.fixture(scope='module')
def installer(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler required')
    bridge = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
    body = function(bridge, 'void *install(void *) {')
    table = body.split('    Hook hooks[] = {', 1)[1].split('    };', 1)[0]
    hooks = re.findall(r'HOOK\((\w+),\s*([\w:]+),\s*([\w:]+)\)', table)
    assert len(hooks) > 100
    entries = '\n'.join('inline const Entry ' + name + '{"' + name + '",' + str(4096 + index * 32) + '};'
                        for index, (name, _, _) in enumerate(hooks))
    declarations = []
    for replacement, original in sorted({(row[1], row[2]) for row in hooks}):
        parts = replacement.split('::')
        if len(parts) == 2:
            assert original.startswith(parts[0] + '::')
            declarations.append('namespace ' + parts[0] + '{void ' + parts[1] + '(){} void* '
                                + original.split('::')[1] + '=nullptr;}')
        else:
            declarations.append('void ' + replacement + '(){} void* ' + original + '=nullptr;')
    source_names = ['mp4_capture_request', 'mp4_capture_update', 'mp4_capture_wrapper_ctor',
                    'mp4_capture_texture_ctor', 'mp4_shader_memory_sync', 'mp4_shader_memory_async',
                    'mp4_shader_file_async', 'mp4_shader_bundle_result', 'mp4_source_timeline_factory',
                    'mp4_scene_shader_loaded', 'mp4_scene_shader_unloaded', 'mp4_scene_shader_bundle_unload',
                    'mp4_scene_shader_load', 'mp4_capture_add_target', 'mp4_capture_request_target']
    source_rows = ','.join('{pin::' + name + '.rva}' for name in source_names)
    prefix = (ROOT / 'tests/fixtures/android_presentation_install.cpp.inc').read_text()
    text = prefix.replace('// PIN_ENTRIES', entries).replace('// HOOK_DECLARATIONS', '\n'.join(declarations))
    text = text.replace('// SOURCE_ROWS', source_rows)
    common = 'std::atomic<bool>mp4_bootstrap_first_failed' + bridge.split('std::atomic<bool>mp4_bootstrap_first_failed', 1)[1].split('\nbool game_call(', 1)[0]
    text = text.replace('// ACTUAL_FIRST_FAILURE', common)
    text = text.replace('// ACTUAL_BOOTSTRAP_FAILURE', function(bridge, 'void mp4_bootstrap_hook_failure('))
    text = text.replace('// ACTUAL_OPTIONAL_POLICY', function(bridge, 'bool mp4_optional_offline_hook('))
    text = text.replace('// ACTUAL_INSTALL', body)
    folder = tmp_path_factory.mktemp('android-presentation-installer')
    source, binary = folder / 'installer.cpp', folder / 'installer'
    source.write_text(text)
    result = subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                             str(source), '-o', str(binary)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return binary


CASES = ['normal', 'native_source', 'fixed_source', 'animation_source', 'managed_prepare',
         'capture_native', 'audio_native', 'queue_bind', 'scene_origin', 'scene_frontends',
         'clock_hook', 'clock_api', 'fixed_hook', 'fixed_api', 'optional_hook', 'optional_receipt',
         'subset_source', 'primary_image', 'primary_hook', 'primary_receipt', 'selection_hook',
         'base_ready', 'shadow_init', 'missing_image']
CASES += ['first_failure_none', 'first_failure_preserved', 'first_failure_bounded']
CASES += ['director_' + str(index) for index in range(7)]
CASES += ['source_' + stage + '_' + str(index) for stage in ('before', 'after') for index in range(15)]


@pytest.mark.parametrize('case', CASES)
def test_optional_export_installation_does_not_disable_primary_graphics_or_selection(installer, case):
    result = subprocess.run([str(installer), case], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
