"""Pinned story archives retain only generic catalog DTOs and provenance."""
import hashlib
import importlib.util
import json
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool
import pytest

from idoly_local.schema import Schema


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("archive_story_catalog_tool", ROOT / "tools/archive_story_catalog.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
PRIVATE = ("FAKE_ACCOUNT_NAME_6532", "FAKE_ACCOUNT_STORY_8192", "FAKE_ACCOUNT_UNKNOWN_2154", "FAKE_KEY_9341")


def small_schema(*, episode_field_type=5):
    file = descriptor_pb2.FileDescriptorProto(name="story_archive.proto", package="api", syntax="proto3")

    def message(name, fields):
        result = file.message_type.add(name=name)
        for number, name, kind, repeated in fields:
            field = result.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, str):
                field.type, field.type_name = 11, ".api." + kind
            else:
                field.type = kind

    message("Empty", [])
    message("MasterTag", [(1, "version", 9, False), (2, "cryptoKey", 9, False)])
    message("MasterResponse", [(1, "masterTag", "MasterTag", False)])
    message("Common", [(1, "updatedData", "Empty", False), (2, "deletedData", "Empty", False),
                       (50, "userStories", 9, False)])
    message("EventEpisode", [(1, "episode", episode_field_type, False), (2, "unlocked", 8, False)])
    message("EventInfo", [(1, "id", 9, False), (2, "episodes", "EventEpisode", True)])
    message("ExtraEpisode", [(1, "episode", 5, False), (2, "unlocked", 8, False)])
    message("ExtraInfo", [(1, "id", 9, False), (2, "unlocked", 8, False), (3, "episodes", "ExtraEpisode", True)])
    message("PartInfo", [(1, "id", 9, False), (2, "unlocked", 8, False), (3, "stories", "ExtraInfo", True)])
    for name, info in (("EventResponse", "EventInfo"), ("ExtraResponse", "PartInfo")):
        message(name, [(1, "infos", info, True), (50, "accountIdentity", 9, False),
                       (9999, "commonResponse", "Common", False)])
    message("HomeResponse", [(1, "accountIdentity", 9, False), (32, "userStories", 9, False),
                             (33, "extraStoryPartInfos", "PartInfo", True), (9999, "commonResponse", "Common", False)])
    for service_name, methods in (("System", [("Check", "Empty")]),
                                 ("Master", [("Get", "MasterResponse")]),
                                 ("Story", [("ListEvent", "EventResponse"), ("ListExtra", "ExtraResponse")]),
                                 ("Home", [("Enter", "HomeResponse")])):
        service = file.service.add(name=service_name)
        for method_name, output in methods:
            service.method.add(name=method_name, input_type=".api.Empty", output_type=".api." + output)
    pool = descriptor_pool.DescriptorPool()
    descriptor = pool.AddSerializedFile(file.SerializeToString())
    return Schema(pool, [descriptor])


@pytest.fixture
def schema():
    return small_schema()


@pytest.fixture
def master_tag(tmp_path):
    path = tmp_path / "tag.json"
    path.write_text(json.dumps({"version": "local-master-version", "cryptoKey": PRIVATE[3]}))
    return path


def original_responses(schema):
    event = schema.response_type("/api.Story/ListEvent")(accountIdentity=PRIVATE[0])
    info = event.infos.add(id="event-fixture")
    info.episodes.add(episode=1, unlocked=True)
    info.episodes.add(episode=2, unlocked=False)
    event.commonResponse.userStories = PRIVATE[1]
    home = schema.response_type("/api.Home/Enter")(accountIdentity=PRIVATE[0], userStories=PRIVATE[1])
    part = home.extraStoryPartInfos.add(id="part-fixture", unlocked=True)
    story = part.stories.add(id="extra-fixture", unlocked=False)
    story.episodes.add(episode=1, unlocked=True)
    story.episodes.add(episode=2, unlocked=False)
    home.commonResponse.userStories = PRIVATE[1]
    return event, home


def sources(monkeypatch, schema):
    event, home = original_responses(schema)
    bodies = [value.SerializeToString() for value in (event, home)]
    safe = tool.sanitize_story_catalog(schema, *bodies)
    rows = []
    for source, raw in zip(tool._SOURCES, bodies):
        row = dict(source)
        row.update(raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest(),
                   git_blob_sha1=hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
                   sanitized_bytes=len(safe[row["kind"]]),
                   sanitized_sha256=hashlib.sha256(safe[row["kind"]]).hexdigest())
        rows.append(row)
    monkeypatch.setattr(tool, "_SOURCES", tuple(rows))
    monkeypatch.setattr(tool, "_COUNTS", {"event": (1, 2), "extra": (1, 1, 2)})
    mapping = {row["source_url"]: raw for row, raw in zip(rows, bodies)}
    calls = []

    def fetch(url, limit):
        calls.append((url, limit))
        return mapping[url]

    return rows, bodies, fetch, calls


