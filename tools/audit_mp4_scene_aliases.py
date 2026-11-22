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
DERIVED_ALIASES={'mp4_actor_derived_late_ref':'derived_late_ref','mp4_actor_derived_late_shared':'derived_late_shared',
 'mp4_animation_interval_add':'interval_add'}
DERIVED_ALIASES.update({'mp4_monitor_pool_'+name.lower():name for name in ('Get','Release','Clear')})
BOOL_ALIASES={'mp4_photography_is_end','mp4_player_is_end','mp4_proflare_try'}
STATIC_ALIASES={'mp4_render_stack','mp4_render_camera'}
ONE_STATIC_ALIASES={'mp4_cine_apply'}
OBJECT_ALIASES={'mp4_selected_renderer':'UnityEngine.Rendering.Universal.ScriptableRenderer'}
OBJECT_ALIASES.update({
 'mp4_shader_memory_sync':'UnityEngine.AssetBundle',
 'mp4_shader_memory_async':'UnityEngine.AssetBundleCreateRequest',
 'mp4_shader_file_async':'UnityEngine.AssetBundleCreateRequest',
 'mp4_shader_bundle_result':'UnityEngine.AssetBundle',
 'mp4_scene_shader_load':'UnityEngine.AsyncOperation',
})
STATIC_ALIASES.update({'mp4_shader_memory_sync','mp4_shader_memory_async','mp4_shader_file_async',
 'mp4_scene_shader_loaded','mp4_scene_shader_unloaded'})

VALUE_ALIASES={'mp4_control_create':'UnityEngine.Playables.Playable',
 'mp4_source_timeline_factory':'UnityEngine.Playables.Playable'}
VALUE_ALIASES.update({name:'UnityEngine.Playables.Playable' for name in (
 'mp4_animation_root_factory','mp4_animation_clips_factory',
 'mp4_animation_infinite_factory','mp4_animation_clip_factory')})
