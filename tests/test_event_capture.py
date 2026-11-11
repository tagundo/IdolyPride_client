"""Real 6.1.1 preservation boundaries, private exports and no implicit actions."""
from datetime import timedelta
import json
from pathlib import Path
import stat

import grpc
import pytest

from idoly_local import codec, event_capture as event
from idoly_local.schema import Schema

TOKEN = "PRIVATE_AUTH_TOKEN_DO_NOT_EXPORT"
PHOTO = "PRIVATE_OWNED_PHOTO"
OPPONENT = "PRIVATE_OPPONENT"


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Original 6.1.1 descriptor unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def metadata(tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"x-app-version": "6.1.1", "x-auth-token": TOKEN,
                                "x-master-version": "master-current"}))
    return path


class Call:
    def __init__(self, status=grpc.StatusCode.OK, headers=()):
        self.status, self.headers = status, headers

    def code(self):
        return self.status

    def initial_metadata(self):
        return self.headers

    def trailing_metadata(self):
        return ()

    def details(self):
        raise AssertionError("Remote error details must never be read")


class RpcFailure(grpc.RpcError):
    def details(self):
        return TOKEN


def install(monkeypatch, schema, *, fail=None, app_error=None, changed_master=None,
            duplicate=False, reflected=False, changed_account=False):
    class Channel:
        def __init__(self):
            self.calls, self.closed, self.user_count = [], False, 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def unary_unary(self, method):
            owner = self
            class Method:
                def with_call(self, raw, *, metadata, timeout):
                    request = schema.request_type(method).FromString(codec.decode(raw))
                    owner.calls.append((method, request, metadata, timeout))
                    if method == fail:
                        raise RpcFailure()
                    response = schema.response_type(method)()
                    if method == event.MASTER:
                        response.masterTag.version = "master-current"
                    elif method == event.USER:
                        owner.user_count += 1
                        response.user.name = TOKEN if reflected else "PRIVATE_ACCOUNT_NAME"
                        response.user.managerExp = owner.user_count
                        response.userPublic.publicUserId = ("OTHER_PRIVATE_ACCOUNT" if changed_account
                            and owner.user_count == 2 else "PRIVATE_PUBLIC_ID")
                        response.photos.add(photoId=PHOTO + "-area", rarity=4, isDreamBase=True)
                        response.photos.add(photoId=PHOTO + "-preview", rarity=4)
                        response.decks.add(number=7, name="PRIVATE_DECK")
                        for number in range(1, 6):
                            response.cards.add(cardId=f"card{number}")
                            response.deckPositions.add(number=7, position=number, cardId=f"card{number}")
                    elif method == event.DREAM_TOP:
                        response.seasonInfo.id = "dream-26-10"
                        response.dreamUserPhotos.add(photoId=PHOTO + "-area", generatedTime=1,
                                                    maxQuestNumber=15, isDisableGenerateArea=True)
                        response.dreamUserPhotos.add(photoId=PHOTO + "-preview")
                        if duplicate:
                            response.dreamUserPhotos.add(photoId=PHOTO + "-area")
                    elif method == event.PVP_TOP:
                        response.topResult.pvpSeason.id = "pvp-season-185"
                        response.opponentInfos.add(opponentId=OPPONENT + "-top", name="PRIVATE_RIVAL_NAME")
                    elif method == event.PVP_OPPONENT:
                        response.opponentInfos.add(opponentId=OPPONENT + "-list", name="PRIVATE_RIVAL_2")
                    elif method == event.DREAM_QUEST:
                        response.maxQuestNumber = 15
                    headers = (("x-error-code", "103"),) if method == app_error else ()
                    if method == changed_master:
                        headers += (("x-master-version", "PRIVATE_CHANGED_MASTER"),)
                    return codec.encode(response.SerializeToString()), Call(headers=headers)
            return Method()
    channel = Channel()
    def secure(target, credentials, *, options):
        assert target == event.OFFICIAL_TARGET and credentials is not None
        assert dict(options)["grpc.enable_retries"] == 0
        return channel
    monkeypatch.setattr(event.grpc, "secure_channel", secure)
    return channel


