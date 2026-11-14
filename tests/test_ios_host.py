"""In-process lifecycle and trusted native-command boundary, without an iOS VM."""
import json
import os
from pathlib import Path
import socket
import threading
from types import SimpleNamespace

import pytest

from idoly_local import ios_host as host
from idoly_local import media_settings, playback, presentation


class Bridge:
    def __init__(self):
        self.events = []

    def post_event(self, raw):
        assert len(raw.encode()) <= host.MAX_JSON_BYTES
        self.events.append(json.loads(raw))

    def aes_cbc(self, _encrypt, _key, _iv, raw):
        return raw

    def open_url(self, *_args, **_kwargs):
        raise AssertionError("Tests must not contact a network resource")


class Library:
    def __init__(self):
        self.downloads = []; self.cancelled = []; self.imported = None

    def catalog_summary(self, platform):
        assert platform == "ios"
        return {"platform": platform, "files": 1, "bytes": 7}

    def start_download(self, platform, *, parallelism):
        self.downloads.append((platform, parallelism))
        return {"job_id": "download", "state": "running"}

    def cancel(self, identifier):
        self.cancelled.append(identifier)
        return {"job_id": identifier, "state": "cancelled"}

    def prepare_export(self, platform):
        return {"job_id": "export", "state": "export_ready", "total_bytes": 7}

    def write_export(self, identifier, out):
        out.write(b"archive")
        return {"job_id": identifier, "state": "completed", "archive_complete": True, "failed_files": 0}

    def import_from(self, source, platform):
        self.imported = source.read()
        return {"job_id": "import", "state": "completed", "failed_files": 0}


class Runtime:
    def __init__(self, root, *, ready=True):
        self.root = root; self.stops = 0; self.running = True; self.alive = ready
        self._grpc = SimpleNamespace(running=ready)
        self._asset_thread = SimpleNamespace(is_alive=lambda: self.alive)
        self._library = Library()
        self.active_media = dict(media_settings.DEFAULTS)

    def status(self):
        return {"running": self.running, "logs": ["x" * 2000] * 200,
            "presentation": presentation.PresentationState(self.root / "client-presentation.json").status(),
            "playback": playback.PlaybackState(self.root / "client-playback.json").status(),
            "media_options": {"settings": media_settings.MediaSettingsState(self.root / "client-media.json").settings(),
                              "effective_settings": self.active_media}}

    def stop(self):
        self.stops += 1; self.running = False; self._grpc.running = False; self.alive = False


@pytest.fixture
def harness(tmp_path):
    from idoly_local import codec
    previous_aes = codec._cipher_backend
    bundle = tmp_path / "app/LocalServer"; bundle.mkdir(parents=True)
    data = tmp_path / "Library/Application Support/IdolyPrideLocal"
    resources = tmp_path / "Documents/IdolyPride"
    bridge = Bridge(); runtimes = []; calls = []
    def factory(root, **kwargs):
        calls.append(kwargs); runtime = Runtime(root); runtimes.append(runtime); return runtime
    subject = host._Host(bridge=bridge, runtime_factory=factory, installer=lambda *_args: None,
                         translation_installer=lambda *_args, **_kwargs: None)
    yield SimpleNamespace(subject=subject, bundle=bundle, data=data, resources=resources,
        bridge=bridge, runtimes=runtimes, calls=calls)
    subject.close()
    codec.configure_aes(previous_aes)


def start(h):
    return h.subject.start(h.bundle, h.data, h.resources, ports=host.PortParams(0, 0))


def command(h, action, **fields):
    return json.loads(h.subject.command(json.dumps({"id": 7, "action": action, **fields})))


