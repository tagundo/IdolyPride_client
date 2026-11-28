#!/usr/bin/env python3
"""Recover stage effect bindings from both pinned original clients.

Generated C++ evidence is embedded in the single stage header. JSON receipts
are optional external evidence, not omitted compiler inputs.
"""
import argparse, hashlib, json, struct
from pathlib import Path
from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original, need
from audit_mp4_actor_state import runtime_type
ROOT=Path(__file__).resolve().parents[1]
SELECT={
 'psyllium_execute':('Solis.Live.Psyllium.RenderPsyllium','Execute',2),
 'psyllium_setup':('Solis.Live.Psyllium.RenderPsyllium','Setup',1),
 'psyllium_compute_execute':('Solis.Live.Psyllium.ComputePsyllium','Execute',2),
 'psyllium_color_array':('Solis.Live.Psyllium.PsylliumController','get_PsyliumColors',0),
 'psyllium_apply':('Solis.Live.Equipment.Environment.LivePsyllium','OnApply',1),
 'active_psyllium':('Solis.Live.Psyllium.PsylliumController','get_ActiveInstance',0),
 'property_get_float':('UnityEngine.MaterialPropertyBlock','GetFloat',1),
 'property_set_float':('UnityEngine.MaterialPropertyBlock','SetFloat',2),
 'shader_property_id':('UnityEngine.Shader','PropertyToID',1),
 'particle_playback_get':('UnityEngine.ParticleSystem','GetPlaybackState_Injected',1),
 'particle_playback_set':('UnityEngine.ParticleSystem','SetPlaybackState_Injected',1),
 'particle_data_get':('UnityEngine.ParticleSystem','GetParticlesWithNativeArray',4),
 'particle_data_set':('UnityEngine.ParticleSystem','SetParticlesWithNativeArray',4),
 'particle_count':('UnityEngine.ParticleSystem','get_particleCount',0),
 'particle_paused':('UnityEngine.ParticleSystem','get_isPaused',0),
 'particle_playing':('UnityEngine.ParticleSystem','get_isPlaying',0),
 'particle_stopped':('UnityEngine.ParticleSystem','get_isStopped',0),
 'particle_emitting':('UnityEngine.ParticleSystem','get_isEmitting',0),
 'particle_seed_get':('UnityEngine.ParticleSystem','get_randomSeed',0),
 'particle_seed_set':('UnityEngine.ParticleSystem','set_randomSeed',1),
 'particle_auto_seed_get':('UnityEngine.ParticleSystem','get_useAutoRandomSeed',0),
 'particle_auto_seed_set':('UnityEngine.ParticleSystem','set_useAutoRandomSeed',1),
 'particle_trails_allocate':('UnityEngine.ParticleSystem/Trails','Allocate',0),
 'particle_trails_get':('UnityEngine.ParticleSystem','GetTrails',1),
 'particle_trails_set':('UnityEngine.ParticleSystem','SetTrails_Injected',1),
 'particle_custom_get':('UnityEngine.ParticleSystem','GetCustomParticleData',2),
 'particle_custom_set':('UnityEngine.ParticleSystem','SetCustomParticleData',2),
 'particle_pause':('UnityEngine.ParticleSystem','Pause',1),
 'particle_stop':('UnityEngine.ParticleSystem','Stop',2),
 'particle_simulate':('UnityEngine.ParticleSystem','Simulate',4),
 'control_particle_simulate':('UnityEngine.Timeline.ParticleControlPlayable','Simulate',2,('System.Single','System.Boolean')),
 'live_particle_simulate':('Solis.Live.Equipment.Environment.LiveParticleEffect','SimulateParticle',2),
 'live_particle_apply':('Solis.Live.Equipment.Environment.LiveParticleEffect','OnApply',1),
 'component_gameobject':('UnityEngine.Component','get_gameObject',0),
 'components_internal':('UnityEngine.GameObject','GetComponentsInternal',6),
 'active_hierarchy':('UnityEngine.GameObject','get_activeInHierarchy',0),
 'playable_script':('UnityEngine.Playables.PlayableHandle','GetScriptInstance_Injected',1),
 'equipment_late_update':('Solis.Live.Equipment.LiveEquipmentController','LateUpdate',0),
 'equipment_initialize_arrays':('Solis.Live.Equipment.LiveEquipmentController','InitializeArray',0),
 'equipment_update':('Solis.Live.Equipment.LiveEquipmentController','Update',0),
 'equipment_receiver_apply':('Solis.Live.Equipment.LiveEquipmentReceiver','UpdateEquipment',1),
 'equipment_initial_store':('Solis.Live.Equipment.LiveEquipmentReceiver','StoreInitialData',1),
 'equipment_graph_valid':('Solis.Live.Equipment.LiveEquipmentController','get_IsValidPlayableGraph',0),
 'equipment_job_complete':('Unity.Jobs.JobHandle','Complete',0),
 'equipment_directional_apply':('Solis.Live.Equipment.Environment.LiveDirectionalLight','OnApply',1),
 'equipment_light_apply':('Solis.Live.Equipment.Environment.LiveLightComponent','OnApply',1),
 'equipment_beam_apply':('Solis.Live.Equipment.Environment.LiveLightBasic','OnApply',1),
 'equipment_laser_apply':('Solis.Live.Equipment.Environment.LiveLaser','OnApply',1),
 'equipment_laser_dependency':('Solis.Live.Equipment.Environment.LiveLaser','AddDependencyJob',2),
 'equipment_psyllium_apply':('Solis.Live.Equipment.Environment.LivePsyllium','OnApply',1),
 'equipment_particle_apply':('Solis.Live.Equipment.Environment.LiveParticleEffect','OnApply',1),
 'equipment_laser_mesh_update':('Solis.Live.Equipment.Environment.LiveLaser','UpdateMesh',0),
 'equipment_material_hash':('Solis.Live.Equipment.LiveEquipmentReceiver','GetMaterialInfoHash',2),
 'equipment_material_get':('Solis.Live.Equipment.LiveEquipmentReceiver','GetMaterialInfo',2),
 'equipment_transform':('UnityEngine.Component','get_transform',0),
 'equipment_rotation_get':('UnityEngine.Transform','get_localRotation_Injected',1),
 'equipment_rotation_set':('UnityEngine.Transform','set_localRotation_Injected',1),
 'equipment_scale_get':('UnityEngine.Transform','get_localScale_Injected',1),
 'equipment_scale_set':('UnityEngine.Transform','set_localScale_Injected',1),
 'equipment_light_color_get':('UnityEngine.Light','get_color_Injected',1),
 'equipment_light_color_set':('UnityEngine.Light','set_color_Injected',1),
 'equipment_light_intensity_get':('UnityEngine.Light','get_intensity',0),
 'equipment_light_intensity_set':('UnityEngine.Light','set_intensity',1),
 'equipment_renderer_enabled_get':('UnityEngine.Renderer','get_enabled',0),
 'equipment_renderer_enabled_set':('UnityEngine.Renderer','set_enabled',1),
 'equipment_mesh_submesh_get':('UnityEngine.Mesh','GetSubMesh',1),
 'equipment_mesh_submesh_set':('UnityEngine.Mesh','SetSubMesh',3),
 'equipment_mesh_submesh_count':('UnityEngine.Mesh','get_subMeshCount',0),
 'vlb_batch_draw':('VLB.VLBBatchSRP','UpdateAndDrawMeshInstanced',3,('UnityEngine.Rendering.CommandBuffer','UnityEngine.Rendering.Universal.CameraData&','UnityEngine.Material')),
 'vlb_camera_draw':('VLB.VLBBatchSRPCameraData','UpdateAndDrawMeshInstanced',4),
 'vlb_camera_ctor':('VLB.VLBBatchSRPCameraData','.ctor',1),
 'vlb_compute_upload':('UnityEngine.ComputeBuffer','InternalSetNativeData',5),
 'vlb_compute_readback':('UnityEngine.ComputeBuffer','InternalGetData',5),
 'vlb_block_clear':('UnityEngine.MaterialPropertyBlock','Clear',0),
 'vlb_config_get':('VLB.Config','GetInstance',1),
 'vlb_compute_count':('UnityEngine.ComputeBuffer','get_count',0),
 'vlb_compute_stride':('UnityEngine.ComputeBuffer','get_stride',0),
 'vlb_object_id':('UnityEngine.Object','GetInstanceID',0),
 'vlb_beam_update':('VLB.VolumetricLightBeam','UpdateAfterManualPropertyChange',0),
}
FIELDS={
 'player_environment':('Solis.Common.Live.SolisLivePlayerBase','_environment',0x40),
 'environment_receiver':('Solis.Common.Live.SolisLiveEnvironment','_equipmentReceiver',0x20),
 'receiver_equipments':('Solis.Live.Equipment.LiveEquipmentReceiver','_equipments',0x20),
 'equipment_psyllium':('Solis.Live.Equipment.Environment.LivePsyllium','_psylliumController',0x30),
 'psyllium_time':('Solis.Live.Psyllium.PsylliumController','time',0x28),
 'psyllium_speed':('Solis.Live.Psyllium.PsylliumController','speed',0x2c),
 'psyllium_detail':('Solis.Live.Psyllium.PsylliumController','drawDetailRange',0x30),
 'psyllium_filling':('Solis.Live.Psyllium.PsylliumController','fillingRate',0x34),
 'psyllium_animation':('Solis.Live.Psyllium.PsylliumController','animationIndex',0x38),
 'psyllium_multiply_color':('Solis.Live.Psyllium.PsylliumController','multiplyColor',0x3c),
 'psyllium_packed_color':('Solis.Live.Psyllium.PsylliumController','_psylliumPackedColor',0x58),
 'psyllium_color_changed':('Solis.Live.Psyllium.PsylliumController','_psylliumColorChanged',0x5c),
 'psyllium_color_array_field':('Solis.Live.Psyllium.PsylliumController','_psylliumColors',0x98),
 'psyllium_audience':('Solis.Live.Psyllium.PsylliumController','_audience',0x20),
 'psyllium_preset':('Solis.Live.Psyllium.PsylliumController','_colorPreset',0x50),
 'psyllium_indirect':('Solis.Live.Psyllium.PsylliumController','_psylliumIndirect',0x60),
 'psyllium_info_buffer':('Solis.Live.Psyllium.PsylliumController','_audienceInfoBuffer',0x68),
 'psyllium_audience_buffer':('Solis.Live.Psyllium.PsylliumController','_audienceBuffer',0x70),
 'psyllium_culling_buffer':('Solis.Live.Psyllium.PsylliumController','_cullingAppendBuffer',0x78),
 'psyllium_body_buffer':('Solis.Live.Psyllium.PsylliumController','_cullingBodyAppendBuffer',0x80),
 'psyllium_indirect_buffer':('Solis.Live.Psyllium.PsylliumController','_psylliumIndirectBuffer',0x88),
 'psyllium_sphere_buffer':('Solis.Live.Psyllium.PsylliumController','_boundingSphereBuffer',0x90),
 'compute_buffer_native':('UnityEngine.ComputeBuffer','m_Ptr',0x10),
 'property_block_native':('UnityEngine.MaterialPropertyBlock','m_Ptr',0x10),
 'pass_controller':('Solis.Live.Psyllium.RenderPsyllium','_psylliumController',0x88),
 'pass_properties':('Solis.Live.Psyllium.RenderPsyllium','_psylliumMaterialPropertyBlock',0x98),
 'live_particle_system':('Solis.Live.Equipment.Environment.LiveParticleEffect','_particle',0x30),
 'live_particle_last_time':('Solis.Live.Equipment.Environment.LiveParticleEffect','m_LastTime',0x40),
 'live_particle_system_time':('Solis.Live.Equipment.Environment.LiveParticleEffect','m_SystemTime',0x44),
 'control_particle':('UnityEngine.Timeline.ParticleControlPlayable','<particleSystem>k__BackingField',0x20),
 'control_last_playable_time':('UnityEngine.Timeline.ParticleControlPlayable','m_LastPlayableTime',0x10),
 'control_last_particle_time':('UnityEngine.Timeline.ParticleControlPlayable','m_LastParticleTime',0x14),
 'control_random_seed':('UnityEngine.Timeline.ParticleControlPlayable','m_RandomSeed',0x18),
 'control_asset_prefab':('UnityEngine.Timeline.ControlPlayableAsset','prefabGameObject',0x28),
 'control_asset_seed':('UnityEngine.Timeline.ControlPlayableAsset','particleRandomSeed',0x34),
 'control_asset_particles':('UnityEngine.Timeline.ControlPlayableAsset','updateParticle',0x30),
 'control_source_reference':('UnityEngine.Timeline.ControlPlayableAsset','sourceGameObject',0x18),
 'timeline_tracks':('UnityEngine.Timeline.TimelineAsset','m_Tracks',0x20),
 'track_children':('UnityEngine.Timeline.TrackAsset','m_Children',0x48),
 'track_clips':('UnityEngine.Timeline.TrackAsset','m_Clips',0x80),
 'clip_asset':('UnityEngine.Timeline.TimelineClip','m_Asset',0x28),
 'equipment_controller_receiver':('Solis.Live.Equipment.LiveEquipmentController','_receiver',0x20),
 'equipment_controller_director':('Solis.Live.Equipment.LiveEquipmentController','_director',0x28),
 'equipment_controller_stream':('Solis.Live.Equipment.LiveEquipmentController','<StreamData>k__BackingField',0x30),
 'equipment_controller_initial':('Solis.Live.Equipment.LiveEquipmentController','<InitialData>k__BackingField',0x40),
 'equipment_controller_animation':('Solis.Live.Equipment.LiveEquipmentController','<AnimationData>k__BackingField',0x50),
 'equipment_controller_timeline':('Solis.Live.Equipment.LiveEquipmentController','<TimelineData>k__BackingField',0x60),
 'equipment_controller_initialized':('Solis.Live.Equipment.LiveEquipmentController','_initialized',0x70),
 'equipment_receiver_initialized':('Solis.Live.Equipment.LiveEquipmentReceiver','_initialized',0x40),
 'equipment_receiver_stream':('Solis.Live.Equipment.LiveEquipmentReceiver','<StreamData>k__BackingField',0x48),
 'equipment_receiver_modifiable':('Solis.Live.Equipment.LiveEquipmentReceiver','_isModifiable',0x58),
 'equipment_receiver_received':('Solis.Live.Equipment.LiveEquipmentReceiver','_receivedFrame',0x59),
 'equipment_laser_handle':('Solis.Live.Equipment.Environment.LiveLaser','_handle',0xa8),
 'equipment_laser_vertices':('Solis.Live.Equipment.Environment.LiveLaser','_vertexData',0x88),
 'equipment_laser_indices':('Solis.Live.Equipment.Environment.LiveLaser','_indexData',0x98),
 'equipment_base_receiver':('Solis.Live.Equipment.EnvironmentBase','_receiver',0x28),
 'equipment_base_id':('Solis.Live.Equipment.EnvironmentBase','id',0x20),
 'equipment_directional_light':('Solis.Live.Equipment.Environment.LiveDirectionalLight','_light',0x30),
 'equipment_component_light':('Solis.Live.Equipment.Environment.LiveLightComponent','_light',0x30),
 'equipment_laser_renderer':('Solis.Live.Equipment.Environment.LiveLaser','_renderer',0x30),
 'equipment_laser_horizontal':('Solis.Live.Equipment.Environment.LiveLaser','horizontal',0x38),
 'equipment_laser_vertical':('Solis.Live.Equipment.Environment.LiveLaser','vertical',0x40),
 'equipment_laser_type':('Solis.Live.Equipment.Environment.LiveLaser','laserType',0x48),
 'equipment_laser_random_speed':('Solis.Live.Equipment.Environment.LiveLaser','randomSpeed',0x74),
 'equipment_laser_mesh':('Solis.Live.Equipment.Environment.LiveLaser','_mesh',0x78),
 'equipment_beam_horizontal':('Solis.Live.Equipment.Environment.LiveLightBasic','horizontal',0x30),
 'equipment_beam_vertical':('Solis.Live.Equipment.Environment.LiveLightBasic','vertical',0x38),
 'equipment_beam_volume':('Solis.Live.Equipment.Environment.LiveLightBasic','beam',0x40),
 'equipment_beam_flares':('Solis.Live.Equipment.Environment.LiveLightBasic','flares',0x48),
 'equipment_beam_renderer':('Solis.Live.Equipment.Environment.LiveLightBasic','renderer',0x50),
 'vlb_beam_noise_mode':('VLB.VolumetricLightBeam','noiseMode',0xa8),
 'vlb_beam_noise_intensity':('VLB.VolumetricLightBeam','noiseIntensity',0xac),
 'vlb_beam_noise_scale_global':('VLB.VolumetricLightBeam','noiseScaleUseGlobal',0xb0),
 'vlb_beam_noise_velocity_global':('VLB.VolumetricLightBeam','noiseVelocityUseGlobal',0xb8),
 'vlb_config_scale':('VLB.Config','globalNoiseScale',0x40),
 'vlb_config_velocity':('VLB.Config','globalNoiseVelocity',0x44),
 'vlb_config_instance':('VLB.Config','ms_Instance',0),
 'vlb_beam_color':('VLB.VolumetricLightBeam','color',0x28),
 'vlb_beam_spot':('VLB.VolumetricLightBeam','spotAngle',0x54),
 'vlb_beam_falloff':('VLB.VolumetricLightBeam','fallOffEnd',0x90),
 'vlb_beam_fresnel':('VLB.VolumetricLightBeam','fresnelPow',0xa4),
 'vlb_beam_occlusion':('VLB.VolumetricLightBeam','m_INTERNAL_DynamicOcclusionMode',0xd4),
 'vlb_beam_occlusion_runtime':('VLB.VolumetricLightBeam','m_INTERNAL_DynamicOcclusionMode_Runtime',0xd8),
 'vlb_beam_callback':('VLB.VolumetricLightBeam','onWillCameraRenderThisBeam',0xe0),
 'vlb_beam_initialized_callback':('VLB.VolumetricLightBeam','m_OnBeamGeometryInitialized',0xe8),
 'vlb_beam_geometry':('VLB.VolumetricLightBeam','m_BeamGeom',0x110),
 'vlb_beam_coroutine':('VLB.VolumetricLightBeam','m_CoPlaytimeUpdate',0x118),
 'vlb_beam_cached_light':('VLB.VolumetricLightBeam','_CachedLight',0x120),
 'vlb_beam_batch':('VLB.VolumetricLightBeam','_batchSRP',0x128),
 'vlb_batch_list':('VLB.VLBBatchSRP','vlbList',0x20),
 'vlb_batch_empty_queue':('VLB.VLBBatchSRP','_vlbEmptyQueue',0x28),
 'vlb_batch_ids':('VLB.VLBBatchSRP','_vlbInstanceIDTable',0x30),
 'vlb_batch_cameras':('VLB.VLBBatchSRP','_cameraDatas',0x38),
 'vlb_batch_access':('VLB.VLBBatchSRP','_transformAccessArray',0x40),
 'vlb_geometry_master':('VLB.VLBBatchSRPGeometry','master',0x10),
 'vlb_geometry_static':('VLB.VLBBatchSRPGeometry','staticProps',0x18),
 'vlb_geometry_material_id':('VLB.VLBBatchSRPGeometry','materialID',0x34),
 'vlb_camera_property_bytes':('VLB.VLBBatchSRPCameraData','_propertyByteSize',0x10),
 'vlb_camera_array':('VLB.VLBBatchSRPCameraData','_bufferArray',0x18),
 'vlb_camera_buffer':('VLB.VLBBatchSRPCameraData','_buffer',0x28),
 'vlb_camera_camera':('VLB.VLBBatchSRPCameraData','_camera',0x30),
 'vlb_camera_id':('VLB.VLBBatchSRPCameraData','_instanceID',0x38),
 'vlb_camera_properties':('VLB.VLBBatchSRPCameraData','_properties',0x40),
 'vlb_camera_block':('VLB.VLBBatchSRPCameraData','_materialPropertyBlock',0x48),
 'vlb_draw_material':('VLB.VLBBatchSRPDrawData','_material',0x10),
 'vlb_draw_indices':('VLB.VLBBatchSRPDrawData','_vlbIndexList',0x18),
 'vlb_render_camera':('UnityEngine.Rendering.Universal.CameraData','camera',0x90),
}
MARK_BEGIN='// BEGIN_ORIGINAL_STAGE_PROFILE'
MARK_END='// END_ORIGINAL_STAGE_PROFILE'
def pointer_free_value(o,name,definition=None):
 """Walk actual TypeDefinition IDs, including ambiguous nested type names.

 A size alone cannot establish that copying a native playback image is safe.
 Reject every managed reference, pointer, native-int and recursive value shape.
 """
 records={};active=set()
 def visit(tid):
  need(tid not in active,'stage_recursive_value_type')
  if tid in records:return
  active.add(tid);full,row=o.types[tid];size_pointer=o.qword(o.size_table+tid*8)
  instance,native,_,_=struct.unpack_from('<4I',o.b,o.offset(size_pointer))
  need(instance>=16 and native==instance-16,'stage_value_native_size_differs:'+full)
  field_pointer=o.qword(o.field_table+tid*8);fields=[]
  for i,fid in enumerate(range(row[8],row[8]+row[18])):
   ni,ti,_=struct.unpack_from('<3I',o.m,o.h[24]+fid*12);ptr=o.qword(o.type_table+ti*8)
   data=o.qword(ptr);bits=struct.unpack_from('<I',o.b,o.offset(ptr)+8)[0];code=(bits>>16)&255
   if bits&16:continue
   offset=struct.unpack_from('<i',o.b,o.offset(field_pointer)+i*4)[0]-16
   need(0<=offset<native,'stage_value_field_offset_differs:'+full)
   need(not bits&(1<<29) and (code in range(2,14) or code==17),'stage_value_contains_pointer_or_reference:'+full+'.'+o.string(ni))
   fields.append({'name':o.string(ni),'metadata_field_index':fid,'metadata_type_index':ti,'kind':code,'offset':offset,'nested_definition':data if code==17 else None})
   if code==17:
    visit(data);field_bytes=records[data]['bytes']
   else:field_bytes={2:1,3:2,4:1,5:1,6:2,7:2,8:4,9:4,10:8,11:8,12:4,13:8}[code]
   need(offset+field_bytes<=native,'stage_value_field_exceeds_layout:'+full)
  active.remove(tid);records[tid]={'type':full,'metadata_type_definition_index':tid,'bytes':native,'fields':fields}
 root=o.type_id(name)if definition is None else definition
 visit(root)
 return {'root_definition':root,'contains_pointers_or_managed_references':False,'definitions':list(records.values())}