def test_fresh_responses_contain_only_known_catalog_dtos_and_empty_common(schema):
    event, home = original_responses(schema)
    unknown = b"\x82\x4b" + bytes([len(PRIVATE[2])]) + PRIVATE[2].encode()
    event.MergeFromString(unknown)
    home.MergeFromString(unknown)
    originals = [value.SerializeToString() for value in (event, home)]
    sanitized = tool.sanitize_story_catalog(schema, *originals)
    safe_event = schema.response_type("/api.Story/ListEvent").FromString(sanitized["event"])
    safe_extra = schema.response_type("/api.Story/ListExtra").FromString(sanitized["extra"])
    assert list(safe_event.infos) == list(event.infos)
    assert list(safe_extra.infos) == list(home.extraStoryPartInfos)
    assert [episode.unlocked for episode in safe_event.infos[0].episodes] == [True, False]
    assert safe_extra.infos[0].stories[0].unlocked is False
    for result in (safe_event, safe_extra):
        assert result.HasField("commonResponse")
        assert result.commonResponse.HasField("updatedData") and not result.commonResponse.updatedData.ListFields()
        assert result.commonResponse.HasField("deletedData") and not result.commonResponse.deletedData.ListFields()
        assert not result.commonResponse.userStories
        assert not result.accountIdentity
        assert {field.name for field, _ in result.ListFields()} == {"infos", "commonResponse"}
    assert all(value.encode() not in raw for value in PRIVATE for raw in sanitized.values())
    assert [value.SerializeToString() for value in (event, home)] == originals


@pytest.mark.parametrize("target", ["event", "episode", "part", "extra", "extra_episode"])
def test_unknown_selected_dto_fields_are_rejected(schema, target):
    event, home = original_responses(schema)
    dto = {"event": event.infos[0], "episode": event.infos[0].episodes[0],
           "part": home.extraStoryPartInfos[0], "extra": home.extraStoryPartInfos[0].stories[0],
           "extra_episode": home.extraStoryPartInfos[0].stories[0].episodes[0]}[target]
    dto.MergeFromString(b"\x82\x4b\x03new")
    with pytest.raises(tool.StoryArchiveError, match="unknown protobuf"):
        tool.sanitize_story_catalog(schema, event.SerializeToString(), home.SerializeToString())


@pytest.mark.parametrize("which,raw", [(0, b""), (0, b"\x0a\x80"), (1, b"x" * (tool.MAX_RESPONSE_BYTES + 1))])
def test_invalid_source_body_is_rejected(schema, which, raw):
    values = [value.SerializeToString() for value in original_responses(schema)]
    values[which] = raw
    with pytest.raises(tool.StoryArchiveError):
        tool.sanitize_story_catalog(schema, *values)


def test_empty_catalog_is_not_accepted(schema):
    event, home = original_responses(schema)
    home.extraStoryPartInfos.clear()
    with pytest.raises(tool.StoryArchiveError, match="expected catalog"):
        tool.sanitize_story_catalog(schema, event.SerializeToString(), home.SerializeToString())


def test_archive_contains_only_three_safe_files_and_manifest(tmp_path, schema, master_tag, monkeypatch):
    rows, bodies, fetch, calls = sources(monkeypatch, schema)
    output = tmp_path / "public-story"
    manifest = tool.archive_story_catalog(schema, master_tag, output, fetch=fetch)
    assert {path.name for path in output.iterdir()} == {"manifest.json", "story-list-event.pb", "story-list-extra.pb"}
    assert calls == [(row["source_url"], tool.MAX_RESPONSE_BYTES) for row in rows]
    assert manifest["schema"] == 1 and manifest["baseline_version"] == 1
    assert manifest["baseline_id"] == tool.BASELINE_ID
    assert manifest["frozen_public_baseline"] is True
    assert manifest["schema_sha256"] == schema.fingerprint
    assert manifest["master_version"] == "local-master-version"
    assert manifest["sanitization"] == {"dto_only": True, "common_response_empty": True, "user_story_state_absent": True}
    assert json.loads((output / "manifest.json").read_text()) == manifest
    expected = tool.sanitize_story_catalog(schema, *bodies)
    for entry, source in zip(manifest["catalogs"], rows):
        payload = (output / entry["file"]).read_bytes()
        assert payload == expected[entry["kind"]]
        assert entry["bytes"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
        assert entry["source"] == {**{key: source[key] for key in (
            "source_url", "raw_bytes", "raw_sha256", "git_blob_sha1", "field")}, "source_commit": tool.SOURCE_COMMIT}
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())
    assert all(value.encode() not in path.read_bytes() for path in output.iterdir() for value in PRIVATE)
    assert not list(tmp_path.glob(".public-story-*"))