def test_fresh_defaults_native_adapters_and_both_listeners_ready(harness):
    h = harness; result = start(h)
    assert result["state"] == "ready" and result["running"]
    assert result["options"] == {**host.DEFAULT_OPTIONS, "language": "ko"}
    assert result["options"] == result["effective_options"] and not result["restart_required"]
    assert h.calls[0]["grpc_port"] == h.calls[0]["asset_port"] == 0
    assert h.calls[0]["resource_platform"] == "ios" and h.calls[0]["media_mode"] is True
    assert h.calls[0]["aes_cbc"] == h.bridge.aes_cbc and h.calls[0]["resource_fetcher"] == h.bridge.open_url
    assert h.bridge.events[-1]["event"] == "ready"
    assert start(h)["running"] and len(h.runtimes) == 1
    assert len(h.subject.command('{"id":1,"action":"status"}').encode()) <= host.MAX_JSON_BYTES


def test_existing_preferences_and_both_databases_are_preserved(harness):
    h = harness; h.data.mkdir(parents=True)
    normal = h.data / "state.db"; media = h.data / "media-state.db"
    normal.write_bytes(b"normal account"); media.write_bytes(b"gallery account")
    options = {"schema": 1, "media_mode": False, "download_missing_resources": False}
    (h.data / "ios-host.json").write_text(json.dumps(options))
    (h.data / "client-language.json").write_text('{"schema":1,"language":"en"}')
    result = start(h)
    assert result["options"] == {**options, "language": "en", "interface_language": "system"}
    assert h.calls[0]["media_mode"] is False and h.calls[0]["download_missing_resources"] is False
    assert normal.read_bytes() == b"normal account" and media.read_bytes() == b"gallery account"
    assert json.loads((h.data / "ios-host.json").read_text()) == options


def test_save_options_defers_language_and_profile_changes_until_next_launch(harness):
    h = harness; start(h)
    result = command(h, "save_options", media_mode=False, language="ja", download_missing_resources=False)
    assert result["ok"] and result["result"]["restart_required"]
    assert result["result"]["effective_options"]["language"] == "ko"
    assert h.runtimes[0].stops == 0 and len(h.calls) == 1
    assert result["result"]["options"]["language"] == "ja"
    assert json.loads((h.data / "ios-host.json").read_text())["media_mode"] is False
    assert json.loads((h.data / "ios-host.json").read_text())["language"] == "ja"
    assert json.loads((h.data / "client-language.json").read_text())["language"] == "ko"
    h.subject.close()
    relaunched = host._Host(bridge=h.bridge, runtime_factory=lambda root, **_kwargs: Runtime(root),
        installer=lambda *_args: None, translation_installer=lambda *_args, **_kwargs: None)
    try:
        next_run = relaunched.start(h.bundle, h.data, h.resources, ports=host.PortParams(0, 0))
        assert next_run["effective_options"] == result["result"]["options"]
        assert json.loads((h.data / "client-language.json").read_text())["language"] == "ja"
    finally:
        relaunched.close()


@pytest.mark.parametrize("action,settings,filename", [
    ("save_presentation", {**presentation.DEFAULTS, "expand_photography": True}, "client-presentation.json"),
    ("save_playback", {"schema": 1, "revision": 0, "wait_for_orientation": False}, "client-playback.json"),
    ("save_media", {**media_settings.DEFAULTS, "mv_sort": "old"}, "client-media.json"),
])
def test_settings_save_uses_shared_validation_atomic_file_and_revision(harness, action, settings, filename):
    h = harness; start(h)
    assert command(h, action, settings=settings)["ok"]
    saved = json.loads((h.data / filename).read_text())
    assert saved["revision"] > settings["revision"]
    assert all(saved[k] == v for k, v in settings.items() if k != "revision")
    assert (h.data / filename).stat().st_mode & 0o777 == 0o600
    assert not list(h.data.glob("." + filename + ".*"))
    assert not command(h, action, settings={**settings, "schema": True})["ok"]
    assert json.loads((h.data / filename).read_text()) == saved


@pytest.mark.parametrize("raw", ["[]", '{"action":"status","action":"status"}',
    '{"action":"save_options","media_mode":NaN}', '{"action":"unknown"}',
    '{"action":"status","path":"/private"}', '{"id":true,"action":"status"}',
    '{"id":"\\ud800","action":"status"}', '[[' * 18 + '0' + ']]' * 18,
    '"' + "x" * host.MAX_JSON_BYTES + '"'])