def producer_proof(o,platform):
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
 cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);answer={}
 for key,args in {
  'live_simulate':('Solis.Live.Equipment.Environment.LiveParticleEffect','SimulateParticle',2),
  'live_apply':('Solis.Live.Equipment.Environment.LiveParticleEffect','OnApply',1),
  'control_simulate':('UnityEngine.Timeline.ParticleControlPlayable','Simulate',2),
  'control_asset_seed_initialize':('UnityEngine.Timeline.ControlPlayableAsset','OnEnable',0),
 }.items():
  m=o.method(*args);a=int(m['rva'],0);rows=[]
  for i in cs.disasm(o.b[o.offset(a):o.offset(a)+1536],a):
   rows.append(i)
   if i.mnemonic=='ret':break
  need(rows[-1].mnemonic=='ret','stage_producer_boundary_differs:'+key)
  answer[key]={'method':m,'bytes':b''.join(i.bytes for i in rows).hex(),'instructions':[i.mnemonic+' '+i.op_str for i in rows]}
 ops=answer['live_simulate']['instructions']
 need('fmov s2, #-1.00000000'in ops or 'fmov s0, #-1.00000000'in ops,'stage_live_unset_branch_missing')
 need(any(op.startswith('stp s8, s0, [x19, #0x40]')or op.startswith('stp s8, s0, [x20, #0x40]')for op in ops),'stage_live_cache_commit_differs')
 fid=o.fields('Solis.Live.Equipment.Environment.LiveParticleEffect')['kUnsetTime']['metadata_field_index'];sentinel=None
 for pos in range(o.h[16],o.h[16]+o.h[17],12):
  field,kind,index=struct.unpack_from('<3I',o.m,pos)
  if field==fid:
   need(o.type_name(kind)=='System.Single','stage_live_unset_type_differs')
   sentinel=struct.unpack_from('<f',o.m,o.h[18]+index)[0]
 need(sentinel==-1,'stage_live_unset_value_differs')
 answer['live_unset_time']={'value':sentinel,'metadata_field_index':fid,'scope':'Forces the original SimulateParticle reset branch before the original zero-time evaluation; not a claimed constructor default.'}
 # The retained reference-generic producer resolves the name at value+0 and
 # falls back to the default object at value+8. Open generic method metadata
 # does not provide a concrete codegen slot; prove the original actual call.
 callsite,a=(0x8eef960,0x66ae9e0)if platform=='android'else(0x778fea8,0x439b824)
 word=struct.unpack_from('<I',o.b,o.offset(callsite))[0];delta=word&0x3ffffff
 if delta&(1<<25):delta-=1<<26
 need(word>>26==0b100101 and callsite+4*delta==a,'stage_control_reference_call_differs')
 rows=[]
 for i in cs.disasm(o.b[o.offset(a):o.offset(a)+1024],a):
  rows.append(i)
  if i.mnemonic=='ret':break
 ops=[i.mnemonic+' '+i.op_str for i in rows]
 need(any(op.startswith('ldr w')and op.endswith(('[x20]','[x19]'))for op in ops),'stage_control_reference_name_differs')
 need(any(op.startswith('ldr x')and op.endswith(('[x20, #8]','[x19, #8]'))for op in ops),'stage_control_reference_default_differs')
 answer['control_source_resolve']={'rva':hex(a),'prefix':b''.join(i.bytes for i in rows[:4]).hex(),'bytes':b''.join(i.bytes for i in rows).hex(),'instructions':ops,'name_offset':0,'default_offset':8}
 execute=o.method('Solis.Live.Psyllium.ComputePsyllium','Execute',2);a=int(execute['rva'],0)
 raw=o.b[o.offset(a):o.offset(a)+4096];rows=[]
 for i in cs.disasm(raw,a):
  rows.append(i)
  if i.mnemonic=='ret':break
 counter=int(o.method('UnityEngine.Rendering.CommandBuffer','SetBufferCounterValue',2)['rva'],0)
 dispatch=int(o.method('UnityEngine.Rendering.CommandBuffer','DispatchCompute',5)['rva'],0)
 calls=[(i.address,int(i.op_str[1:],0))for i in rows if i.mnemonic=='bl']
 resets=[at for at,target in calls if target==counter];dispatches=[at for at,target in calls if target==dispatch]
 need(len(resets)==2 and dispatches and max(resets)<min(dispatches),'stage_psyllium_culling_reset_order_differs')
 for at in resets:
  prior=[i.mnemonic+' '+i.op_str for i in rows if at-20<=i.address<at]
  need('mov w2, wzr'in prior or 'mov w2, #0'in prior,'stage_psyllium_counter_not_zero')
 answer['psyllium_culling_scratch']={'method':execute,'bytes':b''.join(i.bytes for i in rows).hex(),'counter_reset_calls':[hex(x)for x in resets],'first_dispatch':hex(min(dispatches)),'contract':'Both source append counters are reset to zero before the original camera-dependent dispatch and indirect-count copy on every Execute. These are per-pass culling scratch, not simulation history.'}
 return answer
