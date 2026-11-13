from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import threading
import time

from Crypto.Cipher import AES
import pytest

from idoly_local.assets import create_asset_server
from idoly_local.octo_manifest import Database, decrypt_manifest
from idoly_local.octo_runtime import (
    MAX_ARCHIVE_BYTES, MAX_SETTINGS_BYTES, OctoResourceTracker,
    create_octo_gateway, load_octo_archive,
)


ORIGINAL_URL = ("https://d2ilil7yh5oi1v.cloudfront.net/"
                "solis-{v}-{type}/{o}?generation={g}&alt=media")
KEY = hashlib.sha256(b"synthetic runtime application").digest()
CLIENT_KEY = "synthetic-key"
PAYLOAD = b"unchanged original resource bytes"
HEADERS = {"Accept": "application/x-protobuf,x-octo-app/212", "X-OCTO-KEY": CLIENT_KEY}


def aes(encrypt, key, iv, data):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(data) if encrypt else cipher.decrypt(data)


def write_archive(directory, *, revision=1087, platform="android"):
    directory.mkdir(parents=True, exist_ok=True)
    database = Database(revision=revision, urlFormat=ORIGINAL_URL)
    for kind, target in (("assetbundle", database.assetBundleList), ("resources", database.resourceList)):
        target.add(id=1, name="synthetic-"+kind, size=len(PAYLOAD), state=1,
            md5=hashlib.md5(PAYLOAD).hexdigest(), objectName="object_"+kind,
            generation=12345, uploadVersionId=101050 if platform == "ios" else 202050)
    raw = database.SerializeToString()
    settings = {"schema":1, "application_id":212, "application_version":105051 if platform == "ios" else 205051,
        "revision":1159 if platform == "ios" else 1087, "manifest_sha256":hashlib.sha256(raw).hexdigest(),
        "aes_key_hex":KEY.hex(), "client_key":CLIENT_KEY}
    (directory/"settings.json").write_text(json.dumps(settings))
    (directory/"manifest.pb").write_bytes(raw)
    return settings, raw


def upstream(tracker, phase, key="a"*64, received=0, total=10, **extra):
    tracker.on_cache_event({"phase":phase, "cache_key":key,
        "received_bytes":received, "total_bytes":total, **extra})


def local(tracker, phase, *, identity=1, sent=0, total=10, kind="object", **extra):
    tracker.on_http_transfer({"source":"octo", "kind":kind, "phase":phase,
        "transfer_id":identity, "sent_bytes":sent, "total_bytes":total, **extra})


def test_failed_attempt_retry_and_cache_hits_are_distinct_network_measurements():
    logs = []
    tracker = OctoResourceTracker(available=True, log_callback=logs.append)
    upstream(tracker,"started")
    upstream(tracker,"progress",received=4)
    upstream(tracker,"progress",received=4)
    upstream(tracker,"failed",received=6,error_code="upstream_timeout")
    upstream(tracker,"failed",received=6,error_code="upstream_timeout")
    assert tracker.status()["session_received_bytes"] == 6
    assert tracker.status()["active_requests"] == 0
    assert tracker.status()["status"] == "failed"
    upstream(tracker,"started")
    upstream(tracker,"verified",received=10)
    upstream(tracker,"verified",received=10)
    upstream(tracker,"cache_hit")
    upstream(tracker,"cache_hit")
    assert tracker.status()["session_received_bytes"] == 16
    assert tracker.status()["session_verified_files"] == 1
    assert tracker.status()["status"] == "ready"
    assert len(logs) == 2


def test_redownload_counts_new_bytes_but_does_not_claim_another_unique_file():
    tracker = OctoResourceTracker(available=True)
    for _ in range(2):
        upstream(tracker,"started")
        upstream(tracker,"verified",received=10)
    assert tracker.status()["session_received_bytes"] == 20
    assert tracker.status()["session_verified_files"] == 1


