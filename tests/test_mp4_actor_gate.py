"""Compile the real worker gate against synthetic original callback boundaries.

These exercise ownership, ABI forwarding and concurrent grants. They do not
execute Unity or replace the separate pinned-original callback/fence audits.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "mp4_actor_state.hpp"
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
using namespace idoly_mp4_actor;
struct Job { alignas(16) unsigned char bytes[0x168]{}; };
void put(Job& job, size_t at, uintptr_t value) {
    std::memcpy(job.bytes + at, &value, sizeof value);
}
OwnershipKey key(uintptr_t seed) {
    return {{seed, seed + 0x100, seed + 0x200, seed + 0x300}};
}
void apply(Job& job, const OwnershipKey& value) {
    for (size_t i = 0; i < 4; ++i) put(job, list_header_offsets[i], value.list_headers[i]);
}
std::atomic<int> calls{0};
const void* expected_stream = reinterpret_cast<void*>(0x1234);
const void* expected_method = reinterpret_cast<void*>(0x5678);
void* expected_ranges = reinterpret_cast<void*>(0x9abc);
int32_t expected_index = -31;
intptr_t expected_tag = 1;
void managed(void*, const void* stream, const void* method) {
    assert(stream == expected_stream && method == expected_method);
    calls.fetch_add(1);
}
void burst(void*, const void* stream, intptr_t tag, void* ranges, int32_t index) {
    assert(stream == expected_stream && tag == expected_tag);
    assert(ranges == expected_ranges && index == expected_index);
    calls.fetch_add(1);
}
void invoke(WorkerGate& gate, Job* job, bool is_burst=false) {
    if (is_burst) gate.invoke_burst(burst, job, expected_stream, expected_tag,
        expected_ranges, expected_index);
    else gate.invoke_managed(managed, job, expected_stream, expected_method);
}
void throws(void*, const void*, const void*) { throw std::runtime_error("original job"); }
struct Blocker {
    std::mutex mutex;
    std::condition_variable cv;
    bool entered = false, resume = false;
    void wait_for_entry() {
        std::unique_lock<std::mutex> lock(mutex);
        assert(cv.wait_for(lock, std::chrono::seconds(3), [&]{ return entered; }));
    }
    void release() {
        std::lock_guard<std::mutex> lock(mutex); resume=true; cv.notify_all();
    }
};
Blocker* blocker = nullptr;
void blocked(void*, const void* stream, const void* method) {
    assert(stream == expected_stream && method == expected_method && blocker);
    std::unique_lock<std::mutex> lock(blocker->mutex);
    blocker->entered = true; blocker->cv.notify_all();
    assert(blocker->cv.wait_for(lock, std::chrono::seconds(3), []{ return blocker->resume; }));
    calls.fetch_add(1);
}
int main(int argc,char** argv) {
    assert(argc==2); const std::string s=argv[1];
    WorkerGate gate; Job a,b; auto ka=key(0x10000),kb=key(0x20000);apply(a,ka);apply(b,kb);
    if(s=="no_owner_managed"||s=="no_owner_burst") {
        invoke(gate,&a,s=="no_owner_burst");assert(calls==1&&gate.stats().owned_calls==0);return 0;
    }
    if(s=="invalid_publish") {
        assert(gate.publish(&ka,1,1,false)==GateResult::waiting);
        assert(gate.publish(&ka,1,0,true)==GateResult::invalid);
        assert(gate.publish(nullptr,1,1,true)==GateResult::invalid);
        assert(gate.publish(&ka,0,1,true)==GateResult::invalid);
        assert(gate.publish(&ka,max_owned_jobs+1,1,true)==GateResult::invalid);
        OwnershipKey zero{};assert(gate.publish(&zero,1,1,true)==GateResult::invalid);
        OwnershipKey duplicate[]={ka,ka};assert(gate.publish(duplicate,2,1,true)==GateResult::invalid);
        assert(gate.publish(&ka,1,1,true)==GateResult::ok);
        assert(gate.retire(1,true)==GateResult::ok);return 0;
    }
    if(s=="empty_list_header_identity") {
        ka={{0,0,0x30000,0}};apply(a,ka);apply(b,ka);
    }
    OwnershipKey keys[2]={ka,kb};size_t count=s=="multiple_owners"?2:1;
    assert(gate.publish(keys,count,17,true)==GateResult::ok);
    if(s=="held_managed"||s=="held_burst"||s=="burst_high_tag_owned_held") {
        if(s=="burst_high_tag_owned_held")expected_tag=intptr_t{0x100000001};
        invoke(gate,&a,s!="held_managed");assert(calls==0&&gate.stats().held_calls==1);
    } else if(s=="unowned_held"||s=="one_header_differs") {
        if(s=="one_header_differs"){apply(b,ka);put(b,0x98,ka.list_headers[3]+1);}
        invoke(gate,&b);assert(calls==1&&gate.stats().owned_calls==0);
    } else if(s=="root_motion"||s=="unknown_burst_tag") {
        expected_tag=s=="root_motion"?0:77;
        // Non-animation tags must not inspect even this non-dereferenceable job.
        gate.invoke_burst(burst,reinterpret_cast<void*>(1),expected_stream,expected_tag,
            expected_ranges,expected_index);assert(calls==1&&gate.stats().owned_calls==0);
    } else if(s=="null_job") {
        invoke(gate,nullptr);invoke(gate,nullptr,true);assert(calls==2&&gate.stats().owned_calls==0);
    } else if(s=="missing_original") {
        gate.invoke_managed(nullptr,&a,expected_stream,expected_method);
        gate.invoke_burst(nullptr,&a,expected_stream,1,expected_ranges,expected_index);
        assert(calls==0&&gate.stats().readers==0&&gate.stats().owned_calls==0);
    } else if(s=="stale_epoch") {
        assert(gate.grant(1,18,true)==GateResult::stale);
        assert(gate.hold(18,true)==GateResult::stale);
        assert(gate.retire(18,true)==GateResult::stale);
        assert(gate.detach_stale(18)==GateResult::stale);
        invoke(gate,&a);assert(calls==0);
    } else if(s=="unfenced_grant") {
        assert(gate.grant(1,17,false)==GateResult::waiting);invoke(gate,&a);assert(calls==0);
    } else if(s=="unfenced_hold") {
        assert(gate.grant(1,17,true)==GateResult::ok);
        assert(gate.hold(17,false)==GateResult::waiting);invoke(gate,&a);assert(calls==1);
    } else if(s=="unfenced_retire") {
        assert(gate.retire(17,false)==GateResult::waiting);invoke(gate,&a);assert(calls==0);
    } else if(s=="publish_busy") {
        assert(gate.publish(&kb,1,18,true)==GateResult::busy);invoke(gate,&a);assert(calls==0);
    } else if(s=="detach_requires_original_epoch_fence") {
        assert(gate.detach_stale(17)==GateResult::waiting);invoke(gate,&a);assert(calls==1);
        assert(gate.grant(1,17,true)==GateResult::stale);
        assert(gate.publish(&kb,1,18,true)==GateResult::busy);
        assert(gate.retire(18,true)==GateResult::stale);
        assert(gate.retire(17,false)==GateResult::waiting);
    } else {
        assert(gate.grant(1,17,true)==GateResult::ok);
        if(s=="granted_managed"||s=="granted_burst") {
            invoke(gate,&a,s=="granted_burst");assert(calls==1&&gate.stats().permitted_calls==1);
        } else if(s=="mixed_route_duplicate"||s=="empty_list_header_identity") {
            if(s=="mixed_route_duplicate")apply(b,ka);
            invoke(gate,&a);invoke(gate,&b,true);
            assert(calls==1&&gate.stats().duplicate_calls==1);
        } else if(s=="ordered_grants_and_hold") {
            invoke(gate,&a);invoke(gate,&a);assert(calls==1);
            assert(gate.grant(0,17,true)==GateResult::invalid);
            assert(gate.grant(1,17,true)==GateResult::invalid);
            assert(gate.grant(2,17,true)==GateResult::ok);invoke(gate,&a,true);assert(calls==2);
            assert(gate.grant(1,17,true)==GateResult::invalid);
            assert(gate.hold(17,true)==GateResult::ok);invoke(gate,&a);assert(calls==2);
            assert(gate.grant(3,17,true)==GateResult::ok);invoke(gate,&a);assert(calls==3);
        } else if(s=="multiple_owners") {
            invoke(gate,&a);invoke(gate,&b,true);invoke(gate,&a,true);invoke(gate,&b);
            assert(calls==2&&gate.stats().duplicate_calls==2);
        } else if(s=="concurrent_duplicate") {
            std::vector<std::thread> workers;
            for(int i=0;i<32;++i)workers.emplace_back([&,i]{invoke(gate,&a,bool(i&1));});
            for(auto& t:workers)t.join();
            assert(calls==1&&gate.stats().duplicate_calls==31);
        } else if(s=="original_exception_releases_reader") {
            bool caught=false;try{gate.invoke_managed(throws,&a,expected_stream,expected_method);}
            catch(const std::runtime_error&){caught=true;}assert(caught&&gate.stats().readers==0);
            invoke(gate,&a,true);assert(calls==0&&gate.stats().duplicate_calls==1);
        } else if(s=="retirement_waits_for_callback") {
            Blocker state;blocker=&state;
            std::thread worker([&]{gate.invoke_managed(blocked,&a,expected_stream,expected_method);});
            state.wait_for_entry();assert(gate.stats().readers==1);
            // Even a prematurely reported fence cannot overwrite a reader.
            assert(gate.retire(17,true)==GateResult::waiting);
            assert(gate.publish(&kb,1,18,true)==GateResult::busy);
            state.release();worker.join();assert(calls==1&&gate.stats().readers==0);
        } else if(s=="retire_then_republish") {
            invoke(gate,&a);assert(calls==1);
        } else {assert(!"unknown scenario");}
    }
    assert(gate.stats().readers==0);
    assert(gate.retire(17,true)==GateResult::ok);
    if(s=="retire_then_republish"||s=="retirement_waits_for_callback"
            ||s=="detach_requires_original_epoch_fence") {
        assert(gate.publish(&kb,1,18,true)==GateResult::ok);
        assert(gate.grant(1,18,true)==GateResult::ok);invoke(gate,&b);
        assert(gate.retire(18,true)==GateResult::ok);
    }
}
'''


@pytest.fixture(scope="module")
def gate_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    directory = tmp_path_factory.mktemp("mp4-actor-gate")
    source = directory / "gate.cpp"
    source.write_text(SOURCE)
    binary = directory / "gate"
    built = subprocess.run(
        [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-I", str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "no_owner_managed", "no_owner_burst", "invalid_publish", "held_managed", "held_burst", "burst_high_tag_owned_held",
    "unowned_held", "one_header_differs", "root_motion", "unknown_burst_tag", "null_job",
    "missing_original", "stale_epoch", "unfenced_grant", "unfenced_hold", "unfenced_retire",
    "publish_busy", "detach_requires_original_epoch_fence", "granted_managed", "granted_burst",
    "mixed_route_duplicate", "empty_list_header_identity", "ordered_grants_and_hold",
    "multiple_owners", "concurrent_duplicate", "original_exception_releases_reader",
    "retirement_waits_for_callback", "retire_then_republish",
])
def test_original_typed_actor_worker_gate(gate_binary, scenario):
    ran = subprocess.run([str(gate_binary), scenario], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
