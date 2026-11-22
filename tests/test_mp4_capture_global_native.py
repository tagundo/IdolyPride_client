"""The real native-publication helper serializes compare+store, not a postcheck."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def observer(tmp_path_factory):
    cc=shutil.which('c++')
    if not cc:pytest.skip('C++ compiler required')
    folder=tmp_path_factory.mktemp('capture-native');source=folder/'test.cpp';binary=folder/'test'
    actual=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    actual=actual[actual.index('// BEGIN_MP4_CAPTURE_GLOBAL_NATIVE'):actual.index('// END_MP4_CAPTURE_GLOBAL_NATIVE')]
    source.write_text(r'''
#include <atomic>
#include <cstdint>
#include <mutex>
#include <utility>
#include <pthread.h>
'''+actual+r'''
#include <cassert>
#include <condition_variable>
#include <stdexcept>
#include <string>
#include <thread>
using namespace idoly_mp4_capture_global_native;
struct Event {std::mutex m;std::condition_variable cv;bool value=false;
 void set(){std::lock_guard<std::mutex> l(m);value=true;cv.notify_all();}
 void wait(){std::unique_lock<std::mutex> l(m);cv.wait(l,[&]{return value;});}};
NativeHost* nh=nullptr;int native_calls=0;void*ns=nullptr;void*nt=nullptr;Key*nk=nullptr;uint32_t nr=0;
Calls native_calls_api(){Calls c{};
 c.core=[](void*s,uint32_t i,const Key*k,void*t,uint32_t e){assert(s==ns&&i==17&&k==nk&&t==nt&&e==23);++native_calls;nh->publish(&nr,71,2,3,1,k);};
 c.raw_core=[](void*s,const Key*k,uint32_t i,void*t,uint32_t m){assert(s==ns&&i==17&&k==nk&&t==nt&&m==23);++native_calls;nh->publish(&nr,71,2,3,1,k);};
 c.publish=[](void*r,uint32_t id,uint32_t d,uint32_t e,uint32_t f,const Key*k){assert(r==&nr&&id==71&&d==2&&e==3&&f==1&&k==nk);++native_calls;nr=id;};
 c.property_copy=[](void*d,const Key*k,const void*s){assert(d==ns&&s==nt&&k==nk);++native_calls;};
 c.sheet_copy=[](void*d,const void*s){assert(d==ns&&s==nt);++native_calls;};
 c.retired_texture=[](void*s,uint32_t id){assert(s==ns&&id==71);++native_calls;};
 c.get_index=[](void*s,const Key*k,uint32_t kind){assert(s==ns&&k==nk&&kind==6);++native_calls;return int32_t(17);};
 c.global_destroy=[](){++native_calls;};return c;}
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];Observer o;Key k{55,{-1,-1,-1}},other{56,{-1,-1,-1}};
 int sheet=1,local=2,value=1,calls=0;assert(!o.bind(&sheet,55,false));assert(!o.bind(nullptr,55,true));assert(o.bind(&sheet,55,true));
 auto write=[&](int next){o.core(&sheet,&k,[&]{o.publish(&k,[&]{++calls;value=next;});});};
 if(mode=="ordinary"){write(2);assert(value==2&&calls==1&&o.serial()==2);return 0;}
 if(mode=="identical"){write(1);write(1);assert(calls==2&&o.serial()==3);return 0;}
 if(mode=="other_property"){o.core(&sheet,&other,[&]{o.publish(&other,[&]{++calls;});});assert(calls==1&&o.serial()==1);return 0;}
 if(mode=="local_sheet"){o.core(&local,&k,[&]{o.publish(&k,[&]{++calls;});});assert(calls==1&&o.serial()==1);return 0;}
 if(mode=="unattributed"){o.publish(&k,[&]{++calls;value=9;});assert(calls==1&&value==9&&!o.serial());return 0;}
 if(mode=="invalidate"){o.invalidate();write(2);assert(calls==1&&!o.serial());return 0;}
 if(mode=="core_busy"){o.core(&sheet,&k,[&]{assert(!o.serial());assert(!o.read(1,[&]{assert(false);return true;}));o.publish(&k,[&]{value=2;});assert(!o.serial());});assert(o.serial()==2);return 0;}
 if(mode=="stable_read"){assert(o.read(1,[&]{return value==1;}));assert(!o.read(0,[&]{return true;}));assert(!o.read(2,[&]{return true;}));return 0;}
 if(mode=="getter_reentry"){assert(!o.read(1,[&]{write(2);return true;}));assert(value==2&&calls==1&&o.serial()==2);return 0;}
 if(mode=="getter_false"){assert(!o.read(1,[&]{return false;}));assert(o.serial()==1);return 0;}
 if(mode=="whole_sheet"){o.mutation(&sheet,[&]{++calls;value=3;assert(!o.serial());});assert(calls==1&&value==3&&o.serial()==2);return 0;}
 if(mode=="other_sheet_mutation"){o.mutation(&local,[&]{++calls;});assert(calls==1&&o.serial()==1);return 0;}
 if(mode=="layout"){o.layout(&sheet,[&]{++calls;assert(!o.serial());});assert(calls==1&&o.serial()==1);return 0;}
 if(mode=="retire"){o.retire([&]{++calls;assert(!o.serial());});assert(calls==1&&!o.serial());return 0;}
 if(mode=="core_exception"){try{o.core(&sheet,&k,[&]{throw std::runtime_error("core");});assert(false);}catch(const std::runtime_error&){}assert(!o.serial());return 0;}
 if(mode=="publication_exception"){try{o.core(&sheet,&k,[&]{o.publish(&k,[&]{++calls;throw std::runtime_error("native");});});assert(false);}catch(const std::runtime_error&){}assert(calls==1&&!o.serial());return 0;}
 if(mode=="mutation_exception"){try{o.mutation(&sheet,[&]{++calls;throw std::runtime_error("copy");});assert(false);}catch(const std::runtime_error&){}assert(calls==1&&!o.serial());return 0;}
 if(mode.rfind("native_host_",0)==0){NativeHost host;nh=&host;ns=&sheet;nt=&local;nk=&k;auto c=native_calls_api();
  assert(host.bind(&sheet,55,c,true));
  if(mode=="native_host_core")host.core(&sheet,17,&k,&local,23);
  else if(mode=="native_host_raw")host.raw_core(&sheet,&k,17,&local,23);
  else if(mode=="native_host_property_copy")host.property_copy(&sheet,&k,&local);
  else if(mode=="native_host_sheet_copy")host.sheet_copy(&sheet,&local);
  else if(mode=="native_host_retired")host.retired_texture(&sheet,71);
  else if(mode=="native_host_index"){assert(host.get_index(&sheet,&k,6)==17&&native_calls==1&&host.observer().serial()==1);return 0;}
  else if(mode=="native_host_destroy"){host.global_destroy();assert(native_calls==1&&!host.observer().serial());return 0;}
  else if(mode=="native_host_unclosed"){assert(!host.bind(&sheet,55,c,false));host.core(&sheet,17,&k,&local,23);assert(native_calls==2&&nr==71);return 0;}
  else assert(false);
  assert(native_calls==(mode=="native_host_core"||mode=="native_host_raw"?2:1)&&host.observer().serial()==2);return 0;}
 uint64_t after=99;
 if(mode=="restore"){assert(o.set_original(1,&after,[&]{write(3);}));assert(after==2&&o.serial()==2&&value==3&&calls==1);return 0;}
 if(mode=="restore_no_publication"){assert(!o.set_original(1,&after,[&]{}));assert(!after&&value==1&&o.serial()==1);return 0;}
 if(mode=="restore_two_publications"){assert(!o.set_original(1,&after,[&]{write(2);write(3);}));assert(!after&&calls==1&&value==2&&o.serial()==2);return 0;}
 if(mode=="restore_stale_entry"){write(2);assert(!o.set_original(1,&after,[&]{assert(false);}));assert(!after&&value==2&&calls==1);return 0;}
 if(mode=="restore_nested_ordinary"){assert(!o.set_original(1,&after,[&]{o.core(&sheet,&k,[&]{write(9);o.publish(&k,[&]{++calls;value=3;});});}));assert(!after&&value==9&&calls==1&&o.serial()==2);return 0;}
 if(mode=="restore_nested_local"){assert(o.set_original(1,&after,[&]{o.core(&sheet,&k,[&]{o.core(&local,&k,[&]{o.publish(&k,[&]{++calls;});});o.publish(&k,[&]{++calls;value=3;});});}));assert(after==2&&calls==2&&value==3&&o.serial()==2);return 0;}
 if(mode=="restore_native_reentry"){assert(!o.set_original(1,&after,[&]{o.core(&sheet,&k,[&]{o.publish(&k,[&]{++calls;value=3;write(9);});});}));assert(!after&&value==9&&calls==2&&o.serial()==3);return 0;}
 if(mode=="restore_gpu_prepare_race"){
  Event prepared,external_done;std::thread external([&]{prepared.wait();write(9);external_done.set();});
  bool ok=o.set_original(1,&after,[&]{o.core(&sheet,&k,[&]{prepared.set();external_done.wait();o.publish(&k,[&]{++calls;value=3;});});});
  external.join();assert(!ok&&!after&&value==9&&calls==1&&o.serial()==2);return 0;}
 if(mode=="restore_copy_prepare_race"){
  Event prepared,external_done;std::thread external([&]{prepared.wait();o.mutation(&sheet,[&]{++calls;value=9;});external_done.set();});
  bool ok=o.set_original(1,&after,[&]{o.core(&sheet,&k,[&]{prepared.set();external_done.wait();o.publish(&k,[&]{++calls;value=3;});});});
  external.join();assert(!ok&&!after&&value==9&&calls==1&&o.serial()==2);return 0;}
 if(mode=="reader_excludes_queued_writer"){
  Event entered,release;std::thread writer([&]{o.core(&sheet,&k,[&]{entered.set();release.wait();o.publish(&k,[&]{++calls;value=2;});});});
  entered.wait();assert(!o.serial()&&!o.read(1,[&]{assert(false);return true;}));release.set();writer.join();assert(calls==1&&value==2&&o.serial()==2);return 0;}
 if(mode=="parallel_identical"){
  std::thread a([&]{for(int i=0;i<200;++i)write(1);}),b([&]{for(int i=0;i<200;++i)write(1);});a.join();b.join();
  assert(calls==400&&value==1&&o.serial()==401);return 0;}
 if(mode=="restore_missing_after"){assert(!o.set_original(1,nullptr,[&]{assert(false);}));assert(o.serial()==1);return 0;}
 assert(false);
}
''')
    p=subprocess.run([cc,'-std=c++17','-Wall','-Wextra','-Werror','-O1','-g','-pthread',
        '-fsanitize=address,undefined','-fno-pie','-no-pie','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],
        capture_output=True,text=True,timeout=45)
    assert p.returncode==0,p.stdout+p.stderr
    return binary

@pytest.mark.parametrize('mode',['ordinary','identical','other_property','local_sheet','unattributed','invalidate',
    'core_busy','stable_read','getter_reentry','getter_false','whole_sheet','other_sheet_mutation','core_exception',
    'publication_exception','mutation_exception','restore','restore_no_publication','restore_two_publications',
    'restore_stale_entry','restore_nested_ordinary','restore_nested_local','restore_native_reentry',
    'restore_gpu_prepare_race','restore_copy_prepare_race','reader_excludes_queued_writer','parallel_identical','restore_missing_after',
    'layout','retire','native_host_core','native_host_raw','native_host_property_copy','native_host_sheet_copy',
    'native_host_retired','native_host_index','native_host_destroy','native_host_unclosed'])
def test_native_publication(observer,mode):
    p=subprocess.run([str(observer),mode],capture_output=True,text=True,timeout=6)
    assert p.returncode==0,p.stdout+p.stderr
