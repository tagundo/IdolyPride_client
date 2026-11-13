"""Bounded photo rejection facts through the real encrypted HTTP/2 route."""
from dataclasses import replace
import json
import socket
import struct
from urllib.parse import unquote

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import ResponseReceived, StreamEnded, TrailersReceived
import pytest

from idoly_local import codec, h2_server
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.h2_server import Context
from idoly_local.photo_shooting import (
    PhotoExpressionRejectionFacts, format_photo_expression_rejection,
)
from idoly_local.rpc import RpcCode, RpcFailure
from test_photo_shooting import (
    game, schema, expression_game, dump, EXPRESSION_CHECK, USER,
)


CANARY = "PRIVATE_user_photo_uuid_token_987654321"
SHAPE = "Matching nonempty photo character/style lists are required"


@pytest.fixture
def diagnostic_app(game, tmp_path):
    provider, state, master, access = expression_game(game, media=True)
    application = Application(provider.schema, state, FixtureStore(tmp_path / "fixtures", provider.schema),
        profile="player", master_dir=master, media_mode=True, photo_scene_access=access)
    token, _ = state.login("player")
    return application, state, token


def request(application, **changes):
    values = dict(photoExpressionId="expression-a", characterIds=["char-a"],
                  costumeIds=["cos-a"], hairIds=["hair-a"])
    values.update(changes)
    return application.schema.request_type(EXPRESSION_CHECK)(**values)


def wire_rejection(application, token, plain, logs):
    server = h2_server.create_server(application, port=0, log_callback=logs.append).start()
    try:
        peer = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
        peer.initiate_connection()
        peer.send_headers(1, [(":method", "POST"), (":scheme", "http"), (":authority", "localhost"),
            (":path", EXPRESSION_CHECK), ("content-type", "application/grpc"), ("te", "trailers"),
            ("x-auth-token", token), ("private-canary", CANARY)])
        encrypted = codec.encode(plain)
        peer.send_data(1, b"\0" + struct.pack(">I", len(encrypted)) + encrypted, end_stream=True)
        headers, ended = {}, False
        with socket.create_connection(server.address, timeout=3) as client:
            client.settimeout(5)
            client.sendall(peer.data_to_send())
            while not ended:
                data = client.recv(65536)
                assert data
                for event in peer.receive_data(data):
                    if isinstance(event, (ResponseReceived, TrailersReceived)):
                        headers.update(event.headers)
                    elif isinstance(event, StreamEnded):
                        ended = True
                outgoing = peer.data_to_send()
                if outgoing:
                    client.sendall(outgoing)
        return headers
    finally:
        server.stop()


@pytest.mark.parametrize("change,reason,detail", (
    ({"costumeIds": []}, "style_shape", SHAPE),
    ({"costumeIds": [CANARY + "\ninjected=1"]}, "style_unknown", "Unknown photo character or outfit"),
    ({"hairIds": ["hair-b"]}, "style_owner", "Photo character and outfit do not match"),
))
def test_actual_encrypted_grpc_rejection_keeps_status_state_and_private_values(
        diagnostic_app, change, reason, detail):
    application, state, token = diagnostic_app
    before, logs = dump(state), []
    headers = wire_rejection(application, token, request(application, **change).SerializeToString(), logs)
    assert headers["grpc-status"] == "3" and unquote(headers["grpc-message"]) == detail
    assert dump(state) == before
    line = next(line for line in logs if line.startswith("RPC " + EXPRESSION_CHECK + " ->"))
    assert "photo_expression_rejection=" + reason in line
    assert "expr=expression-a" in line and "char=[char-a]" in line
    assert ("counts=1/0/1" if not change.get("costumeIds", True) else "counts=1/1/1") in line
    assert len(line) < 400 and "\n" not in line
    private = application.schema.response_type(USER).FromString(state.snapshot("player")[0])
    assert not any(value in line for value in (CANARY, token, private.user.name,
        private.userPublic.serverUserId, private.userPublic.publicUserId,
        "owned-image", "owned-photo") if value)
    if reason == "style_unknown":
        assert "costume=[unknown]" in line


@pytest.mark.parametrize("change,reason,code", (
    ({"photoExpressionId": ""}, "expression_missing", RpcCode.INVALID_ARGUMENT),
    ({"photoExpressionId": CANARY}, "expression_unknown", RpcCode.INVALID_ARGUMENT),
    ({"characterId": "char-b"}, "legacy_conflict", RpcCode.INVALID_ARGUMENT),
    ({"characterIds": ["char-a"] * 40}, "cast_capacity", RpcCode.INVALID_ARGUMENT),
    ({"costumeIds": ["unowned"]}, "style_unowned", RpcCode.PERMISSION_DENIED),
))
def test_actual_application_capture_retains_raw_lengths_and_original_guard(
        diagnostic_app, change, reason, code):
    application, state, token = diagnostic_app
    before, context = dump(state), Context((("x-auth-token", token),))
    with pytest.raises(RpcFailure) as rejected:
        application.handle(EXPRESSION_CHECK, codec.encode(request(application, **change).SerializeToString()), context)
    assert rejected.value.code == code and dump(state) == before
    facts = context._photo_expression_facts
    assert type(facts) is PhotoExpressionRejectionFacts
    text = format_photo_expression_rejection(EXPRESSION_CHECK, code, rejected.value.details,
        facts, application.photo_shootings)
    assert text.startswith("photo_expression_rejection=" + reason + " ") and CANARY not in text
    if reason == "cast_capacity":
        assert facts.counts == (33, 1, 1) and facts.characters == ("char-a",) * 3
        assert "counts=32+/1/1" in text


