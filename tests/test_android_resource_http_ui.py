"""Actual Android formatter against tracker exports and malformed boundaries.

The host harness compiles the exact pure methods extracted from MainActivity;
its tiny JSONObject seam supplies values without Android or a JSON coercer.
"""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess

import pytest

from idoly_local.octo_runtime import OctoResourceTracker


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/MainActivity.java"
BEGIN = "// Resource HTTP diagnostics formatter begins. Pure, bounded and Android-free."
END = "// Resource HTTP diagnostics formatter ends."


def formatter():
    return ACTIVITY.read_text().split(BEGIN, 1)[1].split(END, 1)[0]


def event(identity=1, *, kind="manifest", phase="received", status=0, **extra):
    return dict(source="octo_request", request_id=identity, method="GET", kind=kind,
                phase=phase, http_status=status, route_fingerprint="a" * 16,
                object_name=None, cache_key=None, error_code=None, cause_code=None,
                application_version=205051 if kind == "manifest" else None,
                requested_revision=1090 if kind == "manifest" else None,
                served_revision=None, response_mode=None, **extra)


def exported_cases():
    idle = OctoResourceTracker(available=True)
    zero = idle.status()
    # A bulk-library cache hit can occur without a game HTTP request. It must
    # not be presented as evidence that bytes were served to the client.
    idle.on_cache_event(dict(phase="cache_hit", cache_key="b" * 64, received_bytes=0, total_bytes=4))
    bulk_only = idle.status()
    failed = OctoResourceTracker(available=True)
    first = event()
    failed.on_http_request(first)
    failed.on_http_request({**first, "phase": "failed", "http_status": 409,
                            "error_code": "octo_revision_unavailable"})
    revision_failure = failed.status()
    latest = {**event(2), "requested_revision": 1089}
    failed.on_http_request(latest)
    failed.on_http_request({**latest, "phase": "completed", "http_status": 200,
                           "served_revision": 1089, "response_mode": "unchanged"})
    recovered = failed.status()
    cached = OctoResourceTracker(available=True)
    row = {**event(kind="object"), "object_name": "adv/event_1.txt", "cache_key": "c" * 64}
    cached.on_http_request(row)
    cached.on_cache_event(dict(phase="cache_hit", cache_key="c" * 64, received_bytes=0, total_bytes=4))
    cached.on_http_request({**row, "phase": "completed", "http_status": 206})
    return zero, bulk_only, revision_failure, recovered, cached.status()


def test_actual_tracker_contract_keeps_http_and_bulk_cache_observations_distinct():
    zero, bulk, failed, recovered, cached = exported_cases()
    assert zero["session_http_requests"] == bulk["session_http_requests"] == 0
    assert bulk["session_cache_hits"] == 1 and bulk["session_served_bytes"] == 0
    assert failed["session_http_requests"] == failed["session_http_failures"] == 1
    assert failed["last_failed_request"]["requested_revision"] == 1090
    assert failed["last_failed_request"]["served_revision"] is None
    assert recovered["session_http_requests"] == 2
    assert recovered["last_failed_request"]["http_status"] == 409
    assert recovered["last_request"]["served_revision"] == 1089
    assert cached["last_request"]["cache_result"] == "cache_hit"
    assert cached["last_request"]["phase"] == "completed"


def test_android_display_uses_public_resource_channel_and_retains_old_byte_labels():
    source = ACTIVITY.read_text()
    update = source.split("private void updateResources(JSONObject details)", 1)[1].split(BEGIN, 1)[0]
    assert 'details.optJSONObject("resource_transfer")' in update
    assert "resourceHttpDiagnostics(resources)" in update
    assert "R.string.resource_transfer_received" in update and "R.string.resource_transfer_served" in update
    assert "setTextIfChanged(resourceServed" in update
    pure = formatter()
    for forbidden in ("rx_bytes", "tx_bytes", "network", "getString(", "android.", "http://", "https://"):
        assert forbidden not in pure
    assert 'resources.has("session_http_requests")' in pure
    assert 'text.length() <= 1024' in pure
    assert "optLong(" not in re.sub(r"//[^\n]*", "", pure)


