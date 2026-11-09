import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import pytest

from idoly_local.catalog import FixtureStore, import_response


@pytest.fixture
def schema():
    file = descriptor_pb2.FileDescriptorProto(name="catalog-test.proto", package="api", syntax="proto3")
    message = file.message_type.add(name="Response")
    message.field.add(name="name", number=1, label=1, type=9)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    response = message_factory.GetMessageClass(pool.FindMessageTypeByName("api.Response"))
    routes = {"/api.User/Get": SimpleNamespace(client_streaming=False, server_streaming=False),
              "/api.Auth/Login": SimpleNamespace(client_streaming=False, server_streaming=False),
              "/api.User/Stream": SimpleNamespace(client_streaming=False, server_streaming=True)}
    return SimpleNamespace(method=lambda path: routes[path], response_type=lambda _: response, response=response)


def write_manifest(root, entries):
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({"schema_version": 1, "responses": entries}))


def test_exact_precedes_wildcard_and_empty_response_is_not_missing(tmp_path, schema):
    (tmp_path / "fallback.pb").write_bytes(schema.response(name="fallback").SerializeToString())
    (tmp_path / "empty.pb").write_bytes(b"")
    write_manifest(tmp_path, [
        {"method": "/api.User/Get", "file": "fallback.pb"},
        {"method": "/api.User/Get", "file": "empty.pb", "request_sha256": hashlib.sha256(b"exact").hexdigest()},
    ])
    store = FixtureStore(tmp_path, schema)
    assert store.get("/api.User/Get", b"exact") == b""
    assert store.get("/api.User/Get", b"other") == schema.response(name="fallback").SerializeToString()
    assert store.get("/api.User/Missing", b"") is None


@pytest.mark.parametrize("filename", ["../outside.pb", "/tmp/outside.pb", "responses/../../outside.pb", "..\\outside.pb"])
def test_rejects_file_escape(tmp_path, schema, filename):
    write_manifest(tmp_path, [{"method": "/api.User/Get", "file": filename}])
    with pytest.raises(ValueError, match="relative|inside"):
        FixtureStore(tmp_path, schema)


def test_rejects_symlink_escape(tmp_path, schema):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    outside = tmp_path / "outside.pb"
    outside.write_bytes(b"")
    (fixtures / "escape.pb").symlink_to(outside)
    write_manifest(fixtures, [{"method": "/api.User/Get", "file": "escape.pb"}])
    with pytest.raises(ValueError, match="inside"):
        FixtureStore(fixtures, schema)


@pytest.mark.parametrize("method,match", [("User/Get", "complete"), ("/api.User/Unknown", "Unknown"),
                                         ("/api.User/Stream", "unary"), ("/api.Auth/Login", "Auth")])
def test_rejects_invalid_methods(tmp_path, schema, method, match):
    (tmp_path / "response.pb").write_bytes(b"")
    write_manifest(tmp_path, [{"method": method, "file": "response.pb"}])
    with pytest.raises(ValueError, match=match):
        FixtureStore(tmp_path, schema)


def test_rejects_duplicate_routes_and_malformed_protobuf(tmp_path, schema):
    (tmp_path / "response.pb").write_bytes(b"")
    entry = {"method": "/api.User/Get", "file": "response.pb"}
    write_manifest(tmp_path, [entry, entry])
    with pytest.raises(ValueError, match="Duplicate"):
        FixtureStore(tmp_path, schema)
    write_manifest(tmp_path, [entry])
    (tmp_path / "response.pb").write_bytes(b"\x0a\x05x")
    with pytest.raises(ValueError, match="Malformed"):
        FixtureStore(tmp_path, schema)


def test_import_hashes_request_and_replaces_only_matching_route(tmp_path, schema):
    output = tmp_path / "fixtures"
    source = tmp_path / "source.pb"
    request = tmp_path / "request.pb"
    request.write_bytes(b"private-request-contents")
    source.write_bytes(schema.response(name="wildcard").SerializeToString())
    import_response(source, output, schema, "/api.User/Get")
    source.write_bytes(b"")
    imported = import_response(source, output, schema, "/api.User/Get", request=request)
    assert imported.read_bytes() == b""
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest["responses"]) == 2
    assert manifest["responses"][1]["request_sha256"] == hashlib.sha256(request.read_bytes()).hexdigest()
    for path in output.rglob("*"):
        if path.is_file():
            assert request.read_bytes() not in path.read_bytes()
    source.write_bytes(schema.response(name="replacement").SerializeToString())
    import_response(source, output, schema, "/api.User/Get", request=request)
    store = FixtureStore(output, schema)
    assert len(store.manifest["responses"]) == 2
    assert store.get("/api.User/Get", request.read_bytes()) == source.read_bytes()
    assert store.get("/api.User/Get", b"other") == schema.response(name="wildcard").SerializeToString()


def test_failed_import_preserves_existing_manifest(tmp_path, schema):
    source = tmp_path / "source.pb"
    output = tmp_path / "fixtures"
    source.write_bytes(b"")
    import_response(source, output, schema, "/api.User/Get")
    before = (output / "manifest.json").read_bytes()
    source.write_bytes(b"\x0a\x05x")
    with pytest.raises(ValueError, match="Malformed"):
        import_response(source, output, schema, "/api.User/Get")
    assert (output / "manifest.json").read_bytes() == before


def test_empty_catalog(tmp_path, schema):
    assert FixtureStore(tmp_path / "absent", schema).get("/api.User/Get", b"") is None


def test_import_decrypts_wire_response(tmp_path, schema):
    from idoly_local.codec import encode

    payload = schema.response(name="encrypted fixture").SerializeToString()
    source = tmp_path / "wire.bin"
    source.write_bytes(encode(payload, ticks=621355968000000000))
    output = tmp_path / "fixtures"
    imported = import_response(source, output, schema, "/api.User/Get", wire=True)
    assert imported.read_bytes() == payload
    assert FixtureStore(output, schema).get("/api.User/Get", b"") == payload


def test_import_rejects_auth_before_creating_output(tmp_path, schema):
    source = tmp_path / "token.pb"
    source.write_bytes(schema.response(name="private-token").SerializeToString())
    output = tmp_path / "fixtures"
    with pytest.raises(ValueError, match="Auth"):
        import_response(source, output, schema, "/api.Auth/Login")
    assert not output.exists()
