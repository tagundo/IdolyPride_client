"""Real private MV-audio IPC over manifest-selected, MD5-verified cache files."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import struct
import threading
import time
from types import SimpleNamespace

import pytest

from idoly_local import mp4_audio_broker as module
from idoly_local.mp4_audio_broker import (
    ACTIVE, ACTIVE_MAGIC, REQUEST, REQUEST_MAGIC, RESPONSE, RESPONSE_MAGIC,
    READY, NOT_FOUND, FAILED, UNSUPPORTED, AudioBrokerError, MP4AudioBroker, decode_request,
)
from idoly_local.mp4_audio_bundle import _serialized, _unpack_fs
from idoly_local.octo_cache import OctoCache
from idoly_local.octo_manifest import Database, OctoManifest
from idoly_local.shared_resource_store import SharedResourceStore
from test_mp4_audio_bundle import (
    NAME, CHEERS, RESOURCE, SAMPLES, CHEER_SAMPLE_ROWS, CHEER_RESOURCE_PINS,
    bundle, masked, cheer_sample,
)
from test_shared_resource_store import Response


def test_quiescent_native_bundle_retirement_releases_owned_count_and_byte_quota(tmp_path):
    store, cache, _, calls, _ = make_store(tmp_path)
    broker = MP4AudioBroker(store, tmp_path, max_prepared=1)
    try:
        configuration = broker.configuration()
        first, raw = request(configuration); send(configuration, first, raw)
        status, prepared = receive(configuration, first)
        assert status == READY
        eventually(lambda: broker.status()["prepared_files"] == 1)
        assert broker.status()["prepared_bytes"] == prepared.stat().st_size
        # The native owner asserts Unity's original unload/async quiescence
        # before retiring this exact inode. The broker never deletes it.
        prepared.unlink()
        eventually(lambda: broker.status()["prepared_files"] == 0)
        assert broker.status()["prepared_bytes"] == 0
        second, raw = request(configuration); send(configuration, second, raw)
        status, second_path = receive(configuration, second)
        assert status == READY and second_path.exists() and len(calls) == 1
    finally:
        broker.close(); store.close(); cache.close(); eventually(lambda: not broker._fds)


def test_changed_owned_bundle_is_not_forgotten_or_deleted_as_quiescent_retirement(setup, tmp_path):
    broker, _, _, _, _, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration); send(configuration, request_id, raw)
    status, prepared = receive(configuration, request_id)
    assert status == READY
    eventually(lambda: broker.status()["prepared_files"] == 1)
    saved_count, saved_bytes = broker.status()["prepared_files"], broker.status()["prepared_bytes"]
    foreign = tmp_path / "unrelated.bundle"
    foreign.write_bytes(b"unrelated file with a reused prepared name"); foreign.chmod(0o400)
    os.replace(foreign, prepared)
    eventually(lambda: not broker.status()["available"])
    assert broker.status()["prepared_files"] == saved_count and broker.status()["prepared_bytes"] == saved_bytes
    assert prepared.read_bytes() == b"unrelated file with a reused prepared name"
    assert not (Path(configuration["directory"]) / "active").exists()



def test_unexpected_preparation_failure_does_not_kill_the_bounded_worker(setup, monkeypatch):
    broker, _, _, _, calls, _ = setup
    configuration = broker.configuration()
    original = module.prepare_audio_bundle
    attempts = []
    def once(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("synthetic decoder preparation failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "prepare_audio_bundle", once)
    first, raw = request(configuration); send(configuration, first, raw)
    status, prepared = receive(configuration, first)
    assert status == FAILED and not prepared.exists() and broker._worker_thread.is_alive()
    second, raw = request(configuration); send(configuration, second, raw)
    status, prepared = receive(configuration, second)
    assert status == READY and prepared.exists() and len(calls) == 1



def test_failed_cache_integrity_never_publishes_a_private_clone(tmp_path):
    original = masked(bundle(), NAME)
    def corrupted(_url, **_):
        return Response(b"x" * len(original))
    store, cache, _record, _, _ = make_store(tmp_path, original, fetcher=corrupted)
    broker = MP4AudioBroker(store, tmp_path)
    try:
        configuration = broker.configuration()
        request_id, raw = request(configuration); send(configuration, request_id, raw)
        status, prepared = receive(configuration, request_id)
        assert status == FAILED and not prepared.exists()
        assert not list(cache.root.rglob("*.bin")) and not list(prepared.parent.iterdir())
    finally:
        broker.close(); store.close(); cache.close()
        eventually(lambda: not broker._fds)


def test_ambiguous_manifest_logical_name_is_not_guessed(tmp_path):
    from types import MappingProxyType
    store, cache, record, calls, _ = make_store(tmp_path)
    alternate = replace(record, object_name="XYZ789")
    # Simulate a future validated catalog with a colliding logical name. The
    # broker must not choose a platform object by list/dictionary order.
    store._records = MappingProxyType({record.identity: record, alternate.identity: alternate})
    broker = MP4AudioBroker(store, tmp_path)
    try:
        configuration = broker.configuration()
        request_id, raw = request(configuration); send(configuration, request_id, raw)
        status, prepared = receive(configuration, request_id)
        assert status == NOT_FOUND and not prepared.exists() and calls == []
    finally:
        broker.close(); store.close(); cache.close()
        eventually(lambda: not broker._fds)


def test_closed_store_reports_cancellation_without_touching_cache(setup):
    broker, store, _, _, calls, _ = setup
    configuration = broker.configuration()
    store.close()
    request_id, raw = request(configuration); send(configuration, request_id, raw)
    status, prepared = receive(configuration, request_id)
    assert status == module.CANCELLED and not prepared.exists() and calls == []



def eventually(check, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if value := check():
            return value
        time.sleep(0.01)
    raise AssertionError("Private audio preparation did not complete")


def make_store(root, raw=None, *, platform="android", fetcher=None, row=None):
    raw = masked(bundle(), NAME) if raw is None else raw
    row = row or dict(name=NAME, object="ABC123", upload=202050 if platform == "android" else 102050,
        generation=11, size=len(raw), md5=hashlib.md5(raw, usedforsecurity=False).hexdigest())
    database = Database(revision=7,
        urlFormat="https://d2ilil7yh5oi1v.cloudfront.net/solis-{v}-{type}/{o}?generation={g}&alt=media")
    database.assetBundleList.add(id=1, name=row["name"], objectName=row["object"], size=row["size"],
        md5=row["md5"], uploadVersionId=row["upload"], generation=row["generation"], state=3)
    database.resourceList.add(id=1, name="synthetic-unused-resource", objectName="DEF456", size=1,
        md5=hashlib.md5(b"r", usedforsecurity=False).hexdigest(),
        uploadVersionId=row["upload"], generation=12, state=3)
    manifest = OctoManifest(database.SerializeToString(), aes_key=b"k"*32, client_key="synthetic",
        base_url="http://127.0.0.1:8080", aes_cbc=lambda _e, _k, _iv, data: data,
        application_version=205051 if platform == "android" else 105051)
    calls = []
    def default_fetch(url, **_):
        calls.append(url)
        return Response(raw)
    cache = OctoCache(root / "cache", fetcher=fetcher or default_fetch)
    store = SharedResourceStore(manifest, cache)
    return store, cache, next(iter(manifest.objects.values())), calls, raw


def request(configuration, *, request_id=None, name=NAME, **changes):
    request_id = secrets.token_bytes(16) if request_id is None else request_id
    values = dict(magic=REQUEST_MAGIC, schema=1, platform=1, reserved=0,
        epoch=configuration["epoch"], capability=bytes.fromhex(configuration["capability"]),
        request_id=request_id, channels=2, reserved2=0, rate=48000, samples=5568000)
    values.update(changes)
    name = name.encode("ascii")
    length = values.pop("length", len(name))
    raw = REQUEST.pack(*[values[key] for key in ("magic", "schema", "platform", "reserved",
        "epoch", "capability", "request_id")], length,
        *[values[key] for key in ("channels", "reserved2", "rate", "samples")]) + name
    return request_id, raw


def send(configuration, request_id, raw):
    root = Path(configuration["directory"]) / "req"
    temporary = root / (".native-" + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    target = root / (request_id.hex() + ".req")
    os.rename(temporary, target)
    return target


def receive(configuration, request_id):
    root = Path(configuration["directory"])
    target = root / "rsp" / (request_id.hex() + ".rsp")
    eventually(target.exists)
    info = target.stat()
    assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
    raw = target.read_bytes()
    assert len(raw) == 52
    values = RESPONSE.unpack(raw)
    assert values[0:2] == (RESPONSE_MAGIC, 1) and values[3] == 0
    assert values[4] == configuration["epoch"]
    assert values[5] == bytes.fromhex(configuration["capability"]) and values[6] == request_id
    target.unlink()
    return values[2], root / "prepared" / (request_id.hex() + ".bundle")


@pytest.fixture
def setup(tmp_path):
    store, cache, record, calls, raw = make_store(tmp_path)
    broker = MP4AudioBroker(store, tmp_path)
    try:
        yield broker, store, cache, record, calls, raw
    finally:
        broker.close(); store.close(); cache.close()
        eventually(lambda: not broker._fds)


def test_wire_and_real_cache_to_immutable_private_clone_preserve_game_source(setup):
    broker, store, cache, record, calls, original = setup
    configuration = broker.configuration()
    root = Path(configuration["directory"])
    assert (root / "active").read_bytes() == ACTIVE.pack(ACTIVE_MAGIC, configuration["epoch"])
    assert stat.S_IMODE((root / "active").stat().st_mode) == 0o600
    assert len(bytes.fromhex(configuration["capability"])) == 16
    request_id, raw = request(configuration)
    assert len(raw) == 68 + len(NAME)
    assert raw[:8] == b"IDMPAUD1" and int.from_bytes(raw[12:20], "little") == configuration["epoch"]
    assert raw[20:36] == bytes.fromhex(configuration["capability"]) and raw[36:52] == request_id
    assert raw[54] == 2 and int.from_bytes(raw[56:60], "little") == 48000
    target = send(configuration, request_id, raw)
    status, prepared = receive(configuration, request_id)
    assert status == READY and not target.exists() and prepared.name == request_id.hex() + ".bundle"
    info = prepared.stat()
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o400 and info.st_nlink == 1
    assert info.st_uid == os.geteuid()
    transformed = _unpack_fs(prepared.read_bytes())
    # Private bundle and CAB names are fresh; original lookup key is retained.
    private_name = transformed.entries[0].data
    offset = int.from_bytes(private_name[32:40], "big")
    name_size = int.from_bytes(private_name[offset:offset+4], "little")
    bundle_name = private_name[offset+4:offset+4+name_size].decode()
    values, _ = _serialized(private_name, NAME, bundle_name=bundle_name)
    assert values[83][0]["m_LoadType"] == 0 and values[83][0]["m_PreloadAudioData"] == 1
    assert values[83][0]["m_LoadInBackground"] == 0 and values[83][0]["m_Name"] == NAME
    assert values[142][0]["m_Name"] == bundle_name != NAME
    assert transformed.entries[1].data == RESOURCE
    canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
    assert canonical.read_bytes() == original and canonical.stat().st_ino != info.st_ino
    assert len(calls) == 1 and store.status()["active_leases"] == 0
    eventually(lambda: broker.status()["ready_requests"] == 1)
    observed = broker.status()
    assert observed["prepared_files"] == 1 and observed["prepared_bytes"] == prepared.stat().st_size
    assert "directory" not in observed and "capability" not in observed and "epoch" not in observed
    broker.close()
    assert not (root / "active").exists() and prepared.read_bytes().startswith(b"UnityFS\0")
    assert canonical.read_bytes() == original and store.status()["closed"] is False


@pytest.mark.parametrize("changes", [{"magic": b"INVALID!"}, {"schema": 2}, {"platform": 0},
    {"reserved": 1}, {"reserved2": 1}, {"epoch": 0}, {"capability": bytes(16)},
    {"channels": 0}, {"channels": 3}, {"rate": 32000}, {"samples": 0},
    {"samples": 48000*900+1}, {"length": 192}])
def test_malformed_capability_shape_or_epoch_rejected_before_manifest_io(setup, monkeypatch, changes):
    broker, store, _, _, calls, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration, **changes)
    monkeypatch.setattr(store, "prepare", lambda *_args, **_kwargs: pytest.fail("Malformed IPC must not access cache"))
    with pytest.raises(AudioBrokerError):
        decode_request(raw, epoch=configuration["epoch"],
            capability=bytes.fromhex(configuration["capability"]), request_id=request_id)
    target = send(configuration, request_id, raw)
    eventually(lambda: not target.exists())
    assert broker.status()["received_requests"] == 0 and calls == []
    assert broker.status()["rejected_requests"] == 1


@pytest.mark.parametrize("name", ["../sud_music_x", "mdl_other", "sud_music_X", "sud_music_x/../../other",
    "sud_se_live_cheers-mix-r", "sud_se_live_cheers-clap-r", "sud_se_live_cheers-mix",
    "sud_se_live_cheers-mix-l/../other", "../sud_se_live_cheers-clap-l",
    "sud_se_live_cheers-clap-l-extra", "sud_se_live_cheers-MIX-l", "sud_se_other",
    "sud_se_live_cheers-mix-l\n", "sud_se_live_cheers-clap-l\0"])
def test_request_accepts_no_paths_or_unaudited_effect_names(setup, name):
    broker, _, _, _, calls, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration, name=name)
    target = send(configuration, request_id, raw)
    eventually(lambda: not target.exists())
    assert calls == [] and broker.status()["rejected_requests"] == 1


@pytest.mark.parametrize("platform,number", [("android", 1), ("ios", 2)])
@pytest.mark.parametrize("name", CHEERS)
def test_exact_audited_cheers_private_ipc_preserves_source_and_capability(tmp_path, platform, number, name):
    raw = masked(bundle(name, platform=13 if number == 1 else 9,
        audio_values={"load": 0, "compression": 0}), name)
    row = dict(name=name, object="ABC123", upload=202050 if number == 1 else 102050,
        generation=11, size=len(raw), md5=hashlib.md5(raw, usedforsecurity=False).hexdigest())
    store, cache, record, calls, original = make_store(tmp_path, raw, platform=platform, row=row)
    broker = MP4AudioBroker(store, tmp_path)
    try:
        configuration = broker.configuration()
        request_id, packet = request(configuration, name=name, platform=number)
        decoded = decode_request(packet, epoch=configuration["epoch"],
            capability=bytes.fromhex(configuration["capability"]), request_id=request_id)
        assert decoded.clip_name == name and decoded.platform == platform
        send(configuration, request_id, packet)
        status, prepared = receive(configuration, request_id)
        assert status == READY and stat.S_IMODE(prepared.stat().st_mode) == 0o400
        private = _unpack_fs(prepared.read_bytes())
        assert private.entries[1].data == RESOURCE
        assert prepared.stat().st_uid == os.geteuid() and prepared.stat().st_nlink == 1
        canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
        assert canonical.read_bytes() == original and canonical.stat().st_ino != prepared.stat().st_ino
        assert len(calls) == 1 and store.status()["active_leases"] == 0
    finally:
        broker.close(); store.close(); cache.close(); eventually(lambda: not broker._fds)


@pytest.mark.parametrize("name", CHEERS)
@pytest.mark.parametrize("failure", ["hash", "size", "bundle_platform", "request_platform", "capability"])
def test_cheers_never_bypasses_manifest_platform_or_session_validation(tmp_path, name, failure):
    raw = masked(bundle(name, platform=9 if failure == "bundle_platform" else 13,
        audio_values={"load": 0, "compression": 0}), name)
    row = dict(name=name, object="ABC123", upload=202050, generation=11,
        size=len(raw) + (failure == "size"),
        md5="0" * 32 if failure == "hash" else hashlib.md5(raw, usedforsecurity=False).hexdigest())
    store, cache, _record, calls, _original = make_store(tmp_path, raw, row=row)
    broker = MP4AudioBroker(store, tmp_path)
    try:
        configuration = broker.configuration()
        options = {"platform": 2} if failure == "request_platform" else {}
        if failure == "capability":
            options["capability"] = bytes(16)
        request_id, packet = request(configuration, name=name, **options)
        target = send(configuration, request_id, packet)
        if failure == "capability":
            eventually(lambda: not target.exists())
            assert broker.status()["rejected_requests"] == 1 and calls == []
        else:
            status, prepared = receive(configuration, request_id)
            assert status == (UNSUPPORTED if failure == "request_platform" else FAILED)
            assert not prepared.exists()
            assert len(calls) == (0 if failure == "request_platform" else 1)
        assert not list((Path(configuration["directory"]) / "prepared").iterdir())
    finally:
        broker.close(); store.close(); cache.close(); eventually(lambda: not broker._fds)


def test_request_id_in_record_must_equal_private_filename(setup):
    broker, _, _, _, calls, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration)
    target = send(configuration, secrets.token_bytes(16), raw)
    eventually(lambda: not target.exists())
    assert calls == [] and broker.status()["rejected_requests"] == 1


@pytest.mark.parametrize("options,status,downloads", [
    ({"name": "sud_music_missing"}, NOT_FOUND, 0),
    ({"platform": 2}, UNSUPPORTED, 0), ({"channels": 1}, UNSUPPORTED, 1),
    ({"rate": 44100}, UNSUPPORTED, 1)])
def test_known_wire_reports_missing_or_incompatible_source_without_publishing(setup, options, status, downloads):
    broker, _, _, _, calls, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration, **options)
    send(configuration, request_id, raw)
    actual, path = receive(configuration, request_id)
    assert actual == status and not path.exists() and len(calls) == downloads


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "writable", "fifo", "large"])
def test_foreign_request_entries_are_not_read_or_removed(setup, tmp_path, attack):
    broker, _, _, _, calls, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration)
    other = tmp_path / "foreign"; other.write_bytes(raw); other.chmod(0o600)
    target = Path(configuration["directory"]) / "req" / (request_id.hex() + ".req")
    if attack == "symlink": target.symlink_to(other)
    elif attack == "hardlink": os.link(other, target)
    elif attack == "fifo": os.mkfifo(target, 0o600)
    else:
        target.write_bytes(raw if attack == "writable" else raw * 100)
        target.chmod(0o644 if attack == "writable" else 0o600)
    time.sleep(0.08)
    assert target.lstat() and other.read_bytes() == raw and calls == []


def test_replay_never_overwrites_an_immutable_bundle(setup):
    broker, _, _, _, calls, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration)
    send(configuration, request_id, raw)
    status, prepared = receive(configuration, request_id)
    assert status == READY
    before, stamp = prepared.read_bytes(), prepared.stat().st_ino
    replay = send(configuration, request_id, raw)
    eventually(lambda: not replay.exists())
    assert broker.status()["rejected_requests"] == 1
    assert prepared.read_bytes() == before and prepared.stat().st_ino == stamp and len(calls) == 1


@pytest.mark.parametrize("limit", ["count", "bytes", "disk"])
def test_prepared_disk_limits_fail_closed_preserving_every_advertised_path(tmp_path, monkeypatch, limit):
    store, cache, _, calls, original = make_store(tmp_path)
    options = {"max_prepared": 1} if limit == "count" else {"max_prepared_bytes": 1} if limit == "bytes" else {}
    broker = MP4AudioBroker(store, tmp_path, **options)
    try:
        configuration = broker.configuration()
        if limit == "disk":
            monkeypatch.setattr(module.os, "statvfs", lambda *_: SimpleNamespace(f_bavail=0, f_frsize=4096))
        first, raw = request(configuration)
        send(configuration, first, raw)
        status, prepared = receive(configuration, first)
        if limit == "count":
            assert status == READY
            before = prepared.read_bytes()
            second, raw = request(configuration); send(configuration, second, raw)
            status, second_path = receive(configuration, second)
            assert status == FAILED and not second_path.exists() and prepared.read_bytes() == before
        else:
            assert status == FAILED and not prepared.exists()
        assert len(calls) == 1
    finally:
        broker.close(); store.close(); cache.close()
        eventually(lambda: not broker._fds)


def test_failed_private_write_cleans_only_owned_partial_and_returns_failed(setup, monkeypatch):
    broker, store, _, record, _, _ = setup
    configuration = broker.configuration()
    store.prepare(f"/octo/{record.upload_version}/assetbundle/{record.object_name}/{record.generation}")
    original = module.os.fsync
    def fail_payload(descriptor):
        if stat.S_IMODE(os.fstat(descriptor).st_mode) == 0o400:
            raise OSError("synthetic private payload fsync failure")
        return original(descriptor)
    monkeypatch.setattr(module.os, "fsync", fail_payload)
    request_id, raw = request(configuration); send(configuration, request_id, raw)
    status, prepared = receive(configuration, request_id)
    assert status == FAILED and not prepared.exists()
    assert list(prepared.parent.iterdir()) == []


def test_foreign_prepared_path_is_never_replaced(setup):
    broker, _, _, _, _, _ = setup
    configuration = broker.configuration()
    request_id, raw = request(configuration)
    path = Path(configuration["directory"]) / "prepared" / (request_id.hex() + ".bundle")
    path.write_bytes(b"foreign private bundle"); path.chmod(0o400)
    send(configuration, request_id, raw)
    status, _ = receive(configuration, request_id)
    assert status == FAILED and path.read_bytes() == b"foreign private bundle"


def test_stop_during_shared_fill_cancels_queued_handoffs_and_releases_descriptors(tmp_path):
    entered, finish = threading.Event(), threading.Event()
    raw = masked(bundle(), NAME)
    def fetch(_url, **_):
        entered.set(); assert finish.wait(3); return Response(raw)
    store, cache, record, _, _ = make_store(tmp_path, raw, fetcher=fetch)
    broker = MP4AudioBroker(store, tmp_path, max_pending=2)
    configuration = broker.configuration()
    try:
        for _ in range(5):
            request_id, packet = request(configuration); send(configuration, request_id, packet)
        assert entered.wait(1)
        eventually(lambda: broker.status()["pending_requests"] == 2)
        before = time.monotonic(); broker.close()
        assert time.monotonic() - before < 0.3
        assert not (Path(configuration["directory"]) / "active").exists()
        finish.set()
        eventually(lambda: not broker._fds)
        assert broker.status()["pending_requests"] == 0
        assert list((Path(configuration["directory"]) / "prepared").iterdir()) == []
        assert list((Path(configuration["directory"]) / "rsp").iterdir()) == []
        canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
        assert canonical.read_bytes() == raw
        with pytest.raises(AudioBrokerError): broker.configuration()
    finally:
        finish.set(); broker.close(); store.close(); cache.close()


def test_restart_capability_and_epoch_reject_old_requests(setup, tmp_path):
    first, store, _, _, calls, _ = setup
    old = first.configuration()
    second = MP4AudioBroker(store, tmp_path)
    try:
        new = second.configuration()
        assert old["directory"] != new["directory"] and old["capability"] != new["capability"]
        request_id, raw = request(old)
        target = send(new, request_id, raw)
        eventually(lambda: not target.exists())
        assert second.status()["rejected_requests"] == 1 and calls == []
    finally:
        second.close(); eventually(lambda: not second._fds)


def test_fatal_directory_failure_retires_only_owned_active_marker(setup):
    broker, _, _, _, _, _ = setup
    configuration = broker.configuration()
    root = Path(configuration["directory"])
    (root / "req").chmod(0o755)
    eventually(lambda: not broker.status()["available"])
    eventually(lambda: not (root / "active").exists())
    assert (root / "prepared").is_dir()


def test_long_suspension_keeps_response_and_prepared_bundle_until_native_consumption(setup, tmp_path, monkeypatch):
    _first, store, _, _, calls, _ = setup
    broker = MP4AudioBroker(store, tmp_path, max_responses=1)
    try:
        configuration = broker.configuration()
        first, raw = request(configuration); send(configuration, first, raw)
        eventually(lambda: broker.status()["ready_requests"] == 1)
        root = Path(configuration["directory"])
        reply = root / "rsp" / (first.hex() + ".rsp")
        prepared = root / "prepared" / (first.hex() + ".bundle")
        before = prepared.read_bytes()
        second, raw = request(configuration); queued = send(configuration, second, raw)
        time.sleep(0.08)
        assert queued.exists()
        baseline = module.monotonic()
        monkeypatch.setattr(module, "monotonic", lambda: baseline + 24 * 3600)
        broker._scan()
        assert reply.exists() and queued.exists() and prepared.read_bytes() == before
        first_status, first_path = receive(configuration, first)
        assert first_status == READY and first_path == prepared
        status, second_path = receive(configuration, second)
        assert status == READY and prepared.read_bytes() == before
        assert second_path.exists() and len(calls) == 1
    finally:
        broker.close(); eventually(lambda: not broker._fds)


@pytest.mark.parametrize("platform,number", [("android", 1), ("ios", 2)])
def test_actual_pinned_song_body_is_cloned_via_verified_store_without_modifying_source(tmp_path, platform, number):
    source = SAMPLES / ("mp4-" + platform + "-analysis")
    if not (source / "song-asset-proof.json").is_file():
        pytest.skip("Pinned public song sample is an optional local audit input")
    proof = json.loads((source / "song-asset-proof.json").read_text()); row = proof["row"]
    raw = (source / (row["name"] + ".bin")).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == proof["raw_sha256"]
    store, cache, record, calls, original = make_store(tmp_path, raw, platform=platform, row=row)
    broker = MP4AudioBroker(store, tmp_path)
    try:
        configuration = broker.configuration()
        request_id, packet = request(configuration, name=row["name"], platform=number)
        send(configuration, request_id, packet)
        status, prepared = receive(configuration, request_id)
        assert status == READY and prepared.read_bytes().startswith(b"UnityFS\0")
        resource = _unpack_fs(prepared.read_bytes()).entries[1].data
        assert hashlib.sha256(resource).hexdigest() == "e56096ca71957c65a034191fead878a9187c15673b4868d4e0705ba29fb9e6b9"
        canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
        assert canonical.read_bytes() == original and len(calls) == 1
    finally:
        broker.close(); store.close(); cache.close()
        eventually(lambda: not broker._fds)


@pytest.mark.parametrize("row", CHEER_SAMPLE_ROWS, ids=lambda row: row["platform"] + "-" + row["name"])
def test_actual_cheers_body_is_cloned_via_verified_store_without_modifying_source(tmp_path, row):
    source, raw = cheer_sample(row)
    store, cache, record, calls, original = make_store(tmp_path, raw, platform=row["platform"], row=row)
    broker = MP4AudioBroker(store, tmp_path)
    try:
        configuration = broker.configuration()
        request_id, packet = request(configuration, name=row["name"],
            platform=1 if row["platform"] == "android" else 2,
            samples=round(CHEER_RESOURCE_PINS[row["name"]][2] * 48000))
        send(configuration, request_id, packet)
        status, prepared = receive(configuration, request_id)
        assert status == READY
        resource = _unpack_fs(prepared.read_bytes()).entries[1].data
        assert (len(resource), hashlib.sha256(resource).hexdigest()) == CHEER_RESOURCE_PINS[row["name"]][:2]
        canonical = cache.root / record.cache_key[:2] / (record.cache_key + ".bin")
        assert canonical.read_bytes() == source.read_bytes() == original and len(calls) == 1
        assert stat.S_IMODE(prepared.stat().st_mode) == 0o400 and prepared.stat().st_ino != canonical.stat().st_ino
        assert calls == [f"https://d2ilil7yh5oi1v.cloudfront.net/solis-{row['upload']}-assetbundle/{row['object']}?generation={row['generation']}&alt=media"]
    finally:
        broker.close(); store.close(); cache.close(); eventually(lambda: not broker._fds)
