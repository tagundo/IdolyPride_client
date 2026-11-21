"""Rebuild all camera/audio/layout bindings from unchanged original clients."""
import importlib.util
import os
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]

def audit_module():
    sys.path.insert(0, str(ROOT / 'tools'))
    spec = importlib.util.spec_from_file_location('selected_camera_profile_audit', ROOT / 'tools/audit_mp4_camera_state.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('platform', ['android', 'ios'])
def test_camera_audio_bindings_reproduce_complete_originals(platform):
    directory = os.environ.get('IDOLY_MP4_ORIGINALS_DIR')
    if not directory:
        pytest.skip('Set IDOLY_MP4_ORIGINALS_DIR for complete original audit')
    module = audit_module()
    base = Path(directory)
    pairs = {'android': (module.OriginalAndroid, 'android-metadata.dat', 'android-native.so'),
             'ios': (module.Original, 'ios-metadata.dat', 'ios-native.bin')}
    generated = {}
    # The emitted platform schemas also contain shared enum/field assertions.
    for name, (constructor, metadata, native) in pairs.items():
        original = constructor((base / metadata).read_bytes(), (base / native).read_bytes())
        generated[name] = module.build(original, name)
        engine = base / ('mp4-android-analysis/libunity.so' if name == 'android' else native)
        generated[name]['native_audio'] = module.native_audio(original, name, engine)
        generated[name]['native_camera'] = module.native_camera(original, name, engine)
    assert module.render(generated) in (ROOT / 'client-presentation/native/mp4_camera_owner.hpp').read_text()
    actual = generated[platform]
    assert actual['native_audio']['paused_offset'] == 0x3ac
    assert actual['native_camera']['automatic_aspect_offset'] == 0x522
    assert actual['enums']['camera_smart']['value'] == 2
    assert actual['enums']['projection_explicit']['value'] == 0
    assert actual['render_context']['bytes'] == 8
    assert actual['render_context']['fields'] == {'m_Ptr': 0}
    assert actual['render_fields']['camera_data_camera']['offset'] == 128
    assert actual['render_fields']['camera_data_camera']['unboxed']
    assert actual['render_fields']['additional_motion']['offset'] == 112
    assert actual['enums']['camera_base']['value'] == 0
    for name in ('render_stack', 'render_camera'):
        method = actual['methods'][name]
        assert method['static']
        assert [item['type'] for item in method['parameters']] == [
            'UnityEngine.Rendering.ScriptableRenderContext', 'UnityEngine.Camera']
