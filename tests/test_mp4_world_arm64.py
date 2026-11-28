"""Execute production FixedGate plus unchanged original fixed/RTTI instructions.

This is CPU execution of the native boundary and its typed data fixtures, not
an actual Unity PlayerLoop, physics scene, prefab, or GPU render.
"""
import importlib.util,json,os,struct,subprocess
from pathlib import Path
import pytest
uc=pytest.importorskip('unicorn')
from unicorn import arm64_const as R
ROOT=Path(__file__).resolve().parents[1]
W=json.loads((ROOT/'tests/mp4_world_original_fixture.json').read_text())['platforms']
C=json.loads((ROOT/'client-presentation/native/mp4_engine_clock_profile.json').read_text())['platforms']
MANAGER,STORAGE,STOP,STACK=0x20000000,0x21000000,0x30000000,0x40000000
REGISTRY,BUCKETS,RTTI=0x22000000,0x23000000,0x24000000
WRAPPER=r'''
#include "mp4_engine_clock.hpp"
#include <new>
extern "C" void*memset(void*p,int v,size_t n){auto*b=(volatile unsigned char*)p;while(n--)*b++=(unsigned char)v;return p;}
extern "C" void*memcpy(void*p,const void*s,size_t n){auto*b=(volatile unsigned char*)p;auto*a=(const volatile unsigned char*)s;while(n--)*b++=*a++;return p;}
static bool main_thread=true;
static bool owner(){return main_thread;}
using idoly_mp4_world::FixedGate;
extern "C" __attribute__((visibility("default"))) int construct(void*p){auto*g=new(p)FixedGate;return g->install({reinterpret_cast<bool(*)()>(ORIGINAL_CONDITION),owner});}
extern "C" __attribute__((visibility("default"))) int acquire(void*p,uint64_t n){return static_cast<FixedGate*>(p)->acquire(n);}
extern "C" __attribute__((visibility("default"))) int call(void*p){return static_cast<FixedGate*>(p)->native_condition();}
extern "C" __attribute__((visibility("default"))) int release(void*p,uint64_t n){static_cast<FixedGate*>(p)->release(n);return 1;}
extern "C" __attribute__((visibility("default"))) int healthy(void*p,uint64_t n){return static_cast<FixedGate*>(p)->healthy(n);}
extern "C" __attribute__((visibility("default"))) int thread(void*,uint32_t n){main_thread=n!=0;return 1;}
extern "C" __attribute__((visibility("default"))) bool condition_adapter(){return reinterpret_cast<FixedGate*>(0x21000000)->native_condition();}
'''
def compiler():
 p=Path(os.environ.get('IDOLY_MP4_NDK_CLANG','/workspace/.setup/android-sdk/ndk/26.3.11579264/toolchains/llvm/prebuilt/linux-x86_64/bin/clang++'))
 if not p.is_file():pytest.skip('Actual ARM64 compiler required')
 return p
