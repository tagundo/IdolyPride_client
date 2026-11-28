#include "../UnityHostPolicy.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    IDUnityHostPolicy s = {0};
    assert(!IDUnityHostMarkInstalled(NULL));
    assert(!IDUnityHostCaptureMain(&s));
    assert(!IDUnityHostEnterApplicationMain(&s));
    assert(!IDUnityHostMarkReady(&s));
    assert(!IDUnityHostBeginRuntime(&s, true, true));
    assert(!IDUnityHostMayForward(&s));
    assert(IDUnityHostMarkInstalled(&s));
    assert(!IDUnityHostMarkInstalled(&s));
    assert(IDUnityHostCaptureMain(&s));
    assert(!IDUnityHostCaptureMain(&s));
    assert(IDUnityHostEnterApplicationMain(&s));
    assert(!IDUnityHostEnterApplicationMain(&s));
    assert(IDUnityHostMarkReady(&s));
    assert(!IDUnityHostMarkReady(&s));
    assert(!IDUnityHostBeginRuntime(&s, false, true));
    assert(!IDUnityHostBeginRuntime(&s, true, false));
    assert(s.runtime_start_calls == 0);
    for (unsigned i = 0; i < IDUnityHostPendingLimit; ++i)
        assert(IDUnityHostQueueEvent(&s));
    assert(!IDUnityHostQueueEvent(&s));
    IDUnityHostDrainEvents(&s);
    assert(s.queued_events == IDUnityHostPendingLimit);
    assert(IDUnityHostBeginRuntime(&s, true, true));
    assert(s.runtime_start_calls == 1 && !IDUnityHostMayForward(&s));
    assert(!IDUnityHostBeginRuntime(&s, true, true));
    assert(IDUnityHostFinishRuntime(&s, true));
    assert(IDUnityHostMayForward(&s));
    IDUnityHostDrainEvents(&s);
    assert(s.queued_events == 0 && !IDUnityHostQueueEvent(&s));
    assert(!IDUnityHostFinishRuntime(&s, true));
    assert(!IDUnityHostBeginRuntime(&s, true, true));
    IDUnityHostPolicy bad = {0};
    assert(IDUnityHostMarkInstalled(&bad) && IDUnityHostCaptureMain(&bad)
        && IDUnityHostEnterApplicationMain(&bad) && IDUnityHostMarkReady(&bad));
    assert(IDUnityHostBeginRuntime(&bad, true, true));
    assert(!IDUnityHostFinishRuntime(&bad, false));
    assert(bad.failed && !bad.started && !bad.launching);
    assert(!IDUnityHostMayForward(&bad) && !IDUnityHostQueueEvent(&bad)
        && !IDUnityHostBeginRuntime(&bad, true, true));
    puts("PASS: Unity host policy; one cold runtime, bounded events, fail-closed routing");
    return 0;
}
