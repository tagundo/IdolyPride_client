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
        assert methods['player_initialize']['native_abi']=='UniTask16(void*,void*,bool,CancellationToken8,const MethodInfo*)'
        assert methods['camera_pixel_width']['return']=='System.Int32'
        assert methods['camera_pixel_height']['return']=='System.Int32'
        assert methods['capture_pass_execute']['native_abi']=='void(void*,ScriptableRenderContext8,void*,const MethodInfo*)'
        assert methods['end_camera_rendering']['native_abi']=='void(ScriptableRenderContext8,void*,const MethodInfo*)'
        assert methods['texture2d_read_pixels_injected']['parameters'][0]['type']=='UnityEngine.Rect&'
        assert methods['bundle_load_file_async']['static']
        assert not methods['bundle_load_asset']['static']
        assert methods['audio_clip_get_data']['parameters'][1]['type']=='System.Int32'
        assert profile['structs']['PlayableGraph']['bytes']==16
        assert profile['structs']['UniTask']['bytes']==16
        assert profile['structs']['UniTask']['fields']=={'source':0,'token':8}
        assert profile['structs']['CancellationToken']['bytes']==8
        assert profile['structs']['CancellationToken']['fields']=={'_source':0}
        assert profile['fields']['selection_actor_descriptor']==0x28
        assert profile['fields']['selection_descriptor_assets']==0x10
        assert profile['fields']['selection_descriptor_game_objects']==0x20
        assert profile['fields']['selection_descriptor_render_layer']==0x34
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


def test_photography_bindings_preserve_actual_owner_async_abi_and_lazy_producer():
    for name in ('mp4_game_profile.json','mp4_game_ios_profile.json'):
        profile=json.loads((NATIVE/name).read_text())
        methods=profile['methods'];fields=profile['fields']
        assert methods['photography_initialize']['native_abi']=='UniTask16(void*,void*,void*,CancellationToken8,const MethodInfo*)'
        assert methods['photography_player_initialize']['native_abi']=='UniTask16(void*,void*,CancellationToken8,const MethodInfo*)'
        assert methods['photography_end']['native_abi']=='void(void*,const MethodInfo*)'
        assert methods['photo_mode_is_mv']['native_abi']=='bool(void*,const MethodInfo*)'
        assert methods['active_enabled']['native_abi']=='bool(void*,const MethodInfo*)'
        assert fields['photo_root_mode']==0x30 and fields['photo_mode_player']==0x20
        assert fields['photo_mode_data']==0x30 and fields['player_built']==0x70
        assert [fields['photo_data_'+n] for n in ('stage','timeline','descriptors','characters')]==[0x10,0x18,0x20,0x28]
        descriptor=profile['field_proof']['photo_data_descriptors']
        assert descriptor['type']=='System.Collections.Generic.IEnumerable`1<Solis.Common.SolisActorDescriptor>'
        assert descriptor['name']=='<ActorDescriptors>k__BackingField'
        select=methods['photo_select_to_array']
        assert select['runtime_closed_method_info_required'] and select['native_abi']=='void*(void*,const MethodInfo*)'
        assert select['module']=='solis-submodule.Runtime.dll' and select['token_row']==28
        assert fields['photo_select_source']==0x10 and fields['photo_select_selector']==0x18
        assert select['generic_proof']['constructor_instructions'][-1]['word']=='b44e01a9'
        assert select['generic_proof']['declared_return'].endswith('[]')


def test_owned_control_reference_bindings_preserve_property_name_value_abi():
    for name in ('mp4_game_profile.json','mp4_game_ios_profile.json'):
        profile=json.loads((NATIVE/name).read_text())
        methods=profile['methods'];fields=profile['fields']
        reference=methods['director_get_reference']
        assert [parameter['type'] for parameter in reference['parameters']]==['UnityEngine.PropertyName','System.Boolean&']
        assert reference['native_abi']=='void*(void*,PropertyName4,void*,const MethodInfo*)'
        assert methods['component_game_object']['native_abi']=='void*(void*,const MethodInfo*)'
        assert methods['track_muted_hierarchy']['native_abi']=='bool(void*,const MethodInfo*)'
        assert profile['structs']['PropertyName']['bytes']==4
        assert profile['structs']['PropertyName']['fields']=={'id':0}
        assert fields['controller_directors']==0x28
        assert {key:fields[key] for key in ('control_source','control_prefab','control_update_director','control_search_hierarchy')}=={
            'control_source':0x18,'control_prefab':0x28,'control_update_director':0x38,'control_search_hierarchy':0x3a}
        assert profile['field_proof']['controller_directors']['type']=='System.Collections.Generic.List`1<UnityEngine.Playables.PlayableDirector>'
        assert profile['field_proof']['control_source']['type']=='UnityEngine.ExposedReference`1<UnityEngine.GameObject>'
