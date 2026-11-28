#!/usr/bin/env python3
"""Reproduce fresh ordinary Photography replay bindings from pinned originals."""
from pathlib import Path
import argparse,hashlib,json,struct
from audit_mp4_ios_game import Original,need
from audit_mp4_game import OriginalAndroid
from audit_mp4_replay import c_exports
ROOT=Path(__file__).resolve().parents[1]
SELECT={
 'download_targets':('Solis.Photography.Data.PhotographyDataUtility','GetDownloadTargets',1,('Solis.Photography.Data.IPhotographyTransition',)),
 'pre_download':('Solis.Common.Octo.ResourceDownloader','PreDownloadAssetsAsync',3,('System.Collections.Generic.IEnumerable`1<System.String>','System.Threading.CancellationToken','System.Boolean')),
 'stage_master':('Solis.Common.Master.MasterManager','get_PhotoQuestStageMaster',0),
 'music_master':('Solis.Common.Master.MasterManager','get_PhotoQuestMusicMaster',0),
 'costume_master':('Solis.Common.Master.MasterManager','get_CostumeMaster',0),
 'hair_master':('Solis.Common.Master.MasterManager','get_HairMaster',0),
 'stage_rows':('Solis.Common.Master.PhotoQuestStageMaster','GetAllWithSortByKey',1),
 'music_rows':('Solis.Common.Master.PhotoQuestMusicMaster','GetAllWithSortByKey',1),
 'find_costume':('Solis.Common.Master.CostumeMaster','FindByKey',1,('System.String',)),
 'find_hair':('Solis.Common.Master.HairMaster','FindByKey',1,('System.String',)),
 'scene_set_data':('Solis.Common.SolisSceneManager','set_TransitionData',1),
 'scene_load':('Solis.Common.SolisSceneManager','LoadScene',2,('System.Int32','UnityEngine.SceneManagement.LoadSceneMode')),
 'actor_ctor':('Solis.Common.Data.ActorCostume','.ctor',2),
 'actor_costume_id':('Solis.Common.Data.ActorCostume','get_CostumeId',0),
 'actor_hair_id':('Solis.Common.Data.ActorCostume','get_HairId',0),
 'transition_ctor':('Solis.Photography.Data.PhotographyLiveTransitionData','.ctor',4),
 'screen_transition_ctor':('Solis.Photography.Data.PhotographyLiveScreenTransitionData','.ctor',5),
}
TYPES={'downloader_type':'Solis.Common.Octo.ResourceDownloader','scene_manager_type':'Solis.Common.SolisSceneManager','scene_define_type':'.SceneDefine','unity_scene_manager_type':'UnityEngine.SceneManagement.SceneManager','actor_type':'Solis.Common.Data.ActorCostume','transition_type':'Solis.Photography.Data.PhotographyLiveTransitionData','screen_transition_type':'Solis.Photography.Data.PhotographyLiveScreenTransitionData'}
FIELDS={'transition_video':('Solis.Photography.Data.AbstPhotographyTransitionData','<IsMvMusic>k__BackingField'),'scene_photography':('.SceneDefine','Photography'),'scene_allow_load':('UnityEngine.SceneManagement.SceneManager','s_AllowLoadScene'),'scene_transition_data':('Solis.Common.SolisSceneManager','<TransitionData>k__BackingField'),'singleton_instance':('Qua.Utility.Singleton`1','_instance'),'transition_preview':('Solis.Photography.Data.AbstPhotographyTransitionData','<IsPreview>k__BackingField'),'transition_stage':('Solis.Photography.Data.PhotographyLiveTransitionData','<PhotoStage>k__BackingField'),'transition_music':('Solis.Photography.Data.PhotographyLiveTransitionData','<PhotoMusic>k__BackingField'),'transition_original':('Solis.Photography.Data.PhotographyLiveScreenTransitionData','<IsOriginal>k__BackingField'),'costume_id':('Solis.Common.Proto.Master.Costume','id_'),'hair_id':('Solis.Common.Proto.Master.Hair','id_'),'actor_list':('Solis.Photography.Data.AbstPhotographyTransitionData','<ActorCostumeList>k__BackingField'),'display_actors':('Solis.Photography.Data.AbstPhotographyTransitionData','<DisplayActorCostumeList>k__BackingField'),'costume':('Solis.Common.Data.ActorCostume','_costume'),'hair':('Solis.Common.Data.ActorCostume','_hair'),'stage_id':('Solis.Common.Proto.Master.PhotoQuestStage','id_'),'music_id':('Solis.Common.Proto.Master.PhotoQuestMusic','id_')}
def build_profile(original,platform):
 methods={name:original.method(*s) for name,s in SELECT.items()}
 for m in methods.values():
  args=[] if m['static'] else ['void*'];args += [original.native_type(a['type']) for a in m['parameters']]
  m['native_abi']=original.native_type(m['return'])+'('+','.join(args+['const MethodInfo*'])+')'
 methods.update(c_exports(original,platform,selected={'field_static_get':('il2cpp_field_static_get_value','void(const FieldInfo*,void*)'),'runtime_class_init':('il2cpp_runtime_class_init','void(Il2CppClass*)'),'method_return_type':('il2cpp_method_get_return_type','const Il2CppType*(const MethodInfo*)'),'class_methods':('il2cpp_class_get_methods','const MethodInfo*(void*,void**)')}))
 pred=methods['pre_download'];definition=original.types[original.type_id(pred['type'])][1]
 count,table=original.module(pred['module']);matches=[]
 for index in range(definition[9],definition[9]+definition[16]):
  row=struct.unpack_from('<7I4H',original.m,original.h[12]+index*36);token=row[6]&0xffffff
  if token and token<=count and original.qword(table+(token-1)*8)==int(pred['rva'],16):matches.append(index)
 need(matches==[pred['metadata_method_index']],'photo_predownload_pointer_not_unique')
 pred['runtime_resolution']='Unique audited methodPointer within the pinned ResourceDownloader class; overloaded name/count is insufficient'
 need(methods['pre_download']['return']=='Cysharp.Threading.Tasks.UniTask`1<System.Boolean>','photo_download_task_type_differs')
 methods['pre_download']['native_abi']='BoolUniTask16(void*,CancellationToken8,bool,const MethodInfo*)'
 for alias,address,abi in {
  'android': [('bool_task_status',0x7394438,'int32_t(BoolUniTask16*,const MethodInfo*)'),('bool_task_awaiter',0x73944ec,'BoolUniTask16(BoolUniTask16*,const MethodInfo*)'),('bool_task_result',0x8138824,'bool(BoolUniTask16*,const MethodInfo*)')],
  'ios': [('bool_task_status',0x54039d8,'int32_t(BoolUniTask16*,const MethodInfo*)'),('bool_task_awaiter',0x5403b70,'BoolUniTask16(BoolUniTask16*,const MethodInfo*)'),('bool_task_result',0x643c38c,'bool(BoolUniTask16*,const MethodInfo*)')],
 }[platform]:
  methods[alias]={'rva':hex(address),'prefix':original.b[original.offset(address):original.offset(address)+16].hex(),'native_abi':abi,'runtime_closed_method_info_required':True,'source':'Original closed UniTask<Boolean> and its Awaiter; resolve context from PreDownload return type'}
 for alias,(address,abi) in {'android':{'list_ctor':(0x6ad9c7c,'void(void*,const MethodInfo*)'),'list_add':(0x6ada3f0,'void(void*,void*,const MethodInfo*)')},'ios':{'list_ctor':(0x492f868,'void(void*,const MethodInfo*)'),'list_add':(0x493024c,'void(void*,void*,const MethodInfo*)')}}[platform].items():
  methods[alias]={'type':'System.Collections.Generic.List`1','name':'.ctor' if alias=='list_ctor' else 'Add','rva':hex(address),'prefix':original.b[original.offset(address):original.offset(address)+16].hex(),'native_abi':abi,'runtime_closed_method_info_required':True,'source':'Original closed List<ActorCostume> shared reference-generic body'}
 types={}
 for alias,name in TYPES.items():
  tid=original.type_id(name);index=original.types[tid][1][2];pointer=original.qword(original.type_table+index*8)
  need(original.type_name(index)==name,'photo_replay_type_differs')
  types[alias]={'type':name,'rva':hex(pointer),'prefix':original.b[original.offset(pointer):original.offset(pointer)+16].hex(),'metadata_type_index':index,'metadata_type_definition_index':tid}
 fields={alias:{'owner':owner,'name':name,**original.fields(owner)[name]} for alias,(owner,name) in FIELDS.items()}
 enums={alias:original.enum_value(name,'Id_Asc')[0] for alias,name in [('stage_sort','Solis.Common.Master.PhotoQuestStageSortType'),('music_sort','Solis.Common.Master.PhotoQuestMusicSortType')]}
 enums['load_mode']=original.enum_value('UnityEngine.SceneManagement.LoadSceneMode','Single')[0]
 hierarchy=[];parent='Solis.Common.SolisSceneManager'
 for _ in range(16):
  row=original.types[original.type_id(parent)][1];base=original.type_name(row[4]);hierarchy.append({'type':parent,'parent':base})
  if base=='System.Object':break
  parent=base.split('<',1)[0]
 need(any(row['parent']=='UnityEngine.Object' for row in hierarchy),'scene_manager_unity_ancestry_differs')
 return {'schema':1,'platform':platform,'sources':{'metadata_sha256':hashlib.sha256(original.m).hexdigest(),'native_sha256':hashlib.sha256(original.b).hexdigest()},'methods':methods,'runtime_types':types,'fields':fields,'enums':enums,'scene_manager_ancestry':hierarchy,'bool_task_layout':{'bytes':16,'source':0,'result':8,'token':10},'scope':{'normal_master_only':True,'special_wrappers_supported':False,'game_executed':False,'runtime_verified':False}}
