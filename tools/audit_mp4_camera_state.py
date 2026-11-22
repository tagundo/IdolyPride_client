#!/usr/bin/env python3
"""Derive bounded camera/audio state bindings and CM layouts from exact originals.

The profile is embedded in the existing camera-owner header. Evidence JSON is
written to an explicit output directory, not omitted from a native receipt.
"""
from pathlib import Path
import argparse,hashlib,json,struct
from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original,need
from audit_mp4_replay import c_exports
from audit_mp4_actor_state import runtime_type
from extract_client_schema import ClientImage
ROOT=Path(__file__).resolve().parents[1]
START='// BEGIN_ORIGINAL_CAMERA_STATE_PROFILE';END='// END_ORIGINAL_CAMERA_STATE_PROFILE'
METHODS={
 'frame_rt_descriptor':('UnityEngine.RenderTexture','get_descriptor',0),
 'frame_rt_ctor':('UnityEngine.RenderTexture','.ctor',1,('UnityEngine.RenderTextureDescriptor',)),
 'frame_rt_create':('UnityEngine.RenderTexture','Create',0),
 'frame_rt_created':('UnityEngine.RenderTexture','IsCreated',0),
 'frame_copy':('UnityEngine.Graphics','CopyTexture',2,('UnityEngine.Texture','UnityEngine.Texture')),
 'frame_copy_support':('UnityEngine.SystemInfo','get_copyTextureSupport',0),
 'frame_wrapper_destroy':('VL.VLRenderTexture','DestroyImmediate',0),
 'frame_wrapper_publish':('VL.VLRenderTexture','UpdateGlobalTexture',0),
 'audio_clip':('UnityEngine.AudioSource','get_clip',0), 'audio_set_clip':('UnityEngine.AudioSource','set_clip',1),
 'audio_samples':('UnityEngine.AudioSource','get_timeSamples',0),'audio_set_samples':('UnityEngine.AudioSource','set_timeSamples',1),
 'audio_playing':('UnityEngine.AudioSource','get_isPlaying',0),'audio_volume':('UnityEngine.AudioSource','get_volume',0),
 'audio_set_volume':('UnityEngine.AudioSource','set_volume',1),'audio_pitch':('UnityEngine.AudioSource','get_pitch',0),
 'audio_set_pitch':('UnityEngine.AudioSource','set_pitch',1),'audio_loop':('UnityEngine.AudioSource','get_loop',0),
 'audio_set_loop':('UnityEngine.AudioSource','set_loop',1),'audio_mute':('UnityEngine.AudioSource','get_mute',0),
 'audio_set_mute':('UnityEngine.AudioSource','set_mute',1),'audio_play':('UnityEngine.AudioSource','Play',0),
 'audio_stop':('UnityEngine.AudioSource','Stop',0),'audio_pause':('UnityEngine.AudioSource','Pause',0),
 'audio_unpause':('UnityEngine.AudioSource','UnPause',0),'audio_clip_samples':('UnityEngine.AudioClip','get_samples',0),
 'core_instance':('Cinemachine.CinemachineCore','get_Instance',0),
 'core_brain_count':('Cinemachine.CinemachineCore','get_BrainCount',0),
 'core_brain':('Cinemachine.CinemachineCore','GetActiveBrain',1),
 'core_vcam_count':('Cinemachine.CinemachineCore','get_VirtualCameraCount',0),
 'core_vcam':('Cinemachine.CinemachineCore','GetVirtualCamera',1),
 'brain_frame_ctor':('Cinemachine.CinemachineBrain/BrainFrame','.ctor',0),
 'blend_ctor':('Cinemachine.CinemachineBlend','.ctor',5),
 'status_ctor':('Cinemachine.CinemachineCore/UpdateStatus','.ctor',0),
 'default_camera_state':('Cinemachine.CameraState','get_Default',0),
 'vcam_previous_set':('Cinemachine.CinemachineVirtualCameraBase','set_PreviousStateIsValid',1),
 'playable_script':('UnityEngine.Playables.PlayableHandle','GetScriptInstance_Injected',1),
 'component_transform':('UnityEngine.Component','get_transform',0),'component_object':('UnityEngine.Component','get_gameObject',0),
 'component_enabled':('UnityEngine.Behaviour','get_enabled',0),'component_set_enabled':('UnityEngine.Behaviour','set_enabled',1),
 'object_active':('UnityEngine.GameObject','get_activeSelf',0),'object_set_active':('UnityEngine.GameObject','SetActive',1),
 'local_position':('UnityEngine.Transform','get_localPosition_Injected',1),'local_rotation':('UnityEngine.Transform','get_localRotation_Injected',1),
 'local_scale':('UnityEngine.Transform','get_localScale_Injected',1),'set_local_pose':('UnityEngine.Transform','SetLocalPositionAndRotation_Injected',2),
 'set_local_scale':('UnityEngine.Transform','set_localScale_Injected',1),
 'camera_near':('UnityEngine.Camera','get_nearClipPlane',0),'camera_set_near':('UnityEngine.Camera','set_nearClipPlane',1),
 'camera_far':('UnityEngine.Camera','get_farClipPlane',0),'camera_set_far':('UnityEngine.Camera','set_farClipPlane',1),
 'camera_size':('UnityEngine.Camera','get_orthographicSize',0),'camera_set_size':('UnityEngine.Camera','set_orthographicSize',1),
 'camera_set_orthographic':('UnityEngine.Camera','set_orthographic',1),
 'camera_set_physical':('UnityEngine.Camera','set_usePhysicalProperties',1),
 'camera_set_gate':('UnityEngine.Camera','set_gateFit',1),
 'camera_set_sensor':('UnityEngine.Camera','set_sensorSize_Injected',1),'camera_set_lens':('UnityEngine.Camera','set_lensShift_Injected',1),
 'camera_reset_projection':('UnityEngine.Camera','ResetProjectionMatrix',0),
 'find_objects':('UnityEngine.Object','FindObjectsOfType',2,('System.Type','System.Boolean')),
 'get_components':('UnityEngine.GameObject','GetComponentsInternal',6),
 'vcam_get_components':('Cinemachine.CinemachineVirtualCamera','GetComponentPipeline',0),
 'core_fixed_get':('Cinemachine.CinemachineCore','get_FixedFrameCount',0),
 'core_fixed_set':('Cinemachine.CinemachineCore','set_FixedFrameCount',1),
 'random_get':('UnityEngine.Random','get_state_Injected',1),'random_set':('UnityEngine.Random','set_state_Injected',1),
 'render_stack':('UnityEngine.Rendering.Universal.UniversalRenderPipeline','RenderCameraStack',2),
 'render_camera':('UnityEngine.Rendering.Universal.UniversalRenderPipeline','RenderSingleCamera',2),
 'render_camera_data':('UnityEngine.Rendering.Universal.UniversalRenderPipeline','RenderSingleCamera',3),
 'selected_renderer':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','get_scriptableRenderer',0),
 'renderer_setup':('VL.Rendering.VLSRPRenderer','Setup',2),
 'renderer_ctor':('VL.Rendering.VLSRPRenderer','.ctor',1),
 'renderer_dispose':('VL.Rendering.VLSRPRenderer','Dispose',1),
 'instantiate':('UnityEngine.Object','Instantiate',1,('UnityEngine.Object',)),
 'render_asset':('UnityEngine.Rendering.Universal.UniversalRenderPipeline','get_asset',0),
 'asset_renderer':('UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset','GetRenderer',1),
 'library_ctor':('VL.Rendering.Internal.VLPostProcessPass/MaterialLibrary','.ctor',1),
 'motion_data_ctor':('UnityEngine.Rendering.Universal.MotionVectorsPersistentData','.ctor',0),
 'motion_data_update':('UnityEngine.Rendering.Universal.MotionVectorsPersistentData','Update',1),
 'post_process_ctor':('VL.Rendering.Internal.VLPostProcessPass','.ctor',4),
 'post_process_cleanup':('VL.Rendering.Internal.VLPostProcessPass','Cleanup',0),
 'post_process_reset':('VL.Rendering.Internal.VLPostProcessPass','ResetHistory',0),
 'post_process_grain':('VL.Rendering.Internal.VLPostProcessPass','SetupGrain',2),
 'post_process_dither':('VL.Rendering.Internal.VLPostProcessPass','SetupDithering',2),
 'volume_instance':('UnityEngine.Rendering.VolumeManager','get_instance',0),
 'volume_create_stack':('UnityEngine.Rendering.VolumeManager','CreateStack',0),
 'volume_destroy_stack':('UnityEngine.Rendering.VolumeManager','DestroyStack',1),
 'volume_update_framework':('UnityEngine.Rendering.Universal.UniversalRenderPipeline','UpdateVolumeFramework',2),
 'volume_stack_component':('UnityEngine.Rendering.VolumeStack','GetComponent',1,('System.Type',)),
 'volume_stack_ctor':('UnityEngine.Rendering.VolumeStack','.ctor',0),
 'volume_stack_reload':('UnityEngine.Rendering.VolumeStack','Reload',1),
 'texture_curve_ctor':('UnityEngine.Rendering.TextureCurve','.ctor',4,('UnityEngine.Keyframe[]','System.Single','System.Boolean','UnityEngine.Vector2&')),
 'texture_curve_release':('UnityEngine.Rendering.TextureCurve','Release',0),
 'texture_curve_set_dirty':('UnityEngine.Rendering.TextureCurve','SetDirty',0),
 'animation_curve_keys':('UnityEngine.AnimationCurve','get_keys',0),
 'animation_curve_set_keys':('UnityEngine.AnimationCurve','set_keys',1),
 'shader_variant_warmed':('UnityEngine.ShaderVariantCollection','get_isWarmedUp',0),
 'use_structured_buffer':('UnityEngine.Rendering.Universal.RenderingUtils','get_useStructuredBuffer',0),
 'cine_apply_postfx':('Cinemachine.PostFX.CinemachineVolumeSettings','ApplyPostFX',1),
 'cine_dynamic_volumes':('Cinemachine.PostFX.CinemachineVolumeSettings','GetDynamicBrainVolumes',2),
 'object_name':('UnityEngine.Object','get_name',0),
 'object_hide_flags':('UnityEngine.Object','get_hideFlags',0),
 'object_destroy_immediate':('UnityEngine.Object','DestroyImmediate',2,('UnityEngine.Object','System.Boolean')),
 'game_object_ctor_name':('UnityEngine.GameObject','.ctor',1,('System.String',)),
 'game_object_layer':('UnityEngine.GameObject','get_layer',0),
 'game_object_transform':('UnityEngine.GameObject','get_transform',0),
 'game_object_set_layer':('UnityEngine.GameObject','set_layer',1),
 'object_active_hierarchy':('UnityEngine.GameObject','get_activeInHierarchy',0),
 'transform_children':('UnityEngine.Transform','get_childCount',0),
 'transform_child':('UnityEngine.Transform','GetChild',1),
 'transform_parent':('UnityEngine.Transform','get_parent',0),
 'transform_set_parent':('UnityEngine.Transform','SetParent',2),
 'string_equal':('System.String','op_Equality',2),
 'volume_enable':('UnityEngine.Rendering.Volume','OnEnable',0),
 'volume_disable':('UnityEngine.Rendering.Volume','OnDisable',0),
 'volume_update':('UnityEngine.Rendering.Volume','Update',0),
 'focus_callback':('VL.VLCinemachineFocusPoint','PostPipelineStageCallback',4),
 'height_callback':('Solis.Common.SolisCinemachineHeightController','PostPipelineStageCallback',4),
 'height_virtual_human':('Solis.Common.SolisVirtualActorController','get_HumanScale',0),
 'scriptable_ctor':('UnityEngine.ScriptableObject','.ctor',0),
 'scriptable_create_type':('UnityEngine.ScriptableObject','CreateScriptableObjectInstanceFromType',2),
 'target_image_process':('Solis.Timeline.SolisTargetImageTrackBehaviour','ProcessFrame',3),
 'target_image_destroy':('Solis.Timeline.SolisTargetImageTrackBehaviour','OnPlayableDestroy',1),
 'target_image_mixer':('Solis.Timeline.SolisTargetImageTrack','CreateTrackMixer',3),
 'target_image_create':('Solis.Timeline.SolisTargetImageClip','CreatePlayable',2),
 'raw_image_set_texture':('UnityEngine.UI.RawImage','set_texture',1),
 'raw_image_set_uv':('UnityEngine.UI.RawImage','set_uvRect',1),
 'graphic_set_color':('UnityEngine.UI.Graphic','set_color',1),
 'video_clip':('UnityEngine.Video.VideoPlayer', 'get_clip', 0),
 'video_set_clip':('UnityEngine.Video.VideoPlayer', 'set_clip', 1),
 'video_source':('UnityEngine.Video.VideoPlayer', 'get_source', 0),
 'video_set_source':('UnityEngine.Video.VideoPlayer', 'set_source', 1),
 'video_audio_mode':('UnityEngine.Video.VideoPlayer', 'get_audioOutputMode', 0),
 'video_set_audio_mode':('UnityEngine.Video.VideoPlayer', 'set_audioOutputMode', 1),
 'video_audio_tracks':('UnityEngine.Video.VideoPlayer', 'get_audioTrackCount', 0),
 'video_controlled_tracks':('UnityEngine.Video.VideoPlayer', 'get_controlledAudioTrackCount', 0),
 'video_render_mode':('UnityEngine.Video.VideoPlayer', 'get_renderMode', 0),
 'video_set_render_mode':('UnityEngine.Video.VideoPlayer', 'set_renderMode', 1),
 'video_play_on_awake':('UnityEngine.Video.VideoPlayer', 'get_playOnAwake', 0),
 'video_set_play_on_awake':('UnityEngine.Video.VideoPlayer', 'set_playOnAwake', 1),
 'video_loop':('UnityEngine.Video.VideoPlayer', 'get_isLooping', 0),
 'video_set_loop':('UnityEngine.Video.VideoPlayer', 'set_isLooping', 1),
 'video_skip':('UnityEngine.Video.VideoPlayer', 'get_skipOnDrop', 0),
 'video_set_skip':('UnityEngine.Video.VideoPlayer', 'set_skipOnDrop', 1),
 'video_wait_first':('UnityEngine.Video.VideoPlayer', 'get_waitForFirstFrame', 0),
 'video_set_wait_first':('UnityEngine.Video.VideoPlayer', 'set_waitForFirstFrame', 1),
 'video_update_mode':('UnityEngine.Video.VideoPlayer', 'get_timeUpdateMode', 0),
 'video_set_update_mode':('UnityEngine.Video.VideoPlayer', 'set_timeUpdateMode', 1),
 'video_speed':('UnityEngine.Video.VideoPlayer', 'get_playbackSpeed', 0),
 'video_set_speed':('UnityEngine.Video.VideoPlayer', 'set_playbackSpeed', 1),
 'video_time_ref':('UnityEngine.Video.VideoPlayer', 'get_timeReference', 0),
 'video_set_time_ref':('UnityEngine.Video.VideoPlayer', 'set_timeReference', 1),
 'video_playing':('UnityEngine.Video.VideoPlayer', 'get_isPlaying', 0),
 'video_paused':('UnityEngine.Video.VideoPlayer', 'get_isPaused', 0),
 'video_prepared':('UnityEngine.Video.VideoPlayer', 'get_isPrepared', 0),
 'video_prepare':('UnityEngine.Video.VideoPlayer', 'Prepare', 0),
 'video_time':('UnityEngine.Video.VideoPlayer', 'get_time', 0),
 'video_set_time':('UnityEngine.Video.VideoPlayer', 'set_time', 1),
 'video_frame':('UnityEngine.Video.VideoPlayer', 'get_frame', 0),
 'video_texture':('UnityEngine.Video.VideoPlayer', 'get_texture', 0),
 'video_pause':('UnityEngine.Video.VideoPlayer', 'Pause', 0),
 'video_stop':('UnityEngine.Video.VideoPlayer', 'Stop', 0),
 'video_step':('UnityEngine.Video.VideoPlayer', 'StepForward', 0),
 'video_send_frames':('UnityEngine.Video.VideoPlayer', 'get_sendFrameReadyEvents', 0),
 'video_set_send_frames':('UnityEngine.Video.VideoPlayer', 'set_sendFrameReadyEvents', 1),
 'video_clip_frames':('UnityEngine.Video.VideoClip', 'get_frameCount', 0),
 'video_clip_rate':('UnityEngine.Video.VideoClip', 'get_frameRate', 0),
 'video_clip_length':('UnityEngine.Video.VideoClip', 'get_length', 0),
 'video_clip_audio':('UnityEngine.Video.VideoClip', 'get_audioTrackCount', 0),
 'video_image_enable':('Solis.Common.VideoImage', 'OnEnable', 0),
 'video_image_disable':('Solis.Common.VideoImage', 'OnDisable', 0),
 'video_image_late':('Solis.Common.VideoImage', 'LateUpdate', 0),
 'maskable_image_enable':('UnityEngine.UI.MaskableGraphic', 'OnEnable', 0),
 'video_mixer_create':('Solis.Timeline.SolisVideoPlayerTrack', 'CreateTrackMixer', 3),
 'video_playable_create':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'OnPlayableCreate', 1),
 'video_playable_destroy':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'OnPlayableDestroy', 1),
 'video_prepare_frame':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'PrepareFrame', 2),
 'video_process_frame':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'ProcessFrame', 3),
 'video_update':('Solis.Timeline.SolisVideoPlayerTrackBehaviour','UpdateVideo',2),
 'video_sync':('Solis.Timeline.SolisVideoPlayerTrackBehaviour','SyncVideoToPlayable',1),
 'playable_input_weight':('UnityEngine.Playables.PlayableHandle','GetInputWeightFromIndex',1),
 'video_stop_behaviour':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'StopVideo', 0),
 'video_frame_ready':('UnityEngine.Video.VideoPlayer', 'InvokeFrameReadyCallback_Internal', 2),
 'video_seek_completed':('UnityEngine.Video.VideoPlayer', 'InvokeSeekCompletedCallback_Internal', 1),
 'video_prepare_completed':('UnityEngine.Video.VideoPlayer', 'InvokePrepareCompletedCallback_Internal', 1),
 'game_object_add_component':('UnityEngine.GameObject', 'AddComponent', 1, ('System.Type',)),
 'game_object_get_component':('UnityEngine.GameObject', 'GetComponent', 1, ('System.Type',)),
 'object_persist':('UnityEngine.Object', 'DontDestroyOnLoad', 1),
 'object_set_hide_flags':('UnityEngine.Object', 'set_hideFlags', 1),

}
EXPORTS={
 'field_offset':('il2cpp_field_get_offset','size_t(const FieldInfo*)'),
 'field_flags':('il2cpp_field_get_flags','uint32_t(const FieldInfo*)'),
 'class_fields':('il2cpp_class_get_fields','FieldInfo*(Il2CppClass*,void**)'),
 'class_size':('il2cpp_class_instance_size','int32_t(Il2CppClass*)'),
 'class_value_size':('il2cpp_class_value_size','int32_t(Il2CppClass*,uint32_t*)'),
 'class_element':('il2cpp_class_get_element_class','Il2CppClass*(Il2CppClass*)'),
 'class_rank':('il2cpp_class_get_rank','int32_t(const Il2CppClass*)'),
 'class_value_type':('il2cpp_class_is_valuetype','bool(const Il2CppClass*)'),
 'class_type':('il2cpp_class_get_type','const Il2CppType*(Il2CppClass*)'),
 'write_barrier':('il2cpp_gc_wbarrier_set_field','void(Il2CppObject*,void**,void*)'),
 'field_static_get':('il2cpp_field_static_get_value','void(FieldInfo*,void*)'),
 'field_static_set':('il2cpp_field_static_set_value','void(FieldInfo*,void*)'),
 'runtime_invoke':('il2cpp_runtime_invoke','Il2CppObject*(const MethodInfo*,void*,void**,Il2CppException**)'),
}
TYPES={
 'tracker':'Cinemachine.UpdateTracker','target_cache':'Cinemachine.TargetPositionCache',
 'impulse_listener':'Cinemachine.CinemachineImpulseListener','impulse_source':'Cinemachine.CinemachineImpulseSource',
 'impulse_independent':'Cinemachine.CinemachineIndependentImpulseListener','transform':'UnityEngine.Transform',
 'impulse_manager':'Cinemachine.CinemachineImpulseManager',
 'motion_data':'UnityEngine.Rendering.Universal.MotionVectorsPersistentData',
 'post_process':'VL.Rendering.Internal.VLPostProcessPass',
 'post_shader_constants':'VL.Rendering.Internal.VLPostProcessPass/ShaderConstants',
 'renderer':'VL.Rendering.VLSRPRenderer','renderer_data':'VL.Rendering.VLSRPRendererData',
 'post_data':'VL.Rendering.VLPostProcessData','compute_shader':'UnityEngine.ComputeShader',
 'post_library':'VL.Rendering.Internal.VLPostProcessPass/MaterialLibrary',
 'lut_pass':'UnityEngine.Rendering.Universal.Internal.ColorGradingLutPass',
 'compute_pass':'VL.Rendering.ColorGradingComputePass',
 'shader_variants':'UnityEngine.ShaderVariantCollection',
 'forward_lights':'UnityEngine.Rendering.Universal.Internal.ForwardLights',
 'cine_volume':'Cinemachine.PostFX.CinemachineVolumeSettings',
 'volume':'UnityEngine.Rendering.Volume',
 'volume_profile':'UnityEngine.Rendering.VolumeProfile',
 'focus_extension':'VL.VLCinemachineFocusPoint',
 'focus_state':'VL.VLCinemachineFocusPoint/VcamFocusPointState',
 'focus_dof':'VL.PostProcessing.VLDOF',
 'height_extension':'Solis.Common.SolisCinemachineHeightController',
 'virtual_actor':'Solis.Common.SolisVirtualActorController',
 'component':'UnityEngine.Component',
 'material':'UnityEngine.Material','shader':'UnityEngine.Shader',
 'target_image_track':'Solis.Timeline.SolisTargetImageTrack',
 'target_image_clip':'Solis.Timeline.SolisTargetImageClip',
 'target_image_mixer':'Solis.Timeline.SolisTargetImageTrackBehaviour',
 'target_image_behaviour':'Solis.Timeline.SolisTargetImageClipBehaviour',
 'raw_image':'UnityEngine.UI.RawImage','rect_transform':'UnityEngine.RectTransform',
 'video_player':'UnityEngine.Video.VideoPlayer',
 'video_clip':'UnityEngine.Video.VideoClip',
 'video_image':'Solis.Common.VideoImage',
 'video_track':'Solis.Timeline.SolisVideoPlayerTrack',
 'video_mixer':'Solis.Timeline.SolisVideoPlayerTrackBehaviour',
 'video_clip_asset':'Solis.Timeline.SolisVideoPlayerClip',
 'game_object':'UnityEngine.GameObject',

}
RENDER_FIELDS={
 'video_image_player':('Solis.Common.VideoImage', '_videoPlayer'),
 'video_track_loop':('Solis.Timeline.SolisVideoPlayerTrack', 'Loop'),
 'video_mixer_videoplayer':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'VideoPlayer'),
 'video_mixer_videoimage':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'VideoImage'),
 'video_mixer_isrecording':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'IsRecording'),
 'video_mixer_isplaymode':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'IsPlayMode'),
 'video_mixer_loop':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', 'Loop'),
 'video_mixer_playedonce':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', '_playedOnce'),
 'video_mixer_preparing':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', '_preparing'),
 'video_mixer_drifted':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', '_drifted'),
 'video_mixer_driftedtime':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', '_driftedTime'),
 'video_mixer_seektime':('Solis.Timeline.SolisVideoPlayerTrackBehaviour', '_seekTime'),
 'video_event_preparecompleted':('UnityEngine.Video.VideoPlayer', 'prepareCompleted'),
 'video_event_looppointreached':('UnityEngine.Video.VideoPlayer', 'loopPointReached'),
 'video_event_started':('UnityEngine.Video.VideoPlayer', 'started'),
 'video_event_framedropped':('UnityEngine.Video.VideoPlayer', 'frameDropped'),
 'video_event_errorreceived':('UnityEngine.Video.VideoPlayer', 'errorReceived'),
 'video_event_seekcompleted':('UnityEngine.Video.VideoPlayer', 'seekCompleted'),
 'video_event_clockresyncoccurred':('UnityEngine.Video.VideoPlayer', 'clockResyncOccurred'),
 'video_event_frameready':('UnityEngine.Video.VideoPlayer', 'frameReady'),
 'target_controller_instance':('VL.Core.VLMonoBehaviourSingleton`1', '_instance'),
 'target_mixer_image':('Solis.Timeline.SolisTargetImageTrackBehaviour', '_rawImage'),
 'target_mixer_enabled':('Solis.Timeline.SolisTargetImageTrackBehaviour', '_rawImageInitialStateEnabled'),
 'target_clip_template':('Solis.Timeline.SolisTargetImageClip', 'behaviour'),
 'target_clip_reference':('Solis.Timeline.SolisTargetImageClip', 'trackingTargetReference'),
 'target_behaviour_target':('Solis.Timeline.SolisTargetImageClipBehaviour', 'trackingTarget'),
 'target_behaviour_alpha':('Solis.Timeline.SolisTargetImageClipBehaviour', 'alpha'),
 'target_behaviour_center':('Solis.Timeline.SolisTargetImageClipBehaviour', 'center'),
 'target_behaviour_scale':('Solis.Timeline.SolisTargetImageClipBehaviour', 'scale'),
 'raw_image_texture':('UnityEngine.UI.RawImage', 'm_Texture'),
 'raw_image_uv':('UnityEngine.UI.RawImage', 'm_UVRect'),
 'graphic_rect':('UnityEngine.UI.Graphic', 'm_RectTransform'),
 'graphic_color':('UnityEngine.UI.Graphic','m_Color'),
 'graphic_dirty_layout':('UnityEngine.UI.Graphic', 'm_OnDirtyLayoutCallback'),
 'graphic_dirty_vertices':('UnityEngine.UI.Graphic', 'm_OnDirtyVertsCallback'),
 'graphic_dirty_material':('UnityEngine.UI.Graphic', 'm_OnDirtyMaterialCallback'),
 'graphic_mask_material':('UnityEngine.UI.MaskableGraphic', 'm_MaskMaterial'),
 'graphic_parent_mask':('UnityEngine.UI.MaskableGraphic', 'm_ParentMask'),
 'graphic_cull_event':('UnityEngine.UI.MaskableGraphic', 'm_OnCullStateChanged'),
 'graphic_stencil':('UnityEngine.UI.MaskableGraphic', 'm_StencilValue'),
 'controller_additional':('VL.Rendering.VLSRPCameraController','_additionalCameraData'),
 'additional_camera':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','m_Camera'),
 'additional_camera_type':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','m_CameraType'),
 'additional_camera_stack':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','m_Cameras'),
 'additional_motion':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','m_MotionVectorsPersistentData'),
 'additional_post_processing':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','m_RenderPostProcessing'),
 'renderer_post_process':('VL.Rendering.VLSRPRenderer','m_PostProcessPass'),
 'renderer_final_post_process':('VL.Rendering.VLSRPRenderer','m_FinalPostProcessPass'),
 'renderer_lut_pass':('VL.Rendering.VLSRPRenderer','m_ColorGradingLutPass'),
 'renderer_compute_pass':('VL.Rendering.VLSRPRenderer','m_ColorGradingComputePass'),
 'renderer_forward_lights':('VL.Rendering.VLSRPRenderer','m_ForwardLights'),
 'forward_structured':('UnityEngine.Rendering.Universal.Internal.ForwardLights','m_UseStructuredBuffer'),
 'lut_ldr_material':('UnityEngine.Rendering.Universal.Internal.ColorGradingLutPass','m_LutBuilderLdr'),
 'lut_hdr_material':('UnityEngine.Rendering.Universal.Internal.ColorGradingLutPass','m_LutBuilderHdr'),
 'compute_pass_shader':('VL.Rendering.ColorGradingComputePass','_lutCompute'),
 'post_library':('VL.Rendering.Internal.VLPostProcessPass','m_Materials'),
 'renderer_data_features':('UnityEngine.Rendering.Universal.ScriptableRendererData','m_RendererFeatures'),
 'renderer_data_feature_map':('UnityEngine.Rendering.Universal.ScriptableRendererData','m_RendererFeatureMap'),
 'renderer_data_post':('UnityEngine.Rendering.Universal.ForwardRendererData','postProcessData'),
 'renderer_data_shaders':('UnityEngine.Rendering.Universal.ForwardRendererData','shaders'),
 'renderer_data_xr':('UnityEngine.Rendering.Universal.ForwardRendererData','xrSystemData'),
 'renderer_data_mode':('UnityEngine.Rendering.Universal.ForwardRendererData','m_RenderingMode'),
 'renderer_mode':('VL.Rendering.VLSRPRenderer','m_RenderingMode'),
 'renderer_data_blend_shader':('VL.Rendering.VLSRPRendererData','vlBlendDownscale'),
 'post_shaders':('UnityEngine.Rendering.Universal.PostProcessData','shaders'),
 'pipeline_renderers':('UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset','m_Renderers'),
 'pipeline_renderer_data':('UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset','m_RendererDataList'),
 'pipeline_default_renderer':('UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset','m_DefaultRendererIndex'),
 'additional_renderer_index':('UnityEngine.Rendering.Universal.UniversalAdditionalCameraData','m_RendererIndex'),
 'post_compute_shader':('VL.Rendering.VLPostProcessData','lutCompute'),
 'post_shader_variants':('VL.Rendering.VLPostProcessData','vlPostProcessVariant'),
 'post_data':('VL.Rendering.Internal.VLPostProcessPass','m_Data'),
 'post_compute':('VL.Rendering.Internal.VLPostProcessPass','_computeGradingAvailable'),
 'post_blit_material':('VL.Rendering.Internal.VLPostProcessPass','m_BlitMaterial'),
 'post_reset':('VL.Rendering.Internal.VLPostProcessPass','m_ResetHistory'),
 'post_dither_index':('VL.Rendering.Internal.VLPostProcessPass','m_DitheringTextureIndex'),
 'post_bokeh_kernel':('VL.Rendering.Internal.VLPostProcessPass','m_BokehKernel'),
 'post_bokeh_hash':('VL.Rendering.Internal.VLPostProcessPass','m_BokehHash'),
 'post_event':('UnityEngine.Rendering.Universal.ScriptableRenderPass','<renderPassEvent>k__BackingField'),
 'motion_view':('UnityEngine.Rendering.Universal.MotionVectorsPersistentData','m_ViewProjection'),
 'motion_previous_view':('UnityEngine.Rendering.Universal.MotionVectorsPersistentData','m_PreviousViewProjection'),
 'motion_last_frame':('UnityEngine.Rendering.Universal.MotionVectorsPersistentData','m_LastFrameIndex'),
 'motion_previous_aspect':('UnityEngine.Rendering.Universal.MotionVectorsPersistentData','m_PrevAspectRatio'),
 'extension_owner':('Cinemachine.CinemachineExtension','m_vcamOwner'),
 'extension_extra_state':('Cinemachine.CinemachineExtension','mExtraState'),
 'focus_offset':('VL.VLCinemachineFocusPoint','offset'),
 'focus_target':('VL.VLCinemachineFocusPoint','target'),
 'focus_state_profile':('VL.VLCinemachineFocusPoint/VcamFocusPointState','profile'),
 'height_virtual':('Solis.Common.SolisCinemachineHeightController','_virtualActorController'),
 'height_actor':('Solis.Common.SolisCinemachineHeightController','_solisActorController'),
 'volume_global':('UnityEngine.Rendering.Volume','isGlobal'),
 'volume_priority':('UnityEngine.Rendering.Volume','priority'),
 'volume_blend':('UnityEngine.Rendering.Volume','blendDistance'),
 'volume_weight':('UnityEngine.Rendering.Volume','weight'),
 'volume_shared':('UnityEngine.Rendering.Volume','sharedProfile'),
 'volume_previous_layer':('UnityEngine.Rendering.Volume','m_PreviousLayer'),
 'volume_previous_priority':('UnityEngine.Rendering.Volume','m_PreviousPriority'),
 'volume_internal':('UnityEngine.Rendering.Volume','m_InternalProfile'),

}
RENDER_ARRAY_FIELDS={
 'root_materials':('VL.Rendering.VLSRPRenderer',('m_BlitMaterial','m_CopyDepthMaterial','m_SamplingMaterial','m_ScreenspaceShadowsMaterial','m_TileDepthInfoMaterial','m_TileDeferredMaterial','m_StencilDeferredMaterial','m_BlendDownscaleMaterial')),
 'library_materials':('VL.Rendering.Internal.VLPostProcessPass/MaterialLibrary',('stopNaN','subpixelMorphologicalAntialiasing','gaussianDepthOfField','bokehDepthOfField','cameraMotionBlur','paniniProjection','bloom','uber','finalPass','vlBloom','vlFlare','vlDOF','vlStarStreak')),
 'renderer_shaders':('UnityEngine.Rendering.Universal.ForwardRendererData/ShaderResources',('blitPS','copyDepthPS','screenSpaceShadowPS','samplingPS','tileDepthInfoPS','tileDeferredPS','stencilDeferredPS')),
 'renderer_ctor_shaders':('UnityEngine.Rendering.Universal.ForwardRendererData/ShaderResources',('blitPS','copyDepthPS','samplingPS','screenSpaceShadowPS','stencilDeferredPS')),
 'post_standard_shaders':('UnityEngine.Rendering.Universal.PostProcessData/ShaderResources',('stopNanPS','subpixelMorphologicalAntialiasingPS','gaussianDepthOfFieldPS','bokehDepthOfFieldPS','cameraMotionBlurPS','paniniProjectionPS','lutBuilderLdrPS','lutBuilderHdrPS','bloomPS','uberPostPS','finalPostPassPS')),
 'post_vl_shaders':('VL.Rendering.VLPostProcessData',('vlBloom','vlFlare','vlDOF','vlStarStreak')),
 'forward_light_arrays':('UnityEngine.Rendering.Universal.Internal.ForwardLights',('m_AdditionalLightPositions','m_AdditionalLightColors','m_AdditionalLightAttenuations','m_AdditionalLightSpotDirections','m_AdditionalLightOcclusionProbeChannels')),
}
PRIMITIVE={2:1,3:2,4:1,5:1,6:2,7:2,8:4,9:4,10:8,11:8,12:4,13:8}
def info(o,p):
 data=o.qword(p);bits=struct.unpack_from('<I',o.b,o.offset(p)+8)[0]
 return data,(bits>>16)&255,bits&65535