def test_parallel_download_status_survives_other_request_failure_and_finishes():
    tracker = OctoResourceTracker(available=True)
    upstream(tracker,"started")
    upstream(tracker,"started",key="b"*64,total=20)
    upstream(tracker,"failed",received=3,error_code="upstream_http")
    assert tracker.status()["status"] == "downloading"
    assert tracker.status()["active_requests"] == 1
    upstream(tracker,"progress",key="b"*64,received=11,total=20)
    status = tracker.status()
    assert (status["last_received_bytes"],status["last_total_bytes"]) == (11,20)
    upstream(tracker,"verified",key="b"*64,received=20,total=20)
    assert tracker.status()["status"] == "ready"
    assert tracker.status()["session_received_bytes"] == 23


def test_parallel_upstream_callbacks_count_every_attempt_once():
    tracker = OctoResourceTracker(available=True)
    def fetch(index):
        key = hashlib.sha256(str(index).encode()).hexdigest()
        upstream(tracker,"started",key=key,total=13)
        upstream(tracker,"progress",key=key,received=7,total=13)
        upstream(tracker,"verified",key=key,received=13,total=13)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(fetch,range(80)))
    status = tracker.status()
    assert status["active_requests"] == 0
    assert status["session_received_bytes"] == 80*13
    assert status["session_verified_files"] == 80


def test_ranges_partial_failure_manifest_and_head_counters_are_not_combined():
    tracker = OctoResourceTracker(available=True)
    local(tracker,"started",identity=1,total=4)
    local(tracker,"completed",identity=1,sent=4,total=4)
    local(tracker,"completed",identity=1,sent=4,total=4)
    local(tracker,"started",identity=2,total=6)
    local(tracker,"progress",identity=2,sent=2,total=6)
    local(tracker,"failed",identity=2,sent=3,total=6,http_status=200)
    local(tracker,"started",identity=3,total=120,kind="manifest")
    local(tracker,"completed",identity=3,sent=120,total=120,kind="manifest")
    # HEAD sends no object transfer events and cached reads receive no new bytes.
    upstream(tracker,"cache_hit")
    status = tracker.status()
    assert status["session_served_bytes"] == 7
    assert status["session_manifest_bytes"] == 120
    assert status["session_received_bytes"] == 0
    assert status["session_verified_files"] == 0


def test_early_http_cache_miss_can_fail_without_counting_an_error_body_as_resource_bytes():
    logs = []
    tracker = OctoResourceTracker(available=True,allow_downloads=False,log_callback=logs.append)
    local(tracker,"failed",sent=0,http_status=503,path="/not-logged-secret")
    assert tracker.status()["status"] == "failed"
    assert tracker.status()["active_requests"] == 0
    assert tracker.status()["session_served_bytes"] == 0
    assert logs == ["게임 리소스 전송 중단 · HTTP 503"]


def test_duplicate_start_does_not_reset_a_live_counter_and_invalid_completion_does_not_finish():
    tracker = OctoResourceTracker(available=True)
    upstream(tracker,"started")
    upstream(tracker,"progress",received=4)
    upstream(tracker,"started")
    upstream(tracker,"progress",received=3)
    upstream(tracker,"verified",received=8)
    assert tracker.status()["session_received_bytes"] == 4
    assert tracker.status()["active_requests"] == 1
    local(tracker,"started")
    local(tracker,"completed",sent=8)
    assert tracker.status()["session_served_bytes"] == 0
    local(tracker,"completed",sent=10)
    assert tracker.status()["session_served_bytes"] == 10
    upstream(tracker,"verified",received=10)
    assert tracker.status()["active_requests"] == 0


def test_oversize_failure_counts_the_extra_byte_actually_received():
    tracker = OctoResourceTracker(available=True)
    upstream(tracker,"started")
    upstream(tracker,"failed",received=11,error_code="upstream_size")
    assert tracker.status()["session_received_bytes"] == 11
    assert tracker.status()["active_requests"] == 0
    assert tracker.status()["session_verified_files"] == 0


