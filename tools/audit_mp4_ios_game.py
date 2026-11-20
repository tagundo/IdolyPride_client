#!/usr/bin/env python3
"""Reproduce typed offline-MV bindings from the pinned original iOS client.

Reads original metadata/native bytes only. Does not execute game code, contact
servers, edit accounts, or patch an IPA. Raw IL2CPP method/field tables and the
Mach-O codegen module registration establish each retained address and prefix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import struct
import zipfile

NATIVE_SHA256 = 'b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf'
METADATA_SHA256 = 'd11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda'
IPA_SHA256 = '33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848'
IPA_BYTES = 146438450
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT/'client-presentation/native/mp4_game_ios_profile.json'
# name, parameter count, optional exact managed parameter types.
SELECT = {
 'presenter_update': ('Solis.OutGame.LivePlayerScreenPresenter','Update',0),
 'director_get_asset': ('UnityEngine.Playables.PlayableDirector','get_playableAsset',0),
 'director_get_time': ('UnityEngine.Playables.PlayableDirector','get_time',0),
 'director_set_time': ('UnityEngine.Playables.PlayableDirector','set_time',1),
 'director_get_mode': ('UnityEngine.Playables.PlayableDirector','get_timeUpdateMode',0),
 'director_set_mode': ('UnityEngine.Playables.PlayableDirector','set_timeUpdateMode',1),
 'director_evaluate': ('UnityEngine.Playables.PlayableDirector','Evaluate',0),
 'director_get_duration': ('UnityEngine.Playables.PlayableDirector','get_duration',0),
 'director_get_binding': ('UnityEngine.Playables.PlayableDirector','GetGenericBinding',1),
 'brain_manual_update': ('Cinemachine.CinemachineBrain','ManualUpdate',0),
 'brain_effective_delta': ('Cinemachine.CinemachineBrain','GetEffectiveDeltaTime',1),
 'core_update_camera': ('Cinemachine.CinemachineCore','UpdateVirtualCamera',3),
 'brain_output_camera': ('Cinemachine.CinemachineBrain','get_OutputCamera',0),
 'graph_set_mode': ('UnityEngine.Playables.PlayableGraph','SetTimeUpdateMode',1),
 'graph_set_mode_injected': ('UnityEngine.Playables.PlayableGraph','SetTimeUpdateMode_Injected',2),
 'graph_valid': ('UnityEngine.Playables.PlayableGraph','IsValid',0),
 'player_set_time': ('Solis.Common.Live.SolisLivePlayerBase','set_TimelineTime',1),
 'director_graph_injected': ('UnityEngine.Playables.PlayableDirector','GetGraphHandle_Injected',1),
 'graph_evaluate_injected': ('UnityEngine.Playables.PlayableGraph','Evaluate_Injected',2),
 'animation_stream_delta': ('UnityEngine.Animations.AnimationStream','get_deltaTime',0),
 'actor_swing_process': ('ActorSwing.ActorSwingJob','ProcessAnimation',1),
 'timeline_get_tracks': ('UnityEngine.Timeline.TimelineAsset','GetOutputTracks',0),
 'track_get_clips': ('UnityEngine.Timeline.TrackAsset','GetClips',0),
 'object_get_name': ('UnityEngine.Object','get_name',0),
 'audio_clip_get_name': ('UnityEngine.AudioClip','GetName',0),
 'audio_clip_samples': ('UnityEngine.AudioClip','get_samples',0),
 'audio_clip_channels': ('UnityEngine.AudioClip','get_channels',0),
 'audio_clip_frequency': ('UnityEngine.AudioClip','get_frequency',0),
 'audio_clip_load_state': ('UnityEngine.AudioClip','get_loadState',0),
 'audio_clip_load_type': ('UnityEngine.AudioClip','get_loadType',0),
 'audio_clip_load_data': ('UnityEngine.AudioClip','LoadAudioData',0),
 'audio_clip_get_data': ('UnityEngine.AudioClip','GetData',2),
 'audio_source_get_volume': ('UnityEngine.AudioSource','get_volume',0),
 'audio_source_set_volume': ('UnityEngine.AudioSource','set_volume',1),
 'bundle_load_file_async': ('UnityEngine.AssetBundle','LoadFromFileAsync',1),
 'bundle_request_get_bundle': ('UnityEngine.AssetBundleCreateRequest','get_assetBundle',0),
 'async_done': ('UnityEngine.AsyncOperation','get_isDone',0),
 'bundle_load_asset': ('UnityEngine.AssetBundle','LoadAsset',2),
 'bundle_unload': ('UnityEngine.AssetBundle','Unload',1),
 'camera_capture_request': ('VL.Rendering.VLSRPCameraController','CaptureRequest',0),
 'camera_get_captured': ('VL.Rendering.VLSRPCameraController','get_capturedTexture',0),
 'camera_get_main': ('VL.Rendering.VLSRPCameraController','get_mainCamera',0),
 'capture_pass_execute': ('VL.Rendering.VLCapturePass','Execute',2),
 'end_camera_rendering': ('UnityEngine.Rendering.RenderPipelineManager','EndCameraRendering',2),
 'rt_active_get': ('UnityEngine.RenderTexture','get_active',0),
 'rt_active_set': ('UnityEngine.RenderTexture','set_active',1),
 'texture_width': ('UnityEngine.Texture','get_width',0),
 'texture_height': ('UnityEngine.Texture','get_height',0),
 'texture_graphics_format': ('UnityEngine.RenderTexture','get_graphicsFormat',0),
 'texture_srgb': ('UnityEngine.RenderTexture','get_sRGB',0),
 'texture2d_ctor_rgba': ('UnityEngine.Texture2D','.ctor',5,('System.Int32','System.Int32','UnityEngine.TextureFormat','System.Boolean','System.Boolean')),
 'texture2d_read_pixels_injected': ('UnityEngine.Texture2D','ReadPixelsImpl_Injected',4),
 'texture2d_raw_data': ('UnityEngine.Texture2D','GetRawTextureData',0),
 'object_destroy': ('UnityEngine.Object','Destroy',1),
 'shader_use_custom': ('VL.Rendering.VLShaderTimeManager','get_UseCustomTime',0),
 'shader_current_time': ('VL.Rendering.VLShaderTimeManager','get_CurrentTime',0),
 'shader_set_custom': ('VL.Rendering.VLShaderTimeManager','SetCustomTime',1),
 'shader_reset_custom': ('VL.Rendering.VLShaderTimeManager','ResetCustomTime',0),
 'camera_main': ('UnityEngine.Camera','get_main',0),
 'supports_async_readback': ('UnityEngine.SystemInfo','get_supportsAsyncGPUReadback',0),
 'readback_texture_injected': ('UnityEngine.Rendering.AsyncGPUReadback','Request_Internal_Texture_2_Injected',5),
 'readback_done': ('UnityEngine.Rendering.AsyncGPUReadbackRequest','get_done',0),
 'readback_error': ('UnityEngine.Rendering.AsyncGPUReadbackRequest','get_hasError',0),
 'readback_layer_count': ('UnityEngine.Rendering.AsyncGPUReadbackRequest','get_layerCount',0),
 'readback_layer_size': ('UnityEngine.Rendering.AsyncGPUReadbackRequest','get_layerDataSize',0),
 'readback_raw': ('UnityEngine.Rendering.AsyncGPUReadbackRequest','GetDataRaw',1),
 'time_delta': ('UnityEngine.Time','get_deltaTime',0),
 'time_unscaled_delta': ('UnityEngine.Time','get_unscaledDeltaTime',0),
 'time_fixed_delta': ('UnityEngine.Time','get_fixedDeltaTime',0),
 'time_scale_get': ('UnityEngine.Time','get_timeScale',0),
 'time_scale_set': ('UnityEngine.Time','set_timeScale',1),
 'swing_update_instance': ('ActorSwing.ActorSwingManager','UpdateInstance',0),
}
FIELD_SELECT = {
 'presenter_player': ('Solis.OutGame.LivePlayerScreenPresenter','_player'),
 'player_director_controller': ('Solis.Common.Live.SolisLivePlayerBase','_timelineController'),
 'brain_update_mode': ('Cinemachine.CinemachineBrain','m_UpdateMethod'),
 'brain_blend_update_mode': ('Cinemachine.CinemachineBrain','m_BlendUpdateMethod'),
 'status_last_frame': ('Cinemachine.CinemachineCore/UpdateStatus','lastUpdateFrame'),
 'status_last_fixed_frame': ('Cinemachine.CinemachineCore/UpdateStatus','lastUpdateFixedFrame'),
 'status_last_mode': ('Cinemachine.CinemachineCore/UpdateStatus','lastUpdateMode'),
 'core_update_filter': ('Cinemachine.CinemachineCore','<CurrentUpdateFilter>k__BackingField'),
 'core_update_status': ('Cinemachine.CinemachineCore','mUpdateStatus'),
 'binder_actors': ('Solis.Common.Live.SolisLiveBinder','<Actors>k__BackingField'),
 'actor_animation_player': ('VL.Core.VLActorController','_animationPlayer'),
 'animation_player_graph': ('VL.VLAnimationClipPlayerBase','_graph'),
 'player_binder': ('Solis.Common.Live.SolisLivePlayerBase','_binder'),
 'player_duration': ('Solis.Common.Live.SolisLivePlayerBase','<Duration>k__BackingField'),
 'player_bgm_source': ('Solis.Common.Live.SolisLivePlayerBase','_bgmSource'),
 'player_voice_source': ('Solis.Common.Live.SolisLivePlayerBase','_voiceSource'),
 'controller_master': ('VL.Timeline.VLTimelineController','_master'),
 'camera_main': ('VL.Rendering.VLSRPCameraController','_mainCamera'),
 'camera_captured': ('VL.Rendering.VLSRPCameraController','<capturedTexture>k__BackingField'),
 'wrapper_texture': ('VL.VLRenderTexture','texture'),
 'wrapper_identifier': ('VL.VLRenderTexture','id'),
 'pass_identifier': ('VL.Rendering.VLCapturePass','_target'),
 'track_muted': ('UnityEngine.Timeline.TrackAsset','m_Muted'),
 'audio_track_properties': ('UnityEngine.Timeline.AudioTrack','m_TrackProperties'),
 'clip_start': ('UnityEngine.Timeline.TimelineClip','m_Start'),
 'clip_in': ('UnityEngine.Timeline.TimelineClip','m_ClipIn'),
 'clip_asset': ('UnityEngine.Timeline.TimelineClip','m_Asset'),
 'clip_duration': ('UnityEngine.Timeline.TimelineClip','m_Duration'),
 'clip_scale': ('UnityEngine.Timeline.TimelineClip','m_TimeScale'),
 'clip_ease_in': ('UnityEngine.Timeline.TimelineClip','m_EaseInDuration'),
 'clip_ease_out': ('UnityEngine.Timeline.TimelineClip','m_EaseOutDuration'),
 'clip_blend_in': ('UnityEngine.Timeline.TimelineClip','m_BlendInDuration'),
 'clip_blend_out': ('UnityEngine.Timeline.TimelineClip','m_BlendOutDuration'),
 'audio_asset_clip': ('UnityEngine.Timeline.AudioPlayableAsset','m_Clip'),
 'audio_asset_loop': ('UnityEngine.Timeline.AudioPlayableAsset','m_Loop'),
 'audio_asset_properties': ('UnityEngine.Timeline.AudioPlayableAsset','m_ClipProperties'),
 'properties_gain': ('UnityEngine.Timeline.AudioClipProperties','volume'),
 'mixer_pan': ('UnityEngine.Timeline.AudioMixerProperties','stereoPan'),
 'mixer_spatial': ('UnityEngine.Timeline.AudioMixerProperties','spatialBlend'),
}
EXPORT_ABI = {
 'il2cpp_array_new':'void*(void*,uintptr_t)',
 'il2cpp_get_corlib':'const void*()',
 'il2cpp_class_get_type':'const void*(void*)',
 'il2cpp_type_get_object':'void*(const void*)',
 'il2cpp_class_from_name':'void*(const void*,const char*,const char*)',
 'il2cpp_gchandle_new':'uint32_t(void*,bool)',
 'il2cpp_gchandle_get_target':'void*(uint32_t)',
 'il2cpp_gchandle_free':'void(uint32_t)',
 'il2cpp_string_new':'void*(const char*)',
 'il2cpp_object_get_class':'void*(void*)',
 'il2cpp_class_get_name':'const char*(void*)',
 'il2cpp_class_get_namespace':'const char*(void*)',
 'il2cpp_class_get_parent':'void*(void*)',
 'il2cpp_object_new':'void*(void*)',
}


def need(value, code):
    if not value:
        raise ValueError(code)


class Original:
    def __init__(self, metadata, native):
        need(type(metadata) is bytes and type(native) is bytes,'original_bytes_required')
        need(hashlib.sha256(metadata).hexdigest()==METADATA_SHA256,'metadata_sha256_differs')
        need(hashlib.sha256(native).hexdigest()==NATIVE_SHA256,'native_sha256_differs')
        self.m,self.b=metadata,native;self.h=struct.unpack_from('<64I',metadata)
        need(self.h[:2]==(0xFAB11BAF,31),'metadata_version_differs')
        self.segments=[];self.constant_segment=None;self.symtab=None;self.exports=None
        count=struct.unpack_from('<I',native,16)[0];cursor=32
        for _ in range(count):
            command,size=struct.unpack_from('<II',native,cursor)
            if command==0x19:
                name,address,_,offset,span=struct.unpack_from('<16s4Q',native,cursor+8)
                self.segments.append((address,address+span,offset))
                if name.rstrip(b'\0')==b'__DATA_CONST':self.constant_segment=(offset,span)
            if command==2:self.symtab=struct.unpack_from('<4I',native,cursor+8)
            if command in (0x22,0x80000022):self.exports=struct.unpack_from('<2I',native,cursor+40)
            if command==0x80000033:self.exports=struct.unpack_from('<2I',native,cursor+8)
            cursor+=size
        self.types={};self.type_ids={}
        for i in range(self.h[41]//88):
            row=struct.unpack_from('<16I8H2I',metadata,self.h[40]+i*88)
            name=self.string(row[1]);name=(name+'.' if name else '.')+self.string(row[0])
            self.types[i]=(name,row);self.type_ids.setdefault(name,[]).append(i)
        reg=struct.unpack_from('<16Q',native,self.offset(0x9C1DEB8))
        need(reg[6]==116926 and reg[10]==len(self.types),'registration_counts_differ')
        self.type_count,self.type_table,self.field_table,self.size_table=reg[6],reg[7],reg[11],reg[13]
        self.modules={};self.images=[]
        for pos in range(self.h[42],self.h[42]+self.h[43],40):
            row=struct.unpack_from('<10i',metadata,pos)
            self.images.append((self.string(row[0]),row[2],row[2]+row[3]))
        self._decoded={}

    def offset(self,address):
        for start,end,offset in self.segments:
            if start<=address<end:return offset+address-start
        raise ValueError('native_address_unmapped')

    def qword(self,address):return struct.unpack_from('<Q',self.b,self.offset(address))[0]
    def string(self,index):
        start=self.h[6]+index;end=self.m.index(0,start,self.h[6]+self.h[7]);return self.m[start:end].decode()
    def type_name(self,index):
        need(0<=index<self.type_count,'type_index_bound')
        return self.decode(self.qword(self.type_table+index*8))
    def decode(self,pointer,depth=0):
        need(depth<12,'type_depth_bound')
        if pointer in self._decoded:return self._decoded[pointer]
        data,bits=struct.unpack_from('<QI',self.b,self.offset(pointer));code=(bits>>16)&255
        primitive={1:'System.Void',2:'System.Boolean',3:'System.Char',4:'System.SByte',5:'System.Byte',6:'System.Int16',7:'System.UInt16',8:'System.Int32',9:'System.UInt32',10:'System.Int64',11:'System.UInt64',12:'System.Single',13:'System.Double',14:'System.String',24:'System.IntPtr',25:'System.UIntPtr',28:'System.Object'}
        if code in (17,18):name=self.types[data][0]
        elif code==21:
            base,inst=struct.unpack_from('<QQ',self.b,self.offset(data));count=struct.unpack_from('<I',self.b,self.offset(inst))[0]
            need(count<=32,'generic_argument_bound');args=self.qword(inst+8)
            name=self.decode(base,depth+1)+'<'+','.join(self.decode(self.qword(args+i*8),depth+1) for i in range(count))+'>'
        elif code in (15,29):name=self.decode(data,depth+1)+('*' if code==15 else '[]')
        elif code==20:name=self.decode(self.qword(data),depth+1)+'[array]'
        else:name=primitive.get(code,'generic-parameter:'+str(data))
        if bits&(1<<29):name+='&'
        self._decoded[pointer]=name;return name

    def type_id(self,name):
        if '/' in name:
            owner,nested=name.rsplit('/',1)
            found=[i for i,(full,row) in self.types.items() if self.string(row[0])==nested and row[3]<self.type_count and self.type_name(row[3])==owner]
        else:found=self.type_ids.get(name,[])
        need(len(found)==1,'type_identity_ambiguous:'+name);return found[0]
    def module(self,name):
        if name in self.modules:return self.modules[name]
        encoded=name.encode()+b'\0';wanted=set();start=0
        while True:
            pos=self.b.find(encoded,start)
            if pos<0:break
            start=pos+1
            for va,end,off in self.segments:
                if off<=pos<off+end-va:wanted.add(va+pos-off)
        candidates=set();off,span=self.constant_segment
        for pointer in wanted:
            at=off
            while True:
                at=self.b.find(struct.pack('<Q',pointer),at,off+span)
                if at<0:break
                if at%8==0:
                    _,count,table=struct.unpack_from('<3Q',self.b,at)
                    if 0<count<1000000:
                        try:self.offset(table);self.offset(table+(count-1)*8);candidates.add((count,table))
                        except ValueError:pass
                at+=1
        need(len(candidates)==1,'codegen_module_ambiguous:'+name)
        self.modules[name]=next(iter(candidates));return self.modules[name]

    def fields(self,type_name):
        index=self.type_id(type_name);row=self.types[index][1];pointer=self.qword(self.field_table+index*8);result={}
        for i,fid in enumerate(range(row[8],row[8]+row[18])):
            name,kind,token=struct.unpack_from('<3I',self.m,self.h[24]+fid*12)
            offset=struct.unpack_from('<i',self.b,self.offset(pointer)+i*4)[0] if pointer else None
            result[self.string(name)]={'offset':offset,'type':self.type_name(kind),'metadata_field_index':fid}
        return result

    def native_type(self,name):
        scalar={'System.Void':'void','System.Boolean':'bool','System.Int32':'int32_t',
            'System.UInt32':'uint32_t','System.Int64':'int64_t','System.UInt64':'uint64_t',
            'System.Single':'float','System.Double':'double','System.IntPtr':'void*'}
        if name in scalar:return scalar[name]
        aggregate={'UnityEngine.Rendering.ScriptableRenderContext':'ScriptableRenderContext8',
            # AAPCS64 lowers this 56-byte, non-HFA by-value aggregate to a pointer.
            'UnityEngine.Animations.AnimationStream':'void*'}
        if name in aggregate:return aggregate[name]
        if name.endswith('&') or name.endswith('*') or name.endswith('[]') or '<' in name:return 'void*'
        if name in self.type_ids:
            fields=self.fields(name)
            if 'value__' in fields:return self.native_type(fields['value__']['type'])
        return 'void*'

    def enum_value(self,type_name,field_name):
        row=self.fields(type_name)[field_name];fid=row['metadata_field_index']
        need(self.fields(type_name)['value__']['type']=='System.Int32','enum_underlying_type_differs')
        for pos in range(self.h[16],self.h[16]+self.h[17],12):
            field,kind,index=struct.unpack_from('<3I',self.m,pos)
            if field!=fid:continue
            need(self.type_name(kind)=='System.Int32','enum_default_type_differs')
            encoded=self.m[self.h[18]+index]
            # Selected non-negative values fit the one-byte signed-compressed form.
            need(encoded<128 and encoded%2==0,'enum_default_encoding_differs')
            return encoded//2,{'type':type_name,'name':field_name,'metadata_field_index':fid,
                'default_data_index':index,'signed_compressed_byte':encoded,'underlying':'System.Int32'}
        raise ValueError('enum_default_missing')

    def struct_layout(self,name):
        tid=self.type_id(name);size_pointer=self.qword(self.size_table+tid*8)
        instance,native,_,_=struct.unpack_from('<4I',self.b,self.offset(size_pointer))
        need(instance>=16 and native==instance-16,'struct_native_size_differs:'+name)
        return {'bytes':native,'fields':{key:value['offset']-16 for key,value in self.fields(name).items()
            if value['offset']>=16},'metadata_type_definition_index':tid,
            'size_table_instance_bytes':instance,'size_table_native_bytes':native}

    def export_bindings(self):
        found={};symoff,count,strings,string_bytes=self.symtab
        for i in range(count):
            index,kind,_,_,address=struct.unpack_from('<IBBHQ',self.b,symoff+i*16)
            if not(kind&1 and kind&0xe==0xe and index<string_bytes):continue
            start=strings+index;end=self.b.find(b'\0',start,min(strings+string_bytes,start+256))
            raw=self.b[start:end]
            for name in EXPORT_ABI:
                if raw==('_'+name).encode():need(name not in found,'duplicate_export');found[name]=address
        offset,size=self.exports;trie=self.b[offset:offset+size]
        def uleb(pos):
            value=0
            for i in range(10):
                byte=trie[pos];pos+=1;value|=(byte&127)<<(7*i)
                if not byte&128:return value,pos
            raise ValueError('export_uleb_bound')
        def lookup(name,node=0,prefix=b'',depth=0):
            need(depth<128 and node<len(trie),'export_trie_bound')
            length,pos=uleb(node);terminal=pos;pos+=length
            if prefix==name and length:
                flags,end=uleb(terminal);need(not flags&0x18,'export_not_local')
                address,_=uleb(end);return address
            children=trie[pos];pos+=1
            for _ in range(children):
                end=trie.index(0,pos);edge=trie[pos:end];pos=end+1;child,pos=uleb(pos)
                if name.startswith(prefix+edge):
                    result=lookup(name,child,prefix+edge,depth+1)
                    if result is not None:return result
            return None
        result={}
        for name,abi in EXPORT_ABI.items():
            need(name in found,'export_missing:'+name);address=found[name]
            need(lookup(('_'+name).encode())==address,'export_trie_symtab_disagree')
            off=self.offset(address);result[name]={'rva':hex(address),'prefix':self.b[off:off+16].hex(),
                'native_abi':abi,'export_trie_and_symtab_agree':True,'has_method_info_argument':False}
        return result

    def method(self,owner,name,count,signature=None):
        tid=self.type_id(owner);row=self.types[tid][1];found=[]
        for mid in range(row[9],row[9]+row[16]):
            method=struct.unpack_from('<7I4H',self.m,self.h[12]+mid*36)
            if self.string(method[0])!=name or method[10]!=count:continue
            args=[]
            for pi in range(method[4],method[4]+count):
                param=struct.unpack_from('<3I',self.m,self.h[22]+pi*12)
                args.append({'name':self.string(param[0]),'type':self.type_name(param[2]),'metadata_type_index':param[2]})
            if signature is not None and tuple(p['type'] for p in args)!=signature:continue
            module=next(module for module,first,last in self.images if first<=tid<last)
            n,table=self.module(module);token=method[6]&0xFFFFFF;need(0<token<=n,'method_token_bound')
            address=self.qword(table+(token-1)*8)
            if not address:continue  # Open generic declarations have no concrete codegen slot.
            found.append({'type':owner,'name':name,'parameter_count':count,'static':bool(method[7]&16),
                'rva':hex(address),'prefix':self.b[self.offset(address):self.offset(address)+16].hex(),
                'return':self.type_name(method[2]),'parameters':args,'metadata_method_index':mid,
                'token_row':token,'module':module,'registration_pointer_slot':hex(table+(token-1)*8)})
        need(len(found)==1,'method_identity_ambiguous:'+owner+'.'+name);return found[0]


def build_profile(metadata:bytes,native:bytes)->dict:
    original=Original(metadata,native)
    methods={alias:original.method(*select) for alias,select in SELECT.items()}
    for method in methods.values():
        args=[] if method['static'] else ['void*']
        args.extend(original.native_type(arg['type']) for arg in method['parameters'])
        method['native_abi']=original.native_type(method['return'])+'('+','.join([*args,'const MethodInfo*'])+')'
    methods['actor_swing_process']['aggregate_abi']={
        'parameter':'stream','managed_value_type':'UnityEngine.Animations.AnimationStream',
        'native_bytes':56,'aapcs64_lowering':'indirect pointer in x1',
        'original_entry_receiver':'unboxed ActorSwingJob pointer in x0'}
    fields={}
    field_proof={}
    for alias,(owner,name) in FIELD_SELECT.items():
        available=original.fields(owner)
        need(name in available,'field_identity_missing:'+owner+'.'+name)
        found=available[name];need(type(found['offset']) is int and found['offset']>=0,'field_offset_invalid')
        fields[alias]=found['offset'];field_proof[alias]={'type':owner,'name':name,**found}
    render=original.fields('UnityEngine.Rendering.Universal.RenderingData')
    camera=original.fields('UnityEngine.Rendering.Universal.CameraData')
    fields['rendering_camera']=render['cameraData']['offset']-16+camera['camera']['offset']-16
    fields['rendering_final_target']=render['cameraData']['offset']-16+camera['resolveFinalTarget']['offset']-16
    enum_select={
        'director_manual':('UnityEngine.Playables.DirectorUpdateMode','Manual'),
        'director_dsp_clock':('UnityEngine.Playables.DirectorUpdateMode','DSPClock'),
        'texture_rgba32':('UnityEngine.TextureFormat','RGBA32'),
        'audio_loaded':('UnityEngine.AudioDataLoadState','Loaded'),
        'audio_decompress_on_load':('UnityEngine.AudioClipLoadType','DecompressOnLoad'),
        'audio_streaming':('UnityEngine.AudioClipLoadType','Streaming'),
        'rgba8_srgb':('UnityEngine.Experimental.Rendering.GraphicsFormat','R8G8B8A8_SRGB'),
    }
    enum_rows={name:original.enum_value(*select) for name,select in enum_select.items()}
    structs={name.rsplit('.',1)[-1]:original.struct_layout(name) for name in (
        'UnityEngine.Rect','UnityEngine.Rendering.AsyncGPUReadbackRequest',
        'UnityEngine.Rendering.RenderTargetIdentifier','UnityEngine.Rendering.ScriptableRenderContext',
        'UnityEngine.Playables.PlayableGraph','UnityEngine.Animations.AnimationStream',
        'ActorSwing.ActorSwingJob')}
    runtime_types={}
    for name in ('System.Single','UnityEngine.AudioClip','UnityEngine.Texture2D'):
        tid=original.type_id(name);type_index=original.types[tid][1][2]
        pointer=original.qword(original.type_table+type_index*8)
        need(original.type_name(type_index)==name,'runtime_type_identity_differs')
        off=original.offset(pointer);kind=(struct.unpack_from('<I',native,off+8)[0]>>16)&255
        need(kind==(12 if name=='System.Single' else 18),'runtime_type_kind_differs')
        runtime_types[name]={'type':name,'kind':kind,'kind_name':'IL2CPP_TYPE_R4' if kind==12 else 'IL2CPP_TYPE_CLASS',
            'rva':hex(pointer),'prefix':native[off:off+16].hex(),'metadata_type_index':type_index,
            'metadata_type_definition_index':tid,'type_table_pointer_slot':hex(original.type_table+type_index*8)}
    return {'schema':1,'platform':'ios','sources':{'metadata_sha256':METADATA_SHA256,'native_sha256':NATIVE_SHA256},
        'methods':methods,'exports':original.export_bindings(),'runtime_types':runtime_types,'type_namespaces':{alias:original.string(original.types[original.type_id(name)][1][1]) for alias,name in (('.CinemachineTrack','.CinemachineTrack'),('.UpdateStatus','Cinemachine.CinemachineCore/UpdateStatus'))},'generic_calls':{'camera_status_try_get':{'rva':'0x3ecb690','prefix':native[original.offset(0x3ecb690):original.offset(0x3ecb690)+16].hex(),'native_abi':'bool(void*,void*,void**,const MethodInfo*)','caller':'Cinemachine.CinemachineCore.UpdateVirtualCamera','runtime_method_slot':'0xa40d2c0','scope':'Original typed private dictionary call; runtime MethodInfo must still match pinned methodPointer'}},'fields':fields,'field_proof':field_proof,
        'enums':{name:row[0] for name,row in enum_rows.items()},
        'enum_proof':{name:row[1] for name,row in enum_rows.items()},'structs':structs,
        'scope':{'static_original_binding_proof':True,'game_executed':False,'runtime_verified':False,'offline_audio_decoder_runtime_verified':False}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--ipa',type=Path,required=True);parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT);args=parser.parse_args(argv)
    soft,hard=resource.getrlimit(resource.RLIMIT_AS);resource.setrlimit(resource.RLIMIT_AS,(min(soft,3*1024**3) if soft>=0 else 3*1024**3,hard))
    with args.ipa.open('rb') as stream:
        need(args.ipa.stat().st_size==IPA_BYTES and hashlib.file_digest(stream,'sha256').hexdigest()==IPA_SHA256,'ipa_pin_differs');stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            metadata=archive.read('Payload/IDOLY PRIDE.app/Data/Managed/Metadata/global-metadata.dat')
            native=archive.read('Payload/IDOLY PRIDE.app/Frameworks/UnityFramework.framework/UnityFramework')
    profile=build_profile(metadata,native);args.output.write_text(json.dumps(profile,indent=2)+'\n')
    print(json.dumps({'status':'PASS_STATIC_ORIGINAL_BINDINGS','methods':len(profile['methods']),'fields':len(profile['fields']),'output_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__=='__main__':main()