def render_header(android,ios):
 names=sorted(android['methods'])+sorted(android['runtime_types']);need(names==sorted(ios['methods'])+sorted(ios['runtime_types']),'photo_replay_aliases_differ')
 lines=['#pragma once','#include "mp4_game_profile.hpp"','// Generated by tools/audit_mp4_photography_replay.py from pinned originals.','namespace idoly_mp4_photography_replay {','struct Profile {']+[' idoly_mp4_game::Binding '+n+';' for n in names]+[' int32_t stage_sort,music_sort,load_mode;','};']
 for p,profile in [('android',android),('ios',ios)]:
  all_={**profile['methods'],**profile['runtime_types']};lines+=['inline constexpr Profile '+p+'_profile={']
  for n in names:
   r=all_[n];b=bytes.fromhex(r['prefix']);lines+=[' {'+r['rva']+', {'+', '.join(hex(x) for x in b)+'}}, // '+n]
  lines += [str(profile['enums']['stage_sort'])+', '+str(profile['enums']['music_sort'])+', '+str(profile['enums']['load_mode'])+'};']
  for group, members in [('code_bindings', sorted(profile['methods'])), ('type_bindings', sorted(profile['runtime_types']))]:
   lines+=['inline constexpr idoly_mp4_game::Binding '+p+'_'+group+'[]={']+[' '+p+'_profile.'+n+',' for n in members]+['};']
 lines+=['} // namespace idoly_mp4_photography_replay',''];return '\n'.join(lines)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--originals',type=Path,required=True);p.add_argument('--output-dir',type=Path,default=ROOT/'client-presentation/native');a=p.parse_args();profiles={}
 for name,C,m,n in [('android',OriginalAndroid,'android-metadata.dat','android-native.so'),('ios',Original,'ios-metadata.dat','ios-native.bin')]:
  profiles[name]=build_profile(C((a.originals/m).read_bytes(),(a.originals/n).read_bytes()),name);(a.output_dir/('mp4_photography_replay_'+name+'_profile.json')).write_text(json.dumps(profiles[name],indent=2)+'\n')
 (a.output_dir/'mp4_photography_replay_profile.hpp').write_text(render_header(profiles['android'],profiles['ios']));print('PASS original typed Photography replay bindings')
if __name__=='__main__':main()
