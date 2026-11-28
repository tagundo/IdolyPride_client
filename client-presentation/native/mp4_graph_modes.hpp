#pragma once
#include "mp4_game_adapter.hpp"
namespace idoly_mp4_game {
// Original setter observations are process metadata, not owning Unity handles.
// Caller serializes reads/writes. Latest observations use bounded LRU storage;
// an active export owns a copy of all restoration modes. Unknown modes reject.
class GraphModes {
    struct Entry { void* handle=nullptr;int32_t version=0,mode=0;uint64_t used=0; };
    Entry entries_[128]{};uint64_t serial_=0;
public:
    bool record(const PlayableGraph& graph,int32_t mode) {
        if(!graph.handle||mode<0||mode>3)return false;
        for(auto& e:entries_)if(e.handle==graph.handle&&e.version==graph.version){e.mode=mode;e.used=++serial_;return true;}
        Entry* oldest=&entries_[0];
        for(auto& e:entries_){if(!e.handle){e={graph.handle,graph.version,mode,++serial_};return true;}if(e.used<oldest->used)oldest=&e;}
        *oldest={graph.handle,graph.version,mode,++serial_};return true;
    }
    bool get(const PlayableGraph& graph,int32_t* mode) {
        if(!graph.handle||!mode)return false;
        for(auto& e:entries_)if(e.handle==graph.handle&&e.version==graph.version){*mode=e.mode;e.used=++serial_;return true;}
        return false;
    }
};
} // namespace idoly_mp4_game
