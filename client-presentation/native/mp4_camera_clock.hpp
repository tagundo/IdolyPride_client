#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstdint>
#include <cstddef>
#endif
namespace idoly_mp4_game {
class CameraGrant {
    void* seen_[128]{};size_t count_=0;bool failed_=false;
public:
    enum class Visit { first, duplicate, failed };
    void begin(){count_=0;failed_=false;}
    Visit visit(void* camera){
        if(!camera){failed_=true;return Visit::failed;}
        for(size_t i=0;i<count_;++i)if(seen_[i]==camera)return Visit::duplicate;
        if(count_==128){failed_=true;return Visit::failed;}
        seen_[count_++]=camera;return Visit::first;
    }
    void fail(){failed_=true;}
    bool ok()const{return !failed_;}
    static bool rebase_late_frame(int32_t current,int32_t* last){
        if(current<=0||!last)return false;
        *last=current-1;return true;
    }
};
} // namespace idoly_mp4_game
