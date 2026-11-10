"""The public tutorial archive must contain canonical data and no account state."""
import hashlib
import importlib.util
import json
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool
import pytest

from idoly_local.schema import Schema


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("archive_tutorial_replays_tool",
                                            ROOT / "tools/archive_tutorial_replays.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
PRIVATE = ("FAKE_ACCOUNT_ID_1742", "FAKE_ACCOUNT_NAME_8321", "FAKE_DETAIL_LOG_9921",
           "FAKE_ACCOUNT_STATE_6341", "FAKE_UNKNOWN_ACCOUNT_2571", "FAKE_MASTER_KEY_4416")


def small_schema(*, identity_field=True):
    file = descriptor_pb2.FileDescriptorProto(name="tutorial_archive.proto", package="api", syntax="proto3")

    def message(name, fields):
        result = file.message_type.add(name=name)
        for number, name, kind, repeated in fields:
            field = result.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, str):
                field.type, field.type_name = 11, ".api." + kind
            else:
                field.type = kind
        return result

    message("Empty", [])
    message("Pack", [(1, "cryptoKey", 9, False)])
    message("MasterTag", [(1, "version", 9, False), (2, "masterTagPacks", "Pack", True)])
    message("MasterResponse", [(1, "masterTag", "MasterTag", False)])
    message("CommonResponse", [(1, "accountState", 9, False)])
    message("Card", [(1, "index", 5, False), (2, "cardId", 9, False)])
    message("Deck", [(1, "deckName", 9, False), (2, "cards", "Card", True)])
    user_fields = [(1, "index", 5, False), (3, "name", 9, False), (4, "emblemId", 9, False),
                   (5, "userDeck", "Deck", False), (100, "note", 9, False)]
    if identity_field:
        user_fields.append((2, "userId", 9, False))
    message("UserInfo", user_fields)
    message("Chart", [(1, "number", 5, False), (2, "score", 3, False)])
    message("LiveResult", [(1, "userInfos", "UserInfo", True), (3, "charts", "Chart", True),
                           (5, "cleared", 8, False), (6, "isDisplayDetailAvailable", 8, False),
                           (8, "detailLogId", 9, False)])
    message("Rank", [(1, "rankType", 5, False), (2, "thresholdScore", 3, False)])
    message("Response", [(1, "result", "LiveResult", False), (2, "rankPatterns", "Rank", True),
                         (50, "privateAccountData", 9, False), (9999, "commonResponse", "CommonResponse", False)])
    for service_name, method_name, output in (("System", "Check", "Empty"),
                                               ("Tutorial", "StartQuest", "Response"),
                                               ("Master", "Get", "MasterResponse")):
        file.service.add(name=service_name).method.add(name=method_name,
            input_type=".api.Empty", output_type=".api." + output)
    pool = descriptor_pool.DescriptorPool()
    descriptor = pool.AddSerializedFile(file.SerializeToString())
    return Schema(pool, [descriptor])


@pytest.fixture
def schema():
    return small_schema()


@pytest.fixture
def master_tag(tmp_path):
    path = tmp_path / "master-tag.json"
    path.write_text(json.dumps({"version": "pinned-master-version",
                               "masterTagPacks": [{"cryptoKey": PRIVATE[5]}]}))
    return path


def original_response(schema, *, score=1234):
    response = schema.response_type(tool.METHOD)()
    user = response.result.userInfos.add(index=1, userId=PRIVATE[0], name=PRIVATE[1], emblemId="emb001")
    user.userDeck.deckName = "Generic demo deck"
    for index in range(1, 6):
        user.userDeck.cards.add(index=index, cardId="card-fixture-" + str(index))
    response.result.charts.add(number=1, score=score)
    response.result.charts.add(number=7, score=score + 10)
    response.result.cleared = True
    response.result.isDisplayDetailAvailable = True
    response.result.detailLogId = PRIVATE[2]
    response.commonResponse.accountState = PRIVATE[3]
    response.privateAccountData = PRIVATE[3]
    for rank, threshold in ((3, 7200), (2, 6000), (1, 0)):
        response.rankPatterns.add(rankType=rank, thresholdScore=threshold)
    return response