def test_commands_reject_malformed_duplicate_nonfinite_deep_and_oversize_json(harness, raw):
    reply = json.loads(harness.subject.command(raw))
    assert reply["ok"] is False and len(json.dumps(reply).encode()) <= host.MAX_JSON_BYTES


def test_close_racing_start_does_not_publish_ready_or_leak_runtime(harness):
    h = harness; entered = threading.Event(); release = threading.Event()
    def factory(root, **_kwargs):
        runtime = Runtime(root); h.runtimes.append(runtime); entered.set(); assert release.wait(3); return runtime
    h.subject._factory = factory
    thread = threading.Thread(target=start, args=(h,)); thread.start(); assert entered.wait(3)
    h.subject.close(); release.set(); thread.join(3)
    assert not thread.is_alive() and h.subject.status()["state"] == "closed"
    assert h.runtimes[0].stops == 1
    assert not any(event["event"] == "ready" for event in h.bridge.events)


def test_concurrent_start_calls_share_one_runtime(harness):
    h = harness; barrier = threading.Event(); entered = threading.Event()
    def factory(root, **_kwargs):
        entered.set(); assert barrier.wait(3); runtime = Runtime(root); h.runtimes.append(runtime); return runtime
    h.subject._factory = factory
    results = []
    a = threading.Thread(target=lambda: results.append(start(h))); a.start(); assert entered.wait(3)
    b = threading.Thread(target=lambda: results.append(start(h))); b.start(); barrier.set(); a.join(3); b.join(3)
    assert not a.is_alive() and not b.is_alive() and len(h.runtimes) == 1
    assert len(results) == 2 and all(value["state"] == "ready" for value in results)


def test_incomplete_listener_start_is_cleaned_up_and_can_retry(harness):
    h = harness
    def factory(root, **_kwargs):
        runtime = Runtime(root, ready=len(h.runtimes) > 0); h.runtimes.append(runtime); return runtime
    h.subject._factory = factory
    assert start(h)["state"] == "failed" and h.runtimes[0].stops == 1
    assert not any(event["event"] == "ready" for event in h.bridge.events)
    assert start(h)["state"] == "ready"


def test_retry_does_not_replace_runtime_until_failed_cleanup_succeeds(harness):
    h = harness; first = Runtime(h.data, ready=False); allow_cleanup = threading.Event()
    def stop():
        if not allow_cleanup.is_set(): raise RuntimeError("cleanup pending")
        first.stops += 1; first.running = False
    first.stop = stop
    h.subject._factory = lambda *_args, **_kwargs: first
    assert start(h)["state"] == "failed" and h.subject._runtime is first
    h.subject._factory = lambda root, **_kwargs: Runtime(root)
    assert start(h)["state"] == "failed" and h.subject._runtime is first
    allow_cleanup.set()
    assert start(h)["state"] == "ready" and first.stops == 1


def test_writable_paths_inside_bundle_or_overlapping_are_rejected_before_creation(harness):
    h = harness; inside = h.bundle / "private"
    assert h.subject.start(h.bundle, inside, h.resources)["state"] == "failed"
    assert not inside.exists()
    assert h.subject.start(h.bundle, h.data, h.data / "cache")["state"] == "failed"
    assert not h.data.exists()


def test_foreground_recovers_only_without_saved_restart_changes(harness):
    h = harness; start(h); h.runtimes[0].alive = False
    assert h.subject.foreground()["state"] == "ready" and len(h.runtimes) == 2
    command(h, "save_options", language="ja")
    h.runtimes[-1].alive = False
    result = h.subject.foreground()
    assert result["state"] == "failed" and result["restart_required"] and len(h.runtimes) == 2


