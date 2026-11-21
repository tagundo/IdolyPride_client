#!/usr/bin/env python3
"""Pin original native animation/director loop phases and their typed slots.

Runs each unchanged native default-loop initializer with bounded symbolic class
and allocation inputs. This proves dispatch provenance, not game/GPU execution.
"""
import argparse,json,re,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn import arm64_const as R
from audit_mp4_world import whole
ROOT=Path(__file__).resolve().parents[1]
HEADER=ROOT/'client-presentation/native/mp4_engine_clock.hpp'
PHASES=[('sample','Initialization','DirectorSampleTime',0x3f8),('update','Update','DirectorUpdate',0x5f0),
 ('begin','PreLateUpdate','DirectorUpdateAnimationBegin',0x600),('legacy','PreLateUpdate','LegacyAnimationUpdate',0x608),
 ('end','PreLateUpdate','DirectorUpdateAnimationEnd',0x610),('deferred','PreLateUpdate','DirectorDeferredEvaluate',0x618),
 ('late','PostLateUpdate','DirectorLateUpdate',0x660),('render','PostLateUpdate','DirectorRenderImage',0x6f8)]
PINS={
 'android':dict(cache_begin=0x809788,cache_end=0x80ccd0,lookups=(0x73985c,0x739660,0x73997c),
  setup=0x567084,setup_bytes=0x600,cache_getter=0x7fa88c,initializer=0x63f808,exit=0x63fb50,
  buffer_slot=0x14dda18,registry=0x14591a0,indirect=True,executor=0x640004,
  writer_begin=0x72f128,writer_end=0x72f1ac,legacy_writer_begin=0x8a51ac,legacy_writer_end=0x8a51dc,
  callbacks=[0x72f6e0,0x72f718,0x72f790,0x8a5208,0x72f7a0,0x72f728,0x72f744,0x72f754],
  lengths=[12,16,16,36,16,28,16,60],sample_region=0x72f6e0,sample_bytes=0x42c,
  manager_slot=0x14e64c0,time_getter=0x6225e8,clock_info=0x731b80),
 'ios':dict(cache_begin=0xe5e46c,cache_end=0xe619d4,lookups=(0xdcf284,0xdcf494),
  setup=0xbf2050,setup_bytes=0x600,cache_getter=0xe4e96c,initializer=0xcca45c,exit=0xcca7b0,
  buffer_slot=0xa8a0e18,registry=0xa939448,indirect=False,executor=0xccac60,
  writer_begin=0xdc5154,writer_end=0xdc51d4,legacy_writer_begin=0xefcbf0,legacy_writer_end=0xefcc18,
  callbacks=[0xdc5618,0xdc5650,0xdc56d8,0xefcc40,0xdc56e8,0xdc5660,0xdc5688,0xdc5698],
  lengths=[12,16,16,40,16,40,16,64],sample_region=0xdc5618,sample_bytes=0x488,
  manager_slot=0xa8a8e00,time_getter=0xcad690,clock_info=0xdc7ae8)}