def draw_copy_proof(engine,image,platform):
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
 offset=image.file_offset if platform=='android'else image.offset
 cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
 locations={'android':(0x5fac70,0x5fa7e8,0x684b18,[0x684bb4,0x684c14,0x684c74]),'ios':(0xc8417c,0xc83c5c,0xd0ff44,[0xc0d8f0,0xc73e20,0xd17a38])}[platform]
 result={}
 for name,address in [('draw',locations[0]),('capture',locations[1]),('clone',locations[2]),*[(f'array{i}',a)for i,a in enumerate(locations[3])]]:
  rows=[]
  for ins in cs.disasm(engine[offset(address):offset(address)+1024],address):
   rows.append(ins)
   if ins.mnemonic=='ret' or (name.startswith('array') and platform=='android' and ins.mnemonic=='b' and ins.op_str=='#0x140a9b0'):break
  need(rows and (rows[-1].mnemonic=='ret' or (name.startswith('array')and platform=='android'and rows[-1].op_str=='#0x140a9b0')),'stage_draw_copy_boundary_differs:'+name)
  ops=[i.mnemonic+' '+i.op_str for i in rows]
  if name=='draw':need(any(i.mnemonic=='bl'and i.op_str==hex(locations[1]).replace('0x','#0x')for i in rows),'stage_draw_property_capture_missing')
  if name=='capture':
   need('mov w0, #0x100'in ops,'stage_draw_property_allocation_differs')
   need(any(op.startswith('str x20, [x8, x21, lsl #3]')for op in ops),'stage_draw_property_owned_slot_missing')
  if name.startswith('array'):
   need('str xzr, [x0]'in ops,'stage_property_clone_not_empty_destination')
   need(any(op in ('ldr x20, [x1]','ldr x21, [x1]')for op in ops),'stage_property_clone_source_missing')
   need(any(op.startswith('lsl x2, x21, #')or op in ('mov x2, x20','mov x2, x21')for op in ops),'stage_property_clone_copy_size_missing')
   need(any(op in ('mov x1, x20','mov x1, x21')for op in ops),'stage_property_clone_copy_source_missing')
   need(sum(i.mnemonic=='bl'for i in rows)==(1 if platform=='android'else 2),'stage_property_clone_call_shape_differs')
  if name=='clone':
   calls={int(i.op_str[1:],0)for i in rows if i.mnemonic=='bl'}
   need(set(locations[3])<=calls,'stage_property_array_clone_missing')
   need(any(op.startswith(('ldrb w8, [x19, #0xf8]','ldrb w8, [x20, #0xf8]'))for op in ops),'stage_property_inline_copy_incomplete')
  raw=b''.join(i.bytes for i in rows);result[name]={'rva':hex(address),'prefix':raw[:16].hex(),'bytes':raw.hex(),'instructions':[i.mnemonic+' '+i.op_str for i in rows]}
 return {'methods':result,'contract':'Native DrawMeshInstancedIndirect captures a newly allocated 0x100-byte property sheet in the command buffer, deep-copies its three data vectors, and copies remaining inline payload by value before returning; later source MPB float mutation cannot alter captured scalar/vector storage.'}

