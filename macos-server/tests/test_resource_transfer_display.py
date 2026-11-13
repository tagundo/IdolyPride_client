"""Cached resource-transfer UI formatting; no Mac execution or cache access."""
from pathlib import Path
import resource
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COUNTERS = ("session_served_bytes", "session_received_bytes", "session_http_requests",
            "session_http_failures", "session_cache_hits", "session_cache_misses")


def bounded():
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def test_display_distinguishes_local_cdn_waiting_failure_and_unknown(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required")
    binary = tmp_path / "transfer-display"
    subprocess.run([compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
        str(ROOT / "cross/tests/resource_transfer_display_test.c"), "-o", str(binary)],
        check=True, timeout=20, preexec_fn=bounded)
    result = subprocess.run([str(binary)], check=False, capture_output=True, text=True,
                            timeout=3, preexec_fn=bounded)
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip().endswith("RESOURCE_TRANSFER_DISPLAY_PASS")


def test_both_actual_uis_use_cached_status_safe_fields_and_typed_counters():
    swift = (ROOT / "App.swift").read_text()
    cocoa = (ROOT / "cross/appkit_ui.c").read_text()
    for key in COUNTERS + ("active_http_requests", "last_request", "last_failed_request", "cause_code"):
        assert f'"{key}"' in swift and f'"{key}"' in cocoa
    assert "CFBooleanGetTypeID()" in swift.split("// BEGIN_RESOURCE_TRANSFER_DISPLAY", 1)[1]
    for key in COUNTERS:
        assert f'id_json_integer(id_item(transfer,"{key}"),-1)' in cocoa
    assert 'resourceTransferMessage = Self.resourceTransferDescription(state["resource_transfer"]' in swift
    assert 'resource_transfer_status(id_item(state,"resource_transfer"))' in cocoa
    assert '"resource_transfer_display.h"' in cocoa
    assert 'count<=64' in cocoa and '$0.count <= 64' in swift
    assert 'id_is(failed,"NSNull")' in cocoa and 'value["last_failed_request"] is NSNull' in swift
    assert "서버 시작 후 누적" in swift and "서버 시작 후 누적" in cocoa
    assert 'request["path"]' not in swift and 'id_item(value,"path")' not in cocoa


def test_actual_cocoa_display_compiles_with_all_existing_controls():
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("A host C compiler is required")
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-fsyntax-only",
        str(ROOT / "cross/appkit_ui.c")], check=True, timeout=20, preexec_fn=bounded)


@pytest.mark.skipif(shutil.which("swiftc") is None, reason="Swift compiler unavailable")
def test_actual_swift_formatter_handles_old_and_failed_snapshots(tmp_path):
    app = (ROOT / "App.swift").read_text()
    methods = app.split("// BEGIN_RESOURCE_TRANSFER_DISPLAY", 1)[1].split("// END_RESOURCE_TRANSFER_DISPLAY", 1)[0]
    methods = methods.replace("private static func resourceTransferDescription", "static func resourceTransferDescription")
    source = "import Foundation\nimport CoreFoundation\nstruct Display {\n" + methods + r'''
}
let legacy:[String:Any] = ["session_served_bytes":4118226035,"session_received_bytes":0]
let old=Display.resourceTransferDescription(legacy)
assert(old.contains("로컬→게임 3.8 GiB · CDN→서버 0 B"))
assert(old.contains("게임 HTTP 요청 확인 불가"))
let failed:[String:Any] = ["kind":"object","phase":"failed","object_name":"body.ab",
 "http_status":503,"error_code":"octo_cache_miss","cache_result":"cache_miss"]
let values:[String:Any] = ["session_http_requests":true,"session_http_failures":1.5,
 "active_http_requests":[],"last_request":["kind":"manifest","http_status":200,"phase":"completed"],
 "last_failed_request":failed]
let text=Display.resourceTransferDescription(values)
assert(text.contains("게임 HTTP 요청 확인 불가 · 실패 확인 불가"))
assert(text.contains("최근 실패: body.ab · HTTP 503 · 실패 · 미보관 · octo_cache_miss"))
assert(!text.contains("HTTP 0"))
print("SWIFT_RESOURCE_TRANSFER_DISPLAY_PASS")
'''
    path = tmp_path / "display.swift"; path.write_text(source)
    binary = tmp_path / "display"
    subprocess.run([shutil.which("swiftc"), str(path), "-o", str(binary)], check=True,
                   capture_output=True, timeout=30)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=3)
    assert result.stdout.strip() == "SWIFT_RESOURCE_TRANSFER_DISPLAY_PASS"