def test_master_tag_is_optional_and_uses_pinned_version(tmp_path, schema, monkeypatch):
    _, _, fetch, _ = sources(monkeypatch, schema)
    result = tool.archive_story_catalog(schema, None, tmp_path / "output", fetch=fetch)
    assert result["master_version"] == tool.DEFAULT_MASTER_VERSION


@pytest.mark.parametrize("field,value,message", [("raw_bytes", 1, "size"), ("raw_sha256", "0" * 64, "SHA256"),
    ("git_blob_sha1", "0" * 40, "Git blob"), ("sanitized_sha256", "0" * 64, "Sanitized")])
def test_failed_second_source_never_writes_partial_archive(tmp_path, schema, monkeypatch, field, value, message):
    rows, _, fetch, _ = sources(monkeypatch, schema)
    rows[1][field] = value
    output = tmp_path / "output"
    with pytest.raises(tool.StoryArchiveError, match=message):
        tool.archive_story_catalog(schema, None, output, fetch=fetch)
    assert not output.exists() and not list(tmp_path.glob(".public-story-*"))


def test_source_count_mismatch_fails_without_output(tmp_path, schema, monkeypatch):
    _, _, fetch, _ = sources(monkeypatch, schema)
    monkeypatch.setattr(tool, "_COUNTS", {"event": (55, 272), "extra": (3, 41, 154)})
    with pytest.raises(tool.StoryArchiveError, match="counts"):
        tool.archive_story_catalog(schema, None, tmp_path / "output", fetch=fetch)
    assert not (tmp_path / "output").exists()


def test_changed_dto_schema_fails_before_fetch(tmp_path):
    with pytest.raises(tool.StoryArchiveError, match="Schema"):
        tool.archive_story_catalog(small_schema(episode_field_type=9), None, tmp_path / "output",
            fetch=lambda *_: pytest.fail("Invalid schema must not fetch"))


@pytest.mark.parametrize("value", [{}, {"version": "bad\nvalue"}, {"version": "version", "unknown": "no"}])
def test_invalid_master_tag_fails_before_fetch(tmp_path, schema, master_tag, value):
    master_tag.write_text(json.dumps(value))
    with pytest.raises(tool.StoryArchiveError, match="MasterTag"):
        tool.archive_story_catalog(schema, master_tag, tmp_path / "output",
            fetch=lambda *_: pytest.fail("Invalid master must not fetch"))


def test_existing_output_is_preserved_without_fetch(tmp_path, schema):
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep").write_text("keep")
    with pytest.raises(tool.StoryArchiveError, match="already exists"):
        tool.archive_story_catalog(schema, None, output, fetch=lambda *_: pytest.fail("Must not fetch"))
    assert (output / "keep").read_text() == "keep"


def test_staging_failure_cleans_only_own_files(tmp_path, schema, monkeypatch):
    _, _, fetch, _ = sources(monkeypatch, schema)
    original = Path.write_bytes

    def fail(path, value):
        if path.name == "story-list-extra.pb":
            raise OSError("synthetic disk failure")
        return original(path, value)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError):
        tool.archive_story_catalog(schema, None, tmp_path / "output", fetch=fetch)
    assert not (tmp_path / "output").exists() and not list(tmp_path.glob(".public-story-*"))


def test_download_is_bounded_and_redirects_rejected(monkeypatch):
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
    with pytest.raises(tool.StoryArchiveError, match="size limit"):
        tool._download(tool._SOURCES[0]["source_url"], tool.MAX_RESPONSE_BYTES)
    with pytest.raises(tool.StoryArchiveError, match="redirected"):
        tool._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid")


def test_cli_needs_only_schema_and_output_and_prints_summary(tmp_path, schema, monkeypatch, capsys):
    _, _, fetch, _ = sources(monkeypatch, schema)
    monkeypatch.setattr(tool.Schema, "from_descriptor_set", lambda _: schema)
    monkeypatch.setattr(tool, "_download", fetch)
    assert tool.main(["--descriptor-set", "schema.pb", "--output", str(tmp_path / "output")]) == 0
    result = capsys.readouterr()
    assert json.loads(result.out)["archived"] == 2
    assert all(value not in result.out + result.err for value in PRIVATE)


def test_available_actual_archive_matches_independent_payload_pins():
    root = ROOT / "data/public-story"
    if not (root / "manifest.json").is_file():
        pytest.skip("Optional generated canonical story archive is unavailable")
    expected = {"event": (2898, "830ce025b2866706bb5b26f7ab54d5b63c8d87b6c33623e8b4c465c32c4e9252"),
                "extra": (2803, "53972ca1710d59ca2d379e172ecda4d717edb0ab8627a08bd070793945ef925f")}
    for kind, (size, digest) in expected.items():
        payload = (root / ("story-list-" + kind + ".pb")).read_bytes()
        assert len(payload) == size and hashlib.sha256(payload).hexdigest() == digest
