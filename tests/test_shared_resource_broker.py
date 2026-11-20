"""Real private-file IPC, cache verification and one physical payload."""
import os
from pathlib import Path
import secrets
import stat
import threading
import time

import pytest

from idoly_local.octo_cache import OctoCache
from idoly_local.shared_resource_store import SharedResourceStore
from idoly_local.shared_resource_broker import (
    NOT_FOUND, READY, UNSUPPORTED, REQUEST, REQUEST_MAGIC, RESPONSE, RESPONSE_MAGIC,
    SharedResourceBroker, SharedResourceBrokerError, decode_request,
)
from test_shared_resource_store import BUNDLE, RESOURCE, Response, catalog


def eventually(check, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := check():
            return result
        time.sleep(0.01)
    raise AssertionError("Private IPC did not reach the expected state")


def request(record, configuration, *, token=None, platform=1, filename=None, **changes):
    values = dict(magic=REQUEST_MAGIC, schema=1, platform=platform,
        kind=1 if record.kind == "assetbundle" else 2,
        token=token or secrets.token_bytes(16), epoch=configuration["epoch"],
        upload=record.upload_version, generation=record.generation, size=record.size,
        object_name=record.object_name.encode("ascii"),
        filename=filename or record.md5 + (".acb" if record.kind == "resources" else ""),
        digest=bytes.fromhex(record.md5))
    values.update(changes)
    name = values.pop("filename").encode("ascii")
    length = values.pop("length", len(name))
    raw = REQUEST.pack(*[values[key] for key in ("magic", "schema", "platform", "kind", "token",
        "epoch", "upload", "generation", "size", "object_name")], length, values["digest"]) + name
    return values["token"], raw


def send(configuration, token, raw):
    directory = Path(configuration["directory"]) / "req"
    temporary = directory / (".native-" + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    final = directory / (token.hex() + ".req")
    os.rename(temporary, final)
    return final


def receive(configuration, token):
    path = Path(configuration["directory"]) / "rsp" / (token.hex() + ".rsp")
    eventually(path.exists)
    before = path.stat()
    assert stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
    raw = path.read_bytes()
    assert len(raw) >= 104
    result = RESPONSE.unpack_from(raw)
    assert result[0:2] == (RESPONSE_MAGIC, 1) and result[3] == 1
    assert result[4] == token and result[5] == configuration["epoch"]
    assert result[-1] == 0 and len(raw) == 104 + result[-2]
    path.unlink()
    return result, raw[104:].decode("utf-8")


@pytest.fixture
def setup(tmp_path):
    manifest, records, bodies = catalog()
    calls = []
    cache = OctoCache(tmp_path / "cache", fetcher=lambda url, **_: (calls.append(url), Response(bodies[url]))[1])
    store = SharedResourceStore(manifest, cache)
    private = tmp_path / "app-private"
    private.mkdir(mode=0o755)
    broker = SharedResourceBroker(store, private)
    try:
        yield broker, store, cache, records, calls
    finally:
        broker.close(); store.close(); cache.close()
        eventually(lambda: not any(thread.is_alive() for thread in broker._threads))
        try:
            broker.cleanup(quiescent=True)
        except OSError:
            pass


@pytest.mark.parametrize("name,extension,body", [("bundle", "", BUNDLE),
    ("resource", ".acb", RESOURCE), ("resource", ".mp4", RESOURCE)])
def test_real_ipc_prepares_one_verified_file_and_returns_sdk_named_same_inode(setup, name, extension, body):
    broker, store, cache, records, calls = setup
    configuration = broker.configuration()
    record = records[name]
    token, raw = request(record, configuration, filename=record.md5 + extension)
    assert len(raw) == 80 + len(record.md5 + extension)
    assert int.from_bytes(raw[36:40], "little") == record.upload_version
    assert raw[56:62] == record.object_name.encode() and raw[64:80].hex() == record.md5
    request_path = send(configuration, token, raw)
    response, view = receive(configuration, token)
    assert response[2] == READY and not request_path.exists()
    path = Path(view)
    canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
    info = path.stat()
    assert path.name == record.md5 + extension
    assert path.parent.name == ("A" if name == "bundle" else "R") + record.object_name
    assert view.startswith(configuration["directory"] + "/views/")
    assert path.is_symlink() and os.readlink(path) == str(canonical)
    assert path.read_bytes() == body and canonical.read_bytes() == body
    assert info.st_ino == canonical.stat().st_ino and info.st_nlink == 1
    assert response[6].hex() == record.md5
    assert response[7:15] == (record.size, info.st_dev, info.st_ino, info.st_mtime_ns,
        info.st_ctime_ns, info.st_mode, 1, len(view.encode()))
    assert len(calls) == 1 and len(list(cache.root.rglob("*.bin"))) == 1
    assert store.status()["active_leases"] == 0
    eventually(lambda: broker.status()["ready_bytes"] == record.size)
    for child in Path(configuration["directory"]).iterdir():
        assert stat.S_IMODE(child.stat().st_mode) == (0o700 if child.is_dir() else 0o600)
    assert "directory" not in broker.status() and "epoch" not in broker.status()
    broker.close(); store.close()
    assert path.read_bytes() == body


@pytest.mark.parametrize("changes", [{"magic": b"INVALID!"}, {"schema": 2}, {"platform": 0},
    {"kind": 3}, {"epoch": 0}, {"upload": 0}, {"generation": 0}, {"size": 0},
    {"object_name": b"../XYZ"}, {"length": 64}, {"filename": "../payload"},
    {"filename": "0" * 32}, {"filename": "0" * 32 + ".ACB"},
    {"filename": "0" * 32 + ".tar.gz"}, {"token": bytes(16)}])
def test_malformed_records_are_denied_before_route_or_cache_io(setup, monkeypatch, changes):
    broker, store, _, records, calls = setup
    configuration = broker.configuration()
    token, raw = request(records["bundle"], configuration, **changes)
    monkeypatch.setattr(store, "_record", lambda *_args, **_kwargs: pytest.fail("Invalid wire resolved manifest"))
    with pytest.raises(ValueError):
        decode_request(raw, epoch=configuration["epoch"], token=token)
    path = send(configuration, token, raw)
    eventually(lambda: not path.exists())
    assert calls == [] and broker.status()["received_requests"] == 0
    assert broker.status()["rejected_requests"] == 1


@pytest.mark.parametrize("changes,status", [({"size": 1}, NOT_FOUND),
    ({"generation": 12}, NOT_FOUND), ({"platform": 2}, UNSUPPORTED),
    ({"filename": "0" * 32, "digest": bytes(16)}, NOT_FOUND)])
def test_valid_but_stale_identity_or_other_platform_fails_without_download(setup, changes, status):
    broker, _, _, records, calls = setup
    configuration = broker.configuration()
    token, raw = request(records["bundle"], configuration, **changes)
    send(configuration, token, raw)
    response, path = receive(configuration, token)
    assert response[2] == status and path == "" and calls == []
    assert response[6:14] == (bytes(16), 0, 0, 0, 0, 0, 0, 0)


def test_repeat_objects_share_original_bytes_and_media_extension_views(setup):
    broker, _, cache, records, calls = setup
    configuration = broker.configuration()
    record = records["resource"]
    seen = []
    for extension in (".acb", ".mp4", ".acb"):
        token, raw = request(record, configuration, filename=record.md5 + extension)
        send(configuration, token, raw)
        response, path = receive(configuration, token)
        assert response[2] == READY
        seen.append(Path(path).stat().st_ino)
    assert len(set(seen)) == len(calls) == 1
    assert len(list(cache.root.rglob("*.bin"))) == 1


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "writable", "fifo", "large"])
def test_untrusted_request_entries_are_not_read_or_removed(setup, tmp_path, attack):
    broker, _, _, records, calls = setup
    configuration = broker.configuration()
    token, raw = request(records["bundle"], configuration)
    target = tmp_path / "foreign"
    target.write_bytes(raw); target.chmod(0o600)
    path = Path(configuration["directory"]) / "req" / (token.hex() + ".req")
    if attack == "symlink": path.symlink_to(target)
    elif attack == "hardlink": os.link(target, path)
    elif attack == "fifo": os.mkfifo(path, 0o600)
    else:
        path.write_bytes(raw if attack == "writable" else raw * 100)
        path.chmod(0o644 if attack == "writable" else 0o600)
    time.sleep(0.075)
    assert path.lstat() and calls == [] and target.read_bytes() == raw
    assert broker.status()["received_requests"] == 0


