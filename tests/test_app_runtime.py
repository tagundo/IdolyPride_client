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
from urllib.request import urlopen

import grpc
from google.protobuf import descriptor_pb2

from idoly_local import app_runtime, codec
from idoly_local.gameplay import repair_starter_roster
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
    (root / "master-json").mkdir()
    return Schema.from_descriptor_set(schema_file)


class _Application:
    created = []

    def __init__(self, schema, state, fixtures, profile, master_response, master_dir):
        self.schema, self.state, self.profile = schema, state, profile
        self.master_response, self.master_dir = master_response, master_dir
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
                                                    repair_starter_roster=repair_starter_roster),
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

    def test_existing_imported_snapshot_is_not_seeded_again(self):
        state = State(self.root / "state.db")
        new_profile(state, self.schema, "sandbox", "Preserved Manager")
        before = state.snapshot("sandbox")
        runtime = self.start()
        self.assertEqual(self.rpc(runtime, "/api.User/Get").user.name, "Preserved Manager")
        self.assertEqual(state.snapshot("sandbox"), before)
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


if __name__ == "__main__":
    unittest.main()
