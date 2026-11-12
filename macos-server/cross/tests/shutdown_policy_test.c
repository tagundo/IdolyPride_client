#define _POSIX_C_SOURCE 200809L
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "../shutdown_policy.h"

static int checks;
#define CHECK(value) do { ++checks; if (!(value)) { fprintf(stderr, "shutdown policy failed at %d\n", __LINE__); return 1; } } while (0)

static long short_write(int fd, const void *bytes, unsigned long count) {
    (void)fd; (void)bytes; return count > 1 ? (long)count - 1 : 0;
}
static double monotonic(void) {
    struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec + now.tv_nsec / 1000000000.0;
}

int main(void) {
    IDShutdown stopped = {0};
    CHECK(id_shutdown_request(&stopped, 100, 0, 0) == ID_TERMINATE_NOW);
    CHECK(stopped.observedExit && !stopped.requested);

    IDShutdown normal = {0};
    CHECK(id_shutdown_request(&normal, 100, 42, 1) == ID_TERMINATE_CANCEL);
    CHECK(id_shutdown_step(&normal, 100.2, 1, 42) == ID_SHUTDOWN_WAIT);
    CHECK(id_shutdown_step(&normal, 100.5, 0, 42) == ID_SHUTDOWN_FINISH);
    CHECK(normal.observedExit && !normal.termSent && !normal.killSent);
    CHECK(id_shutdown_request(&normal, 100.5, 42, 0) == ID_TERMINATE_NOW);

    IDShutdown stuck = {0};
    CHECK(id_shutdown_request(&stuck, 100, 42, 1) == ID_TERMINATE_CANCEL);
    /* Repeated menu/Cmd-Q/window-close attempts must not restart the grace period. */
    CHECK(id_shutdown_request(&stuck, 107, 42, 1) == ID_TERMINATE_CANCEL);
    CHECK(stuck.requestedAt == 100);
    CHECK(id_shutdown_step(&stuck, 107.99, 1, 42) == ID_SHUTDOWN_WAIT);
    CHECK(id_shutdown_step(&stuck, 108, 1, 42) == ID_SHUTDOWN_TERM);
    CHECK(id_shutdown_step(&stuck, 108.2, 1, 42) == ID_SHUTDOWN_WAIT);
    CHECK(id_shutdown_step(&stuck, 109.99, 1, 42) == ID_SHUTDOWN_WAIT);
    CHECK(id_shutdown_step(&stuck, 110, 1, 42) == ID_SHUTDOWN_KILL);
    CHECK(id_shutdown_step(&stuck, 110.2, 1, 42) == ID_SHUTDOWN_WAIT);
    CHECK(id_shutdown_step(&stuck, 111.99, 1, 42) == ID_SHUTDOWN_WAIT);
    CHECK(id_shutdown_step(&stuck, 112, 1, 42) == ID_SHUTDOWN_FINISH);
    CHECK(stuck.timedOut && !stuck.observedExit && stuck.termSent && stuck.killSent);
    CHECK(id_shutdown_request(&stuck, 112, 42, 1) == ID_TERMINATE_NOW);
    CHECK(id_shutdown_step(&stuck, 113, 1, 42) == ID_SHUTDOWN_WAIT);

    IDShutdown termExit = {0};
    CHECK(id_shutdown_request(&termExit, 0, 81, 1) == ID_TERMINATE_CANCEL);
    CHECK(id_shutdown_step(&termExit, 8, 1, 81) == ID_SHUTDOWN_TERM);
    CHECK(id_shutdown_step(&termExit, 8.2, 0, 81) == ID_SHUTDOWN_FINISH);
    CHECK(termExit.observedExit && !termExit.killSent && !termExit.timedOut);

    IDShutdown killExit = {0};
    CHECK(id_shutdown_request(&killExit, 0, 81, 1) == ID_TERMINATE_CANCEL);
    /* A delayed event loop escalates directly, without issuing two signals together. */
    CHECK(id_shutdown_step(&killExit, 10.4, 1, 81) == ID_SHUTDOWN_KILL);
    CHECK(id_shutdown_step(&killExit, 10.6, 0, 81) == ID_SHUTDOWN_FINISH);
    CHECK(killExit.observedExit && !killExit.timedOut && !killExit.termSent);

    IDShutdown replaced = {0};
    CHECK(id_shutdown_request(&replaced, 0, 81, 1) == ID_TERMINATE_CANCEL);
    CHECK(id_shutdown_step(&replaced, 8, 1, 99) == ID_SHUTDOWN_FINISH);
    CHECK(replaced.ownershipLost && !replaced.termSent && !replaced.killSent);
    IDShutdown invalid = {0};
    CHECK(id_shutdown_request(&invalid, 0, -1, 1) == ID_TERMINATE_CANCEL);
    CHECK(id_shutdown_step(&invalid, 10, 1, -1) == ID_SHUTDOWN_FINISH);
    CHECK(invalid.ownershipLost && !invalid.killSent);

    int pipeFD[2]; CHECK(pipe(pipeFD) == 0);
    CHECK(id_control_nonblocking(pipeFD[1], F_GETFL, F_SETFL, O_NONBLOCK, fcntl));
    CHECK((fcntl(pipeFD[1], F_GETFL) & O_NONBLOCK) != 0);
    const char command[] = "{\"action\":\"quit\"}\n";
    CHECK(id_control_send(pipeFD[1], command, sizeof command - 1, write) == 1);
    char received[512];
    CHECK(read(pipeFD[0], received, sizeof received) == (long)sizeof command - 1);
    CHECK(memcmp(received, command, sizeof command - 1) == 0);

    char block[512]; memset(block, 'x', sizeof block);
    int filled = 0;
    while (filled < 1048576 && id_control_send(pipeFD[1], block, sizeof block, write) == 1) filled += sizeof block;
    CHECK(filled > 0 && filled < 1048576);
    double started = monotonic();
    for (int attempt = 0; attempt < 100; ++attempt)
        CHECK(id_control_send(pipeFD[1], block, sizeof block, write) == 0);
    CHECK(monotonic() - started < 0.5);
    CHECK(id_control_send(pipeFD[1], block, 513, write) == 0);
    CHECK(id_control_send(pipeFD[1], block, 512, short_write) == -1);
    /* Closing stdin remains an EOF shutdown request when a full pipe rejected quit. */
    CHECK(close(pipeFD[1]) == 0);
    int drained = 0; long count;
    while ((count = read(pipeFD[0], received, sizeof received)) > 0) drained += (int)count;
    CHECK(count == 0 && drained == filled);
    close(pipeFD[0]);

    CHECK(!id_control_nonblocking(-1, F_GETFL, F_SETFL, O_NONBLOCK, fcntl));
    CHECK(id_control_send(-1, command, sizeof command - 1, write) == 0);
    CHECK(id_control_send(1, command, 0, write) == 0);
    CHECK(pipe(pipeFD) == 0);
    close(pipeFD[0]); signal(SIGPIPE, SIG_IGN);
    CHECK(id_control_send(pipeFD[1], command, sizeof command - 1, write) == 0);
    close(pipeFD[1]);
    printf("PASS: %d shutdown escalation and real nonblocking pipe checks\n", checks);
    return 0;
}
