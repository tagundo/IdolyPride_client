"""Scoped native-clock protocol; original ARM64 kernel proof is audited separately."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "client-presentation/native/mp4_engine_clock.hpp"
#include <assert.h>
#include <stdio.h>
using namespace idoly_mp4_engine_clock;
struct Manager{alignas(8) uint8_t bytes[0x500]{};};
Manager one,two;void* current=&one;bool verified=true;unsigned calls=0;
template<class T>T get(void* p,size_t at){T value{};memcpy(&value,static_cast<uint8_t*>(p)+at,sizeof(value));return value;}
template<class T>void put(void* p,size_t at,T value){memcpy(static_cast<uint8_t*>(p)+at,&value,sizeof(value));}
bool same(double a,double b){return __builtin_fabs(a-b)<1.e-8;}
bool valid(void* p){return verified&&p==current;}
void original(void* p,double wall){
 ++calls;put(p,0xc8,get<uint64_t>(p,0xc8)+1);put(p,0xd0,get<uint32_t>(p,0xd0)+1);
 if(get<uint8_t>(p,0xf8))return;
 put(p,0xc1,uint8_t(0)); // Representative original one-shot housekeeping.
 put(p,0x60,wall-940.);put(p,0x70,wall-900.);
 put(p,0x90,wall-940.);put(p,0xa0,wall-900.);
 for(size_t at:{size_t(0x78),size_t(0x7c),size_t(0x80),size_t(0xa8),size_t(0xac),size_t(0xb0)})put(p,at,9.f);
}
void seed(Manager& m){
 memset(m.bytes,0,sizeof(m.bytes));
 for(size_t at:{size_t(0x30),size_t(0x38),size_t(0x60),size_t(0x68),size_t(0x90),size_t(0x98)})put(&m,at,60.);
 for(size_t at:{size_t(0x40),size_t(0x70),size_t(0xa0)})put(&m,at,100.);
 put(&m,0x48,.02f);put(&m,0xfc,.5f);put(&m,0xe0,940.);put(&m,0xe8,900.);put(&m,0xf0,-50.);
 put(&m,0xc8,uint64_t(99));put(&m,0xd0,uint32_t(17));
}
void held(const Manager& m,double game,double unscaled,float delta){
 for(size_t at:{size_t(0x60),size_t(0x90)})assert(same(get<double>(const_cast<Manager*>(&m),at),game));
 for(size_t at:{size_t(0x70),size_t(0xa0)})assert(same(get<double>(const_cast<Manager*>(&m),at),unscaled));
 for(size_t at:{size_t(0x78),size_t(0x7c),size_t(0x80),size_t(0xa8),size_t(0xac),size_t(0xb0)})assert(get<float>(const_cast<Manager*>(&m),at)==delta);
}
int main(int argc,char**argv){
 assert(argc==2);const char* test=argv[1];seed(one);seed(two);Scope scope;assert(scope.install({valid,original}));
 if(!strcmp(test,"inactive")){
  assert(scope.native_tick(&one,1000.25));assert(calls==1&&scope.latest_manager()==&one&&scope.last_wall_timestamp()==1000.25);
  assert(get<uint64_t>(&one,0xc8)==100);puts(test);return 0;
 }
 if(!strcmp(test,"invalid_api")){Scope empty;assert(!empty.install({nullptr,original}));assert(!empty.acquire(&one,1000,60));assert(!empty.native_tick(&one,1000));assert(calls==0);puts(test);return 0;}
 if(!strcmp(test,"invalid_state")){put(&one,0x80,__builtin_nanf(""));assert(!scope.acquire(&one,1000.,60));assert(get<float>(&one,0xfc)==.5f&&get<float>(&one,0xd8)==0);puts(test);return 0;}
 if(!strcmp(test,"engine_paused")){put(&one,0xf8,uint8_t(1));assert(!scope.acquire(&one,1000.,60));assert(!strcmp(scope.error(),"engine_clock_engine_paused"));puts(test);return 0;}
 if(!strcmp(test,"invalid_hz")){assert(!scope.acquire(&one,1000.,30));assert(!scope.acquire(&one,1000.,0));assert(!scope.acquire(&one,1000.,90));puts(test);return 0;}
 const uint32_t hz=!strcmp(test,"120hz")?120:60;uint8_t original_time[0x8c];memcpy(original_time,one.bytes+0x30,sizeof(original_time));
 assert(scope.acquire(&one,1000.,hz));assert(scope.active()&&scope.simulation_hz()==hz);
 assert(get<float>(&one,0xd8)==1.f/hz&&get<float>(&one,0xfc)==1.f);
 assert(scope.held()&&calls==0&&get<uint64_t>(&one,0xc8)==99);held(one,60.,100.,0.f);
 put(&one,0xb0,.1f);assert(!scope.held());put(&one,0xb0,0.f);assert(scope.held());
 if(!strcmp(test,"quiescent_policy")){
  assert(scope.set_owned_loop_quiescent(true));put(&one,0xc1,uint8_t(1));
  assert(scope.native_tick(&one,1001.,{false,0}));assert(calls==0&&get<uint64_t>(&one,0xc8)==99&&get<uint8_t>(&one,0xc1)==1);
  assert(scope.native_tick(&one,1002.,{true,0}));assert(calls==1&&get<uint8_t>(&one,0xc1)==0);
  assert(scope.native_tick(&one,1003.,{true,1}));assert(calls==2&&!scope.held());
  assert(!scope.set_owned_loop_quiescent(false)&&scope.owned_loop_quiescent());
  assert(scope.hold_for_boundary(&one,1004.));assert(calls==2&&scope.held());
  assert(scope.native_tick(&one,1005.,{false,0}));assert(calls==2&&scope.tick()==1);
  put(&one,0xf8,uint8_t(1));assert(!scope.native_tick(&one,1006.,{true,2}));assert(calls==2&&scope.tick()==1);
  put(&one,0xf8,uint8_t(0));assert(scope.native_tick(&one,1007.,{true,2}));assert(calls==3);
  assert(scope.hold_for_boundary(&one,1008.)&&scope.rebase_for_restore(&one,1008.,true));
  assert(scope.native_tick(&one,1009.,{false,0}));assert(calls==3&&scope.held());held(one,60.,100.,0.f);
  assert(scope.restore(&one,1010.,true));assert(!scope.owned_loop_quiescent());
  assert(scope.native_tick(&one,1010.01));assert(calls==4);puts(test);return 0;
 }
 if(!strcmp(test,"boundary_hold_invalid")){
  const auto before=one;assert(!scope.hold_for_boundary(&two,1001.));assert(!memcmp(&one,&before,sizeof(one))&&calls==0);
  assert(!scope.hold_for_boundary(&one,999.));assert(!memcmp(&one,&before,sizeof(one))&&calls==0);puts(test);return 0;
 }
 if(!strcmp(test,"double_acquire")){assert(!scope.acquire(&two,1001.,hz));assert(scope.active()&&get<float>(&two,0xfc)==.5f);assert(scope.restore(&one,1001.,true));puts(test);return 0;}
 if(!strcmp(test,"owner_replaced")){
  const auto before=one;current=&two;assert(!scope.native_tick(&two,1001.,{true,0}));assert(calls==1&&!scope.active());
  assert(!memcmp(&one,&before,sizeof(one)));assert(!strcmp(scope.error(),"engine_clock_owner_replaced"));puts(test);return 0;
 }
 if(!strcmp(test,"owner_unverified")){
  const auto before=one;verified=false;assert(!scope.restore(&one,1001.,true));assert(!memcmp(&one,&before,sizeof(one)));puts(test);return 0;
 }
 assert(scope.native_tick(&one,1000.01,{false,0}));held(one,60.,100.,0.f);assert(calls==1&&!scope.have_tick());
 assert(scope.native_tick(&one,1000.2,{true,0}));held(one,60.,100.,0.f);assert(calls==2&&scope.have_tick()&&scope.tick()==0);
 if(!strcmp(test,"out_of_order")){
  assert(!scope.native_tick(&one,1000.3,{true,2}));held(one,60.,100.,0.f);assert(calls==3&&scope.tick()==0);
  assert(!strcmp(scope.error(),"engine_clock_grant_out_of_order"));assert(scope.restore(&one,1001.,true));puts(test);return 0;
 }
 if(!strcmp(test,"wall_reversed")){
  assert(!scope.native_tick(&one,999.,{true,1}));held(one,60.,100.,0.f);assert(calls==3&&scope.tick()==0);
  assert(scope.last_wall_timestamp()==1000.2);assert(scope.restore(&one,1001.,true));puts(test);return 0;
 }
 if(!strcmp(test,"paused_mid_session")){
  put(&one,0xf8,uint8_t(1));assert(!scope.native_tick(&one,1003.,{true,1}));held(one,60.,100.,0.f);
  assert(calls==3&&scope.tick()==0&&scope.active()&&!strcmp(scope.error(),"engine_clock_engine_paused"));
  put(&one,0xf8,uint8_t(0));assert(scope.native_tick(&one,1004.,{true,1}));held(one,60.+1./hz,100.+1./hz,1.f/hz);
  assert(calls==4&&scope.tick()==1&&!strcmp(scope.error(),"none"));assert(scope.restore(&one,1005.,true));puts(test);return 0;
 }
 assert(scope.native_tick(&one,1003.,{true,1}));held(one,60.+1./hz,100.+1./hz,1.f/hz);assert(calls==3);
 assert(!scope.held());
 if(!strcmp(test,"restore_requires_held")){
  const auto before=one;assert(!scope.rebase_for_restore(&one,1003.,true));assert(!memcmp(&one,&before,sizeof(one)));
  assert(!strcmp(scope.error(),"engine_clock_restore_not_held"));puts(test);return 0;
 }
 assert(same(get<double>(&one,0x68),60.));assert(same(get<double>(&one,0x98),60.));
 put(&one,0xc1,uint8_t(1));assert(scope.native_tick(&one,1009.,{false,0}));held(one,60.+1./hz,100.+1./hz,0.f);
 assert(calls==4&&get<uint64_t>(&one,0xc8)==103&&get<uint32_t>(&one,0xd0)==21&&get<uint8_t>(&one,0xc1)==0);
 if(!strcmp(test,"two_phase_restore")){
  assert(scope.rebase_for_restore(&one,1009.,true)&&scope.restoring()&&scope.held());held(one,60.,100.,0.f);assert(calls==4);
  assert(scope.rebase_for_restore(&one,1009.,true));assert(get<float>(&one,0xd8)==1.f/hz&&get<float>(&one,0xfc)==1.f);
  assert(scope.native_tick(&one,1010.,{false,0}));held(one,60.,100.,0.f);assert(calls==5);
  assert(!scope.native_tick(&one,1011.,{true,2}));held(one,60.,100.,0.f);assert(calls==6&&scope.tick()==1);
  assert(scope.restore(&one,1012.,true));held(one,60.,100.,0.f);assert(!scope.active()&&get<uint64_t>(&one,0xc8)==105);
  assert(get<float>(&one,0xfc)==.5f&&get<float>(&one,0xd8)==0&&get<double>(&one,0xe0)==952.);puts(test);return 0;
 }
 if(!strcmp(test,"level_replaced")){
  put(&one,0xf0,-60.-1./hz);assert(!scope.restore(&one,1010.,true));assert(!scope.active());
  assert(same(get<double>(&one,0x60)+get<double>(&one,0xf0),0.));assert(same(get<double>(&one,0xe0),1010.-60.-1./hz));
  assert(!strcmp(scope.error(),"engine_clock_scene_time_changed"));puts(test);return 0;
 }
 if(!strcmp(test,"level_changed_tick")){
  put(&one,0xf0,-60.-1./hz);assert(!scope.native_tick(&one,1010.,{true,2}));assert(calls==5&&!scope.active());
  assert(get<double>(&one,0xf0)==-60.-1./hz&&get<float>(&one,0xd8)==0&&get<float>(&one,0xfc)==.5f);
  assert(!strcmp(scope.error(),"engine_clock_scene_time_changed"));puts(test);return 0;
 }
 if(!strcmp(test,"lost_scene")){
  put(&one,0xf0,-60.-1./hz);put(&one,0x30,60.);assert(scope.restore(&one,1010.,false));
  assert(same(get<double>(&one,0x60),60.+1./hz)&&same(get<double>(&one,0x30),60.));assert(same(get<double>(&one,0x60)+get<double>(&one,0xf0),0.));
  assert(get<float>(&one,0xd8)==0&&get<float>(&one,0xfc)==.5f);puts(test);return 0;
 }
 if(!strcmp(test,"settings_changed")){
  put(&one,0xfc,2.f);assert(!scope.native_tick(&one,1010.,{true,2}));assert(!scope.active()&&calls==5);
  assert(get<float>(&one,0xfc)==2.f&&get<float>(&one,0xd8)==0);assert(!strcmp(scope.error(),"engine_clock_settings_changed"));puts(test);return 0;
 }
 if(!strcmp(test,"fixed_changed")){
  put(&one,0x48,.01f);assert(!scope.restore(&one,1010.,true));assert(get<float>(&one,0x48)==.01f);puts(test);return 0;
 }
 assert(scope.native_tick(&one,1011.,{true,2}));held(one,60.+2./hz,100.+2./hz,1.f/hz);assert(calls==5);
 assert(scope.restore(&one,1012.,true));assert(!scope.active()&&calls==5);
 assert(!memcmp(original_time,one.bytes+0x30,sizeof(original_time)));assert(get<float>(&one,0xd8)==0&&get<float>(&one,0xfc)==.5f);
 assert(get<uint64_t>(&one,0xc8)==104&&get<uint32_t>(&one,0xd0)==22&&get<uint8_t>(&one,0xc1)==0);
 assert(same(get<double>(&one,0xe0),952.)&&same(get<double>(&one,0xe8),912.)&&get<double>(&one,0xf0)==-50.);
 assert(scope.restore(&one,1014.,true));assert(calls==5&&get<double>(&one,0xe0)==952.);
 puts(test);
}
'''


@pytest.fixture(scope="module")
def run_clock(tmp_path_factory):
    folder = tmp_path_factory.mktemp("mp4-engine-clock")
    source, binary = folder / "clock.cpp", folder / "clock"
    source.write_text(HARNESS)
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    result = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    def run(scenario):
        result = subprocess.run([str(binary), scenario], capture_output=True, text=True, timeout=4)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    return run


@pytest.mark.parametrize("scenario", ["60hz", "120hz", "inactive", "invalid_api", "invalid_state", "engine_paused", "paused_mid_session", "invalid_hz", "double_acquire", "owner_replaced", "owner_unverified", "out_of_order", "wall_reversed", "level_replaced", "level_changed_tick", "lost_scene", "settings_changed", "fixed_changed", "two_phase_restore", "restore_requires_held", "quiescent_policy", "boundary_hold_invalid"])
def test_scoped_native_clock_grants_backpressure_housekeeping_and_cleanup(run_clock, scenario):
    assert run_clock(scenario) == scenario
