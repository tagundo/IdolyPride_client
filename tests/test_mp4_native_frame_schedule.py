"""Production native frame proposal/acceptance invariants, without a GPU claim."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cstdint>
#include <cassert>
#include <string>
// PRODUCTION
int main(int argc,char**argv){
    assert(argc==2);std::string mode=argv[1];FrameSchedule schedule;
    if(mode=="invalid"){
        for(auto fps:{0U,24U,120U})assert(!schedule.reset(1,fps,2));
        assert(!schedule.reset(0,30,2));assert(!schedule.reset(1,30,0));
        assert(!schedule.reset(1,30,~uint64_t(0)));assert(!schedule.propose(1).advance);return 0;
    }
    const uint32_t fps=mode=="thirty"?30:60;assert(schedule.reset(37,fps,3));
    auto first=schedule.propose(37);assert(first.advance&&first.tick==0&&first.frame==0);
    if(mode=="rejected_clock"){
        // Clock rejection is not a commit; retry the same exact proposal.
        assert(schedule.next_tick()==0);auto again=schedule.propose(37);
        assert(again.tick==first.tick&&again.frame==first.frame);
    }
    if(mode=="stale"){
        assert(!schedule.commit(36,first));assert(!schedule.propose(36).advance);
        auto forged=first;forged.frame=1;assert(!schedule.commit(37,forged));
        forged=first;forged.tick=1;assert(!schedule.commit(37,forged));
    }
    assert(schedule.commit(37,first));assert(!schedule.commit(37,first));
    assert(!schedule.propose(37).advance);assert(!schedule.encoder_accepted(37,0));
    assert(!schedule.readback_received(36,0));assert(!schedule.readback_received(37,1));
    assert(schedule.readback_received(37,0));assert(!schedule.readback_received(37,0));
    if(mode=="retry")for(int i=0;i<20;++i){
        assert(!schedule.propose(37).advance);assert(schedule.next_tick()==1);
        assert(schedule.pixels_received()&&schedule.accepted_frames()==0);
    }
    assert(!schedule.encoder_accepted(36,0));assert(!schedule.encoder_accepted(37,1));
    assert(schedule.encoder_accepted(37,0));assert(!schedule.encoder_accepted(37,0));
    if(mode=="accept_then_reject"){
        auto proposal=schedule.propose(37);assert(proposal.tick==1);
        // A later rejected clock proposal does not undo the earlier accepted output.
        assert(schedule.accepted_frames()==1&&schedule.next_tick()==1);
        assert(schedule.propose(37).tick==proposal.tick);
    }
    uint64_t output=1;
    while(!schedule.complete()){
        auto proposal=schedule.propose(37);assert(proposal.advance);assert(schedule.commit(37,proposal));
        if(proposal.frame<0){assert(fps==30&&proposal.tick%2==1);continue;}
        assert(static_cast<uint64_t>(proposal.frame)==output);
        assert(proposal.tick==output*(60/fps));
        assert(schedule.readback_received(37,output));assert(schedule.encoder_accepted(37,output));++output;
    }
    assert(output==3&&schedule.accepted_frames()==3&&!schedule.awaiting_frame());
    assert(!schedule.propose(37).advance);assert(schedule.next_tick()==1+2*(60/fps));
    if(mode=="reset"){
        assert(schedule.reset(38,30,1));assert(!schedule.propose(37).advance);
        assert(!schedule.readback_received(37,0));assert(!schedule.encoder_accepted(37,0));
        auto next=schedule.propose(38);assert(next.tick==0&&next.frame==0);
    }
}
'''


@pytest.fixture(scope="module")
def schedule_binary(tmp_path_factory):
    compiler=shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:pytest.skip("C++ compiler required")
    source=(ROOT/"client-presentation/native/mp4_runtime.hpp").read_text()
    body=source.split("// BEGIN_MP4_NATIVE_FRAME_SCHEDULE",1)[1].split("// END_MP4_NATIVE_FRAME_SCHEDULE",1)[0]
    root=tmp_path_factory.mktemp("native-frame-schedule");code=root/"schedule.cpp";binary=root/"schedule"
    code.write_text(HARNESS.replace("// PRODUCTION",body))
    built=subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",str(code),"-o",str(binary)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stderr
    return binary


@pytest.mark.parametrize("mode",["invalid","thirty","sixty","stale","retry","rejected_clock","accept_then_reject","reset"])
def test_native_simulation_and_encoder_commits(schedule_binary,mode):
    result=subprocess.run([str(schedule_binary),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