def source_row(kind, raw):
    return {"kind": kind, "source_url": "https://raw.githubusercontent.com/pinned/" + kind,
            "raw_bytes": len(raw), "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def sources(monkeypatch, schema, *, second_raw=None):
    bodies = [original_response(schema, score=score).SerializeToString() for score in (1234, 5678)]
    if second_raw is not None:
        bodies[1] = second_raw
    rows = tuple(source_row(kind, raw) for kind, raw in zip(("short", "full"), bodies))
    monkeypatch.setattr(tool, "_SOURCES", rows)
    mapping = {row["source_url"]: raw for row, raw in zip(rows, bodies)}
    calls = []

    def fetch(url, limit):
        calls.append((url, limit))
        return mapping[url]

    return rows, bodies, fetch, calls


def test_sanitizer_preserves_exact_demo_and_ranks_but_not_account_state(schema):
    original = original_response(schema)
    # Unknown envelope/account bytes must not enter the fresh response.
    unknown = b"\x82\x4b" + bytes([len(PRIVATE[4])]) + PRIVATE[4].encode()
    original.MergeFromString(unknown)
    raw = original.SerializeToString()
    sanitized = tool.sanitize_replay(schema, raw)
    result = schema.response_type(tool.METHOD).FromString(sanitized)
    expected = schema.response_type(tool.METHOD)()
    expected.result.CopyFrom(original.result)
    expected.result.userInfos[0].ClearField("userId")
    expected.result.userInfos[0].ClearField("name")
    expected.result.ClearField("detailLogId")
    expected.result.isDisplayDetailAvailable = False
    expected.result.DiscardUnknownFields()
    expected.rankPatterns.extend(original.rankPatterns)
    expected.commonResponse.SetInParent()
    assert result.SerializeToString(deterministic=True) == expected.SerializeToString(deterministic=True)
    assert result.result.userInfos[0].emblemId == "emb001"
    assert result.result.userInfos[0].userDeck.deckName == "Generic demo deck"
    assert not result.commonResponse.ListFields()
    assert not result.privateAccountData
    assert all(value.encode() not in sanitized for value in PRIVATE)
    assert original.SerializeToString() == raw


def test_unknown_demo_fields_are_rejected_to_preserve_complete_timeline(schema):
    original = original_response(schema)
    original.result.MergeFromString(b"\x82\x4b\x03new")
    with pytest.raises(tool.TutorialArchiveError, match="fully preserve"):
        tool.sanitize_replay(schema, original.SerializeToString())


def test_identity_echo_outside_reviewed_fields_is_rejected_without_logging_it(schema):
    original = original_response(schema)
    original.result.userInfos[0].note = PRIVATE[0]
    with pytest.raises(tool.TutorialArchiveError, match="outside") as error:
        tool.sanitize_replay(schema, original.SerializeToString())
    assert all(value not in str(error.value) for value in PRIVATE)


def test_archives_only_two_sanitized_files_and_bound_provenance(tmp_path, schema, master_tag, monkeypatch):
    rows, bodies, fetch, calls = sources(monkeypatch, schema)
    output = tmp_path / "public-tutorial"
    manifest = tool.archive_tutorial_replays(schema, master_tag, output, fetch=fetch)
    assert {path.name for path in output.iterdir()} == {"tutorial-short.pb", "tutorial-full.pb", "manifest.json"}
    assert calls == [(row["source_url"], tool.MAX_RESPONSE_BYTES) for row in rows]
    assert manifest["schema"] == 1 and manifest["fixed_demo"] is True
    assert manifest["schema_sha256"] == schema.fingerprint
    assert manifest["master_version"] == "pinned-master-version"
    assert manifest["source_commit"] == tool.SOURCE_COMMIT
    assert json.loads((output / "manifest.json").read_text()) == manifest
    for entry, row, original in zip(manifest["replays"], rows, bodies):
        payload = (output / entry["file"]).read_bytes()
        assert entry["quest_id"] == "qt-tutorial-" + entry["kind"]
        assert entry["bytes"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
        assert entry["source"] == {**{key: row[key] for key in (
            "source_url", "raw_bytes", "raw_sha256", "git_blob_sha1")}, "source_commit": tool.SOURCE_COMMIT}
        assert payload == tool.sanitize_replay(schema, original)
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())
    assert all(value.encode() not in path.read_bytes() for path in output.iterdir() for value in PRIVATE)
    assert not list(tmp_path.glob(".public-tutorial-*"))


@pytest.mark.parametrize("field,value,error", [("raw_bytes", 1, "size"),
    ("raw_sha256", "0" * 64, "SHA256"), ("git_blob_sha1", "0" * 40, "Git blob")])
def test_second_source_failure_leaves_no_partial_archive(tmp_path, schema, master_tag, monkeypatch, field, value, error):
    rows, _, fetch, calls = sources(monkeypatch, schema)
    rows[1][field] = value
    output = tmp_path / "public-tutorial"
    with pytest.raises(tool.TutorialArchiveError, match=error):
        tool.archive_tutorial_replays(schema, master_tag, output, fetch=fetch)
    assert len(calls) == 2
    assert not output.exists()
    assert not list(tmp_path.glob(".public-tutorial-*"))


@pytest.mark.parametrize("raw", [b"\x0a\x80", b"x" * (tool.MAX_RESPONSE_BYTES + 1)])
def test_malformed_or_oversized_pinned_source_is_not_saved(tmp_path, schema, master_tag, monkeypatch, raw):
    _, _, fetch, _ = sources(monkeypatch, schema, second_raw=raw)
    output = tmp_path / "public-tutorial"
    with pytest.raises(tool.TutorialArchiveError):
        tool.archive_tutorial_replays(schema, master_tag, output, fetch=fetch)
    assert not output.exists()


@pytest.mark.parametrize("change", [lambda r: r.ClearField("result"),
    lambda r: r.result.userInfos.add(), lambda r: r.result.userInfos[0].userDeck.cards.pop(),
    lambda r: r.result.charts.clear(), lambda r: r.rankPatterns.pop()])
def test_noncanonical_response_shape_is_rejected(schema, change):
    reply = original_response(schema)
    change(reply)
    with pytest.raises(tool.TutorialArchiveError, match="fixed demonstration"):
        tool.sanitize_replay(schema, reply.SerializeToString())


def test_invalid_schema_is_rejected_before_download(tmp_path, master_tag):
    schema = small_schema(identity_field=False)
    with pytest.raises(tool.TutorialArchiveError, match="Schema"):
        tool.archive_tutorial_replays(schema, master_tag, tmp_path / "output",
            fetch=lambda *_: pytest.fail("Invalid schema must not initiate a download"))


@pytest.mark.parametrize("value", [{}, {"version": ""}, {"version": "bad\nvalue"},
                                     {"version": "valid", "unexpectedField": "not accepted"}])
def test_invalid_master_tag_does_not_download(tmp_path, schema, master_tag, value):
    master_tag.write_text(json.dumps(value))
    with pytest.raises(tool.TutorialArchiveError, match="MasterTag"):
        tool.archive_tutorial_replays(schema, master_tag, tmp_path / "output",
            fetch=lambda *_: pytest.fail("Invalid master must not initiate a download"))


def test_existing_archive_is_never_overwritten(tmp_path, schema, master_tag):
    output = tmp_path / "public-tutorial"
    output.mkdir()
    (output / "keep.txt").write_text("existing")
    with pytest.raises(tool.TutorialArchiveError, match="already exists"):
        tool.archive_tutorial_replays(schema, master_tag, output,
            fetch=lambda *_: pytest.fail("Existing output must not initiate a download"))
    assert (output / "keep.txt").read_text() == "existing"


def test_staging_write_failure_removes_only_own_temporary_files(tmp_path, schema, master_tag, monkeypatch):
    _, _, fetch, _ = sources(monkeypatch, schema)
    original = Path.write_bytes

    def fail(path, value):
        if path.name == "tutorial-full.pb":
            raise OSError("synthetic disk failure")
        return original(path, value)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError):
        tool.archive_tutorial_replays(schema, master_tag, tmp_path / "output", fetch=fetch)
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".public-tutorial-*"))


