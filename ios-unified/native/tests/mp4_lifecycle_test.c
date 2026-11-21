// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../MP4LifecyclePolicy.h"
#include <assert.h>
#include <stdio.h>

static int suspends, resumes, last_reason;
static void suspend_export(int reason) { ++suspends; last_reason = reason; }
static void resume_export(void) { ++resumes; last_reason = 0; }
int main(void) {
    IDMP4LifecyclePolicy state = ID_MP4_LIFECYCLE_POLICY_INITIALIZER;
    IDMP4LifecycleSetActive(&state, false, suspend_export, resume_export);
    assert(suspends == 1 && resumes == 0 && last_reason == 1);
    IDMP4LifecycleSetUserPaused(&state, true, suspend_export, resume_export);
    assert(last_reason == 3);
    IDMP4LifecycleSetActive(&state, true, suspend_export, resume_export);
    assert(last_reason == 3 && resumes == 0);
    IDMP4LifecycleSetActive(&state, false, suspend_export, resume_export);
    assert(last_reason == 3 && resumes == 0);
    // Resuming from the server panel while backgrounded must not wake Unity.
    IDMP4LifecycleSetUserPaused(&state, false, suspend_export, resume_export);
    assert(last_reason == 1 && resumes == 0);
    IDMP4LifecycleSetActive(&state, true, suspend_export, resume_export);
    assert(last_reason == 0 && resumes == 1);
    IDMP4LifecycleSetUserPaused(&state, true, suspend_export, resume_export);
    IDMP4LifecycleSetUserPaused(&state, false, suspend_export, resume_export);
    assert(resumes == 2 && !state.user_paused && state.active);
    // An older optional addon may not export the callbacks; policy remains safe.
    IDMP4LifecycleSetActive(&state, false, NULL, NULL);
    IDMP4LifecycleSetUserPaused(&state, true, NULL, NULL);
    IDMP4LifecycleSetActive(&state, true, suspend_export, resume_export);
    assert(last_reason == 3 && resumes == 2);
    assert(pthread_mutex_destroy(&state.mutex) == 0);
    puts("PASS MP4 lifecycle policy");
    return 0;
}