def profile(o,platform,engine):
 methods={key:o.method(*args) for key,args in SELECT.items()}
 # This original receiver fast path calls a closed int/reference generic body.
 # Runtime additionally validates its actual closed MethodInfo methodPointer.
 call,target=((0x88191f4,0x71a291c) if platform=='android' else (0x6f6b310,0x51d4c34))
 word=struct.unpack_from('<I',o.b,o.offset(call))[0]
 displacement=word&0x3ffffff
 if displacement&(1<<25):displacement-=1<<26
 need(word>>26==0b100101 and call+displacement*4==target,'stage_material_try_call_differs')
 method=methods['equipment_material_get'];need(int(method['rva'],16)<=call<int(method['rva'],16)+2048,'stage_material_try_caller_differs')
 material_try={'rva':hex(target),'prefix':o.b[o.offset(target):o.offset(target)+16].hex(),'caller':hex(call),'caller_instruction':word,'abi':'bool(void* closedSerializedDictionary,int32_t key,void** value,Method* exactClosedMethod)','runtime_requirement':'Selected receiver table; exact closed TryGetValue MethodInfo methodPointer, source hash route, returned exact MaterialInfo/renderer/index.'}
 for method in methods.values():
  args=[]if method['static']else['void*'];args.extend(o.native_type(p['type'])for p in method['parameters'])
  method['native_abi']=o.native_type(method['return'])+'('+','.join([*args,'const MethodInfo*'])+')'
 fields={}
 for key,(owner,name,offset)in FIELDS.items():
  f=o.fields(owner)[name];need(f['offset']==offset,'stage_field_differs:'+key);fields[key]={'owner':owner,'name':name,**f}
 color=o.struct_layout('UnityEngine.Color');need(color['bytes']==16 and sorted(color['fields'].values())==[0,4,8,12],'stage_psyllium_color_layout_differs')
 for key,kind in [('psyllium_time','System.Single'),('psyllium_speed','System.Single'),('psyllium_detail','System.Single'),('psyllium_filling','System.Single'),('psyllium_animation','System.Int32'),('psyllium_multiply_color','UnityEngine.Color')]:
  need(fields[key]['type']==kind,'stage_psyllium_scalar_type_differs:'+key)
 playback=o.struct_layout('UnityEngine.ParticleSystem/PlaybackState');particle=o.struct_layout('UnityEngine.ParticleSystem/Particle')
 need(playback['bytes']==352 and particle['bytes']==132,'stage_particle_layout_differs')
 equipment_layouts={key:o.struct_layout(name)for key,name in (
  ('stream','Solis.Live.Equipment.LiveEquipmentStreamData'),('initial','Solis.Live.Equipment.LiveEquipmentInitialData'),
  ('animation','Solis.Live.Equipment.LiveEquipmentAnimationData'),('timeline','Solis.Live.Equipment.LiveEquipmentTimelineData'),
  ('vertex','.VertexLayout'),('submesh','UnityEngine.Rendering.SubMeshDescriptor'),('vlb_property','VLB.VLBProperty'))}
 need({key:value['bytes']for key,value in equipment_layouts.items()}=={'stream':116,'initial':64,'animation':96,'timeline':4,'vertex':44,'submesh':48,'vlb_property':256},'stage_equipment_value_layout_differs')
 need(o.enum_value('Unity.Collections.Allocator','Persistent')[0]==4,'stage_equipment_allocator_differs')
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
 initializer=methods['equipment_initialize_arrays'];start=int(initializer['rva'],16);module_count,module_table=o.module(initializer['module'])
 end=min(value for value in (o.qword(module_table+i*8)for i in range(module_count))if value>start)
 initialization=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(o.b[o.offset(start):o.offset(start)+end-start],start))
 operations=[i.mnemonic+' '+i.op_str for i in initialization]
 need(operations.count('mov w1, #0x100')==3 and operations.count('mov w1, #1')==1 and operations.count('mov w2, #4')==4,'stage_equipment_array_constructor_shape_differs')
 equipment_initialization={'method':initializer,'body_end':hex(end),'counts':{'stream':256,'initial':256,'animation':256,'timeline':1},'allocator':4,'instructions':operations}
 beam_spans=[]
 need(o.enum_value('VLB.ColorMode','Flat')[0]==0,'stage_vlb_flat_color_mode_differs')
 need(o.enum_value('UnityEngine.ComputeBufferType','Structured')[0]==16,'stage_vlb_structured_buffer_mode_differs')
 need(o.enum_value('Unity.Collections.NativeArrayOptions','ClearMemory')[0]==1,'stage_vlb_array_clear_mode_differs')
 ctor=methods['vlb_camera_ctor'];start=int(ctor['rva'],16);n,table=o.module(ctor['module']);end=min(value for value in (o.qword(table+i*8)for i in range(n))if value>start)
 ctor_body=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(o.b[o.offset(start):o.offset(start)+end-start],start));ctor_ops=[i.mnemonic+' '+i.op_str for i in ctor_body]
 need(ctor_ops.count('mov w1, #0x100')==2 and 'mov w2, #4'in ctor_ops and 'mov w3, #1'in ctor_ops and 'mov w3, #0x10'in ctor_ops,'stage_vlb_constructor_initialization_differs')
 vlb_initialization={'method':ctor,'instructions':ctor_ops,'property_count':256,'property_bytes':256,'clear_memory_enum':1,'structured_buffer_enum':16,'initial_gpu_upload':'Original constructor uploads the clear NativeArray to the entire ComputeBuffer before creating432 sparse DrawData slots and an empty MaterialPropertyBlock.'}
 cfg=methods['vlb_config_get'];start=int(cfg['rva'],16);n,table=o.module(cfg['module']);end=min(value for value in (o.qword(table+i*8)for i in range(n))if value>start)
 cfg_body=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(o.b[o.offset(start):o.offset(start)+end-start],start));cfg_ops=[i.mnemonic+' '+i.op_str for i in cfg_body]
 need(cfg_ops.count('ldr x8, [x8, #0xb8]')>=3 and 'ldr x0, [x8]'in cfg_ops,'stage_vlb_config_static_slot_differs')
 f=fields['vlb_config_instance'];_,ti,_=struct.unpack_from('<3I',o.m,o.h[24]+f['metadata_field_index']*12);ptr=o.qword(o.type_table+ti*8);bits=struct.unpack_from('<I',o.b,o.offset(ptr)+8)[0]
 need(bits&16 and f['type']=='VLB.Config','stage_vlb_config_instance_not_static')
 vlb_config={'method':cfg,'instructions':cfg_ops,'class_static_fields_offset':184,'static_instance_offset':0,'scale_offset':64,'velocity_offset':68,'readonly_route':'Resolve exact VLB.Config class; read its already published static-field block and ms_Instance directly. Never call the lazy GetInstance(Resources.Load) branch. Retain exact live source singleton; compare native identity and used finite scale/velocity values without writing config.'}
 geometry_static=o.fields('VLB.VLBBatchSRPGeometry')['staticProps'];_,ti,_=struct.unpack_from('<3I',o.m,o.h[24]+geometry_static['metadata_field_index']*12)
 pointer=o.qword(o.type_table+ti*8);definition=o.qword(pointer)
 vlb_static=pointer_free_value(o,geometry_static['type'],definition)
 root=next(r for r in vlb_static['definitions']if r['metadata_type_definition_index']==definition)
 need(root['bytes']==28,'stage_vlb_static_properties_size_differs')
 for name,row in o.fields('VLB.VolumetricLightBeam').items():
  _,ti,_=struct.unpack_from('<3I',o.m,o.h[24]+row['metadata_field_index']*12);pointer=o.qword(o.type_table+ti*8)
  data=o.qword(pointer);bits=struct.unpack_from('<I',o.b,o.offset(pointer)+8)[0];kind=(bits>>16)&255
  if bits&16:continue
  if kind in (18,20,21,28,29):size=8;identity=True
  elif kind in range(2,14):size={2:1,3:2,4:1,5:1,6:2,7:2,8:4,9:4,10:8,11:8,12:4,13:8}[kind];identity=False
  elif kind==17:
   size_pointer=o.qword(o.size_table+data*8);instance,native,_,_=struct.unpack_from('<4I',o.b,o.offset(size_pointer));need(native==instance-16 and native<=64,'stage_beam_value_shape_differs:'+name);size=native;identity=False
   pointer_free_value(o,row['type'],data)
  else:need(False,'stage_beam_field_kind_unsupported:'+name)
  need(row['offset']>=32 and row['offset']+size<=304,'stage_beam_field_bounds_differs:'+name)
  beam_spans.append({'name':name,'offset':row['offset'],'bytes':size,'identity':identity,'kind':kind,'metadata_field_index':row['metadata_field_index'],'metadata_type_index':ti})
 trail=o.fields('UnityEngine.ParticleSystem/Trails')
 need([trail[n]['offset']for n in ('positions','frontPositions','backPositions','positionCounts','textureOffsets','maxTrailCount','maxPositionsPerTrailCount')]==[16,24,32,40,48,56,60],'stage_trail_layout_differs')
 context=o.struct_layout('UnityEngine.Rendering.ScriptableRenderContext');need(context['bytes']==8,'stage_render_context_differs')
 controls=o.fields('UnityEngine.Timeline.ParticleControlPlayable')
 need(o.enum_value('UnityEngine.ParticleSystemStopBehavior','StopEmitting')[0]==1,'stage_particle_stop_enum_differs')
 # The original native getter completes the real pending handle at native+70,
 # then advances deferred work only for nonzero render delta. Held-clock callers
 # prove a pure job completion/readback boundary before particle state copies.
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
 from extract_client_schema import ClientImage
 image=ClientImage(o.m,engine)if platform=='android'else o
 offset=image.file_offset if platform=='android'else image.offset
 a=0xe23d84 if platform=='android'else 0x1367d48
 raw=engine[offset(a):offset(a)+124];ins=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(raw,a))
 ops=[i.mnemonic+' '+i.op_str for i in ins]
 need(any('#0x6c]'in p and p.startswith('ldrb')for p in ops),'stage_particle_pending_flag_differs')
 need(any('#0x70]!'in p for p in ops),'stage_particle_actual_handle_address_differs')
 need(any('#0xac'in p for p in ops)and any('#0xa8'in p for p in ops),'stage_particle_delta_fields_differ')
 need('fcmp s0, #0.0'in ops,'stage_particle_held_guard_differs')
 callsite=0x4f0460 if platform=='android'else 0xb7baec
 word=struct.unpack_from('<I',engine,offset(callsite))[0];delta=word&0x3ffffff
 if delta&(1<<25):delta-=1<<26
 need(word>>26==0b100101 and callsite+delta*4==a,'stage_particle_fence_call_differs')
 return {'schema':1,'platform':platform,'sources':{'native_sha256':hashlib.sha256(o.b).hexdigest(),'metadata_sha256':hashlib.sha256(o.m).hexdigest(),'engine_sha256':hashlib.sha256(engine).hexdigest()},'methods':methods,'material_try':material_try,'fields':fields,'vlb_static_properties':vlb_static,'vlb_initialization':vlb_initialization,'vlb_config':vlb_config,'beam_spans':beam_spans,'equipment_initialization':equipment_initialization,'equipment_layouts':equipment_layouts,'layouts':{'playback':playback,'particle':particle,'trail_bytes':48,'trail_fields':trail,'context':context},'pointer_free_values':{name:pointer_free_value(o,name)for name in ('UnityEngine.ParticleSystem/PlaybackState','UnityEngine.ParticleSystem/Particle','UnityEngine.Color','Solis.Live.Equipment.LiveEquipmentStreamData','Solis.Live.Equipment.LiveEquipmentInitialData','Solis.Live.Equipment.LiveEquipmentAnimationData','Solis.Live.Equipment.LiveEquipmentTimelineData','.VertexLayout','UnityEngine.Rendering.SubMeshDescriptor','VLB.VLBProperty')},'producer_control':producer_proof(o,platform),'particle_control_fields':controls,'runtime_types':{n:runtime_type(o,n,17 if n.endswith('/Trails') or n=='VLB.VLBProperty' else 18)for n in ('UnityEngine.ParticleSystem','UnityEngine.Transform','UnityEngine.ParticleSystem/Trails','Solis.Live.Equipment.LiveEquipmentController','VLB.VLBProperty','VLB.Config')},'draw_property_copy':draw_copy_proof(engine,image,platform),'particle_fence':{'rva':hex(a),'prefix':raw[:16].hex(),'bytes':raw.hex(),'actual_handle_offset':0x70,'requires_held_render_delta':[0xa8,0xac]},'scope':'Original binding/readback evidence only; runtime ownership and supported particle-control admission remain mandatory.'}
