"""Exercise callback work on a 64 KiB host stack, using real native headers.

Unity storage and methods are synthetic. The bounded host stack verifies that
large value resets do not depend on a multi-megabyte caller stack; device stack
sizes and actual Unity rendering are not established by this test.
"""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_mp4_game_adapter import SOURCE as GAME_SOURCE
from test_mp4_selection_capture import SOURCE as CAPTURE_SOURCE

ROOT = Path(__file__).resolve().parents[1]

THREAD = r'''
#include <pthread.h>
#include <sys/resource.h>
void on_small_stack(void*(*work)(void*),void* context){
    rlimit limit{0,0};assert(setrlimit(RLIMIT_CORE,&limit)==0);
    pthread_attr_t attributes;assert(pthread_attr_init(&attributes)==0);
    assert(pthread_attr_setstacksize(&attributes,64*1024)==0);
    assert(pthread_attr_setguardsize(&attributes,4096)==0);
    pthread_t thread;assert(pthread_create(&thread,&attributes,work,context)==0);
    assert(pthread_attr_destroy(&attributes)==0);assert(pthread_join(thread,nullptr)==0);
}
'''

CAPTURE_DRIVER = r'''
struct Work {
    Capture* capture;Descriptor* output;Fixture* normal;Fixture* photo;
    Object *data,*descriptors,*transition;idoly_mp4_queue::Queue* queue;
};
void* capture_on_stack(void* context){
    auto& w=*static_cast<Work*>(context);
    for(unsigned repeat=0;repeat<4;++repeat){
        assert(w.capture->observe(ptr(w.normal->player),ptr(w.normal->param))==Result::ok);
        assert(w.capture->selected(ptr(w.normal->player),*w.output)==Result::ok);
        assert(w.output->actor_count==1&&!w.output->photo.source_kind);
        assert(w.output->actors[0].render_layer_base==7&&w.output->stage_max_capacity==500);
        assert(w.capture->observe_photography(ptr(w.photo->player),ptr(w.data),ptr(w.descriptors))==Result::waiting);
        assert(w.capture->attach_photography_transition(ptr(w.photo->player),ptr(w.transition))==Result::ok);
        assert(w.capture->selected(ptr(w.photo->player),*w.output)==Result::ok);
        assert(w.output->photo.source_kind==1&&w.output->photo.actor_count==1);
        assert(!std::strcmp(w.output->photo.actors[0].costume_id,"costume-rei"));
        idoly_mp4_queue::Options options{};options.width=1280;options.height=720;char id[33]{};
        assert(w.queue->enqueue(*w.output,options,id)==idoly_mp4_queue::Error::ok);
        assert(w.queue->remove(id)==idoly_mp4_queue::Error::ok&&w.queue->count()==0);
    }
    w.capture->reset();assert(handles.empty());return nullptr;
}
int main(int argc,char** argv){
    assert(argc==2);auto capture=std::make_unique<Capture>();auto output=std::make_unique<Descriptor>();
    assert(capture->set_api(api()));Fixture normal,photo;
    photo.player->type="Solis.Common.Photography.PhotographyLive3DPresenter";
    auto* data=make("Solis.Common.Photography.PhotographyLiveData");
    auto* characters=array({ptr(photo.character)});characters->type="System.String[]";
    auto* descriptors=array({ptr(photo.descriptor)});descriptors->type="Solis.Common.SolisActorDescriptor[]";
    put(data,0x10,ptr(photo.stage));put(data,0x18,ptr(photo.timeline));put(data,0x20,ptr(descriptors));put(data,0x28,ptr(characters));
    auto* transition=make("Solis.Photography.Data.PhotographyLiveTransitionData");
    auto* stage=make("Solis.Common.Proto.Master.PhotoQuestStage");auto* music=make("Solis.Common.Proto.Master.PhotoQuestMusic");
    put(stage,0x18,ptr(string("stage-rei")));put(music,0x18,ptr(string("music-rei")));
    auto* costume=make("Solis.Common.Data.ActorCostume");auto* dress=make("Solis.Common.Proto.Master.Costume");auto* hair=make("Solis.Common.Proto.Master.Hair");
    put(dress,0x18,ptr(string("costume-rei")));put(hair,0x18,ptr(string("hair-rei")));put(costume,0x10,ptr(dress));put(costume,0x18,ptr(hair));
    put(transition,0x48,ptr(list(array({ptr(costume)}),1)));put(transition,0x68,ptr(stage));put(transition,0x70,ptr(music));
    idoly_mp4_queue::Queue queue;assert(queue.open(argv[1],"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")==idoly_mp4_queue::Error::ok);
    Work work{capture.get(),output.get(),&normal,&photo,data,descriptors,transition,&queue};on_small_stack(capture_on_stack,&work);
}
'''

