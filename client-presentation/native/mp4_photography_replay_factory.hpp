// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Rehydrate ordinary Photography selections through original master lookups,
// constructors and scene-transition input construction. No managed graph is saved.
#include "mp4_replay_factories.hpp"
namespace idoly_mp4_photography_replay {
using Method=const void;
struct Calls {
    idoly_mp4_replay_factories::Calls managed{};
    void*(*new_string)(const char*)=nullptr;
    size_t(*string_utf8)(void*,char*,size_t)=nullptr;
    void*(*stage_master)(Method*)=nullptr;void*(*music_master)(Method*)=nullptr;
    void*(*costume_master)(Method*)=nullptr;void*(*hair_master)(Method*)=nullptr;
    void*(*stage_rows)(void*,int32_t,Method*)=nullptr;void*(*music_rows)(void*,int32_t,Method*)=nullptr;
    void*(*find_costume)(void*,void*,Method*)=nullptr;void*(*find_hair)(void*,void*,Method*)=nullptr;
    void(*actor_ctor)(void*,void*,void*,Method*)=nullptr;
    void*(*actor_costume_id)(void*,Method*)=nullptr;void*(*actor_hair_id)(void*,Method*)=nullptr;
    void(*transition_ctor)(void*,void*,void*,void*,bool,Method*)=nullptr;
    void(*screen_transition_ctor)(void*,void*,void*,void*,bool,bool,Method*)=nullptr;
    uintptr_t expected_list_ctor=0,expected_list_add=0;
    int32_t stage_sort=0,music_sort=0;
};
struct Classes {void*actor=nullptr,*transition=nullptr,*screen_transition=nullptr;};
class Factory {
public:
    Factory()=default;
    ~Factory(){release_owned();}
    Factory(const Factory&)=delete;Factory&operator=(const Factory&)=delete;
    bool configure(Calls api,Classes types){
        release_owned();api_=api;types_=types;ready_=false;error_="photography_factory_unavailable";
        const auto& m=api_.managed;
        if(!m.object_class||!m.class_name||!m.class_namespace||!m.class_parent||!m.field||!m.field_type
            ||!m.class_from_type||!m.object_new||!m.method||!m.strong_new||!m.target||!m.release
            ||!api_.new_string||!api_.string_utf8||!api_.stage_master||!api_.music_master
            ||!api_.costume_master||!api_.hair_master||!api_.stage_rows||!api_.music_rows
            ||!api_.find_costume||!api_.find_hair||!api_.actor_ctor||!api_.actor_costume_id||!api_.actor_hair_id
            ||!api_.transition_ctor||!api_.screen_transition_ctor)return false;
        if(!named(types_.actor,"Solis.Common.Data","ActorCostume")
            ||!named(types_.transition,"Solis.Photography.Data","PhotographyLiveTransitionData")
            ||!named(types_.screen_transition,"Solis.Photography.Data","PhotographyLiveScreenTransitionData"))
            return fail("photography_factory_class_mismatch");
        try {
            void* field=find_field(types_.transition,"<ActorCostumeList>k__BackingField");
            const void* type=field?m.field_type(field):nullptr;
            list_class_=type?m.class_from_type(type):nullptr;
            if(!named(list_class_,"System.Collections.Generic","List`1"))return fail("photography_actor_list_type_mismatch");
            list_ctor_=m.method(list_class_,".ctor",0);list_add_=m.method(list_class_,"Add",1);
            if(!api_.expected_list_ctor||!api_.expected_list_add
                ||reinterpret_cast<uintptr_t>(pointer<Constructor>(list_ctor_))!=api_.expected_list_ctor
                ||reinterpret_cast<uintptr_t>(pointer<Add>(list_add_))!=api_.expected_list_add)
                return fail("photography_actor_list_methods_unverified");
            ready_=true;error_="none";return true;
        }catch(...){return fail("photography_factory_metadata_exception");}
    }
    const char*error()const{return error_;}
    void*build_transition(const idoly_mp4_queue::PhotoSelection& photo){
        release_owned();
        if(!ready_)return failed("photography_factory_unavailable");
        if(photo.source_kind!=1)return failed("photography_source_kind_unsupported");
        if(photo.is_preview>1||photo.is_original>1||photo.screen_transition>1||(!photo.screen_transition&&photo.is_original)||!photo.actor_count
            ||photo.actor_count>idoly_mp4_queue::max_actors||!text(photo.stage_id)||!text(photo.music_id))
            return failed("photography_selection_invalid");
        try {
            Root stage(*this,nullptr),music(*this,nullptr);
            if(!find_row(api_.stage_master,api_.stage_rows,api_.stage_sort,"PhotoQuestStage",photo.stage_id,stage))
                return failed("photography_stage_not_found");
            if(!find_row(api_.music_master,api_.music_rows,api_.music_sort,"PhotoQuestMusic",photo.music_id,music))
                return failed("photography_music_not_found");
            Root costume_master(*this,api_.costume_master(nullptr)),hair_master(*this,api_.hair_master(nullptr));
            if(!costume_master||!exact(costume_master.get(),"Solis.Common.Master","CostumeMaster"))return failed("photography_costume_master_not_ready");
            if(!hair_master||!exact(hair_master.get(),"Solis.Common.Master","HairMaster"))return failed("photography_hair_master_not_ready");
            Root list(*this,api_.managed.object_new(list_class_));
            if(!list||api_.managed.object_class(list.get())!=list_class_)return failed("photography_actor_list_allocation_failed");
            pointer<Constructor>(list_ctor_)(list.get(),list_ctor_);
            for(uint32_t i=0;i<photo.actor_count;++i){
                const auto& selected=photo.actors[i];
                if(!text(selected.costume_id)||!text(selected.hair_id))return failed("photography_actor_selection_invalid");
                Root costume_key(*this,api_.new_string(selected.costume_id)),hair_key(*this,api_.new_string(selected.hair_id));
                if(!costume_key||!hair_key)return failed("photography_gc_handle_failed");
                Root costume(*this,api_.find_costume(costume_master.get(),costume_key.get(),nullptr));
                Root hair(*this,api_.find_hair(hair_master.get(),hair_key.get(),nullptr));
                if(!costume||!exact(costume.get(),"Solis.Common.Proto.Master","Costume"))return failed("photography_costume_not_found");
                if(!hair||!exact(hair.get(),"Solis.Common.Proto.Master","Hair"))return failed("photography_hair_not_found");
                Root actor(*this,api_.managed.object_new(types_.actor));
                if(!actor||api_.managed.object_class(actor.get())!=types_.actor)return failed("photography_actor_allocation_failed");
                api_.actor_ctor(actor.get(),costume.get(),hair.get(),nullptr);
                if(!same_text(api_.actor_costume_id(actor.get(),nullptr),selected.costume_id)
                    ||!same_text(api_.actor_hair_id(actor.get(),nullptr),selected.hair_id))
                    return failed("photography_actor_canonical_selection_changed");
                pointer<Add>(list_add_)(list.get(),actor.get(),list_add_);
            }
            Root transition(*this,api_.managed.object_new(photo.screen_transition?types_.screen_transition:types_.transition));
            if(!transition||api_.managed.object_class(transition.get())!=(photo.screen_transition?types_.screen_transition:types_.transition))
                return failed("photography_transition_allocation_failed");
            if(photo.screen_transition)api_.screen_transition_ctor(transition.get(),stage.get(),music.get(),list.get(),photo.is_preview!=0,photo.is_original!=0,nullptr);
            else api_.transition_ctor(transition.get(),stage.get(),music.get(),list.get(),photo.is_preview!=0,nullptr);
            if(field<uint8_t>(transition.get(),0x28)!=0)return failed("photography_video_master_unsupported");
            // The original constructor chooses display actors from the music metadata.
            // Reject a changed master or an order/count mismatch before scene loading.
            void* display=field<void*>(transition.get(),0x48);void** entries=nullptr;size_t count=0;
            if(!list_entries(display,&entries,&count)||count!=photo.actor_count)return failed("photography_display_actor_count_changed");
            for(size_t i=0;i<count;++i){
                if(api_.managed.object_class(entries[i])!=types_.actor
                    ||!same_text(api_.actor_costume_id(entries[i],nullptr),photo.actors[i].costume_id)
                    ||!same_text(api_.actor_hair_id(entries[i],nullptr),photo.actors[i].hair_id))
                    return failed("photography_display_actor_order_changed");
            }
            owned_=api_.managed.strong_new(transition.get(),false);
            if(!owned_)return failed("photography_gc_handle_failed");
            error_="none";return api_.managed.target(owned_);
        }catch(...){return failed("photography_replay_construction_exception");}
    }
private:
    using Constructor=void(*)(void*,Method*);using Add=void(*)(void*,void*,Method*);
    class Root {
    public:Root(Factory& owner,void* value):owner_(owner),handle_(value?owner.api_.managed.strong_new(value,false):0){}
        ~Root(){if(handle_)owner_.api_.managed.release(handle_);}
        void*get()const{return handle_?owner_.api_.managed.target(handle_):nullptr;}
        explicit operator bool()const{return get()!=nullptr;}
        bool set(void* value){
            const uint32_t next=value?owner_.api_.managed.strong_new(value,false):0;
            if(value&&!next)return false;
            if(handle_)owner_.api_.managed.release(handle_);
            handle_=next;return true;
        }
        Root(const Root&)=delete;Root&operator=(const Root&)=delete;
    private:Factory&owner_;uint32_t handle_;
    };
    template<class T>static T field(void* object,size_t offset){T value{};if(object)::memcpy(&value,static_cast<uint8_t*>(object)+offset,sizeof value);return value;}
    template<class T>static T pointer(Method* method){T value=nullptr;if(method)::memcpy(&value,method,sizeof value);return value;}
    static bool text(const char*value){if(!value||!value[0])return false;for(size_t i=1;i<idoly_mp4_queue::name_capacity;++i)if(!value[i])return true;return false;}
    bool same_text(void* managed,const char*expected)const{char buffer[idoly_mp4_queue::name_capacity]{};return managed&&api_.string_utf8(managed,buffer,sizeof buffer)<sizeof buffer&&!::strcmp(buffer,expected);}
    bool named(void*klass,const char*space,const char*name)const{
        if(!klass)return false;const char*n=api_.managed.class_name(klass),*s=api_.managed.class_namespace(klass);
        return n&&s&&!::strcmp(n,name)&&!::strcmp(s,space);
    }
    bool exact(void*object,const char*space,const char*name)const{return object&&named(api_.managed.object_class(object),space,name);}
    void*find_field(void*klass,const char*name)const{for(unsigned depth=0;klass&&depth<32;++depth,klass=api_.managed.class_parent(klass))if(void*f=api_.managed.field(klass,name))return f;return nullptr;}
    bool list_entries(void*list,void***entries,size_t*count)const{
        if(!exact(list,"System.Collections.Generic","List`1"))return false;
        int32_t size=field<int32_t>(list,0x18);void*array=field<void*>(list,0x10);
        if(size<0||size>65536||!array||field<uintptr_t>(array,0x18)<static_cast<uintptr_t>(size)||field<uintptr_t>(array,0x18)>65536)return false;
        *count=static_cast<size_t>(size);*entries=reinterpret_cast<void**>(static_cast<uint8_t*>(array)+0x20);return true;
    }
    bool find_row(void*(*master)(Method*),void*(*rows)(void*,int32_t,Method*),int32_t sort,const char*type,const char*id,Root& selected){
        Root collection(*this,master(nullptr));
        char master_name[64]{};const size_t name_length=::strlen(type);
        if(name_length+7>sizeof master_name)return false;
        ::memcpy(master_name,type,name_length);::memcpy(master_name+name_length,"Master",7);
        if(!collection||!exact(collection.get(),"Solis.Common.Master",master_name))return false;
        Root list(*this,rows(collection.get(),sort,nullptr));void**entries=nullptr;size_t count=0;
        if(!list||!list_entries(list.get(),&entries,&count))return false;
        void* found=nullptr;
        for(size_t i=0;i<count;++i){
            if(!exact(entries[i],"Solis.Common.Proto.Master",type))return false;
            if(same_text(field<void*>(entries[i],0x18),id)){if(found)return false;found=entries[i];}
        }
        // Retain before the temporary master/list roots are released. Master
        // caches are an implementation detail, never a lifetime guarantee.
        return found&&selected.set(found);
    }
    void release_owned(){if(owned_&&api_.managed.release)api_.managed.release(owned_);owned_=0;}
    bool fail(const char*value){error_=value;return false;}
    void*failed(const char*value){fail(value);return nullptr;}
    Calls api_{};Classes types_{};void*list_class_=nullptr;Method*list_ctor_=nullptr,*list_add_=nullptr;
    uint32_t owned_=0;bool ready_=false;const char*error_="photography_factory_unavailable";
};
} // namespace idoly_mp4_photography_replay
