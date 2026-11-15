#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <pthread.h>
#include <utility>

namespace idoly::presentation::wardrobe_timing {
enum class Room : uint8_t { None, CharacterCostume, FittingRoom };
enum class Stage : uint8_t { None, Back, Preclose, Hide, Disable, SelectionShow, SelectionOpen, GC, Unload, Completed };
inline const char *name(Room value) {
    switch (value) {
    case Room::CharacterCostume: return "character_costume";
    case Room::FittingRoom: return "fitting_room";
    default: return "none";
    }
}
inline const char *name(Stage value) {
    switch (value) {
    case Stage::Back: return "back";
    case Stage::Preclose: return "preclose";
    case Stage::Hide: return "hide";
    case Stage::Disable: return "disable";
    case Stage::SelectionShow: return "selection_show";
    case Stage::SelectionOpen: return "selection_open";
    case Stage::GC: return "gc";
    case Stage::Unload: return "unload";
    case Stage::Completed: return "completed";
    default: return "idle";
    }
}
inline bool callable(Stage value) { return value >= Stage::Back && value <= Stage::Unload; }
struct Span { Stage stage=Stage::None; int64_t duration_ms=0; };
struct Snapshot {
    Room room=Room::None;
    Stage phase=Stage::None, max_stage=Stage::None;
    bool active=false, in_original=false;
    int64_t elapsed_ms=-1, last_sync_ms=0, max_sync_ms=0, sequence=0;
    size_t span_count=0;
    Span spans[8]{};
};

// Diagnostic clocks only. These scopes never keep, await, poll, complete or
// replace a managed task, and never change a token, argument, result or error.
// The mutex protects small state copies only; no original game function or
// clock is called while it is held, so JNI can observe an ongoing long call.
class Tracker {
public:
    using Clock = int64_t (*)();
    static constexpr int64_t window_ms=120000;
    struct Stamp {
        uint64_t generation=0, serial=0, parent_serial=0;
        Stage stage=Stage::None, parent_stage=Stage::None;
        int64_t started_ms=-1;
    };
private:
    struct Guard {
        pthread_mutex_t *mutex;
        explicit Guard(pthread_mutex_t &value) : mutex(&value) { pthread_mutex_lock(mutex); }
        ~Guard() { pthread_mutex_unlock(mutex); }
        Guard(const Guard &)=delete;
        Guard &operator=(const Guard &)=delete;
    };
    mutable pthread_mutex_t mutex_=PTHREAD_MUTEX_INITIALIZER;
    Clock clock_=nullptr; // Configured once before bridge publication.
    Snapshot state_{};
    uint64_t generation_=0, next_serial_=0, current_serial_=0;
    int64_t started_ms_=-1, completed_ms_=-1;
    bool pending_=false;
    static int64_t increment(int64_t value) { return value<INT64_MAX ? value+1 : INT64_MAX; }
    int64_t now() const { return clock_ ? clock_() : -1; }
    bool active_locked(int64_t at) const {
        return pending_ && started_ms_>=0 && at>=started_ms_ && at-started_ms_<=window_ms;
    }
    Stamp begin_locked(Stage stage, int64_t at) {
        if (!callable(stage) || !active_locked(at) || next_serial_==UINT64_MAX) return {};
        Stamp stamp{generation_,++next_serial_,current_serial_,stage,state_.phase,at};
        current_serial_=stamp.serial; state_.phase=stage; state_.in_original=true;
        state_.sequence=increment(state_.sequence);
        return stamp;
    }
    Stamp arm_locked(Room room,Stage stage,int64_t at) {
        if (at<0 || (room!=Room::CharacterCostume && room!=Room::FittingRoom)) return {};
        if (current_serial_) return begin_locked(stage,at);
        if (generation_==UINT64_MAX) return {};
        const int64_t sequence=increment(state_.sequence);
        state_=Snapshot{}; state_.room=room; state_.sequence=sequence;
        ++generation_; next_serial_=0; current_serial_=0;
        started_ms_=at; completed_ms_=-1; pending_=true;
        return begin_locked(stage,at);
    }
public:
    Tracker()=default;
    Tracker(const Tracker &)=delete;
    Tracker &operator=(const Tracker &)=delete;
    void configure(Clock clock) { clock_=clock; }
    bool ready() const { return clock_!=nullptr; }
    bool active() const { const int64_t at=now(); Guard guard(mutex_); return active_locked(at); }
    Stamp begin_back(Room room) {
        const int64_t at=now(); Guard guard(mutex_);
        // Reentrant back dispatch belongs to the enclosing original call.
        return arm_locked(room,Stage::Back,at);
    }
    Stamp begin_close(Room room,Stage stage) {
        const int64_t at=now(); Guard guard(mutex_);
        // UI close bindings can bypass RecursiveBack. An exact close-boundary
        // hook can arm observation itself without inventing a back event or
        // resetting an existing active transition's elapsed clock and maxima.
        if (stage!=Stage::Preclose && stage!=Stage::Hide) return {};
        if (active_locked(at)) return begin_locked(stage,at);
        return arm_locked(room,stage,at);
    }
    Stamp begin(Stage stage) {
        const int64_t at=now(); Guard guard(mutex_); return begin_locked(stage,at);
    }
    void finish(const Stamp &stamp) {
        if (!stamp.serial) return;
        const int64_t at=now(); Guard guard(mutex_);
        if (stamp.generation!=generation_ || stamp.serial!=current_serial_) return;
        if (at>=stamp.started_ms && stamp.started_ms>=0) {
            const int64_t duration=at-stamp.started_ms;
            state_.last_sync_ms=duration;
            if (state_.max_stage==Stage::None || duration>state_.max_sync_ms) {
                state_.max_sync_ms=duration; state_.max_stage=stamp.stage;
            }
            // Retain the maximum measured span of each of the eight stages.
            // Short repeated await-resumption calls cannot evict a slow stage.
            size_t index=0;
            while (index<state_.span_count && state_.spans[index].stage!=stamp.stage) ++index;
            if (index==state_.span_count && state_.span_count<8) {
                state_.spans[index]={stamp.stage,duration}; ++state_.span_count;
            } else if (index<state_.span_count && duration>state_.spans[index].duration_ms) {
                state_.spans[index].duration_ms=duration;
            }
        }
        current_serial_=stamp.parent_serial; state_.in_original=current_serial_!=0;
        state_.phase=current_serial_ ? stamp.parent_stage : (pending_ ? stamp.stage : Stage::Completed);
        state_.sequence=increment(state_.sequence);
    }
    void complete() {
        const int64_t at=now(); Guard guard(mutex_);
        if (!active_locked(at)) return;
        pending_=false; completed_ms_=at;
        if (!current_serial_) state_.phase=Stage::Completed;
        state_.sequence=increment(state_.sequence);
    }
    Snapshot snapshot(int64_t at) const {
        Guard guard(mutex_); Snapshot result=state_;
        result.active=active_locked(at);
        const int64_t end=completed_ms_>=0 ? completed_ms_ : at;
        if (started_ms_>=0 && end>=started_ms_) result.elapsed_ms=end-started_ms_;
        return result;
    }
    class Scope {
        Tracker *owner_;
        Stamp stamp_;
    public:
        Scope(Tracker &owner, Stamp stamp) : owner_(&owner),stamp_(stamp) {}
        ~Scope() { owner_->finish(stamp_); }
        Scope(const Scope &)=delete;
        Scope &operator=(const Scope &)=delete;
    };
    template<class F, class... Args>
    decltype(auto) invoke(Stage stage,F original,Args&&... args) {
        Scope scope(*this,begin(stage)); return original(std::forward<Args>(args)...);
    }
    template<class F, class... Args>
    decltype(auto) invoke_back(Room room,F original,Args&&... args) {
        Scope scope(*this,begin_back(room)); return original(std::forward<Args>(args)...);
    }
    template<class F, class... Args>
    decltype(auto) invoke_close(Room room,Stage stage,F original,Args&&... args) {
        Scope scope(*this,begin_close(room,stage)); return original(std::forward<Args>(args)...);
    }
    // Emits exactly the schema-1 nested exit object. Legacy failure diagnostics
    // remain a separate outer object; output contains no pointers or account IDs.
    static bool json(const Snapshot &value,char *output,size_t capacity) {
        if (!output || !capacity) return false;
        char elapsed[32];
        if (value.elapsed_ms<0) std::snprintf(elapsed,sizeof elapsed,"null");
        else std::snprintf(elapsed,sizeof elapsed,"%lld",static_cast<long long>(value.elapsed_ms));
        int count=std::snprintf(output,capacity,"{\"schema\":1,\"room\":\"%s\",\"phase\":\"%s\","
            "\"active\":%s,\"in_original\":%s,\"elapsed_ms\":%s,\"last_sync_ms\":%lld,"
            "\"max_sync_ms\":%lld,\"max_sync_stage\":\"%s\",\"sequence\":%lld,\"spans\":[",
            name(value.room),name(value.phase),value.active?"true":"false",value.in_original?"true":"false",
            elapsed,static_cast<long long>(value.last_sync_ms),static_cast<long long>(value.max_sync_ms),
            value.max_stage==Stage::None?"none":name(value.max_stage),static_cast<long long>(value.sequence));
        if (count<0 || static_cast<size_t>(count)>=capacity) return false;
        size_t used=static_cast<size_t>(count);
        for (size_t i=0;i<value.span_count && i<8;++i) {
            count=std::snprintf(output+used,capacity-used,"%s{\"stage\":\"%s\",\"duration_ms\":%lld}",
                i?",":"",name(value.spans[i].stage),static_cast<long long>(value.spans[i].duration_ms));
            if (count<0 || static_cast<size_t>(count)>=capacity-used) return false;
            used+=static_cast<size_t>(count);
        }
        count=std::snprintf(output+used,capacity-used,"]}");
        return count>=0 && static_cast<size_t>(count)<capacity-used;
    }
};
} // namespace idoly::presentation::wardrobe_timing