def test_foreign_response_is_never_overwritten_or_cleaned(setup):
    broker, _, _, records, _ = setup
    configuration = broker.configuration()
    token, raw = request(records["bundle"], configuration)
    foreign = Path(configuration["directory"]) / "rsp" / (token.hex() + ".rsp")
    foreign.write_bytes(b"foreign response"); foreign.chmod(0o600)
    send(configuration, token, raw)
    eventually(lambda: broker.status()["failed_requests"] == 1)
    assert foreign.read_bytes() == b"foreign response"
    broker.close()
    eventually(lambda: not any(thread.is_alive() for thread in broker._threads))
    with pytest.raises(SharedResourceBrokerError):
        broker.cleanup(quiescent=True)
    assert foreign.read_bytes() == b"foreign response"


def test_only_abandoned_response_metadata_expires_after_native_timeout_not_sdk_views(setup, tmp_path, monkeypatch):
    from idoly_local import shared_resource_broker as module
    _first, store, cache, records, calls = setup
    broker = SharedResourceBroker(store, tmp_path, max_responses=1)
    configuration = broker.configuration()
    record = records["resource"]
    try:
        first, raw = request(record, configuration)
        send(configuration, first, raw)
        response_file = Path(configuration["directory"]) / "rsp" / (first.hex() + ".rsp")
        eventually(lambda: broker.status()["ready_requests"] == 1)
        raw_reply = response_file.read_bytes()
        view = Path(raw_reply[104:].decode())
        second, raw = request(record, configuration, filename=record.md5 + ".mp4")
        queued = send(configuration, second, raw)
        time.sleep(0.075)
        assert queued.exists() and broker.status()["received_requests"] == 1
        baseline = module._monotonic()
        monkeypatch.setattr(module, "_monotonic", lambda: baseline + 601)
        eventually(lambda: not response_file.exists())
        response, second_view = receive(configuration, second)
        assert response[2] == READY and view.read_bytes() == Path(second_view).read_bytes() == RESOURCE
        assert view.stat().st_ino == Path(second_view).stat().st_ino
        assert len(calls) == 1 and len(list(cache.root.rglob("*.bin"))) == 1
    finally:
        broker.close()
        eventually(lambda: not any(thread.is_alive() for thread in broker._threads))
        broker.cleanup(quiescent=True)

