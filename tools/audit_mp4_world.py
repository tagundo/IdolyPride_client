#!/usr/bin/env python3
"""Generate exact world-admission bindings, native RTTI and FixedUpdate proof.

No public Physics simulation control is assumed. The actual fixed-root native
condition and runtime RTTI lookup close cases absent from managed metadata.
"""
from pathlib import Path
import argparse,hashlib,json,re,struct
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original
from extract_client_schema import ClientImage
from audit_mp4_engine_clock import PINS as ENGINE_PINS
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
SELECT={'find_objects':('UnityEngine.Object','FindObjectsOfType',2,('System.Type','System.Boolean')),
        'current_loop':('UnityEngine.LowLevel.PlayerLoop','GetCurrentPlayerLoopInternal',0),
        'cloth_enabled':('UnityEngine.Cloth','get_enabled',0),
        'actor_registry':('VL.Core.VLActorController','get_actorControllers',0),
        'game_object':('UnityEngine.Component','get_gameObject',0),
        'active_hierarchy':('UnityEngine.GameObject','get_activeInHierarchy',0),
        'active_enabled':('UnityEngine.Behaviour','get_isActiveAndEnabled',0),
        'animator_graph':('UnityEngine.Animator','GetCurrentGraph',1),
        'animator_controller':('UnityEngine.Animator','get_runtimeAnimatorController',0),
        'animator_bound':('UnityEngine.Animator','get_hasBoundPlayables',0),
        'animator_mode':('UnityEngine.Animator','get_updateMode',0),
        'legacy_state_count':('UnityEngine.Animation','GetStateCount',0),
        'graph_valid':('UnityEngine.Playables.PlayableGraph','IsValid_Injected',1),
        'graph_output_count':('UnityEngine.Playables.PlayableGraph','GetOutputCount_Injected',1),
        'graph_output':('UnityEngine.Playables.PlayableGraph','GetOutputInternal_Injected',3),
        'output_valid':('UnityEngine.Playables.PlayableOutputHandle','IsValid_Injected',1),
        'output_type':('UnityEngine.Playables.PlayableOutputHandle','GetPlayableOutputType_Injected',1),
        'output_target':('UnityEngine.Animations.AnimationPlayableOutput','InternalGetTarget',1)}
TYPES={'rigidbody_type':'UnityEngine.Rigidbody','rigidbody2d_type':'UnityEngine.Rigidbody2D',
       'cloth_type':'UnityEngine.Cloth','character_controller_type':'UnityEngine.CharacterController',
       'fixed_update_type':'UnityEngine.PlayerLoop.FixedUpdate',
       'animator_type':'UnityEngine.Animator','animation_type':'UnityEngine.Animation',
       'animation_output_type':'UnityEngine.Animations.AnimationPlayableOutput'}
NATIVE_ENTRIES={
 'android':{'registry_slot':0x1497250,'lookup':0x54a674,'lookup_impl':0x54a688,'lookup_iterator':0x54ad4c,
            'lookup_hash':0x54bc88,'registrar':0x54b388,'fixed_condition':0x6420e4,'fixed_executor':0x63ffd8,
            'get_manager':0x6225e8,'fixed_tick':0x6221fc,'condition_exit':0x6400d0,
            'animator_register':0x8bbb80,'animator_unregister':0x8bb9e8,'animator_record_ctor':0x8affb8,'animator_append':0x8bf09c},
 'ios':{'registry_slot':0xa938f90,'lookup':0xbd69b4,'lookup_impl':0xbd69c4,'lookup_iterator':0xb410e0,
        'registrar':0xbd781c,'fixed_condition':0xccc210,'fixed_executor':0xccac30,
        'get_manager':0xcad690,'fixed_tick':0xcad210,'condition_exit':0xccad28,
        'animator_register':0xf13468,'animator_unregister':0xf13290,'animator_record_ctor':0xf072ec,'animator_append':0xf1681c}}
NATIVE_BINDINGS=('lookup','lookup_impl','lookup_iterator','lookup_hash','registrar','fixed_condition','fixed_executor',
                 'animator_register','animator_unregister','animator_record_ctor','animator_append')

