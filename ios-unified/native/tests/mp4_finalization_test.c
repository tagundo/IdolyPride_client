// SPDX-License-Identifier: AGPL-3.0-or-later
#include "../MP4FinalizationPolicy.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    IDMP4FinalizationPolicy state = {0};
    uintptr_t identifier = 77;
    assert(!IDMP4FinalizationEnd(&state,0,&identifier));
    assert(identifier == 77);
    uint64_t first = IDMP4FinalizationBegin(&state);
    assert(first == 1 && state.pending && !state.active);
    assert(IDMP4FinalizationBegin(&state) == 0);
    // A returned zero task ID is valid and must be ended exactly once.
    assert(IDMP4FinalizationGrant(&state,first,0,true));
    assert(state.active && !state.pending);
    assert(IDMP4FinalizationBegin(&state) == 0);
    assert(IDMP4FinalizationEnd(&state,first,&identifier) && identifier == 0);
    assert(!IDMP4FinalizationEnd(&state,first,&identifier));
    // A timer from the first assertion cannot end a newer reused OS task ID.
    uint64_t second = IDMP4FinalizationBegin(&state);
    assert(second > first && IDMP4FinalizationGrant(&state,second,0,true));
    assert(!IDMP4FinalizationEnd(&state,first,&identifier));
    assert(state.active);
    assert(IDMP4FinalizationEnd(&state,0,&identifier) && identifier == 0);
    // OS rejection leaves no assertion and permits a future attempt.
    uint64_t rejected = IDMP4FinalizationBegin(&state);
    assert(!IDMP4FinalizationGrant(&state,rejected,99,false));
    assert(!state.active && !state.pending);
    assert(!IDMP4FinalizationEnd(&state,rejected,&identifier));
    // Expiration (or foregrounding) during begin invalidates the pending
    // grant. UIKit's caller then ends the returned valid OS task directly.
    uint64_t expired = IDMP4FinalizationBegin(&state);
    assert(!IDMP4FinalizationEnd(&state,expired,&identifier));
    assert(!IDMP4FinalizationGrant(&state,expired,123,true));
    assert(!state.active && !state.pending);
    uint64_t current = IDMP4FinalizationBegin(&state);
    assert(!IDMP4FinalizationGrant(&state,expired,123,true));
    assert(state.pending);
    assert(IDMP4FinalizationGrant(&state,current,456,true));
    assert(!IDMP4FinalizationEnd(&state,expired,&identifier));
    assert(state.active);
    assert(IDMP4FinalizationEnd(&state,current,&identifier) && identifier == 456);
    state.generation = UINT64_MAX;
    assert(IDMP4FinalizationBegin(&state) == 0);
    puts("PASS MP4 finalization policy");
    return 0;
}