def test_session_restart_rejects_old_epoch_and_uses_new_private_directory(setup, tmp_path):
    first, store, _, records, calls = setup
    old = first.configuration()
    second = SharedResourceBroker(store, tmp_path)
    try:
        configuration = second.configuration()
        assert configuration["directory"] != old["directory"] and configuration["epoch"] != old["epoch"]
        token, raw = request(records["bundle"], old)
        path = send(configuration, token, raw)
        eventually(lambda: not path.exists())
        assert calls == [] and second.status()["rejected_requests"] == 1
    finally:
        second.close()
        eventually(lambda: not any(thread.is_alive() for thread in second._threads))
        second.cleanup(quiescent=True)


def test_bounded_worker_queue_and_stop_refuse_late_handoff_without_deleting_payload(tmp_path):
    manifest, records, bodies = catalog()
    entered, finish = threading.Event(), threading.Event()
    calls = []
    def fetch(url, **_):
        calls.append(url); entered.set()
        assert finish.wait(2)
        return Response(bodies[url])
    cache = OctoCache(tmp_path / "cache", fetcher=fetch)
    store = SharedResourceStore(manifest, cache)
    broker = SharedResourceBroker(store, tmp_path, workers=1, max_pending=2)
    configuration = broker.configuration()
    requests = [request(records["bundle"], configuration) for _ in range(5)]
    try:
        for token, raw in requests:
            send(configuration, token, raw)
        assert entered.wait(1)
        eventually(lambda: broker.status()["pending_requests"] == 2)
        assert broker.status()["received_requests"] == 2
        start = time.monotonic(); broker.close()
        assert time.monotonic() - start < 1.1
        finish.set()
        eventually(lambda: not any(thread.is_alive() for thread in broker._threads))
        eventually(lambda: not broker._fds)
        assert not list((Path(configuration["directory"]) / "rsp").iterdir())
        assert len(calls) == 1
        canonical = cache.root / records["bundle"].cache_key[:2] / (records["bundle"].cache_key + ".bin")
        assert canonical.read_bytes() == BUNDLE
        with pytest.raises(SharedResourceBrokerError): broker.configuration()
    finally:
        finish.set(); broker.close(); store.close(); cache.close()


