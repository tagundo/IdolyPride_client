"""Execute exact family dispatch; unknown recipes never inherit source ownership."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]

def test_shipping_auxiliary_recipe_families_are_explicit(tmp_path):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual=text.split('// BEGIN_MP4_GPU_AUXILIARY_RECIPE_ROUTER',1)[1].split('// END_MP4_GPU_AUXILIARY_RECIPE_ROUTER',1)[0]
    prefix='''#include <cassert>\n#include <cstdint>\n#include <stdexcept>\nbool thread=true;bool game_call(){return thread;}\n'''
    driver=r'''
int pf=0,stage=0;bool retained=true;
bool paused(uint64_t source,uint64_t job,uint64_t recipe){++pf;return retained&&source==7&&job==9&&recipe==0x5046000000000001ULL;}
bool equipment(uint64_t source,uint64_t job,uint64_t recipe){++stage;return source==7&&job==9&&recipe==0x5354000000000002ULL;}
bool throws(uint64_t,uint64_t,uint64_t){throw std::runtime_error("proof");}
int main(){
 const uint64_t a=0x5046000000000001ULL,b=0x5354000000000002ULL;
 assert(!mp4_gpu_auxiliary_recipe_router(7,9,a)&&!mp4_gpu_auxiliary_recipe_router(7,9,b));
 mp4_gpu_paused_auxiliary_recipe_closed=paused;mp4_gpu_stage_auxiliary_recipe_closed=equipment;
 assert(mp4_gpu_auxiliary_recipe_router(7,9,a)&&pf==1&&!stage);
 assert(mp4_gpu_auxiliary_recipe_router(7,9,b)&&pf==1&&stage==1);
 assert(!mp4_gpu_auxiliary_recipe_router(7,9,0x1234000000000001ULL)&&pf==1&&stage==1);
 assert(!mp4_gpu_auxiliary_recipe_router(7,9,0x5046000000000000ULL)&&pf==1);
 assert(!mp4_gpu_auxiliary_recipe_router(0,9,a)&&!mp4_gpu_auxiliary_recipe_router(7,0,a)&&pf==1);
 thread=false;assert(!mp4_gpu_auxiliary_recipe_router(7,9,a)&&pf==1);thread=true;
 assert(!mp4_gpu_auxiliary_recipe_router(8,9,a)&&pf==2&&stage==1);
 retained=false;assert(!mp4_gpu_auxiliary_recipe_router(7,9,a)&&pf==3);
 mp4_gpu_paused_auxiliary_recipe_closed=throws;assert(!mp4_gpu_auxiliary_recipe_router(7,9,a)&&stage==1);
 assert(mp4_gpu_auxiliary_recipe_router(7,9,b)&&stage==2);
}
'''
    source=tmp_path/'router.cpp';binary=tmp_path/'router';source.write_text(prefix+actual+driver)
    built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-pie','-no-pie',str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