DIRECTOR_NATIVE={
 'android':{'manager_slot':0x14e64c0,'tagged_queue':True,'entries':{
 'registry_getter':(0x731404,12),'sample_category':(0x72f8c0,172),'rebuild':(0x72f96c,108),'append':(0x73093c,172),
 'category':(0x73061c,76),'callbacks_rebuild':(0x730364,100),'callbacks_dispatch':(0x7302f0,116),'output_callbacks':(0x730a48,464),
 'drain':(0x72fb78,796),'collect':(0x72fe94,196),'enqueue':(0x730464,88),'deferred_a':(0x7305ac,112),'deferred_b':(0x73052c,128),
 'deferred_append_a':(0x7306c0,112),'deferred_append_b':(0x7304bc,112),'graph_create':(0x730834,132),'graph_destroy':(0x73075c,128),
 'atomic_push':(0x6f10cc,72),'atomic_pop':(0x6f115c,80)},'outputs':[
 (0x1423b70,0x8e39b0,384,[(0x8b34d8,3),(0x8b3e70,4)],True),
 (0x1426600,0x94e438,108,[(0x94dfc0,5)],False),(0x1419648,0x72df8c,84,[(0x72dfe0,2)],False)]},
 'ios':{'manager_slot':0xa8a8e00,'tagged_queue':False,'entries':{
 'registry_getter':(0xdc73a0,12),'sample_category':(0xdc5838,176),'rebuild':(0xdc58e8,120),'append':(0xdc696c,160),
 'category':(0xdc6618,80),'callbacks_rebuild':(0xdc632c,108),'callbacks_dispatch':(0xdc62b4,120),'output_callbacks':(0xdc6a6c,468),
 'drain':(0xdc5b18,820),'collect':(0xdc5e4c,204),'enqueue':(0xdc6448,100),'deferred_a':(0xdc65a4,116),'deferred_b':(0xdc6520,132),
 'deferred_append_a':(0xdc66c0,116),'deferred_append_b':(0xdc64ac,116),'graph_create':(0xdc6870,184),'graph_destroy':(0xdc6760,184),
 'atomic_push':(0xd87a1c,20),'atomic_pop':(0xd87a44,36)},'outputs':[
 (0x97f7688,0xf3fa68,416,[(0xf0aa08,3),(0xf0b490,4)],True),
 (0x97fa218,0xfa37f8,144,[(0xfa3394,5)],False),(0x97f2140,0xdc443c,96,[(0xdc449c,2)],False)]}}

def director_registry(original,engine,offset,platform):
 p=DIRECTOR_NATIVE[platform];md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
 def raw(a,n):return engine[offset(a):offset(a)+n]
 def binding(a,n):return {'rva':hex(a),'prefix':raw(a,16).hex(),'body':raw(a,n).hex(),'bounded_bytes':n}
 native={k:binding(*v)for k,v in p['entries'].items()}
 instructions={k:[i.mnemonic+' '+i.op_str for i in md.disasm(bytes.fromhex(v['body']),int(v['rva'],0))]for k,v in native.items()}
 assert any('#0x478]'in s for s in instructions['enqueue'])
 assert any('#0x368'in s for s in instructions['rebuild'])and any('#0x370]'in s for s in instructions['rebuild'])
 assert any('#0x378'in s for s in instructions['graph_create'])
 assert any('#0x41a]'in s for s in instructions['drain'])and any('#0x41b]'in s for s in instructions['category'])
 assert any('#0x3a8]'in s for s in instructions['deferred_b'])and any('#0x388]'in s for s in instructions['deferred_a'])
 assert any('#0x250'in s for s in instructions['callbacks_rebuild'])and any('#0x260]'in s for s in instructions['callbacks_dispatch'])
 assert any('#0x48'in s for s in instructions['sample_category'])
 assert any('#2'in s for s in instructions['graph_destroy'])and any('#0x20]'in s for s in instructions['graph_destroy'])
 im=ClientImage(original.m,engine)if platform=='android'else original
 outputs=[]
 for vt,producer,n,pairs,animation in p['outputs']:
  pointer=im.read_pointer(vt+0x20)if platform=='android'else im.qword(vt+0x20)
  assert pointer==producer,'original_output_producer_vtable_changed'
  body=binding(producer,n);ops=[i.mnemonic+' '+i.op_str for i in md.disasm(bytes.fromhex(body['body']),producer)]
  if animation:assert any('#0xd0]'in s for s in ops)and any('#0x190]'in s for s in ops)
  outputs.append({'vtable':hex(vt),'producer':body,'callbacks':[binding(a,16)for a,_ in pairs],
                  'categories':[c for _,c in pairs],'animation':animation})
 return {'manager_slot':hex(p['manager_slot']),'tagged_queue':p['tagged_queue'],'native':native,'outputs':outputs,
  'layout':{'active':0x368,'stopped':0x378,'slot':0x10,'slot_version':0x20,'slot_native':0x28,'queue':0x478,
            'queue_record_bytes':32,'deferred':[0x388,0x3a8],'graph_dispatch':[0x90,0x170],'callback_dispatch':0x250},
  'ownership_requires':['exact current source graphs or authorized BEFORE retirement basis plus actual valid pending Destroy/version+2',
   'typed animation target / audio state / script userData+managed node callback closure for every native output',
   'maintenance captured/closed witness and operation-kind authorization receipts; no manual flush'],
  'native_source_scope':'Original AArch64 producer and manager body source pins; not whole-scene or GPU execution proof'}