def test_observer_exceptions_secret_fields_and_returned_status_do_not_affect_transfers():
    logs=[]
    def broken(message):
        logs.append(message)
        raise RuntimeError("untrusted secret")
    tracker=OctoResourceTracker(available=True,log_callback=broken)
    upstream(tracker,"started")
    upstream(tracker,"failed",received=4,error_code="untrusted secret",headers={"Authorization":"secret"})
    snapshot=tracker.status();snapshot["session_received_bytes"]=-100
    assert tracker.status()["session_received_bytes"]==4
    assert logs==["게임 리소스 내려받기 중단 · download_failed · 파일 " + "a" * 12]
    assert "secret" not in repr(tracker.status())


def test_counter_overflow_is_bounded_and_maps_are_bounded():
    tracker=OctoResourceTracker(available=True)
    maximum=2**63-1
    for key in ("a"*64,"b"*64):
        upstream(tracker,"started",key=key,total=maximum)
        upstream(tracker,"verified",key=key,received=maximum,total=maximum)
    assert tracker.status()["session_received_bytes"]==maximum
    for index in range(1025):
        key=hashlib.sha256(str(index).encode()).hexdigest()
        upstream(tracker,"started",key=key)
    assert tracker.status()["active_requests"]==1024
    assert tracker.status()["measurement_limited"] is True


def test_missing_legacy_archive_has_no_cache_or_aes_or_network_side_effect(tmp_path,monkeypatch):
    monkeypatch.setitem(sys.modules,"Crypto.Cipher",None)
    def forbidden(*args,**kwargs):
        raise AssertionError("no network or AES call expected")
    gateway,tracker=create_octo_gateway(tmp_path,"http://127.0.0.1:8080",fetcher=forbidden)
    assert gateway is None and tracker.status()["available"] is False
    assert not (tmp_path/"octo-cache").exists()
    assert load_octo_archive(tmp_path/"public-octo") is None


@pytest.mark.parametrize("filename",["settings.json","manifest.pb"])
def test_partial_archive_is_rejected_without_creating_cache(tmp_path,filename):
    public=tmp_path/"public-octo";write_archive(public);(public/filename).unlink()
    with pytest.raises(ValueError):create_octo_gateway(tmp_path,"http://127.0.0.1:8080")
    assert not (tmp_path/"octo-cache").exists()


@pytest.mark.parametrize("changes",[
    {"schema":True},{"application_id":213},{"application_version":"205051"},{"revision":1088},
    {"aes_key_hex":"A"*64},{"manifest_sha256":"F"*64},
    {"client_key":"bad\r\nheader"},{"client_key":"bad\x00key"},{"client_key":"非ASCII"},
    {"client_key":"k"*257},{"firebase_user":"must-not-be-accepted"},
])
def test_settings_reject_other_versions_credentials_and_header_injection(tmp_path,changes):
    public=tmp_path/"public-octo";settings,_=write_archive(public);settings.update(changes)
    (public/"settings.json").write_text(json.dumps(settings))
    with pytest.raises(ValueError):load_octo_archive(public)
    assert not (tmp_path/"octo-cache").exists()


def test_duplicate_json_keys_and_deep_json_raise_sanitized_value_error(tmp_path):
    public=tmp_path/"public-octo";write_archive(public)
    for encoded in (b'{"client_key":"secret","client_key":"other-secret"}',
                    ("["*1500+"0"+"]"*1500).encode()):
        (public/"settings.json").write_bytes(encoded)
        with pytest.raises(ValueError) as error:load_octo_archive(public)
        assert "secret" not in str(error.value)


@pytest.mark.parametrize("filename,limit",[("settings.json",MAX_SETTINGS_BYTES),("manifest.pb",MAX_ARCHIVE_BYTES)])
def test_size_limits_reject_sparse_oversized_inputs_without_reading_them(tmp_path,filename,limit):
    public=tmp_path/"public-octo";write_archive(public)
    with (public/filename).open("wb") as stream:stream.truncate(limit+1)
    with pytest.raises(ValueError):load_octo_archive(public)


