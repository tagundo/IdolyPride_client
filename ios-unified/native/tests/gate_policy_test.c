#include "../GatePolicy.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    assert(!IDGateReadFailedHostStatus(NULL, 1, 1));
    for (int phase = IDGateIdle; phase <= IDGateRunning; ++phase)
        for (int python = 0; python <= 1; ++python)
            for (int worker = 0; worker <= 1; ++worker) {
                IDGate observed = {.phase = (IDGatePhase)phase};
                assert(IDGateReadFailedHostStatus(&observed, python, worker)
                    == (phase == IDGateFailed && python && worker));
            }
    IDGate g = {0};
    assert(!IDGateForward(&g));
    IDGate early = {0};
    assert(IDGateBegin(&early) && !early.captured && early.attempts == 1);
    assert(IDGateSucceeded(&early) && !IDGateRequestLaunch(&early));
    assert(IDGateCapture(&early) && !IDGateBegin(&early));
    assert(IDGateRequestLaunch(&early) && IDGatePreparedLaunch(&early));
    assert(IDGateForwardVisible(&early, 0));
    assert(IDGateCapture(&g) && !IDGateCapture(&g));
    assert(IDGateBegin(&g) && !IDGateBegin(&g) && g.attempts == 1);
    assert(!IDGateForward(&g) && !IDGateRequestLaunch(&g) && !g.launch_requested);
    assert(IDGateFailedAttempt(&g) && !IDGateFailedAttempt(&g));
    assert(!IDGateSucceeded(&g) && !IDGateForward(&g));
    assert(IDGateBegin(&g) && g.attempts == 2);
    assert(IDGateSucceeded(&g) && !IDGateSucceeded(&g));
    // Ready must remain on the server menu until an intentional user action.
    assert(!IDGateForwardVisible(&g, 0) && g.phase == IDGateReady && !g.forwarded);
    IDGate unavailable = g;
    assert(IDGateServerUnavailable(&unavailable) && unavailable.phase == IDGateFailed);
    assert(IDGateBegin(&unavailable) && IDGateSucceeded(&unavailable));
    assert(IDGateRequestLaunch(&g) && !IDGateRequestLaunch(&g));
    assert(!IDGateForwardVisible(&g, 0) && !g.launch_prepared);
    // A failed health recheck returns to Retry without opening the game.
    assert(IDGateLaunchFailed(&g) && !IDGateForward(&g));
    assert(g.phase == IDGateReady && !IDGateBegin(&g) && g.attempts == 2 && !g.launch_requested);
    assert(IDGateRequestLaunch(&g));
    assert(IDGatePreparedLaunch(&g) && !IDGatePreparedLaunch(&g));
    assert(!IDGateForwardVisible(&g, 1) && g.phase == IDGateReady && !g.forwarded);
    assert(IDGateForwardVisible(&g, 0) && g.phase == IDGateRunning);
    for (unsigned i = 0; i < 10000; ++i)
        assert(!IDGateForward(&g) && !IDGateBegin(&g) && !IDGateCapture(&g));
    puts("PASS: server menu, explicit start, retry and exactly-once forwarding policy");
    return 0;
}