def manifest(path):
    return json.loads((path / "manifest.json").read_text())


def test_active_capture_is_private_bounded_and_has_separate_post_menu_snapshot(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema)
    output = tmp_path / "events"
    result = event.collect_events(schema, metadata, output, visit_menus=True)
    methods = [row[0] for row in channel.calls]
    assert methods == [event.MASTER, event.USER, event.HOME, event.QUEST, event.DREAM_TOP,
        event.DREAM_QUEST, event.DREAM_MATERIAL, event.PVP_TOP, event.PVP_OPPONENT,
        event.PVP_ASSET, event.PVP_ASSET, event.USER]
    assert all(method in event.ACTIVE_METHODS for method in methods)
    assert channel.closed and result["complete"] and result["consistent_final_snapshot"]
    assert channel.calls[2][1].skipUpdate
    assert channel.calls[5][1].basePhotoId == PHOTO + "-area"
    assert channel.calls[6][1].basePhotoId == PHOTO + "-preview"
    assert {row[1].opponentId for row in channel.calls if row[0] == event.PVP_ASSET} == {
        OPPONENT + "-top", OPPONENT + "-list"}
    assert all(row[1].deckNumber == 7 for row in channel.calls if row[0] == event.PVP_ASSET)
    archive = manifest(output)
    assert archive["consistent_snapshot_record"] == 12
    user_rows = [row for row in archive["records"] if row["method"] == event.USER]
    assert len(user_rows) == 2 and user_rows[0]["response"]["sha256"] != user_rows[1]["response"]["sha256"]
    assert archive["normal_menu_visits_may_reconcile_account_state"]
    for safe in (json.dumps(result), (output / "manifest.json").read_text()):
        assert all(secret not in safe for secret in (TOKEN, PHOTO, OPPONENT, "PRIVATE_ACCOUNT_NAME", "PRIVATE_DECK"))
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    for file in output.iterdir():
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert TOKEN not in b"".join(file.read_bytes() for file in output.iterdir()).decode(errors="ignore")


def test_no_menu_opt_in_never_sends_dream_or_pvp_and_still_binds_final_snapshot(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema)
    result = event.collect_events(schema, metadata, tmp_path / "events")
    assert [row[0] for row in channel.calls] == [event.MASTER, event.USER, event.HOME, event.QUEST, event.USER]
    assert result["complete"] and result["captured_responses"] == 5


@pytest.mark.parametrize("kind,code", [("auth", "rpc_failed"), ("application", "application_error"),
                                     ("master", "master_changed")])
def test_failures_stop_without_recovery_and_keep_prior_valid_responses(schema, metadata, tmp_path, monkeypatch, kind, code):
    channel = install(monkeypatch, schema, fail=event.DREAM_TOP if kind == "auth" else None,
        app_error=event.DREAM_TOP if kind == "application" else None,
        changed_master=event.DREAM_TOP if kind == "master" else None)
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError) as error:
        event.collect_events(schema, metadata, output, visit_menus=True)
    assert error.value.code == code and TOKEN not in str(error.value)
    assert len(channel.calls) == 5 and channel.closed
    archive = manifest(output)
    assert len(archive["records"]) == 4 and archive["stopped_code"] == code
    assert archive["consistent_snapshot_record"] is None and not archive["complete"]
    assert list(output.glob("*.response.pb"))


def test_duplicate_dream_reference_stops_before_reading_arbitrary_photo(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema, duplicate=True)
    with pytest.raises(event.EventCaptureError, match="dream_photo_references_invalid"):
        event.collect_events(schema, metadata, tmp_path / "events", visit_menus=True)
    assert len(channel.calls) == 5


@pytest.mark.parametrize("options", [{"target": "evil.example:443"}, {"visit_menus": 1},
    {"timeout": float("nan")}, {"timeout": 31}, {"deadline_seconds": 0},
    {"photo_limit": True}, {"opponent_limit": 21}])
def test_invalid_options_never_open_channel_or_write(schema, metadata, tmp_path, monkeypatch, options):
    monkeypatch.setattr(event.grpc, "secure_channel", lambda *a, **k: pytest.fail("unexpected network"))
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError):
        event.collect_events(schema, metadata, output, **options)
    assert not output.exists()