def qualified(o,tid):
 name,row=o.types[tid]
 if row[3]<o.type_count:return o.type_name(row[3])+'/'+o.string(row[0])
 return name

def cell(o,p,depth=0):
 need(depth<12,'camera_value_type_depth')
 data,code,_=info(o,p)
 if code in PRIMITIVE:return PRIMITIVE[code],[]
 if code in(14,18,20,28,29):return 8,[0]
 if code==21:
  base=o.qword(data);tid,basecode,_=info(o,base)
  need(basecode in(17,18),'camera_generic_base_invalid')
  if not(o.types[tid][1][24]&1):return 8,[0]
  raise ValueError('camera_generic_value_unavailable')
 if code==17:
  row=o.types[data][1];p_size=o.qword(o.size_table+data*8);size=struct.unpack_from('<I',o.b,o.offset(p_size))[0]-16
  need(0<size<=4096,'camera_value_size_invalid');refs=[]
  fieldp=o.qword(o.field_table+data*8)
  for index,fid in enumerate(range(row[8],row[8]+row[18])):
   _,ti,_=struct.unpack_from('<3I',o.m,o.h[24]+fid*12);tp=o.qword(o.type_table+ti*8)
   _,_,attrs=info(o,tp)
   if attrs&16:continue
   at=struct.unpack_from('<i',o.b,o.offset(fieldp)+index*4)[0]-16
   n,child=cell(o,tp,depth+1);need(at>=0 and at+n<=size,'camera_value_field_outside')
   refs.extend(at+x for x in child)
  return size,sorted(set(refs))
 raise ValueError('camera_field_kind_unsupported:'+str(code))

