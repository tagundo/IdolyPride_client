"""Bounded native trace copies scalar evidence without calling game providers."""
from pathlib import Path
import json
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def trace_binary(tmp_path_factory):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('A host C++ compiler is required')
    source = (ROOT / 'client-presentation/native/mp4_runtime.hpp').read_text()
    stage = source.split('enum class Stage{', 1)[1].split('};', 1)[0]
    body = source.split('// BEGIN_MP4_EXPORT_FAILURE_TRACE\n', 1)[1].split('// END_MP4_EXPORT_FAILURE_TRACE', 1)[0]
    harness = r'''
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <pthread.h>
#include <thread>
#include <vector>
#include <cassert>
#include <string>
enum class Stage { STAGES };
struct Schedule {uint64_t tick=0;uint64_t next_tick()const{return tick;}};
struct Job {Stage stage=Stage::idle;uint64_t frame=0;Schedule schedule{};}job;
// ACTUAL
int main(int argc,char**argv){
 assert(argc==2);const std::string mode=argv[1];
 if(mode=="empty"){}
 else if(mode=="sanitize"){diagnostic_event("x\"/tmp/a\n", "secret/\\\"\n",3,4,true);}
 else if(mode=="coalesce"){for(unsigned i=0;i<100;++i)diagnostic_event("capture","waiting",5,7);}
 else if(mode=="wrap"){for(unsigned i=0;i<40;++i)diagnostic_event("frame_readback","step",i,i+1);}
 else if(mode=="modules"){for(size_t i=0;i<trace_modules;++i)diagnostic_module(i,i%2==0,"provider_unbound");diagnostic_module(trace_modules,true,"invalid");}
 else if(mode=="changed_module"){diagnostic_module(7,false,"video_coordinator_unbound");diagnostic_module(7,false,"video_coordinator_unbound");diagnostic_module(7,true,"ignored");}
 else if(mode=="safe_numbers"){diagnostic_event("stage","limit",~uint64_t(0),~uint64_t(0));}
 else if(mode=="long"){char text[400];memset(text,'a',sizeof text);text[399]=0;diagnostic_event(text,text,0,0,true);}
 else if(mode=="job"){job.stage=Stage::frame_submit;job.frame=12;job.schedule.tick=23;diagnostic_job_event("encoder_frame_rejected",true);}
 else if(mode=="concurrent"){std::vector<std::thread>threads;for(unsigned t=0;t<4;++t)threads.emplace_back([t]{for(unsigned i=0;i<100;++i)diagnostic_event("writer","observed",t*100+i,i);});for(auto&t:threads)t.join();}
 else if(mode=="small"){struct Buffer{char bytes[16];uint64_t guard=0x87654321;}b{};assert(!diagnostics(b.bytes,sizeof b.bytes));assert(!b.bytes[0]);assert(b.guard==0x87654321);}
 else if(mode=="null"){assert(!diagnostics(nullptr,0));char c='a';assert(!diagnostics(&c,0));assert(c=='a');}
 else assert(false);
 char json[16384]{};const auto n=diagnostics(json,sizeof json);assert(n&&n==strlen(json)&&n<sizeof json);puts(json);
}
'''.replace('STAGES', stage).replace('// ACTUAL', body)
    directory = tmp_path_factory.mktemp('mp4-export-trace')
    cpp, binary = directory / 'trace.cpp', directory / 'trace'
    cpp.write_text(harness)
    subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread', str(cpp), '-o', str(binary)], check=True, capture_output=True, text=True)
    return binary

@pytest.mark.parametrize('mode', ['empty','sanitize','coalesce','wrap','modules','changed_module','safe_numbers','long','job','concurrent','small','null'])
def test_bounded_export_failure_trace(trace_binary, mode):
    result = subprocess.run([str(trace_binary),mode],check=True,capture_output=True,text=True,timeout=15)
    trace = json.loads(result.stdout)['export_trace']
    assert set(trace)=={'schema','current_stage','last_error','events','modules'}
    assert trace['schema']==1 and len(trace['events'])<=16 and len(trace['modules'])==20
    assert all(type(v) is bool for v in trace['modules'].values())
    assert all(len(trace[k])<=95 and all(c.isascii() and (c.isalnum() or c=='_') for c in trace[k]) for k in ['current_stage','last_error'])
    events=trace['events']
    assert all(set(e)=={'sequence','stage','code','frame','tick'} for e in events)
    assert all(0<=e[k]<=9007199254740991 for e in events for k in ['sequence','frame','tick'])
    assert [e['sequence'] for e in events]==sorted(set(e['sequence'] for e in events))
    if mode=='coalesce': assert len(events)==1
    if mode=='wrap': assert len(events)==16 and events[0]['frame']==24 and events[-1]['frame']==39
    if mode=='concurrent': assert len(events)==16 and events[-1]['sequence']==400
    if mode=='changed_module': assert len(events)==1 and trace['modules']['video_coordinator'] is True
    if mode=='sanitize': assert '/' not in result.stdout and '\\' not in result.stdout
    if mode=='job': assert events[-1]['stage']=='encoder_append' and events[-1]['frame']==12 and events[-1]['tick']==22
