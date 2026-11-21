// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
// Managed-only construction for the original MV screen router. Call on the
// Unity thread after the pinned C API and readonly class references are checked.
#include "mp4_replay.hpp"

namespace idoly_mp4_replay_factories {
using Kind=idoly_mp4_replay::Kind;
using Method=const void;
struct Calls {
    void*(*object_class)(void*)=nullptr;
    const char*(*class_name)(void*)=nullptr;
    const char*(*class_namespace)(void*)=nullptr;
    void*(*class_parent)(void*)=nullptr;
    void*(*field)(void*,const char*)=nullptr;
    const void*(*field_type)(void*)=nullptr;
    void*(*class_from_type)(const void*)=nullptr;
    void*(*object_new)(void*)=nullptr;
    Method*(*method)(void*,const char*,int32_t)=nullptr;
    uint32_t(*strong_new)(void*,bool)=nullptr;
    void*(*target)(uint32_t)=nullptr;
    void(*release)(uint32_t)=nullptr;
    int32_t(*type_get_type)(const void*)=nullptr;
    // Pinned IL2CPP API: reference fields take the object itself (or null).
    // Primitive/value fields instead take an address to the value storage.
    void(*field_set_value)(void*,void*,void*)=nullptr;
};
struct Classes {
    void*out_game_param=nullptr;
    void*actor_descriptor=nullptr;
    void*transition_param=nullptr;
};
class Factory {
public:
    Factory()=default;
    Factory(const Factory&)=delete;Factory&operator=(const Factory&)=delete;
    bool configure(Calls calls,Classes classes) {
        ready_=false;api_=calls;classes_=classes;assets_class_=string_class_=nullptr;
        list_ctor_=list_add_=nullptr;error_="factory_api_unavailable";
        for(auto& field:fields_)field={};
        if(!api_.object_class||!api_.class_name||!api_.class_namespace||!api_.class_parent
            ||!api_.field||!api_.field_type||!api_.class_from_type||!api_.object_new
            ||!api_.method||!api_.strong_new||!api_.target||!api_.release
            ||!api_.type_get_type||!api_.field_set_value)return false;
        if(!named(classes_.out_game_param,"Solis.OutGame","OutGameLivePlayerParam")
            ||!named(classes_.actor_descriptor,"Solis.Common","SolisActorDescriptor")
            ||!named(classes_.transition_param,"Solis.OutGame","LivePlayerTransitionParam"))
            return fail("factory_class_mismatch");
        try {
            const Definition* definitions=definitions_();
            for(size_t i=0;i<field_count_;++i) {
                const Definition& def=definitions[i];void* field=find_field(type(def.owner),def.name);
                const void* field_type=field?api_.field_type(field):nullptr;
                if(!field_type)return fail("factory_field_unavailable");
                const int32_t kind=api_.type_get_type(field_type);
                if(kind!=def.kind)return fail("factory_field_type_mismatch");
                void* reference=nullptr;
                if(def.kind==14||def.kind==17||def.kind==18||def.kind==21||def.kind==29) {
                    reference=api_.class_from_type(field_type);
                    if(!reference)return fail("factory_field_class_unavailable");
                }
                if(i==assets_index_) {
                    if(!named(reference,"System.Collections.Generic","List`1"))return fail("factory_asset_list_type_mismatch");
                    assets_class_=reference;
                } else if(i==name_index_) {
                    if(!named(reference,"System","String"))return fail("factory_string_type_mismatch");
                    string_class_=reference;
                } else if(i==collider_index_) {
                    if(!named(reference,"VL","VLActorColliderType"))return fail("factory_collider_type_mismatch");
                } else if(i==live_param_index_&&reference!=classes_.out_game_param)
                    return fail("factory_live_parameter_type_mismatch");
                fields_[i]={field,reference};
            }
            list_ctor_=api_.method(assets_class_,".ctor",0);
            list_add_=api_.method(assets_class_,"Add",1);
            if(!method_pointer<Constructor>(list_ctor_)||!method_pointer<Add>(list_add_))
                return fail("factory_list_method_unavailable");
            ready_=true;error_="none";return true;
        } catch(...) {return fail("factory_metadata_exception");}
    }
    bool ready()const{return ready_;}
    const char*error()const{return error_;}
    void*new_object(Kind kind) {
        if(!ready_)return nullptr;
        void* klass=type(kind);if(!klass){fail("factory_object_kind_invalid");return nullptr;}
        try {
            Root root(api_,api_.object_new(klass));
            if(!root||api_.object_class(root.get())!=klass){fail("factory_object_allocation_failed");return nullptr;}
            error_="none";return root.get();
        } catch(...) {fail("factory_object_allocation_exception");return nullptr;}
    }
    void*new_field_list(void* owner,const char* name) {
        if(!ready_||!owner||!name||::strcmp(name,"_assets")
            ||api_.object_class(owner)!=classes_.actor_descriptor){fail("factory_asset_owner_invalid");return nullptr;}
        try {
            Root owner_root(api_,owner);if(!owner_root){fail("factory_gc_handle_failed");return nullptr;}
            Root list(api_,api_.object_new(assets_class_));
            if(!list||api_.object_class(list.get())!=assets_class_){fail("factory_list_allocation_failed");return nullptr;}
            method_pointer<Constructor>(list_ctor_)(list.get(),list_ctor_);
            // Attach before the temporary root is released. The retained
            // descriptor owns this list across the caller's next allocation.
            api_.field_set_value(owner_root.get(),fields_[assets_index_].field,list.get());
            error_="none";return list.get();
        } catch(...) {fail("factory_list_construction_exception");return nullptr;}
    }
    bool list_add(void* list,void* value) {
        if(!ready_||!list||!value||api_.object_class(list)!=assets_class_
            ||api_.object_class(value)!=string_class_)return fail("factory_list_value_type_mismatch");
        try {
            Root list_root(api_,list),value_root(api_,value);
            if(!list_root||!value_root)return fail("factory_gc_handle_failed");
            method_pointer<Add>(list_add_)(list_root.get(),value_root.get(),list_add_);
            error_="none";return true;
        } catch(...) {return fail("factory_list_add_exception");}
    }
    bool set_object(void* owner,const char* name,void* value) {
        const int slot=field_slot(owner,name);if(slot<0)return fail("factory_object_field_invalid");
        const Definition& def=definitions_()[slot];const Field& field=fields_[slot];
        if(def.kind!=14&&def.kind!=18&&def.kind!=21&&def.kind!=29)return fail("factory_object_field_invalid");
        // No dynamic Unity GameObjects can enter a logical queue job. The
        // nullable name preserves null separately from an empty managed string.
        if((slot==game_objects_index_&&value)||(!value&&slot!=name_index_&&slot!=game_objects_index_)
            ||(value&&api_.object_class(value)!=field.reference))return fail("factory_object_value_type_mismatch");
        try {
            Root owner_root(api_,owner),value_root(api_,value);
            if(!owner_root||(value&&!value_root))return fail("factory_gc_handle_failed");
            api_.field_set_value(owner_root.get(),field.field,value_root.get());
            error_="none";return true;
        } catch(...) {return fail("factory_field_assignment_exception");}
    }
    bool set_i32(void* owner,const char* name,int32_t value) {
        const int slot=field_slot(owner,name);if(slot<0)return fail("factory_integer_field_invalid");
        const int kind=definitions_()[slot].kind;
        if(kind!=8&&(slot!=collider_index_||kind!=17))return fail("factory_integer_field_invalid");
        if(slot==collider_index_&&value!=0&&value!=1)return fail("factory_collider_value_invalid");
        return assign(owner,fields_[slot].field,&value);
    }
    bool set_bool(void* owner,const char* name,bool value) {
        const int slot=field_slot(owner,name);
        if(slot<0||definitions_()[slot].kind!=2)return fail("factory_boolean_field_invalid");
        uint8_t managed=value?1:0;return assign(owner,fields_[slot].field,&managed);
    }
private:
    using Constructor=void(*)(void*,Method*);
    using Add=void(*)(void*,void*,Method*);
    struct Definition {Kind owner;const char*name;int32_t kind;};
    struct Field {void*field=nullptr;void*reference=nullptr;};
    static constexpr size_t field_count_=13;
    static constexpr int assets_index_=2,name_index_=3,game_objects_index_=4,collider_index_=6,live_param_index_=11;
    static const Definition*definitions_() {
        static constexpr Definition values[field_count_]={
            {Kind::out_game_param,"stageMaxCapacity",8},
            {Kind::out_game_param,"detachActorsOnPlayerDestroyed",2},
            {Kind::actor_descriptor,"_assets",21},
            {Kind::actor_descriptor,"_name",14},
            {Kind::actor_descriptor,"_gameObjects",29},
            {Kind::actor_descriptor,"_humanoid",2},
            {Kind::actor_descriptor,"_colliderType",17},
            {Kind::actor_descriptor,"_colliderTrigger",2},
            {Kind::actor_descriptor,"_autoBlinkDisabled",2},
            {Kind::actor_descriptor,"_useADVSettings",2},
            {Kind::actor_descriptor,"_renderingLayerMaskBaseIndex",8},
            {Kind::transition_param,"liveParam",18},
            {Kind::transition_param,"isDebugMode",2},
        };return values;
    }
    class Root {
    public:
        Root(const Calls&api,void* object):api_(api),handle_(object?api.strong_new(object,false):0){}
        ~Root(){if(handle_)api_.release(handle_);}
        Root(const Root&)=delete;Root&operator=(const Root&)=delete;
        void*get()const{return handle_?api_.target(handle_):nullptr;}
        explicit operator bool()const{return get()!=nullptr;}
    private:const Calls&api_;uint32_t handle_=0;
    };
    template<class Function>static Function method_pointer(Method*method) {
        Function call=nullptr;if(method)::memcpy(&call,method,sizeof(call));return call;
    }
    void*type(Kind kind)const {
        switch(kind){case Kind::out_game_param:return classes_.out_game_param;
        case Kind::actor_descriptor:return classes_.actor_descriptor;
        case Kind::transition_param:return classes_.transition_param;default:return nullptr;}
    }
    bool named(void*klass,const char*space,const char*name)const {
        if(!klass)return false;
        const char*actual_name=api_.class_name(klass),*actual_space=api_.class_namespace(klass);
        return actual_name&&actual_space&&!::strcmp(actual_name,name)&&!::strcmp(actual_space,space);
    }
    void*find_field(void*klass,const char*name)const {
        for(unsigned depth=0;klass&&depth<32;++depth,klass=api_.class_parent(klass))
            if(void*field=api_.field(klass,name))return field;
        return nullptr;
    }
    int field_slot(void*owner,const char*name)const {
        if(!ready_||!owner||!name)return -1;
        void*klass=api_.object_class(owner);const Definition* definitions=definitions_();
        for(size_t i=0;i<field_count_;++i)
            if(type(definitions[i].owner)==klass&&!::strcmp(name,definitions[i].name))return static_cast<int>(i);
        return -1;
    }
    bool assign(void*owner,void*field,void*value) {
        try {
            Root root(api_,owner);if(!root)return fail("factory_gc_handle_failed");
            api_.field_set_value(root.get(),field,value);error_="none";return true;
        } catch(...) {return fail("factory_field_assignment_exception");}
    }
    bool fail(const char*error){error_=error;return false;}
    Calls api_{};Classes classes_{};Field fields_[field_count_]{};
    void*assets_class_=nullptr,*string_class_=nullptr;Method*list_ctor_=nullptr,*list_add_=nullptr;
    bool ready_=false;const char*error_="factory_api_unavailable";
};
} // namespace idoly_mp4_replay_factories
