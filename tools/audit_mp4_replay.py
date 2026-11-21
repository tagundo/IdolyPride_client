#!/usr/bin/env python3
"""Audit sequential MV queue replay against both pinned original clients.

Reads original bytes only. Methods are selected by exact managed signatures;
allocation types, original value-call ABIs, and public IL2CPP exports are proved
independently of the MP4 rendering hook profiles. No game code is executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import struct

from audit_mp4_ios_game import Original, need
from audit_mp4_game import OriginalAndroid
from extract_ios_schema import read_ipa

ROOT=Path(__file__).resolve().parents[1]
SELECT={
    'out_game_param_ctor':('Solis.OutGame.OutGameLivePlayerParam','.ctor',2),
    'actor_descriptor_ctor':('Solis.Common.SolisActorDescriptor','.ctor',0),
    'transition_param_ctor':('Solis.OutGame.LivePlayerTransitionParam','.ctor',0),
    'param_add_actor':('Solis.Common.SolisLivePlayerParam','AddActor',6),
    'scene_instance':('Solis.OutGame.OutGameScenePresenter','get_Instance',0),
    'scene_busy':('Solis.OutGame.OutGameScenePresenter','get_IsBusy',0),
    'live_state':('Solis.OutGame.ScreenState','get_LivePlayer',0),
    'tree_with_param':('Qua.UI.TF','Tree',2,('Qua.UI.IWindowNodeState','Qua.UI.TransitionParam')),
    'open_tree':('Qua.UI.WindowPresenterBase','OpenTree',2),
    'top_screen':('Qua.UI.WindowPresenterBase','get_TopScreen',0),
    'presenter_end':('Solis.OutGame.LivePlayerScreenPresenter','EndAsync',1),
    'task_status':('Cysharp.Threading.Tasks.UniTask','get_Status',0),
    'task_get_awaiter':('Cysharp.Threading.Tasks.UniTask','GetAwaiter',0),
    'task_get_result':('Cysharp.Threading.Tasks.UniTask/Awaiter','GetResult',0),
    'player_ready':('Solis.Common.SolisLivePlayer','get_IsReady',0),
}
RUNTIME_TYPES={
    'out_game_param_type':'Solis.OutGame.OutGameLivePlayerParam',
    'actor_descriptor_type':'Solis.Common.SolisActorDescriptor',
    'transition_param_type':'Solis.OutGame.LivePlayerTransitionParam',
}
EXPORTS={
    'field_set_value':('il2cpp_field_set_value','void(void*,const void*,const void*)'),
    'field_from_name':('il2cpp_class_get_field_from_name','void*(void*,const char*)'),
    'field_type':('il2cpp_field_get_type','const void*(const void*)'),
    'class_from_type':('il2cpp_class_from_type','void*(const void*)'),
    'class_method':('il2cpp_class_get_method_from_name','const void*(void*,const char*,int32_t)'),
    'object_new':('il2cpp_object_new','void*(void*)'),
    'type_get_type':('il2cpp_type_get_type','int32_t(const void*)'),
}
FIELD_SELECT={
    'stage_capacity':('Solis.OutGame.OutGameLivePlayerParam','stageMaxCapacity'),
    'detach_actors':('Solis.Common.SolisLivePlayerParam','detachActorsOnPlayerDestroyed'),
    'assets':('VL.Core.VLActorDescriptor','_assets'),
    'descriptor_name':('VL.Core.VLActorDescriptor','_name'),
    'game_objects':('VL.Core.VLActorDescriptor','_gameObjects'),
    'humanoid':('VL.VLDefaultActorDescriptor','_humanoid'),
    'collider':('VL.VLDefaultActorDescriptor','_colliderType'),
    'collider_trigger':('VL.VLDefaultActorDescriptor','_colliderTrigger'),
    'blink_disabled':('Solis.Common.SolisActorDescriptor','_autoBlinkDisabled'),
    'adv_settings':('Solis.Common.SolisActorDescriptor','_useADVSettings'),
    'render_layer':('Solis.Common.SolisActorDescriptor','_renderingLayerMaskBaseIndex'),
    'transition_live':('Solis.OutGame.LivePlayerTransitionParam','liveParam'),
    'transition_debug':('Solis.OutGame.LivePlayerTransitionParam','isDebugMode'),
}


def c_exports(original,platform):
    wanted={name:abi for name,abi in EXPORTS.values()};found={}
    data=original.b
    if platform=='android':
        offset=struct.unpack_from('<Q',data,40)[0];size,count=struct.unpack_from('<HH',data,58)
        sections=[struct.unpack_from('<II4QII2Q',data,offset+i*size) for i in range(count)]
        for section in sections:
            if section[1]!=11:continue
            strings=sections[section[6]]
            for at in range(section[4],section[4]+section[5],section[9]):
                index,info,_,_,address,_=struct.unpack_from('<IBBHQQ',data,at)
                start=strings[4]+index;end=data.index(0,start,strings[4]+strings[5]);name=data[start:end].decode()
                if name not in wanted:continue
                need(info&15==2 and address>0,'replay_export_kind_differs')
                need(name not in found,'replay_export_duplicate');found[name]=address
    else:
        symbols,count,strings,string_bytes=original.symtab
        for i in range(count):
            index,kind,_,_,address=struct.unpack_from('<IBBHQ',data,symbols+i*16)
            if not(kind&1 and kind&0xe==0xe and index<string_bytes):continue
            start=strings+index;end=data.find(b'\0',start,min(strings+string_bytes,start+256));raw=data[start:end]
            if end<0:continue
            for name in wanted:
                if raw==('_'+name).encode():need(name not in found,'replay_export_duplicate');found[name]=address
        offset,size=original.exports;trie=data[offset:offset+size]
        def uleb(at):
            value=0
            for i in range(10):
                need(at<len(trie),'replay_export_trie_truncated');byte=trie[at];at+=1;value|=(byte&127)<<(i*7)
                if not byte&128:return value,at
            raise ValueError('replay_export_uleb_bound')
        def lookup(name,node=0,prefix=b'',depth=0):
            need(depth<128 and node<len(trie),'replay_export_trie_bound')
            length,at=uleb(node);terminal=at;at+=length
            if prefix==name and length:
                flags,end=uleb(terminal);need(not flags&0x18,'replay_export_not_local');address,_=uleb(end);return address
            need(at<len(trie),'replay_export_trie_truncated');children=trie[at];at+=1
            for _ in range(children):
                end=trie.index(0,at);edge=trie[at:end];at=end+1;child,at=uleb(at)
                if name.startswith(prefix+edge):
                    result=lookup(name,child,prefix+edge,depth+1)
                    if result is not None:return result
            return None
        for name,address in found.items():need(lookup(('_'+name).encode())==address,'replay_export_trie_disagrees')
    need(set(found)==set(wanted),'replay_export_missing')
    return {alias:{'export':name,'rva':hex(found[name]),'prefix':data[original.offset(found[name]):original.offset(found[name])+16].hex(),
            'native_abi':abi,'dynamic_symbol':True,'has_method_info_argument':False,
            'export_trie_and_symtab_agree':platform=='ios'} for alias,(name,abi) in EXPORTS.items()}


def build_profile(original,platform):
    methods={alias:original.method(*select) for alias,select in SELECT.items()}
    for alias,row in methods.items():
        args=[] if row['static'] else ['void*']
        args.extend(original.native_type(p['type']) for p in row['parameters'])
        result='UniTask16' if alias=='task_get_awaiter' else original.native_type(row['return'])
        row['native_abi']=result+'('+','.join([*args,'const MethodInfo*'])+')'
    need(methods['presenter_end']['native_abi']=='UniTask16(void*,CancellationToken8,const MethodInfo*)','replay_end_abi_differs')
    need(methods['task_status']['native_abi']=='int32_t(void*,const MethodInfo*)','replay_status_abi_differs')
    need(methods['task_get_result']['native_abi']=='void(void*,const MethodInfo*)','replay_result_abi_differs')
    structs={name.rsplit('.',1)[-1]:original.struct_layout(name) for name in ('Cysharp.Threading.Tasks.UniTask','System.Threading.CancellationToken')}
    # UniTask's nested Awaiter is returned by value and is layout-identical to
    # the original task. Prove its own size and fields; never infer from a name.
    awaiter='Cysharp.Threading.Tasks.UniTask/Awaiter';tid=original.type_id(awaiter)
    sizep=original.qword(original.size_table+tid*8);instance,native,_,_=struct.unpack_from('<4I',original.b,original.offset(sizep))
    fields=original.fields(awaiter)
    need(instance==32 and native==0xffffffff,'replay_awaiter_size_differs')
    need({key:row['offset']-16 for key,row in fields.items()}=={'task':0},'replay_awaiter_fields_differ')
    need(fields['task']['type']=='Cysharp.Threading.Tasks.UniTask','replay_awaiter_task_differs')
    get_awaiter_row=struct.unpack_from('<7I4H',original.m,original.h[12]+methods['task_get_awaiter']['metadata_method_index']*36)
    need(get_awaiter_row[2]==original.types[tid][1][2],'replay_awaiter_return_type_differs')
    structs['Awaiter']={'bytes':16,'fields':{'task':0},'contains_managed_references':True,'metadata_type_definition_index':tid}
    statuses={name:original.enum_value('Cysharp.Threading.Tasks.UniTaskStatus',name) for name in ('Pending','Succeeded','Faulted','Canceled')}
    need({name:value[0] for name,value in statuses.items()}=={'Pending':0,'Succeeded':1,'Faulted':2,'Canceled':3},'replay_task_status_values_differ')
    types={}
    for alias,name in RUNTIME_TYPES.items():
        tid=original.type_id(name);row=original.types[tid][1];index=row[2];pointer=original.qword(original.type_table+index*8)
        need(original.type_name(index)==name,'replay_runtime_type_differs');kind=struct.unpack_from('<I',original.b,original.offset(pointer)+8)[0]>>16&255
        need(kind==18,'replay_runtime_class_required')
        types[alias]={'type':name,'kind':kind,'rva':hex(pointer),'prefix':original.b[original.offset(pointer):original.offset(pointer)+16].hex(),
            'metadata_type_index':index,'metadata_type_definition_index':tid,'type_table_pointer_slot':hex(original.type_table+index*8)}
    fields={}
    for alias,(owner,name) in FIELD_SELECT.items():
        row=original.fields(owner).get(name);need(row is not None and type(row['offset']) is int and row['offset']>=16,'replay_field_missing')
        fields[alias]={'owner':owner,'name':name,**row}
    return {'schema':1,'platform':platform,'sources':{'metadata_sha256':hashlib.sha256(original.m).hexdigest(),'native_sha256':hashlib.sha256(original.b).hexdigest()},
        'methods':methods,'runtime_types':types,'exports':c_exports(original,platform),'fields':fields,'structs':structs,
        'task_status_values':{name:value[0] for name,value in statuses.items()},'task_status_proof':{name:value[1] for name,value in statuses.items()},
        'scope':{'static_original_binding_proof':True,'game_executed':False,'runtime_verified':False,
            'original_screen_router':True,'independent_concurrent_scene':False}}


def render_header(android,ios):
    def all_rows(profile):return {**profile['methods'],**profile['runtime_types'],**profile['exports']}
    a,b=all_rows(android),all_rows(ios);need(set(a)==set(b),'replay_platform_aliases_differ');aliases=sorted(a)
    lines=['#pragma once','#ifndef IDOLY_DARWIN_BRIDGE','#include <stdint.h>','#endif',
        '// Generated by tools/audit_mp4_replay.py; pinned originals, read-only proof.',
        'namespace idoly_mp4_replay {','struct ReplayBinding { uintptr_t rva; uint8_t prefix[16]; };','struct ReplayProfile {']
    lines+=['    ReplayBinding '+alias+';' for alias in aliases];lines+=['};']
    for platform,profile in [('android',android),('ios',ios)]:
        lines+=['inline constexpr ReplayProfile '+platform+'_replay_profile = {']
        for alias,row in sorted(all_rows(profile).items()):
            raw=bytes.fromhex(row['prefix']);need(len(raw)==16,'replay_prefix_bound')
            lines+=['    {'+row['rva']+', {'+', '.join('0x'+raw[i:i+1].hex() for i in range(16))+'}}, // '+alias]
        lines+=['};','inline constexpr ReplayBinding '+platform+'_replay_bindings[] = {']
        lines+=['    '+platform+'_replay_profile.'+alias+',' for alias in aliases];lines+=['};']
    lines+=['} // namespace idoly_mp4_replay',''];return '\n'.join(lines)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--android-metadata',type=Path,required=True);p.add_argument('--android-native',type=Path,required=True)
    p.add_argument('--ios-ipa',type=Path,required=True);p.add_argument('--output-dir',type=Path,default=ROOT/'client-presentation/native');args=p.parse_args(argv)
    soft,hard=resource.getrlimit(resource.RLIMIT_AS);resource.setrlimit(resource.RLIMIT_AS,(min(soft,3*1024**3) if soft>=0 else 3*1024**3,hard))
    android=build_profile(OriginalAndroid(args.android_metadata.read_bytes(),args.android_native.read_bytes()),'android')
    metadata,native,_=read_ipa(args.ios_ipa);ios=build_profile(Original(metadata,native),'ios')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for profile in (android,ios):(args.output_dir/('mp4_replay_'+profile['platform']+'_profile.json')).write_text(json.dumps(profile,indent=2)+'\n')
    (args.output_dir/'mp4_replay_profile.hpp').write_text(render_header(android,ios))
    print(json.dumps({'status':'PASS_STATIC_ORIGINAL_REPLAY_BINDINGS','methods':len(SELECT),'runtime_types':len(RUNTIME_TYPES),'exports':len(EXPORTS),'fields':len(FIELD_SELECT)}))

if __name__=='__main__':main()