def test_close_cleanup_failure_is_retained_for_retry(harness):
    h = harness; start(h); runtime = h.runtimes[0]; original = runtime.stop
    def once():
        runtime.stop = original
        raise RuntimeError("private details must not enter the error reply")
    runtime.stop = once
    h.subject.close(); assert h.subject.status()["last_error"]["code"] == "cleanup_failed"
    h.subject.close(); assert runtime.stops == 1 and h.subject._runtime is None


def test_atomic_preferences_reject_symlinks_and_preserve_original_on_replace_failure(harness, monkeypatch):
    h = harness; start(h); target = h.data / "ios-host.json"; original = target.read_bytes()
    real_replace = os.replace
    def failed(source, destination):
        if destination == target: raise OSError("simulated full disk")
        return real_replace(source, destination)
    monkeypatch.setattr(os, "replace", failed)
    assert not command(h, "save_options", language="en")["ok"]
    assert target.read_bytes() == original and not list(h.data.glob(".ios-host.json.*"))
    target.unlink(); outside = h.data.parent / "outside.json"; outside.write_text('secret')
    target.symlink_to(outside)
    assert not command(h, "save_options", language="ja")["ok"] and outside.read_text() == 'secret'


def test_archive_export_is_async_and_import_requires_native_owned_regular_file(harness, tmp_path):
    h = harness; start(h)
    initial = command(h, "resources_export")
    assert initial["ok"] and initial["result"]["ready"] is False
    h.subject._archive_worker.join(3)
    completed = h.subject.status()["resource_operation"]
    assert completed["ready"] and Path(completed["output_path"]).read_bytes() == b"archive"
    imports = h.data / "imports"; selected = imports / "approved.zip"; selected.write_bytes(b"trusted copied archive")
    assert command(h, "resources_import", path=str(selected))["ok"]
    h.subject._archive_worker.join(3)
    assert h.runtimes[0]._library.imported == b"trusted copied archive"
    assert not command(h, "resources_import", path=str(tmp_path / "outside.zip"))["ok"]
    alias = imports / "alias.zip"; alias.symlink_to(selected)
    assert not command(h, "resources_import", path=str(alias))["ok"]
    alias.unlink(); os.link(selected, alias)
    assert not command(h, "resources_import", path=str(alias))["ok"]
    assert command(h, "resources_download", parallelism=8)["ok"]
    assert h.runtimes[0]._library.downloads == [("ios", 8)]
    assert not command(h, "resources_download", parallelism=True)["ok"]


def test_export_size_and_retained_temp_file_bounds(harness, monkeypatch):
    h = harness; start(h); monkeypatch.setattr(host, "MAX_ARCHIVE_BYTES", 3)
    assert command(h, "resources_export")["ok"]
    h.subject._archive_worker.join(3)
    assert not h.subject.status()["resource_operation"]["accepted"]
    exports = h.data / "tmp/exports"
    assert not list(exports.iterdir())
    for index in range(host.MAX_EXPORT_FILES): (exports / str(index)).write_bytes(b"x")
    assert not command(h, "resources_export")["ok"]