STATIC_ALIASES.add('mp4_animation_clip_factory')
TYPED_PARAMETERS={
 'mp4_monitor_graphic_rebuild':['UnityEngine.UI.CanvasUpdate'],
 'mp4_proflare_try':['UnityEngine.Camera','.ProFlareBatchForSRPData&'],
 'mp4_proflare_initialize':['System.Int32'],
 'mp4_capture_request':[],
 'mp4_capture_update':[],
 'mp4_capture_wrapper_ctor':['UnityEngine.RenderTextureDescriptor','System.String'],
 'mp4_capture_texture_ctor':['UnityEngine.RenderTextureDescriptor'],
 'mp4_control_create':['UnityEngine.Playables.PlayableGraph','UnityEngine.GameObject'],
 'mp4_source_timeline_factory':['UnityEngine.Playables.PlayableGraph','UnityEngine.GameObject'],
 'mp4_scene_shader_load':['System.String','System.Int32','UnityEngine.SceneManagement.LoadSceneParameters','System.Boolean'],
 'mp4_scene_shader_loaded':['UnityEngine.SceneManagement.Scene','UnityEngine.SceneManagement.LoadSceneMode'],
 'mp4_scene_shader_unloaded':['UnityEngine.SceneManagement.Scene'],
 'mp4_scene_shader_bundle_unload':['System.Boolean'],
 'mp4_source_game_object_active':['System.Boolean'],
 'mp4_animation_root_factory':['UnityEngine.Playables.PlayableGraph','UnityEngine.GameObject','UnityEngine.Timeline.IntervalTree`1<UnityEngine.Timeline.RuntimeElement>'],
 'mp4_animation_clips_factory':['UnityEngine.Playables.PlayableGraph','UnityEngine.Timeline.AnimationTrack','UnityEngine.GameObject','UnityEngine.Timeline.IntervalTree`1<UnityEngine.Timeline.RuntimeElement>','UnityEngine.Timeline.AppliedOffsetMode'],
 'mp4_animation_infinite_factory':['UnityEngine.Playables.PlayableGraph','UnityEngine.GameObject','UnityEngine.Timeline.IntervalTree`1<UnityEngine.Timeline.RuntimeElement>','UnityEngine.Timeline.AppliedOffsetMode'],
 'mp4_animation_clip_factory':['UnityEngine.Playables.PlayableGraph','UnityEngine.AnimationClip','UnityEngine.Vector3','UnityEngine.Vector3','System.Boolean','UnityEngine.Timeline.AppliedOffsetMode','System.Boolean','.LoopMode'],
 'mp4_capture_add_target':['UnityEngine.Rendering.RenderTargetIdentifier','UnityEngine.Rendering.Universal.RenderPassEvent'],
 'mp4_capture_request_target':['UnityEngine.Rendering.RenderTargetIdentifier','UnityEngine.Rendering.Universal.RenderPassEvent'],
 'mp4_shader_memory_sync':['System.Byte[]','System.UInt32'],
 'mp4_shader_memory_async':['System.Byte[]','System.UInt32'],
 'mp4_shader_file_async':['System.String','System.UInt32','System.UInt64'],
 'mp4_shader_bundle_result':[],

 'mp4_srp_add_precull':['UnityEngine.Events.UnityAction'],
 'mp4_srp_invoke_precull':[],
 'mp4_srp_begin_frame':['UnityEngine.Rendering.ScriptableRenderContext','UnityEngine.Camera[]'],
}
TYPED_ABIS={
 'mp4_monitor_graphic_rebuild':'void(void*,int32_t,const MethodInfo*)',
 'mp4_proflare_try':'bool(void*,void*,void**,const MethodInfo*)',
 'mp4_proflare_initialize':'void(void*,int32_t,const MethodInfo*)',
 'mp4_capture_request':'void(void*,const MethodInfo*)',
 'mp4_capture_update':'void(void*,const MethodInfo*)',
 'mp4_capture_wrapper_ctor':'void(void*,const RenderTextureDescriptor52*,void*,const MethodInfo*)',
 'mp4_capture_texture_ctor':'void(void*,const RenderTextureDescriptor52*,const MethodInfo*)',
 'mp4_control_create':'Playable16(void*,PlayableGraph16,void*,const MethodInfo*)',
 'mp4_source_timeline_factory':'Playable16(void*,PlayableGraph16,void*,const MethodInfo*)',
 'mp4_scene_shader_load':'void*(void*,void*,int32_t,LoadSceneParameters8,bool,const MethodInfo*)',
 'mp4_scene_shader_loaded':'void(Scene4,int32_t,const MethodInfo*)',
 'mp4_scene_shader_unloaded':'void(Scene4,const MethodInfo*)',
 'mp4_scene_shader_bundle_unload':'void(void*,bool,const MethodInfo*)',
 'mp4_source_game_object_active':'void(void*,bool,const MethodInfo*)',
 'mp4_animation_root_factory':'Playable16(void*,PlayableGraph16,void*,void*,const MethodInfo*)',
 'mp4_animation_clips_factory':'Playable16(void*,PlayableGraph16,void*,void*,void*,int32_t,const MethodInfo*)',
 'mp4_animation_infinite_factory':'Playable16(void*,PlayableGraph16,void*,void*,int32_t,const MethodInfo*)',
 'mp4_animation_clip_factory':'Playable16(PlayableGraph16,void*,Vector3,Vector3,bool,int32_t,bool,int32_t,const MethodInfo*)',
 'mp4_capture_add_target':'void(void*,const RenderTargetIdentifier40*,int32_t,const MethodInfo*)',
 'mp4_capture_request_target':'void(void*,const RenderTargetIdentifier40*,int32_t,const MethodInfo*)',
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
 'mp4_video_process_frame':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'ProcessFrame', 3, ('UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData', 'System.Object')),
 'mp4_video_prepare_frame':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'PrepareFrame', 2, ('UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData')),
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
 'mp4_source_timeline_factory':('UnityEngine.Timeline.TimelineAsset','CreatePlayable',2,tuple(TYPED_PARAMETERS['mp4_source_timeline_factory'])),
 'mp4_scene_shader_load':('UnityEngine.SceneManagement.SceneManagerAPI','LoadSceneAsyncByNameOrIndex',4,tuple(TYPED_PARAMETERS['mp4_scene_shader_load'])),
 'mp4_scene_shader_loaded':('UnityEngine.SceneManagement.SceneManager','Internal_SceneLoaded',2,tuple(TYPED_PARAMETERS['mp4_scene_shader_loaded'])),
 'mp4_scene_shader_unloaded':('UnityEngine.SceneManagement.SceneManager','Internal_SceneUnloaded',1,tuple(TYPED_PARAMETERS['mp4_scene_shader_unloaded'])),
 'mp4_scene_shader_bundle_unload':('UnityEngine.AssetBundle','Unload',1,tuple(TYPED_PARAMETERS['mp4_scene_shader_bundle_unload'])),
 'mp4_source_game_object_active':('UnityEngine.GameObject','SetActive',1,tuple(TYPED_PARAMETERS['mp4_source_game_object_active'])),
 'mp4_animation_root_factory':('UnityEngine.Timeline.AnimationTrack','CreateMixerPlayableGraph',3,tuple(TYPED_PARAMETERS['mp4_animation_root_factory'])),
 'mp4_animation_clips_factory':('UnityEngine.Timeline.AnimationTrack','CompileTrackPlayable',5,tuple(TYPED_PARAMETERS['mp4_animation_clips_factory'])),
 'mp4_animation_infinite_factory':('UnityEngine.Timeline.AnimationTrack','CreateInfiniteTrackPlayable',4,tuple(TYPED_PARAMETERS['mp4_animation_infinite_factory'])),
 'mp4_animation_clip_factory':('UnityEngine.Timeline.AnimationPlayableAsset','CreatePlayable',8,tuple(TYPED_PARAMETERS['mp4_animation_clip_factory'])),
 'mp4_capture_add_target':('VL.Rendering.VLSRPCapture','Add',2,tuple(TYPED_PARAMETERS['mp4_capture_add_target'])),
 'mp4_capture_request_target':('VL.Rendering.VLSRPCameraController','CaptureRequest',2,tuple(TYPED_PARAMETERS['mp4_capture_request_target'])),
 'mp4_gobo_late_update':('Solis.Common.GoboLight.GoboLightController','LateUpdate',0),
 'mp4_gobo_disable':('Solis.Common.GoboLight.GoboLightController','OnDisable',0),
 'mp4_camera_manual_render':('UnityEngine.Camera','Render',0),
 'mp4_proflare_start':('.ProFlare','Start',0),
 'mp4_proflare_enable':('.ProFlare','OnEnable',0),
 'mp4_proflare_disable':('.ProFlare','OnDisable',0),
 'mp4_proflare_try':('.ProFlareBatchForSRP','TryGetUpdatedFlareBatch',2),
 'mp4_proflare_initialize':('.ProFlareBatchForSRPData','Initialize',1),
 'mp4_proflare_batch_late':('.ProFlareBatchForSRP','LateUpdate',0),
 'mp4_proflare_batch_disable':('.ProFlareBatchForSRP','OnDisable',0),
 'mp4_monitor_tv_update_texture':('Solis.Common.CanvasRT.CanvasRenderTexture','UpdateTexture',0),
 'mp4_monitor_tv_disable':('Solis.Common.CanvasRT.CanvasRenderTexture','OnDisable',0),
 'mp4_monitor_image_apply':('UnityEngine.UI.Image','OnDidApplyAnimationProperties',0),
 'mp4_monitor_graphic_rebuild':('UnityEngine.UI.Graphic','Rebuild',1),
})
# Typed Video Timeline/decoder observations from both immutable originals.
TYPED_PARAMETERS.update({
 'mp4_video_process_frame':['UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData', 'System.Object'],
 'mp4_video_prepare_frame':['UnityEngine.Playables.Playable', 'UnityEngine.Playables.FrameData'],
 'mp4_video_mixer_create':['UnityEngine.Playables.PlayableGraph', 'UnityEngine.GameObject', 'System.Int32'],
 'mp4_video_playable_create':['UnityEngine.Playables.Playable'],
 'mp4_video_playable_destroy':['UnityEngine.Playables.Playable'],
 'mp4_video_update':['System.Boolean', 'System.Double'],
 'mp4_video_sync':['System.Double'],
 'mp4_video_set_skip':['System.Boolean'],
 'mp4_video_set_wait_first':['System.Boolean'],
 'mp4_video_set_play_on_awake':['System.Boolean'],
 'mp4_video_set_loop':['System.Boolean'],
 'mp4_video_set_time':['System.Double'],
 'mp4_video_set_external_reference_time':['System.Double'],
 'mp4_video_step':[],
 'mp4_video_loop':['UnityEngine.Video.VideoPlayer'],
 'mp4_video_prepared':['UnityEngine.Video.VideoPlayer'],
 'mp4_video_seek':['UnityEngine.Video.VideoPlayer'],
 'mp4_video_error':['UnityEngine.Video.VideoPlayer', 'System.String'],
 'mp4_video_frame_ready':['UnityEngine.Video.VideoPlayer', 'System.Int64'],
 'mp4_video_image_enable':[],
 'mp4_video_image_late':[],
})
TYPED_ABIS.update({
 'mp4_video_process_frame':'void(void*,Playable16,FrameData64,void*,const MethodInfo*)',
 'mp4_video_prepare_frame':'void(void*,Playable16,FrameData64,const MethodInfo*)',
 'mp4_video_mixer_create':'Playable16(void*,PlayableGraph16,void*,int32_t,const MethodInfo*)',
 'mp4_video_playable_create':'void(void*,Playable16,const MethodInfo*)',
 'mp4_video_playable_destroy':'void(void*,Playable16,const MethodInfo*)',
 'mp4_video_update':'void(void*,bool,double,const MethodInfo*)',
 'mp4_video_sync':'void(void*,double,const MethodInfo*)',
 'mp4_video_set_skip':'void(void*,bool,const MethodInfo*)',
 'mp4_video_set_wait_first':'void(void*,bool,const MethodInfo*)',
 'mp4_video_set_play_on_awake':'void(void*,bool,const MethodInfo*)',
 'mp4_video_set_loop':'void(void*,bool,const MethodInfo*)',
 'mp4_video_set_time':'void(void*,double,const MethodInfo*)',
 'mp4_video_set_external_reference_time':'void(void*,double,const MethodInfo*)',
 'mp4_video_step':'void(void*,const MethodInfo*)',
 'mp4_video_loop':'void(void*,void*,const MethodInfo*)',
 'mp4_video_prepared':'void(void*,void*,const MethodInfo*)',
 'mp4_video_seek':'void(void*,void*,const MethodInfo*)',
 'mp4_video_error':'void(void*,void*,void*,const MethodInfo*)',
 'mp4_video_frame_ready':'void(void*,int64_t,const MethodInfo*)',
 'mp4_video_image_enable':'void(void*,const MethodInfo*)',
 'mp4_video_image_late':'void(void*,const MethodInfo*)',
})
VALUE_ALIASES['mp4_video_mixer_create']='UnityEngine.Playables.Playable'
STATIC_ALIASES.add('mp4_video_frame_ready')
SELECTIONS.update({
 'mp4_video_mixer_create':('Solis.Timeline.SolisVideoPlayerTrack', 'CreateTrackMixer', 3, ('UnityEngine.Playables.PlayableGraph', 'UnityEngine.GameObject', 'System.Int32')),
 'mp4_video_playable_create':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'OnPlayableCreate', 1, ('UnityEngine.Playables.Playable',)),
 'mp4_video_playable_destroy':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'OnPlayableDestroy', 1, ('UnityEngine.Playables.Playable',)),
 'mp4_video_update':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'UpdateVideo', 2, ('System.Boolean', 'System.Double')),
 'mp4_video_sync':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'SyncVideoToPlayable', 1, ('System.Double',)),
 'mp4_video_set_skip':('UnityEngine.Video.VideoPlayer', 'set_skipOnDrop', 1, ('System.Boolean',)),
 'mp4_video_set_wait_first':('UnityEngine.Video.VideoPlayer', 'set_waitForFirstFrame', 1, ('System.Boolean',)),
 'mp4_video_set_play_on_awake':('UnityEngine.Video.VideoPlayer', 'set_playOnAwake', 1, ('System.Boolean',)),
 'mp4_video_set_loop':('UnityEngine.Video.VideoPlayer', 'set_isLooping', 1, ('System.Boolean',)),
 'mp4_video_set_time':('UnityEngine.Video.VideoPlayer', 'set_time', 1, ('System.Double',)),
 'mp4_video_set_external_reference_time':('UnityEngine.Video.VideoPlayer', 'set_externalReferenceTime', 1, ('System.Double',)),
 'mp4_video_step':('UnityEngine.Video.VideoPlayer', 'StepForward', 0, ()),
 'mp4_video_loop':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'LoopPointReached', 1, ('UnityEngine.Video.VideoPlayer',)),
 'mp4_video_prepared':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'PrepareCompleted', 1, ('UnityEngine.Video.VideoPlayer',)),
 'mp4_video_seek':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'SeekCompleted', 1, ('UnityEngine.Video.VideoPlayer',)),
 'mp4_video_error':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'ErrorReceived', 2, ('UnityEngine.Video.VideoPlayer', 'System.String')),
 'mp4_video_frame_ready':('UnityEngine.Video.VideoPlayer', 'InvokeFrameReadyCallback_Internal', 2, ('UnityEngine.Video.VideoPlayer', 'System.Int64')),
 'mp4_video_image_enable':('Solis.Common.VideoImage', 'OnEnable', 0, ()),
 'mp4_video_image_late':('Solis.Common.VideoImage', 'LateUpdate', 0, ()),
})