def schemas(o):
 result=[]
 for tid,(name,row)in o.types.items():
  if not(qualified(o,tid).startswith(('Cinemachine.','UnityEngine.Events.'))or name in('.CinemachineMixer','.CinemachineShotPlayable','UnityEngine.Rendering.Volume','UnityEngine.Rendering.VolumeProfile','Solis.Common.SolisCinemachineHeightController','VL.VLCinemachineFocusPoint')):continue
  # Pure value schemas are referenced through fields/arrays, not object roots.
  if row[24]&1:continue
  ancestry=[];at=tid;seen=set()
  while at not in seen:
   seen.add(at);n,tr=o.types[at];ancestry.append((at,n,tr))
   if tr[4]>=o.type_count:break
   parent=o.type_name(tr[4]);ids=o.type_ids.get(parent,[])
   if len(ids)!=1:break
   at=ids[0]
   if parent in('UnityEngine.MonoBehaviour','UnityEngine.ScriptableObject','System.Object'):break
  parent=o.types[at][0];p_size=o.qword(o.size_table+at*8);begin=struct.unpack_from('<I',o.b,o.offset(p_size))[0]if parent!='System.Object'else 16
  p_size=o.qword(o.size_table+tid*8);size=struct.unpack_from('<I',o.b,o.offset(p_size))[0]
  entry={'name':qualified(o,tid),'space':o.string(row[1]),'leaf':o.string(row[0]),'definition':tid,'begin':begin,'bytes':size-begin,'references':[],'supported':True,'fields':[]}
  try:
   need(16<=begin<=size<=65536,'camera_object_size_invalid')
   for parent_tid,n,tr in reversed(ancestry):
    ptr=o.qword(o.field_table+parent_tid*8)
    for index,fid in enumerate(range(tr[8],tr[8]+tr[18])):
     ni,ti,_=struct.unpack_from('<3I',o.m,o.h[24]+fid*12);tp=o.qword(o.type_table+ti*8);_,_,attrs=info(o,tp)
     if attrs&16:continue
     off=struct.unpack_from('<i',o.b,o.offset(ptr)+index*4)[0];nbytes,refs=cell(o,tp)
     need(off>=begin and off+nbytes<=size,'camera_object_field_outside')
     entry['references'].extend(off-begin+x for x in refs)
     entry['fields'].append({'name':o.string(ni),'offset':off,'bytes':nbytes,'type':o.type_name(ti),'references':refs,'field_index':fid})
   entry['references']=sorted(set(entry['references']))
   entry['runtime_type']=runtime_type(o,qualified(o,tid),18)
  except (ValueError,KeyError)as e:entry['supported']=False;entry['reason']=str(e)
  result.append(entry)
 return result

