#ifndef IDOLY_UNITY_HOST_POLICY_H
#define IDOLY_UNITY_HOST_POLICY_H
#include <stdbool.h>
#include <stddef.h>

enum { IDUnityHostPendingLimit = 8 };
typedef struct {
    bool installed, captured, host_ready, launching, started, failed;
    unsigned application_main_calls, runtime_start_calls, queued_events;
} IDUnityHostPolicy;

static inline bool IDUnityHostMarkInstalled(IDUnityHostPolicy *s) {
    if (!s || s->installed || s->failed) return false;
    s->installed = true;
    return true;
}
static inline bool IDUnityHostCaptureMain(IDUnityHostPolicy *s) {
    if (!s || !s->installed || s->captured || s->failed) return false;
    s->captured = true;
    return true;
}
static inline bool IDUnityHostEnterApplicationMain(IDUnityHostPolicy *s) {
    if (!s || !s->captured || s->application_main_calls || s->failed) return false;
    s->application_main_calls = 1;
    return true;
}
static inline bool IDUnityHostMarkReady(IDUnityHostPolicy *s) {
    if (!s || !s->captured || s->host_ready || s->failed) return false;
    s->host_ready = true;
    return true;
}
static inline bool IDUnityHostBeginRuntime(IDUnityHostPolicy *s, bool verified_root,
                                          bool pre_runtime) {
    if (!s || !s->host_ready || s->launching || s->runtime_start_calls || s->failed
            || !verified_root || !pre_runtime) return false;
    s->launching = true;
    s->runtime_start_calls = 1;
    return true;
}
static inline bool IDUnityHostFinishRuntime(IDUnityHostPolicy *s, bool verified_root) {
    if (!s || !s->launching || s->runtime_start_calls != 1) return false;
    s->launching = false;
    s->started = verified_root;
    s->failed = !verified_root;
    return verified_root;
}
static inline bool IDUnityHostMayForward(const IDUnityHostPolicy *s) {
    return s && s->started && !s->launching && !s->failed;
}
static inline bool IDUnityHostQueueEvent(IDUnityHostPolicy *s) {
    if (!s || s->started || s->failed || s->queued_events >= IDUnityHostPendingLimit) return false;
    ++s->queued_events;
    return true;
}
static inline void IDUnityHostDrainEvents(IDUnityHostPolicy *s) {
    if (s && IDUnityHostMayForward(s)) s->queued_events = 0;
}
#endif
