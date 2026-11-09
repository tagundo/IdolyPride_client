"""Preservation uses existing session headers and never performs login or retries."""
from pathlib import Path
import json
import stat

import grpc
import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from idoly_local import codec
from idoly_local.catalog import FixtureStore
from idoly_local.collect import COLLECT_METHODS, OFFICIAL_TARGET, CollectorError, collect_session
from idoly_local.schema import Schema


@pytest.fixture
def schema():
    file = descriptor_pb2.FileDescriptorProto(name="collector.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    home = file.message_type.add(name="HomeEnterRequest")
    home.field.add(name="skipUpdate", number=1, type=8, label=1)
    response = file.message_type.add(name="Response")
    response.field.add(name="contents", number=1, type=9, label=1)
    pack = file.message_type.add(name="MasterTagPack")
    for name, number, kind in [("type", 1, 9), ("fileName", 2, 9), ("fileSize", 3, 5),
                               ("cryptoKey", 4, 9), ("downloadUrl", 5, 9)]:
        pack.field.add(name=name, number=number, type=kind, label=1)
    tag = file.message_type.add(name="MasterTag")
    tag.field.add(name="version", number=1, type=9, label=1)
    tag.field.add(name="masterTagPacks", number=2, type=11, type_name=".api.MasterTagPack", label=3)
    master = file.message_type.add(name="MasterGetResponse")
    master.field.add(name="masterTag", number=1, type=11, type_name=".api.MasterTag", label=1)
    for service_name, method_name in [("System", "Check"), ("Master", "Get"), ("User", "Get"),
                                      ("Home", "Enter"), ("Dokan", "List"), ("Notice", "List")]:
        service = file.service.add(name=service_name)
        service.method.add(name=method_name,
                           input_type=".api.HomeEnterRequest" if service_name == "Home" else ".api.Empty",
                           output_type=".api.MasterGetResponse" if service_name == "Master" else ".api.Response")
    pool = descriptor_pool.DescriptorPool()
    loaded = pool.Add(file)
    return Schema(pool, [loaded], "collector-test")


@pytest.fixture
def metadata_file(tmp_path):
    file = tmp_path / "existing-session.json"
    file.write_text(json.dumps({"x-app-version": "6.1.1", "x-auth-token": "private-session-token-123",
                                "x-master-version": "existing-master", "x-device": "private-device-id"}))
    return file


class Call:
    def __init__(self, *, status=grpc.StatusCode.OK, initial=(), trailing=()):
        self.status, self.initial, self.trailing = status, initial, trailing

    def code(self):
        return self.status

    def initial_metadata(self):
        return self.initial

    def trailing_metadata(self):
        return self.trailing


class FailedCall(grpc.RpcError, Call):
    def __init__(self, **kwargs):
        Call.__init__(self, **kwargs)

    def details(self):
        return "never print remote token private-session-token-123"


class Channel:
    def __init__(self, responses):
        self.responses, self.invocations, self.closed = responses, [], False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def unary_unary(self, method):
        channel = self

        class Method:
            def with_call(self, request, *, metadata, timeout):
                channel.invocations.append((method, request, metadata, timeout))
                result = channel.responses[method]
                if isinstance(result, Exception):
                    raise result
                return result

        return Method()


def install_channel(monkeypatch, schema, overrides=None):
    responses = {}
    for method in COLLECT_METHODS:
        response = schema.response_type(method)()
        if method == "/api.Master/Get":
            response.masterTag.version = "preserved-master"
        else:
            response.contents = "preserved response " + method
        responses[method] = (codec.encode(response.SerializeToString()), Call())
    responses.update(overrides or {})
    channel = Channel(responses)

    def secure_channel(target, credentials, *, options):
        assert target == OFFICIAL_TARGET
        assert credentials is not None
        assert dict(options)["grpc.enable_retries"] == 0
        return channel

    monkeypatch.setattr(grpc, "secure_channel", secure_channel)
    return channel


def test_captures_only_allowlist_without_exporting_session_metadata(tmp_path, schema, metadata_file, monkeypatch):
    channel = install_channel(monkeypatch, schema)
    output = tmp_path / "preservation"
    result = collect_session(schema, metadata_file, output)
    assert result == {"captured": list(COLLECT_METHODS)}
    assert [call[0] for call in channel.invocations] == list(COLLECT_METHODS)
    assert channel.closed
    for method, request, metadata, timeout in channel.invocations:
        assert dict(metadata)["x-auth-token"] == "private-session-token-123"
        assert timeout == 15
        parsed = schema.request_type(method).FromString(codec.decode(request))
        if method == "/api.Home/Enter":
            assert parsed.skipUpdate is True
        else:
            assert request == b""
    store = FixtureStore(output / "fixtures", schema)
    assert len(store.manifest["responses"]) == 5
    for method in COLLECT_METHODS:
        assert store.get(method, b"") is not None
    assert json.loads((output / "master-tag.json").read_text()) == {"version": "preserved-master"}
    for file in output.rglob("*"):
        if file.is_file():
            assert b"private-session-token-123" not in file.read_bytes()
            assert b"private-device-id" not in file.read_bytes()
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert not list(output.glob(".collect-*"))


@pytest.mark.parametrize("headers", [
    [("x-error-code", "1003")], [("x-error-code", "401")],
    [("x-error-code", "private-session-token-123")],
])
@pytest.mark.parametrize("location", ["initial", "trailing"])
def test_application_errors_reject_payload_and_preserve_earlier_results(
        tmp_path, schema, metadata_file, monkeypatch, headers, location):
    failure = Call(**{location: headers})
    method = "/api.User/Get"
    channel = install_channel(monkeypatch, schema, {method: (b"", failure)})
    output = tmp_path / "preservation"
    with pytest.raises(CollectorError) as error:
        collect_session(schema, metadata_file, output)
    assert method in str(error.value)
    assert "private-session-token-123" not in str(error.value)
    assert "application codes" in str(error.value)
    assert len(channel.invocations) == 2
    assert channel.closed
    store = FixtureStore(output / "fixtures", schema)
    assert store.get("/api.Master/Get", b"") is not None
    assert store.get(method, b"") is None
    assert (output / "master-tag.json").exists()


def test_zero_application_code_is_success(tmp_path, schema, metadata_file, monkeypatch):
    channel = install_channel(monkeypatch, schema)
    for method, (raw, _) in channel.responses.items():
        channel.responses[method] = raw, Call(initial=[("x-error-code", "0")], trailing=[("x-error-code", "000")])
    assert len(collect_session(schema, metadata_file, tmp_path / "out")["captured"]) == 5


def test_rpc_failure_is_sanitized_and_never_retried(tmp_path, schema, metadata_file, monkeypatch):
    method = "/api.User/Get"
    channel = install_channel(monkeypatch, schema, {method: FailedCall(status=grpc.StatusCode.UNAUTHENTICATED)})
    with pytest.raises(CollectorError, match="UNAUTHENTICATED") as error:
        collect_session(schema, metadata_file, tmp_path / "out")
    assert "private-session-token-123" not in str(error.value)
    assert len(channel.invocations) == 2


@pytest.mark.parametrize("payload", [b"bad envelope", codec.encode(b"\x0a\x80")])
def test_malformed_response_not_saved(tmp_path, schema, metadata_file, monkeypatch, payload):
    install_channel(monkeypatch, schema, {"/api.Master/Get": (payload, Call())})
    output = tmp_path / "out"
    with pytest.raises(CollectorError, match="malformed response"):
        collect_session(schema, metadata_file, output)
    assert not output.exists()


def test_non_ok_status_not_saved(tmp_path, schema, metadata_file, monkeypatch):
    install_channel(monkeypatch, schema, {"/api.Master/Get": (b"", Call(status=grpc.StatusCode.PERMISSION_DENIED))})
    output = tmp_path / "out"
    with pytest.raises(CollectorError, match="PERMISSION_DENIED"):
        collect_session(schema, metadata_file, output)
    assert not output.exists()


@pytest.mark.parametrize("target", ["localhost:443", "api.game-idolypride.jp.evil.test:443",
                                     "https://api.game-idolypride.jp:443", "api.game-idolypride.jp:80"])
def test_credentials_never_sent_to_other_target(tmp_path, schema, metadata_file, monkeypatch, target):
    monkeypatch.setattr(grpc, "secure_channel", lambda *args: pytest.fail("must not connect"))
    with pytest.raises(CollectorError, match="official TLS target"):
        collect_session(schema, metadata_file, tmp_path / "out", target=target)


@pytest.mark.parametrize("metadata", [
    [], {"x-auth-token": "secret"}, {"x-app-version": "6.1.1", "x-auth-token": "", "x-master-version": "v"},
    {"x-app-version": "6.1.1", "x-auth-token": "secret\r\nheader", "x-master-version": "v"},
    {"x-app-version": "6.1.1", "x-auth-token": "secret", "x-master-version": "v", "bad\nkey": "x"},
    {"x-app-version": "6.1.1", "x-auth-token": 42, "x-master-version": "v"},
])
def test_invalid_metadata_fails_before_connection(tmp_path, schema, metadata_file, monkeypatch, metadata):
    metadata_file.write_text(json.dumps(metadata))
    monkeypatch.setattr(grpc, "secure_channel", lambda *args: pytest.fail("must not connect"))
    with pytest.raises(CollectorError):
        collect_session(schema, metadata_file, tmp_path / "out")


class PublicResponse:
    status = 200

    def __init__(self, payload, url):
        from io import BytesIO
        self.stream, self.url = BytesIO(payload), url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()

    def geturl(self):
        return self.url

    def read(self, size):
        return self.stream.read(size)


def public_master(monkeypatch, schema, *, pack_urls=None, bodies=None):
    import idoly_local.collect as collector
    urls = pack_urls or ["https://climaster.game-idolypride.jp/master/first",
                         "https://climaster.game-idolypride.jp/master/second"]
    response = schema.response_type("/api.Master/Get")()
    response.masterTag.version = "public-master-v1"
    contents = [b"first encrypted raw pack", b"second raw pack"]
    for i, (url, payload) in enumerate(zip(urls, contents)):
        response.masterTag.masterTagPacks.add(type=f"Table{i}", fileName=f"filename-is-not-sha-{i}",
            fileSize=len(payload), cryptoKey=f"pack-key-{i}", downloadUrl=url)
    channel = install_channel(monkeypatch, schema, {
        "/api.Master/Get": (codec.encode(response.SerializeToString()), Call())})
    downloads = []

    class Opener:
        def open(self, request, *, timeout):
            downloads.append(request.full_url)
            assert not request.has_header("Authorization")
            assert timeout == 30
            index = urls.index(request.full_url)
            payload = bodies[index] if bodies is not None else contents[index]
            return PublicResponse(payload, request.full_url)

    monkeypatch.setattr(collector, "build_opener", lambda *handlers: Opener())
    return channel, downloads, contents


def test_anonymous_master_download_and_hash_validated_resume(tmp_path, schema, monkeypatch):
    import hashlib
    from idoly_local.collect import archive_public_master
    channel, downloads, contents = public_master(monkeypatch, schema)
    output = tmp_path / "public"
    result = archive_public_master(schema, output, workers=2)
    assert result == {"master_version": "public-master-v1", "packs": 2, "downloaded": 2,
                      "reused": 0, "bytes": sum(map(len, contents)), "complete": True}
    assert len(channel.invocations) == 1
    method, request, metadata, timeout = channel.invocations[0]
    assert method == "/api.Master/Get" and request == b"" and timeout == 15
    assert metadata == [("x-app-version", "6.1.1")]
    report = json.loads((output / "archive-report.json").read_text())
    assert report["complete"] and report["completed_packs"] == 2
    for i, payload in enumerate(contents):
        path = output / "assets/master" / f"filename-is-not-sha-{i}"
        assert path.read_bytes() == payload
        assert report["packs"][f"Table{i}"]["sha256"] == hashlib.sha256(payload).hexdigest()
    report_bytes = (output / "archive-report.json").read_bytes()
    assert b"pack-key-" not in report_bytes and b"https://" not in report_bytes
    assert schema.response_type(method).FromString((output / "response.pb").read_bytes()).masterTag.version == "public-master-v1"
    for file in output.rglob("*"):
        if file.is_file():
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert not list((output / "assets/master").glob(".master-pack-*"))
    downloads.clear()
    resumed = archive_public_master(schema, output)
    assert resumed["reused"] == 2 and resumed["downloaded"] == 0
    assert downloads == []
    # Same size is insufficient: verify the recorded SHA-256 before reuse.
    (output / "assets/master/filename-is-not-sha-0").write_bytes(b"x" * len(contents[0]))
    resumed = archive_public_master(schema, output)
    assert resumed["reused"] == 1 and resumed["downloaded"] == 1
    assert len(downloads) == 1


def test_master_file_without_recorded_hash_is_downloaded_again(tmp_path, schema, monkeypatch):
    from idoly_local.collect import archive_public_master
    _, downloads, contents = public_master(monkeypatch, schema)
    output = tmp_path / "public"
    directory = output / "assets/master"
    directory.mkdir(parents=True)
    (directory / "filename-is-not-sha-0").write_bytes(contents[0])
    archive_public_master(schema, output)
    assert len(downloads) == 2


def test_master_partial_size_failure_retains_valid_files_for_resume(tmp_path, schema, monkeypatch):
    from idoly_local.collect import archive_public_master
    public_master(monkeypatch, schema, bodies=[b"too short", b"second raw pack"])
    output = tmp_path / "public"
    with pytest.raises(CollectorError, match="incomplete.*1/2"):
        archive_public_master(schema, output)
    report = json.loads((output / "archive-report.json").read_text())
    assert not report["complete"]
    assert set(report["packs"]) == {"Table1"}
    assert not (output / "assets/master/filename-is-not-sha-0").exists()
    assert not list((output / "assets/master").glob(".master-pack-*"))
    _, downloads, _ = public_master(monkeypatch, schema)
    result = archive_public_master(schema, output)
    assert result["reused"] == 1 and result["downloaded"] == 1
    assert len(downloads) == 1


@pytest.mark.parametrize("url", ["https://unexpected.invalid/pack", "http://climaster.game-idolypride.jp/pack",
                                  "https://user:password@climaster.game-idolypride.jp/pack",
                                  "https://climaster.game-idolypride.jp/pack?token=secret"])
def test_master_rejects_nonpublic_pack_urls_before_download(tmp_path, schema, monkeypatch, url):
    from idoly_local.collect import archive_public_master
    _, downloads, _ = public_master(monkeypatch, schema, pack_urls=[url])
    with pytest.raises(CollectorError, match="official public HTTPS host") as error:
        archive_public_master(schema, tmp_path / "public")
    assert "secret" not in str(error.value) and "password" not in str(error.value)
    assert downloads == []
    assert not (tmp_path / "public").exists()


def test_master_redirect_rejected_before_sending_destination():
    from urllib.request import Request
    from idoly_local.collect import _PublicMasterRedirect
    redirect = _PublicMasterRedirect()
    original = Request("https://climaster.game-idolypride.jp/pack")
    with pytest.raises(CollectorError, match="official public HTTPS host"):
        redirect.redirect_request(original, None, 302, "Found", {}, "https://unexpected.invalid/pack")
    assert redirect.redirect_request(original, None, 302, "Found", {},
        "https://climaster.game-idolypride.jp/new-pack").full_url.endswith("/new-pack")


def test_anonymous_master_application_error_does_not_write(tmp_path, schema, monkeypatch):
    from idoly_local.collect import archive_public_master
    install_channel(monkeypatch, schema, {"/api.Master/Get": (b"", Call(trailing=[("x-error-code", "1002")]))})
    with pytest.raises(CollectorError, match="1002"):
        archive_public_master(schema, tmp_path / "public")
    assert not (tmp_path / "public").exists()
