"""Compile the real Photo replay factory against a collecting managed heap.

The synthetic runtime checks source identity, fresh original-constructor inputs,
closed generic calls and GC ownership. It does not execute Unity or a device.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_photography_replay_factory.hpp"
#include <cassert>
#include <cstddef>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using namespace idoly_mp4_photography_replay;
struct Class;
struct Type {Class* klass;};
struct Field {std::string name;Type type;};
struct Class {std::string space,name;Class* parent=nullptr;std::vector<std::unique_ptr<Field>> fields;};
struct Object {
    alignas(uintptr_t) unsigned char raw[0x400]{};
    bool alive=true,marked=false,constructed=false;
    std::string value;
    std::map<size_t,Object*> references;
};
struct ManagedMethod {void(*pointer)();};
std::vector<std::unique_ptr<Class>> classes;
std::vector<std::unique_ptr<Object>> heap;
std::vector<Object*> static_roots;
std::map<uint32_t,Object*> handles;
uint32_t serial=1;
Class *actor_class,*transition_class,*screen_class,*base_class,*list_class,*array_class,*string_class;
Class *stage_class,*music_class,*costume_class,*hair_class,*tree_class,*wrong_class;
Class *stage_master_class,*music_master_class,*costume_master_class,*hair_master_class;
Field* actor_list_field;
Object *stage_master_object,*music_master_object,*costume_master_object,*hair_master_object;
Object *stage_rows_object,*music_rows_object,*stage_row,*music_row;
std::map<std::string,Object*> costumes,hairs;
int allocation_fail=-1,retain_fail=-1;
int allocations=0,retains=0,list_constructor_calls=0,list_add_calls=0,transition_calls=0,screen_calls=0,tree_calls=0;
int last_stage_sort=-1,last_music_sort=-1,display_mode=0;
bool fail_stage_master=false,fail_music_master=false,fail_costume_master=false,fail_hair_master=false;
bool fallback_hair=false,throw_actor=false,throw_list_ctor=false,throw_list_add=false,throw_transition=false,throw_tree=false;
bool bad_allocated_class=false,bad_tree_class=false,throw_metadata=false;
bool last_preview=false,last_original=false;
bool transient_master_rows=false,sweep_on_release=false;
Object *transient_stage_master=nullptr,*transient_music_master=nullptr;
Object *transient_stage_list=nullptr,*transient_music_list=nullptr;

template<class T>T read(Object* o,size_t offset){assert(o&&o->alive);T v{};std::memcpy(&v,o->raw+offset,sizeof v);return v;}
template<class T>void write(Object* o,size_t offset,T v){assert(o&&o->alive);std::memcpy(o->raw+offset,&v,sizeof v);}
void ref(Object* owner,size_t offset,Object* value){write(owner,offset,value);owner->references[offset]=value;}
void mark(Object* o){if(!o||!o->alive||o->marked)return;o->marked=true;for(auto& r:o->references)mark(r.second);}
void collect(){for(auto& o:heap)o->marked=false;for(auto* o:static_roots)mark(o);for(auto& h:handles)mark(h.second);for(auto& o:heap)if(!o->marked)o->alive=false;}
Class* klass(const char* space,const char* name,Class* parent=nullptr){auto p=std::make_unique<Class>();p->space=space;p->name=name;p->parent=parent;Class* result=p.get();classes.push_back(std::move(p));return result;}
Object* allocate(Class* type){collect();++allocations;if(allocation_fail==0)return nullptr;if(allocation_fail>0)--allocation_fail;auto p=std::make_unique<Object>();Object* result=p.get();write(result,0,type);heap.push_back(std::move(p));return result;}
Object* permanent(Class* type){Object* o=allocate(type);assert(o);static_roots.push_back(o);return o;}
uint32_t retain(void* p,bool pinned){assert(!pinned);Object* o=static_cast<Object*>(p);assert(o&&o->alive);++retains;if(retain_fail==0)return 0;if(retain_fail>0)--retain_fail;handles[serial]=o;return serial++;}
void* target(uint32_t h){auto i=handles.find(h);return i==handles.end()?nullptr:i->second;}
void release(uint32_t h){assert(handles.erase(h)==1);if(sweep_on_release)collect();}
void* object_class(void* p){return read<Class*>(static_cast<Object*>(p),0);}
const char* class_name(void* p){return static_cast<Class*>(p)->name.c_str();}
const char* class_namespace(void* p){return static_cast<Class*>(p)->space.c_str();}
void* class_parent(void* p){return static_cast<Class*>(p)->parent;}
void* find_field(void* p,const char* name){if(throw_metadata)throw std::runtime_error("metadata");for(auto& f:static_cast<Class*>(p)->fields)if(f->name==name)return f.get();return nullptr;}
const void* field_type(void* p){return &static_cast<Field*>(p)->type;}
void* class_from_type(const void* p){return static_cast<const Type*>(p)->klass;}
void* object_new(void* p){return allocate(bad_allocated_class?wrong_class:static_cast<Class*>(p));}
void original_list_ctor(void*,Method*);
void original_list_add(void*,void*,Method*);
ManagedMethod list_ctor_method{reinterpret_cast<void(*)()>(original_list_ctor)},list_add_method{reinterpret_cast<void(*)()>(original_list_add)};
Method* method(void* p,const char* name,int32_t count){if(p!=list_class)return nullptr;if(!std::strcmp(name,".ctor")&&count==0)return &list_ctor_method;if(!std::strcmp(name,"Add")&&count==1)return &list_add_method;return nullptr;}
Object* backing(Object* list){return read<Object*>(list,0x10);}
int32_t count(Object* list){return read<int32_t>(list,0x18);}
Object* item(Object* list,int i){return read<Object*>(backing(list),0x20+static_cast<size_t>(i)*8);}
void initialize_list(Object* list){Object* array=allocate(array_class);if(!array)throw std::runtime_error("backing allocation");ref(list,0x10,array);write<int32_t>(list,0x18,0);write<uintptr_t>(array,0x18,32);list->constructed=true;}
void append(Object* list,Object* actor){const int i=count(list);assert(i>=0&&i<32);ref(backing(list),0x20+static_cast<size_t>(i)*8,actor);write<int32_t>(list,0x18,i+1);}
void original_list_ctor(void* p,Method* m){assert(m==&list_ctor_method);Object* list=static_cast<Object*>(p);assert(object_class(list)==list_class);++list_constructor_calls;collect();assert(list->alive);if(throw_list_ctor)throw std::runtime_error("list ctor");initialize_list(list);}
void original_list_add(void* p,void* v,Method* m){assert(m==&list_add_method);Object* list=static_cast<Object*>(p);Object* actor=static_cast<Object*>(v);assert(object_class(list)==list_class&&list->constructed&&object_class(actor)==actor_class);++list_add_calls;collect();assert(list->alive&&actor->alive);if(throw_list_add)throw std::runtime_error("list add");append(list,actor);}
void* new_string(const char* text){Object* value=allocate(string_class);if(value)value->value=text;return value;}
size_t string_utf8(void* p,char* out,size_t capacity){Object* value=static_cast<Object*>(p);assert(value->alive&&object_class(value)==string_class);const size_t n=value->value.size();if(n<capacity)std::memcpy(out,value->value.c_str(),n+1);return n;}
Object* managed_id(Object* row){return read<Object*>(row,0x18);}
std::string id(Object* row){Object* text=managed_id(row);assert(text&&text->alive);return text->value;}
void* stage_master(Method* m){assert(!m);if(fail_stage_master)return nullptr;if(transient_master_rows){stage_master_object=allocate(stage_master_class);transient_stage_master=stage_master_object;}return stage_master_object;}
void* music_master(Method* m){assert(!m);if(fail_music_master)return nullptr;if(transient_master_rows){music_master_object=allocate(music_master_class);transient_music_master=music_master_object;}return music_master_object;}
void* costume_master(Method* m){assert(!m);return fail_costume_master?nullptr:costume_master_object;}
void* hair_master(Method* m){assert(!m);return fail_hair_master?nullptr:hair_master_object;}
Object* fresh_rows(Object* master,Class* type,const char* name,Object** selected){
    // Model an original managed getter's temporary return graph. It has no
    // static cache roots. Its currently rooted master keeps it alive while the
    // getter builds the managed list/row/string and returns to native code.
    Object* list=allocate(list_class);assert(list);ref(master,0x10,list);initialize_list(list);
    Object* row=allocate(type);assert(row);append(list,row);
    Object* text=static_cast<Object*>(new_string(name));assert(text);ref(row,0x18,text);*selected=row;
    for(auto* root:static_roots)assert(root!=master&&root!=list&&root!=row&&root!=text);
    return list;
}
void* stage_rows(void* p,int32_t sort,Method* m){assert(p==stage_master_object&&!m);last_stage_sort=sort;if(transient_master_rows){stage_rows_object=fresh_rows(static_cast<Object*>(p),stage_class,"stage-1",&stage_row);transient_stage_list=stage_rows_object;}return stage_rows_object;}
void* music_rows(void* p,int32_t sort,Method* m){assert(p==music_master_object&&!m);last_music_sort=sort;if(transient_master_rows){music_rows_object=fresh_rows(static_cast<Object*>(p),music_class,"music-1",&music_row);transient_music_list=music_rows_object;}return music_rows_object;}
void* find_costume(void* p,void* key,Method* m){assert(p==costume_master_object&&!m);const auto& name=static_cast<Object*>(key)->value;auto i=costumes.find(name);return i==costumes.end()?nullptr:i->second;}
void* find_hair(void* p,void* key,Method* m){assert(p==hair_master_object&&!m);const auto& name=static_cast<Object*>(key)->value;auto i=hairs.find(name);return i==hairs.end()?nullptr:i->second;}
void actor_ctor(void* p,void* c,void* h,Method* m){assert(!m);Object* actor=static_cast<Object*>(p);assert(object_class(actor)==actor_class);collect();assert(actor->alive&&static_cast<Object*>(c)->alive&&static_cast<Object*>(h)->alive);if(throw_actor)throw std::runtime_error("actor ctor");ref(actor,0x10,static_cast<Object*>(c));ref(actor,0x18,fallback_hair?hairs.at("hair-default"):static_cast<Object*>(h));}
void* actor_costume_id(void* p,Method* m){assert(!m);return managed_id(read<Object*>(static_cast<Object*>(p),0x10));}
void* actor_hair_id(void* p,Method* m){assert(!m);return managed_id(read<Object*>(static_cast<Object*>(p),0x18));}
void construct_transition(Object* self,Object* stage,Object* music,Object* actors,bool preview,bool screen,bool original){
    collect();assert(self->alive&&stage->alive&&music->alive&&actors->alive);assert(stage==stage_row&&music==music_row);if(throw_transition)throw std::runtime_error("transition ctor");
    last_preview=preview;last_original=original;ref(self,0x68,stage);ref(self,0x70,music);ref(self,0x40,actors);write<uint8_t>(self,0x10,preview);write<uint8_t>(self,0x28,display_mode==4);if(screen)write<uint8_t>(self,0x80,original);
    Object* display=allocate(list_class);if(!display)throw std::runtime_error("display allocation");ref(self,0x48,display);initialize_list(display);
    const int n=count(actors);for(int i=0;i<n-(display_mode==1?1:0);++i)append(display,item(actors,display_mode==2?n-i-1:i));
    if(display_mode==3&&n)write(item(display,0),0,wrong_class);
}
void transition_ctor(void* p,void* s,void* m,void* a,bool preview,Method* mi){assert(!mi&&object_class(p)==transition_class);++transition_calls;construct_transition(static_cast<Object*>(p),static_cast<Object*>(s),static_cast<Object*>(m),static_cast<Object*>(a),preview,false,false);}
void screen_ctor(void* p,void* s,void* m,void* a,bool preview,bool original,Method* mi){assert(!mi&&object_class(p)==screen_class);++screen_calls;construct_transition(static_cast<Object*>(p),static_cast<Object*>(s),static_cast<Object*>(m),static_cast<Object*>(a),preview,true,original);}
void* create_tree(void* p,Method* m){assert(!m);Object* trans=static_cast<Object*>(p);collect();assert(trans->alive);++tree_calls;if(throw_tree)throw std::runtime_error("tree");Object* tree=allocate(bad_tree_class?wrong_class:tree_class);if(tree)ref(tree,0x10,trans);return tree;}
Calls calls(){Calls a{};auto& m=a.managed;m.object_class=object_class;m.class_name=class_name;m.class_namespace=class_namespace;m.class_parent=class_parent;m.field=find_field;m.field_type=field_type;m.class_from_type=class_from_type;m.object_new=object_new;m.method=method;m.strong_new=retain;m.target=target;m.release=release;
    a.new_string=new_string;a.string_utf8=string_utf8;a.stage_master=stage_master;a.music_master=music_master;a.costume_master=costume_master;a.hair_master=hair_master;a.stage_rows=stage_rows;a.music_rows=music_rows;a.find_costume=find_costume;a.find_hair=find_hair;a.actor_ctor=actor_ctor;a.actor_costume_id=actor_costume_id;a.actor_hair_id=actor_hair_id;a.transition_ctor=transition_ctor;a.screen_transition_ctor=screen_ctor;a.expected_list_ctor=reinterpret_cast<uintptr_t>(original_list_ctor);a.expected_list_add=reinterpret_cast<uintptr_t>(original_list_add);a.stage_sort=7;a.music_sort=9;return a;}
Classes types(){return {actor_class,transition_class,screen_class};}
Object* make_row(Class* type,const char* name){Object* row=permanent(type);Object* text=static_cast<Object*>(new_string(name));assert(text);ref(row,0x18,text);return row;}
void setup(){
    actor_class=klass("Solis.Common.Data","ActorCostume");base_class=klass("Solis.Photography.Data","AbstPhotographyTransitionData");transition_class=klass("Solis.Photography.Data","PhotographyLiveTransitionData",base_class);screen_class=klass("Solis.Photography.Data","PhotographyLiveScreenTransitionData",transition_class);
    list_class=klass("System.Collections.Generic","List`1");array_class=klass("Test","ReferenceArray");string_class=klass("System","String");wrong_class=klass("Test","WrongClass");tree_class=klass("Qua.UI","TransitionTree");
    stage_class=klass("Solis.Common.Proto.Master","PhotoQuestStage");music_class=klass("Solis.Common.Proto.Master","PhotoQuestMusic");costume_class=klass("Solis.Common.Proto.Master","Costume");hair_class=klass("Solis.Common.Proto.Master","Hair");
    stage_master_class=klass("Solis.Common.Master","PhotoQuestStageMaster");music_master_class=klass("Solis.Common.Master","PhotoQuestMusicMaster");costume_master_class=klass("Solis.Common.Master","CostumeMaster");hair_master_class=klass("Solis.Common.Master","HairMaster");
    auto f=std::make_unique<Field>();f->name="<ActorCostumeList>k__BackingField";f->type={list_class};actor_list_field=f.get();base_class->fields.push_back(std::move(f));
    stage_master_object=permanent(stage_master_class);music_master_object=permanent(music_master_class);costume_master_object=permanent(costume_master_class);hair_master_object=permanent(hair_master_class);
    stage_rows_object=permanent(list_class);initialize_list(stage_rows_object);music_rows_object=permanent(list_class);initialize_list(music_rows_object);
    stage_row=make_row(stage_class,"stage-1");music_row=make_row(music_class,"music-1");append(stage_rows_object,stage_row);append(music_rows_object,music_row);
    costumes["costume-1"]=make_row(costume_class,"costume-1");costumes["costume-2"]=make_row(costume_class,"costume-2");hairs["hair-1"]=make_row(hair_class,"hair-1");hairs["hair-2"]=make_row(hair_class,"hair-2");hairs["hair-default"]=make_row(hair_class,"hair-default");
}
idoly_mp4_queue::PhotoSelection selection(){idoly_mp4_queue::PhotoSelection p{};p.source_kind=1;p.actor_count=2;std::strcpy(p.stage_id,"stage-1");std::strcpy(p.music_id,"music-1");std::strcpy(p.actors[0].costume_id,"costume-2");std::strcpy(p.actors[0].hair_id,"hair-1");std::strcpy(p.actors[1].costume_id,"costume-1");std::strcpy(p.actors[1].hair_id,"hair-2");return p;}
void no_roots(){assert(handles.empty());collect();for(auto& o:heap)if(o->alive)assert(o->marked);}
void failed(Factory& factory,const idoly_mp4_queue::PhotoSelection& p,const char* error){assert(!factory.build_transition(p));assert(!std::strcmp(factory.error(),error));assert(handles.empty());}
void positive(const std::string& mode){
    {
        Factory f;assert(f.configure(calls(),types()));auto p=selection();p.is_preview=mode=="screen-original";p.screen_transition=mode!="base";p.is_original=mode=="screen-original";
        Object* tree=static_cast<Object*>(f.build_transition(p));assert(tree&&tree->alive&&handles.size()==1&&!std::strcmp(f.error(),"none"));
        assert(last_stage_sort==7&&last_music_sort==9&&last_preview==(p.is_preview!=0));assert(last_original==(p.is_original!=0));assert(list_constructor_calls==1&&list_add_calls==2&&tree_calls==0);
        assert(transition_calls==(p.screen_transition?0:1)&&screen_calls==(p.screen_transition?1:0));
        Object* trans=tree;assert(object_class(trans)==(p.screen_transition?screen_class:transition_class));Object* display=read<Object*>(trans,0x48);assert(count(display)==2);
        assert(id(read<Object*>(item(display,0),0x10))=="costume-2"&&id(read<Object*>(item(display,0),0x18))=="hair-1");assert(id(read<Object*>(item(display,1),0x10))=="costume-1");
        collect();assert(tree->alive&&trans->alive&&display->alive&&item(display,0)->alive); // only owned tree roots this new graph
    }
    no_roots();
}
void lifetime(){
    Object* old=nullptr;{
        Factory f;assert(f.configure(calls(),types()));auto p=selection();old=static_cast<Object*>(f.build_transition(p));assert(old&&handles.size()==1);
        Object* next=static_cast<Object*>(f.build_transition(p));assert(next&&next!=old&&handles.size()==1&&!old->alive);collect();assert(next->alive);
        assert(f.configure(calls(),types()));assert(handles.empty());collect();assert(!next->alive);
        old=static_cast<Object*>(f.build_transition(p));assert(old&&handles.size()==1);p.source_kind=0;failed(f,p,"photography_source_kind_unsupported");collect();assert(!old->alive);
        p.source_kind=1;old=static_cast<Object*>(f.build_transition(p));assert(old&&handles.size()==1);
        Calls missing=calls();missing.managed.release=nullptr;assert(!f.configure(missing,types()));assert(handles.empty());collect();assert(!old->alive);
        assert(f.configure(calls(),types()));old=static_cast<Object*>(f.build_transition(p));assert(old&&handles.size()==1);
    }assert(handles.empty());collect();assert(!old->alive); // destructor releases final owned tree
}
void transient_lookup_lifetime(){
    transient_master_rows=true;sweep_on_release=true;
    Object *tree=nullptr,*selected_stage=nullptr,*selected_music=nullptr;
    {
        Factory f;assert(f.configure(calls(),types()));tree=static_cast<Object*>(f.build_transition(selection()));
        assert(tree&&handles.size()==1);selected_stage=stage_row;selected_music=music_row;
        // find_row has released both local lookup roots; only the caller's
        // selected root, followed by the new transition tree, can retain rows.
        assert(transient_stage_master&&!transient_stage_master->alive);
        assert(transient_music_master&&!transient_music_master->alive);
        assert(transient_stage_list&&!transient_stage_list->alive);
        assert(transient_music_list&&!transient_music_list->alive);
        assert(selected_stage->alive&&selected_music->alive);
        Object* transition=tree;
        assert(read<Object*>(transition,0x68)==selected_stage&&read<Object*>(transition,0x70)==selected_music);
        collect();assert(tree->alive&&selected_stage->alive&&selected_music->alive);
    }
    assert(handles.empty()&&!tree->alive&&!selected_stage->alive&&!selected_music->alive);
}
void invalid_selection(const std::string& mode){Factory f;assert(f.configure(calls(),types()));auto p=selection();const char* error="photography_selection_invalid";
    if(mode=="unsupported"){p.source_kind=2;error="photography_source_kind_unsupported";}else if(mode=="zero-actors")p.actor_count=0;else if(mode=="many-actors")p.actor_count=33;else if(mode=="preview")p.is_preview=2;else if(mode=="original")p.is_original=2;else if(mode=="base-original")p.is_original=1;else if(mode=="screen")p.screen_transition=2;else if(mode=="empty-stage")p.stage_id[0]=0;else if(mode=="unterminated-music")std::memset(p.music_id,'x',sizeof p.music_id);else if(mode=="empty-costume"){p.actors[1].costume_id[0]=0;error="photography_actor_selection_invalid";}else assert(false);
    failed(f,p,error);assert(tree_calls==0);
}
void lookup(const std::string& mode){Factory f;assert(f.configure(calls(),types()));auto p=selection();const char* error="photography_stage_not_found";
    if(mode=="stage-master")fail_stage_master=true;else if(mode=="music-master"){fail_music_master=true;error="photography_music_not_found";}else if(mode=="wrong-master")write(stage_master_object,0,wrong_class);else if(mode=="missing-stage")std::strcpy(p.stage_id,"stage-missing");else if(mode=="missing-music"){std::strcpy(p.music_id,"music-missing");error="photography_music_not_found";}else if(mode=="duplicate-stage")append(stage_rows_object,stage_row);else if(mode=="wrong-row")write(stage_row,0,wrong_class);else if(mode=="wrong-list")write(stage_rows_object,0,wrong_class);else if(mode=="negative-count")write<int32_t>(stage_rows_object,0x18,-1);else if(mode=="huge-count")write<int32_t>(stage_rows_object,0x18,65537);else if(mode=="short-backing")write<uintptr_t>(backing(stage_rows_object),0x18,0);else if(mode=="huge-backing")write<uintptr_t>(backing(stage_rows_object),0x18,65537);else if(mode=="null-backing")ref(stage_rows_object,0x10,nullptr);else if(mode=="costume-master"){fail_costume_master=true;error="photography_costume_master_not_ready";}else if(mode=="hair-master"){fail_hair_master=true;error="photography_hair_master_not_ready";}else if(mode=="costume-row"){costumes.erase("costume-1");error="photography_costume_not_found";}else if(mode=="hair-row"){hairs.erase("hair-1");error="photography_hair_not_found";}else if(mode=="wrong-costume-row"){write(costumes.at("costume-2"),0,wrong_class);error="photography_costume_not_found";}else if(mode=="wrong-hair-row"){write(hairs.at("hair-1"),0,wrong_class);error="photography_hair_not_found";}else assert(false);
    failed(f,p,error);assert(tree_calls==0);
}
void construction(const std::string& mode){Factory f;assert(f.configure(calls(),types()));auto p=selection();const char* error="photography_replay_construction_exception";
    if(mode=="video-master"){display_mode=4;error="photography_video_master_unsupported";}else if(mode=="canonical-hair"){fallback_hair=true;error="photography_actor_canonical_selection_changed";}else if(mode=="display-trim"){display_mode=1;error="photography_display_actor_count_changed";}else if(mode=="display-order"){display_mode=2;error="photography_display_actor_order_changed";}else if(mode=="display-class"){display_mode=3;error="photography_display_actor_order_changed";}else if(mode=="actor-exception")throw_actor=true;else if(mode=="list-ctor-exception")throw_list_ctor=true;else if(mode=="list-add-exception")throw_list_add=true;else if(mode=="transition-exception")throw_transition=true;else if(mode=="wrong-allocation"){bad_allocated_class=true;error="photography_actor_list_allocation_failed";}else assert(false);
    failed(f,p,error);
}
void failures(){
    // Every allocation/retain in the successful path is made to fail in turn.
    int allocation_total=0,retain_total=0;{
        Factory f;assert(f.configure(calls(),types()));int a=allocations,r=retains;assert(f.build_transition(selection()));allocation_total=allocations-a;retain_total=retains-r;
    }assert(handles.empty());
    for(int i=0;i<allocation_total;++i){Factory f;assert(f.configure(calls(),types()));allocation_fail=i;assert(!f.build_transition(selection()));allocation_fail=-1;assert(handles.empty());}
    for(int i=0;i<retain_total;++i){Factory f;assert(f.configure(calls(),types()));retain_fail=i;assert(!f.build_transition(selection()));retain_fail=-1;assert(handles.empty());}
}
void metadata(const std::string& mode){Factory f;Calls a=calls();Classes t=types();const char* error="photography_factory_unavailable";
    if(mode=="missing-api")a.managed.strong_new=nullptr;else if(mode=="wrong-actor"){t.actor=wrong_class;error="photography_factory_class_mismatch";}else if(mode=="wrong-list-type"){actor_list_field->type.klass=wrong_class;error="photography_actor_list_type_mismatch";}else if(mode=="bad-ctor-pin"){a.expected_list_ctor++;error="photography_actor_list_methods_unverified";}else if(mode=="bad-add-pin"){a.expected_list_add=0;error="photography_actor_list_methods_unverified";}else if(mode=="metadata-exception"){throw_metadata=true;error="photography_factory_metadata_exception";}else if(mode=="missing-field"){actor_list_field->name="WrongField";error="photography_actor_list_type_mismatch";}else assert(false);
    assert(!f.configure(a,t));assert(!std::strcmp(f.error(),error));assert(!f.build_transition(selection())&&!std::strcmp(f.error(),"photography_factory_unavailable"));assert(handles.empty());
}
int main(int argc,char** argv){assert(argc==3);setup();const std::string group=argv[1],mode=argv[2];if(group=="positive")positive(mode);else if(group=="lifetime")lifetime();else if(group=="transient-lifetime")transient_lookup_lifetime();else if(group=="selection")invalid_selection(mode);else if(group=="lookup")lookup(mode);else if(group=="construction")construction(mode);else if(group=="failures")failures();else if(group=="metadata")metadata(mode);else assert(false);no_roots();}
'''


@pytest.fixture(scope="module")
def photo_factory_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    build = tmp_path_factory.mktemp("mp4-photography-replay-factory")
    source = build / "factory.cpp"
    source.write_text(SOURCE)
    executable = build / "factory"
    warnings = ["-Wno-misleading-indentation"]
    if "g++" in Path(compiler).name:
        warnings.append("-Wno-class-memaccess")
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *warnings,
         "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(executable)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


SCENARIOS = {
    "positive": ["base", "screen-false", "screen-original"],
    "lifetime": ["owned-tree"],
    "transient-lifetime": ["retained-before-master-and-list-release"],
    "selection": ["unsupported", "zero-actors", "many-actors", "preview", "original", "base-original", "screen",
                  "empty-stage", "unterminated-music", "empty-costume"],
    "lookup": ["stage-master", "music-master", "wrong-master", "missing-stage", "missing-music",
               "duplicate-stage", "wrong-row", "wrong-list", "negative-count", "huge-count",
               "short-backing", "huge-backing", "null-backing", "costume-master", "hair-master",
               "costume-row", "hair-row", "wrong-costume-row", "wrong-hair-row"],
    "construction": ["video-master", "canonical-hair", "display-trim", "display-order", "display-class",
                     "actor-exception", "list-ctor-exception", "list-add-exception",
                     "transition-exception", "wrong-allocation"],
    "failures": ["every-allocation-and-gc-handle"],
    "metadata": ["missing-api", "wrong-actor", "wrong-list-type", "bad-ctor-pin", "bad-add-pin",
                 "metadata-exception", "missing-field"],
}


@pytest.mark.parametrize("group,scenario", [(g, s) for g, ss in SCENARIOS.items() for s in ss])
def test_original_photography_replay_factory(photo_factory_binary, group, scenario):
    result = subprocess.run([str(photo_factory_binary), group, scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
