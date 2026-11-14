#include "../GatePolicy.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    IDGate g = {0};
    assert(!IDGateBegin(&g) && !IDGateForward(&g));
    assert(IDGateCapture(&g) && !IDGateCapture(&g));
    assert(IDGateBegin(&g) && !IDGateBegin(&g) && g.attempts == 1);
    assert(!IDGateForward(&g));
    assert(IDGateFailedAttempt(&g) && !IDGateFailedAttempt(&g));
    assert(!IDGateSucceeded(&g) && !IDGateForward(&g));
    assert(IDGateBegin(&g) && g.attempts == 2);
    assert(IDGateSucceeded(&g) && !IDGateSucceeded(&g));
    assert(!IDGateForwardVisible(&g, 1) && g.phase == IDGateReady && !g.forwarded);
    assert(IDGateForwardVisible(&g, 0) && g.phase == IDGateRunning);
    for (unsigned i = 0; i < 10000; ++i)
        assert(!IDGateForward(&g) && !IDGateBegin(&g) && !IDGateCapture(&g));
    puts("PASS: startup deferral, retry, and exactly-once forwarding policy");
    return 0;
}
