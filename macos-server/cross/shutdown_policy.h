#ifndef IDOLY_SHUTDOWN_POLICY_H
#define IDOLY_SHUTDOWN_POLICY_H

/* No Cocoa calls or sleeping here: the ordinary main run loop drives cleanup.
   NSTerminateLater would switch to a modal mode and starve the default timer. */
enum IDShutdownAction { ID_SHUTDOWN_WAIT, ID_SHUTDOWN_TERM, ID_SHUTDOWN_KILL, ID_SHUTDOWN_FINISH };
enum IDTerminateReply { ID_TERMINATE_CANCEL = 0, ID_TERMINATE_NOW = 1 };
typedef struct {
    int requested, ready, ownedPID, termSent, killSent, observedExit, timedOut, ownershipLost;
    double requestedAt;
} IDShutdown;

static inline enum IDTerminateReply id_shutdown_request(IDShutdown *state, double now, int pid, int alive) {
    if (state->ready) return ID_TERMINATE_NOW;
    if (!alive) { state->ready = state->observedExit = 1; return ID_TERMINATE_NOW; }
    if (!state->requested) {
        state->requested = 1; state->requestedAt = now; state->ownedPID = pid;
    }
    return ID_TERMINATE_CANCEL;
}

static inline enum IDShutdownAction id_shutdown_step(IDShutdown *state, double now, int alive, int pid) {
    if (!state->requested || state->ready) return ID_SHUTDOWN_WAIT;
    if (!alive) { state->ready = state->observedExit = 1; return ID_SHUTDOWN_FINISH; }
    /* A PID learned from anything other than our one NSTask is never a target. */
    if (state->ownedPID <= 0 || pid != state->ownedPID) {
        state->ready = state->ownershipLost = 1; return ID_SHUTDOWN_FINISH;
    }
    double elapsed = now - state->requestedAt;
    /* Keep the original 8s grace and 10s KILL deadline. The extra 2s only
       observes NSTask's exit/reap asynchronously; it never blocks the UI. */
    if (state->killSent && elapsed >= 12) {
        state->ready = state->timedOut = 1; return ID_SHUTDOWN_FINISH;
    }
    if (elapsed >= 10 && !state->killSent) { state->killSent = 1; return ID_SHUTDOWN_KILL; }
    if (elapsed >= 8 && !state->termSent) { state->termSent = 1; return ID_SHUTDOWN_TERM; }
    return ID_SHUTDOWN_WAIT;
}

/* Darwin constants are supplied by the UI; the host regression uses its own
   fcntl constants against real pipes. Preserve any existing descriptor flags. */
static inline int id_control_nonblocking(int fd, int getFlags, int setFlags, int nonblocking,
        int (*control)(int, int, ...)) {
    if (fd < 0) return 0;
    int flags = control(fd, getFlags);
    return flags >= 0 && control(fd, setFlags, flags | nonblocking) == 0;
}

/* Commands are below POSIX's minimum PIPE_BUF (512): an O_NONBLOCK pipe write
   completes atomically or returns immediately. A short write poisons framing. */
static inline int id_control_send(int fd, const char *bytes, unsigned long count,
        long (*sendBytes)(int, const void *, unsigned long)) {
    if (fd < 0 || !bytes || !count || count > 512) return 0;
    long sent = sendBytes(fd, bytes, count);
    return sent == (long)count ? 1 : sent > 0 ? -1 : 0;
}

#endif
