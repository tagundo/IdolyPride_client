"""Execute original-typed graph/output traversal from the shipping bridge."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


def function(text,signature):
    start=text.index(signature);opening=text.index('{',start);depth=1;end=opening+1
    while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]


@pytest.fixture(scope='module')
def output_host(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:pytest.skip('Host C++ compiler required')
    text=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    actual='\n'.join(function(text,s)for s in ('bool mp4_director_graph_handle(', '[[maybe_unused]] bool mp4_director_graph_nodes(', '[[maybe_unused]] bool mp4_director_output_handle(', '[[maybe_unused]] bool mp4_director_output_source('))
    prefix=r'''
#include "mp4_actor_state.hpp"
#include "mp4_engine_clock.hpp"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
namespace mp4actor=idoly_mp4_actor;namespace mp4world=idoly_mp4_world;
using Method=const void;
bool mp4_output_calls_verified=true,current=true,graph_valid=true,wrong_graph=false;int32_t reported=3;
mp4actor::Handle graph{100,3,0};std::vector<uintptr_t> roots{1};std::map<uintptr_t,std::vector<uintptr_t>>edges{{1,{2,3}},{2,{}},{3,{}}};
using H=mp4actor::Handle;
bool valid_graph(H* h,Method*){return graph_valid&&h->handle==graph.handle&&h->version==graph.version;}
bool valid_node(H* h,Method*){return edges.count(h->handle)&&h->version==3;}
int32_t root_count(H*,Method*){return static_cast<int32_t>(roots.size());}
void root_get(H*,int32_t i,H* out,Method*){*out={roots.at(i),3,0};}
int32_t input_count(H* h,Method*){return static_cast<int32_t>(edges.at(h->handle).size());}
void input_get(H* h,int32_t i,H* out,Method*){const auto value=edges.at(h->handle).at(i);*out={value,3,0};}
int32_t graph_count(H*,Method*){return reported;}
void graph_get(H*,H* out,Method*){*out=graph;if(wrong_graph)++out->handle;}
struct Api{decltype(&valid_graph)graph_valid=valid_graph;decltype(&valid_node)playable_valid=valid_node;decltype(&root_count)graph_root_count=root_count;decltype(&root_get)graph_root=root_get;decltype(&input_count)playable_input_count=input_count;decltype(&input_get)playable_input=input_get;};
Api mp4_actor_state_api(){return {};}
bool mp4_scene_registry_current_graph(uintptr_t n,uintptr_t s,uint32_t v){return current&&n==200&&s==graph.handle&&v==2;}
bool mp4_scene_graph_owned_version(uintptr_t s,uint32_t v,bool normalized,H* out){assert(normalized);if(!current||s!=graph.handle||v!=2)return false;*out=graph;return true;}
uintptr_t image_base=0;
struct Pin{uintptr_t rva;};
struct OutputPins{Pin graph_count{reinterpret_cast<uintptr_t>(&::graph_count)},source;}mp4_output_pins;
struct ActorPins{Pin playable_graph_get{reinterpret_cast<uintptr_t>(&graph_get)};struct NativeOutput{uint32_t slot_output=40;}native_output;}mp4_actor_profile;
std::vector<mp4world::AnimationOutput> outputs{{300,3,0},{301,3,0}};std::map<uintptr_t,uintptr_t> native{{300,500},{301,501}};
int32_t output_count(H*,Method*){return static_cast<int32_t>(outputs.size());}
void output_get(H*,int32_t i,mp4world::AnimationOutput* out,Method*){*out=outputs.at(i);}
bool output_valid(mp4world::AnimationOutput* out,Method*){return native.count(out->handle)&&out->version==3;}
void source_get(mp4world::AnimationOutput*,H* out,Method*){*out={1,3,0};}
struct WorldPins{Pin graph_output_count{reinterpret_cast<uintptr_t>(&output_count)},graph_output{reinterpret_cast<uintptr_t>(&output_get)},output_valid{reinterpret_cast<uintptr_t>(&::output_valid)};}mp4_world_profile;
bool mp4_actor_field(void* object,size_t offset,uintptr_t& out){assert(offset==40);const auto slot=reinterpret_cast<uintptr_t>(object);if(!native.count(slot))return false;out=native[slot];return true;}
'''
    driver=r'''
int main(int argc,char**argv){assert(argc==2);std::string mode=argv[1];mp4world::DirectorGraphIdentity identity{200,100,2,0,0,0};
    mp4_output_pins.source.rva=reinterpret_cast<uintptr_t>(&source_get);
    if(mode=="source_unverified")mp4_output_calls_verified=false;
    if(mode=="source_changed")current=false;
    if(mode=="invalid_graph")graph_valid=false;
    if(mode=="wrong_node_graph")wrong_graph=true;
    if(mode=="unknown_node")edges[1].push_back(4);
    if(mode=="omitted_disconnected")++reported;
    if(mode=="cycle")edges[3].push_back(1);
    if(mode=="shared_cycle"){roots={1,3};edges={{1,{2}},{2,{3}},{3,{4}},{4,{2}}};reported=4;}
    if(mode=="zero_input")edges[1].push_back(0);
    if(mode=="shared_dag")edges[2].push_back(3);
    if(mode=="negative_count")reported=-1;
    if(mode=="over_capacity")reported=4097;
    H nodes[16]{};size_t used=99;
    const bool traversed=mp4_director_graph_nodes(identity,nodes,16,&used);
    const bool expected=mode=="normal"||mode=="zero_input"||mode=="shared_dag"||mode.rfind("output_",0)==0;
    assert(traversed==expected);
    if(traversed)assert(used==3);
    if(mode.rfind("output_",0)==0){
        if(mode=="output_duplicate")native[301]=500;
        if(mode=="output_invalid")outputs[1].version=4;
        if(mode=="output_missing")native[300]=502;
        mp4world::AnimationOutput result{};
        const bool found=mp4_director_output_handle(identity,500,&result);
        assert(found==(mode=="output_normal"));
        if(found){H source{};assert(result.handle==300&&mp4_director_output_source(result,&source)&&source.handle==1);}
    }
}
'''
    folder=tmp_path_factory.mktemp('output-host');source=folder/'test.cpp';binary=folder/'test'
    source.write_text(prefix+actual+driver)
    result=subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return binary


@pytest.mark.parametrize('mode',['normal','source_unverified','source_changed','invalid_graph','wrong_node_graph','unknown_node','omitted_disconnected','cycle','shared_cycle','zero_input','shared_dag','negative_count','over_capacity','output_normal','output_duplicate','output_invalid','output_missing'])
def test_shipping_traversal_does_not_omit_graph_producers_or_ambiguate_native_outputs(output_host,mode):
    result=subprocess.run([str(output_host),mode],capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