@pytest.mark.parametrize("filename",["settings.json","manifest.pb"])
def test_archive_does_not_follow_files_outside_its_directory(tmp_path,filename):
    public=tmp_path/"public-octo";write_archive(public)
    outside=tmp_path/"outside";outside.write_bytes((public/filename).read_bytes())
    (public/filename).unlink();(public/filename).symlink_to(outside)
    with pytest.raises(ValueError):load_octo_archive(public)


def test_manifest_digest_and_actual_revision_are_checked_before_cache_creation(tmp_path):
    public=tmp_path/"public-octo";write_archive(public)
    (public/"manifest.pb").write_bytes(b"modified")
    with pytest.raises(ValueError,match="digest"):load_octo_archive(public)
    write_archive(public,revision=1088)
    with pytest.raises(ValueError,match="revision"):
        create_octo_gateway(tmp_path,"http://127.0.0.1:8080")
    assert not (tmp_path/"octo-cache").exists()


@pytest.mark.parametrize("value",[0,1,"true",None])
def test_download_choice_must_be_an_explicit_boolean_even_for_legacy_data(tmp_path,value):
    with pytest.raises(TypeError):create_octo_gateway(tmp_path,"http://127.0.0.1:8080",allow_downloads=value)


class Response(io.BytesIO):
    status=200
    def __init__(self,url):
        super().__init__(PAYLOAD);self.url=url;self.headers={"Content-Length":str(len(PAYLOAD))}
    def geturl(self):return self.url


def test_factory_real_http_ranges_head_and_cached_restart_keep_counters_honest(tmp_path):
    public=tmp_path/"public-octo";write_archive(public);calls=[]
    def fetch(url,*,timeout):
        calls.append(url);return Response(url)
    gateway,tracker=create_octo_gateway(tmp_path,"http://127.0.0.1:8080",aes_cbc=aes,fetcher=fetch)
    record=next(iter(gateway.manifest.objects.values()))
    object_path=f"/octo/{record.upload_version}/{record.kind}/{record.object_name}/{record.generation}"
    server=create_asset_server("127.0.0.1",0,tmp_path,octo=gateway)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(method,path,headers=None):
        connection=HTTPConnection(*server.server_address,timeout=5)
        connection.request(method,path,headers=headers or {})
        response=connection.getresponse();status=response.status;body=response.read();connection.close()
        return status,body
    try:
        status,encrypted=request("GET","/v2/pub/a/212/v/205051/list/0",HEADERS)
        assert status==200
        manifest=Database.FromString(decrypt_manifest(encrypted,aes_key=KEY,aes_cbc=aes))
        assert manifest.urlFormat=="http://127.0.0.1:8080/octo/{v}/{type}/{o}/{g}"
        assert tracker.status()["session_received_bytes"]==0 and calls==[]
        status,body=request("GET",object_path,{"Range":"bytes=2-8"})
        assert status==206 and body==PAYLOAD[2:9]
        assert request("HEAD",object_path)==(200,b"")
        assert request("GET",object_path)==(200,PAYLOAD)
        # HTTP bodies can reach the reader before independent serving threads
        # emit their final callbacks. Wait for both observations, not a new GET.
        deadline = time.monotonic() + 2
        while ((snapshot := tracker.status())["session_served_bytes"] != 7 + len(PAYLOAD)
               or snapshot["session_manifest_bytes"] != len(encrypted)) and time.monotonic() < deadline:
            threading.Event().wait(0.005)
        assert len(calls)==1
        assert snapshot["session_received_bytes"]==len(PAYLOAD)
        assert snapshot["session_verified_files"]==1
        assert snapshot["session_served_bytes"]==7+len(PAYLOAD)
        assert snapshot["session_manifest_bytes"]==len(encrypted)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
    def no_network(*args,**kwargs):raise AssertionError("cached restart must not fetch")
    restarted,new_tracker=create_octo_gateway(tmp_path,"http://127.0.0.1:8080",aes_cbc=aes,
        fetcher=no_network,allow_downloads=False)
    with restarted.cache.open_verified(record) as stream:assert stream.read()==PAYLOAD
    assert new_tracker.status()["session_received_bytes"]==0
    assert new_tracker.status()["session_verified_files"]==0
    assert new_tracker.status()["status"]=="ready"


