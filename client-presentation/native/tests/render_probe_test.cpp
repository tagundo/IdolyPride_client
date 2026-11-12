#include <cassert>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include "render_probe_fragment.hpp"

static void emit(const char *name, const RenderProbeTracker &tracker, int64_t now) {
    char output[512];
    RenderProbeTracker::write_json(tracker.snapshot(), now, output, sizeof output);
    std::cout << name << '\t' << output << '\n';
}

int main() {
    RenderProbeTracker tracker;
    emit("waiting", tracker, 1000);
    assert(!tracker.begin_sample(-1));
    assert(tracker.begin_sample(1000));
    tracker.complete_sample(1000, 2, 21, 321);
    emit("first", tracker, 1250);
    assert(!tracker.begin_sample(1000));
    assert(!tracker.begin_sample(2999));
    assert(tracker.begin_sample(3000));
    tracker.complete_sample(3000, 0, 11, 321);
    emit("direct", tracker, 5000);
    assert(!tracker.begin_sample(2999)); // A clock regression cannot resample.
    emit("age_unknown", tracker, -1);
    emit("clock_regressed", tracker, 2999);

    tracker.complete_sample(6000, 6, 21, 321);
    emit("unknown_mode", tracker, 6000);
    tracker.complete_sample(8000, 2, 256, 321);
    emit("unknown_api", tracker, 8000);
    tracker.complete_sample(10000, 2, 21, 0);
    emit("missing_tid", tracker, 10000);
    tracker.complete_sample(12000, 2, 21, int64_t{INT32_MAX} + 1);
    emit("invalid_tid", tracker, 12000);
    tracker.complete_sample(14000, 5, 255, INT32_MAX);
    emit("raw_api", tracker, 14000);
    tracker.complete_sample(0, 1, 8, 321);
    emit("maximum_age", tracker, INT64_MAX);
    assert(RenderProbeTracker::next_observation_count(0) == 1);
    assert(RenderProbeTracker::next_observation_count(INT64_MAX - 1) == INT64_MAX);
    assert(RenderProbeTracker::next_observation_count(INT64_MAX) == INT64_MAX);

    for (int mode = 0; mode <= 5; ++mode) {
        RenderProbeTracker each;
        each.complete_sample(0, mode, 21, 321);
        char name[32]; std::snprintf(name, sizeof name, "mode_%d", mode);
        emit(name, each, 0);
    }
    tracker.initialization_failed();
    emit("init_failed", tracker, 20000);
}