def test_in_memory_api_does_not_require_or_create_token_file(schema, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema)
    metadata = {"x-app-version": "6.1.1", "x-auth-token": TOKEN, "x-master-version": "master-current"}
    result = event.collect_in_memory(schema, metadata, tmp_path / "events")
    assert result["complete"] and channel.closed
    assert sorted(p.name for p in tmp_path.iterdir()) == ["events"]


def test_request_specific_metadata_is_rejected_before_any_network(schema, metadata, tmp_path, monkeypatch):
    values = json.loads(metadata.read_text()); values["x-app-request-id"] = "123"
    metadata.write_text(json.dumps(values))
    monkeypatch.setattr(event.grpc, "secure_channel", lambda *a, **k: pytest.fail("unexpected network"))
    with pytest.raises(event.EventCaptureError, match="per_request_metadata_not_allowed"):
        event.collect_events(schema, metadata, tmp_path / "events")


def test_existing_output_and_symlink_are_never_overwritten(schema, metadata, tmp_path, monkeypatch):
    monkeypatch.setattr(event.grpc, "secure_channel", lambda *a, **k: pytest.fail("unexpected network"))
    output = tmp_path / "events"; output.mkdir(); (output / "important").write_text("keep")
    link = tmp_path / "link"; link.symlink_to(output, target_is_directory=True)
    for destination in (output, link):
        with pytest.raises(event.EventCaptureError, match="output_exists"):
            event.collect_events(schema, metadata, destination)
    assert (output / "important").read_text() == "keep"


def test_passive_import_accepts_manually_observed_mutation_but_never_calls_network(schema, tmp_path, monkeypatch):
    monkeypatch.setattr(event.grpc, "secure_channel", lambda *a, **k: pytest.fail("unexpected network"))
    method = "/api.Dream/GenerateArea"
    request = schema.request_type(method)(basePhotoId=PHOTO, materialPhotoId="PRIVATE_MATERIAL").SerializeToString()
    response = schema.response_type(method)().SerializeToString()
    output = tmp_path / "events"
    result = event.import_observed(schema, [event.ObservedResponse(method,
        codec.encode(response), codec.encode(request), True, True)], output)
    assert result["complete"] and not result["consistent_final_snapshot"]
    archive = manifest(output)
    assert archive["mode"] == "observed-response-import" and archive["records"][0]["method"] == method
    assert (output / archive["records"][0]["request"]["file"]).read_bytes() == request
    assert PHOTO not in json.dumps(archive)


@pytest.mark.parametrize("method,request_bytes,response", [
    ("/api.Auth/Login", b"", b""), (event.DREAM_QUEST, None, b""),
    (event.DREAM_TOP, b"", b"\x0a\x80")])
def test_invalid_observations_rejected_before_output(schema, tmp_path, method, request_bytes, response):
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError):
        event.import_observed(schema, [event.ObservedResponse(method, response, request_bytes)], output)
    assert not output.exists()


def test_photo_and_opponent_caps_mark_archive_incomplete_without_extra_queries(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema)
    output = tmp_path / "events"
    result = event.collect_events(schema, metadata, output, visit_menus=True, photo_limit=0, opponent_limit=0)
    assert not result["complete"] and result["consistent_final_snapshot"]
    assert not any(row[0] in (event.DREAM_QUEST, event.DREAM_MATERIAL, event.PVP_ASSET) for row in channel.calls)
    assert manifest(output)["limitations"] == ["dream_photo_limit", "pvp_opponent_limit"]


def test_capture_stops_at_local_jst_day_boundary_without_initializing_day(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema)
    original = event._now
    calls = 0
    def now():
        nonlocal calls
        calls += 1
        return original() + (timedelta(days=1) if calls > 3 else timedelta())
    monkeypatch.setattr(event, "_now", now)
    with pytest.raises(event.EventCaptureError, match="day_changed"):
        event.collect_events(schema, metadata, tmp_path / "events")
    assert len(channel.calls) == 1