def test_downloader_reads_at_most_one_byte_beyond_limit(monkeypatch):
    class Response:
        status, headers = 200, {}
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, amount):
            assert amount == tool.MAX_RESPONSE_BYTES + 1
            return b"x" * amount
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == tool._SOURCES[0]["source_url"] and timeout == 30
            return Response()
    monkeypatch.setattr(tool, "build_opener", lambda *_: Opener())
    with pytest.raises(tool.TutorialArchiveError, match="size limit"):
        tool._download(tool._SOURCES[0]["source_url"], tool.MAX_RESPONSE_BYTES)
    with pytest.raises(tool.TutorialArchiveError, match="redirected"):
        tool._NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid")


def test_cli_outputs_summary_only(tmp_path, schema, master_tag, monkeypatch, capsys):
    _, _, fetch, _ = sources(monkeypatch, schema)
    monkeypatch.setattr(tool.Schema, "from_descriptor_set", lambda _: schema)
    monkeypatch.setattr(tool, "_download", fetch)
    assert tool.main(["--descriptor-set", str(tmp_path / "schema.pb"), "--master-tag", str(master_tag),
                      "--output", str(tmp_path / "output")]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["archived"] == 2
    assert all(value not in captured.out + captured.err for value in PRIVATE)


def test_available_actual_archive_matches_independent_whole_response_pins():
    root = ROOT / "data/public-tutorial"
    if not (root / "manifest.json").is_file():
        pytest.skip("Optional generated canonical archive is not available")
    expected = {"short": (31243, "719068e48099082fad71760d65a88047182be8b858a3586f33f87b812103fba7"),
                "full": (32251, "29ecb24412bd6a2034a8b31803fcb34a8cd6b6632c2f0a96fe0319c15236d562")}
    for kind, (size, digest) in expected.items():
        payload = (root / ("tutorial-" + kind + ".pb")).read_bytes()
        assert len(payload) == size and hashlib.sha256(payload).hexdigest() == digest