def test_ios_catalog_requires_its_own_archive_version_and_keeps_android_cache_separate(tmp_path):
    android, _ = write_archive(tmp_path / "public-octo")
    ios, original = write_archive(tmp_path / "public-octo-ios", revision=1159, platform="ios")
    assert load_octo_archive(tmp_path / "public-octo-ios", platform="ios") == (ios, original)
    with pytest.raises(ValueError, match="version"):
        load_octo_archive(tmp_path / "public-octo-ios")
    with pytest.raises(ValueError, match="version"):
        load_octo_archive(tmp_path / "public-octo", platform="ios")
    gateway, tracker = create_octo_gateway(tmp_path, "http://127.0.0.1:8080",
                                           platform="ios", aes_cbc=aes)
    try:
        response = gateway.manifest.manifest_response("/v2/pub/a/212/v/105051/list/0", HEADERS)
        assert Database.FromString(decrypt_manifest(response, aes_key=KEY, aes_cbc=aes)).revision == 1159
        assert all(row.upload_version == 101050 for row in gateway.manifest.objects.values())
        from idoly_local.octo_manifest import OctoRequestError
        with pytest.raises(OctoRequestError) as error:
            gateway.manifest.manifest_response("/v2/pub/a/212/v/205051/list/0", HEADERS)
        assert error.value.status == 404
        assert not (tmp_path / "octo-cache").exists()
    finally:
        gateway.close()
    assert load_octo_archive(tmp_path / "public-octo")[0] == android


def test_upstream_failure_logs_distinguish_tls_and_http_without_adapter_details():
    logs = []
    tracker = OctoResourceTracker(available=True, log_callback=logs.append)
    for code, extra in (("upstream_tls", {"verify_code": 20}),
                        ("upstream_http", {"http_status": 403}),
                        ("upstream_http", {"http_status": 404})):
        upstream(tracker, "started")
        upstream(tracker, "failed", error_code=code, reason="sensitive URL/token", **extra)
    assert logs == ["게임 리소스 내려받기 중단 · upstream_tls · 인증서 코드 20 · 파일 " + "a" * 12,
                    "게임 리소스 내려받기 중단 · upstream_http · HTTP 403 · 파일 " + "a" * 12,
                    "게임 리소스 내려받기 중단 · upstream_http · HTTP 404 · 파일 " + "a" * 12]
    assert "sensitive" not in repr(logs)


@pytest.mark.parametrize("platform", [None, 0, True, [], "macos", "../public-octo"])
def test_unrecognized_resource_platform_rejected_even_without_an_archive(tmp_path, platform):
    with pytest.raises(ValueError, match="platform"):
        create_octo_gateway(tmp_path, "http://127.0.0.1:8080", platform=platform)
    assert not list(tmp_path.iterdir())


def observed_request(tracker, phase, identity=1, **changes):
    event = {"source": "octo_request", "request_id": identity, "method": "GET", "kind": "object",
             "phase": phase, "http_status": 0, "object_name": None, "cache_key": None,
             "route_fingerprint": "a" * 16, "error_code": None, "cause_code": None}
    event.update(changes)
    tracker.on_http_request(event)


