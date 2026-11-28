"""Ordinary original stacks cannot mint or prematurely retire source leases."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include "mp4_engine_clock.hpp"
#include <atomic>
#include <cassert>
#include <string>
#include <thread>
using namespace idoly_mp4_world;
FixedGate fixed;AnimationGate animation;
const auto main_thread=std::this_thread::get_id();
bool owner(){return std::this_thread::get_id()==main_thread;}
std::string mode;std::atomic<bool>entered{false},finish{false};unsigned calls=0;bool nested=false,blocked=false;
int first=1,second=2;
bool fixed_original(){++calls;
 if(mode=="fixed_reentrant"||mode=="fixed_nested"){
  if(mode=="fixed_nested"&&!nested){nested=true;assert(fixed.native_condition());nested=false;}
  auto lease=fixed.acquire_lease(7,&first);assert(lease.empty());blocked=true;
 }
 if(mode=="fixed_unpublished"){assert(fixed.install({fixed_original,owner}));auto lease=fixed.acquire_lease(7,&first);assert(lease.empty());blocked=true;}
 if(mode=="fixed_throw")throw 17;
 if(mode=="fixed_foreign"||mode=="fixed_release_inflight"){entered.store(true,std::memory_order_release);while(!finish.load(std::memory_order_acquire))std::this_thread::yield();}
 return true;
}
void animation_original();
AnimationApi animation_api(){AnimationApi api{};api.owner_thread=owner;for(auto&fn:api.original)fn=animation_original;return api;}
void animation_original(){++calls;
 if(mode=="animation_reentrant"||mode=="animation_nested"){
  if(mode=="animation_nested"&&!nested){nested=true;assert(animation.invoke(1));nested=false;}
  auto lease=animation.acquire_lease(7,&first);assert(lease.empty());blocked=true;
 }
 if(mode=="animation_unpublished"){assert(animation.install(animation_api()));auto lease=animation.acquire_lease(7,&first);assert(lease.empty());blocked=true;}
 if(mode=="animation_throw")throw 19;
 if(mode=="animation_foreign"||mode=="animation_release_inflight"){entered.store(true,std::memory_order_release);while(!finish.load(std::memory_order_acquire))std::this_thread::yield();}
}
int main(int argc,char**argv){assert(argc==2);mode=argv[1];
 const bool f=mode.rfind("fixed",0)==0;
 if(mode=="fixed_unpublished"){assert(fixed.forward_unpublished(fixed_original));assert(blocked&&calls==1);auto lease=fixed.acquire_lease(7,&first);assert(!lease.empty()&&fixed.release_lease(lease,&first));return 0;}
 if(mode=="animation_unpublished"){assert(animation.forward_unpublished(animation_original));assert(blocked&&calls==1);auto lease=animation.acquire_lease(7,&first);assert(!lease.empty()&&animation.release_lease(lease,&first));return 0;}
 assert(fixed.install({fixed_original,owner})&&animation.install(animation_api()));
 if(mode=="fixed_throw"||mode=="animation_throw"){
  bool thrown=false;try{if(f)(void)fixed.native_condition();else(void)animation.invoke(0);}catch(int value){thrown=value==(f?17:19);}
  assert(thrown&&calls==1);auto lease=f?fixed.acquire_lease(7,&first):animation.acquire_lease(7,&first);assert(!lease.empty());assert(f?fixed.release_lease(lease,&first):animation.release_lease(lease,&first));return 0;
 }
 if(mode=="fixed_foreign"||mode=="animation_foreign"||mode=="fixed_release_inflight"||mode=="animation_release_inflight"){
  SourceGateLease lease;
  const bool existing=mode.find("release")!=std::string::npos;
  if(existing){auto acquired=f?fixed.acquire_lease(7,&first):animation.acquire_lease(7,&first);assert(lease.take(static_cast<SourceGateLease&&>(acquired)));}
  std::thread worker([&]{if(f)(void)fixed.native_condition();else(void)animation.invoke(0);});
  while(!entered.load(std::memory_order_acquire))std::this_thread::yield();
  if(existing){assert(!(f?fixed.release_lease(lease,&first):animation.release_lease(lease,&first)));assert(!lease.empty());}
  else{auto acquired=f?fixed.acquire_lease(7,&first):animation.acquire_lease(7,&first);assert(acquired.empty());}
  finish.store(true,std::memory_order_release);worker.join();assert(calls==1);
  if(existing)assert(f?fixed.release_lease(lease,&first):animation.release_lease(lease,&first));
  auto later=f?fixed.acquire_lease(8,&second):animation.acquire_lease(8,&second);assert(later.empty());return 0;
 }
 if(f)assert(fixed.native_condition());else assert(animation.invoke(0));
 assert(blocked&&calls==(mode.find("nested")!=std::string::npos?2u:1u));
 auto lease=f?fixed.acquire_lease(7,&first):animation.acquire_lease(7,&first);assert(!lease.empty());assert(f?fixed.release_lease(lease,&first):animation.release_lease(lease,&first));
}
'''
@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('C++ compiler required')
    folder=tmp_path_factory.mktemp('source-gate-entry');source=folder/'test.cpp';out=folder/'test';source.write_text(HARNESS)
    result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-O1','-g','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(out)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    return out
@pytest.mark.parametrize('mode','fixed_reentrant fixed_nested fixed_unpublished fixed_throw fixed_foreign fixed_release_inflight animation_reentrant animation_nested animation_unpublished animation_throw animation_foreign animation_release_inflight'.split())
def test_ordinary_entry_lifetime(binary,mode):
    result=subprocess.run([str(binary),mode],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
