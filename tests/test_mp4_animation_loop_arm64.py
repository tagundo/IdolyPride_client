"""Production grant gate around unchanged original SampleTime counter code.

Original wrapper, sample loop and graph counter body execute unchanged. Other
phase processing leaves and time getter are explicit stubs; no Unity/GPU claim.
"""
import json,subprocess
from pathlib import Path
import pytest
from test_mp4_world_arm64 import Engine,STORAGE,MANAGER,compiler
from unicorn import arm64_const as R
import unicorn as uc
ROOT=Path(__file__).resolve().parents[1]
PROFILE=json.loads((ROOT/'tests/mp4_animation_loop_original_fixture.json').read_text())['platforms']
WRAPPER=r'''
#include "mp4_engine_clock.hpp"
#include <new>
extern "C" void*memset(void*p,int v,size_t n){auto*b=(volatile unsigned char*)p;while(n--)*b++=(unsigned char)v;return p;}
extern "C" void*memcpy(void*p,const void*s,size_t n){auto*b=(volatile unsigned char*)p;auto*a=(const volatile unsigned char*)s;while(n--)*b++=*a++;return p;}
static bool thread=true;static bool owner(){return thread;}
using idoly_mp4_world::AnimationGate;
extern "C" __attribute__((visibility("default"))) int construct(void*p){
 auto*g=new(p)AnimationGate;idoly_mp4_world::AnimationApi api{};
 const auto&profile=idoly_mp4_world::ANIMATION_PROFILE;
 for(unsigned i=0;i<8;++i)api.original[i]=reinterpret_cast<void(*)()>(profile.phases[i].callback.rva);
 api.owner_thread=owner;return g->install(api);
}
extern "C" __attribute__((visibility("default"))) int acquire(void*p,uint64_t n){return static_cast<AnimationGate*>(p)->acquire(n);}
extern "C" __attribute__((visibility("default"))) int call(void*p,uint32_t n){return static_cast<AnimationGate*>(p)->invoke(n);}
extern "C" __attribute__((visibility("default"))) int grant(void*p,uint64_t n,uint64_t t){return static_cast<AnimationGate*>(p)->grant(n,t);}
extern "C" __attribute__((visibility("default"))) int release(void*p,uint64_t n){return static_cast<AnimationGate*>(p)->release(n);}
extern "C" __attribute__((visibility("default"))) int healthy(void*p,uint64_t n){return static_cast<AnimationGate*>(p)->healthy(n);}
extern "C" __attribute__((visibility("default"))) int closed(void*p,uint64_t n){return static_cast<AnimationGate*>(p)->closed(n);}
#define FORWARD(N) extern "C" __attribute__((visibility("default"))) void p##N(){reinterpret_cast<AnimationGate*>(0x21000000)->invoke(N);}
FORWARD(0) FORWARD(1) FORWARD(2) FORWARD(3) FORWARD(4) FORWARD(5) FORWARD(6) FORWARD(7)
static bool mapped(uintptr_t a,size_t n,bool write){
 const auto&p=idoly_mp4_world::ANIMATION_PROFILE;
 if(a==p.registry&&n==sizeof(uintptr_t)&&!write)return true;
 const uintptr_t registry=p.indirect?*reinterpret_cast<const uintptr_t*>(p.registry):p.registry;
 return a>=registry&&n<=0x800&&a-registry<=0x800-n;
}
extern "C" __attribute__((visibility("default"))) int routes_construct(void*p){
 auto*r=new(p)idoly_mp4_world::AnimationRoutes;uintptr_t hooks[8]{};
 hooks[0]=reinterpret_cast<uintptr_t>(&p0);hooks[1]=reinterpret_cast<uintptr_t>(&p1);hooks[2]=reinterpret_cast<uintptr_t>(&p2);hooks[3]=reinterpret_cast<uintptr_t>(&p3);
 hooks[4]=reinterpret_cast<uintptr_t>(&p4);hooks[5]=reinterpret_cast<uintptr_t>(&p5);hooks[6]=reinterpret_cast<uintptr_t>(&p6);hooks[7]=reinterpret_cast<uintptr_t>(&p7);
 return r->install({mapped},idoly_mp4_world::ANIMATION_PROFILE,0,hooks);
}
extern "C" __attribute__((visibility("default"))) int routes_ready(void*p){return static_cast<idoly_mp4_world::AnimationRoutes*>(p)->ready();}
extern "C" __attribute__((visibility("default"))) int routes_release(void*p){return static_cast<idoly_mp4_world::AnimationRoutes*>(p)->release();}
'''
@pytest.fixture(scope='module',params=['android','ios'])
def original(request,tmp_path_factory):
 platform=request.param;d=tmp_path_factory.mktemp('animation-arm64-'+platform);source=d/'test.cpp';binary=d/'test.so';source.write_text(WRAPPER)
 r=subprocess.run([str(compiler()),'--target=aarch64-linux-android26','-std=c++17','-O2','-mno-outline-atomics','-fPIC','-fno-exceptions','-fno-rtti','-ffreestanding','-fno-builtin','-fvisibility=hidden','-nostdlib','-shared','-Wl,-Bsymbolic','-Wl,--no-undefined','-Wl,-Ttext=0x10000000','-DANIMATION_PROFILE='+platform+'_animation_profile','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 return platform,binary.read_bytes()

class AnimationEngine(Engine):
 def __init__(self,native):
  super().__init__(native);self.animation=PROFILE[self.platform];fixture=self.animation['sample_fixture'];self.phase_calls=[0]*8
  # Apply the ELF loader's exact relative relocations for callback address
  # constants in the production installer's local hook table.
  binary=native[1];pack=__import__('struct');section_offset=pack.unpack_from('<Q',binary,40)[0]
  stride,number=pack.unpack_from('<HH',binary,58)
  for section in range(number):
   row=pack.unpack_from('<II4QII2Q',binary,section_offset+section*stride)
   if row[1]!=4:continue
   for at in range(row[4],row[4]+row[5],row[9]):
    address,info,addend=pack.unpack_from('<QQq',binary,at)
    assert info&0xffffffff==1027
    self.write(address,'Q',addend)
  self.native_manager=0x25000000;self.graph=self.native_manager+0x4000;self.record=self.native_manager+0x2000
  self.map(self.native_manager,bytes(0x10000))
  self.map(int(fixture['sample_region'],16),bytes.fromhex(fixture['bytes']))
  self.map(int(fixture['manager_slot'],16),__import__('struct').pack('<Q',self.native_manager))
  self.write(self.native_manager+0xd0,'Q',self.record);self.write(self.native_manager+0xe0,'Q',1)
  self.write(self.record+0x48,'Q',self.graph);self.write(self.graph+0x20,'Q',17)
  self.write(MANAGER+0xc8,'Q',123);self.write(MANAGER+0xd0,'I',77)
  self.write(MANAGER+0xa8,'f',0);self.write(MANAGER+0x7c,'f',0)
  stubs={int(a,16)for a in fixture['stubbed_callbacks']}|{int(fixture['phase_dispatch'],16),int(fixture['clock_info'],16)}
  getter=int(fixture['time_getter'],16)
  for a in stubs|{getter}:self.map(a,bytes.fromhex('c0035fd6'))
  for row in self.animation['phases']:self.map(int(row['callback']['rva'],16),bytes.fromhex(row['callback']['body']))
  entries={int(row['callback']['rva'],16):i for i,row in enumerate(self.animation['phases'])}
  def hook(machine,pc,size,unused):
   if pc in entries:self.phase_calls[entries[pc]]+=1
   if pc==getter:machine.reg_write(R.UC_ARM64_REG_X0,MANAGER)
   elif pc in stubs:machine.reg_write(R.UC_ARM64_REG_X0,0)
  self.m.hook_add(uc.UC_HOOK_CODE,hook)
 def counter(self):return self.read(self.graph+0x20,'Q')
 def native_time_held(self):return self.read(MANAGER+0xc8,'Q')==123 and self.read(MANAGER+0xd0,'I')==77

def test_unchanged_sample_repeats_without_gate_despite_held_native_time(original):
 e=AnimationEngine(original)
 assert e.call('call',STORAGE,0)==1 and e.counter()==18 and e.native_time_held()
 assert e.call('call',STORAGE,0)==1 and e.counter()==19 and e.native_time_held()
 assert e.phase_calls[0]==2

def test_production_gate_runs_tick_zero_once_and_blocks_held_retry_scheduling(original):
 e=AnimationEngine(original);assert e.call('acquire',STORAGE,7)==1
 for _ in range(3):
  for phase in range(8):assert e.call('call',STORAGE,phase)==0
 assert e.counter()==17 and e.phase_calls==[0]*8
 assert e.call('grant',STORAGE,7,0)==1
 for phase in range(8):assert e.call('call',STORAGE,phase)==1
 assert e.counter()==18 and e.phase_calls==[1]*8 and e.call('closed',STORAGE,7)==1
 for _ in range(5):
  for phase in range(8):assert e.call('call',STORAGE,phase)==0
 assert e.counter()==18 and e.phase_calls==[1]*8 and e.native_time_held()
 assert e.call('grant',STORAGE,7,1)==1
 for phase in range(8):assert e.call('call',STORAGE,phase)==1
 assert e.counter()==19 and e.phase_calls==[2]*8 and e.native_time_held()
 assert e.call('release',STORAGE,7)==1
 assert e.call('call',STORAGE,0)==1 and e.counter()==20


def test_owned_cell_publication_drives_unchanged_native_dispatch_without_code_patch(original):
 e=AnimationEngine(original);profile=e.animation;route_storage=STORAGE+0x800
 registry=0x26000000 if profile['registry_indirect']else int(profile['registry'],16)
 e.map(registry,bytes(0x1000))
 if profile['registry_indirect']:e.map(int(profile['registry'],16),__import__('struct').pack('<Q',registry))
 for row in profile['phases']:e.write(registry+int(row['slot'],16),'Q',int(row['callback']['rva'],16))
 row=profile['executor'];entry=int(row['rva'],16);body=b''.join(bytes.fromhex(i['bytes'])for i in row['instructions']);e.map(entry,body)
 exit_rva=0x6400ac if e.platform=='android'else 0xccad04
 e.map(exit_rva,bytes.fromhex('c0035fd6'))
 node=STORAGE+0x400;e.write(node+0xc0,'Q',registry+int(profile['phases'][0]['slot'],16))
 def dispatch():
  hit=[]
  def stop(machine,address,size,unused):
   if address==exit_rva:hit.append(address);machine.emu_stop()
  hook=e.m.hook_add(uc.UC_HOOK_CODE,stop)
  e.m.reg_write(R.UC_ARM64_REG_X24,node);e.m.reg_write(R.UC_ARM64_REG_SP,0x4000ff00)
  try:e.m.emu_start(entry,exit_rva+4,count=100000)
  finally:e.m.hook_del(hook)
  assert hit==[exit_rva]
 dispatch();assert e.counter()==18
 assert e.call('routes_construct',route_storage)==1 and e.call('routes_ready',route_storage)==1
 assert e.call('acquire',STORAGE,7)==1
 dispatch();assert e.counter()==18
 assert e.call('grant',STORAGE,7,0)==1
 dispatch();assert e.counter()==19
 dispatch();assert e.counter()==19
 for phase in range(1,8):assert e.call('call',STORAGE,phase)==1
 assert e.call('closed',STORAGE,7)==1
 assert e.call('release',STORAGE,7)==1 and e.call('routes_release',route_storage)==1
 dispatch();assert e.counter()==20