def test_quiescent_cleanup_requires_explicit_boolean_and_never_removes_cache(setup):
    broker, _, cache, records, _ = setup
    configuration = broker.configuration()
    token, raw = request(records["bundle"], configuration)
    send(configuration, token, raw)
    response, view = receive(configuration, token)
    assert response[2] == READY
    with pytest.raises(SharedResourceBrokerError): broker.cleanup(quiescent=1)
    assert Path(view).is_symlink()
    broker.close()
    eventually(lambda: not any(thread.is_alive() for thread in broker._threads))
    broker.cleanup(quiescent=True)
    assert not Path(configuration["directory"]).exists()
    assert len(list(cache.root.rglob("*.bin"))) == 1


def test_native_descriptor_is_private_and_runtime_status_has_only_measurements(setup):
    from idoly_local.app_runtime import Runtime
    broker, store, *_ = setup
    runtime = Runtime("sandbox")
    runtime._shared_resources, runtime._shared_resource_store = broker, store
    runtime._running = True
    assert runtime.shared_resources_configuration() == broker.configuration()
    observed = runtime.diagnostics_snapshot()["runtime"]["shared_resources"]
    assert observed == broker.status()
    assert "directory" not in observed and "epoch" not in observed
    runtime.stop()
    assert runtime.shared_resources_configuration() == {"schema": 1, "available": False}


def test_liveness_marker_has_exact_native_wire_and_disappears_on_stop_without_removing_views(setup):
    broker, store, _, records, _ = setup
    configuration = broker.configuration()
    active = Path(configuration["directory"]) / "active"
    assert active.read_bytes() == b"IDRSACT1" + configuration["epoch"].to_bytes(8, "little")
    info = active.stat()
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 1 and info.st_uid == os.geteuid()
    token, raw = request(records["resource"], configuration)
    send(configuration, token, raw)
    response, view = receive(configuration, token)
    assert response[2] == READY
    broker.close()
    assert not active.exists() and Path(view).read_bytes() == RESOURCE
    assert store.status()["closed"] is False


def test_fatal_scanner_failure_retires_only_owned_liveness_marker(setup):
    broker, _, _, _, _ = setup
    configuration = broker.configuration()
    root = Path(configuration["directory"])
    (root / "req").chmod(0o755)
    eventually(lambda: not broker.status()["available"])
    eventually(lambda: not (root / "active").exists())
    assert (root / "views").is_dir()