def test_request_history_is_bounded_sticky_failure_survives_success_and_snapshots_are_independent():
    tracker = OctoResourceTracker(available=True)
    observed_request(tracker, "received")
    observed_request(tracker, "failed", http_status=409, error_code="octo_revision_unavailable")
    failure = tracker.status()["last_failed_request"]
    for identity in range(2, 75):
        observed_request(tracker, "received", identity)
        observed_request(tracker, "waiting_cache", identity, object_name="known stage", cache_key="b" * 64)
        upstream(tracker, "cache_hit", key="b" * 64)
        observed_request(tracker, "sending", identity, http_status=206, object_name="known stage", cache_key="b" * 64)
        observed_request(tracker, "completed", identity, http_status=206, object_name="known stage", cache_key="b" * 64)
    snapshot = tracker.status()
    assert snapshot["session_http_requests"] == 74 and snapshot["session_http_failures"] == 1
    assert snapshot["session_cache_hits"] == 73 and snapshot["session_cache_misses"] == 0
    assert len(snapshot["recent_requests"]) == 32 and not snapshot["active_http_requests"]
    assert snapshot["last_failed_request"] == failure
    assert snapshot["last_request"]["request_id"] == 74 and snapshot["last_request"]["cache_result"] == "cache_hit"
    assert snapshot["session_served_bytes"] == snapshot["session_received_bytes"] == 0
    assert all(not key.startswith("_") for row in snapshot["recent_requests"] for key in row)
    snapshot["last_failed_request"]["error_code"] = "changed"
    snapshot["recent_requests"].clear()
    assert tracker.status()["last_failed_request"] == failure and len(tracker.status()["recent_requests"]) == 32


def test_active_request_observations_are_bounded_and_failure_details_are_fixed_and_redacted():
    tracker = OctoResourceTracker(available=True)
    for identity in range(1, 66):
        observed_request(tracker, "received", identity, headers={"Authorization": "secret-token"}, url="?key=secret-query")
    snapshot = tracker.status()
    assert snapshot["session_http_requests"] == 65 and len(snapshot["active_http_requests"]) == 64
    assert snapshot["measurement_limited"] is True
    assert "secret" not in json.dumps(snapshot) and "headers" not in json.dumps(snapshot)
    observed_request(tracker, "failed", 1, http_status=502, error_code="secret-error")
    assert tracker.status()["session_http_failures"] == 0
    observed_request(tracker, "failed", 1, http_status=502, error_code="octo_resource_unavailable", cause_code="secret-cause")
    assert tracker.status()["session_http_failures"] == 0
    observed_request(tracker, "failed", 1, http_status=502, error_code="octo_resource_unavailable", cause_code="upstream_timeout")
    snapshot = tracker.status()
    assert snapshot["session_http_failures"] == 1
    assert snapshot["last_failed_request"]["cause_code"] == "upstream_timeout"
    assert len(snapshot["active_http_requests"]) == 63 and "secret" not in json.dumps(snapshot)


def test_cache_source_events_do_not_label_another_threads_matching_request():
    tracker = OctoResourceTracker(available=True)
    observed_request(tracker, "received")
    observed_request(tracker, "waiting_cache", object_name="known stage", cache_key="a" * 64)
    thread = threading.Thread(target=lambda: upstream(tracker, "cache_hit"))
    thread.start(); thread.join(timeout=2)
    assert not thread.is_alive()
    snapshot = tracker.status()
    assert snapshot["session_cache_hits"] == 1
    assert snapshot["active_http_requests"][0]["cache_result"] == "pending"
    upstream(tracker, "cache_hit")
    assert tracker.status()["active_http_requests"][0]["cache_result"] == "cache_hit"


@pytest.mark.parametrize("changes", [{"request_id": True}, {"method": "POST"}, {"http_status": True},
    {"route_fingerprint": "a" * 17}, {"object_name": "unsafe\nname"}, {"cache_key": "not-a-key"},
    {"phase": "progress"}, {"source": "untrusted"}])
def test_invalid_request_observations_do_not_create_work(changes):
    tracker = OctoResourceTracker(available=True)
    observed_request(tracker, changes.get("phase", "received"),
                     **{key: value for key, value in changes.items() if key != "phase"})
    snapshot = tracker.status()
    assert snapshot["session_http_requests"] == 0 and snapshot["active_http_requests"] == []
    assert snapshot["recent_requests"] == [] and snapshot["last_request"] is None
