"""Original task forwarding and exact failure/owner-scoped wardrobe wait recovery."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent


def test_real_task_lifecycle_preserves_owner_failure_cancel_and_reuse(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    binary = tmp_path / "wardrobe-lifecycle"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    str(HERE / "wardrobe_lifecycle_test.cpp"), "-o", str(binary)],
                   check=True, capture_output=True, timeout=20)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    fields = {"schema", "phase", "show_failures", "released_waits", "sequence", "sample_age_ms"}
    assert len(rows) == 3 and all(set(row) == fields and row["schema"] == 1 for row in rows)
    assert rows[0] == dict(schema=1, phase="idle", show_failures=0, released_waits=0, sequence=0, sample_age_ms=None)
    assert rows[1] == dict(schema=1, phase="hide_wait_released", show_failures=1, released_waits=1, sequence=3, sample_age_ms=50)
    assert all(rows[2][name] == (1 << 63) - 1 for name in fields - {"schema", "phase"})


def test_android_only_original_pins_and_readonly_jni_are_wired():
    profile = json.loads((NATIVE / "profile.json").read_text())
    aliases = profile["aliases"]
    assert len(aliases) == 111
    expected = {
        "wardrobe_show": ("0x53779a4", "HOOK"),
        "wardrobe_move": ("0x497094c", "HOOK"),
        "wardrobe_fail": ("0x7d0e5f4", "HOOK"),
        "wardrobe_wait": ("0x8d6e1e8", "HOOK"),
        "wardrobe_yield": ("0x8d6d274", "CALL"),
        "wardrobe_hide_predicate": ("0x49702ec", "CALL"),
    }
    for name, pair in expected.items():
        assert (aliases[name]["rva"], aliases[name]["mode"]) == pair
    assert aliases["wardrobe_hide_predicate"]["function_size_bytes"] == 8
    bridge = (NATIVE / "bridge.cpp").read_text()
    assert '#ifndef IDOLY_DARWIN_BRIDGE\n#include "wardrobe_lifecycle.hpp"\n#include "wardrobe_timing.hpp"\n#include "bulk_checked_filter.hpp"\n#endif' in bridge
    assert "HOOK(wardrobe_hide_predicate" not in bridge
    for name in ("wardrobe_show", "wardrobe_move", "wardrobe_fail", "wardrobe_wait"):
        assert f"HOOK({name}," in bridge
    jni = bridge.split("NativePresentation_wardrobeStatus(", 1)[1].split("\n}", 1)[0]
    assert "wardrobe_status_json" in jni and "char json[1536]" in jni
    assert "wardrobe_lifecycle" not in jni and "_get(" not in jni
    snapshot = bridge.split("void wardrobe_status_json(", 1)[1].split("\n}", 1)[0]
    assert "wardrobe_tracker.snapshot()" in snapshot and "render_probe_monotonic_ms()" in snapshot
    assert "cleanup" not in snapshot and "game_call" not in snapshot


def test_scoped_sort_dispatch_uses_original_filter_and_original_fallback(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("A host C++ compiler is unavailable")
    bridge = (NATIVE / "bridge.cpp").read_text()
    dispatch = bridge.split("// BEGIN_ORIGINAL_COSTUME_SORT_DISPATCH\n", 1)[1].split("// END_ORIGINAL_COSTUME_SORT_DISPATCH", 1)[0]
    source = tmp_path / "sort.cpp"
    source.write_text(r'''
#include <atomic>
#include <cassert>
#include <stdexcept>
using Method=const void;
std::atomic<bool> ready{false};bool thread=false,policy=false;int normal=0,ordered=0;
bool game_call(bool establish){assert(!establish);return thread;}
bool master_costume_order_enabled(){return policy;}
''' + dispatch + r'''
void *self1=(void*)1,*char1=(void*)2;Method *info=(Method*)3;
void *original(void*s,void*c,Method*m){++normal;assert(m==info);return s?s:c;}
void *order(void*s,void*c,Method*m){++ordered;assert(s==self1&&c==char1&&!m);return c;}
int main(){costume_sorted_original=original;costume_order_sorted=order;
costume_sorted_hook(self1,char1,info);assert(normal==1&&!ordered);
ready=true;policy=true;costume_sorted_hook(self1,char1,info);assert(normal==2&&!ordered);
thread=true;policy=false;costume_sorted_hook(self1,char1,info);assert(normal==3&&!ordered);
policy=true;assert(costume_sorted_hook(self1,char1,info)==char1);assert(ordered==1);
costume_sorted_hook(nullptr,char1,info);costume_sorted_hook(self1,nullptr,info);assert(normal==5&&ordered==1);
}
''')
    binary = tmp_path / "sort"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)
