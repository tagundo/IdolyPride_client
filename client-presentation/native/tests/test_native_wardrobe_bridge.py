"""Run the actual typed bridge hooks with controlled, blocking original calls."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1]


def test_original_hook_arguments_results_and_background_snapshot(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("Host C++ compiler unavailable")
    bridge = (NATIVE / "bridge.cpp").read_text()
    chunk = bridge.split("namespace wardrobe = idoly::presentation::wardrobe;", 1)[1].split("\n#endif", 1)[0]
    source = tmp_path / "exit.cpp"
    source.write_text(r'''
#include <atomic>
#include <cassert>
#include <cstring>
#include <cstdio>
#include "wardrobe_lifecycle.hpp"
#include "wardrobe_timing.hpp"
using Method=const void;
std::atomic<bool> ready{false};bool correct_thread=true;int64_t clock_ms=1000;
int64_t render_probe_monotonic_ms(){return clock_ms;}
bool game_call(bool establish){assert(!establish);return correct_thread;}
namespace wardrobe=idoly::presentation::wardrobe;
''' + chunk + r'''
void *self=(void*)0x11,*info=(void*)0x22,*cancel=(void*)0x33;
Method *method=(Method*)0x44;
int backs=0,gcs=0,unloads=0;
wardrobe::Task expected{(void*)0x123,-123,{}};
void check(void*s,Method*m){assert(s==self&&m==method);}
void check(wardrobe::Task t){assert(t.source==expected.source&&t.token==expected.token);}
wardrobe::Task preclose(void*s,void*i,wardrobe::Token t,Method*m){check(s,m);assert(i==info&&t.source==cancel);clock_ms+=37000;return expected;}
wardrobe::Task details(void*s,void*i,wardrobe::Token t,Method*m){check(s,m);assert(i==info&&t.source==cancel);++clock_ms;return expected;}
wardrobe::Task show(void*s,wardrobe::Token t,Method*m){check(s,m);assert(t.source==cancel);++clock_ms;return expected;}
void simple(void*s,Method*m){check(s,m);++clock_ms;}
void transition(void*s,void*i,Method*m){check(s,m);assert(i==info);++clock_ms;}
void gc(Method*m){assert(m==method);++gcs;++clock_ms;}
void *unload(Method*m){assert(m==method);++unloads;++clock_ms;return info;}
void back(void*s,Method*m){check(s,m);++backs;
 check(wardrobe_preclose_hook(s,info,{cancel},m));
 for(int i=0;i<100;++i)wardrobe_hide_move_hook(s,m);
 wardrobe_disable_hook(s,m);wardrobe_gc_collect_hook(m);
 assert(wardrobe_unload_unused_hook(m)==info);
 check(character_list_show_hook(s,{cancel},m));
 check(character_details_close_in_hook(s,info,{cancel},m));
 character_list_open_in_hook(s,info,m);
 character_list_close_in_hook(s,info,m);
}
int main(){
 wardrobe_exit_tracker.configure(render_probe_monotonic_ms);
 wardrobe_back_original=back;fitting_back_original=simple;
 wardrobe_preclose_original=preclose;wardrobe_hide_move_original=simple;
 wardrobe_disable_original=simple;character_list_show_original=show;
 character_details_close_in_original=details;
 character_list_open_in_original=transition;character_list_close_in_original=transition;
 wardrobe_gc_collect_original=gc;wardrobe_unload_unused_original=unload;
 ready=true;wardrobe_back_hook(self,method);
 assert(backs==1&&gcs==1&&unloads==1);
 char json[1536];wardrobe_status_json(json,sizeof json);std::puts(json);
 const auto sequence=wardrobe_exit_tracker.snapshot(clock_ms).sequence;
 correct_thread=false;wardrobe_back_hook(self,method);
 assert(backs==2&&wardrobe_exit_tracker.snapshot(clock_ms).sequence==sequence);
 correct_thread=true;fitting_back_hook(self,method);character_list_close_in_hook(self,info,method);
 wardrobe_status_json(json,sizeof json);std::puts(json);
}
''')
    binary = tmp_path / "exit"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                    "-I", str(NATIVE), str(source), "-o", str(binary)],
                   check=True, capture_output=True, timeout=20)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
    first, second = map(json.loads, result.stdout.splitlines())
    assert first["schema"] == second["schema"] == 2
    assert first["phase"] == "idle" and first["show_failures"] == first["released_waits"] == 0
    observed = first["exit"]
    assert observed["room"] == "character_costume" and observed["phase"] == "completed"
    assert not observed["active"] and not observed["in_original"]
    assert observed["max_sync_ms"] >= 37000
    assert {"stage": "preclose", "duration_ms": 37000} in observed["spans"]
    assert second["exit"]["room"] == "fitting_room" and second["exit"]["phase"] == "completed"