def test_display_error_tokens_match_the_actual_export_allowlist():
    from idoly_local.octo_runtime import _FAILURE_CODES, _REQUEST_CAUSES, _REQUEST_ERRORS
    assert set(re.findall(r'case "([^"]+)"', formatter())) == _FAILURE_CODES | _REQUEST_CAUSES | _REQUEST_ERRORS


def java_value(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "Boolean.TRUE" if value else "Boolean.FALSE"
    if isinstance(value, int):
        if -(2**31) <= value < 2**31:
            return str(value)
        return str(value) + "L" if -(2**63) < value < 2**63 else 'new java.math.BigInteger(' + json.dumps(str(value)) + ')'
    if isinstance(value, float):
        return repr(value) + "d"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, dict):
        return "new JSONObject()" + "".join(".put(" + json.dumps(k) + "," + java_value(v) + ")" for k, v in value.items()
                                             if not isinstance(v, list))
    raise AssertionError(type(value))


def test_host_java_formats_real_snapshots_without_coercion_or_unbounded_fields(tmp_path):
    cached_jdk = ROOT.parent / ".setup/jdk-system/usr/lib/jvm/java-21-openjdk-amd64/bin"
    javac = cached_jdk / "javac" if (cached_jdk / "javac").is_file() else shutil.which("javac")
    java = cached_jdk / "java" if (cached_jdk / "java").is_file() else shutil.which("java")
    if not javac or not java:
        pytest.skip("Host JDK unavailable")
    zero, bulk, failed, recovered, cached = exported_cases()
    tests = []

    def check(value, contains=(), excludes=(), exact=None):
        tests.append("check(" + java_value(value) + ",new String[]{" + ",".join(java_value(x) for x in contains)
                     + "},new String[]{" + ",".join(java_value(x) for x in excludes) + "}," + java_value(exact) + ");")

    check(None, exact="")
    check({}, exact="")
    check(zero, ["로컬 HTTP 요청 0 · 실패 0", "로컬 요청 수신 없음"], ["형식 오류", "캐시에서 응답"])
    check(bulk, ["캐시 적중 1", "로컬 요청 수신 없음"], ["형식 오류", "캐시에서 응답"])
    check(failed, ["로컬 HTTP 요청 1 · 실패 1", "마지막 실패 기록", "HTTP 409", "octo_revision_unavailable",
                   "앱 205051 · 요청 개정 1090 · 제공 개정 확인 안 됨"], ["최근 요청"])
    check(recovered, ["마지막 실패 기록", "HTTP 409", "최근 요청", "HTTP 200", "요청 개정 1089 · 제공 개정 1089"])
    check(cached, ["서버 캐시에서 응답한 기록 있음", "HTTP 206", "파일 adv/event_1.txt"], ["실패 기록 있음"])
    for value in (True, "1", 1.0, -1, 2**63):
        check({"session_http_requests": value}, exact="로컬 HTTP 요청 기록 형식 오류")
    check({"session_http_requests": 2**63 - 1}, ["9223372036854775807", "실패 확인 안 됨", "캐시 적중 확인 안 됨"])
    check({"session_http_requests": 1, "session_http_failures": "7", "session_cache_hits": 1.5},
          ["실패 확인 안 됨", "캐시 적중 확인 안 됨"], ["실패 7", "적중 1"])
    for name in ("https://host/private?token=secret", "../private", "bad\nname", "a//b", "x" * 161):
        row = {**event(kind="object"), "phase": "failed", "http_status": 503,
               "error_code": "octo_cache_miss", "object_name": name, "cache_key": "a" * 64}
        check({"session_http_requests": 1, "session_http_failures": 1, "last_failed_request": row},
              ["HTTP 503", "octo_cache_miss", "파일 키 " + "a" * 64], [name])
    row = {**event(kind="object"), "phase": "failed", "http_status": 503, "object_name": "x" * 160,
           "error_code": "unsafe?token=secret", "cause_code": "upstream_tls", "cache_key": "A" * 64}
    check({"session_http_requests": 1, "last_failed_request": row}, ["파일 " + "x" * 160, "upstream_tls"], ["secret", "A" * 64])
    for status in (True, "503", 503.5, 99, 600):
        check({"session_http_requests": 1, "last_failed_request": {**row, "http_status": status}}, excludes=[" · HTTP "])
    for requested in (True, "1090", -1, 2**31):
        bad = {**event(), "phase": "completed", "http_status": 200,
               "requested_revision": requested, "served_revision": 1090, "response_mode": "unchanged"}
        check({"session_http_requests": 1, "last_request": bad}, excludes=["앱 205051"])
    max_revision = {**event(), "phase": "completed", "http_status": 200,
                    "requested_revision": 2**31 - 1, "served_revision": 2**31 - 1, "response_mode": "unchanged"}
    check({"session_http_requests": 1, "last_request": max_revision}, ["요청 개정 2147483647 · 제공 개정 2147483647"])
    full_ios = {**max_revision, "application_version": 105051, "requested_revision": 0,
                "served_revision": 1160, "response_mode": "full"}
    check({"session_http_requests": 1, "last_request": full_ios}, ["앱 105051 · 요청 개정 0 · 제공 개정 1160"])
    for served in (0, -1, 2**31, True, "1089", 1089.0):
        bad = {**max_revision, "requested_revision": 1089, "served_revision": served}
        check({"session_http_requests": 1, "last_request": bad}, ["제공 개정 확인 안 됨"])
    bad_sticky = {**row, "request_id": 7, "phase": "not-a-phase"}
    latest = {**max_revision, "request_id": 7}
    check({"session_http_requests": 1, "last_failed_request": bad_sticky, "last_request": latest},
          ["최근 요청", "HTTP 200"], ["마지막 실패 기록"])
    harness = """import java.util.HashMap;
public final class ResourceHttpUiHost {
 static final class JSONObject {
  private final HashMap<String,Object> values = new HashMap<>();
  JSONObject put(String key,Object value) { values.put(key,value); return this; }
  Object opt(String key) { return values.get(key); }
  boolean has(String key) { return values.containsKey(key); }
  JSONObject optJSONObject(String key) { Object v=opt(key); return v instanceof JSONObject?(JSONObject)v:null; }
 }
""" + formatter() + """
 static void check(JSONObject row,String[] contains,String[] excludes,String exact) {
  String actual=resourceHttpDiagnostics(row);
  if (actual.length()>1024) throw new AssertionError("unbounded output");
  if (exact!=null && !actual.equals(exact)) throw new AssertionError(actual);
  for (String value:contains) if (!actual.contains(value)) throw new AssertionError("missing "+value+" in "+actual);
  for (String value:excludes) if (actual.contains(value)) throw new AssertionError("unsafe/unexpected "+value+" in "+actual);
 }
 public static void main(String[] args) {
""" + "\n".join(tests) + '\nSystem.out.println("resource HTTP formatter checks passed");\n}\n}\n'
    source = tmp_path / "ResourceHttpUiHost.java"
    source.write_text(harness)
    flags = ["-Xms16m", "-Xmx64m", "-Xss256k", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1",
             "-XX:MaxMetaspaceSize=48m", "-XX:CompressedClassSpaceSize=8m", "-XX:ReservedCodeCacheSize=16m"]
    env = dict(os.environ)
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS"):
        env.pop(key, None)
    subprocess.run([str(javac), *("-J" + flag for flag in flags), "-encoding", "UTF-8", "-d", str(tmp_path), str(source)],
                   check=True, capture_output=True, timeout=30, env=env)
    result = subprocess.run([str(java), *flags, "-cp", str(tmp_path), "ResourceHttpUiHost"],
                            check=True, text=True, capture_output=True, timeout=10, env=env)
    assert "resource HTTP formatter checks passed" in result.stdout