def test_foreign_replacement_liveness_marker_is_never_deleted(setup, tmp_path):
    broker, _, _, _, _ = setup
    configuration = broker.configuration()
    active = Path(configuration["directory"]) / "active"
    foreign = tmp_path / "foreign-active"
    foreign.write_bytes(b"foreign marker")
    foreign.chmod(0o600)
    os.replace(foreign, active)
    eventually(lambda: not broker.status()["available"])
    broker.close()
    assert active.read_bytes() == b"foreign marker"



@pytest.mark.parametrize("unified", [False, True])
def test_real_runtime_enables_private_broker_only_for_unified_native_and_shares_gateway_cache(tmp_path, monkeypatch, unified):
    import hashlib
    import json
    import sys
    from types import SimpleNamespace
    from idoly_local import app_runtime, love
    from idoly_local.octo_manifest import Database
    from idoly_local.profiles import new_profile
    from idoly_local.state import State
    from test_app_runtime import _Application, _write_bundle
    from test_octo_runtime import PAYLOAD, write_archive
    from test_octo_app_runtime import request as http_request, ResourceResponse

    schema = _write_bundle(tmp_path)
    state = State(tmp_path / "state.db")
    new_profile(state, schema, "sandbox", "Preserved manager")
    before = state.snapshot("sandbox")
    monkeypatch.setitem(sys.modules, "idoly_local.application", SimpleNamespace(Application=_Application))
    monkeypatch.setitem(sys.modules, "idoly_local.gameplay", SimpleNamespace(
        seed_starter_profile=lambda *_: pytest.fail("Existing account must be retained"),
        repair_starter_roster=lambda *_: False, repair_starter_home_positions=lambda *_: False,
        repair_starter_inventory=lambda *_: False, repair_starter_card_level_mission=lambda *_: False))
    settings, raw = write_archive(tmp_path / "public-octo")
    db = Database.FromString(raw)
    db.assetBundleList[0].objectName = "ABC123"
    db.resourceList[0].objectName = "DEF456"
    raw = db.SerializeToString()
    settings["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    (tmp_path / "public-octo/manifest.pb").write_bytes(raw)
    (tmp_path / "public-octo/settings.json").write_text(json.dumps(settings))
    calls = []
    def fetch(url, **_):
        calls.append(url)
        return ResourceResponse(url)
    runtime = app_runtime.start(tmp_path, grpc_port=0, asset_port=0,
        resource_fetcher=fetch, shared_resource_dir=tmp_path if unified else None)
    try:
        configuration = runtime.shared_resources_configuration()
        assert configuration["available"] is unified
        observed = runtime.diagnostics_snapshot()
        assert "directory" not in observed["runtime"]["shared_resources"]
        assert calls == []  # Startup never preloads the catalog.
        if unified:
            record = runtime._shared_resource_store._manifest.lookup_object("/octo/202050/assetbundle/ABC123/12345")
            token, raw = request(record, configuration)
            send(configuration, token, raw)
            response, path = receive(configuration, token)
            assert response[2] == READY and Path(path).read_bytes() == PAYLOAD
            assert runtime.status()["resource_transfer"]["session_served_bytes"] == 0
            code, _, body = http_request(runtime.status()["asset_url"], "/octo/202050/assetbundle/ABC123/12345")
            assert code == 200 and body == PAYLOAD and len(calls) == 1
            assert len(list((tmp_path / "octo-cache").rglob("*.bin"))) == 1
        assert state.snapshot("sandbox") == before
    finally:
        runtime.stop()
    assert runtime.shared_resources_configuration()["available"] is False
    if unified:
        broker = runtime._shared_resources
        eventually(lambda: not broker._fds)
        assert Path(path).read_bytes() == PAYLOAD
        broker.cleanup(quiescent=True)


def test_response_fsync_failure_removes_only_the_owned_partial_temporary(setup, monkeypatch):
    from idoly_local import shared_resource_broker as module
    broker, _, _, records, _ = setup
    configuration = broker.configuration()
    monkeypatch.setattr(module.os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("synthetic fsync failure")))
    token, raw = request(records["bundle"], configuration)
    send(configuration, token, raw)
    eventually(lambda: broker.status()["failed_requests"] == 1)
    assert list((Path(configuration["directory"]) / "rsp").iterdir()) == []