def build(originals,platform):
 original,b,off=whole(originals,platform);pin=PINS[platform];md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
 def raw(a,n):return b[off(a):off(a)+n]
 def text(a):
  at=off(a);return b[at:b.index(b'\0',at,at+500)].decode()
 def records(a,n):return [{'rva':hex(i.address),'bytes':i.bytes.hex(),'instruction':i.mnemonic+' '+i.op_str}for i in md.disasm(raw(a,n),a)]
 # Reconstruct exact type labels from original cache constructor inputs, then
 # execute the actual native loop initializer to associate them with slots.
 registers={};cache={}
 for i in md.disasm(raw(pin['cache_begin'],pin['cache_end']-pin['cache_begin']),pin['cache_begin']):
  a=i.op_str.split(', ')
  if i.mnemonic=='adrp':registers[a[0]]=int(a[1][1:],0)
  elif i.mnemonic in('add','sub')and len(a)==3 and a[2].startswith('#')and isinstance(registers.get(a[1]),int):
   registers[a[0]]=registers[a[1]]+(1 if i.mnemonic=='add'else-1)*int(a[2][1:],0)
  elif i.mnemonic=='mov'and len(a)==2:registers[a[0]]=registers.get(a[1])
  elif i.mnemonic=='bl':
   if int(i.op_str[1:],0)in pin['lookups']:
    values=[registers.get('x'+str(k))for k in range(3)]
    registers['x0']={'rva':hex(i.address),'lookup':i.op_str,'arguments':[text(v)if isinstance(v,int)else v for v in values]}
   else:registers['x0']=None
  elif i.mnemonic=='str'and a[0]=='x0'and '[x8'in i.op_str and isinstance(registers.get('x0'),dict):
   match=re.search(r'#(0x[0-9a-f]+|\d+)',i.op_str);cache[int(match[1],0)if match else 0]={**registers['x0'],'store':hex(i.address)}
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);pages=set()
 def mapped(a,n,content=None):
  for page in range(a&~4095,(a+n+4095)&~4095,4096):
   if page not in pages:u.mem_map(page,4096);pages.add(page)
  if content is not None:u.mem_write(a,content)
 for a,n in [(pin['initializer']&~4095,0x3000),(pin['setup']&~4095,0x2000)]:mapped(a,n,raw(a,n))
 for a in[pin['buffer_slot'],pin['registry']]:mapped(a,0x2000)
 for a in[0x18000000,0x19000000,0x20000000,0x21000000]:mapped(a,0x10000)
 u.mem_write(pin['buffer_slot'],struct.pack('<Q',0x18000000))
 registry=0x20000000 if pin['indirect']else pin['registry']
 if pin['indirect']:u.mem_write(pin['registry'],struct.pack('<Q',registry))
 for at in range(0,0x1000,8):
  u.mem_write(0x19000000+at,struct.pack('<Q',0x19000000+at));u.mem_write(registry+at,struct.pack('<Q',0x20000000+at))
 calls=[]
 def hook(machine,pc,size,unused):
  ins=next(md.disasm(bytes(machine.mem_read(pc,4)),pc))
  if ins.mnemonic=='bl':
   target=int(ins.op_str[1:],0);calls.append(target)
   if target==pin['setup']:return
   machine.reg_write(R.UC_ARM64_REG_X0,0x19000000 if target==pin['cache_getter']else 1)
   machine.reg_write(R.UC_ARM64_REG_PC,pc+4)
 u.hook_add(UC_HOOK_CODE,hook);u.reg_write(R.UC_ARM64_REG_SP,0x2100f000);u.reg_write(R.UC_ARM64_REG_LR,pin['exit'])
 u.emu_start(pin['initializer'],pin['exit'],count=50000)
 assert u.reg_read(R.UC_ARM64_REG_PC)==pin['exit']and pin['setup']in calls
 nodes=[]
 for index in range(133):
  node=bytes(u.mem_read(0x18000000+index*0x68,0x68));typ=struct.unpack_from('<Q',node,0x30)[0]
  slot=struct.unpack_from('<Q',node,0x58)[0];condition=struct.unpack_from('<Q',node,0x60)[0]
  nodes.append({'index':index,'class':cache.get(typ-0x19000000),'slot':slot-registry if slot else None,'condition':condition})
 native_animation={n['class']['arguments'][-1]for n in nodes if n['class']
                   and any(word in str(n['class']['arguments'][-1])for word in('Director','AnimationUpdate'))}
 fixed_animation={'FixedUpdate/'+name for name in('DirectorFixedSampleTime','DirectorFixedUpdate',
                  'DirectorFixedUpdatePostPhysics','LegacyFixedAnimationUpdate')}
 assert native_animation=={parent+'/'+name for _,parent,name,_ in PHASES}|fixed_animation,\
        ('unclassified_native_animation_phase',platform,native_animation)
 # Execute slot writers' straight-line original address computations. A slot
 # has one exact callback wrapper, and every wrapper overwrites its arguments.
 writers={}
 for start,end in [(pin['writer_begin'],pin['writer_end']),(pin['legacy_writer_begin'],pin['legacy_writer_end'])]:
  registers={}
  for i in md.disasm(raw(start,end-start),start):
   a=i.op_str.split(', ')
   if i.mnemonic=='adrp':registers[a[0]]=int(a[1][1:],0)
   elif i.mnemonic=='add'and len(a)==3 and a[2].startswith('#')and isinstance(registers.get(a[1]),int):registers[a[0]]=registers[a[1]]+int(a[2][1:],0)
   elif i.mnemonic=='ldr'and platform=='android'and i.op_str=='x8, [x8, #0x1a0]':registers['x8']=registry
   elif i.mnemonic=='ldr'and platform=='android'and i.op_str=='x10, [x10, #0x1a0]':registers['x10']=registry
   elif i.mnemonic=='str':
    match=re.fullmatch(r'(x\d+), \[(x\d+), #(0x[0-9a-f]+|\d+)\]',i.op_str)
    if match and isinstance(registers.get(match[1]),int)and isinstance(registers.get(match[2]),int):
     slot=registers[match[2]]+int(match[3],0)-registry
     writers[slot]={'rva':hex(i.address),'target':registers[match[1]],'instructions':records(start,i.address+4-start)}
 rows=[]
 for index,(alias,parent,name,slot)in enumerate(PHASES):
  full='UnityEngine.PlayerLoop.'+parent+'/'+name
  found=[n for n in nodes if n['class']and n['class']['arguments']==['UnityEngine.CoreModule.dll','UnityEngine.PlayerLoop',parent+'/'+name]]
  assert len(found)==1 and found[0]['slot']==slot and found[0]['condition']==0,(platform,full,found)
  assert slot in writers,(platform,hex(slot),'native_callback_writer_missing')
  writer=writers[slot];entry=pin['callbacks'][index];assert writer['target']==entry
  tid=original.type_id(full);type_index=original.types[tid][1][2];pointer=original.qword(original.type_table+type_index*8)
  prefix=original.b[original.offset(pointer):original.offset(pointer)+16];assert prefix[10]==17
  rows.append({'alias':alias,'type':full,'name':name,'namespace':'','loop_index':found[0]['index'],'slot':hex(slot),
   'type_cache':found[0]['class'],'writer':writer,
   'callback':{'rva':hex(entry),'prefix':raw(entry,16).hex(),'body':raw(entry,pin['lengths'][index]).hex(),'native_abi':'void(void)'},
   'type_binding':{'rva':hex(pointer),'prefix':prefix.hex(),'kind':17,'definition':tid}})
 assert [r['loop_index']for r in rows]==sorted(r['loop_index']for r in rows)
 sample_fixture={k:hex(pin[k])for k in['sample_region','manager_slot','time_getter','clock_info']}
 sample_fixture['bytes']=raw(pin['sample_region'],pin['sample_bytes']).hex()
 sample_fixture['phase_dispatch']=next(i.op_str[1:]for i in md.disasm(bytes.fromhex(rows[1]['callback']['body']),pin['callbacks'][1])if i.mnemonic=='b')
 sample_fixture['stubbed_callbacks']=[]
 for i in[3,5,7]:
  callback=rows[i]['callback']
  for ins in md.disasm(bytes.fromhex(callback['body']),int(callback['rva'],0)):
   if ins.mnemonic in('bl','b'):sample_fixture['stubbed_callbacks'].append(ins.op_str[1:])
 dispatch=records(pin['executor'],24)
 assert dispatch[0]['instruction']=='ldr x8, [x24, #0xc0]'
 assert any(r['instruction']=='blr x8'for r in dispatch)
 assert not any(r['instruction'].startswith(('cmp ','ldr w','ldr d','ldr s','ldrb '))for r in dispatch)
 return {'schema':1,'platform':platform,'sources':{'engine_sha256':__import__('hashlib').sha256(b).hexdigest()},
  'registry':hex(pin['registry']),'registry_indirect':pin['indirect'],'phases':rows,
  'all_native_animation_phases':sorted(native_animation),'fixed_root_owned_phases':sorted(fixed_animation),
  'sample_fixture':sample_fixture,
  'executor':{'rva':hex(pin['executor']),'prefix':raw(pin['executor'],16).hex(),'instructions':records(pin['executor'],40)},
  'initializer':{'rva':hex(pin['initializer']),'bytes':raw(pin['initializer'],pin['exit']-pin['initializer']).hex()},
  'type_setup':{'rva':hex(pin['setup']),'bytes':raw(pin['setup'],pin['setup_bytes']).hex()}}

