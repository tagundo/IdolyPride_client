#ifndef IDOLY_EMBEDDED_GATE_POLICY_H
#define IDOLY_EMBEDDED_GATE_POLICY_H

// All mutations happen on the main thread. Worker results are dispatched there.
typedef enum { IDGateIdle, IDGateStarting, IDGateReady, IDGateFailed, IDGateRunning } IDGatePhase;
typedef struct {
    IDGatePhase phase;
    unsigned captured, forwarded, attempts, launch_requested, launch_prepared;
} IDGate;
static inline int IDGateCapture(IDGate *g) {
    if (g->captured || g->forwarded) return 0;
    g->captured = 1; return 1;
}
static inline int IDGateBegin(IDGate *g) {
    if (!g->captured || g->forwarded || (g->phase != IDGateIdle && g->phase != IDGateFailed)) return 0;
    g->phase = IDGateStarting; g->launch_requested = 0; g->launch_prepared = 0;
    ++g->attempts; return 1;
}
static inline int IDGateSucceeded(IDGate *g) {
    if (g->phase != IDGateStarting) return 0;
    g->phase = IDGateReady; return 1;
}
static inline int IDGateFailedAttempt(IDGate *g) {
    if (g->phase != IDGateStarting) return 0;
    g->phase = IDGateFailed; return 1;
}
static inline int IDGateForward(IDGate *g) {
    if (!g->captured || g->forwarded || g->phase != IDGateReady
            || !g->launch_requested || !g->launch_prepared) return 0;
    g->forwarded = 1; g->phase = IDGateRunning; return 1;
}
static inline int IDGateRequestLaunch(IDGate *g) {
    if (!g->captured || g->forwarded || g->phase != IDGateReady || g->launch_requested) return 0;
    g->launch_requested = 1; return 1;
}
static inline int IDGatePreparedLaunch(IDGate *g) {
    if (g->phase != IDGateReady || !g->launch_requested || g->launch_prepared || g->forwarded) return 0;
    g->launch_prepared = 1; return 1;
}
static inline int IDGateLaunchFailed(IDGate *g) {
    if (g->phase != IDGateReady || !g->launch_requested || g->forwarded) return 0;
    g->launch_requested = 0; g->launch_prepared = 0; g->phase = IDGateFailed; return 1;
}
static inline int IDGateForwardVisible(IDGate *g, int background) {
    return !background && IDGateForward(g);
}
#endif