@pytest.mark.parametrize("platform,number", [("android", 1), ("ios", 2)])
def test_translated_sdk_alias_keeps_requested_bucket_and_canonical_receipt(tmp_path, platform, number):
    manifest, records, bodies = catalog(platform, translated=True)
    cache = OctoCache(tmp_path / "cache", local_source=lambda record: Response(bodies[record.upstream_url]),
        fetcher=lambda *_args, **_kwargs: pytest.fail("Prepared translation must not fetch CDN"))
    store = SharedResourceStore(manifest, cache)
    broker = SharedResourceBroker(store, tmp_path)
    configuration = broker.configuration()
    try:
        record = records["bundle"]
        token, raw = request(record, configuration, platform=number, object_name=b"ABC123")
        send(configuration, token, raw)
        response, path = receive(configuration, token)
        assert response[2] == READY
        view = Path(path)
        canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
        assert view.parent.name == "AABC123" and record.object_name.startswith("local_ko_")
        assert view.stat().st_ino == canonical.stat().st_ino and view.read_bytes() == BUNDLE
    finally:
        broker.close(); store.close(); cache.close()
        eventually(lambda: not any(thread.is_alive() for thread in broker._threads))
        broker.cleanup(quiescent=True)


@pytest.fixture(scope="module")
def native_hook_driver(tmp_path_factory):
    import shutil
    import subprocess
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("A host C++ compiler is required for the real native IPC contract")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("native-shared-cache") / "shared-cache-host-test"
    source = root / "client-presentation/native/tests/shared_cache_test.cpp"
    subprocess.run([compiler, "-std=c++17", "-pthread", "-Wall", "-Wextra", "-Werror",
        str(source), "-o", str(binary)], check=True, capture_output=True, timeout=60)
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)
    return binary


@pytest.mark.parametrize("name,extension,body", [("bundle", "", BUNDLE),
    ("resource", ".acb", RESOURCE), ("resource", ".mp4", RESOURCE)])
def test_actual_cpp_pre_download_worker_and_main_thread_replay_consume_real_python_broker(
        setup, native_hook_driver, name, extension, body):
    import json
    import subprocess
    broker, store, cache, records, calls = setup
    configuration = broker.configuration()
    record = records[name]
    before = set(cache.root.rglob("*"))
    completed = subprocess.run([str(native_hook_driver), "--ipc", configuration["directory"],
        str(configuration["epoch"]), "1" if name == "bundle" else "2",
        str(record.upload_version), str(record.generation), str(record.size), record.object_name,
        record.md5, record.md5 + extension], check=True, capture_output=True, text=True, timeout=20)
    observed = json.loads(completed.stdout)
    assert observed["status"] == "ready" and observed["replayed"] == 1 and observed["handles_released"] == 3
    view = Path(observed["path"])
    canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
    assert view.is_symlink() and view.name == record.md5 + extension
    assert view.read_bytes() == canonical.read_bytes() == body
    assert view.stat().st_dev == observed["device"] == canonical.stat().st_dev
    assert view.stat().st_ino == observed["inode"] == canonical.stat().st_ino
    assert view.stat().st_nlink == 1
    assert len(calls) == 1 and len(list(cache.root.rglob("*.bin"))) == 1
    assert before == set()  # No pre-seeded SDK or cache files.
    assert broker.status()["ready_requests"] == 1 and store.status()["active_leases"] == 0
    assert list((Path(configuration["directory"]) / "req").iterdir()) == []
    assert list((Path(configuration["directory"]) / "rsp").iterdir()) == []