@pytest.fixture(scope='module',params=['android','ios'])
def native(request,tmp_path_factory):
 pl=request.param;d=tmp_path_factory.mktemp('world-arm64-'+pl);s=d/'gate.cpp';b=d/'gate.so';s.write_text(WRAPPER)
 r=subprocess.run([str(compiler()),'--target=aarch64-linux-android26','-std=c++17','-O2','-mno-outline-atomics','-fPIC','-fno-exceptions','-fno-rtti','-ffreestanding','-fno-builtin','-fvisibility=hidden','-nostdlib','-shared','-Wl,-Bsymbolic','-Wl,--no-undefined','-Wl,-Ttext=0x10000000','-DORIGINAL_CONDITION='+W[pl]['native']['fixed_condition']['rva'],'-I',str(ROOT/'client-presentation/native'),str(s),'-o',str(b)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 return pl,b.read_bytes()
class Engine:
 def __init__(self,native):
  self.platform,binary=native;self.profile=W[self.platform];self.clock=C[self.platform]
  self.m=uc.Uc(uc.UC_ARCH_ARM64,uc.UC_MODE_ARM);self.pages=set();self.symbols={};self.calls=0
  phoff=struct.unpack_from('<Q',binary,32)[0];psz,pcount=struct.unpack_from('<HH',binary,54)
  for i in range(pcount):
   kind,_,off,a,_,size,mem,_=struct.unpack_from('<II6Q',binary,phoff+i*psz)
   if kind==1:self.map(a,binary[off:off+size],mem)
  so=struct.unpack_from('<Q',binary,40)[0];ss,sn=struct.unpack_from('<HH',binary,58);sections=[struct.unpack_from('<II4QII2Q',binary,so+i*ss)for i in range(sn)]
  for sec in sections:
   if sec[1]!=2:continue
   st=sections[sec[6]];names=binary[st[4]:st[4]+st[5]]
   for off in range(sec[4],sec[4]+sec[5],sec[9]):
    name,_,_,defined,value,_=struct.unpack_from('<IBBHQQ',binary,off)
    if defined:self.symbols[names[name:].split(b'\0')[0].decode()]=value
  for r in self.profile['native'].values():self.map(int(r['rva'],16),bytes.fromhex(r['body']))
  for r in self.clock['bindings'].values():self.map(int(r['rva'],16),bytes.fromhex(r['body']))
  rg=self.clock['registry_getter'];self.map(int(rg['rva'],16),bytes.fromhex(rg['bytes']))
  for r in self.clock['kernel_constants']:self.map(int(r['rva'],16),bytes.fromhex(r['bytes']))
  for a,n in [(MANAGER,4096),(STORAGE,4096),(STACK,65536),(REGISTRY,4096),(BUCKETS,4096),(RTTI,4096)]:self.map(a,bytes(n))
  self.map(STOP,bytes.fromhex('c0035fd6'))
  self.map(int(self.clock['registry_slot_rva'],16),struct.pack('<Q',MANAGER))
  self.map(int(self.profile['registry_slot'],16),struct.pack('<Q',REGISTRY))
  for f,v in [(0x30,59.96),(0x38,59.94),(0x40,99.96),(0x60,60.1),(0x68,60.08),(0x70,100.1),(0x90,60.1),(0x98,60.08),(0xa0,100.1),(0xe0,940.),(0xe8,900.),(0xf0,-50.)]:self.write(MANAGER+f,'d',v)
  for f,v in [(0x48,.02),(0x4c,.02),(0x50,.02),(0x58,50.),(0xfc,1.),(0x100,.3333)]:self.write(MANAGER+f,'f',v)
  a=int(self.profile['native']['fixed_condition']['rva'],16)
  self.m.hook_add(uc.UC_HOOK_CODE,lambda *args:setattr(self,'calls',self.calls+1),begin=a,end=a)
  assert self.call('construct',STORAGE)==1
 def map(self,a,b,size=None):
  n=max(len(b),size or 0)
  for p in range(a&~4095,(a+n+4095)&~4095,4096):
   if p not in self.pages:self.m.mem_map(p,4096);self.pages.add(p)
  self.m.mem_write(a,b)
 def write(self,a,t,v):self.m.mem_write(a,struct.pack('<'+t,v))
 def read(self,a,t):return struct.unpack('<'+t,self.m.mem_read(a,struct.calcsize(t)))[0]
 def call(self,fn,*args):
  for i,a in enumerate(args):self.m.reg_write(R.UC_ARM64_REG_X0+i,a)
  self.m.reg_write(R.UC_ARM64_REG_SP,STACK+0xff00);self.m.reg_write(R.UC_ARM64_REG_X30,STOP)
  self.m.emu_start(self.symbols[fn]if isinstance(fn,str)else fn,STOP,count=100000)
  assert self.m.reg_read(R.UC_ARM64_REG_PC)==STOP
  return self.m.reg_read(R.UC_ARM64_REG_X0)

def test_actual_gate_holds_original_fixed_kernel_and_resumes_it(native):
 e=Engine(native);start=e.read(MANAGER+0x30,'d')
 assert e.call('call',STORAGE)==1 and e.calls==1
 assert e.read(MANAGER+0x30,'d')>start
 assert e.call('acquire',STORAGE,7)==1
 before=bytes(e.m.mem_read(MANAGER,0x108))
 for _ in range(5):assert e.call('call',STORAGE)==0
 assert e.calls==1 and bytes(e.m.mem_read(MANAGER,0x108))==before
 assert e.call('healthy',STORAGE,7)==1
 e.call('release',STORAGE,8);assert e.call('call',STORAGE)==0 # foreign lease cannot release
 e.call('release',STORAGE,7);assert e.call('call',STORAGE)==1 and e.calls==2
 assert e.read(MANAGER+0x30,'d')>struct.unpack_from('<d',before,0x30)[0]

def test_wrong_thread_forwards_original_and_poisons_rewind_permission(native):
 e=Engine(native);assert e.call('acquire',STORAGE,9)==1;e.call('thread',STORAGE,0)
 assert e.call('call',STORAGE)==1 and e.calls==1
 assert e.call('healthy',STORAGE,9)==0
 e.call('thread',STORAGE,1);e.call('release',STORAGE,9);assert e.call('acquire',STORAGE,10)==0

def test_unchanged_native_executor_condition_skips_the_whole_child_tree(native):
 e=Engine(native);entry=int(e.profile['native']['fixed_executor']['rva'],16)
 child=entry+16;exit_rva=int(e.profile['loop']['exit_rva'],16)
 # False exits may cross a page; stop before executing its original epilogue.
 e.map(exit_rva,bytes.fromhex('c0035fd6'))
 e.write(STORAGE+0x400+0x60,'Q',e.symbols['condition_adapter'])
 def path():
  hit=[]
  def stop(machine,address,size,unused):
   if address in(child,exit_rva):hit.append(address);machine.emu_stop()
  hook=e.m.hook_add(uc.UC_HOOK_CODE,stop)
  e.m.reg_write(R.UC_ARM64_REG_X19,STORAGE+0x400)
  e.m.reg_write(R.UC_ARM64_REG_SP,STACK+0xff00);e.m.reg_write(R.UC_ARM64_REG_X30,STOP)
  try:e.m.emu_start(entry,STOP,count=100000)
  finally:e.m.hook_del(hook)
  assert len(hit)==1
  return hit[0]
 assert path()==child and e.calls==1
 assert e.call('acquire',STORAGE,73)==1
 before=bytes(e.m.mem_read(MANAGER,0x108))
 assert path()==exit_rva and e.calls==1
 assert bytes(e.m.mem_read(MANAGER,0x108))==before
 e.call('release',STORAGE,73)
 assert path()==child and e.calls==2

def native_hash(v):
 v=(v+(v<<12)+0x7ed55d16)&0xffffffff;v^=v>>19;v^=0xc761c23c;v=(v+(v<<5))&0xffffffff
 v=((v+0xe9f8cc1d)&0xffffffff)^((0xaccf6200+(v<<9))&0xffffffff)
 v=(v+(v<<3)+0xfd7046c5)&0xffffffff;return (v^(v>>16)^0xb55a4f09)&0xffffffff

def test_unchanged_original_registry_lookup_distinguishes_absence_from_registered_class(native):
 e=Engine(native);mask=15*8;e.write(REGISTRY+0x40,'Q',BUCKETS);e.write(REGISTRY+0x48,'I',mask)
 for i in range(16):e.write(BUCKETS+i*24,'I',0xffffffff)
 values={54:RTTI,50:RTTI+0x100,183:RTTI+0x200,143:RTTI+0x300}
 for key,value in values.items():
  h=native_hash(key);index=h&mask;probe=8
  while e.read(BUCKETS+index*3,'I')!=0xffffffff:index=(index+probe)&mask;probe+=8
  at=BUCKETS+index*3;e.write(at,'I',h&0xfffffffc);e.write(at+8,'I',key);e.write(at+16,'Q',value)
 entry=int(e.profile['native']['lookup']['rva'],16)
 for key,value in values.items():assert e.call(entry,key)==value
 assert e.call(entry,171741748)==0
 # The same exact native getter must see a registered Articulation class.
 key=171741748;h=native_hash(key);index=h&mask;probe=8
 while e.read(BUCKETS+index*3,'I')!=0xffffffff:index=(index+probe)&mask;probe+=8
 at=BUCKETS+index*3;e.write(at,'I',h&0xfffffffc);e.write(at+8,'I',key);e.write(at+16,'Q',RTTI+0x400)
 assert e.call(entry,key)==RTTI+0x400

def test_original_actor_registry_getter_reads_the_real_static_registry(native):
 e=Engine(native);row=e.profile['methods']['actor_registry'];link=e.profile['actors']['registry_getter_linkage']
 entry=int(row['rva'],16);e.map(entry,bytes.fromhex(row['body']))
 e.map(int(link['initialized_flag'],16),b'\x01')
 cell,klass,statics,actors=STORAGE+0x500,STORAGE+0x600,STORAGE+0x800,STORAGE+0xa00
 e.map(int(link['class_link_slot'],16),struct.pack('<Q',cell if link['indirect_class_cell']else klass))
 e.write(cell,'Q',klass);e.write(klass+0xb8,'Q',statics);e.write(statics,'Q',actors)
 assert e.call(entry)==actors
 # Runtime list replacement is observed; no cached selected-cast substitute.
 e.write(statics,'Q',actors+0x100)
 assert e.call(entry)==actors+0x100

def test_original_animator_binding_constructor_and_append_preserve_all_versioned_members(native):
 e=Engine(native);output=0x27000000;graph=output+0x1000;output_slot=output+0x2000;graph_slot=output+0x3000
 e.map(output,bytes(0x4000));e.write(output+0x44,'i',12)
 helpers=(0x732258,0x73247c,0x72ab0c)if e.platform=='android'else(0xdc8200,0xdc8454,0xdc0bc8)
 for address in helpers:e.map(address,bytes.fromhex('c0035fd6'))
 def hook(machine,pc,size,unused):
  if pc==helpers[0]:
   assert machine.reg_read(R.UC_ARM64_REG_X0)==output
   machine.reg_write(R.UC_ARM64_REG_X0,output_slot);machine.reg_write(R.UC_ARM64_REG_X1,7)
  elif pc==helpers[1]:
   assert machine.reg_read(R.UC_ARM64_REG_X0)==output
   machine.reg_write(R.UC_ARM64_REG_X0,graph)
  elif pc==helpers[2]:
   assert machine.reg_read(R.UC_ARM64_REG_X0)==graph
   result=machine.reg_read(R.UC_ARM64_REG_X8);e.write(result,'Q',graph_slot);e.write(result+8,'I',9)
 e.m.hook_add(uc.UC_HOOK_CODE,hook)
 record=STORAGE+0x400;vector=STORAGE+0x600;items=STORAGE+0x800
 ctor=int(e.profile['native']['animator_record_ctor']['rva'],16)
 append=int(e.profile['native']['animator_append']['rva'],16)
 e.call(ctor,record,output)
 assert (e.read(record,'Q'),e.read(record+8,'I'),e.read(record+16,'Q'),e.read(record+24,'I'),e.read(record+32,'I'))==(output_slot,7,graph_slot,9,12)
 e.write(vector,'Q',items);e.write(vector+16,'Q',0);e.write(vector+24,'Q',4) # encoded capacity2
 e.call(append,vector,record)
 assert e.read(vector+16,'Q')==1 and e.read(vector+24,'Q')==4
 assert bytes(e.m.mem_read(items,36))==bytes(e.m.mem_read(record,36))
 e.write(record,'Q',output_slot+0x100);e.write(record+16,'Q',graph_slot+0x100)
 e.call(append,vector,record)
 assert e.read(vector+16,'Q')==2 and e.read(vector+24,'Q')==4
 assert bytes(e.m.mem_read(items+40,36))==bytes(e.m.mem_read(record,36))