def render(profiles):
 lines=['namespace idoly_mp4_world {','struct AnimationPhaseBinding {const char* name;uintptr_t slot;CodeBinding callback;TypeBinding type;};',
        'struct AnimationProfile {uintptr_t registry;bool indirect;CodeBinding executor;AnimationPhaseBinding phases[8];};']
 for platform in('android','ios'):
  p=profiles[platform];bs=lambda s:','.join(hex(v)for v in bytes.fromhex(s))
  lines+=['inline constexpr AnimationProfile '+platform+'_animation_profile={'+p['registry']+','+str(p['registry_indirect']).lower()+',',
          '    {'+p['executor']['rva']+',{'+bs(p['executor']['prefix'])+'}}, {']
  for r in p['phases']:
   c=r['callback'];t=r['type_binding'];lines+=['    {"'+r['name']+'",'+r['slot']+',{'+c['rva']+',{'+bs(c['prefix'])+'}},{'+t['rva']+',{'+bs(t['prefix'])+'},17,'+str(t['definition'])+'}},']
  lines+=['}};']
 return '\n'.join([*lines,'} // namespace idoly_mp4_world',''])

def render_scope(profiles,source=None):
 source=source or HEADER.read_text();a='// BEGIN_ORIGINAL_ANIMATION_LOOP_PROFILE';z='// END_ORIGINAL_ANIMATION_LOOP_PROFILE';block=a+'\n'+render(profiles).rstrip()+'\n'+z
 if a not in source:return source+'\n\n'+block+'\n'
 assert source.count(a)==source.count(z)==1
 return re.sub(re.escape(a)+r'[\s\S]*?'+re.escape(z),lambda _:block,source)

def main():
 p=argparse.ArgumentParser();p.add_argument('--originals',type=Path,required=True);p.add_argument('--header',type=Path,default=HEADER);p.add_argument('--proof',type=Path,required=True);a=p.parse_args()
 profiles={pl:build(a.originals,pl)for pl in('android','ios')};a.header.write_text(render_scope(profiles));a.proof.write_text(json.dumps({'schema':1,'platforms':profiles},indent=2)+'\n')
 print('PASS original typed eight-phase native dispatch; no game/GPU execution claim')
if __name__=='__main__':main()
