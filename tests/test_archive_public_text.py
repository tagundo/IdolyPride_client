import hashlib
import importlib.util
import json
from pathlib import Path

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool
import pytest

from idoly_local import codec
from idoly_local.catalog import FixtureStore
from idoly_local.schema import Schema

SOURCE = Path(__file__).resolve().parents[1] / "tools/archive_public_text.py"
SPEC = importlib.util.spec_from_file_location("archive_public_text_tool", SOURCE)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


@pytest.fixture
def schema():
    file = descriptor_pb2.FileDescriptorProto(name="public_text.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    for enum_name, prefix, count in [("RuleType", "Rule", 7), ("HelpType", "Help", 4)]:
        enum = file.enum_type.add(name=enum_name)
        for i in range(count + 1):
            enum.value.add(name=f"{prefix}_{i}", number=i)
    rule = file.message_type.add(name="RuleRequest")
    rule.field.add(name="ruleType", number=1, type=14, type_name=".api.RuleType", label=1)
    help_request = file.message_type.add(name="HelpRequest")
    help_request.field.add(name="helpType", number=1, type=14, type_name=".api.HelpType", label=1)
    response = file.message_type.add(name="PublicResponse")
    response.field.add(name="text", number=1, type=9, label=1)
    system = file.service.add(name="System")
    system.method.add(name="Check", input_type=".api.Empty", output_type=".api.PublicResponse")
    master = file.service.add(name="Master")
    master.method.add(name="Rule", input_type=".api.RuleRequest", output_type=".api.PublicResponse")
    master.method.add(name="GetHelpCategory", input_type=".api.HelpRequest", output_type=".api.PublicResponse")
    pool = descriptor_pool.DescriptorPool()
    descriptor = pool.Add(file)
    return Schema(pool, [descriptor], "public-text-fixture")


class Call:
    def __init__(self, initial=(), trailing=(), status=grpc.StatusCode.OK):
        self.initial, self.trailing, self.status = initial, trailing, status

    def initial_metadata(self):
        return self.initial

    def trailing_metadata(self):
        return self.trailing

    def code(self):
        return self.status


class Channel:
    def __init__(self, schema, overrides=None):
        self.schema, self.overrides = schema, overrides or {}
        self.calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def unary_unary(self, method):
        channel = self

        class Method:
            def with_call(self, raw, *, metadata, timeout):
                request = channel.schema.request_type(method).FromString(codec.decode(raw))
                value = request.ruleType if method == tool.RULE else request.helpType
                channel.calls.append((method, value, metadata, timeout))
                if (method, value) in channel.overrides:
                    return channel.overrides[method, value]
                payload = channel.schema.response_type(method)(text=f"public response {method} {value}").SerializeToString()
                return codec.encode(payload), Call()

        return Method()


def install_channel(monkeypatch, schema, overrides=None):
    channel = Channel(schema, overrides)

    def secure_channel(target, credentials, *, options):
        assert target == "api.game-idolypride.jp:443"
        assert dict(options)["grpc.enable_retries"] == 0
        return channel

    monkeypatch.setattr(grpc, "secure_channel", secure_channel)
    return channel


def test_collects_exact_anonymous_contract_with_request_keyed_public_responses(tmp_path, schema, monkeypatch):
    channel = install_channel(monkeypatch, schema)
    output = tmp_path / "public-fixtures"
    assert tool.archive_public_text(schema, output) == {
        "anonymous": True, "captured_responses": 10, "rules": 7, "help_types": [1, 2, 3]}
    expected = [(tool.RULE, value) for value in range(1, 8)] + [(tool.HELP, value) for value in (1, 2, 3)]
    assert [(method, value) for method, value, _, _ in channel.calls] == expected
    assert channel.closed
    assert all(metadata == [("x-app-version", "6.1.1")] and timeout == 15
               for _, _, metadata, timeout in channel.calls)
    store = FixtureStore(output, schema)
    assert len(store.manifest["responses"]) == 10
    for method, value in expected:
        field = "ruleType" if method == tool.RULE else "helpType"
        request = schema.request_type(method)(**{field: value}).SerializeToString()
        response = store.get(method, request)
        assert response is not None
        assert schema.response_type(method).FromString(response).text.endswith(str(value))
        assert any(entry.get("request_sha256") == hashlib.sha256(request).hexdigest()
                   and entry["method"] == method for entry in store.manifest["responses"])
    recovery = schema.request_type(tool.HELP)(helpType=4).SerializeToString()
    assert store.get(tool.HELP, recovery) is None
    assert not list(tmp_path.glob(".public-text-*"))
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.rglob("*") if path.is_file())


@pytest.mark.parametrize("location", ["initial", "trailing"])
def test_application_error_is_not_saved_or_retried_and_prior_success_is_preserved(
        tmp_path, schema, monkeypatch, location):
    failure = Call(**{location: [("x-error-code", "1003")]})
    channel = install_channel(monkeypatch, schema, {(tool.RULE, 2): (b"must not be saved", failure)})
    output = tmp_path / "public-fixtures"
    with pytest.raises(tool.CollectorError, match="1003"):
        tool.archive_public_text(schema, output)
    assert len(channel.calls) == 2 and channel.closed
    store = FixtureStore(output, schema)
    assert store.get(tool.RULE, schema.request_type(tool.RULE)(ruleType=1).SerializeToString()) is not None
    assert store.get(tool.RULE, schema.request_type(tool.RULE)(ruleType=2).SerializeToString()) is None


@pytest.mark.parametrize("raw", [b"bad encrypted body", codec.encode(b"\x0a\x80")])
def test_malformed_response_is_rejected_before_fixture_creation(tmp_path, schema, monkeypatch, raw):
    install_channel(monkeypatch, schema, {(tool.RULE, 1): (raw, Call())})
    with pytest.raises(tool.CollectorError, match="malformed response"):
        tool.archive_public_text(schema, tmp_path / "fixtures")
    assert not (tmp_path / "fixtures").exists()


def test_empty_successful_rule_response_is_preserved_without_invented_fallback(tmp_path, schema, monkeypatch):
    install_channel(monkeypatch, schema, {(tool.RULE, 4): (b"", Call())})
    output = tmp_path / "fixtures"
    tool.archive_public_text(schema, output)
    request = schema.request_type(tool.RULE)(ruleType=4).SerializeToString()
    assert FixtureStore(output, schema).get(tool.RULE, request) == b""


def test_cli_outputs_only_summary_and_supports_explicit_descriptor(tmp_path, schema, monkeypatch, capsys):
    install_channel(monkeypatch, schema)
    monkeypatch.setattr(tool.Schema, "from_descriptor_set", lambda path: schema)
    assert tool.main(["--descriptor-set", str(tmp_path / "descriptor.pb"),
                      "--output", str(tmp_path / "fixtures")]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["captured_responses"] == 10
    assert "public response" not in captured.out
    assert captured.err == ""
