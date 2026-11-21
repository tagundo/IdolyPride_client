"""Exercise managed replay construction, GC roots and typed field barriers.

The fake collector runs before managed allocation and original List.Add/ctor
work. These tests do not claim Unity navigation or device validation.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_replay_factories.hpp"
#include <cassert>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly_mp4_replay_factories;
struct Class;
struct Type {int32_t kind;Class* klass;};
struct Field {std::string name;Type type;};
struct Class {std::string space,name;Class* parent=nullptr;std::vector<std::unique_ptr<Field>> fields;};
struct Object {Class* klass;bool alive=true,marked=false,constructed=false;std::map<Field*,Object*> refs;std::map<Field*,int32_t> values;std::vector<Object*> items;};
struct ManagedMethod {void(*pointer)();};
std::vector<std::unique_ptr<Class>> classes;
std::vector<std::unique_ptr<Object>> objects;
std::map<uint32_t,Object*> handles;uint32_t serial=1;
int allocation_fail=-1,retain_fail=-1;bool throw_ctor=false,throw_add=false;
int barriers=0,constructors=0,adds=0;
Class *outgame,*descriptor,*transition,*commonparam,*defaultdesc,*assetdesc,*listclass,*otherlist,*stringclass,*arrayclass,*colliderclass,*intclass,*boolclass;
Field *assetsfield,*namefield,*gameobjectsfield,*livefield,*colliderfield,*renderfield;
void mark(Object* o){if(!o||o->marked||!o->alive)return;o->marked=true;for(auto& r:o->refs)mark(r.second);for(auto* value:o->items)mark(value);}
void collect(){for(auto& o:objects)o->marked=false;for(auto& h:handles)mark(h.second);for(auto& o:objects)if(!o->marked)o->alive=false;}
Class* klass(const char* space,const char* name,Class* parent=nullptr){auto c=std::make_unique<Class>();c->space=space;c->name=name;c->parent=parent;auto* p=c.get();classes.push_back(std::move(c));return p;}
Field* field(Class* owner,const char* name,int32_t kind,Class* type=nullptr){auto f=std::make_unique<Field>();f->name=name;f->type={kind,type};auto* p=f.get();owner->fields.push_back(std::move(f));return p;}
Object* allocate(Class* klass){collect();if(allocation_fail==0)return nullptr;if(allocation_fail>0)--allocation_fail;auto o=std::make_unique<Object>();o->klass=klass;auto* p=o.get();objects.push_back(std::move(o));return p;}
uint32_t retain(void* value,bool pinned){assert(!pinned);auto* o=static_cast<Object*>(value);assert(o&&o->alive);if(retain_fail==0)return 0;if(retain_fail>0)--retain_fail;handles[serial]=o;return serial++;}
void* target(uint32_t h){auto i=handles.find(h);return i==handles.end()?nullptr:i->second;}
void release(uint32_t h){assert(handles.erase(h)==1);}
struct Root {uint32_t handle=0;explicit Root(Object* o):handle(o?retain(o,false):0){}~Root(){if(handle)release(handle);}Object*get()const{return static_cast<Object*>(target(handle));}};
void* object_class(void* value){auto* o=static_cast<Object*>(value);assert(o&&o->alive);return o->klass;}
const char* class_name(void* c){return static_cast<Class*>(c)->name.c_str();}
const char* class_namespace(void* c){return static_cast<Class*>(c)->space.c_str();}
void* class_parent(void* c){return static_cast<Class*>(c)->parent;}
void* find_field(void* c,const char* name){for(auto& f:static_cast<Class*>(c)->fields)if(f->name==name)return f.get();return nullptr;}
const void* field_type(void* f){return &static_cast<Field*>(f)->type;}
void* class_from_type(const void* t){return static_cast<const Type*>(t)->klass;}
int32_t type_kind(const void* t){return static_cast<const Type*>(t)->kind;}
void* object_new(void* c){return allocate(static_cast<Class*>(c));}
void field_set(void* value,void* field,void* input){
    auto* o=static_cast<Object*>(value);auto* f=static_cast<Field*>(field);assert(o&&o->alive);++barriers;
    if(f->type.kind==2){assert(input);o->values[f]=*static_cast<uint8_t*>(input);}
    else if(f->type.kind==8||f->type.kind==17){assert(input);o->values[f]=*static_cast<int32_t*>(input);}
    else {
        // Actual pinned Field.SetValueRaw(w3=0) reference branch stores input
        // directly. A native address-of-object-pointer must never enter the
        // managed object graph, even if dereferencing it would look plausible.
        auto* ref=static_cast<Object*>(input);bool registered=!ref;
        for(const auto& candidate:objects)if(candidate.get()==ref)registered=true;
        assert(registered&&(!ref||(ref->alive&&ref->klass==f->type.klass)));
        o->refs[f]=ref;
    }
}
void original_ctor(void* value,Method* method);
void original_add(void* list,void* value,Method* method);
ManagedMethod ctor_method{reinterpret_cast<void(*)()>(original_ctor)},add_method{reinterpret_cast<void(*)()>(original_add)};
Method* method(void* c,const char* name,int32_t count){if(c!=listclass)return nullptr;if(!std::strcmp(name,".ctor")&&count==0)return &ctor_method;if(!std::strcmp(name,"Add")&&count==1)return &add_method;return nullptr;}
void original_ctor(void* value,Method* method){auto* list=static_cast<Object*>(value);assert(method==&ctor_method&&list->klass==listclass&&list->alive);++constructors;collect();assert(list->alive);if(throw_ctor)throw std::runtime_error("constructor failure");Object* backing=allocate(arrayclass);if(!backing)throw std::runtime_error("array allocation failure");list->items.push_back(backing);list->constructed=true;}
void original_add(void* list_value,void* value,Method* method){auto* list=static_cast<Object*>(list_value);auto* item=static_cast<Object*>(value);assert(method==&add_method&&list->klass==listclass&&list->constructed&&item->klass==stringclass);++adds;collect();assert(list->alive&&item->alive);if(throw_add)throw std::runtime_error("add failure");Object* backing=allocate(arrayclass);if(!backing)throw std::runtime_error("array allocation failure");list->items.push_back(backing);list->items.push_back(item);}
Calls calls(){Calls a{};a.object_class=object_class;a.class_name=class_name;a.class_namespace=class_namespace;a.class_parent=class_parent;a.field=find_field;a.field_type=field_type;a.class_from_type=class_from_type;a.object_new=object_new;a.method=method;a.strong_new=retain;a.target=target;a.release=release;a.type_get_type=type_kind;a.field_set_value=field_set;return a;}
Classes roots(){return {outgame,descriptor,transition};}
void setup(){
    stringclass=klass("System","String");arrayclass=klass("UnityEngine","GameObject[]");
    intclass=klass("System","Int32");boolclass=klass("System","Boolean");colliderclass=klass("VL","VLActorColliderType");
    listclass=klass("System.Collections.Generic","List`1");otherlist=klass("System.Collections.Generic","List`1");
    commonparam=klass("Solis.Common","SolisLivePlayerParam");outgame=klass("Solis.OutGame","OutGameLivePlayerParam",commonparam);
    assetdesc=klass("VL","VLActorAssetDescriptor");defaultdesc=klass("VL","VLDefaultActorDescriptor",assetdesc);
    descriptor=klass("Solis.Common","SolisActorDescriptor",defaultdesc);transition=klass("Solis.OutGame","LivePlayerTransitionParam");
    field(outgame,"stageMaxCapacity",8,intclass);field(commonparam,"detachActorsOnPlayerDestroyed",2,boolclass);
    assetsfield=field(assetdesc,"_assets",21,listclass);namefield=field(assetdesc,"_name",14,stringclass);gameobjectsfield=field(assetdesc,"_gameObjects",29,arrayclass);
    field(defaultdesc,"_humanoid",2,boolclass);colliderfield=field(defaultdesc,"_colliderType",17,colliderclass);field(defaultdesc,"_colliderTrigger",2,boolclass);
    field(descriptor,"_autoBlinkDisabled",2,boolclass);field(descriptor,"_useADVSettings",2,boolclass);renderfield=field(descriptor,"_renderingLayerMaskBaseIndex",8,intclass);
    livefield=field(transition,"liveParam",18,outgame);field(transition,"isDebugMode",2,boolclass);
}
void rooting(){
    Factory f;assert(f.configure(calls(),roots()));
    {
        Root desc(static_cast<Object*>(f.new_object(Kind::actor_descriptor)));assert(desc.get()&&handles.size()==1);
        Object* list=static_cast<Object*>(f.new_field_list(desc.get(),"_assets"));assert(list&&list->constructed&&constructors==1);
        assert(desc.get()->refs[assetsfield]==list&&handles.size()==1&&barriers==1);
        // Only the descriptor root retains the list after its factory returns.
        Root text(allocate(stringclass));assert(list->alive);
        assert(f.list_add(list,text.get())&&adds==1&&handles.size()==2);
        assert(f.set_object(desc.get(),"_name",text.get()));
        assert(f.set_object(desc.get(),"_gameObjects",nullptr));
        assert(f.set_bool(desc.get(),"_autoBlinkDisabled",true));
        assert(f.set_bool(desc.get(),"_useADVSettings",false));
        assert(f.set_i32(desc.get(),"_renderingLayerMaskBaseIndex",23));
        assert(f.set_i32(desc.get(),"_colliderType",1));
        assert(desc.get()->values[renderfield]==23&&desc.get()->values[colliderfield]==1);
        Root param(static_cast<Object*>(f.new_object(Kind::out_game_param)));
        Root trans(static_cast<Object*>(f.new_object(Kind::transition_param)));
        assert(f.set_i32(param.get(),"stageMaxCapacity",500)&&f.set_bool(param.get(),"detachActorsOnPlayerDestroyed",false));
        assert(f.set_object(trans.get(),"liveParam",param.get())&&f.set_bool(trans.get(),"isDebugMode",false));
        assert(trans.get()->refs[livefield]==param.get());
    }
    assert(handles.empty());collect();for(auto& o:objects)assert(!o->alive);
}
void validation(){
    Factory f;assert(f.configure(calls(),roots()));Root desc(static_cast<Object*>(f.new_object(Kind::actor_descriptor)));
    Root name(allocate(stringclass)),wrong(allocate(otherlist)),array(allocate(arrayclass));
    const int before=barriers;
    assert(!f.set_object(desc.get(),"_assets",wrong.get()));assert(!f.set_object(desc.get(),"_assets",nullptr));
    assert(!f.set_object(desc.get(),"_gameObjects",array.get()));assert(!f.set_object(desc.get(),"_name",array.get()));
    assert(!f.set_i32(desc.get(),"_autoBlinkDisabled",1));assert(!f.set_bool(desc.get(),"_colliderType",true));
    assert(!f.set_i32(desc.get(),"_colliderType",2));assert(!f.set_bool(desc.get(),"stageMaxCapacity",true));
    assert(!f.set_object(desc.get(),"not_a_field",name.get()));assert(!f.new_field_list(desc.get(),"_name"));
    assert(!f.list_add(wrong.get(),name.get()));assert(barriers==before);
    assert(f.set_object(desc.get(),"_name",nullptr)&&desc.get()->refs[namefield]==nullptr);
    assert(f.set_object(desc.get(),"_name",name.get()));
    assert(!f.new_object(static_cast<Kind>(0)));
}
void faults(){
    Factory f;assert(f.configure(calls(),roots()));Root desc(static_cast<Object*>(f.new_object(Kind::actor_descriptor)));
    size_t before=handles.size();allocation_fail=0;assert(!f.new_object(Kind::transition_param));assert(handles.size()==before);
    allocation_fail=-1;retain_fail=0;assert(!f.new_object(Kind::transition_param));assert(handles.size()==before);retain_fail=-1;
    throw_ctor=true;assert(!f.new_field_list(desc.get(),"_assets"));assert(handles.size()==before&&!desc.get()->refs[assetsfield]);throw_ctor=false;
    allocation_fail=1;assert(!f.new_field_list(desc.get(),"_assets"));assert(handles.size()==before);allocation_fail=-1;
    Object* list=static_cast<Object*>(f.new_field_list(desc.get(),"_assets"));assert(list);
    Root text(allocate(stringclass));before=handles.size();throw_add=true;
    assert(!f.list_add(list,text.get())&&handles.size()==before);throw_add=false;
    assert(f.list_add(list,text.get()));
    retain_fail=1;assert(!f.set_object(desc.get(),"_name",text.get())&&handles.size()==before);retain_fail=-1;
}
void metadata(){
    Factory f;Calls api=calls();api.field_set_value=nullptr;assert(!f.configure(api,roots()));
    assert(!f.ready()&&!f.new_object(Kind::actor_descriptor));
    renderfield->type.kind=2;assert(!f.configure(calls(),roots()));renderfield->type.kind=8;
    colliderfield->type.klass=intclass;assert(!f.configure(calls(),roots()));colliderfield->type.klass=colliderclass;
    livefield->type.klass=descriptor;assert(!f.configure(calls(),roots()));livefield->type.klass=outgame;
    std::string old=descriptor->name;descriptor->name="WrongDescriptor";assert(!f.configure(calls(),roots()));descriptor->name=old;
    Class* original=descriptor->parent;Class* chain=defaultdesc;
    for(int i=0;i<33;++i)chain=klass("Test","Ancestor",chain);
    descriptor->parent=chain;assert(!f.configure(calls(),roots()));descriptor->parent=original;
    assert(f.configure(calls(),roots()));assert(handles.empty());
}
int main(int argc,char** argv){assert(argc==2);setup();std::string mode=argv[1];
    if(mode=="rooting")rooting();else if(mode=="validation")validation();
    else if(mode=="faults")faults();else if(mode=="metadata")metadata();else assert(false);
    assert(handles.empty());
}
'''


@pytest.fixture(scope="module")
def factories_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    build = tmp_path_factory.mktemp("mp4-replay-factories")
    source = build / "factories.cpp"
    source.write_text(SOURCE)
    executable = build / "factories"
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
         "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(executable)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


@pytest.mark.parametrize("scenario", ["rooting", "validation", "faults", "metadata"])
def test_original_managed_factory_boundary(factories_binary, scenario):
    result = subprocess.run([str(factories_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