def test_facts_do_not_normalize_legacy_fields_or_retain_unknown_strings(diagnostic_app):
    application, state, _token = diagnostic_app
    provider, before = application.photo_shootings, dump(state)
    value = request(application, characterIds=[], costumeIds=[], hairIds=[],
                    characterId=CANARY, costumeId=CANARY, hairId=CANARY)
    facts = provider.expression_rejection_facts(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT, value.SerializeToString())
    assert facts == PhotoExpressionRejectionFacts((0, 0, 0), (True, True, True), "expression-a", (), (), ())
    assert CANARY not in repr(facts) and dump(state) == before


@pytest.mark.parametrize("kind", ("string", "dict", "count", "legacy", "shape", "newline", "unknown-id"))
def test_formatter_rejects_forged_context_data(diagnostic_app, kind):
    application, _state, _token = diagnostic_app
    provider = application.photo_shootings
    facts = provider.expression_rejection_facts(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT,
        request(application).SerializeToString())
    forged = {
        "string": CANARY, "dict": {"characters": CANARY},
        "count": replace(facts, counts=(True, 1, 1)),
        "legacy": replace(facts, legacy=(1, False, False)),
        "shape": replace(facts, characters=["char-a"]),
        "newline": replace(facts, expression="expression-a\n" + CANARY),
        "unknown-id": replace(facts, characters=(CANARY,)),
    }[kind]
    text = format_photo_expression_rejection(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT, SHAPE, forged, provider)
    assert text == "photo_expression_rejection=style_shape facts=unavailable" and CANARY not in text


def test_corrupt_oversized_and_unsafe_master_ids_fail_closed(diagnostic_app):
    application, _state, _token = diagnostic_app
    provider = application.photo_shootings
    (provider.catalog.directory / "Character.json").write_text(json.dumps([{"id": "char-a"}, {"id": CANARY + "\n"}]))
    (provider.catalog.directory / "Costume.json").write_text("{" + CANARY)
    (provider.catalog.directory / "Hair.json").write_bytes(b" " * (1024 * 1024 + 1))
    facts = provider.expression_rejection_facts(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT,
        request(application).SerializeToString())
    assert facts.characters == facts.costumes == facts.hairs == ("unknown",)
    text = format_photo_expression_rejection(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT, CANARY, facts, provider)
    assert "photo_expression_rejection=unclassified" in text and CANARY not in text


def test_long_canonical_ids_are_omitted_whole_to_keep_complete_log_below_400(diagnostic_app):
    application, _state, _token = diagnostic_app
    provider = application.photo_shootings
    identities = tuple(letter * 128 for letter in ("e", "c", "o", "h"))
    for table, identity in zip(("PhotoExpression", "Character", "Costume", "Hair"), identities):
        provider.catalog.loaded[table] = [{"id": identity}]
    facts = PhotoExpressionRejectionFacts((3, 3, 3), (False,) * 3, identities[0],
        (identities[1],) * 3, (identities[2],) * 3, (identities[3],) * 3)
    text = format_photo_expression_rejection(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT, SHAPE, facts, provider)
    assert "[omitted]" in text and len(text) <= 320
    assert len("RPC " + EXPRESSION_CHECK + " -> INVALID_ARGUMENT [" + text + "]") < 400
    for identity in identities:
        assert identity in text or identity[:80] not in text


@pytest.mark.parametrize("plain", (b"\x0a\x80", b"x" * (64 * 1024 + 1), CANARY))
def test_invalid_or_oversized_plaintext_has_no_retained_facts(diagnostic_app, plain):
    application, _state, _token = diagnostic_app
    provider = application.photo_shootings
    assert provider.expression_rejection_facts(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT, plain) is None
    assert format_photo_expression_rejection(EXPRESSION_CHECK, RpcCode.INVALID_ARGUMENT, CANARY,
        None, provider) == "photo_expression_rejection=unclassified facts=unavailable"


def test_other_routes_success_and_diagnostic_faults_preserve_original_behavior(diagnostic_app, monkeypatch):
    application, state, token = diagnostic_app
    provider, context = application.photo_shootings, Context((("x-auth-token", token),))
    before = dump(state)
    result = application.handle(EXPRESSION_CHECK, codec.encode(request(application).SerializeToString()), context)
    assert application.schema.response_type(EXPRESSION_CHECK).FromString(result).HasField("commonResponse")
    assert not hasattr(context, "_photo_expression_facts") and dump(state) == before
    assert provider.expression_rejection_facts(USER, RpcCode.INVALID_ARGUMENT, b"") is None
    assert format_photo_expression_rejection(USER, RpcCode.INVALID_ARGUMENT, CANARY) is None
    assert format_photo_expression_rejection(EXPRESSION_CHECK, RpcCode.INTERNAL, CANARY) is None
    def broken(*_args):
        raise RuntimeError(CANARY)
    monkeypatch.setattr(provider, "expression_rejection_facts", broken)
    logs = []
    headers = wire_rejection(application, token, request(application, costumeIds=[]).SerializeToString(), logs)
    assert headers["grpc-status"] == "3" and unquote(headers["grpc-message"]) == SHAPE
    assert dump(state) == before and all(CANARY not in line for line in logs)
