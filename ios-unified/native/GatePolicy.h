#ifndef IDOLY_EMBEDDED_GATE_POLICY_H
#define IDOLY_EMBEDDED_GATE_POLICY_H

// All mutations happen on the main thread. Worker results are dispatched there.
typedef enum { IDGateIdle, IDGateStarting, IDGateReady, IDGateFailed, IDGateRunning } IDGatePhase;
typedef struct { IDGatePhase phase; unsigned captured, forwarded, attempts; } IDGate;
static inline int IDGateCapture(IDGate *g) {
    if (g->captured || g->forwarded) return 0;
    g->captured = 1; return 1;
}
static inline int IDGateBegin(IDGate *g) {
    if (!g->captured || g->forwarded || (g->phase != IDGateIdle && g->phase != IDGateFailed)) return 0;
    g->phase = IDGateStarting; ++g->attempts; return 1;
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
    if (!g->captured || g->forwarded || g->phase != IDGateReady) return 0;
    g->forwarded = 1; g->phase = IDGateRunning; return 1;
}
static inline int IDGateForwardVisible(IDGate *g, int background) {
    return !background && IDGateForward(g);
}
#endif