def render(profiles):
 lines=[MARK_BEGIN,'// Generated by tools/audit_mp4_stage_state.py from both unchanged originals.','struct Binding {uintptr_t rva;uint8_t prefix[16];};','struct FieldSpan {uint16_t offset,bytes;bool identity;};','struct TypeBinding {uintptr_t rva;uint8_t prefix[16];uint32_t metadata_definition,metadata_type;};','struct Profile {const char* native_sha256;const char* metadata_sha256;const char* engine_sha256;']
 for key in SELECT:lines.append('    Binding '+key+';')
 lines+=['    Binding equipment_material_try_get;','    Binding control_source_resolve;','    Binding particle_fence;','    Binding draw_copy[6];','    TypeBinding particle_type,transform_type,trails_type,equipment_controller_type,vlb_property_type,vlb_config_type;','};']
 fields=profiles['android']['fields'];need({k:v['offset']for k,v in fields.items()}=={k:v['offset']for k,v in profiles['ios']['fields'].items()},'stage_shared_layout_differs')
 lines+=['struct Layout {']
 for key,row in fields.items():lines.append('    static constexpr size_t '+key+'='+hex(row['offset'])+';')
 for key,value in profiles['android']['equipment_layouts'].items():
  need(value['bytes']==profiles['ios']['equipment_layouts'][key]['bytes'],'stage_equipment_shared_size_differs:'+key)
  lines.append('    static constexpr size_t equipment_'+key+'_stride='+str(value['bytes'])+';')
 for key,value in profiles['android']['equipment_initialization']['counts'].items():
  need(value==profiles['ios']['equipment_initialization']['counts'][key],'stage_equipment_array_count_differs')
  lines.append('    static constexpr size_t equipment_'+key+'_count='+str(value)+';')
 lines.append('    static constexpr int32_t equipment_allocator=4;')
 lines.append('    static constexpr size_t equipment_laser_cpu_bytes=48;')
 lines.append('    static constexpr size_t vlb_config_static_fields=184;')
 scalar_bytes=fields['psyllium_multiply_color']['offset']+16-fields['psyllium_time']['offset'];need(scalar_bytes==36,'stage_psyllium_scalar_image_differs')
 lines+=['    static constexpr size_t psyllium_scalar_bytes='+str(scalar_bytes)+';', '    static constexpr size_t control_source_name=0,control_source_default=8;','    static constexpr float live_unset_time=-1.0f;','};']
 beam=[(r['offset'],r['bytes'],r['identity'])for r in profiles['android']['beam_spans']]
 need(beam==[(r['offset'],r['bytes'],r['identity'])for r in profiles['ios']['beam_spans']],'stage_beam_shared_fields_differ')
 lines+=['inline constexpr FieldSpan beam_spans[]={']
 for offset,span,identity in beam:lines.append('    {'+str(offset)+','+str(span)+','+('true'if identity else'false')+'},')
 lines+=['};']
 for platform,p in profiles.items():
  lines += ['inline constexpr Profile '+platform+'_profile={','    "'+p['sources']['native_sha256']+'","'+p['sources']['metadata_sha256']+'","'+p['sources']['engine_sha256']+'",']
  for key in SELECT:
   m=p['methods'][key];lines.append('    {'+m['rva']+',{'+','.join('0x'+m['prefix'][i:i+2]for i in range(0,32,2))+'}}, // '+key)
  b=p['material_try'];lines+=['    {'+b['rva']+',{'+','.join('0x'+b['prefix'][i:i+2]for i in range(0,32,2))+'}},']
  b=p['producer_control']['control_source_resolve'];lines+=['    {'+b['rva']+',{'+','.join('0x'+b['prefix'][i:i+2]for i in range(0,32,2))+'}},']
  f=p['particle_fence'];lines+=['    {'+f['rva']+',{'+','.join('0x'+f['prefix'][i:i+2]for i in range(0,32,2))+'}},']
  lines+=['    {']
  for name in ('draw','capture','clone','array0','array1','array2'):
   b=p['draw_property_copy']['methods'][name];lines+=['        {'+b['rva']+',{'+','.join('0x'+b['prefix'][i:i+2]for i in range(0,32,2))+'}},']
  lines+=['    },']
  for name in ('UnityEngine.ParticleSystem','UnityEngine.Transform','UnityEngine.ParticleSystem/Trails','Solis.Live.Equipment.LiveEquipmentController','VLB.VLBProperty','VLB.Config'):
   t=p['runtime_types'][name];lines.append('    {'+t['rva']+',{'+','.join('0x'+t['prefix'][i:i+2]for i in range(0,32,2))+'},'+str(t['metadata_type_definition_index'])+','+str(t['metadata_type_index'])+'},')
  lines+=['};']
 return '\n'.join([*lines,MARK_END])
def main():
 p=argparse.ArgumentParser();p.add_argument('--originals',type=Path,required=True);p.add_argument('--header',type=Path,default=ROOT/'client-presentation/native/mp4_stage_state.hpp');p.add_argument('--report',type=Path);a=p.parse_args();profiles={}
 for name,C,meta,native in [('android',OriginalAndroid,'android-metadata.dat','android-native.so'),('ios',Original,'ios-metadata.dat','ios-native.bin')]:
  o=C((a.originals/meta).read_bytes(),(a.originals/native).read_bytes());engine=(a.originals/'mp4-android-analysis/libunity.so').read_bytes()if name=='android'else o.b;profiles[name]=profile(o,name,engine)
 text=a.header.read_text();start=text.index(MARK_BEGIN);end=text.index(MARK_END,start)+len(MARK_END);a.header.write_text(text[:start]+render(profiles)+text[end:])
 if a.report:a.report.write_text(json.dumps({'schema':1,'platforms':profiles},indent=2)+'\n')
 print(json.dumps({'status':'PINNED_STAGE_BINDINGS_ONLY','header':str(a.header),'methods_per_platform':len(SELECT)}))
if __name__=='__main__':main()
