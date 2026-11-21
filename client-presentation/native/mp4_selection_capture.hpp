// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include "mp4_game_adapter.hpp"
#include "mp4_queue.hpp"

namespace idoly_mp4_selection {
using Result=idoly_mp4_game::Result;
using Api=idoly_mp4_game::Api;
using Descriptor=idoly_mp4_queue::Descriptor;
// Reproduced from both pinned originals by audit_mp4_{ios_,}game.py.
struct Layout {
    size_t actors=0x10,stage=0x18,timeline=0x20,detach=0x28,stage_max_capacity=0x2c;
    size_t list_items=0x10,list_count=0x18;
    size_t character=0x10,actor_index=0x18,psyllium=0x1c,track_index=0x20,descriptor=0x28,audience=0x30;
    size_t assets=0x10,name=0x18,game_objects=0x20,humanoid=0x28,collider=0x2c,trigger=0x30,
        auto_blink=0x31,adv=0x32,render_layer=0x34;
};
// This cache has only ephemeral, bounded Unity player roots. Serialized queue
// records contain Descriptor values exclusively; no managed pointer is saved.
class Capture {
public:
    static constexpr size_t capacity=16;
    Capture()=default;
    Capture(const Capture&)=delete;Capture&operator=(const Capture&)=delete;
    bool set_api(Api api,Layout layout={}) {
        if(!api.is_type||!api.alive||!api.retain||!api.retained||!api.release
            ||!api.array_length||!api.array_data||!api.string_utf8)return false;
        reset();api_=api;layout_=layout;return true;
    }
    Result observe(void* player,void* param) {
        if(!api_.is_type)return fail(Result::unsupported,"selection_api_unavailable");
        maintenance();
        if(!is(player,"Solis.Common.SolisLivePlayer")||!api_.alive(player))return fail(Result::stale,"selection_player_unavailable");
        Entry* slot=nullptr;
        for(auto& entry:entries_)if(entry.handle&&api_.retained(entry.handle)==player){slot=&entry;break;}
        if(!slot){
            for(auto& entry:entries_)if(!entry.handle){slot=&entry;break;}
            if(!slot){slot=&entries_[0];for(auto& entry:entries_)if(entry.sequence<slot->sequence)slot=&entry;clear(*slot);}
            slot->handle=api_.retain(player);if(!slot->handle)return fail(Result::failed,"selection_handle_failed");
        }
        slot->valid=false;slot->sequence=++sequence_;
        slot->error="invalid_selection_parameter";
        if(!is(param,"Solis.OutGame.OutGameLivePlayerParam"))return fail_entry(*slot,Result::unsupported,"unsupported_selection_parameter");
        scratch_=Descriptor{};
        if(!text(field<void*>(param,layout_.stage),scratch_.stage_asset)
            ||!text(field<void*>(param,layout_.timeline),scratch_.timeline_asset))
            return fail_entry(*slot,Result::invalid,"selection_asset_name_invalid");
        const uint8_t detach=field<uint8_t>(param,layout_.detach);
        if(detach>1)return fail_entry(*slot,Result::invalid,"selection_detach_flag_invalid");
        scratch_.detach_actors_on_player_destroyed=detach;
        scratch_.stage_max_capacity=field<int32_t>(param,layout_.stage_max_capacity);
        void** actors=nullptr;size_t count=0;
        if(!list(field<void*>(param,layout_.actors),idoly_mp4_queue::max_actors,actors,count)||!count)
            return fail_entry(*slot,Result::invalid,"selection_actor_list_invalid");
        scratch_.actor_count=static_cast<uint32_t>(count);
        for(size_t i=0;i<count;++i){
            void* value=actors[i];auto& actor=scratch_.actors[i];
            if(!is(value,"SolisLiveActorParam")||!text(field<void*>(value,layout_.character),actor.character_id))
                return fail_entry(*slot,Result::invalid,"selection_actor_parameter_invalid");
            actor.actor_index=field<int32_t>(value,layout_.actor_index);actor.track_index=field<int32_t>(value,layout_.track_index);
            actor.psyllium_color_type=field<int32_t>(value,layout_.psyllium);actor.audience_amount=field<int32_t>(value,layout_.audience);
            void* descriptor=field<void*>(value,layout_.descriptor);
            if(!is(descriptor,"Solis.Common.SolisActorDescriptor"))return fail_entry(*slot,Result::invalid,"selection_actor_descriptor_invalid");
            void* objects=field<void*>(descriptor,layout_.game_objects);
            if(objects&&api_.array_length(objects))return fail_entry(*slot,Result::unsupported,"selection_dynamic_game_objects_unsupported");
            void* name=field<void*>(descriptor,layout_.name);
            actor.name_is_null=name?0:1;
            if(name&&!text(name,actor.descriptor_name,true))return fail_entry(*slot,Result::invalid,"selection_descriptor_name_invalid");
            actor.humanoid=field<uint8_t>(descriptor,layout_.humanoid);actor.collider_type=field<int32_t>(descriptor,layout_.collider);
            actor.trigger=field<uint8_t>(descriptor,layout_.trigger);actor.auto_blink_disabled=field<uint8_t>(descriptor,layout_.auto_blink);
            actor.use_adv_settings=field<uint8_t>(descriptor,layout_.adv);actor.render_layer_base=field<int32_t>(descriptor,layout_.render_layer);
            void** assets=nullptr;size_t asset_count=0;
            if(!list(field<void*>(descriptor,layout_.assets),idoly_mp4_queue::max_assets,assets,asset_count)||!asset_count)
                return fail_entry(*slot,Result::invalid,"selection_actor_assets_invalid");
            actor.asset_count=static_cast<uint32_t>(asset_count);
            for(size_t j=0;j<asset_count;++j)if(!text(assets[j],actor.assets[j]))
                return fail_entry(*slot,Result::invalid,"selection_actor_asset_name_invalid");
        }
        if(!idoly_mp4_queue::detail::descriptor(scratch_))return fail_entry(*slot,Result::unsupported,"selection_descriptor_unsupported");
        slot->descriptor=scratch_;slot->valid=true;slot->error="none";error_="none";return Result::ok;
    }
    Result selected(void* player,Descriptor& output) {
        maintenance();
        if(!player||!api_.alive||!api_.alive(player))return fail(Result::stale,"selection_player_unavailable");
        for(auto& entry:entries_)if(entry.handle&&api_.retained(entry.handle)==player){
            if(!entry.valid)return fail(Result::unsupported,entry.error);
            output=entry.descriptor;error_="none";return Result::ok;
        }
        return fail(Result::waiting,"selection_initialization_not_observed");
    }
    uint64_t identity(void* player)const {
        for(const auto& entry:entries_)if(entry.handle&&entry.valid&&api_.retained(entry.handle)==player)return entry.sequence;
        return 0;
    }
    void maintenance(){
        if(!api_.retained||!api_.alive)return;
        for(auto& entry:entries_)if(entry.handle){void* player=api_.retained(entry.handle);if(!player||!api_.alive(player))clear(entry);}
    }
    void reset(){for(auto& entry:entries_)clear(entry);sequence_=0;error_="none";}
    const char* error()const{return error_;}
private:
    struct Entry {uint32_t handle=0;uint64_t sequence=0;Descriptor descriptor{};bool valid=false;const char*error="none";};
    Api api_{};Layout layout_{};Entry entries_[capacity]{};Descriptor scratch_{};uint64_t sequence_=0;const char*error_="none";
    template<class T>static T field(void* object,size_t offset){T result{};if(object)std::memcpy(&result,static_cast<uint8_t*>(object)+offset,sizeof(result));return result;}
    bool is(void* object,const char* type)const{return object&&api_.is_type&&api_.is_type(object,type);}
    bool text(void* value,char* out,bool empty=false)const{
        if(!is(value,"System.String"))return false;
        const size_t n=api_.string_utf8(value,out,idoly_mp4_queue::name_capacity);
        return n<idoly_mp4_queue::name_capacity&&(empty||n>0);
    }
    bool list(void* value,size_t maximum,void**& items,size_t& count)const{
        if(!is(value,"System.Collections.Generic.List`1"))return false;
        const int32_t length=field<int32_t>(value,layout_.list_count);void* backing=field<void*>(value,layout_.list_items);
        if(length<0||static_cast<size_t>(length)>maximum||!backing)return false;
        const size_t capacity=api_.array_length(backing);
        if(capacity>4096||static_cast<size_t>(length)>capacity)return false;
        items=static_cast<void**>(api_.array_data(backing));count=static_cast<size_t>(length);return !count||items;
    }
    void clear(Entry& entry){if(entry.handle&&api_.release)api_.release(entry.handle);entry.handle=0;entry.valid=false;entry.sequence=0;entry.error="none";}
    Result fail(Result code,const char* error){error_=error;return code;}
    Result fail_entry(Entry& entry,Result code,const char* error){entry.error=error;return fail(code,error);}
};
} // namespace idoly_mp4_selection
