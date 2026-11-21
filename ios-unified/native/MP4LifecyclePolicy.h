// SPDX-License-Identifier: AGPL-3.0-or-later
#ifndef IDOLY_MP4_LIFECYCLE_POLICY_H
#define IDOLY_MP4_LIFECYCLE_POLICY_H
#include <stdbool.h>
#include <pthread.h>

// UIKit lifecycle events and the trusted command worker can arrive together.
// Serialize the decision and its native call so a late foreground callback
// cannot resume an export after a newer background or explicit pause.
typedef struct {
    pthread_mutex_t mutex;
    bool active;
    bool user_paused;
} IDMP4LifecyclePolicy;
#define ID_MP4_LIFECYCLE_POLICY_INITIALIZER { PTHREAD_MUTEX_INITIALIZER, true, false }
typedef void (*IDMP4SuspendCall)(int reason);
typedef void (*IDMP4ResumeCall)(void);
static inline void IDMP4LifecycleApplyLocked(IDMP4LifecyclePolicy *state,
        IDMP4SuspendCall suspend, IDMP4ResumeCall resume) {
    if (state->user_paused) { if (suspend) suspend(3); }
    else if (!state->active) { if (suspend) suspend(1); }
    else if (resume) resume();
}
static inline void IDMP4LifecycleSetActive(IDMP4LifecyclePolicy *state, bool active,
        IDMP4SuspendCall suspend, IDMP4ResumeCall resume) {
    pthread_mutex_lock(&state->mutex);
    state->active = active;
    IDMP4LifecycleApplyLocked(state, suspend, resume);
    pthread_mutex_unlock(&state->mutex);
}
static inline void IDMP4LifecycleSetUserPaused(IDMP4LifecyclePolicy *state, bool paused,
        IDMP4SuspendCall suspend, IDMP4ResumeCall resume) {
    pthread_mutex_lock(&state->mutex);
    state->user_paused = paused;
    IDMP4LifecycleApplyLocked(state, suspend, resume);
    pthread_mutex_unlock(&state->mutex);
}
#endif
