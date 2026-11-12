// Original iOS 6.1.1 phone-turn UX adapted only on a verified Mac desktop.
// The caller wires pinned ORIGINAL functions before publishing any hooks.
#pragma once
namespace idoly::presentation::ios_orientation {
using Method = const void;
struct CancellationToken { void *source; };
struct UniTask { void *source; signed short token; unsigned char padding[6]; };
static_assert(sizeof(CancellationToken)==8, "original CancellationToken ABI");
static_assert(sizeof(UniTask)==16 && __builtin_offsetof(UniTask,token)==8,
              "original nongeneric UniTask x0/x1 ABI");

using Wait = UniTask (*)(int, CancellationToken, Method *);
using WaitLabel = UniTask (*)(int, void *, CancellationToken, Method *);
using WaitOption = UniTask (*)(int, bool, CancellationToken, Method *);
using Predicate = bool (*)(void *, Method *);
using MoveNext = void (*)(void *, Method *);

struct Calls {
    // enabled must combine the static-install ready flag with the platform's
    // actual iOS-on-Mac test, never a user graphics preference.
    bool (*desktop_enabled)() = nullptr;
    bool (*game_thread)(bool establish) = nullptr;
    int (*frame_count)(Method *) = nullptr;
    int (*screen_width)(Method *) = nullptr;
    int (*screen_height)(Method *) = nullptr;
    bool (*token_cancelled)(CancellationToken *, Method *) = nullptr;
    UniTask (*set_orientation_async)(int, Method *) = nullptr;
};
inline Calls calls;
inline Wait original_wait = nullptr;
inline WaitLabel original_wait_label = nullptr;
inline WaitOption original_wait_simple = nullptr, original_wait_preview = nullptr;
inline MoveNext original_internal_move = nullptr;
inline Predicate original_starts_portrait = nullptr, original_starts_landscape = nullptr;
inline Predicate original_fixed_portrait = nullptr, original_fixed_landscape = nullptr;
inline Predicate original_after = nullptr;
// These are adapter bookkeeping only. No managed state machine or clock is
// modified. Access is confined to the verified original Unity thread.
inline bool begin_seen = false;
inline uint32_t begin_frame = 0;

inline void configure(const Calls &value) { calls=value; }
inline bool ready_for_publish() {
    return calls.desktop_enabled && calls.game_thread && calls.frame_count
        && calls.screen_width && calls.screen_height && calls.token_cancelled
        && calls.set_orientation_async && original_wait && original_wait_label
        && original_wait_simple && original_wait_preview && original_internal_move
        && original_starts_portrait && original_starts_landscape
        && original_fixed_portrait && original_fixed_landscape && original_after;
}
inline bool active(bool establish=false) {
    return calls.desktop_enabled && calls.desktop_enabled()
        && calls.game_thread && calls.game_thread(establish);
}
inline bool redirect(CancellationToken token) {
    return active(true) && calls.set_orientation_async && calls.token_cancelled
        && !calls.token_cancelled(&token,nullptr);
}

// All four original static overloads only select description/label/preview UI;
// there is no completion callback argument to drop. Their common state machine
// first awaits PUBLIC SetOrientationAsync(FixedPortrait) with its OWN CTS, then
// uses the caller token in the physical-turn view. Desktop removes that view
// and returns the REAL public FixedLandscape task, retaining its normal
// CancelThenNewToken and Before/After pipeline. As in that original orientation
// substep, the caller token is not externally linked mid-transition. A token
// already cancelled follows the complete original overload unchanged.
inline UniTask wait_hook(int description,CancellationToken token,Method *method) {
    return redirect(token) ? calls.set_orientation_async(3,nullptr)
                           : original_wait(description,token,method);
}
inline UniTask wait_label_hook(int description,void *label,CancellationToken token,Method *method) {
    return redirect(token) ? calls.set_orientation_async(3,nullptr)
                           : original_wait_label(description,label,token,method);
}
inline UniTask wait_simple_hook(int description,bool simple,CancellationToken token,Method *method) {
    return redirect(token) ? calls.set_orientation_async(3,nullptr)
                           : original_wait_simple(description,simple,token,method);
}
inline UniTask wait_preview_hook(int description,bool preview,CancellationToken token,Method *method) {
    return redirect(token) ? calls.set_orientation_async(3,nullptr)
                           : original_wait_preview(description,preview,token,method);
}

// Public wrappers inline this state-machine startup. Hook its original unboxed
// MoveNext, recording ONLY the initial -1 state, never each continuation.
inline void internal_move_hook(void *self,Method *method) {
    if (self && active(true) && calls.frame_count) {
        int32_t state=0;
        ::memcpy(&state,self,sizeof state);
        if (state==-1) {
            begin_frame=static_cast<uint32_t>(calls.frame_count(nullptr));
            begin_seen=true;
        }
    }
    original_internal_move(self,method);
}
inline bool settled(void *self,Method *method,Predicate original) {
    // An install arriving during an already-running transition keeps its
    // original behavior until an original start has actually been observed.
    if (!active() || !begin_seen || !calls.frame_count || !calls.screen_width || !calls.screen_height)
        return original(self,method);
    const uint32_t elapsed=static_cast<uint32_t>(calls.frame_count(nullptr))-begin_frame;
    return elapsed>=2 && elapsed<0x80000000u
        && calls.screen_width(nullptr)>0 && calls.screen_height(nullptr)>0;
}
inline bool starts_portrait_hook(void *self,Method *method) { return settled(self,method,original_starts_portrait); }
inline bool starts_landscape_hook(void *self,Method *method) { return settled(self,method,original_starts_landscape); }
inline bool fixed_portrait_hook(void *self,Method *method) { return settled(self,method,original_fixed_portrait); }
inline bool fixed_landscape_hook(void *self,Method *method) { return settled(self,method,original_fixed_landscape); }
inline bool after_hook(void *self,Method *method) { return settled(self,method,original_after); }
} // namespace idoly::presentation::ios_orientation