def render_director(profiles):
 names=list(DIRECTOR_NATIVE['android']['entries'])
 lines=['struct DirectorOutputRoute {uintptr_t vtable;CodeBinding producer;CodeBinding callbacks[2];uint32_t categories[2];uint8_t count;bool animation;};',
        'struct DirectorRegistryProfile {uintptr_t manager_slot;bool tagged_queue;CodeBinding '+','.join(names)+';DirectorOutputRoute outputs[3];};']
 def pin(row):return '{'+row['rva']+',{'+','.join(hex(b)for b in bytes.fromhex(row['prefix']))+'}}'
 for platform in('android','ios'):
  p=profiles[platform]['director_registry'];lines.append('inline constexpr DirectorRegistryProfile '+platform+'_director_registry_profile={'+p['manager_slot']+','+str(p['tagged_queue']).lower()+',')
  for name in names:lines.append('    '+pin(p['native'][name])+', // '+name)
  lines.append('    {')
  for route in p['outputs']:
   callbacks=[pin(v)for v in route['callbacks']];callbacks+=['{0,{}}']*(2-len(callbacks));categories=route['categories']+[0]*(2-len(route['categories']))
   lines.append('        {'+route['vtable']+','+pin(route['producer'])+',{'+','.join(callbacks)+'},{'+','.join(map(str,categories))+'},'+str(len(route['callbacks']))+','+str(route['animation']).lower()+'},')
  lines+=['    }','};']
 return '\n'.join(lines)

def whole(originals,platform):
 meta=(originals/(platform+'-metadata.dat')).read_bytes()
 aot=(originals/('android-native.so'if platform=='android'else'ios-native.bin')).read_bytes()
 engine=(originals/('mp4-android-analysis/libunity.so'if platform=='android'else'ios-native.bin')).read_bytes()
 original=(OriginalAndroid if platform=='android'else Original)(meta,aot)
 expected=json.loads((NATIVE/'mp4_playback_state_profile.json').read_text())['platforms'][platform]['sources']
 assert hashlib.sha256(meta).hexdigest()==expected['metadata_sha256']
 assert hashlib.sha256(aot).hexdigest()==expected['native_sha256']
 assert len(engine)==ENGINE_PINS[platform][1] and hashlib.sha256(engine).hexdigest()==ENGINE_PINS[platform][0]
 im=ClientImage(meta,engine)if platform=='android'else original
 return original,engine,(im.file_offset if platform=='android'else im.offset)