def value_schemas(o):
 result=[]
 for tid,(name,row) in o.types.items():
  if not qualified(o,tid).startswith('Cinemachine.') or not(row[24]&1):continue
  try:
   ptr=o.qword(o.type_table+row[2]*8);size,refs=cell(o,ptr)
   result.append({'name':qualified(o,tid),'space':o.string(row[1]),'leaf':o.string(row[0]),'definition':tid,'bytes':size,'references':refs,'runtime_type':runtime_type(o,qualified(o,tid),17)})
  except ValueError:continue
 return result

def focus_factory_binding(o,platform):
 """Resolve actual shared CreateInstance<T> and each exact Focus callsite.

 The generic wrapper calls CreateInstance(Type), which tailbranches to its
 native icall. CreateScriptableObjectInstanceFromType's managed AOT wrapper is
 therefore not an observer route for this source path.
 """
 metadata=0x96dd758 if platform=='android'else 0x9c1deb8
 reg=[o.qword(metadata+k*8)for k in range(16)]
 roles=[('profile',0x99a8b70,0x9218a84),('dof',0x9a08970,0x9218a90)]if platform=='android'else[('profile',0xa46f328,0x7b9e2a0),('dof',0xa46f320,0x7b9e2ac)]
 rows=[];canonical=None
 for role,slot,ret in roles:
  usage=o.qword(slot)if platform=='android'else slot;encoded=o.qword(usage);kind=(encoded>>29)&7;ix=(encoded&0x1fffffff)>>1
  need(kind==6 and ix<reg[8],'focus_factory_methodspec_usage')
  spec=struct.unpack_from('<3i',o.b,o.offset(reg[9])+ix*12)
  need(spec[1]<0 and spec[2]>=0,'focus_factory_static_generic_context')
  inst=o.qword(reg[3]+spec[2]*8);argc=struct.unpack_from('<I',o.b,o.offset(inst))[0];argv=o.qword(inst+8)
  args=[o.decode(o.qword(argv+k*8))for k in range(argc)]
  need(args==(['UnityEngine.Rendering.VolumeProfile']if role=='profile'else['VL.PostProcessing.VLDOF']),'focus_factory_closed_role')
  if canonical is None:
   for si in range(reg[8]):
    sp=struct.unpack_from('<3i',o.b,o.offset(reg[9])+si*12)
    if sp[0]!=spec[0]or sp[1]>=0 or sp[2]<0:continue
    ip=o.qword(reg[3]+sp[2]*8);ac=struct.unpack_from('<I',o.b,o.offset(ip))[0];av=o.qword(ip+8)
    if ac==1 and o.decode(o.qword(av))=='System.Object':canonical=si;break
  need(canonical is not None,'focus_factory_canonical_missing')
  record=None
  for ri in range(reg[4]):
   rr=struct.unpack_from('<4i',o.b,o.offset(reg[5])+ri*16)
   if rr[0]==canonical:record=rr;break
  need(record is not None,'focus_factory_canonical_function_missing')
  table=0x94f2f80 if platform=='android'else struct.unpack_from('<2Q',o.b,o.offset(0x982aed0)-104)[1]
  shared=o.qword(table+record[1]*8)
  need(shared==(0x60993a8 if platform=='android'else 0x3bb24f8),'focus_factory_shared_function_differs')
  call=struct.unpack_from('<I',o.b,o.offset(ret-4))[0];delta=(call&0x3ffffff)*4
  if delta&0x8000000:delta-=0x10000000
  need(call>>26==0b100101 and ret-4+delta==shared,'focus_factory_direct_callsite')
  rows.append({'role':role,'input_slot':hex(slot),'method_info_cell':hex(usage),'encoded':hex(encoded),'method_spec_index':ix,'method_spec':list(spec),'generic_arguments':args,'canonical_spec_index':canonical,'canonical_record':list(record),'metadata_registration':hex(metadata),'pointer_slot':hex(table+record[1]*8),'return_address':hex(ret),'call_site':{'rva':hex(ret-4),'prefix':o.b[o.offset(ret-4):o.offset(ret-4)+16].hex()}})
 owner='VL.VLCinemachineFocusPoint/VcamFocusPointState';creator=o.method(owner,'CreateProfile',0)
 mid=rows[0]['method_spec'][0];method_row=struct.unpack_from('<7I4H',o.m,o.h[12]+mid*36)
 tid=o.type_id('UnityEngine.ScriptableObject');decl=o.types[tid][1]
 need(decl[9]<=mid<decl[9]+decl[16]and o.string(method_row[0])=='CreateInstance'and method_row[10]==0 and bool(method_row[7]&16),'focus_factory_open_declaration_differs')
 module=next(name for name,first,last in o.images if first<=tid<last)
 method={'metadata_method_index':mid,'token_row':method_row[6]&0xffffff,'module':module}
 shared={'type':'UnityEngine.ScriptableObject','name':'CreateInstance<T>','rva':hex(shared),'prefix':o.b[o.offset(shared):o.offset(shared)+16].hex(),'metadata_method_index':method['metadata_method_index'],'token_row':method['token_row'],'module':method['module'],'native_abi':'void*(const MethodInfo* closedGenericX0)','generic_arguments':['System.Object'],'method_spec_index':canonical,'metadata_registration':hex(metadata),'pointer_table':hex(table),'method_pointer_index':record[1],'pointer_slot':hex(table+record[1]*8)}
 return {'shared':shared,'creator':creator,'roles':rows,'route':'shared reference generic CreateInstance<T> -> CreateInstance(Type) -> native icall; no AOT FromType wrapper hook'}