# Appended single original source mutation observer for Fresh Video.
TYPED_PARAMETERS['mp4_video_behaviour_play']=['UnityEngine.Playables.Playable','UnityEngine.Playables.FrameData']
TYPED_ABIS['mp4_video_behaviour_play']='void(void*,Playable16,FrameData64,const MethodInfo*)'
SELECTIONS['mp4_video_behaviour_play']=('Solis.Timeline.SolisVideoPlayerTrackBehaviour','OnBehaviourPlay',2,tuple(TYPED_PARAMETERS['mp4_video_behaviour_play']))

FIXED_ALIAS='mp4_fixed_loop_condition'
NATIVE_IOS_ALIASES={
 'mp4_capture_native_publication':{'rva':0xb04424,'native_abi':'void(int32_t,void*)',
     'native_parameter_registers':{'propertyId':'W0','managedTexture':'X1'}},
 'mp4_animation_output_target':{'rva':0xf3f980,'native_abi':'void(void*,void*)',
     'native_parameter_registers':{'nativeOutput':'X0','nativeAnimator':'X1'}},
 'mp4_animation_output_create':{'rva':0xb576b8,'native_abi':'bool(PlayableGraph16*,void*,PlayableOutput16*)',
     'native_parameter_registers':{'graph':'X0','managedName':'X1','output':'X2'}},
 'mp4_audio_canonical_target':{'rva':0xfa3394,'native_abi':'void(void*)',
     'native_parameter_registers':{'category5Vector':'X0'}},
 'mp4_audio_source_process_target':{'rva':0xf91db8,'native_abi':'void(void*)',
     'native_parameter_registers':{'nativeAudioSource':'X0'}},
 'mp4_director_enqueue':{'rva': 14443592, 'native_abi': 'void(void*,uint32_t,const AnimationGraph16*)', 'native_parameter_registers': {'manager': 'X0', 'operation': 'W1', 'graphPointer': 'X2'}},
 'mp4_director_append_a':{'rva': 14444224, 'native_abi': 'void(void*,const AnimationGraph16*)', 'native_parameter_registers': {'manager': 'X0', 'graphPointer': 'X1'}},
 'mp4_director_append_b':{'rva': 14443692, 'native_abi': 'void(void*,const AnimationGraph16*)', 'native_parameter_registers': {'manager': 'X0', 'graphPointer': 'X1'}},
 'mp4_director_collect':{'rva': 14442060, 'native_abi': 'void(void*,void*)', 'native_parameter_registers': {'temporary': 'X0', 'queue': 'X1'}},
 'mp4_director_deferred_a':{'rva': 14443940, 'native_abi': 'void(void*)', 'native_parameter_registers': {'manager': 'X0'}},
 'mp4_director_deferred_b':{'rva': 14443808, 'native_abi': 'void(void*)', 'native_parameter_registers': {'manager': 'X0'}},
 'mp4_director_graph_create':{'rva': 14444656, 'native_abi': 'void*(void*,uintptr_t)', 'native_parameter_registers': {'manager': 'X0', 'name': 'X1'}},
 'mp4_animation_binding_build':{'rva':0xf0e458,'native_abi':'void(void*)',
     'native_parameter_registers':{'nativeAnimator':'X0'}},
}
ANIMATION_ALIASES=['mp4_animation_'+suffix for suffix in ('sample','update','begin','legacy','end','deferred','late','render')]
BASE_SHA={
 'android':'163b0c46f45603bf972e8537472dd3fd862ccbbe1b1b55d59ea8cf8069bd4927',
 'ios':'60ecc264edd253ed482519c1035264647c8e67b960fe5b3b99e1c909d9a309b0',
}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def interval_add_binding(original,platform):
    """Resolve the actual reference-sharing Add called by both Timeline factories.

    The declaration is open generic and has no codegen-module method slot. Its
    System.Object sharing body is distinct from the fully-shared value body;
    runtime admission must additionally prove the real RuntimeElement tree and
    that tree's closed MethodInfo. A name or shared code address alone is not
    the runtime type witness.
    """
    owner='UnityEngine.Timeline.IntervalTree`1';types=original.types[original.type_id(owner)][1]
    methods={}
    for mid in range(types[9],types[9]+types[16]):
        row=struct.unpack_from('<7I4H',original.m,original.h[12]+mid*36)
        if original.string(row[0])=='Add' and row[10]==1:methods[mid]=row
    assert len(methods)==1,'timeline_interval_add_declaration_differs'
    metadata=0x96dd758 if platform=='android' else 0x9c1deb8
    reg=[original.qword(metadata+k*8)for k in range(16)]
    if platform=='android':count,table=251131,0x94f2f80
    else:
        count,table=struct.unpack_from('<2Q',original.b,original.offset(0x982aed0)-104)
        assert (count,table)==(251314,0x9a33128),'timeline_generic_pointer_table_differs'
    specs={i:value for i in range(reg[8])
        if (value:=struct.unpack_from('<3i',original.b,original.offset(reg[9])+i*12))[0]in methods}
    found=[]
    for index in range(reg[4]):
        record=struct.unpack_from('<4i',original.b,original.offset(reg[5])+index*16)
        if record[0]not in specs:continue
        spec=specs[record[0]]
        assert 0<=record[1]<count and 0<=spec[1]<reg[2],'timeline_generic_index_invalid'
        instance=original.qword(reg[3]+spec[1]*8)
        argc=struct.unpack_from('<I',original.b,original.offset(instance))[0]
        assert argc==1,'timeline_interval_generic_arity_differs'
        args=[original.decode(original.qword(original.qword(instance+8)))]
        if args!=['System.Object']:continue
        address=original.qword(table+record[1]*8);method=methods[spec[0]]
        param=struct.unpack_from('<3I',original.m,original.h[22]+method[4]*12)
        parameters=[{'name':original.string(param[0]),'type':original.type_name(param[2]),'metadata_type_index':param[2]}]
        assert not method[7]&16 and original.type_name(method[2])=='System.Void'
        argument=original.qword(original.type_table+param[2]*8)
        generic_index,bits=struct.unpack_from('<QI',original.b,original.offset(argument))
        assert (bits>>16)&255==19,'timeline_interval_add_argument_not_type_variable'
        container=struct.unpack_from('<4i',original.m,original.h[30]+types[6]*16)
        generic=struct.unpack_from('<2I4H',original.m,original.h[26]+generic_index*16)
        assert container==(original.type_id(owner),1,0,generic_index)
        assert generic[0]==types[6] and generic[4]==0
        assert parameters[0]['name']=='item' and parameters[0]['type']=='generic-parameter:'+str(generic_index)
        found.append({'type':owner,'name':'Add','parameter_count':1,'parameters':parameters,'return':'System.Void',
            'rva':hex(address),'prefix':original.b[original.offset(address):original.offset(address)+16].hex(),
            'metadata_method_index':spec[0],'metadata_registration':hex(metadata),'method_spec_index':record[0],
            'generic_arguments':args,'method_pointer_index':record[1],'pointer_table':hex(table),
            'pointer_slot':hex(table+record[1]*8),'native_abi':'void(void*,void*,const MethodInfo*)'})
    assert len(found)==1,'timeline_interval_add_shared_body_ambiguous'
    value=found[0]
    expected=(0x686c3ec,147438,137831,0x96002b8)if platform=='android'else(0x4626bbc,147455,137868,0x9b40588)
    assert (int(value['rva'],16),value['method_spec_index'],value['method_pointer_index'],int(value['pointer_slot'],16))==expected
    return value