def test_declared_size_caps_stop_before_any_output(schema, tmp_path, monkeypatch):
    monkeypatch.setattr(event, "MAX_RESPONSE", 1)
    response = schema.response_type(event.DREAM_TOP)(); response.seasonInfo.id = "dream"
    with pytest.raises(event.EventCaptureError, match="message_size_invalid"):
        event.import_observed(schema, [event.ObservedResponse(event.DREAM_TOP, response.SerializeToString())], tmp_path / "events")
    assert not (tmp_path / "events").exists()


def test_reflected_session_credential_is_rejected_before_raw_response_write(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema, reflected=True)
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError, match="credential_reflection_detected"):
        event.collect_events(schema, metadata, output)
    assert len(channel.calls) == 2 and len(manifest(output)["records"]) == 1
    assert TOKEN.encode() not in b"".join(file.read_bytes() for file in output.iterdir())


def test_final_account_identity_is_checked_before_saving_its_payload(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema, changed_account=True)
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError, match="account_changed"):
        event.collect_events(schema, metadata, output)
    archive = manifest(output)
    assert len(channel.calls) == 5 and len(archive["records"]) == 4
    assert archive["consistent_snapshot_record"] is None
    assert b"OTHER_PRIVATE_ACCOUNT" not in b"".join(file.read_bytes() for file in output.iterdir())


def test_total_deadline_stops_without_automatic_retry(schema, metadata, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema)
    ticks = iter((0, 0, 0, 400))
    monkeypatch.setattr(event.time, "monotonic", lambda: next(ticks))
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError, match="time_limit_reached"):
        event.collect_events(schema, metadata, output)
    assert len(channel.calls) == 1 and len(manifest(output)["records"]) == 1


def test_import_cli_rejects_escape_paths_without_network_or_secret_output(schema, tmp_path, monkeypatch, capsys):
    import importlib.util
    source = Path(__file__).resolve().parents[1] / "tools/preserve_events.py"
    spec = importlib.util.spec_from_file_location("preserve_events_cli", source)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    monkeypatch.setattr(cli.Schema, "from_descriptor_set", lambda _: schema)
    monkeypatch.setattr(event.grpc, "secure_channel", lambda *a, **k: pytest.fail("unexpected network"))
    outside = tmp_path / "secret"; outside.write_text(TOKEN)
    inputs = tmp_path / "captures"; inputs.mkdir()
    plan = inputs / "plan.json"
    plan.write_text(json.dumps([{"method": event.DREAM_TOP, "response": "../secret"}]))
    output = tmp_path / "events"
    assert cli.main(["import", "--plan", str(plan), "--output", str(output)]) == 1
    result = capsys.readouterr()
    assert TOKEN not in result.out + result.err and "import_file_invalid" in result.err
    assert not output.exists()


def test_bare_bearer_token_reflection_is_rejected_before_private_response_write(schema, tmp_path, monkeypatch):
    channel = install(monkeypatch, schema, reflected=True)
    output = tmp_path / "events"
    metadata = {"x-app-version": "6.1.1", "x-master-version": "master-current",
                "x-auth-token": "DIFFERENT_PRIVATE_GAME_TOKEN", "authorization": "bEaReR  " + TOKEN}
    with pytest.raises(event.EventCaptureError, match="credential_reflection_detected"):
        event.collect_in_memory(schema, metadata, output)
    assert len(channel.calls) == 2 and len(manifest(output)["records"]) == 1
    assert TOKEN.encode() not in b"".join(file.read_bytes() for file in output.iterdir())


@pytest.mark.parametrize("boundary,code", (("day", "day_changed"), ("deadline", "time_limit_reached")))
def test_final_response_crossing_capture_boundary_is_not_saved_or_marked_consistent(
        schema, metadata, tmp_path, monkeypatch, boundary, code):
    channel = install(monkeypatch, schema)
    clock, ticks = [event._now()], [0]
    monkeypatch.setattr(event, "_now", lambda: clock[0])
    monkeypatch.setattr(event.time, "monotonic", lambda: ticks[0])
    original = channel.unary_unary
    def unary(method):
        wrapped = original(method)
        class Method:
            def with_call(self, *args, **kwargs):
                response = wrapped.with_call(*args, **kwargs)
                if method == event.USER and channel.user_count == 2:
                    if boundary == "day": clock[0] += timedelta(days=1)
                    else: ticks[0] = 301
                return response
        return Method()
    channel.unary_unary = unary
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError, match=code):
        event.collect_events(schema, metadata, output)
    archive = manifest(output)
    assert len(channel.calls) == 5 and len(archive["records"]) == 4
    assert archive["stopped_code"] == code and not archive["complete"]
    assert archive["consistent_snapshot_record"] is None