def build(o,platform):
 methods={name:o.method(*spec)for name,spec in METHODS.items()}
 for row in methods.values():
  args=[]if row['static']else['void*']
  if row['name']=='PostPipelineStageCallback':need(o.fields('Cinemachine.CinemachineCore/Stage')['value__']['type']=='System.Int32','camera_stage_abi_differs')
  args.extend('int32_t'if row['name']=='PostPipelineStageCallback'and x['type']=='.Stage'else o.native_type(x['type'])for x in row['parameters'])
  row['abi']=o.native_type(row['return'])+'('+','.join([*args,'const MethodInfo*'])+')'
 methods['default_camera_state']['abi']='CameraState232 return indirectX8(const MethodInfo* X0)'
 structured_at=int(methods['use_structured_buffer']['rva'],16)
 structured_prefix=o.b[o.offset(structured_at):o.offset(structured_at)+8]
 need(structured_prefix.hex() in ('e0031f2ac0035fd6','00008052c0035fd6'),'camera_structured_buffer_not_literal_false')
 need(o.fields('UnityEngine.Object')['m_CachedPtr']['offset']==16,'audio_native_pointer_field_differs')
 need(o.struct_layout('UnityEngine.Random/State')['bytes']==16,'camera_random_state_size_differs')
 context=o.struct_layout('UnityEngine.Rendering.ScriptableRenderContext')
 need(context['bytes']==8 and context['fields']=={'m_Ptr':0},'camera_render_context_layout_differs')
 render_fields={name:{'owner':owner,'name':field,**o.fields(owner)[field]}for name,(owner,field)in RENDER_FIELDS.items()}
 # The inherited closed generic field has offset0 in the open definition's
 # static table. Prove its declaration and concrete argument from metadata,
 # prove the exact receiver load in the retained property, then ALSO require
 # runtime FieldInfo offset56 in the concrete Height admission callback.
 parent=o.type_name(o.types[o.type_id('Solis.Common.SolisVirtualActorController')][1][4])
 need(parent=='VL.VLVirtualActorController`1<Solis.Common.ISolisActorController>','camera_virtual_controller_instantiation_differs')
 field=o.fields('VL.VLVirtualActorController`1')['controllerBase']
 need(field['type'].startswith('generic-parameter:'),'camera_virtual_controller_generic_field_differs')
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
 at=int(methods['height_virtual_human']['rva'],16)
 instructions=[{'rva':hex(i.address),'instruction':i.mnemonic+' '+i.op_str}for i in Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(o.b[o.offset(at):o.offset(at)+0xa0],at)]
 import re
 loads=[i for i in instructions if re.fullmatch(r'ldr x\d+, \[x\d+, #0x38\]',i['instruction'])]
 need(bool(loads),'camera_virtual_controller_native_load_missing')
 render_fields['height_virtual_controller']={'owner':parent,'name':'controllerBase',**field,'declared_offset':field['offset'],'offset':56,'instantiated_type':'Solis.Common.ISolisActorController','native_property':methods['height_virtual_human'],'receiver_loads':loads,'runtime_field_info_required':True}

 for name,field in [('state_custom0','mCustom0'),('state_custom1','mCustom1'),('state_custom2','mCustom2'),('state_custom3','mCustom3'),('state_custom_overflow','m_CustomOverflow'),('state_custom_count','<NumCustomBlendables>k__BackingField')]:
  value=o.fields('Cinemachine.CameraState')[field]
  render_fields[name]={'owner':'Cinemachine.CameraState','name':field,**value,'offset':value['offset']-16,'unboxed':True}
 for name,field in [('camera_data_camera','camera'),('camera_data_aspect','aspectRatio'),('camera_data_xr','xr'),('camera_data_dither','isDitheringEnabled')]:
  value=o.fields('UnityEngine.Rendering.Universal.CameraData')[field]
  render_fields[name]={'owner':'UnityEngine.Rendering.Universal.CameraData','name':field,**value,'offset':value['offset']-16,'unboxed':True}
 return {'focus_factory':focus_factory_binding(o,platform),'platform':platform,'native_sha256':hashlib.sha256(o.b).hexdigest(),'metadata_sha256':hashlib.sha256(o.m).hexdigest(),'methods':methods,'exports':c_exports(o,platform,selected=EXPORTS),'types':{name:runtime_type(o,owner,8 if owner=='System.Int32'else 18)for name,owner in TYPES.items()},'type_names':{name:{'space':o.string(o.types[o.type_id(owner)][1][1]),'leaf':o.string(o.types[o.type_id(owner)][1][0])}for name,owner in TYPES.items()},'schemas':schemas(o),'values':value_schemas(o),'render_fields':render_fields,'render_arrays':{name:[{'owner':owner,'name':field,**o.fields(owner)[field]}for field in fields]for name,(owner,fields)in RENDER_ARRAY_FIELDS.items()},'render_context':context,'enums':{name:{'value':o.enum_value(owner,field)[0],'proof':o.enum_value(owner,field)[1]}for name,owner,field in [('camera_base','UnityEngine.Rendering.Universal.CameraRenderType','Base'),('projection_explicit','UnityEngine.Camera/ProjectionMatrixMode','Explicit'),('projection_implicit','UnityEngine.Camera/ProjectionMatrixMode','Implicit'),('projection_physical','UnityEngine.Camera/ProjectionMatrixMode','PhysicalPropertiesBased'),('camera_late','Cinemachine.CinemachineBrain/UpdateMethod','LateUpdate'),('camera_smart','Cinemachine.CinemachineBrain/UpdateMethod','SmartUpdate'),('cache_disabled','Cinemachine.TargetPositionCache/Mode','Disabled'),('blend_late','Cinemachine.CinemachineBrain/BrainUpdateMethod','LateUpdate'),('video_audio_none','UnityEngine.Video.VideoAudioOutputMode','None'),('video_render_api','UnityEngine.Video.VideoRenderMode','APIOnly'),('video_source_clip','UnityEngine.Video.VideoSource','VideoClip'),('private_hide_flags','UnityEngine.HideFlags','HideAndDontSave')]},'fields':{name:o.fields(name)for name in ['.CinemachineMixer','.CinemachineShotPlayable','Cinemachine.CinemachineBrain','Cinemachine.CinemachineBrain/BrainFrame','Cinemachine.CinemachineCore','Cinemachine.CinemachineCore/UpdateStatus','Cinemachine.UpdateTracker','Cinemachine.UpdateTracker/UpdateStatus','Cinemachine.TargetPositionCache','Cinemachine.CinemachineVirtualCamera','Cinemachine.CinemachineVirtualCameraBase','Cinemachine.CinemachineComponentBase','Cinemachine.CinemachineBasicMultiChannelPerlin','Cinemachine.CinemachineImpulseManager','UnityEngine.Events.UnityEventBase','UnityEngine.Events.InvokableCallList','UnityEngine.Events.PersistentCallGroup']}}

