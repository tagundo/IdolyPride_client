"""Physical owner join against actual helper; modeled retired-ledger leaves."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include <cassert>
#include <cstdint>
#include <string>
struct Mp4RenderContext{void*pointer;};
struct{Mp4RenderContext context{reinterpret_cast<void*>(1)};uint64_t source_generation=7,job_generation=9,draw_token=11;}mp4_owned_render_submission;
struct Gpu{uint64_t source=7,epoch=9,sequence=3,retired=2,active_token=11,last_token=11;bool draw=true,configured=true,sealed=false;}mp4_gpu_fence_host,mp4_gpu_auxiliary_host;
int camera;void*mp4_owned_render_camera=&camera;bool mp4_owned_render_ticket_active=true,thread=true;unsigned mp4_owned_render_depth=1,mp4_unowned_render_depth=0;
bool game_call(){return thread;}
'''
DRIVER=r'''
int main(int argc,char**argv){assert(argc==2);const std::string mode=argv[1];Mp4ProFlareGpuOwner owner;
 mp4_gpu_auxiliary_host.configured=false;mp4_gpu_auxiliary_host.draw=false;
 if(mode=="offthread"){thread=false;assert(!mp4_proflare_gpu_origin(7,9,&camera,&owner));return 0;}
 if(mode=="no_actual_draw")mp4_owned_render_ticket_active=false;
 if(mode=="wrong_source")mp4_owned_render_submission.source_generation=8;
 if(mode=="wrong_job")mp4_gpu_fence_host.epoch=10;
 if(mode=="wrong_ticket")mp4_gpu_fence_host.active_token=12;
 if(mode=="unowned_nested")mp4_unowned_render_depth=1;
 if(mode=="nested_draw")mp4_owned_render_depth=2;
 const bool admitted=mode!="no_actual_draw"&&mode!="wrong_source"&&mode!="wrong_job"&&mode!="wrong_ticket"&&mode!="unowned_nested"&&mode!="nested_draw";
 assert(mp4_proflare_gpu_origin(7,9,&camera,&owner)==admitted);
 if(!admitted){assert(!owner.source);return 0;}
 assert(mp4_proflare_gpu_current(owner)&&!mp4_proflare_gpu_quiet(owner));
 mp4_owned_render_depth=0;mp4_owned_render_ticket_active=false;mp4_gpu_fence_host.draw=false;
 assert(!mp4_proflare_gpu_current(owner)&&!mp4_proflare_gpu_quiet(owner));
 mp4_gpu_fence_host.retired=mp4_gpu_fence_host.sequence;assert(mp4_proflare_gpu_quiet(owner));
 if(mode=="pending_later_draw"){++mp4_gpu_fence_host.sequence;assert(!mp4_proflare_gpu_quiet(owner));}
 else if(mode=="pending_upload"){mp4_gpu_auxiliary_host.configured=true;assert(!mp4_proflare_gpu_quiet(owner));}
 else if(mode=="open_upload"){mp4_gpu_auxiliary_host.draw=true;assert(!mp4_proflare_gpu_quiet(owner));}
 else if(mode=="upload_wrong_job"){mp4_gpu_auxiliary_host.configured=true;mp4_gpu_auxiliary_host.retired=mp4_gpu_auxiliary_host.sequence;mp4_gpu_auxiliary_host.epoch=10;assert(!mp4_proflare_gpu_quiet(owner));}
 else if(mode=="finished_too_early"){mp4_gpu_fence_host.configured=false;assert(!mp4_proflare_gpu_quiet(owner));}
 else if(mode=="retired_upload"){mp4_gpu_auxiliary_host.configured=true;mp4_gpu_auxiliary_host.retired=mp4_gpu_auxiliary_host.sequence;assert(mp4_proflare_gpu_quiet(owner));}
 else assert(mode=="normal");
}
'''
def block(s,name):
    a=s.index(f"// BEGIN_{name}");b=s.index(f"// END_{name}",a);return s[a:b]
@pytest.fixture(scope="module")
def host(tmp_path_factory):
    bridge=(ROOT/"client-presentation/native/bridge.cpp").read_text()
    source=PREFIX+block(bridge,"MP4_PROFLARE_GPU_OWNER_API")+block(bridge,"MP4_PROFLARE_GPU_OWNER_HOST")+DRIVER
    directory=tmp_path_factory.mktemp("mp4-proflare-gpu-owner");path=directory/"host.cpp";path.write_text(source);binary=directory/"host"
    r=subprocess.run([shutil.which("g++")or"clang++","-std=c++17","-Wall","-Wextra","-Werror","-Wno-misleading-indentation","-O1","-g","-fsanitize=address,undefined","-fno-pie","-no-pie",str(path),"-o",str(binary)],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    return binary
@pytest.mark.parametrize("case",["normal","offthread","no_actual_draw","wrong_source","wrong_job","wrong_ticket","unowned_nested","nested_draw","pending_later_draw","pending_upload","open_upload","upload_wrong_job","finished_too_early","retired_upload"])
def test_actual_gpu_owner(host,case):
    r=subprocess.run([str(host),case],capture_output=True,text=True);assert r.returncode==0,r.stdout+r.stderr
