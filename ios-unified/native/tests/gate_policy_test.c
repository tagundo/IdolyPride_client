#include "../GatePolicy.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    IDGate g = {0};
    assert(!IDGateBegin(&g) && !IDGateForward(&g));
    assert(IDGateCapture(&g) && !IDGateCapture(&g));
    assert(IDGateBegin(&g) && !IDGateBegin(&g) && g.attempts == 1);
    assert(!IDGateForward(&g) && !IDGateRequestLaunch(&g) && !g.launch_requested);
    assert(IDGateFailedAttempt(&g) && !IDGateFailedAttempt(&g));
    assert(!IDGateSucceeded(&g) && !IDGateForward(&g));
    assert(IDGateBegin(&g) && g.attempts == 2);
    assert(IDGateSucceeded(&g) && !IDGateSucceeded(&g));
    // Ready must remain on the server menu until an intentional user action.
    assert(!IDGateForwardVisible(&g, 0) && g.phase == IDGateReady && !g.forwarded);
    assert(IDGateRequestLaunch(&g) && !IDGateRequestLaunch(&g));
    assert(!IDGateForwardVisible(&g, 0) && !g.launch_prepared);
    // A failed health recheck returns to Retry without opening the game.
    assert(IDGateLaunchFailed(&g) && !IDGateForward(&g));
    assert(IDGateBegin(&g) && g.attempts == 3 && !g.launch_requested);
    assert(IDGateSucceeded(&g) && IDGateRequestLaunch(&g));
    assert(IDGatePreparedLaunch(&g) && !IDGatePreparedLaunch(&g));
    assert(!IDGateForwardVisible(&g, 1) && g.phase == IDGateReady && !g.forwarded);
    assert(IDGateForwardVisible(&g, 0) && g.phase == IDGateRunning);
    for (unsigned i = 0; i < 10000; ++i)
        assert(!IDGateForward(&g) && !IDGateBegin(&g) && !IDGateCapture(&g));
    puts("PASS: server menu, explicit start, retry and exactly-once forwarding policy");
    return 0;
}