def native_audio(o,platform,native):
 raw=native.read_bytes();digest=hashlib.sha256(raw).hexdigest()
 expected={'android':'c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85','ios':'b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf'}[platform]
 need(digest==expected,'camera_audio_native_sha_differs')
 image=o if platform=='ios'else ClientImage(o.m,raw);offset=image.offset if platform=='ios'else image.file_offset
 locations={'android':(0x9393e4,0x939030,0x9300fc),'ios':(0xf90740,0xf90374,0xf8707c)}[platform]
 rows={name:{'rva':hex(at),'prefix':raw[offset(at):offset(at)+16].hex()}for name,at in zip(('pause','unpause','playing'),locations)}
 need(bytes.fromhex(rows['pause']['prefix'])[:8]==bytes.fromhex('2800805208b00e39'),'camera_audio_pause_store_differs')
 need(bytes.fromhex(rows['unpause']['prefix'])[:4]==bytes.fromhex('1fb00e39'),'camera_audio_unpause_store_differs')
 # Verify every address used by the conservative source-channel admission
 # against actual loads in the original getter body, not an invented getter.
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
 instructions=[i.mnemonic+' '+i.op_str for i in Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(raw[offset(locations[2]):offset(locations[2])+0xc0],locations[2])]
 for operand in('#0x395]','#0x360]','#0x320]','#0x318','#0x400]'):
  need(any(operand in line for line in instructions),'camera_audio_channel_witness_missing:'+operand)
 return {'sha256':digest,'cached_ptr':16,'paused_offset':0x3ac,'fast_flag':0x395,'primary':0x360,'supplementary_head':0x318,'supplementary_tail':0x320,'supplementary_count':0x400,'getter_instructions':instructions,**rows}