def tiny_core(h, monkeypatch):
    """Small wire fixtures; real Runtime/SQLite/HTTP/H2 listener ownership."""
    from google.protobuf import descriptor_pb2
    from idoly_local import application, gameplay
    def install(_bundle, root, _log):
        root.mkdir(parents=True, exist_ok=True)
        file = descriptor_pb2.FileDescriptorProto(name="ios-host.proto", package="api", syntax="proto3")
        file.message_type.add(name="Empty")
        pack = file.message_type.add(name="MasterPack")
        for number, name, kind in [(1,"type",9),(2,"fileName",9),(3,"fileSize",5),(4,"cryptoKey",9),(5,"downloadUrl",9)]:
            pack.field.add(name=name, number=number, type=kind)
        tag = file.message_type.add(name="MasterTag")
        tag.field.add(name="version", number=1, type=9)
        tag.field.add(name="masterTagPacks", number=2, type=11, label=3, type_name=".api.MasterPack")
        response = file.message_type.add(name="MasterGetResponse")
        response.field.add(name="masterTag", number=1, type=11, type_name=".api.MasterTag")
        file.service.add(name="Master").method.add(name="Get", input_type=".api.Empty", output_type=".api.MasterGetResponse")
        file.service.add(name="System").method.add(name="Check", input_type=".api.Empty", output_type=".api.Empty")
        descriptor = descriptor_pb2.FileDescriptorSet(); descriptor.file.add().CopyFrom(file)
        (root / "protocol").mkdir(exist_ok=True)
        (root / "protocol/idolypride-6.1.1.pb").write_bytes(descriptor.SerializeToString())
        master = root / "original-master"; (master / "assets/master").mkdir(parents=True, exist_ok=True)
        (master / "assets/master/tiny").write_bytes(b"tiny")
        (master / "master-tag.json").write_text(json.dumps({"version":"fixture","masterTagPacks":[
            {"type":"Fixture","fileName":"tiny","fileSize":4,"cryptoKey":"key","downloadUrl":"https://invalid/tiny"}]}))
        (root / "master-json").mkdir(exist_ok=True)
        (root / "ios-host.json").write_text(json.dumps({"schema":1,"media_mode":False,"download_missing_resources":False}))
        (root / "client-language.json").write_text('{"schema":1,"language":"ja"}')
    class Application:
        def __init__(self, schema, *_args, **_kwargs): self.schema = schema
        def handle(self, path, _raw, _context): return self.schema.response_type(path)().SerializeToString()
    monkeypatch.setattr(application, "Application", Application)
    monkeypatch.setattr(gameplay, "seed_starter_profile", lambda *_args: None)
    h.subject._installer = install; h.subject._factory = None


def test_failed_bind_real_runtime_releases_already_bound_asset_listener(harness, monkeypatch):
    from idoly_local import assets
    h = harness; tiny_core(h, monkeypatch)
    resource = socket.socket(); resource.bind(("127.0.0.1", 0)); occupied = resource.getsockname()[1]
    opened = []; original = assets.create_asset_server
    def observe(*args, **kwargs):
        server = original(*args, **kwargs); opened.append(server.server_address[1]); return server
    monkeypatch.setattr(assets, "create_asset_server", observe)
    try:
        result = h.subject.start(h.bundle, h.data, h.resources, ports=host.PortParams(occupied, 0))
        assert result["state"] == "failed" and len(opened) == 1
        probe = socket.socket()
        try: probe.bind(("127.0.0.1", opened[0]))
        finally: probe.close()
        assert not any(event["event"] == "ready" for event in h.bridge.events)
    finally: resource.close()


def test_real_core_loopback_http_h2_sqlite_start_and_shutdown(harness, monkeypatch):
    from urllib.request import urlopen
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import StreamEnded, TrailersReceived
    h = harness; tiny_core(h, monkeypatch); result = start(h)
    assert result["state"] == "ready", result
    address = result["runtime"]["grpc_address"]; asset_url = result["runtime"]["asset_url"]
    with urlopen(asset_url + "/client/playback", timeout=3) as response:
        assert json.loads(response.read())["wait_for_orientation"] is True
    connection = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
    connection.initiate_connection()
    connection.send_headers(1,[(":method","POST"),(":scheme","http"),(":authority",address),
        (":path","/api.System/Check"),("content-type","application/grpc+proto"),("te","trailers")])
    connection.send_data(1,b"\0"*5,end_stream=True); statuses=[]; ended=False
    with socket.create_connection(tuple([address.rsplit(":",1)[0],int(address.rsplit(":",1)[1])]),timeout=3) as stream:
        stream.sendall(connection.data_to_send())
        while not ended:
            for event in connection.receive_data(stream.recv(65536)):
                if isinstance(event,TrailersReceived): statuses.append(dict(event.headers)["grpc-status"])
                if isinstance(event,StreamEnded): ended=True
            pending=connection.data_to_send()
            if pending:stream.sendall(pending)
    assert statuses == ["0"] and (h.data / "state.db").is_file()
    ports=[int(address.rsplit(":",1)[1]),int(asset_url.rsplit(":",1)[1])]
    h.subject.close()
    for port in ports:
        probe=socket.socket();probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:probe.bind(("127.0.0.1",port))
        finally:probe.close()