def test_import_cumulative_input_budget_stops_before_decoding_later_records(schema, tmp_path, monkeypatch):
    response = schema.response_type(event.DREAM_TOP)()
    response.seasonInfo.id = "synthetic-season"
    raw = response.SerializeToString()
    observations = [event.ObservedResponse(event.DREAM_TOP, raw)] * 3
    monkeypatch.setattr(event, "MAX_ARCHIVE", len(raw) * 2)
    parsed, original = [], event._parse
    def parse(*args, **kwargs):
        parsed.append(kwargs.get("request", False))
        return original(*args, **kwargs)
    monkeypatch.setattr(event, "_parse", parse)
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError, match="archive_size_limit_reached"):
        event.import_observed(schema, observations, output)
    assert parsed == [True, False, True, False] and not output.exists()


def test_import_decoded_and_wire_budget_stops_before_parsing_next_record(schema, tmp_path, monkeypatch):
    response = schema.response_type(event.DREAM_TOP)()
    response.seasonInfo.id = "synthetic-season"
    plain = response.SerializeToString()
    wire = codec.encode(plain)
    observations = [event.ObservedResponse(event.DREAM_TOP, wire, response_is_wire=True)] * 2
    monkeypatch.setattr(event, "MAX_ARCHIVE", len(plain) + len(wire) - 1)
    parsed, original = [], event._parse
    def parse(*args, **kwargs):
        parsed.append(kwargs.get("request", False))
        return original(*args, **kwargs)
    monkeypatch.setattr(event, "_parse", parse)
    output = tmp_path / "events"
    with pytest.raises(event.EventCaptureError, match="archive_size_limit_reached"):
        event.import_observed(schema, observations, output)
    assert parsed == [True, False] and not output.exists()


def _import_cli():
    import importlib.util
    source = Path(__file__).resolve().parents[1] / "tools/preserve_events.py"
    spec = importlib.util.spec_from_file_location("bounded_preserve_events_cli", source)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def test_import_cli_stops_before_reading_file_over_aggregate_budget(schema, tmp_path, monkeypatch, capsys):
    cli = _import_cli()
    monkeypatch.setattr(cli.Schema, "from_descriptor_set", lambda _: schema)
    response = schema.response_type(event.DREAM_TOP)()
    response.seasonInfo.id = "synthetic-season"
    raw = response.SerializeToString()
    (tmp_path / "first.pb").write_bytes(raw)
    (tmp_path / "second.pb").write_bytes(raw)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"method": event.DREAM_TOP, "response": name}
                               for name in ("first.pb", "second.pb")]))
    monkeypatch.setattr(cli, "MAX_ARCHIVE", len(raw) + 1)
    reads, original = [], Path.open
    def open_file(path, *args, **kwargs):
        if path.suffix == ".pb": reads.append(path.name)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(cli, "import_observed", lambda *a: pytest.fail("oversized import dispatched"))
    output = tmp_path / "events"
    assert cli.main(["import", "--plan", str(plan), "--output", str(output)]) == 1
    assert reads == ["first.pb"] and not output.exists()
    assert "archive_size_limit_reached" in capsys.readouterr().err


def test_import_file_read_remains_bounded_if_file_grows_after_stat(tmp_path, monkeypatch):
    import io
    cli = _import_cli()
    path = tmp_path / "growing.pb"
    path.write_bytes(b"x")
    reads = []
    class Growing(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    monkeypatch.setattr(Path, "open", lambda *a, **kw: Growing(b"x" * 100))
    with pytest.raises(event.EventCaptureError, match="archive_size_limit_reached"):
        cli._private_input(tmp_path, path.name, 100, remaining=4)
    assert reads == [5]