def build(originals,platform):
 original,engine,offset=whole(originals,platform);md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
 def raw(a,n):return engine[offset(a):offset(a)+n]
 def code(a,n):return list(md.disasm(raw(a,n),a))
 def bounded(a):
  out=[]
  for i in code(a,1024):
   out.append(i)
   if i.mnemonic=='ret':break
  assert out[-1].mnemonic=='ret','native_body_boundary_unproved'
  return out
 ep=dict(NATIVE_ENTRIES[platform]);lookup=bounded(ep['lookup_impl']);iterator=bounded(ep['lookup_iterator'])
 calls=[int(i.op_str[1:],0)for i in iterator if i.mnemonic=='bl']
 assert len(calls)==1
 ep['lookup_hash']=calls[0]
 # Exact readonly lookup field path and null result; iterator and hash prove
 # bucket stride/status/key/value, rather than inferring a C++ container ABI.
 text=[(i.mnemonic,i.op_str)for i in lookup]
 assert ('add','x0, x0, #0x40')in text
 assert any(i.mnemonic=='ldr'and i.op_str=='x0, [x8, #0x10]'for i in lookup)
 assert any(i.mnemonic=='mov'and i.op_str in('x0, xzr','x0, #0')for i in lookup)
 h=bounded(ep['lookup_hash']);ht=[(i.mnemonic,i.op_str)for i in h]
 assert ('ldr','w8, [x1]')in ht and ('ldr','w9, [x0, #8]')in ht
 assert any(i.mnemonic=='ldr'and '#8]'in i.op_str for i in h)
 assert any(i.mnemonic=='add'and 'lsl #1'in i.op_str for i in h)
 assert any(i.mnemonic=='add'and '#0x18'in i.op_str for i in h)
 # Registrar is the same manager's ID -> actual RuntimeTypeInfo map.
 reg=bounded(ep['registrar']);rt=[(i.mnemonic,i.op_str)for i in reg]
 assert ('ldr','w1, [x1, #0x28]')in rt
 if platform=='android':
  assert ('ldr','x2, [x21, #0x10]')in rt
  assert ('mov','w2, #0x50')in rt and ('add','x0, x20, #0x40')in rt
 else:
  assert ('ldr','x2, [x20, #0x10]')in rt and ('add','x0, x19, #0x40')in rt
  for item in [('ldr','q0, [x20]'),('str','q0, [x22]'),('ldp','q0, q1, [x20, #0x10]'),('ldp','q2, q3, [x20, #0x30]'),('stp','q2, q3, [x22, #0x30]'),('stp','q0, q1, [x22, #0x10]')]:
   assert item in rt
 condition=code(ep['fixed_condition'],16 if platform=='android'else 20)
 assert condition[-1].mnemonic=='b'and int(condition[-1].op_str[1:],0)==ep['fixed_tick']
 assert any(i.mnemonic=='bl'and int(i.op_str[1:],0)==ep['get_manager']for i in condition)
 assert not any(i.mnemonic in('ldr','mov')and i.op_str.startswith('x0, [')for i in condition)
 executor=code(ep['fixed_executor'],24)
 assert [(i.mnemonic,i.op_str)for i in executor[:3]]==[
  ('ldr','x8, [x19, #0x60]'),('cbz','x8, #'+hex(ep['fixed_executor']+16)),('blr','x8')]
 assert executor[3].mnemonic in('tbz','cbz')and int(executor[3].op_str.rsplit('#',1)[1],0)==ep['condition_exit']
 methods={n:original.method(*v)for n,v in SELECT.items()}
 assert methods['animator_graph']['return']=='System.Void'and methods['animator_graph']['parameters'][0]['type']=='UnityEngine.Playables.PlayableGraph&'
 assert methods['legacy_state_count']['return']=='System.Int32'
 # The original typed getter returns the actual static registry. Its original
 # final loads prove the static storage field at offset zero; callers never
 # guess an Il2CppClass layout or enumerate only the selected actors.
 actor_fields=original.fields('VL.Core.VLActorController')
 assert actor_fields['_actorControllers']['offset']==0
 assert actor_fields['_extensions']['offset']==0x40
 assert actor_fields['_animator']['offset']==0x30
 getter=methods['actor_registry'];assert getter['static'] and getter['return']=='System.Collections.Generic.IReadOnlyList`1<VL.IVLActorController>'
 getter_start=int(getter['rva'],0);getter_offset=original.offset(getter_start)
 getter_code=[]
 for i in md.disasm(original.b[getter_offset:getter_offset+160],getter_start):
  getter_code.append(i)
  if i.mnemonic=='ret':break
 assert getter_code[-1].mnemonic=='ret'
 getter_loads=[(i.mnemonic,i.op_str)for i in getter_code]
 assert ('ldr','x8, [x8, #0xb8]')in getter_loads and ('ldr','x0, [x8]')in getter_loads
 getter['body']=b''.join(i.bytes for i in getter_code).hex()
 # Retain original lazy metadata linkage addresses so an ARM test can execute
 # this getter's unchanged instructions with its already-initialized class.
 registers={};getter_link={}
 for i in getter_code:
  if i.mnemonic=='adrp':
   reg,value=i.op_str.split(', ');registers[reg]=int(value[1:],0)
  elif i.mnemonic=='add':
   match=re.fullmatch(r'(x\d+), (x\d+), #(0x[0-9a-f]+|\d+)',i.op_str)
   if match and match[2]in registers:registers[match[1]]=registers[match[2]]+int(match[3],0)
  elif i.mnemonic=='ldrb' and i.op_str.startswith('w8, [x19, #'):
   getter_link['initialized_flag']=hex(registers['x19']+int(i.op_str.split('#')[1][:-1],0))
  elif i.mnemonic=='ldr' and i.op_str.startswith('x20, [x20, #'):
   getter_link['class_link_slot']=hex(registers['x20']+int(i.op_str.split('#')[1][:-1],0));getter_link['indirect_class_cell']=True
  elif i.mnemonic=='tbnz' and platform=='ios':
   getter_link['class_link_slot']=hex(registers['x20']);getter_link['indirect_class_cell']=False
  if i.mnemonic=='tbnz':break
 assert len(getter_link)==3
 types={}
 for alias,name in TYPES.items():
  tid=original.type_id(name);row=original.types[tid][1];index=row[2];pointer=original.qword(original.type_table+index*8)
  bits=struct.unpack_from('<I',original.b,original.offset(pointer)+8)[0];kind=bits>>16&255
  assert original.type_name(index)==name and kind==(17 if alias in('fixed_update_type','animation_output_type')else 18)
  types[alias]={'type':name,'rva':hex(pointer),'prefix':original.b[original.offset(pointer):original.offset(pointer)+16].hex(),
                'kind':kind,'type_definition':tid,'metadata_type_index':index}
 fields=original.fields('UnityEngine.LowLevel.PlayerLoopSystemInternal')
 assert {k:v['offset']-16 for k,v in fields.items()}=={'type':0,'updateDelegate':8,'updateFunction':16,'loopConditionFunction':24,'numSubSystems':32}
 native={name:{'rva':hex(ep[name]),'prefix':raw(ep[name],16).hex(),
               'body':b''.join(i.bytes for i in (condition if name=='fixed_condition'else executor if name=='fixed_executor'else bounded(ep[name]))).hex()}
         for name in NATIVE_BINDINGS}
 # Every native binding is a versioned OutputHandle plus its actual owning
 # GraphHandle. Registration itself is conditional, so GetTarget==Animator
 # alone may not prove membership in this authoritative bound-output list.
 binding_code={name:[(i.mnemonic,i.op_str)for i in md.disasm(bytes.fromhex(native[name]['body']),ep[name])]
               for name in('animator_register','animator_record_ctor','animator_append')}
 bc=binding_code['animator_register']
 assert ('ldrb','w8, [x0, #0x194]')in bc and ('ldr','x8, [x0, #0x178]')in bc
 assert ('ldr','x9, [x19, #0x168]')in bc and ('add','x21, x19, #0x168')in bc
 assert ('add','x9, x9, #0x28')in bc and ('ldr','x10, [x10, #0x28]')in bc
 bc=binding_code['animator_record_ctor']
 assert ('str','x0, [x19]')in bc and ('str','w1, [x19, #8]')in bc
 assert ('str','x8, [x19, #0x10]')in bc and ('str','w9, [x19, #0x18]')in bc
 bc=binding_code['animator_append']
 assert ('ldp','x21, x8, [x0, #0x10]')in bc and ('cmp','x22, x8, lsr #1')in bc
 assert ('str','x22, [x20, #0x10]')in bc and ('mov','w9, #0x28')in bc
 assert original.fields('UnityEngine.Object')['m_CachedPtr']['offset']==0x10
 return {'schema':1,'platform':platform,'director_registry':director_registry(original,engine,offset,platform),'sources':{'engine_sha256':hashlib.sha256(engine).hexdigest(),
          'native_sha256':hashlib.sha256(original.b).hexdigest(),'metadata_sha256':hashlib.sha256(original.m).hexdigest()},
         'methods':methods,'types':types,'registry_slot':hex(ep['registry_slot']),'native':native,
         'actors':{'registry_field':actor_fields['_actorControllers'],'extensions_field':actor_fields['_extensions'],
                   'animator_field':actor_fields['_animator'],'active_requires_original_game_object_hierarchy':True,
                   'active_swing_must_be_in_selected_binder':True,'registry_getter_linkage':getter_link},
         'animator_bindings':{'cached_ptr':0x10,'data':0x168,'count':0x178,'count_bytes':8,'capacity':0x180,
               'capacity_bytes':8,'capacity_shift':1,'registration_flags':0x194,'registration_suspended_bit':4,
               'record_bytes':0x28,'output_handle':0,'output_version':8,'graph_handle':0x10,'graph_version':0x18},
         'loop':{'value_bytes':40,'fields':{k:v['offset']-16 for k,v in fields.items()},'condition_abi':'bool(void)',
                 'condition_false_skips_all_children':True,'exit_rva':hex(ep['condition_exit'])},
         'registry':{'map':0x40,'data':0,'mask':8,'occupied':12,'free':16,'bucket_bytes':24,'status':0,'key':8,'rtti':16,
                     'rtti_name':16,'rtti_class_id':40,'articulation_class_id':171741748,
                     'absence_requires_complete_registered_map_and_native_lookup':True}}

