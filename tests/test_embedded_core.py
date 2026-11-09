"""Exercise the portable crypto/schema and transactional game-update boundaries."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

from Crypto.Cipher import AES
from google.protobuf import descriptor_pb2
import pytest

from idoly_local import codec
from idoly_local.state import State


def test_platform_cipher_uses_same_wire_bytes_without_adding_padding():
    expected = codec.encode(b"portable protobuf", ticks=123)
    calls = []

    def platform_cipher(encrypt, key, iv, data):
        assert len(data) % 16 == 0
        calls.append(encrypt)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.encrypt(data) if encrypt else cipher.decrypt(data)

    try:
        codec.configure_aes(platform_cipher)
        assert codec.encode(b"portable protobuf", ticks=123) == expected
        assert codec.decode(expected) == b"portable protobuf"
        assert calls == [True, False]
        codec.configure_aes(lambda *_: b"bad length")
        with pytest.raises(codec.CodecError, match="length"):
            codec.encode(b"payload")
    finally:
        codec.configure_aes()


def test_pure_python_protobuf_loads_and_exports_the_same_schema(tmp_path):
    file = descriptor_pb2.FileDescriptorProto(name="portable.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    file.service.add(name="System").method.add(name="Check", input_type=".api.Empty", output_type=".api.Empty")
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    path = tmp_path / "schema.pb"
    path.write_bytes(descriptors.SerializeToString())
    code = "from idoly_local.schema import Schema;from pathlib import Path;s=Schema.from_descriptor_set(Path(__import__('sys').argv[1]));assert len(s.methods)==1;s.export(Path(__import__('sys').argv[2]))"
    subprocess.run([sys.executable, "-c", code, str(path), str(tmp_path / "export.pb")],
                   env=os.environ | {"PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "python"}, check=True)
    assert (tmp_path / "export.pb").read_bytes() == descriptors.SerializeToString(deterministic=True)


def test_game_updates_serialize_and_keep_the_local_session(tmp_path):
    state = State(tmp_path / "state.db")
    state.save_snapshot("local", b"0", "schema")
    token, _ = state.login("local")

    def increment(_):
        return state.mutate_snapshot("local", "schema", lambda b: str(int(b) + 1).encode())

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(increment, range(20)))
    assert state.snapshot("local") == (b"20", "schema")
    assert state.authenticated(token, "local")
    state.mutate_snapshot("local", "schema", lambda b: b, setting_info=b"settings")
    assert State(state.path).settings("local") == (b"settings", "schema")


def test_bad_game_update_rolls_back_snapshot_and_settings(tmp_path):
    state = State(tmp_path / "state.db")
    state.save_snapshot("local", b"original", "schema")
    state.mutate_snapshot("local", "schema", lambda b: b, setting_info=b"old settings")
    with pytest.raises(ValueError):
        state.mutate_snapshot("local", "schema", lambda _: None, setting_info=b"replacement")
    assert state.snapshot("local") == (b"original", "schema")
    assert state.settings("local") == (b"old settings", "schema")
    with pytest.raises(ValueError, match="different schema"):
        state.mutate_snapshot("local", "wrong", lambda _: b"bad")
