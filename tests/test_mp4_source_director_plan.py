"""Shipping readonly source plans and initial physical-capture bootstrap.

The actual bank, output/runtime closure and bootstrap bodies are extracted from
Bridge. Generic Script/Actor/Camera/World/Stage leaf validators remain explicit
models in the closure fixture; there is no engine/device/render-pass claim.
"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_mp4_child_source_host import marker

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'client-presentation/native'
FIX=ROOT/'tests/fixtures/mp4_source_plan'

@pytest.fixture(scope='module')
def source_plan_binaries(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('A host C++ compiler is required')
    text=(NATIVE/'bridge.cpp').read_text()
    folder=tmp_path_factory.mktemp('shipping-source-plan')
    context='struct Mp4TimelineList {'+text.split('struct Mp4TimelineList {',1)[1].split('void *mp4_timeline_class(',1)[0]
    prefix=(FIX/'bank-prefix.cpp.inc').read_text().replace('// ACTUAL_SOURCE_CONTEXT',context)
    # Keep the finite source phase contract tied to actual production bodies.
    enum='enum class Mp4TimelineProofPhase : uint8_t {'+text.split('enum class Mp4TimelineProofPhase : uint8_t {',1)[1].split('};',1)[0]+'};'
    helper='bool mp4_timeline_source_plan_phase('+text.split('bool mp4_timeline_source_plan_phase(',1)[1].split('}',1)[0]+'}'
    prefix=prefix.replace('enum class Mp4TimelineProofPhase:uint8_t{admission=0,active=1,source_bootstrap_plan=4};',enum)
    prefix=prefix.replace('bool mp4_timeline_source_plan_phase(Mp4TimelineProofPhase p){return p==Mp4TimelineProofPhase::admission||p==Mp4TimelineProofPhase::source_bootstrap_plan;}',helper)

    host=marker(text,'MP4_SOURCE_DIRECTOR_PLAN_HOST')
    close=marker(text,'MP4_SOURCE_DIRECTOR_PLAN_CLOSURE_HOST')
    setup=(FIX/'bank-main.cpp.inc').read_text().split(' if(model.mode==1)',1)[0]
    models={'bank':prefix+host+(FIX/'bank-main.cpp.inc').read_text()}
    audio='struct Mp4AudioProgramClip {'+text.split('struct Mp4AudioProgramClip {',1)[1].split('// Parent Timeline component proves',1)[0]
    cp=prefix.replace('struct Mp4AudioProgramImage{};',audio)
    cp=cp.replace('struct{mp4game::Binding get_game_object;}mp4_actor_profile;', 'struct{mp4game::Binding get_game_object;struct{size_t slot_output=0x28;}native_output;}mp4_actor_profile;')
    cp+='struct Mp4TimelineRuntime {'+text.split('struct Mp4TimelineRuntime {',1)[1].split('struct Mp4TimelineProducer',1)[0]
    cp=cp.replace('struct{int root=1;}mp4_timeline_pins;bool mp4_timeline_exact(void*,int){return model.mode!=16;}', 'struct{int root=1,clip=2,scheduled=3,infinite=4;}mp4_timeline_pins;extern bool audio_mode;extern uint8_t audio_element[64];bool mp4_timeline_exact(void*object,int kind){if(object==audio_element)return kind==3;return kind==1;}')
    cp=cp.replace('bool mp4_timeline_tracks(Mp4TimelineContext&){return model.mode!=18;}', 'bool mp4_timeline_tracks(Mp4TimelineContext&);').replace('bool mp4_timeline_runtime_elements(Mp4TimelineContext&,bool verify){assert(!verify);return model.mode!=20;}', 'bool mp4_timeline_runtime_elements(Mp4TimelineContext&,bool);')
    # Deliberate boundary: all generic node producer leaves are fixture services.
    # Exact new Audio/node classification, runtime mapping and ordered outputs,
    # whole intrusive output list and recursion/readers execute shipping bodies.
    start=close.index('bool mp4_source_plan_nodes(')
    end=close.index('bool mp4_source_director_plan_close(',start)
    closed=close[:start]+'bool mp4_source_director_plan(const Mp4TimelineContext&,void*,void*);\nbool mp4_source_plan_nodes(Mp4SourcePlanEntry&entry){return plan_nodes(entry);}\n'+close[end:]
    models['closure']=cp+(FIX/'closure-prefix.cpp.inc').read_text()+host+closed+setup.replace('model.mode=atoi(argv[1]);','const int test=atoi(argv[1]);model.mode=0;')+(FIX/'closure-main.cpp.inc').read_text()
    bp=prefix.replace('struct PlayableGraph{uintptr_t handle=0;', 'struct PlayableGraph{void*handle=nullptr;')
    bp=bp.replace('struct{bool active=false;}mp4_scene_host;', 'struct{bool active=true,invalidated=false,releasing=false;unsigned configured=7;Mp4SceneWitness source{};}mp4_scene_host;struct{bool active=false;}mp4_rebuild_ledger;')
    bp=bp.replace('*out={(uintptr_t)r->graph,2,0};','*out={r->graph,2,0};')
    bp=bp.replace('struct{decltype(&get_graph)director_graph_injected=get_graph;}mp4_api;', 'void*get_asset(void*d,Method*){auto*r=by_director(d);return r?r->asset:nullptr;}\nstruct{decltype(&get_graph)director_graph_injected=get_graph;decltype(&get_asset)director_get_asset=get_asset;}mp4_api;\nstruct{mp4game::Binding director_get_asset,director_graph_injected;}mp4_profile;\nbool held=true,acquiring=true;namespace idoly_mp4_playback{enum class Phase{acquiring,restoring};}namespace idoly_mp4_runtime{struct{ idoly_mp4_playback::Phase automatic_rebuild_phase(){return ::acquiring?idoly_mp4_playback::Phase::acquiring:idoly_mp4_playback::Phase::restoring;}}game;}\nbool mp4_actor_clock_held(void*){return held;}bool mp4_scene_source_current(){return model.phase;}\nvoid*mp4_child_factory_original=(void*)0x111;bool mp4_source_factory_bindings(void*,void*p){return p==mp4_child_factory_original&&model.pins;}')
    bp=bp.replace('bool mp4_exact_type(void*p,const char*){return by_director(p)&&!(model.mode==11&&p==model.roots[1].director);}', 'bool mp4_exact_type(void*p,const char*type){if(!std::strcmp(type,"UnityEngine.Timeline.TimelineAsset")){for(auto&r:model.roots)if(p==r.asset)return true;return false;}return by_director(p)!=nullptr;}')
    models['bootstrap']=bp+marker(text,'MP4_SOURCE_BOOTSTRAP_ROOTS_HOST')+setup+(FIX/'bootstrap-main.cpp.inc').read_text()
    binaries={}
    for name,body in models.items():
        path,binary=folder/(name+'.cpp'),folder/name
        path.write_text(body)
        result=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie','-I',str(NATIVE),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        binaries[name]=binary
    return binaries

@pytest.mark.parametrize('mode',range(35))
def test_shipping_retained_all_root_source_contexts(source_plan_binaries,mode):
    result=subprocess.run([str(source_plan_binaries['bank']),str(mode)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr

@pytest.mark.parametrize('mode',range(27))
def test_shipping_finite_output_audio_runtime_and_reader_closure(source_plan_binaries,mode):
    result=subprocess.run([str(source_plan_binaries['closure']),str(mode)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr

@pytest.mark.parametrize('mode',range(27))
def test_shipping_direct_source_bootstrap_has_no_owned_image_grant(source_plan_binaries,mode):
    result=subprocess.run([str(source_plan_binaries['bootstrap']),str(mode)],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
