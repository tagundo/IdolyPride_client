#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
enum class Mp4SceneResult:int {ok=0,waiting=1,unsupported=-1,invalid=-2,failed=-3,stale=-4};
struct Mp4SceneWitness {uint64_t generation=0;void*source=nullptr;};
struct Mp4SceneHost {unsigned admitted=15;Mp4SceneWitness admitted_source{91,reinterpret_cast<void*>(91)};}mp4_scene_host;
struct Mp4ScenePart {void*context;Mp4SceneResult(*admit)(void*,const Mp4SceneWitness&);const char*(*error)(void*);};
bool mp4_scene_same_source(const Mp4SceneWitness&a,const Mp4SceneWitness&b){return a.generation==b.generation&&a.source==b.source;}
namespace idoly_mp4_runtime {
// DIAGNOSTIC_STRUCTS
struct Game {Mp4SceneWitness current{7,reinterpret_cast<void*>(7)};bool selected_scene_witness(Mp4SceneWitness&out){out=current;return true;}}game;
}
int calls[4]{},throw_family=-1,change_after=-1,failed_family=-1;
bool empty_error=false,none_error=false;
Mp4SceneResult result_for_failure=Mp4SceneResult::unsupported;
unsigned expected_mask=0;
Mp4SceneResult admit(void*context,const Mp4SceneWitness&witness){
    const unsigned family=static_cast<unsigned>(reinterpret_cast<uintptr_t>(context)-1);
    assert(family<4&&witness.generation==7&&mp4_scene_host.admitted_source.generation==7);
    assert(mp4_scene_host.admitted==expected_mask);++calls[family];
    if(static_cast<int>(family)==change_after)++idoly_mp4_runtime::game.current.generation;
    if(static_cast<int>(family)==throw_family)throw std::runtime_error("family admission fixture");
    if(static_cast<int>(family)==failed_family)return result_for_failure;
    expected_mask|=1u<<family;return Mp4SceneResult::ok;
}
const char*error(void*){return empty_error?"":none_error?"none":"actual_family_error";}
// SHIPPING_DIAGNOSTIC_DISPATCH
int main(int argc,char**argv){
    assert(argc==2);std::string mode=argv[1];bool verified[4]={true,true,true,true};
    const char*names[]={"actor","camera","stage","world"};
    for(int i=0;i<4;++i){if(mode==std::string(names[i])+"_failed")failed_family=i;if(mode==std::string(names[i])+"_throw")throw_family=i;}
    if(mode=="camera_wait"){failed_family=1;result_for_failure=Mp4SceneResult::waiting;}
    if(mode=="unverified")verified[1]=false;
    if(mode=="all_unverified")for(auto&v:verified)v=false;
    if(mode=="source_changed")change_after=0;
    if(mode=="empty_error"){failed_family=2;empty_error=true;}
    if(mode=="failed_none"){failed_family=2;none_error=true;}
    const Mp4ScenePart parts[4]={
        {reinterpret_cast<void*>(1),admit,error},{reinterpret_cast<void*>(2),admit,error},
        {reinterpret_cast<void*>(3),admit,error},{reinterpret_cast<void*>(4),admit,error}};
    idoly_mp4_runtime::NativeSceneDiagnostics out{};
    const auto witness=idoly_mp4_runtime::game.current; // Same frozen local copy as the real probe.
    mp4_scene_diagnostic_parts(witness,parts,verified,out);
    assert(out.available&&mp4_scene_host.admitted==15&&mp4_scene_host.admitted_source.generation==91);
    assert(mp4_scene_host.admitted_source.source==reinterpret_cast<void*>(91));
    for(int i=0;i<4;++i){
        const auto&p=out.parts[i];
        if(change_after==0){assert(p.result==-4&&!std::strcmp(p.error,"diagnostic_source_changed"));assert(calls[i]==(i==0));continue;}
        assert(calls[i]==static_cast<int>(verified[i]));
        if(!verified[i]){assert(p.result==-1&&!std::strcmp(p.error,"diagnostic_source_bindings_unverified"));continue;}
        if(i==throw_family){assert(p.result==-3&&!std::strcmp(p.error,"diagnostic_admission_exception"));continue;}
        if(i==failed_family){assert(p.result==static_cast<int>(result_for_failure));assert(!std::strcmp(p.error,(empty_error||none_error)?"diagnostic_admission_failed":"actual_family_error"));continue;}
        assert(p.result==0&&!std::strcmp(p.error,"none"));
    }
}