def native_camera(o,platform,native):
 raw=native.read_bytes();image=o if platform=='ios'else ClientImage(o.m,raw);offset=image.offset if platform=='ios'else image.file_offset
 # Same complete originals as native_audio above. Setter clears the authority
 # byte while ResetAspect writes one; the projection getter uses native +514.
 locations={'android':{'reset':0xbe5da8,'set':0xbe8828,'projection':0xbf4b44,'reset_store':0xbe5e6c,'set_store':0xbe8844},'ios':{'reset':0x11b8730,'set':0x11bb360,'projection':0x11c87b4,'reset_store':0x11b87f8,'set_store':0x11bb37c}}[platform]
 rows={name:{'rva':hex(at),'prefix':raw[offset(at):offset(at)+16].hex()}for name,at in locations.items()}
 need(bytes.fromhex(rows['set_store']['prefix'])[:4]==bytes.fromhex('1f881439'),'camera_aspect_authority_clear_differs')
 need(bytes.fromhex(rows['reset_store']['prefix'])[:4]==bytes.fromhex('748a1439'),'camera_aspect_authority_reset_differs')
 return {'sha256':hashlib.sha256(raw).hexdigest(),'cached_ptr':16,'automatic_aspect_offset':0x522,**rows}

def render(data):
 lines=[START,'namespace idoly_mp4_camera_profile {','struct Binding {uintptr_t rva;uint8_t prefix[16];};','struct Profile {']
 for name in [*METHODS,*EXPORTS]:lines.append(' Binding '+name+';')
 lines+=['};']
 extra_fields={'brain_update':('Cinemachine.CinemachineBrain','m_UpdateMethod'),'brain_blend_update':('Cinemachine.CinemachineBrain','m_BlendUpdateMethod'),'shot_camera':('.CinemachineShotPlayable','VirtualCamera'),'vcam_pipeline':('Cinemachine.CinemachineVirtualCamera','m_ComponentPipeline'),'vcam_extensions':('Cinemachine.CinemachineVirtualCameraBase','mExtensions'),'component_owner':('Cinemachine.CinemachineComponentBase','m_vcamOwner'),'perlin_time':('Cinemachine.CinemachineBasicMultiChannelPerlin','mNoiseTime'),'impulse_active':('Cinemachine.CinemachineImpulseManager','m_ActiveEvents'),'event_calls':('UnityEngine.Events.UnityEventBase','m_Calls'),'event_persistent_group':('UnityEngine.Events.UnityEventBase','m_PersistentCalls'),'event_runtime_list':('UnityEngine.Events.InvokableCallList','m_RuntimeCalls'),'event_persistent_list':('UnityEngine.Events.InvokableCallList','m_PersistentCalls'),'event_executing_list':('UnityEngine.Events.InvokableCallList','m_ExecutingCalls'),'persistent_group_list':('UnityEngine.Events.PersistentCallGroup','m_Calls')}
 lines+=['struct ExtraLayout {']
 for name,(owner,field)in extra_fields.items():
  values=[d['fields'][owner][field]['offset']for d in data.values()];need(len(set(values))==1,'camera_extra_field_differs:'+name);lines.append(' static constexpr uint32_t '+name+'='+hex(values[0])+';')
 for name in next(iter(data.values()))['enums']:
  values=[d['enums'][name]['value']for d in data.values()];need(len(set(values))==1,'camera_enum_differs:'+name);lines.append(' static constexpr int32_t '+name+'='+str(values[0])+';')
 lines+=['};']
 lines+=['struct RenderLayout {']
 for name in next(iter(data.values()))['render_fields']:
  values=[d['render_fields'][name]['offset']for d in data.values()];need(len(set(values))==1,'camera_render_field_differs:'+name)
  lines.append(' static constexpr uint32_t '+name+'='+hex(values[0])+';')
 for name in RENDER_ARRAY_FIELDS:
  values=[[f['offset']for f in d['render_arrays'][name]]for d in data.values()];need(all(v==values[0]for v in values),'camera_render_array_fields_differ:'+name)
  lines.append(' static constexpr uint32_t '+name+'['+str(len(values[0]))+']={'+','.join(hex(v)for v in values[0])+'};')
 lines+=['};']
 for p,d in data.items():
  lines+=['inline constexpr Profile '+p+'_profile={']
  for name in [*METHODS,*EXPORTS]:
   r=(d['methods']if name in METHODS else d['exports'])[name];prefix=r['prefix']
   lines.append(' {'+r['rva']+',{'+','.join('0x'+prefix[i:i+2]for i in range(0,32,2))+'}}, // '+name)
  lines+=['};']
 lines+=['struct FocusFactory {Binding shared,creator;uintptr_t method_cells[2],return_sites[2];Binding call_sites[2];};']
 for p,d in data.items():
  f=d['focus_factory'];bindings=[]
  for key in ('shared','creator'):
   v=f[key];prefix=v['prefix'];bindings.append('{'+v['rva']+',{'+','.join('0x'+prefix[i:i+2]for i in range(0,32,2))+'}}')
  calls=[]
  for role in f['roles']:
   v=role['call_site'];prefix=v['prefix'];calls.append('{'+v['rva']+',{'+','.join('0x'+prefix[i:i+2]for i in range(0,32,2))+'}}')
  lines+=['inline constexpr FocusFactory '+p+'_focus_factory={'+','.join(bindings)+',{'+','.join(r['method_info_cell']for r in f['roles'])+'},{'+','.join(r['return_address']for r in f['roles'])+'},{'+','.join(calls)+'}};']
 lines+=['struct TypeName {const char* space;const char* leaf;};','struct TypeNames {']
 for name in TYPES:lines.append(' TypeName '+name+';')
 lines+=['};','inline constexpr TypeNames type_names={']
 for name in TYPES:
  values=[d['type_names'][name]for d in data.values()];need(all(v==values[0]for v in values),'camera_type_names_differ:'+name)
  lines.append(' {'+json.dumps(values[0]['space'])+','+json.dumps(values[0]['leaf'])+'}, // '+name)
 lines+=['};']
 lines+=['struct Types {']
 for name in TYPES:lines.append(' Binding '+name+';')
 lines+=['};']
 for p,d in data.items():
  lines+=['inline constexpr Types '+p+'_types={']
  for name in TYPES:
   r=d['types'][name];prefix=r['prefix'];lines.append(' {'+r['rva']+',{'+','.join('0x'+prefix[i:i+2]for i in range(0,32,2))+'}}, // '+name)
  lines+=['};']
 lines+=['struct NativeAudio {const char*sha256;uint32_t cached_ptr,paused_offset,fast_flag,primary,supplementary_head,supplementary_tail,supplementary_count;Binding pause,unpause,playing;};']
 for p,d in data.items():
  r=d['native_audio'];parts=[]
  for name in('pause','unpause','playing'):
   v=r[name];prefix=v['prefix'];parts.append('{'+v['rva']+',{'+','.join('0x'+prefix[i:i+2]for i in range(0,32,2))+'}}')
  lines+=['inline constexpr NativeAudio '+p+'_native_audio={'+json.dumps(r['sha256'])+','+','.join(str(r[k])for k in('cached_ptr','paused_offset','fast_flag','primary','supplementary_head','supplementary_tail','supplementary_count'))+','+','.join(parts)+'};']
 lines+=['struct NativeCamera {const char*sha256;uint32_t cached_ptr,automatic_aspect_offset;Binding reset,set,projection,reset_store,set_store;};']
 for p,d in data.items():
  r=d['native_camera'];parts=[]
  for name in('reset','set','projection','reset_store','set_store'):
   v=r[name];prefix=v['prefix'];parts.append('{'+v['rva']+',{'+','.join('0x'+prefix[i:i+2]for i in range(0,32,2))+'}}')
  lines+=['inline constexpr NativeCamera '+p+'_native_camera={'+json.dumps(r['sha256'])+','+str(r['cached_ptr'])+','+str(r['automatic_aspect_offset'])+','+','.join(parts)+'};']
 field_map={'brain_frames':('Cinemachine.CinemachineBrain','mFrameStack'),'brain_next_id':('Cinemachine.CinemachineBrain','mNextFrameId'),'brain_current_blend':('Cinemachine.CinemachineBrain','mCurrentLiveCameras'),'brain_previous':('Cinemachine.CinemachineBrain','mActiveCameraPreviousFrame'),'brain_state':('Cinemachine.CinemachineBrain','<CurrentCameraState>k__BackingField'),'core_status':('Cinemachine.CinemachineCore','mUpdateStatus'),'core_fixed_frame':('Cinemachine.CinemachineCore','<FixedFrameCount>k__BackingField'),'mixer_brain':('.CinemachineMixer','mBrain'),'mixer_id':('.CinemachineMixer','mBrainOverrideId')}
 lines+=['struct Layout {']
 for name,(owner,field)in field_map.items():
  values=[d['fields'][owner][field]['offset']for d in data.values()];need(len(set(values))==1,'camera_state_shared_field_differs:'+name)
  lines.append(' static constexpr uint32_t '+name+'='+hex(values[0])+';')
 lines+=['};']
 lines+=['struct Schema {const char*name;const char*space;const char*leaf;uint32_t definition,begin,bytes;uintptr_t type_rva;uint8_t type_prefix[16];const uint32_t*refs;uint32_t references;int32_t identity,next_id,last_frame,window_frame;};']
 for p,d in data.items():
  rows=[]
  for i,r in enumerate(d['schemas']):
   if not r['supported']:continue
   refs=r['references'];symbol=p+'_refs_'+str(i)
   if refs:lines.append('inline constexpr uint32_t '+symbol+'[]={'+','.join(map(str,refs))+'};')
   semantic=[]
   for owners,field in((('Cinemachine.CinemachineBrain/BrainFrame',),'id'),(('Cinemachine.CinemachineBrain',),'mNextFrameId'),(('Cinemachine.CinemachineCore/UpdateStatus','Cinemachine.UpdateTracker/UpdateStatus'),'lastUpdateFrame'if r['name']!='Cinemachine.UpdateTracker/UpdateStatus'else'lastFrameUpdated'),(('Cinemachine.UpdateTracker/UpdateStatus',),'windowStart')):
    semantic.append(str(next((f['offset']-r['begin']for f in r['fields']if f['name']==field),-1))if r['name']in owners else'-1')
   prefix=r['runtime_type']['prefix'];rows.append(' {'+','.join(json.dumps(r[k])for k in('name','space','leaf'))+','+str(r['definition'])+','+str(r['begin'])+','+str(r['bytes'])+','+r['runtime_type']['rva']+',{'+','.join('0x'+prefix[k:k+2]for k in range(0,32,2))+'},'+(symbol if refs else'nullptr')+','+str(len(refs))+','+','.join(semantic)+'},')
  lines+=['inline constexpr Schema '+p+'_schemas[]={',*rows,'};']
 for p,d in data.items():
  rows=[]
  for i,r in enumerate(d['values']):
   refs=r['references'];symbol=p+'_value_refs_'+str(i)
   if refs:lines.append('inline constexpr uint32_t '+symbol+'[]={'+','.join(map(str,refs))+'};')
   prefix=r['runtime_type']['prefix'];rows.append(' {'+','.join(json.dumps(r[k])for k in('name','space','leaf'))+','+str(r['definition'])+',0,'+str(r['bytes'])+','+r['runtime_type']['rva']+',{'+','.join('0x'+prefix[k:k+2]for k in range(0,32,2))+'},'+(symbol if refs else'nullptr')+','+str(len(refs))+',-1,-1,-1,-1},')
  lines+=['inline constexpr Schema '+p+'_values[]={',*rows,'};']
 lines+=['} // namespace idoly_mp4_camera_profile',END]
 return '\n'.join(lines)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--originals',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--header',type=Path,default=ROOT/'client-presentation/native/mp4_camera_owner.hpp');a=p.parse_args();result={}
 for platform,ctor,m,n in [('android',OriginalAndroid,'android-metadata.dat','android-native.so'),('ios',Original,'ios-metadata.dat','ios-native.bin')]:
  original=ctor((a.originals/m).read_bytes(),(a.originals/n).read_bytes());result[platform]=build(original,platform)
  result[platform]['native_audio']=native_audio(original,platform,a.originals/('mp4-android-analysis/libunity.so'if platform=='android'else n))
  result[platform]['native_camera']=native_camera(original,platform,a.originals/('mp4-android-analysis/libunity.so'if platform=='android'else n))
 a.evidence.parent.mkdir(parents=True,exist_ok=True);a.evidence.write_text(json.dumps(result,indent=2)+'\n')
 text=a.header.read_text();section=render(result)
 if START in text:text=text[:text.index(START)]+section+text[text.index(END)+len(END):]
 else:text+='\n'+section+'\n'
 a.header.write_text(text);print(json.dumps({p:{'methods':len(r['methods']),'exports':len(r['exports']),'schemas':len(r['schemas']),'supported':sum(x['supported']for x in r['schemas'])}for p,r in result.items()}))
if __name__=='__main__':main()
