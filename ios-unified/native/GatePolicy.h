#ifndef IDOLY_EMBEDDED_GATE_POLICY_H
#define IDOLY_EMBEDDED_GATE_POLICY_H

// All mutations happen on the main thread. Worker results are dispatched there.
typedef enum { IDGateIdle, IDGateStarting, IDGateReady, IDGateFailed, IDGateRunning } IDGatePhase;
typedef struct {
    IDGatePhase phase;
    unsigned captured, forwarded, attempts, launch_requested, launch_prepared;
} IDGate;
// Failed startup may still have a live interpreter and durable diagnostics.
// Starting remains immediate so periodic status calls cannot queue behind it.
static inline int IDGateReadFailedHostStatus(const IDGate *g, int python_ready, int worker_ready) {
    return g && g->phase == IDGateFailed && python_ready && worker_ready;
}
static inline int IDGateCapture(IDGate *g) {
    if (g->captured || g->forwarded) return 0;
    g->captured = 1; return 1;
}
static inline int IDGateBegin(IDGate *g) {
    // The server can start before Unity reaches its captured initialization.
    if (g->forwarded || (g->phase != IDGateIdle && g->phase != IDGateFailed)) return 0;
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
static inline int IDGateCanForward(const IDGate *g) {
    return g->captured && !g->forwarded && g->phase == IDGateReady
        && g->launch_requested && g->launch_prepared;
}
static inline int IDGateForward(IDGate *g) {
    if (!IDGateCanForward(g)) return 0;
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
    g->launch_requested = 0; g->launch_prepared = 0; return 1;
}
static inline int IDGateServerUnavailable(IDGate *g) {
    if (g->phase != IDGateReady || g->forwarded) return 0;
    g->launch_requested = 0; g->launch_prepared = 0; g->phase = IDGateFailed; return 1;
}
static inline int IDGateForwardVisible(IDGate *g, int background) {
    return !background && IDGateForward(g);
}
#endif
