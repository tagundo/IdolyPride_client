#!/usr/bin/env python3
"""Derive exact offline-scene hooks from both pinned original clients.

Only profile/header source is generated. This tool does not run or package an
app, and the ordinary original render path remains the unowned fallback.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original
ALIAS='mp4_psyllium_execute'
PARTICLE_ALIAS='mp4_particle_simulate'
LIVE_ALIAS='mp4_live_particle_simulate'
END_ALIAS='mp4_presenter_end'
CONTROL_ALIAS='mp4_particle_control_simulate'
DERIVED_ALIASES={'mp4_actor_derived_late_ref':'derived_late_ref','mp4_actor_derived_late_shared':'derived_late_shared'}
BOOL_ALIASES={'mp4_photography_is_end','mp4_player_is_end'}
STATIC_ALIASES={'mp4_render_stack','mp4_render_camera'}
ONE_STATIC_ALIASES={'mp4_cine_apply'}
OBJECT_ALIASES={'mp4_selected_renderer':'UnityEngine.Rendering.Universal.ScriptableRenderer'}
OBJECT_ALIASES.update({
 'mp4_shader_memory_sync':'UnityEngine.AssetBundle',
 'mp4_shader_memory_async':'UnityEngine.AssetBundleCreateRequest',
 'mp4_shader_file_async':'UnityEngine.AssetBundleCreateRequest',
 'mp4_shader_bundle_result':'UnityEngine.AssetBundle',
})
STATIC_ALIASES.update({'mp4_shader_memory_sync','mp4_shader_memory_async','mp4_shader_file_async'})

VALUE_ALIASES={'mp4_control_create':'UnityEngine.Playables.Playable'}
TYPED_PARAMETERS={
 'mp4_capture_request':[],
 'mp4_capture_update':[],
 'mp4_capture_wrapper_ctor':['UnityEngine.RenderTextureDescriptor','System.String'],
 'mp4_capture_texture_ctor':['UnityEngine.RenderTextureDescriptor'],
 'mp4_control_create':['UnityEngine.Playables.PlayableGraph','UnityEngine.GameObject'],
 'mp4_shader_memory_sync':['System.Byte[]','System.UInt32'],
 'mp4_shader_memory_async':['System.Byte[]','System.UInt32'],
 'mp4_shader_file_async':['System.String','System.UInt32','System.UInt64'],
 'mp4_shader_bundle_result':[],

 'mp4_srp_add_precull':['UnityEngine.Events.UnityAction'],
 'mp4_srp_invoke_precull':[],
 'mp4_srp_begin_frame':['UnityEngine.Rendering.ScriptableRenderContext','UnityEngine.Camera[]'],
}
TYPED_ABIS={
 'mp4_capture_request':'void(void*,const MethodInfo*)',
 'mp4_capture_update':'void(void*,const MethodInfo*)',
 'mp4_capture_wrapper_ctor':'void(void*,const RenderTextureDescriptor52*,void*,const MethodInfo*)',
 'mp4_capture_texture_ctor':'void(void*,const RenderTextureDescriptor52*,const MethodInfo*)',
 'mp4_control_create':'Playable16(void*,PlayableGraph16,void*,const MethodInfo*)',
 'mp4_shader_memory_sync':'void*(void*,uint32_t,const MethodInfo*)',
 'mp4_shader_memory_async':'void*(void*,uint32_t,const MethodInfo*)',
 'mp4_shader_file_async':'void*(void*,uint32_t,uint64_t,const MethodInfo*)',
 'mp4_shader_bundle_result':'void*(void*,const MethodInfo*)',

 'mp4_srp_add_precull':'void(void*,void*,const MethodInfo*)',
 'mp4_srp_invoke_precull':'void(void*,const MethodInfo*)',
 'mp4_srp_begin_frame':'void(void*,ScriptableRenderContext8,void*,const MethodInfo*)',
}
SELECTIONS={'mp4_context_submit':('UnityEngine.Rendering.ScriptableRenderContext','Submit',0),'mp4_mirror_late':('VL.Rendering.MirrorVolume','LateUpdate',0),'mp4_mirror_parameters':('VL.Rendering.MirrorVolume','UpdateParameters',0),'mp4_mirror_destroy':('VL.Rendering.MirrorVolume','OnDestroy',0),'mp4_fog_enable':('Solis.Rendering.VolumetricHeightFogVolume','OnEnable',0),'mp4_fog_disable':('Solis.Rendering.VolumetricHeightFogVolume','OnDisable',0),'mp4_fog_late':('Solis.Rendering.VolumetricHeightFogVolume','LateUpdate',0),'mp4_cine_apply':('Cinemachine.PostFX.CinemachineVolumeSettings','ApplyPostFX',1),'mp4_cine_game_object_ctor':('UnityEngine.GameObject','.ctor',1,('System.String',)),'mp4_cine_volume_enable':('UnityEngine.Rendering.Volume','OnEnable',0),'mp4_volume_update':('UnityEngine.Rendering.Volume','Update',0),'mp4_material_ctor_shader':('UnityEngine.Material','.ctor',1,('UnityEngine.Shader',)),'mp4_render_library_ctor':('VL.Rendering.Internal.VLPostProcessPass/MaterialLibrary','.ctor',1),'mp4_selected_renderer':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','get_scriptableRenderer',0),'mp4_vlb_draw':('VLB.VLBBatchSRP','UpdateAndDrawMeshInstanced',3,('UnityEngine.Rendering.CommandBuffer','UnityEngine.Rendering.Universal.CameraData&','UnityEngine.Material')),'mp4_render_stack':('UnityEngine.Rendering.Universal.UniversalRenderPipeline','RenderCameraStack',2),'mp4_render_camera':('UnityEngine.Rendering.Universal.UniversalRenderPipeline','RenderSingleCamera',2),'mp4_photography_is_end':('Solis.Common.Photography.PhotographyLive3DPresenter','IsEndTimeline',0),'mp4_player_is_end':('Solis.Common.SolisLivePlayer','IsTimelineEnded',0),'mp4_equipment_late':('Solis.Live.Equipment.LiveEquipmentController','LateUpdate',0),CONTROL_ALIAS:('UnityEngine.Timeline.ParticleControlPlayable','Simulate',2,('System.Single','System.Boolean')),ALIAS:('Solis.Live.Psyllium.RenderPsyllium','Execute',2),PARTICLE_ALIAS:('UnityEngine.ParticleSystem','Simulate',4),LIVE_ALIAS:('Solis.Live.Equipment.Environment.LiveParticleEffect','SimulateParticle',2),END_ALIAS:('Solis.OutGame.LivePlayerScreenPresenter','EndAsync',1),
    'mp4_actor_update':('VL.Core.VLActorController','Update',0),'mp4_actor_late':('VL.Core.VLActorController','LateUpdate',0),
    'mp4_actor_eye_late':('VL.VLActorEye','LateUpdate',0),'mp4_actor_face_late':('VL.VLActorFaceTargetCorrection','LateUpdate',0),
    'mp4_actor_foot_apply':('VL.VLActorFootShadow','ApplyJob',0)}
SELECTIONS.update({
 'mp4_capture_request':('VL.Rendering.VLSRPCameraController','CaptureRequest',0),
 'mp4_capture_update':('VL.Rendering.VLSRPCameraController','UpdateCapturedTexture',0),
 'mp4_capture_wrapper_ctor':('VL.VLRenderTexture','.ctor',2,tuple(TYPED_PARAMETERS['mp4_capture_wrapper_ctor'])),
 'mp4_capture_texture_ctor':('UnityEngine.RenderTexture','.ctor',1,tuple(TYPED_PARAMETERS['mp4_capture_texture_ctor'])),
 'mp4_control_create':('UnityEngine.Timeline.ControlPlayableAsset','CreatePlayable',2,tuple(TYPED_PARAMETERS['mp4_control_create'])),
 'mp4_shader_memory_sync':('UnityEngine.AssetBundle','LoadFromMemory_Internal',2,tuple(TYPED_PARAMETERS['mp4_shader_memory_sync'])),
 'mp4_shader_memory_async':('UnityEngine.AssetBundle','LoadFromMemoryAsync_Internal',2,tuple(TYPED_PARAMETERS['mp4_shader_memory_async'])),
 'mp4_shader_file_async':('UnityEngine.AssetBundle','LoadFromFileAsync_Internal',3,tuple(TYPED_PARAMETERS['mp4_shader_file_async'])),
 'mp4_shader_bundle_result':('UnityEngine.AssetBundleCreateRequest','get_assetBundle',0),

 'mp4_srp_add_precull':('VL.Rendering.VLSRPCameraController','AddPreCullFrameEvent',1,tuple(TYPED_PARAMETERS['mp4_srp_add_precull'])),
 'mp4_srp_invoke_precull':('VL.Rendering.VLSRPCameraController','InvokePreCullFrameEvent',0),
 'mp4_srp_begin_frame':('VL.Rendering.VLSRPCameraController','OnBeginFrameRendering',2,tuple(TYPED_PARAMETERS['mp4_srp_begin_frame'])),
})
FIXED_ALIAS='mp4_fixed_loop_condition'
ANIMATION_ALIASES=['mp4_animation_'+suffix for suffix in ('sample','update','begin','legacy','end','deferred','late','render')]
BASE_SHA={
 'android':'163b0c46f45603bf972e8537472dd3fd862ccbbe1b1b55d59ea8cf8069bd4927',
 'ios':'60ecc264edd253ed482519c1035264647c8e67b960fe5b3b99e1c909d9a309b0',
}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def derive(original,platform,alias):
    if alias in DERIVED_ALIASES:
        from audit_mp4_actor_state import derived_callbacks
        value=derived_callbacks(original,platform)[DERIVED_ALIASES[alias]]
        row=struct.unpack_from('<7I4H',original.m,original.h[12]+value['metadata_method_index']*36)
        slot=int(value['pointer_slot'],16)
        tid=original.type_id(value['type']);module=next(name for name,first,last in original.images if first<=tid<last)
        return {'name':value['type']+'.'+value['name'],'module':module,
            'type_definition_index':tid, 'metadata_method_index':value['metadata_method_index'],
            'token_row':row[6]&0xffffff,'rva':value['rva']if platform=='android'else int(value['rva'],16),
            'return_type_index':row[2],'parameters':[],'parameter_count':0,'method_flags':row[7],
            'return_type':value['return'],'registration_pointer_slot_rva':hex(slot)if platform=='android'else slot,
            'prefix16':value['prefix'],'native_abi':value['native_abi'],
            'generic_source':{k:value[k]for k in('metadata_registration','method_spec_index','generic_arguments','method_pointer_index','pointer_table','pointer_slot')}}
    value=original.method(*SELECTIONS[alias])
    assert value['static']==(alias in STATIC_ALIASES or alias in ONE_STATIC_ALIASES) and value['return']==(VALUE_ALIASES[alias]if alias in VALUE_ALIASES else OBJECT_ALIASES[alias]if alias in OBJECT_ALIASES else'System.Boolean'if alias in BOOL_ALIASES else'Cysharp.Threading.Tasks.UniTask'if alias==END_ALIAS else'System.Void')
    expected=(TYPED_PARAMETERS[alias]if alias in TYPED_PARAMETERS else['Cinemachine.CinemachineBrain']if alias=='mp4_cine_apply'else['System.String']if alias=='mp4_cine_game_object_ctor'else['UnityEngine.Shader']if alias=='mp4_material_ctor_shader' else['VL.Rendering.VLPostProcessData']if alias=='mp4_render_library_ctor' else['UnityEngine.Rendering.CommandBuffer','UnityEngine.Rendering.Universal.CameraData&','UnityEngine.Material']if alias=='mp4_vlb_draw' else['UnityEngine.Rendering.ScriptableRenderContext','UnityEngine.Camera']if alias in STATIC_ALIASES else['System.Single','System.Boolean']if alias==CONTROL_ALIAS else []if SELECTIONS[alias][2]==0 else['System.Threading.CancellationToken']if alias==END_ALIAS else['UnityEngine.Rendering.ScriptableRenderContext','UnityEngine.Rendering.Universal.RenderingData&']if alias==ALIAS else ['UnityEngine.ParticleSystem','System.Single']if alias==LIVE_ALIAS else['System.Single','System.Boolean','System.Boolean','System.Boolean'])
    assert [p['type'] for p in value['parameters']]==expected
    row=struct.unpack_from('<7I4H',original.m,original.h[12]+value['metadata_method_index']*36)
    parameters=[{'name':p['name'],('typeindex'if platform=='android'else'metadata_type_index'):p['metadata_type_index'],('type'if platform=='android'else'type_name'):p['type']}for p in value['parameters']]
    rva=int(value['rva'],16);slot=int(value['registration_pointer_slot'],16)
    result={'name':value['type']+'.'+value['name'],'module':value['module'],'type_definition_index':original.type_id(value['type']),
        'metadata_method_index':value['metadata_method_index'],'token_row':value['token_row'],'rva':hex(rva)if platform=='android'else rva,
        'return_type_index':row[2],'parameters':parameters,'parameter_count':len(expected),'method_flags':row[7],
        'return_type':value['return'],'registration_pointer_slot_rva':hex(slot)if platform=='android'else slot,
        'prefix16':value['prefix'],'native_abi':(TYPED_ABIS[alias]if alias in TYPED_ABIS else'void(ScriptableRenderContext8*,const MethodInfo*)'if alias=='mp4_context_submit'else'void(void*,void*,const MethodInfo*)'if alias in{'mp4_material_ctor_shader','mp4_render_library_ctor','mp4_cine_game_object_ctor'}else'void(void*,const MethodInfo*)'if alias in ONE_STATIC_ALIASES else'void*(void*,const MethodInfo*)'if alias in OBJECT_ALIASES else'void(void*,void*,CameraData336Ref*,void*,const MethodInfo*)'if alias=='mp4_vlb_draw' else'void(ScriptableRenderContext8,void*,const MethodInfo*)'if alias in STATIC_ALIASES else'bool(void*,const MethodInfo*)'if alias in BOOL_ALIASES else'void(void*,const MethodInfo*)'if not expected else'UniTask16(void*,CancellationToken8,const MethodInfo*)'if alias==END_ALIAS else'void(void*,ScriptableRenderContext8,void*,const MethodInfo*)'if alias==ALIAS else'void(void*,void*,float,const MethodInfo*)'if alias==LIVE_ALIAS else'void(void*,float,bool,const MethodInfo*)'if alias==CONTROL_ALIAS else'void(void*,float,bool,bool,bool,const MethodInfo*)')}
    # Both original value layouts contain exactly one native pointer. A 16B
    # invented context shifts RenderingData/MethodInfo and is not accepted.
    context=original.struct_layout('UnityEngine.Rendering.ScriptableRenderContext')
    assert context['size_table_instance_bytes']==24 and context['size_table_native_bytes']==8
    return result


def stripped(profile,platform):
    old=json.loads(json.dumps(profile))
    for alias in (*SELECTIONS,*DERIVED_ALIASES):
        if alias in old['aliases']:
            del old['aliases'][alias]
            if platform=='ios':
                old['hook_names'].remove(alias);old['gateway_region']['bytes']-=32;old['slot_region']['bytes']-=8
    if platform=='ios':
        for alias in ANIMATION_ALIASES:
            if alias in old['aliases']:
                del old['aliases'][alias];old['hook_names'].remove(alias)
                old['gateway_region']['bytes']-=32;old['slot_region']['bytes']-=8
    if platform=='ios' and FIXED_ALIAS in old['aliases']:
        del old['aliases'][FIXED_ALIAS];old['hook_names'].remove(FIXED_ALIAS)
        old['gateway_region']['bytes']-=32;old['slot_region']['bytes']-=8
        del old['native_extra_relay_regions']
    assert digest((json.dumps(old,indent=2)+'\n').encode())==BASE_SHA[platform], 'previous_profile_bytes_changed'
    return old


def generate_android_header(old,row,alias):
    declaration='inline constexpr Entry '+alias+'{'+json.dumps(row['name'])+', '+row['rva']+'u, {'+', '.join('0x'+row['prefix16'][i:i+2]for i in range(0,32,2))+'};'
    # Close the nested byte array and Entry initializer separately.
    declaration=declaration[:-2]+'}};'
    if 'inline constexpr Entry '+alias+'{' in old:
        import re
        old=re.sub(r'\ninline constexpr Entry '+alias+r'\{[^\n]+\};\n','',old)
        old=old.replace('\n    '+alias+',','')
    marker='\ninline constexpr Entry all[] = {'
    assert old.count(marker)==1
    old=old.replace(marker,'\n'+declaration+'\n'+marker)
    end='\n};\n} // namespace idoly::presentation::profile'
    assert old.count(end)==1
    return old.replace(end,'\n    '+alias+','+end)


def profiles(originals):
    result={}
    for platform,constructor in [('android',OriginalAndroid),('ios',Original)]:
        original=constructor((originals/(platform+'-metadata.dat')).read_bytes(),(originals/('android-native.so'if platform=='android'else'ios-native.bin')).read_bytes())
        profile_path=ROOT/'client-presentation'/('native'if platform=='android'else'ios')/'profile.json'
        old=json.loads(profile_path.read_text());stripped(old,platform)
        if platform=='ios':
            for alias in ANIMATION_ALIASES:
                if alias in old['aliases']:
                    del old['aliases'][alias];old['hook_names'].remove(alias)
                    old['gateway_region']['bytes']-=32;old['slot_region']['bytes']-=8
            if 'native_extra_relay_regions' in old:
                old['native_extra_relay_regions']=[r for r in old['native_extra_relay_regions']if r['name']==FIXED_ALIAS]
        for alias in (*SELECTIONS,*DERIVED_ALIASES):
            row=derive(original,platform,alias)
            if alias in old['aliases']:assert old['aliases'][alias]==row,(platform,alias,old['aliases'][alias],row)
            else:
                old['aliases'][alias]=row
                if platform=='ios':old['hook_names'].append(alias);old['gateway_region']['bytes']+=32;old['slot_region']['bytes']+=8
        if platform=='ios':
            from audit_mp4_world import build as world_profile
            world=world_profile(originals,'ios');condition=world['native']['fixed_condition']
            relay=old['native_relay_region'];entry=relay['rva']+relay['bytes']
            fixed={'name':'PlayerLoop::FixedUpdateCondition','module':None,
                'source':'pinned_original_native_fixed_update_loop_condition','native_abi':'bool(void)',
                'native_parameter_registers':{},'rva':int(condition['rva'],16),'prefix16':condition['prefix'],
                'registration_pointer_slot_rva':None,'relay_in':entry,'relay_out':entry+4}
            if FIXED_ALIAS in old['aliases']:assert old['aliases'][FIXED_ALIAS]==fixed
            else:
                old['aliases'][FIXED_ALIAS]=fixed;old['hook_names'].append(FIXED_ALIAS)
                old['gateway_region']['bytes']+=32;old['slot_region']['bytes']+=8
                old['native_extra_relay_regions']=[dict(relay,name=FIXED_ALIAS,rva=entry)]
        result[platform]=old
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--originals',type=Path,required=True);p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args();generated=profiles(args.originals)
    proof={'schema':1,'scope':'typed_offline_scene_aliases_source_only','aliases':{platform:{alias:profile['aliases'][alias]for alias in (*SELECTIONS,*DERIVED_ALIASES)}for platform,profile in generated.items()},'ios_native_fixed_condition':generated['ios']['aliases'][FIXED_ALIAS],'previous_profiles_preserved':True}
    if args.apply:
        for platform,profile in generated.items():
            folder=ROOT/'client-presentation'/('native'if platform=='android'else'ios');(folder/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')
        native=ROOT/'client-presentation/native/profile.hpp';header=native.read_text()
        for alias in (*SELECTIONS,*DERIVED_ALIASES):header=generate_android_header(header,generated['android']['aliases'][alias],alias)
        native.write_text(header)
        validator=ROOT/'src/idoly_local/ios_presentation.py';text=validator.read_text()
        import re
        sha=digest((ROOT/'client-presentation/ios/profile.json').read_bytes())
        text=re.sub(r'PROFILE_SHA256 = "[a-f0-9]{64}"','PROFILE_SHA256 = "'+sha+'"',text)
        text=re.sub(r'PROFILE_ENTRY_COUNT = \d+','PROFILE_ENTRY_COUNT = '+str(len(generated['ios']['aliases'])),text);text=re.sub(r'PROFILE_HOOK_COUNT = \d+','PROFILE_HOOK_COUNT = '+str(len(generated['ios']['hook_names'])),text);validator.write_text(text)
        spec=importlib.util.spec_from_file_location('scene_ios_profile',validator);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        plan=module.make_plan();header=module.render_header(plan);(ROOT/'client-presentation/ios/ios_profile.hpp').write_bytes(header)
        proof.update(ios_profile_sha256=sha,ios_header_sha256=digest(header))
    if args.output:args.output.write_text(json.dumps(proof,indent=2)+'\n')
    else:print(json.dumps(proof,indent=2))

if __name__=='__main__':main()