def render(profiles):
 lines=['namespace idoly_mp4_world {','struct CodeBinding {uintptr_t rva;uint8_t prefix[16];};',
 'struct TypeBinding {uintptr_t rva;uint8_t prefix[16];uint32_t kind,definition;};',
 'struct WorldProfile {uintptr_t registry_slot;CodeBinding '+','.join([*SELECT,*NATIVE_BINDINGS])+';TypeBinding '+','.join(TYPES)+';};']
 for platform in('android','ios'):
  p=profiles[platform];lines += ['inline constexpr WorldProfile '+platform+'_world_profile={'+p['registry_slot']+',']
  for name in [*SELECT,*NATIVE_BINDINGS]:
   row=p['methods'if name in SELECT else'native'][name];bs=','.join(hex(b)for b in bytes.fromhex(row['prefix']))
   lines += ['    {'+row['rva']+',{'+bs+'}}, // '+name]
  for name in TYPES:
   row=p['types'][name];bs=','.join(hex(b)for b in bytes.fromhex(row['prefix']))
   lines += ['    {'+row['rva']+',{'+bs+'},'+str(row['kind'])+','+str(row['type_definition'])+'}, // '+name]
  lines+=['};']
 return '\n'.join([*lines,render_director(profiles),'} // namespace idoly_mp4_world',''])

