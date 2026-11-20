#!/usr/bin/env python3
"""Recover the offline MV adapter's typed Android bindings from original bytes.

The exact original metadata/native SHA pins, real codegen registrations, method
signatures and field tables are checked. This does not run or modify the game.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import resource
import struct
from audit_mp4_ios_game import Original, SELECT, FIELD_SELECT, need
from extract_client_schema import ClientImage

ROOT=Path(__file__).resolve().parents[1]
METADATA_SHA256='f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e'
NATIVE_SHA256='68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3'

class OriginalAndroid(Original):
    def __init__(self,metadata:bytes,native:bytes):
        need(type(metadata) is bytes and type(native) is bytes,'original_bytes_required')
        need(hashlib.sha256(metadata).hexdigest()==METADATA_SHA256,'metadata_sha256_differs')
        need(hashlib.sha256(native).hexdigest()==NATIVE_SHA256,'native_sha256_differs')
        self.im=ClientImage(metadata,native);self.m,self.b=metadata,native;self.h=self.im.header
        self.types={};self.type_ids={}
        for i in range(self.h[41]//88):
            row=struct.unpack_from('<16I8H2I',metadata,self.h[40]+i*88)
            namespace=self.string(row[1]);name=(namespace+'.' if namespace else '.')+self.string(row[0])
            self.types[i]=(name,row);self.type_ids.setdefault(name,[]).append(i)
        reg=[self.qword(0x96dd758+i*8) for i in range(16)]
        need(reg[6]==116916 and reg[10]==len(self.types),'registration_counts_differ')
        self.type_count,self.type_table,self.field_table=reg[6],reg[7],reg[11];self.size_table=reg[13]
        self.modules={};self.images=[];self._decoded={}
        for position in range(self.h[42],self.h[42]+self.h[43],40):
            row=struct.unpack_from('<10i',metadata,position)
            self.images.append((self.string(row[0]),row[2],row[2]+row[3]))
    def offset(self,address):return self.im.file_offset(address)
    def qword(self,address):return self.im.read_pointer(address)
    def decode(self,pointer,depth=0):
        need(depth<12,'type_depth_bound')
        if pointer in self._decoded:return self._decoded[pointer]
        data=self.qword(pointer);bits=struct.unpack_from('<I',self.b,self.offset(pointer)+8)[0];code=(bits>>16)&255
        primitive={1:'System.Void',2:'System.Boolean',3:'System.Char',4:'System.SByte',5:'System.Byte',6:'System.Int16',7:'System.UInt16',8:'System.Int32',9:'System.UInt32',10:'System.Int64',11:'System.UInt64',12:'System.Single',13:'System.Double',14:'System.String',24:'System.IntPtr',25:'System.UIntPtr',28:'System.Object'}
        if code in (17,18):name=self.types[data][0]
        elif code==21:
            base,inst=self.qword(data),self.qword(data+8);count=struct.unpack_from('<I',self.b,self.offset(inst))[0]
            need(count<=32,'generic_argument_bound');args=self.qword(inst+8)
            name=self.decode(base,depth+1)+'<'+','.join(self.decode(self.qword(args+i*8),depth+1) for i in range(count))+'>'
        elif code in (15,29):name=self.decode(data,depth+1)+('*' if code==15 else '[]')
        elif code==20:name=self.decode(self.qword(data),depth+1)+'[array]'
        else:name=primitive.get(code,'generic-parameter:'+str(data))
        if bits&(1<<29):name+='&'
        self._decoded[pointer]=name;return name
    def module(self,name):
        if name in self.modules:return self.modules[name]
        locations=set();offset=0
        while True:
            offset=self.b.find(name.encode()+b'\0',offset)
            if offset<0:break
            locations.add(self.im.virtual_address(offset));offset+=1
        candidates=set()
        for address,target in self.im.relocations.items():
            if target not in locations:continue
            try:
                count,table=self.qword(address+8),self.qword(address+16)
                if 0<count<1000000:self.offset(table+(count-1)*8);candidates.add((count,table))
            except (ValueError,struct.error):pass
        need(len(candidates)==1,'codegen_module_ambiguous:'+name)
        self.modules[name]=next(iter(candidates));return self.modules[name]
    def export_bindings(self):
        wanted={'il2cpp_array_new':'void*(void*,uintptr_t)','il2cpp_string_new':'void*(const char*)',
            'il2cpp_type_get_object':'void*(const void*)'}
        shoff=struct.unpack_from('<Q',self.b,40)[0];shsize,count=struct.unpack_from('<HH',self.b,58)
        sections=[struct.unpack_from('<II4QII2Q',self.b,shoff+i*shsize) for i in range(count)]
        result={}
        for section in sections:
            if section[1]!=11:continue
            strings=sections[section[6]]
            for offset in range(section[4],section[4]+section[5],section[9]):
                name,info,_,_,address,_=struct.unpack_from('<IBBHQQ',self.b,offset)
                start=strings[4]+name;end=self.b.index(0,start,strings[4]+strings[5]);name=self.b[start:end].decode()
                if name not in wanted:continue
                need(info&15==2 and address>0,'native_export_kind_differs')
                need(name not in result,'native_export_ambiguous')
                result[name]={'rva':hex(address),'prefix':self.b[self.offset(address):self.offset(address)+16].hex(),
                    'native_abi':wanted[name],'dynamic_symbol':True,'has_method_info_argument':False}
        need(set(result)==set(wanted),'native_export_missing');return result

def build_profile(metadata:bytes,native:bytes)->dict:
    original=OriginalAndroid(metadata,native)
    methods={alias:original.method(*selection) for alias,selection in SELECT.items()}
    for method in methods.values():
        args=[] if method['static'] else ['void*']
        args.extend(original.native_type(arg['type']) for arg in method['parameters'])
        method['native_abi']=original.native_type(method['return'])+'('+','.join([*args,'const MethodInfo*'])+')'
    fields={};proof={}
    for alias,(owner,name) in FIELD_SELECT.items():
        available=original.fields(owner);need(name in available,'field_identity_missing:'+owner+'.'+name)
        found=available[name];need(type(found['offset']) is int and found['offset']>=0,'field_offset_invalid')
        fields[alias]=found['offset'];proof[alias]={'type':owner,'name':name,**found}
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
    enum_rows={name:original.enum_value(*selection) for name,selection in enum_select.items()}
    structs={name.rsplit('.',1)[-1]:original.struct_layout(name) for name in (
        'UnityEngine.Rect','UnityEngine.Rendering.AsyncGPUReadbackRequest',
        'UnityEngine.Rendering.RenderTargetIdentifier','UnityEngine.Rendering.ScriptableRenderContext',
        'UnityEngine.Playables.PlayableGraph','UnityEngine.Animations.AnimationStream')}
    runtime_types={}
    for name in ('System.Single','UnityEngine.AudioClip','UnityEngine.Texture2D'):
        tid=original.type_id(name);row=original.types[tid][1];type_index=row[2];pointer=original.qword(original.type_table+type_index*8)
        bits=struct.unpack_from('<I',native,original.offset(pointer)+8)[0];kind=(bits>>16)&255
        need(original.type_name(type_index)==name,'runtime_type_identity_differs')
        runtime_types[name]={'type':name,'kind':kind,'rva':hex(pointer),'prefix':native[original.offset(pointer):original.offset(pointer)+16].hex(),'metadata_type_index':type_index,'metadata_type_definition_index':tid,'type_table_pointer_slot':hex(original.type_table+type_index*8)}
    return {'schema':1,'platform':'android','sources':{'metadata_sha256':METADATA_SHA256,'native_sha256':NATIVE_SHA256},
        'methods':methods,'fields':fields,'field_proof':proof,'runtime_types':runtime_types,'type_namespaces':{alias:original.string(original.types[original.type_id(name)][1][1]) for alias,name in (('.CinemachineTrack','.CinemachineTrack'),('.UpdateStatus','Cinemachine.CinemachineCore/UpdateStatus'))},'exports':original.export_bindings(),'generic_calls':{'camera_status_try_get':{'rva':'0x62ff700','prefix':native[original.offset(0x62ff700):original.offset(0x62ff700)+16].hex(),'native_abi':'bool(void*,void*,void**,const MethodInfo*)','caller':'Cinemachine.CinemachineCore.UpdateVirtualCamera','runtime_method_slot':'0x99a88c8'}},
        'enums':{name:row[0] for name,row in enum_rows.items()},
        'enum_proof':{name:row[1] for name,row in enum_rows.items()},'structs':structs,
        'scope':{'static_original_binding_proof':True,'game_executed':False,'runtime_verified':False,'offline_audio_decoder_runtime_verified':False}}

def render_header(android:dict,ios:dict)->str:
    aliases=sorted(android['methods']);need(aliases==sorted(ios['methods']),'platform_api_aliases_differ')
    lines=['#pragma once','#ifndef IDOLY_DARWIN_BRIDGE','#include <cstdint>','#endif','// Generated by tools/audit_mp4_game.py from the pinned original clients.',
        'namespace idoly_mp4_game {','struct Binding { uintptr_t rva; uint8_t prefix[16]; };','struct GameProfile {']
    lines += ['    Binding '+alias+';' for alias in aliases];lines+=['};']
    for platform,profile in [('android',android),('ios',ios)]:
        lines+=['inline constexpr GameProfile '+platform+'_game_profile = {']
        for alias in aliases:
            method=profile['methods'][alias];prefix=bytes.fromhex(method['prefix']);need(len(prefix)==16,'prefix_length')
            lines+=['    { '+method['rva']+', {'+', '.join('0x'+prefix[i:i+1].hex() for i in range(16))+'} }, // '+alias]
        lines+=['};','inline constexpr Binding '+platform+'_game_bindings[] = {']
        lines += ['    '+platform+'_game_profile.'+alias+',' for alias in aliases]
        lines+=['};']
    lines+=['struct RuntimeProfile { Binding array_new,string_new,type_get_object,single_type,audio_clip_type,texture2d_type,camera_status_try_get; };']
    for platform,profile in [('android',android),('ios',ios)]:
        rows=[profile['exports'][name] for name in ('il2cpp_array_new','il2cpp_string_new','il2cpp_type_get_object')]
        rows += [profile['runtime_types'][name] for name in ('System.Single','UnityEngine.AudioClip','UnityEngine.Texture2D')]
        rows += [profile['generic_calls']['camera_status_try_get']]
        lines+=['inline constexpr RuntimeProfile '+platform+'_runtime_profile = {']
        for row in rows:
            prefix=bytes.fromhex(row['prefix']);need(len(prefix)==16,'prefix_length')
            lines+=['    { '+row['rva']+', {'+', '.join('0x'+prefix[i:i+1].hex() for i in range(16))+'} },']
        lines+=['};']
    lines+=['} // namespace idoly_mp4_game',''];return '\n'.join(lines)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata',type=Path,required=True);parser.add_argument('--native',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'client-presentation/native/mp4_game_profile.json')
    parser.add_argument('--ios-profile',type=Path,default=ROOT/'client-presentation/native/mp4_game_ios_profile.json')
    parser.add_argument('--header',type=Path,default=ROOT/'client-presentation/native/mp4_game_profile.hpp');args=parser.parse_args(argv)
    soft,hard=resource.getrlimit(resource.RLIMIT_AS);resource.setrlimit(resource.RLIMIT_AS,(min(soft,3*1024**3) if soft>=0 else 3*1024**3,hard))
    profile=build_profile(args.metadata.read_bytes(),args.native.read_bytes())
    args.output.write_text(json.dumps(profile,indent=2)+'\n')
    ios=json.loads(args.ios_profile.read_text());args.header.write_text(render_header(profile,ios))
    print(json.dumps({'status':'PASS_STATIC_ORIGINAL_BINDINGS','methods':len(profile['methods']),'fields':len(profile['fields']),'profile':str(args.output),'header':str(args.header)}))
if __name__=='__main__':main()
