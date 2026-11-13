#include "../wardrobe_timing.hpp"
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <thread>

using namespace idoly::presentation::wardrobe_timing;
static std::atomic<int64_t> instant{0};
static int clock_calls=0;
static int64_t clock_now() { ++clock_calls; return instant.load(); }
struct Token { void *source; };
struct Task { void *source; uint16_t token; };
static void emit(const Snapshot &value) {
    char json[1024]; assert(Tracker::json(value,json,sizeof json)); std::puts(json);
    char tiny[8]; assert(!Tracker::json(value,tiny,sizeof tiny));
}
int main() {
    Tracker tracker; tracker.configure(clock_now);
    assert(tracker.ready()); emit(tracker.snapshot(0));
    instant=100;
    void *owner=reinterpret_cast<void *>(0x1234), *method=reinterpret_cast<void *>(0x5678);
    Token cancellation{reinterpret_cast<void *>(0x9911)};
    const Task returned=tracker.invoke_back(Room::CharacterCostume,
        [&](void *self,Token token,void *metadata) -> Task {
            assert(self==owner && token.source==cancellation.source && metadata==method);
            bool observed=false;
            // A JNI-style reader can obtain state while an original is running.
            // Holding the state mutex across the original would deadlock here.
            std::thread observer([&] { auto s=tracker.snapshot(101);
                observed=s.active && s.in_original && s.phase==Stage::Back && s.elapsed_ms==1; });
            observer.join(); assert(observed);
            instant=150;
            Task nested=tracker.invoke(Stage::Preclose,[&] { instant=200; return Task{owner,73}; });
            assert(nested.source==owner && nested.token==73);
            auto s=tracker.snapshot(200); assert(s.in_original && s.phase==Stage::Back);
            tracker.invoke(Stage::Unload,[&] {
                instant=37000;
                auto slow=tracker.snapshot(37000);
                assert(slow.in_original && slow.phase==Stage::Unload && slow.elapsed_ms==36900);
            });
            instant=37100; return Task{method,64999};
        },owner,cancellation,method);
    assert(returned.source==method && returned.token==64999 && clock_calls==6);
    auto first=tracker.snapshot(37100);
    assert(first.active && !first.in_original && first.elapsed_ms==37000);
    assert(first.last_sync_ms==37000 && first.max_sync_ms==37000 && first.max_stage==Stage::Back);
    assert(first.span_count==3 && first.spans[0].stage==Stage::Preclose && first.spans[0].duration_ms==50);
    assert(first.spans[1].stage==Stage::Unload && first.spans[1].duration_ms==36800);
    emit(first);
    tracker.complete(); auto completed=tracker.snapshot(99999);
    assert(!completed.active && completed.phase==Stage::Completed && completed.elapsed_ms==37000);
    emit(completed);

    instant=40000;
    tracker.invoke_back(Room::FittingRoom,[&] {
        auto s=tracker.snapshot(40000); assert(s.room==Room::FittingRoom && !s.span_count && !s.max_sync_ms);
        for (int i=0;i<12;++i) tracker.invoke(Stage::Hide,[&] { ++instant; });
    });
    auto bounded=tracker.snapshot(40012);
    assert(bounded.span_count==2 && bounded.spans[0].stage==Stage::Hide && bounded.spans[1].stage==Stage::Back);
    assert(bounded.spans[0].duration_ms==1 && bounded.spans[1].duration_ms==12);
    emit(bounded);
    assert(!tracker.snapshot(40000+Tracker::window_ms+1).active);
    instant=40000+Tracker::window_ms+1;
    const int before=clock_calls;
    int direct=tracker.invoke(Stage::GC,[] { return 19; });
    assert(direct==19 && clock_calls==before+1); // inactive trace still forwards the original
    assert(tracker.snapshot(instant).sequence==bounded.sequence);

    instant=200000;
    const char *original_error="same original exception";
    try {
        tracker.invoke_back(Room::FittingRoom,[&] { instant=200005; throw original_error; });
        assert(false);
    } catch (const char *actual) { assert(actual==original_error); }
    auto failed=tracker.snapshot(200005); assert(!failed.in_original && failed.last_sync_ms==5);
    instant=-1;
    tracker.invoke_back(Room::CharacterCostume,[&] { assert(!tracker.snapshot(-1).active); });
    instant=200010;
    assert(tracker.snapshot(200010).room==Room::FittingRoom); // invalid clock did not reset state
    Tracker unavailable;
    assert(unavailable.invoke_back(Room::CharacterCostume,[] { return 31; })==31);
    assert(unavailable.snapshot(0).sequence==0);
    instant=300000;
    tracker.invoke_back(Room::CharacterCostume,[&] {
        tracker.invoke(Stage::Preclose,[&] { instant=337000; });
        for (int i=0;i<100;++i) tracker.invoke(Stage::Hide,[&] { ++instant; });
    });
    auto retained=tracker.snapshot(337100);
    assert(retained.span_count==3 && retained.spans[0].stage==Stage::Preclose);
    assert(retained.spans[0].duration_ms==37000 && retained.spans[1].stage==Stage::Hide);
    assert(retained.spans[1].duration_ms==1 && retained.spans[2].stage==Stage::Back);
    assert(retained.spans[2].duration_ms==37100);
    Tracker ui_close; ui_close.configure(clock_now); instant=500000;
    auto direct_close=ui_close.invoke_close(Room::CharacterCostume,Stage::Preclose,
        [&](void *self,Token token,void *info) -> Task {
            assert(self==owner && token.source==cancellation.source && info==method);
            instant=537000; auto s=ui_close.snapshot(537000);
            assert(s.room==Room::CharacterCostume && s.phase==Stage::Preclose);
            assert(s.active && s.in_original && s.elapsed_ms==37000);
            return Task{method,12345};
        },owner,cancellation,method);
    assert(direct_close.source==method && direct_close.token==12345);
    auto direct_snapshot=ui_close.snapshot(537000);
    assert(direct_snapshot.span_count==1 && direct_snapshot.spans[0].stage==Stage::Preclose);
    assert(direct_snapshot.spans[0].duration_ms==37000 && direct_snapshot.max_stage==Stage::Preclose);
    // A later exact close boundary belongs to the current observation even if
    // RecursiveBack was bypassed and its original call has already returned.
    instant=537005;
    ui_close.invoke_close(Room::FittingRoom,Stage::Hide,[&] { instant=537010; });
    auto unchanged_epoch=ui_close.snapshot(537010);
    assert(unchanged_epoch.room==Room::CharacterCostume && unchanged_epoch.elapsed_ms==37010);
    assert(unchanged_epoch.max_stage==Stage::Preclose && unchanged_epoch.max_sync_ms==37000);
    assert(unchanged_epoch.span_count==2 && unchanged_epoch.spans[0].duration_ms==37000);
    emit(direct_snapshot);
    Snapshot largest;
    largest.room=Room::CharacterCostume; largest.phase=Stage::SelectionShow;
    largest.max_stage=Stage::SelectionShow; largest.elapsed_ms=INT64_MAX;
    largest.last_sync_ms=largest.max_sync_ms=largest.sequence=INT64_MAX;
    largest.span_count=8;
    for (auto &span:largest.spans) span={Stage::SelectionShow,INT64_MAX};
    char json[1024]; assert(Tracker::json(largest,json,sizeof json));
}