def test_interface_language_saves_without_restarting_the_game_server(harness):
    h = harness; start(h)
    result = command(h, "save_options", interface_language="ja")
    assert result["ok"] and result["result"]["options"]["interface_language"] == "ja"
    assert result["result"]["restart_required"] is False
    assert h.runtimes[0].stops == 0 and len(h.runtimes) == 1
    assert json.loads((h.data / "ios-host.json").read_text())["interface_language"] == "ja"


@pytest.mark.parametrize("value", [None, True, 1, "fr", [], {}])
def test_interface_language_rejects_invalid_values_without_overwriting_preferences(harness, value):
    h = harness; start(h)
    before = (h.data / "ios-host.json").read_bytes()
    assert not command(h, "save_options", interface_language=value)["ok"]
    assert (h.data / "ios-host.json").read_bytes() == before


def test_game_start_applies_selected_language_before_preparing_embedded_data(harness, monkeypatch):
    from idoly_local import ios_client_data
    h = harness; start(h)
    assert command(h, "save_options", language="ja", media_mode=False)["ok"]
    observed = []
    def prepare(app, data, language):
        assert app == h.bundle.parent and data == h.data
        assert language == h.subject.status()["effective_options"]["language"] == "ja"
        assert json.loads((h.data / "client-language.json").read_text())["language"] == "ja"
        observed.append(language)
        return {"schema": 1, "language": language, "bundle_id": "local.idoly.client-data",
                "bundle_path": str(data / "client-data/ja.bundle"), "files": 46, "reused": False}
    monkeypatch.setattr(ios_client_data, "prepare_client_data", prepare)
    result = h.subject.prepare_game_start()
    assert result["running"] and result["client_data"]["language"] == "ja"
    assert observed == ["ja"] and len(h.runtimes) == 2 and h.runtimes[0].stops == 1
    assert h.calls[-1]["media_mode"] is False


@pytest.mark.parametrize("state", ["preparing", "running", "export_ready", "cancelling"])
def test_game_start_preserves_an_active_resource_job(harness, monkeypatch, state):
    from idoly_local import ios_client_data
    h = harness; start(h); runtime = h.runtimes[0]
    original_status = runtime.status
    monkeypatch.setattr(runtime, "status", lambda: {**original_status(), "resource_library": {"job": {"state": state}}})
    monkeypatch.setattr(ios_client_data, "prepare_client_data", lambda *_: pytest.fail("active job must be retained"))
    assert command(h, "save_options", language="en")["ok"]
    with pytest.raises(RuntimeError, match="Finish or cancel"):
        h.subject.prepare_game_start()
    assert runtime.stops == 0 and len(h.runtimes) == 1


def test_failed_game_start_restart_reports_server_unavailable(harness, monkeypatch):
    h = harness; start(h)
    assert command(h, "save_options", language="en")["ok"]
    def failed_factory(*_args, **_kwargs):
        raise OSError("fixture listener failure")
    h.subject._factory = failed_factory
    with pytest.raises(RuntimeError, match="could not apply"):
        h.subject.prepare_game_start()
    assert h.subject.readiness() == {"state": "failed", "running": False}
    assert h.runtimes[0].stops == 1


def test_data_only_failure_keeps_existing_server_available(harness, monkeypatch):
    from idoly_local import ios_client_data
    h = harness; start(h)
    def damaged_data(*_args): raise ValueError("fixture client data damaged")
    monkeypatch.setattr(ios_client_data, "prepare_client_data", damaged_data)
    with pytest.raises(ValueError, match="client data damaged"):
        h.subject.prepare_game_start()
    assert h.subject.readiness() == {"state": "ready", "running": True}
    assert h.runtimes[0].stops == 0
