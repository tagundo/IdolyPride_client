// SPDX-License-Identifier: AGPL-3.0-or-later
#ifndef IDOLY_MP4_FINALIZATION_POLICY_H
#define IDOLY_MP4_FINALIZATION_POLICY_H
#include <stdbool.h>
#include <stdint.h>

// UIKit owns all calls on main. Presence is independent of the numeric OS task
// identifier: zero is a valid value, and UIBackgroundTaskInvalid is an extern
// UIKit constant that cannot initialize a C static. Generations also prevent a
// stale expiration/timer from ending a newer task with a reused OS identifier.
typedef struct {
    uint64_t generation;
    uintptr_t identifier;
    bool active;
    bool pending;
} IDMP4FinalizationPolicy;

static inline uint64_t IDMP4FinalizationBegin(IDMP4FinalizationPolicy *state) {
    if (state->active || state->pending || state->generation == UINT64_MAX) return 0;
    state->pending = true;
    return ++state->generation;
}
static inline bool IDMP4FinalizationGrant(IDMP4FinalizationPolicy *state,
        uint64_t generation, uintptr_t identifier, bool valid) {
    if (!generation || generation != state->generation || !state->pending) return false;
    state->pending = false;
    if (!valid) return false;
    state->identifier = identifier;
    state->active = true;
    return true;
}
// Generation zero means an explicit foreground/completion end of the current
// assertion. Ending a pending grant invalidates it; its caller must end the OS
// identifier directly if beginBackgroundTask subsequently returns a valid one.
static inline bool IDMP4FinalizationEnd(IDMP4FinalizationPolicy *state,
        uint64_t generation, uintptr_t *identifier) {
    if (generation && generation != state->generation) return false;
    state->pending = false;
    if (!state->active || !identifier) return false;
    *identifier = state->identifier;
    state->active = false;
    return true;
}
#endif
