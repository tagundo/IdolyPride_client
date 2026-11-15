"""Exercise embedded startup, real listeners, persistence and cleanup ownership."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.request import Request, urlopen

import grpc
from google.protobuf import descriptor_pb2

from idoly_local import app_runtime, codec
from idoly_local.gameplay import (repair_starter_home_positions, repair_starter_inventory,
                                 repair_starter_roster, repair_starter_card_level_mission)
from idoly_local.profiles import new_profile
from idoly_local.schema import Schema
from idoly_local.state import State


def _write_bundle(root: Path):
    file = descriptor_pb2.FileDescriptorProto(name="runtime-test.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    user = file.message_type.add(name="RuntimeUser")
    user.field.add(name="name", number=1, type=9)
    user.field.add(name="managerLevel", number=100, type=5)
    public = file.message_type.add(name="RuntimeUserPublic")
    public.field.add(name="serverUserId", number=1, type=9)
    public.field.add(name="publicUserId", number=2, type=9)
    response = file.message_type.add(name="UserGetResponse")
    response.field.add(name="user", number=1, type=11, type_name=".api.RuntimeUser")
    response.field.add(name="userPublic", number=2, type=11, type_name=".api.RuntimeUserPublic")
    pack = file.message_type.add(name="MasterTagPack")
    for number, name, kind in [(1, "type", 9), (2, "fileName", 9), (3, "fileSize", 5),
                               (4, "cryptoKey", 9), (5, "downloadUrl", 9)]:
        pack.field.add(name=name, number=number, type=kind)
    tag = file.message_type.add(name="MasterTag")
    tag.field.add(name="version", number=1, type=9)
    tag.field.add(name="masterTagPacks", number=2, type=11, label=3, type_name=".api.MasterTagPack")
    response = file.message_type.add(name="MasterGetResponse")
    response.field.add(name="masterTag", number=1, type=11, type_name=".api.MasterTag")
    response = file.message_type.add(name="SystemCheckResponse")
    response.field.add(name="keepAliveTimeMilliseconds", number=3, type=5)
    for name, method, response_name in [("System", "Check", "SystemCheckResponse"),
                                         ("Master", "Get", "MasterGetResponse"),
                                         ("User", "Get", "UserGetResponse")]:
        file.service.add(name=name).method.add(name=method, input_type=".api.Empty", output_type=".api." + response_name)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    directory = root / "protocol"
    directory.mkdir()
    schema_file = directory / "idolypride-6.1.1.pb"
    schema_file.write_bytes(descriptors.SerializeToString())
    master = root / "original-master"
    (master / "assets" / "master").mkdir(parents=True)
    (master / "assets" / "master" / "tiny.pack").write_bytes(b"archived-pack")
    (master / "master-tag.json").write_text(json.dumps({"version": "fixture-master", "masterTagPacks": [
        {"type": "Tiny", "fileName": "tiny.pack", "fileSize": 13, "cryptoKey": "fixture-key",
         "downloadUrl": "https://official.invalid/tiny"}]}))
    (master / "assets" / "master" / "media-tiny.pack").write_bytes(b"media-outfit-pack")
    (master / "media-master-tag.json").write_text(json.dumps({
        "version": "local-media-outfits-v1-fixture", "masterTagPacks": [
            {"type": "Tiny", "fileName": "media-tiny.pack", "fileSize": 17,
             "cryptoKey": "fixture-media-key", "downloadUrl": "https://official.invalid/media-tiny"}]}))
    (root / "master-json").mkdir()
    return Schema.from_descriptor_set(schema_file)


class _Application:
    created = []

    def __init__(self, schema, state, fixtures, profile, master_response, master_dir, **options):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_response, self.master_dir = master_response, master_dir
        self.fixtures, self.options = fixtures, options
        self.created.append(self)

    def handle(self, path, raw, context):
        self.schema.request_type(path).FromString(codec.decode(raw))
        if path == "/api.Master/Get":
            return self.master_response
        if path == "/api.User/Get":
            return self.state.snapshot(self.profile)[0]
        return self.schema.response_type(path)(keepAliveTimeMilliseconds=60000).SerializeToString()


class EmbeddedRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.schema = _write_bundle(self.root)
        self.seed_calls = []
        self.seed_error = None
        _Application.created.clear()

        def seed(state, schema, profile, master_dir):
            self.seed_calls.append((profile, master_dir))
            if self.seed_error:
                raise self.seed_error
            return new_profile(state, schema, profile, "Starter Manager")

        self.module_patcher = mock.patch.dict(sys.modules, {
            "idoly_local.application": SimpleNamespace(Application=_Application),
            "idoly_local.gameplay": SimpleNamespace(seed_starter_profile=seed,
                                                    repair_starter_roster=repair_starter_roster,
                                                    repair_starter_home_positions=repair_starter_home_positions,
                                                    repair_starter_inventory=repair_starter_inventory,
                                                    repair_starter_card_level_mission=repair_starter_card_level_mission),
        })
        self.module_patcher.start()
        self.addCleanup(self.module_patcher.stop)

    def start(self, **kwargs):
        runtime = app_runtime.start(self.root, grpc_port=kwargs.pop("grpc_port", 0),
                                    asset_port=kwargs.pop("asset_port", 0), **kwargs)
        self.addCleanup(runtime.stop)
        return runtime

    def rpc(self, runtime, method):
        with grpc.insecure_channel(runtime.status()["grpc_address"]) as channel:
            raw = channel.unary_unary(method)(b"", timeout=5)
        return self.schema.response_type(method).FromString(codec.decode(raw))

    def test_real_grpc_and_asset_listeners_share_prepared_master_url(self):
        runtime = self.start()
        status = runtime.status()
        self.assertTrue(status["running"])
        self.assertEqual(status["profile"], "sandbox")
        self.assertEqual(self.rpc(runtime, "/api.System/Check").keepAliveTimeMilliseconds, 60000)
        master = self.rpc(runtime, "/api.Master/Get")
        url = master.masterTag.masterTagPacks[0].downloadUrl
        self.assertEqual(url, status["asset_url"] + "/master/tiny.pack")
        with urlopen(url, timeout=3) as response:
            self.assertEqual(response.read(), b"archived-pack")
        self.assertEqual(self.rpc(runtime, "/api.User/Get").user.name, "Starter Manager")
        self.assertEqual(_Application.created[-1].master_dir, self.root / "master-json")
        self.assertEqual(len(self.seed_calls), 1)
        self.assertEqual(json.loads(json.dumps(status))["running"], True)

    def test_media_mode_uses_an_independent_database_and_live_response_store(self):
        ordinary = State(self.root / "state.db")
        new_profile(ordinary, self.schema, "sandbox", "Normal Manager")
        before = (self.root / "state.db").read_bytes()
        scenes = object()

        def media_seed(state, schema, profile, master_dir):
            self.assertEqual(state.path, self.root / "media-state.db")
            new_profile(state, schema, profile, "Media Manager")
            return scenes

        with mock.patch("idoly_local.media_runtime.prepare_media_profile", side_effect=media_seed):
            runtime = self.start(media_mode=True)
        self.assertTrue(runtime.status()["media_mode"])
        self.assertEqual(self.rpc(runtime, "/api.User/Get").user.name, "Media Manager")
        self.assertEqual((self.root / "state.db").read_bytes(), before)
        app = _Application.created[-1]
        self.assertEqual(app.fixtures.directory, self.root / "media-fixtures")
        self.assertTrue(app.options["media_mode"])
        self.assertIs(app.options["photo_scene_access"], scenes)
        master = self.rpc(runtime, "/api.Master/Get")
        self.assertEqual(master.masterTag.version, "local-media-outfits-v1-fixture")
        with urlopen(master.masterTag.masterTagPacks[0].downloadUrl, timeout=3) as response:
            self.assertEqual(response.read(), b"media-outfit-pack")
        original = json.loads((self.root / "original-master/master-tag.json").read_text())
        self.assertEqual(original["version"], "fixture-master")
        self.assertEqual((self.root / "original-master/assets/master/tiny.pack").read_bytes(), b"archived-pack")

    def test_missing_media_master_stops_before_creating_or_mutating_an_account(self):
        ordinary = State(self.root / "state.db")
        new_profile(ordinary, self.schema, "sandbox", "Normal Manager")
        before = (self.root / "state.db").read_bytes()
        (self.root / "original-master/media-master-tag.json").unlink()
        with mock.patch("idoly_local.media_runtime.prepare_media_profile") as seed:
            with self.assertRaisesRegex(ValueError, "Media outfit master is missing"):
                self.start(media_mode=True)
        seed.assert_not_called()
        self.assertFalse((self.root / "media-state.db").exists())
        self.assertEqual((self.root / "state.db").read_bytes(), before)

    def test_invalid_media_master_stops_before_seeding(self):
        tag = self.root / "original-master/media-master-tag.json"
        pack = self.root / "original-master/assets/master/media-tiny.pack"
        valid_tag, valid_pack = tag.read_bytes(), pack.read_bytes()
        for fault in ("json", "missing_pack", "pack_size"):
            with self.subTest(fault=fault):
                tag.write_bytes(valid_tag)
                pack.write_bytes(valid_pack)
                if fault == "json":
                    tag.write_text("{broken")
                elif fault == "missing_pack":
                    pack.unlink()
                else:
                    pack.write_bytes(b"incomplete")
                with mock.patch("idoly_local.media_runtime.prepare_media_profile") as seed:
                    with self.assertRaises(ValueError):
                        self.start(media_mode=True)
                seed.assert_not_called()
                self.assertFalse((self.root / "media-state.db").exists())

    def test_media_mode_requires_an_explicit_boolean(self):
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Media mode"):
                self.start(media_mode=value)
        self.assertFalse((self.root / "media-state.db").exists())

    def test_loopback_runtime_endpoint_exports_existing_snapshot_and_safe_rpc_log_only(self):
        runtime = self.start()
        self.assertEqual(self.rpc(runtime, "/api.System/Check").keepAliveTimeMilliseconds, 60000)
        runtime._log("RPC /api.Deck/Save -> UNIMPLEMENTED")
        state = State(self.root / "state.db")
        before = state.snapshot("sandbox")
        session_token, _ = state.login("sandbox")
        # The HTTP observer reads existing runtime metadata, without selecting
        # or loading any account profile or session from local storage.
        with mock.patch.object(State, "snapshot", side_effect=AssertionError("account read")):
            with urlopen(runtime.status()["asset_url"] + "/diagnostics/runtime", timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                body = response.read()
                self.assertEqual(int(response.headers["Content-Length"]), len(body))
        observed = json.loads(body)
        # Serving this endpoint itself updates HTTP observations after the
        # snapshot body has been encoded. Compare the otherwise stable fields.
        current = runtime.diagnostics_snapshot()
        observed_http = observed["runtime"].pop("http_requests")
        current["runtime"].pop("http_requests")
        self.assertEqual(observed, current)
        self.assertEqual(observed_http["last_request"]["path"], "/diagnostics/runtime")
        self.assertTrue(observed["runtime"]["running"])
        self.assertIn("RPC /api.Deck/Save -> UNIMPLEMENTED", observed["runtime"]["logs"])
        self.assertTrue(any("/api.System/Check -> OK" in line for line in observed["runtime"]["logs"]))
        self.assertNotIn("Starter Manager", body.decode())
        self.assertNotIn(session_token, body.decode())
        self.assertNotIn("state.db", body.decode())
        self.assertEqual(state.snapshot("sandbox"), before)
        self.assertTrue(state.authenticated(session_token, "sandbox"))

    def test_stop_releases_both_ports_and_restart_preserves_snapshot(self):
        first = self.start()
        original = self.rpc(first, "/api.User/Get").SerializeToString()
        status = first.status()
        grpc_port = int(status["grpc_address"].rsplit(":", 1)[1])
        asset_port = int(status["asset_url"].rsplit(":", 1)[1])
        first.stop()
        first.stop()
        self.assertFalse(first.status()["running"])
        restarted = self.start(grpc_port=grpc_port, asset_port=asset_port)
        self.assertEqual(self.rpc(restarted, "/api.User/Get").SerializeToString(), original)
        self.assertEqual(len(self.seed_calls), 1)

    def test_playback_default_is_on_for_both_platforms_and_is_exposed_independently(self):
        for platform in ("android", "ios"):
            with self.subTest(platform=platform):
                runtime = self.start(resource_platform=platform)
                address = runtime.status()["asset_url"]
                with urlopen(address + "/client/playback", timeout=3) as response:
                    setting = json.load(response)
                self.assertEqual(setting, {"schema": 1, "revision": 0, "wait_for_orientation": True})
                self.assertEqual(runtime.status()["playback"]["settings"], setting)
                self.assertFalse(runtime.status()["playback"]["client"]["applied"])
                with urlopen(address + "/client/presentation", timeout=3) as response:
                    graphics = json.load(response)
                self.assertEqual(len(graphics), 10)
                self.assertNotIn("wait_for_orientation", graphics)
                runtime.stop()

    def test_existing_imported_snapshot_is_not_seeded_again(self):
        state = State(self.root / "state.db")
        new_profile(state, self.schema, "sandbox", "Preserved Manager")
        before = state.snapshot("sandbox")
        runtime = self.start()
        self.assertEqual(self.rpc(runtime, "/api.User/Get").user.name, "Preserved Manager")
        self.assertEqual(state.snapshot("sandbox"), before)
        self.assertFalse(self.seed_calls)

    def test_render_probe_is_transient_exported_readback_and_restart_preserves_account(self):
        runtime = self.start()
        state = State(self.root / "state.db")
        before = state.snapshot("sandbox")
        database = (self.root / "state.db").read_bytes()
        empty = {"client": None, "age_seconds": None, "stale": True}
        self.assertEqual(runtime.status()["render_probe"], empty)
        value = {"schema": 1, "state": "observed", "actual_mode": 0, "graphics_api": 21,
                 "callback_tid": 123, "observations": 1, "sample_age_ms": 10000,
                 "cpu_frame_ms": None, "gpu_frame_ms": None, "timing_age_ms": None}
        address = runtime.status()["asset_url"]
        with mock.patch.object(State, "snapshot", side_effect=AssertionError("account read")):
            with urlopen(Request(address + "/client/render-probe", data=json.dumps(value).encode(),
                         headers={"Content-Type": "application/json"}), timeout=3) as response:
                self.assertEqual(json.load(response), {"accepted": True})
            for route in ("/client/render-probe", "/diagnostics/runtime"):
                with urlopen(address + route, timeout=3) as response:
                    observed = json.load(response)
                probe = observed if route == "/client/render-probe" else observed["runtime"]["render_probe"]
                self.assertEqual(probe["client"], value)
                self.assertGreaterEqual(probe["age_seconds"], 0)
                self.assertTrue(probe["stale"])
        self.assertEqual(state.snapshot("sandbox"), before)
        self.assertEqual((self.root / "state.db").read_bytes(), database)
        self.assertFalse(list(self.root.glob("*render-probe*")))
        runtime.stop()
        restarted = self.start()
        self.assertEqual(restarted.status()["render_probe"], empty)
        self.assertEqual(state.snapshot("sandbox"), before)

    def test_startup_repairs_roster_home_inventory_then_card_level_mission(self):
        state = State(self.root / "state.db")
        new_profile(state, self.schema, "sandbox", "Preserved Manager")
        before = state.snapshot("sandbox")
        token, _ = state.login("sandbox")
        order = []
        gameplay = sys.modules["idoly_local.gameplay"]
        with mock.patch.object(gameplay, "repair_starter_roster", side_effect=lambda *args: order.append("roster") or False), \
                mock.patch.object(gameplay, "repair_starter_home_positions", side_effect=lambda *args: order.append("home") or False), \
                mock.patch.object(gameplay, "repair_starter_inventory", side_effect=lambda *args: order.append("inventory") or False), \
                mock.patch.object(gameplay, "repair_starter_card_level_mission", side_effect=lambda *args: order.append("mission") or False):
            self.start()
        self.assertEqual(order, ["roster", "home", "inventory", "mission"])
        self.assertEqual(state.snapshot("sandbox"), before)
        self.assertTrue(state.authenticated(token, "sandbox"))
        self.assertFalse(self.seed_calls)

    def test_busy_grpc_port_cleans_asset_listener_created_before_failure(self):
        with socket.socket() as busy, socket.socket() as reserve:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            reserve.bind(("127.0.0.1", 0))
            asset_port = reserve.getsockname()[1]
            reserve.close()
            with self.assertRaises(OSError):
                app_runtime.start(self.root, grpc_port=busy.getsockname()[1], asset_port=asset_port)
        # The attempted startup already bound assets; failure must release it.
        with socket.socket() as reusable:
            reusable.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reusable.bind(("127.0.0.1", asset_port))

    def test_missing_master_catalog_and_failed_seed_do_not_lock_in_minimal_profile(self):
        (self.root / "master-json").rmdir()
        with self.assertRaisesRegex(ValueError, "master-json"):
            self.start()
        (self.root / "master-json").mkdir()
        self.seed_error = ValueError("invalid starter catalog")
        with self.assertRaisesRegex(ValueError, "starter catalog"):
            self.start()
        self.assertIsNone(State(self.root / "state.db").snapshot("sandbox"))
        self.seed_error = None
        runtime = self.start()
        self.assertEqual(self.rpc(runtime, "/api.User/Get").user.name, "Starter Manager")

    def test_ui_callback_errors_do_not_stop_serving_and_log_is_bounded(self):
        def broken_callback(_):
            raise RuntimeError("UI is closed")
        runtime = self.start(log_callback=broken_callback)
        for index in range(250):
            runtime._log(str(index) + "x" * 3000)
        status = runtime.status()
        self.assertEqual(len(status["logs"]), 200)
        self.assertTrue(all(len(line) <= 2000 for line in status["logs"]))
        self.assertTrue(status["running"])
        self.assertEqual(self.rpc(runtime, "/api.System/Check").keepAliveTimeMilliseconds, 60000)

    def test_cleanup_failure_retains_owned_grpc_for_retry_and_still_closes_assets(self):
        runtime = self.start()
        grpc_server = runtime._grpc
        with mock.patch.object(grpc_server, "stop", side_effect=RuntimeError("test cleanup failure")):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                runtime.stop()
        self.assertIs(runtime._grpc, grpc_server)
        self.assertIsNone(runtime._asset)
        self.assertTrue(runtime.status()["running"])
        runtime.stop()
        self.assertIsNone(runtime._grpc)
        self.assertFalse(grpc_server.running)

    def test_aes_backend_is_configured_before_the_application_is_created(self):
        callback = lambda encrypt, key, iv, data: data
        with mock.patch("idoly_local.codec.configure_aes") as configure:
            runtime = self.start(aes_cbc=callback)
        configure.assert_called_once_with(callback)
        self.assertTrue(runtime.status()["running"])




class RuntimeDiagnosticsPollingTests(unittest.TestCase):
    def test_status_skips_history_and_explicit_export_copies_it_once(self):
        from copy import deepcopy
        runtime = app_runtime.Runtime("sandbox")
        frames = ["Solis.Benchmark.Polling.Frame" + str(index) for index in range(16)]
        event = {"kind": "exception", "type": "NullReferenceException", "frames": frames}
        raw = json.dumps({"schema": 1, "source": "android-game", "events": [event]}).encode()
        for _ in range(200):
            runtime._diagnostics.receive(raw)
        history_sizes = []
        def observe(snapshot):
            if "events" in snapshot:
                history_sizes.append(len(snapshot["events"]))
            return deepcopy(snapshot)
        with mock.patch("idoly_local.diagnostics.deepcopy", side_effect=observe):
            routine = runtime.status()
            self.assertEqual(history_sizes, [])
            self.assertNotIn("events", routine["client_diagnostics"])
            exported = runtime.diagnostics_snapshot()
            self.assertEqual(history_sizes, [200])
        self.assertEqual(exported["runtime"], routine)
        self.assertEqual(exported["client_diagnostics"]["stored_events"], 200)
        self.assertEqual(exported["client_diagnostics"]["received_events"], 200)
        self.assertEqual(len(exported["client_diagnostics"]["events"]), 200)
        exported["client_diagnostics"]["events"][0]["frames"].clear()
        exported["runtime"]["client_diagnostics"]["latest_exception"]["frames"].clear()
        self.assertEqual(len(runtime.status()["client_diagnostics"]["latest_exception"]["frames"]), 16)


if __name__ == "__main__":
    unittest.main()