def monitor_pool_bindings(original,platform):
    """Derive actual reference-sharing ObjectPool bodies, never open stubs.

    Runtime admission must still check each concrete List pool/closed MethodInfo.
    Patching the shared body grants no ownership to other ObjectPool users.
    """
    cached=getattr(original,'_mp4_monitor_pool_bindings',None)
    if cached is not None:return cached
    owner='UnityEngine.Pool.ObjectPool`1';tid=original.type_id(owner);types=original.types[tid][1]
    methods={}
    for mid in range(types[9],types[9]+types[16]):
        row=struct.unpack_from('<7I4H',original.m,original.h[12]+mid*36)
        name=original.string(row[0])
        if name in {'Get','Release','Clear'} and row[10]==(1 if name=='Release'else 0):methods[mid]=(name,row)
    assert len(methods)==3,'monitor_pool_declarations_differ'
    metadata=0x96dd758 if platform=='android'else 0x9c1deb8
    reg=[original.qword(metadata+k*8)for k in range(16)]
    if platform=='android':count,table=251131,0x94f2f80
    else:
        count,table=struct.unpack_from('<2Q',original.b,original.offset(0x982aed0)-104)
        assert(count,table)==(251314,0x9a33128),'monitor_generic_pointer_table_differs'
    specs={i:sp for i in range(reg[8])
           if(sp:=struct.unpack_from('<3i',original.b,original.offset(reg[9])+i*12))[0]in methods}
    found={}
    for index in range(reg[4]):
        record=struct.unpack_from('<4i',original.b,original.offset(reg[5])+index*16)
        if record[0]not in specs:continue
        sp=specs[record[0]]
        if sp[1:]!=(10,-1):continue
        assert 0<=record[1]<count and sp[1]<reg[2],'monitor_generic_index_invalid'
        instance=original.qword(reg[3]+sp[1]*8)
        assert struct.unpack_from('<I',original.b,original.offset(instance))[0]==1,'monitor_pool_generic_arity_differs'
        args=[original.decode(original.qword(original.qword(instance+8)))]
        assert args==['System.Object'],'monitor_pool_not_reference_sharing'
        name,row=methods[sp[0]];parameters=[]
        assert not row[7]&16,'monitor_pool_not_instance_method'
        for pi in range(row[4],row[4]+row[10]):
            param=struct.unpack_from('<3I',original.m,original.h[22]+pi*12)
            parameters.append({'name':original.string(param[0]),'type':original.type_name(param[2]),'metadata_type_index':param[2]})
        if name!='Clear':
            type_index=row[2]if name=='Get'else parameters[0]['metadata_type_index']
            argument=original.qword(original.type_table+type_index*8)
            generic_index,bits=struct.unpack_from('<QI',original.b,original.offset(argument))
            assert(bits>>16)&255==19,'monitor_pool_argument_not_type_variable'
            container=struct.unpack_from('<4i',original.m,original.h[30]+types[6]*16)
            generic=struct.unpack_from('<2I4H',original.m,original.h[26]+generic_index*16)
            assert container==(tid,1,0,generic_index)and generic[0]==types[6]and generic[4]==0
        if name!='Get':assert original.type_name(row[2])=='System.Void'
        address=original.qword(table+record[1]*8);assert name not in found,'monitor_pool_shared_body_ambiguous'
        found[name]={'type':owner,'name':name,'parameter_count':row[10],'parameters':parameters,'return':original.type_name(row[2]),
            'rva':hex(address),'prefix':original.b[original.offset(address):original.offset(address)+16].hex(),
            'metadata_method_index':sp[0],'metadata_registration':hex(metadata),'method_spec_index':record[0],
            'generic_arguments':args,'method_pointer_index':record[1],'pointer_table':hex(table),
            'pointer_slot':hex(table+record[1]*8),'class_inst':sp[1],'method_inst':sp[2],
            'native_abi':{'Get':'void*(void*,const MethodInfo*)','Release':'void(void*,void*,const MethodInfo*)','Clear':'void(void*,const MethodInfo*)'}[name]}
    expected=({'Clear':(0x6f05164,196617,172993),'Get':(0x6f04f60,196619,172995),'Release':(0x6f05080,196621,172997)}
              if platform=='android'else{'Clear':(0x4e7ad40,196784,173182),'Get':(0x4e7ab14,196786,173184),'Release':(0x4e7ac48,196788,173186)})
    assert set(found)==set(expected),'monitor_pool_shared_bodies_missing'
    for name,v in found.items():assert(int(v['rva'],16),v['method_spec_index'],v['method_pointer_index'])==expected[name]
    original._mp4_monitor_pool_bindings=found
    return found