GAME_BASE, GAME_MAIN = GAME_SOURCE.split("int main(){", 1)
CONNECT = GAME_MAIN.split("Api selected_api=api();", 1)[0]
GAME_BASE = GAME_BASE.replace('#include "mp4_game_adapter.hpp"', '#include "mp4_runtime.hpp"')

RUNTIME_DRIVER = r'''
namespace runtime=idoly_mp4_runtime;
extern "C" IDMP4EncoderHandle IDMP4EncoderCreate(const IDMP4EncoderConfig*,char*,size_t){assert(false);return nullptr;}
extern "C" int IDMP4EncoderAppendFrame(IDMP4EncoderHandle,const uint8_t*,size_t,uint64_t){assert(false);return -1;}
extern "C" int IDMP4EncoderPoll(IDMP4EncoderHandle,IDMP4EncoderStatus*){assert(false);return -1;}
extern "C" int IDMP4EncoderFinish(IDMP4EncoderHandle){assert(false);return -1;}
extern "C" void IDMP4EncoderCancel(IDMP4EncoderHandle){assert(false);}
extern "C" int IDMP4EncoderDestroy(IDMP4EncoderHandle){assert(false);return -1;}
void* runtime_on_stack(void*){
    // Poison real storage first: a raw zeroing replacement would lose fd=-1,
    // codec/fps/bitrate and status member defaults, which this rejects.
    std::memset(&runtime::job,0xa5,sizeof(runtime::job));
    idoly_mp4_queue::detail::reset_value(runtime::job);
    const auto& job=runtime::job;
    assert(job.config.root==-1&&job.config.req==-1&&job.config.rsp==-1&&job.config.prepared==-1&&job.config.exports==-1);
    assert(job.options.fps_num==30&&job.options.fps_den==1&&job.options.codec==1&&job.options.bitrate==16000000&&job.options.audio_bitrate==192000);
    assert(!std::strcmp(job.status.phase,"idle")&&!std::strcmp(job.status.error,"none"));
    assert(job.pcm==-1&&!job.encoder&&!job.rgba&&job.stage==runtime::Stage::idle);
    for(float value:job.source)assert(value==0);for(float value:job.mixed_pcm)assert(value==0);
    for(unsigned tick=0;tick<16;++tick){assert(!runtime::begin_job());runtime::on_unity_tick();}
    assert(runtime::job.stage==runtime::Stage::idle&&!runtime::control_busy&&!runtime::start_pending);
    return nullptr;
}
int main(){
    connect_scene();Api selected=api();selected.source_geometry=actual_source_geometry;
    runtime::install_game_api(selected,Layout{});runtime::observe_presenter(ptr(presenter));runtime::observe_camera_controller(ptr(camera_controller));
    on_small_stack(runtime_on_stack,nullptr);runtime::game.reset_observations();runtime::selection.reset();assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def small_stack_binaries(tmp_path_factory):
    if sys.platform != "linux":
        pytest.skip("The bounded host pthread-stack fixture runs on Linux")
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("C++ compiler required")
    folder = tmp_path_factory.mktemp("mp4-small-stack")
    programs = {
        "capture": CAPTURE_SOURCE.split("void succeeds(", 1)[0] + THREAD + CAPTURE_DRIVER,
        "runtime": GAME_BASE + THREAD + "\nvoid connect_scene(){\n" + CONNECT + "\n}\n" + RUNTIME_DRIVER,
    }
    binaries = {}
    # Match the shared managed-heap fixture's warning settings; its compact
    # callback definitions and deliberate value-storage poisoning are reused.
    warning_flags = ["-Wno-misleading-indentation"]
    predefined = subprocess.run([compiler,"-dM","-E","-x","c++","-"],input="",
        capture_output=True,text=True,timeout=10)
    assert predefined.returncode == 0, predefined.stderr
    macros = {line.split()[1] for line in predefined.stdout.splitlines() if line.startswith("#define ")}
    assert "__cplusplus" in macros
    # Clang defines __GNUC__ for compatibility; executable names and wrappers
    # do not identify which compiler's warning options are actually supported.
    if "__GNUC__" in macros and "__clang__" not in macros:
        warning_flags += ["-Wno-class-memaccess", "-Wno-format-truncation"]
    for name, program in programs.items():
        source, executable = folder / f"{name}.cpp", folder / name
        source.write_text(program)
        result = subprocess.run([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror",*warning_flags,"-pthread",
            "-I",str(ROOT / "client-presentation/native"),str(source),"-o",str(executable)],capture_output=True,text=True,timeout=45)
        assert result.returncode == 0, result.stderr
        binaries[name] = executable
    return binaries


def test_capture_and_queue_mutations_use_bounded_callback_stack(small_stack_binaries,tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir(mode=0o700)
    result = subprocess.run([str(small_stack_binaries["capture"]),str(queue)],capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr


def test_runtime_idle_tick_and_value_defaults_use_bounded_callback_stack(small_stack_binaries):
    result = subprocess.run([str(small_stack_binaries["runtime"])],capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr
