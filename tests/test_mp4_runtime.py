"""Trusted runtime MP4 descriptors never become public HTTP/UI configuration."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from idoly_local import app_runtime
from test_mp4_audio_bundle import NAME, bundle, masked
from test_mp4_audio_broker import eventually, request, send, receive, READY
from test_app_runtime import _Application, _write_bundle
from test_octo_runtime import write_archive
from test_octo_app_runtime import request as http_request, ResourceResponse
from test_ios_host import harness, Runtime as HostRuntime, start as host_start, command as host_command


@pytest.fixture
def runtime_factory(tmp_path, monkeypatch):
    # Existing runtime fixtures replace gameplay before importing love. Load
    # the real dependency first so this fixture is independently runnable.
    from idoly_local import love
    from idoly_local.octo_manifest import Database
    from idoly_local.profiles import new_profile
    from idoly_local.state import State
    schema = _write_bundle(tmp_path)
    state = State(tmp_path / "state.db")
    new_profile(state, schema, "sandbox", "Preserved manager")
    snapshot = state.snapshot("sandbox")
    monkeypatch.setitem(sys.modules, "idoly_local.application", SimpleNamespace(Application=_Application))
    monkeypatch.setitem(sys.modules, "idoly_local.gameplay", SimpleNamespace(
        seed_starter_profile=lambda *_: pytest.fail("Existing account must remain"),
        repair_starter_roster=lambda *_: False, repair_starter_home_positions=lambda *_: False,
        repair_starter_inventory=lambda *_: False, repair_starter_card_level_mission=lambda *_: False))
    body = masked(bundle(), NAME)
    for platform, folder, revision in (("android", "public-octo", 1087), ("ios", "public-octo-ios", 1159)):
        settings, raw = write_archive(tmp_path / folder, platform=platform, revision=revision)
        database = Database.FromString(raw)
        row = database.assetBundleList[0]
        row.name, row.objectName, row.size, row.md5, row.state = (
            NAME, "ABC123", len(body), hashlib.md5(body, usedforsecurity=False).hexdigest(), 3)
        raw = database.SerializeToString()
        settings["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        (tmp_path / folder / "manifest.pb").write_bytes(raw)
        (tmp_path / folder / "settings.json").write_text(json.dumps(settings))
    private = tmp_path / "native-private"; private.mkdir(mode=0o755)
    runtimes, calls = [], []
    def start(*, unified=True, platform="android"):
        def fetch(url, **_):
            calls.append(url)
            response = ResourceResponse(url)
            response.seek(0); response.truncate(0); response.write(body); response.seek(0)
            response.headers["Content-Length"] = str(len(body))
            return response
        runtime = app_runtime.start(tmp_path, grpc_port=0, asset_port=0,
            resource_fetcher=fetch, resource_platform=platform,
            shared_resource_dir=private if unified else None)
        runtimes.append(runtime)
        return runtime
    yield SimpleNamespace(start=start, calls=calls, private=private, state=state,
        snapshot=snapshot, body=body, runtimes=runtimes)
    for runtime in runtimes:
        runtime.stop()
        for broker in (runtime._mp4_audio, runtime._shared_resources):
            if broker is not None:
                eventually(lambda broker=broker: not broker._fds)


@pytest.mark.parametrize("unified", [False, True])
@pytest.mark.parametrize("platform", ["android", "ios"])
def test_real_runtime_descriptor_is_unified_only_and_absent_from_http_exports(runtime_factory, unified, platform):
    h = runtime_factory
    runtime = h.start(unified=unified, platform=platform)
    configuration = runtime.mp4_configuration()
    assert configuration["available"] is unified and h.calls == []
    public = runtime.diagnostics_snapshot()
    assert public["runtime"]["mp4_audio"]["available"] is unified
    if unified:
        root = Path(configuration["directory"])
        assert root.is_relative_to(h.private)
        for key, name in (("export_directory", "exports"), ("temporary_directory", "tmp")):
            directory = Path(configuration[key])
            assert directory == root / name and directory.is_dir() and not directory.is_symlink()
            assert directory.stat().st_mode & 0o777 == 0o700 and directory.stat().st_uid == os.geteuid()
        text = json.dumps(public)
        for key in ("directory", "capability", "export_directory", "temporary_directory"):
            assert configuration[key] not in text
        code, _, body = http_request(runtime.status()["asset_url"], "/diagnostics/runtime")
        assert code == 200
        for key in ("directory", "capability", "export_directory", "temporary_directory"):
            assert configuration[key].encode() not in body
        for route in ("/mp4/configuration", "/client/mp4", "/prepared/private.bundle"):
            assert http_request(runtime.status()["asset_url"], route)[0] == 404
    assert h.state.snapshot("sandbox") == h.snapshot
    runtime.stop()
    assert runtime.mp4_configuration() == {"schema": 1, "available": False}


def test_real_runtime_reuses_verified_store_and_preserves_private_outputs_after_stop(runtime_factory):
    h = runtime_factory; runtime = h.start()
    configuration = runtime.mp4_configuration()
    request_id, raw = request(configuration)
    send(configuration, request_id, raw)
    status, prepared = receive(configuration, request_id)
    assert status == READY
    exports, temporary = Path(configuration["export_directory"]), Path(configuration["temporary_directory"])
    final, partial = exports / ("a"*32 + ".mp4"), temporary / ("a"*32 + ".partial")
    for path in (final, partial):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"native-owned pending export")
    prepared_bytes = prepared.read_bytes()
    store = runtime._shared_resource_store
    assert runtime._mp4_audio._store is store and runtime._shared_resources._store is store
    assert len(h.calls) == 1 and store.status()["active_leases"] == 0
    runtime.stop()
    assert not (Path(configuration["directory"]) / "active").exists()
    assert store.status()["closed"] is True and prepared.read_bytes() == prepared_bytes
    assert final.read_bytes() == partial.read_bytes() == b"native-owned pending export"
    assert h.state.snapshot("sandbox") == h.snapshot


def test_runtime_closes_audio_capability_before_its_shared_input_store():
    runtime = app_runtime.Runtime("sandbox")
    calls = []
    runtime._mp4_audio = SimpleNamespace(close=lambda: calls.append("audio"))
    runtime._shared_resources = SimpleNamespace(close=lambda: calls.append("shared"))
    runtime._shared_resource_store = SimpleNamespace(close=lambda: calls.append("store"))
    runtime.stop()
    assert calls == ["audio", "shared", "store"]


@pytest.mark.parametrize("broken", ["audio", "shared", "both"])
def test_optional_broker_start_failure_keeps_game_listeners_and_other_feature(runtime_factory, monkeypatch, broken):
    from idoly_local import mp4_audio_broker, shared_resource_broker
    def unavailable(*_args, **_kwargs):
        raise OSError("synthetic private feature unavailable")
    if broken in ("audio", "both"):
        monkeypatch.setattr(mp4_audio_broker, "MP4AudioBroker", unavailable)
    if broken in ("shared", "both"):
        monkeypatch.setattr(shared_resource_broker, "SharedResourceBroker", unavailable)
    runtime = runtime_factory.start()
    assert runtime.status()["running"] is True
    assert runtime.mp4_configuration()["available"] is (broken == "shared")
    assert runtime.shared_resources_configuration()["available"] is (broken == "audio")
    assert (runtime._shared_resource_store is None) is (broken == "both")
    assert http_request(runtime.status()["asset_url"], "/master/tiny.pack")[0] == 200


def test_android_private_accessor_returns_descriptor_without_status_leak(runtime_factory):
    path = Path(__file__).resolve().parents[1] / "android-server/app/src/main/python/android_server_runtime.py"
    spec = importlib.util.spec_from_file_location("android_mp4_private_boundary", path)
    boundary = importlib.util.module_from_spec(spec); spec.loader.exec_module(boundary)
    assert json.loads(boundary.mp4_configuration_json()) == {"schema": 1, "available": False}
    runtime = runtime_factory.start(); boundary._RUNTIME = runtime
    descriptor = json.loads(boundary.mp4_configuration_json())
    assert descriptor == runtime.mp4_configuration()
    for public in (boundary.status_json(), boundary.diagnostics_json()):
        for key in ("directory", "capability", "export_directory", "temporary_directory"):
            assert descriptor[key] not in public
    runtime.stop()
    assert json.loads(boundary.mp4_configuration_json()) == {"schema": 1, "available": False}


def test_ios_private_mp4_accessor_refreshes_after_foreground_without_web_exposure(harness, monkeypatch):
    from idoly_local import ios_host
    h = harness
    def configuration(runtime):
        root = runtime.root / ("mp4-private-" + str(id(runtime)))
        return {"schema": 1, "available": runtime.running, "directory": str(root), "epoch": id(runtime),
            "capability": "c"*32, "export_directory": str(root / "exports"), "temporary_directory": str(root / "tmp")}
    monkeypatch.setattr(HostRuntime, "mp4_configuration", configuration, raising=False)
    assert h.subject.mp4_configuration() == {"schema": 1, "available": False}
    host_start(h); monkeypatch.setattr(ios_host, "_HOST", h.subject)
    original = ios_host.mp4_configuration()
    assert original["available"] is True and original["directory"] not in json.dumps(h.subject.status())
    assert not host_command(h, "mp4_configuration")["ok"]
    h.runtimes[0].alive = False
    assert h.subject.foreground()["state"] == "ready"
    refreshed = ios_host.mp4_configuration()
    assert refreshed["directory"] != original["directory"] and refreshed["epoch"] != original["epoch"]
    assert refreshed["directory"] not in json.dumps(h.subject.status())
    h.subject.close()
    assert ios_host.mp4_configuration() == {"schema": 1, "available": False}


def test_ios_prepare_game_start_includes_private_mp4_only_in_native_result(harness, monkeypatch):
    from idoly_local import ios_client_data
    h = harness; host_start(h)
    private = {"schema": 1, "available": True, "directory": "/private/test-mp4",
        "epoch": 42, "capability": "d"*32, "export_directory": "/private/test-mp4/exports"}
    monkeypatch.setattr(h.runtimes[-1], "mp4_configuration", lambda: dict(private), raising=False)
    monkeypatch.setattr(ios_client_data, "prepare_client_data", lambda *_: {"language": "ko"})
    assert h.subject.prepare_game_start()["mp4"] == private
    assert private["directory"] not in json.dumps(h.subject.status())
    assert not host_command(h, "mp4_configuration")["ok"]
