"""Attest that version locked native export maps retain typed boundaries."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import audit_mp4_game as audit
import audit_mp4_ios_game as ios_audit

NATIVE=ROOT/'client-presentation/native'

@pytest.mark.parametrize('build',[audit.build_profile,ios_audit.build_profile])
def test_modified_original_is_rejected_before_parsing(build):
    with pytest.raises(ValueError,match='metadata_sha256_differs'):
        build(b'not original metadata',b'not original native')


def test_generated_cross_platform_header_and_typed_hook_boundaries():
    android=json.loads((NATIVE/'mp4_game_profile.json').read_text())
    ios=json.loads((NATIVE/'mp4_game_ios_profile.json').read_text())
    assert (NATIVE/'mp4_game_profile.hpp').read_text()==audit.render_header(android,ios)
    assert android['fields']==ios['fields']
    assert android['enums']==ios['enums']
    for profile in (android,ios):
        methods=profile['methods']
        assert len(methods)>=63
        assert methods['presenter_update']['native_abi']=='void(void*,const MethodInfo*)'
        assert methods['capture_pass_execute']['native_abi']=='void(void*,ScriptableRenderContext8,void*,const MethodInfo*)'
        assert methods['end_camera_rendering']['native_abi']=='void(ScriptableRenderContext8,void*,const MethodInfo*)'
        assert methods['texture2d_read_pixels_injected']['parameters'][0]['type']=='UnityEngine.Rect&'
        assert methods['bundle_load_file_async']['static']
        assert not methods['bundle_load_asset']['static']
        assert methods['audio_clip_get_data']['parameters'][1]['type']=='System.Int32'
        assert profile['structs']['PlayableGraph']['bytes']==16
        assert profile['structs']['AnimationStream']['bytes']==56
        assert profile['structs']['RenderTargetIdentifier']['bytes']==40
        assert profile['fields']['rendering_camera']==0x90
        assert profile['fields']['rendering_final_target']==0x158
        assert profile['fields']['status_last_frame']==0x10
        assert profile['fields']['core_update_status']==0x30
        assert profile['fields']['core_update_filter']==0x38
        assert profile['type_namespaces']=={'.CinemachineTrack':'','.UpdateStatus':''}
        assert profile['enums']['director_manual']==3
        assert profile['scope']['runtime_verified'] is False
        for method in methods.values():
            assert int(method['rva'],16)>0
            assert len(bytes.fromhex(method['prefix']))==16


def test_profile_header_rejects_missing_platform_method():
    android=json.loads((NATIVE/'mp4_game_profile.json').read_text())
    ios=json.loads((NATIVE/'mp4_game_ios_profile.json').read_text())
    del ios['methods']['bundle_unload']
    with pytest.raises(ValueError,match='platform_api_aliases_differ'):
        audit.render_header(android,ios)