def derive(original,platform,alias):
    if alias in DERIVED_ALIASES:
        if alias=='mp4_animation_interval_add':value=interval_add_binding(original,platform)
        elif alias.startswith('mp4_monitor_pool_'):value=monitor_pool_bindings(original,platform)[DERIVED_ALIASES[alias]]
        else:
            from audit_mp4_actor_state import derived_callbacks
            value=derived_callbacks(original,platform)[DERIVED_ALIASES[alias]]
        row=struct.unpack_from('<7I4H',original.m,original.h[12]+value['metadata_method_index']*36)
        slot=int(value['pointer_slot'],16)
        tid=original.type_id(value['type']);module=next(name for name,first,last in original.images if first<=tid<last)
        parameters=[{'name':p['name'],('typeindex'if platform=='android'else'metadata_type_index'):p['metadata_type_index'],
            ('type'if platform=='android'else'type_name'):p['type']}for p in value['parameters']]
        return {'name':value['type']+'.'+value['name'],'module':module,
            'type_definition_index':tid, 'metadata_method_index':value['metadata_method_index'],
            'token_row':row[6]&0xffffff,'rva':value['rva']if platform=='android'else int(value['rva'],16),
            'return_type_index':row[2],'parameters':parameters,'parameter_count':value['parameter_count'],'method_flags':row[7],
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
    if platform=='ios':
        for alias in NATIVE_IOS_ALIASES:
            if alias in old['aliases']:
                del old['aliases'][alias];old['hook_names'].remove(alias)
                old['gateway_region']['bytes']-=32;old['slot_region']['bytes']-=8
    for alias in (*SELECTIONS,*DERIVED_ALIASES):
        if alias in old['aliases']:
            del old['aliases'][alias]
            if platform=='ios' and alias in old['hook_names']:
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
            if alias in old['aliases']:
                assert old['aliases'][alias]==row,(platform,alias,old['aliases'][alias],row)
                if platform=='ios' and alias not in old['hook_names']:
                    old['hook_names'].append(alias);old['gateway_region']['bytes']+=32;old['slot_region']['bytes']+=8
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
            # Exact engine-native roles share the same verified zero gap as
            # the clock and fixed-loop relays. They have no managed method slot.
            for index,(name,spec) in enumerate(NATIVE_IOS_ALIASES.items(),start=2):
                rva=spec['rva'];entry=relay['rva']+8*index
                native={'name':name,'module':None,'source':'pinned_original_engine_native',
                    **spec,'prefix16':original.b[original.offset(rva):original.offset(rva)+16].hex(),
                    'registration_pointer_slot_rva':None,'relay_in':entry,'relay_out':entry+4}
                if name in old['aliases']:assert old['aliases'][name]==native
                else:
                    old['aliases'][name]=native;old['hook_names'].append(name)
                    old['gateway_region']['bytes']+=32;old['slot_region']['bytes']+=8
                old['native_extra_relay_regions'].append(dict(relay,name=name,rva=entry))
        result[platform]=old
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--originals',type=Path,required=True);p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args();generated=profiles(args.originals)
    proof={'schema':1,'scope':'typed_offline_scene_aliases_source_only','aliases':{platform:{alias:profile['aliases'][alias]for alias in (*SELECTIONS,*DERIVED_ALIASES)}for platform,profile in generated.items()},'ios_native_fixed_condition':generated['ios']['aliases'][FIXED_ALIAS],'ios_engine_native_aliases':{name:generated['ios']['aliases'][name]for name in NATIVE_IOS_ALIASES},'previous_profiles_preserved':True}
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
