"""Verify immutable MV selection capture against a synthetic managed heap.

These are native-boundary tests, not Unity, device, or detached-render evidence.
The fixture uses the audited Idoly 6.1.1 field layout and exposes no game objects
through the persisted descriptor.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

SOURCE = r'''
#include "mp4_selection_capture.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <vector>
using idoly_mp4_selection::Api;
using idoly_mp4_selection::Capture;
using idoly_mp4_selection::Layout;
using idoly_mp4_selection::Result;
using idoly_mp4_queue::Descriptor;

struct Object {
    alignas(16) std::array<unsigned char,256> memory{};
    std::string type,text;
    std::vector<void*> items;
};
std::vector<std::unique_ptr<Object>> heap;
std::map<void*,Object*> objects;
std::map<uint32_t,void*> handles;
uint32_t serial=1;
Object* make(const char* type,const char* text="") {
    auto item=std::make_unique<Object>();item->type=type;item->text=text;
    Object* out=item.get();objects[out->memory.data()]=out;
    heap.push_back(std::move(item));return out;
}
void* ptr(Object* o){return o?o->memory.data():nullptr;}
template<class T> void put(Object* o,size_t offset,T value) {
    assert(o&&offset+sizeof(value)<=o->memory.size());
    std::memcpy(o->memory.data()+offset,&value,sizeof(value));
}
bool is_type(void* p,const char* type) {
    auto found=objects.find(p);
    return found!=objects.end()&&found->second->type==type;
}
bool alive(void* p){return p&&objects.count(p);}
uint32_t retain(void* p){if(!alive(p))return 0;handles[serial]=p;return serial++;}
void* retained(uint32_t h){auto found=handles.find(h);return found==handles.end()?nullptr:found->second;}
void release(uint32_t h){assert(handles.erase(h)==1);}
size_t array_length(void* p){assert(alive(p));return objects.at(p)->items.size();}
void* array_data(void* p){assert(alive(p));return objects.at(p)->items.data();}
size_t string_utf8(void* p,char* out,size_t cap) {
    if(!p)return 0;assert(is_type(p,"System.String"));const auto& text=objects.at(p)->text;
    if(text.size()<cap)std::memcpy(out,text.c_str(),text.size()+1);
    return text.size();
}
Api api() {
    Api a{};a.is_type=is_type;a.alive=alive;a.retain=retain;
    a.retained=retained;a.release=release;a.array_length=array_length;
    a.array_data=array_data;a.string_utf8=string_utf8;return a;
}
Object* string(const char* text){return make("System.String",text);}
Object* array(std::initializer_list<void*> items) {
    auto* a=make("array");a->items=items;return a;
}
Object* list(Object* backing,int32_t count) {
    auto* l=make("System.Collections.Generic.List`1");
    put(l,0x10,ptr(backing));put(l,0x18,count);return l;
}
struct Fixture {
    Object *player,*param,*actors,*actor_array,*actor,*descriptor,*assets,*asset_array;
    Object *stage,*timeline,*character,*name,*asset0,*asset1;
    Fixture() {
        player=make("Solis.Common.SolisLivePlayer");
        param=make("Solis.OutGame.OutGameLivePlayerParam");
        stage=string("scn_live_stage-001");timeline=string("scn_live_short-tri-004");
        character=string("rei");name=string("actor_rei");
        asset0=string("mdl_rei-body-001");asset1=string("mdl_rei-hair-001");
        asset_array=array({ptr(asset0),ptr(asset1)});assets=list(asset_array,2);
        descriptor=make("Solis.Common.SolisActorDescriptor");
        put(descriptor,0x10,ptr(assets));put(descriptor,0x18,ptr(name));
        put(descriptor,0x20,static_cast<void*>(nullptr));
        put(descriptor,0x28,uint8_t(1));put(descriptor,0x2c,int32_t(1));
        put(descriptor,0x30,uint8_t(1));put(descriptor,0x31,uint8_t(1));
        put(descriptor,0x32,uint8_t(0));put(descriptor,0x34,int32_t(7));
        actor=make("SolisLiveActorParam");
        put(actor,0x10,ptr(character));put(actor,0x18,int32_t(5));
        put(actor,0x1c,int32_t(4));put(actor,0x20,int32_t(2));
        put(actor,0x28,ptr(descriptor));put(actor,0x30,int32_t(150));
        actor_array=array({ptr(actor)});actors=list(actor_array,1);
        put(param,0x10,ptr(actors));put(param,0x18,ptr(stage));
        put(param,0x20,ptr(timeline));put(param,0x28,uint8_t(0));
        put(param,0x2c,int32_t(500));
    }
};
void succeeds(Capture& c,Fixture& f,Descriptor& d) {
    const Result result=c.observe(ptr(f.player),ptr(f.param));
    if(result!=Result::ok)std::fprintf(stderr,"Selection rejected: %s\n",c.error());
    assert(result==Result::ok);
    assert(c.selected(ptr(f.player),d)==Result::ok);
}
void fails_at(Capture& c,Fixture& f,int line) {
    const Result result=c.observe(ptr(f.player),ptr(f.param));
    if(result==Result::ok)std::fprintf(stderr,"Unexpected accepted selection at harness line %d\n",line);
    assert(result!=Result::ok);
    Descriptor d{};assert(c.selected(ptr(f.player),d)!=Result::ok);
    assert(c.error()&&c.error()[0]);
}
#define fails(c,f) fails_at(c,f,__LINE__)
void immutable() {
    Capture c;assert(c.set_api(api(),Layout{}));Fixture f;Descriptor captured{};
    succeeds(c,f,captured);assert(captured.actor_count==1);
    assert(!std::strcmp(captured.stage_asset,"scn_live_stage-001"));
    assert(!std::strcmp(captured.timeline_asset,"scn_live_short-tri-004"));
    assert(captured.stage_max_capacity==500&&!captured.detach_actors_on_player_destroyed);
    const auto& a=captured.actors[0];
    assert(!std::strcmp(a.character_id,"rei")&&!std::strcmp(a.descriptor_name,"actor_rei"));
    assert(a.actor_index==5&&a.track_index==2&&a.audience_amount==150&&a.psyllium_color_type==4);
    assert(a.asset_count==2&&!std::strcmp(a.assets[0],"mdl_rei-body-001"));
    assert(!std::strcmp(a.assets[1],"mdl_rei-hair-001"));
    assert(a.humanoid==1&&a.collider_type==1&&a.trigger==1&&a.auto_blink_disabled==1);
    assert(a.use_adv_settings==0&&a.render_layer_base==7&&!a.name_is_null);
    f.stage->text="changed_stage";f.timeline->text="changed_timeline";
    f.character->text="mana";f.name->text="changed_actor";
    f.asset0->text="mdl_changed";f.asset1->text="mdl_changed_hair";
    f.asset_array->items.clear();put(f.assets,0x18,int32_t(0));
    f.actor_array->items.clear();put(f.actors,0x18,int32_t(0));
    put(f.actor,0x18,int32_t(99));put(f.descriptor,0x34,int32_t(99));
    Descriptor again{};assert(c.selected(ptr(f.player),again)==Result::ok);
    assert(!std::memcmp(&captured,&again,sizeof(again)));
    // Caller-owned copies cannot mutate the cached logical selection either.
    again.actors[0].assets[0][0]='X';again.actor_count=0;
    assert(c.selected(ptr(f.player),again)==Result::ok&&again.actor_count==1);
    assert(!std::strcmp(again.actors[0].assets[0],"mdl_rei-body-001"));
    auto* other=make("Solis.Common.SolisLivePlayer");
    assert(c.selected(ptr(other),again)!=Result::ok);
    c.reset();assert(handles.empty());
}
void lifetimes() {
    Capture c;assert(c.set_api(api(),Layout{}));Fixture f;Descriptor d{};
    succeeds(c,f,d);
    // A failed reinitialization cannot silently reuse the previous MV snapshot.
    f.param->type="Solis.Common.SolisLivePlayerParam";fails(c,f);
    f.param->type="Solis.OutGame.OutGameLivePlayerParam";succeeds(c,f,d);
    objects.erase(ptr(f.player));
    assert(c.selected(ptr(f.player),d)!=Result::ok);c.maintenance();
    c.reset();assert(handles.empty());
    // Losing a retained root must not expose a cached logical selection.
    Fixture g;succeeds(c,g,d);
    for(auto& h:handles)h.second=nullptr;
    assert(c.selected(ptr(g.player),d)!=Result::ok);
    c.maintenance();c.reset();assert(handles.empty());
}
void bounded_cache() {
    Capture c;assert(c.set_api(api(),Layout{}));
    std::vector<std::unique_ptr<Fixture>> fixtures;
    Descriptor d{};
    for(size_t i=0;i<17;++i){fixtures.push_back(std::make_unique<Fixture>());succeeds(c,*fixtures.back(),d);}
    assert(c.selected(ptr(fixtures.front()->player),d)!=Result::ok);
    assert(c.selected(ptr(fixtures.back()->player),d)==Result::ok);
    // Cache bounds also bound retained Unity roots, not only copied descriptors.
    assert(handles.size()<=32);c.reset();assert(handles.empty());
}
void bounds_and_types() {
    Capture c;assert(c.set_api(api(),Layout{}));Descriptor d{};
    {
        Fixture f;put(f.actors,0x18,int32_t(-1));fails(c,f);
        put(f.actors,0x18,int32_t(0));fails(c,f);
        put(f.actors,0x18,int32_t(33));fails(c,f);
        put(f.actors,0x18,int32_t(2));fails(c,f); // length 1 cannot back size 2.
        put(f.actors,0x18,int32_t(1));succeeds(c,f,d);
        f.actor_array->items.resize(33,ptr(f.actor));succeeds(c,f,d);
        f.actor_array->items.resize(4097,ptr(f.actor));fails(c,f);
    }
    {
        Fixture f;put(f.assets,0x18,int32_t(-1));fails(c,f);
        put(f.assets,0x18,int32_t(0));fails(c,f);
        put(f.assets,0x18,int32_t(17));fails(c,f);
        put(f.assets,0x18,int32_t(3));fails(c,f); // length 2 cannot back size 3.
        put(f.assets,0x18,int32_t(2));succeeds(c,f,d);
        f.asset_array->items.resize(17,ptr(f.asset0));succeeds(c,f,d);
        f.asset_array->items.resize(4097,ptr(f.asset0));fails(c,f);
    }
    {
        Fixture f;f.actor->type="UnityEngine.GameObject";fails(c,f);
        f.actor->type="SolisLiveActorParam";f.descriptor->type="VL.VLActorDescriptor";fails(c,f);
        f.descriptor->type="Solis.Common.SolisActorDescriptor";
        f.actors->type="System.Object";fails(c,f);
        f.actors->type="System.Collections.Generic.List`1";
        f.assets->type="System.Object";fails(c,f);
        f.assets->type="System.Collections.Generic.List`1";
        f.stage->type="System.Object";fails(c,f);
        f.stage->type="System.String";f.asset0->type="System.Object";fails(c,f);
    }
    {
        Fixture f;f.stage->text=std::string(idoly_mp4_queue::name_capacity,'s');fails(c,f);
        f.stage->text="scn_stage";f.asset0->text="../not-an-asset";fails(c,f);
        f.asset0->text="mdl_body";put(f.actor,0x28,static_cast<void*>(nullptr));fails(c,f);
    }
    {
        Fixture f;
        for(int32_t i=1;i<32;++i) {
            auto* actor=make("SolisLiveActorParam");actor->memory=f.actor->memory;
            put(actor,0x18,int32_t(i+5));put(actor,0x20,int32_t(i+2));
            f.actor_array->items.push_back(ptr(actor));
        }
        put(f.actors,0x18,int32_t(32));succeeds(c,f,d);assert(d.actor_count==32);
        for(int32_t i=2;i<16;++i) {
            const std::string asset="mdl_accessory-"+std::to_string(i);
            f.asset_array->items.push_back(ptr(string(asset.c_str())));
        }
        put(f.assets,0x18,int32_t(16));succeeds(c,f,d);
        assert(d.actors[31].asset_count==16);
    }
    {
        Fixture f;put(f.param,0x28,uint8_t(2));fails(c,f);
        put(f.param,0x28,uint8_t(0));put(f.descriptor,0x28,uint8_t(2));fails(c,f);
        put(f.descriptor,0x28,uint8_t(1));put(f.descriptor,0x30,uint8_t(2));fails(c,f);
        put(f.descriptor,0x30,uint8_t(1));put(f.descriptor,0x2c,int32_t(2));fails(c,f);
    }
    c.reset();assert(handles.empty());
}
void gameobjects_and_duplicates() {
    Capture c;assert(c.set_api(api(),Layout{}));Descriptor d{};Fixture f;
    put(f.descriptor,0x18,static_cast<void*>(nullptr));succeeds(c,f,d);
    assert(d.actors[0].name_is_null==1&&!d.actors[0].descriptor_name[0]);
    f.name->text="";put(f.descriptor,0x18,ptr(f.name));succeeds(c,f,d);
    assert(d.actors[0].name_is_null==0&&!d.actors[0].descriptor_name[0]);
    f.name->text="actor_rei";
    auto* gameobjects=array({});put(f.descriptor,0x20,ptr(gameobjects));succeeds(c,f,d);
    gameobjects->items.push_back(ptr(make("UnityEngine.GameObject")));fails(c,f);
    put(f.descriptor,0x20,static_cast<void*>(nullptr));succeeds(c,f,d);
    // Distinct managed actor objects still cannot serialize colliding actor IDs.
    Fixture second;f.actor_array->items.push_back(ptr(second.actor));put(f.actors,0x18,int32_t(2));
    put(second.actor,0x20,int32_t(3));fails(c,f);
    put(second.actor,0x18,int32_t(6));put(second.actor,0x20,int32_t(2));fails(c,f);
    put(second.actor,0x20,int32_t(3));succeeds(c,f,d);assert(d.actor_count==2);
    c.reset();assert(handles.empty());
}
int main(int argc,char** argv) {
    assert(argc==2);std::string mode=argv[1];
    if(mode=="immutable")immutable();
    else if(mode=="cache")bounded_cache();
    else if(mode=="bounds")bounds_and_types();
    else if(mode=="gameobjects")gameobjects_and_duplicates();
    else if(mode=="lifetimes")lifetimes();
    else assert(false);
    assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def selection_capture_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    build = tmp_path_factory.mktemp("mp4-selection-capture")
    source = build / "capture.cpp"
    source.write_text(SOURCE)
    executable = build / "capture"
    warning_flags = ["-Wno-misleading-indentation"]
    if "g++" in Path(compiler).name:
        warning_flags.append("-Wno-class-memaccess")
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *warning_flags, "-I",
         str(ROOT / "client-presentation/native"), str(source), "-o", str(executable)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


@pytest.mark.parametrize("scenario", ["immutable", "lifetimes", "cache", "bounds", "gameobjects"])
def test_immutable_selection_boundary(selection_capture_binary, scenario):
    result = subprocess.run([str(selection_capture_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