def render_scope(profiles,source=None):
 source=source or (NATIVE/'mp4_engine_clock.hpp').read_text();a='// BEGIN_ORIGINAL_WORLD_PROFILE';z='// END_ORIGINAL_WORLD_PROFILE'
 block=a+'\n'+render(profiles).rstrip()+'\n'+z
 if a not in source:
  marker='// A normal-MV export never needs';assert marker in source;return source.replace(marker,block+'\n\n'+marker,1)
 assert source.count(a)==source.count(z)==1
 return re.sub(re.escape(a)+r'[\s\S]*?'+re.escape(z),lambda _:block,source)

def main():
 p=argparse.ArgumentParser();p.add_argument('--originals',type=Path,required=True);p.add_argument('--header',type=Path,default=NATIVE/'mp4_engine_clock.hpp');p.add_argument('--proof',type=Path,required=True);args=p.parse_args()
 profiles={pl:build(args.originals,pl)for pl in('android','ios')}
 args.header.parent.mkdir(parents=True,exist_ok=True);args.header.write_text(render_scope(profiles))
 args.proof.parent.mkdir(parents=True,exist_ok=True);args.proof.write_text(json.dumps({'schema':1,'platforms':profiles},indent=2)+'\n')
 print('PASS pinned original world queries, complete registry schema, and fixed-loop condition; no game/GPU execution claim')
if __name__=='__main__':main()
