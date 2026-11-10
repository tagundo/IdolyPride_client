"""Frozen public eligibility catalogs preserve independent profile read state."""
import copy
import hashlib
import json
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.internal.encoder import _VarintBytes
import pytest

from idoly_local import story_catalog as module
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import synthetic_schema


EVENT = "/api.Story/ListEvent"
EXTRA = "/api.Story/ListExtra"


def small_schema(path):
    synthetic_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]

    def message(target_file, name, fields):
        target = target_file.message_type.add(name=name)
        for number, (name, kind, repeated) in enumerate(fields, 1):
            field = target.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type = 14 if kind.endswith("PlayType") else 11
                field.type_name = "." + target_file.package + "." + kind

    def fields(*values):
        return [(name, kind, False) for name, kind in values]

    message(file, "OwnedStory", fields(("storyId", 9), ("statusType", 5), ("isInvalid", 8), ("isPhotoShot", 8)))
    for name in ("UserGetResponse", "UpdatedData"):
        target = next(row for row in file.message_type if row.name == name)
        target.field.add(name="stories", number=len(target.field) + 1, label=3, type=11, type_name=".api.OwnedStory")
    message(file, "EventEpisode", fields(("episode", 5), ("unlocked", 8)))
    message(file, "EventInfo", fields(("id", 9)) + [("episodes", "EventEpisode", True)])
    message(file, "ExtraEpisode", fields(("episode", 5), ("unlocked", 8)))
    message(file, "ExtraInfo", fields(("id", 9), ("unlocked", 8)) + [("episodes", "ExtraEpisode", True)])
    message(file, "ExtraPartInfo", fields(("id", 9), ("unlocked", 8)) + [("stories", "ExtraInfo", True)])
    message(file, "EventResponse", [("infos", "EventInfo", True)] + fields(("commonResponse", "CommonResponse")))
    message(file, "ExtraResponse", [("infos", "ExtraPartInfo", True)] + fields(("commonResponse", "CommonResponse")))
    message(file, "StoryReadRequest", fields(("storyId", 9), ("isLast", 8)))
    home = next(row for row in file.message_type if row.name == "HomeEnterResponse")
    home.field.add(name="extraStoryPartInfos", number=len(home.field) + 1, label=3, type=11, type_name=".api.ExtraPartInfo")
    service = file.service.add(name="Story")
    for name, request, response in (("ListEvent", "Empty", "EventResponse"), ("ListExtra", "Empty", "ExtraResponse"),
                                    ("Read", "StoryReadRequest", "ActionResponse")):
        service.method.add(name=name, input_type=".api." + request, output_type=".api." + response)
    master = descriptors.file.add(name="story-master-test.proto", package="master", syntax="proto3")
    enum = master.enum_type.add(name="PlayType")
    for number in (0, 1):
        enum.value.add(name="PlayType" + str(number), number=number)
    message(master, "EventStoryEpisode", fields(("episode", 5), ("storyId", 9)))
    message(master, "EventStory", fields(("id", 9)) + [("episodes", "EventStoryEpisode", True)])
    message(master, "ExtraStoryPart", fields(("id", 9)) + [("extraStoryIds", 9, True)])
    message(master, "ExtraStoryEpisode", fields(("episode", 5), ("storyId", 9)))
    message(master, "ExtraStory", fields(("id", 9), ("extraStoryPartId", 9)) + [("episodes", "ExtraStoryEpisode", True)])
    message(master, "Story", fields(("id", 9)) + [("advPlayTypes", "PlayType", True), ("advAssetIds", 9, True)])
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture(scope="module", params=("small", "client-6.1.1"))
def schema(request, tmp_path_factory):
    if request.param == "small":
        return small_schema(tmp_path_factory.mktemp("story-schema") / "schema.pb")
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Optional recovered client descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path, monkeypatch):
    master, directory = tmp_path / "master", tmp_path / "public-story"
    master.mkdir()
    directory.mkdir()
    rows = {
        "EventStory": [{"id": "event-a", "episodes": [{"episode": 1, "storyId": "story-a"},
                                                        {"episode": 2, "storyId": "story-b"}]}],
        "ExtraStoryPart": [{"id": "part-a", "extraStoryIds": ["extra-a"]}],
        "ExtraStory": [{"id": "extra-a", "extraStoryPartId": "part-a",
                        "episodes": [{"episode": 1, "storyId": "story-c"}]}],
        "Story": [{"id": "story-" + key, "advPlayTypes": [1], "advAssetIds": ["public-" + key]} for key in "abc"],
    }
    for table, values in rows.items():
        (master / (table + ".json")).write_text(json.dumps(values))
    (master / "!version.txt").write_text("fixture-story-master")
    event = schema.response_type(EVENT)()
    info = event.infos.add(id="event-a")
    info.episodes.add(episode=1, unlocked=True)
    info.episodes.add(episode=2, unlocked=True)
    extra = schema.response_type(EXTRA)()
    part = extra.infos.add(id="part-a", unlocked=True)
    part.stories.add(id="extra-a", unlocked=True).episodes.add(episode=1, unlocked=True)
    pins = copy.deepcopy(module._SOURCES)
    for kind, response in (("event", event), ("extra", extra)):
        response.commonResponse.updatedData.SetInParent()
        response.commonResponse.deletedData.SetInParent()
        raw = response.SerializeToString(deterministic=True)
        pins[kind]["bytes"], pins[kind]["sha256"] = len(raw), hashlib.sha256(raw).hexdigest()
        (directory / pins[kind]["file"]).write_bytes(raw)
    monkeypatch.setattr(module, "_SOURCES", pins)
    monkeypatch.setattr(module, "_SCHEMA_SHA256", schema.fingerprint)
    monkeypatch.setattr(module, "_EXPECTED", {"event_infos": 1, "event_episodes": 2, "extra_parts": 1,
        "extra_stories": 1, "extra_episodes": 1, "referenced_stories": 3})
    entries = []
    for kind, pin in pins.items():
        entries.append({"kind": kind, **{name: pin[name] for name in ("method", "file", "bytes", "sha256")},
            "source": {"source_url": module._source_url(pin), "source_commit": module._COMMIT,
                       **{name: pin[name] for name in ("raw_bytes", "raw_sha256", "git_blob_sha1", "field")}}})
    manifest = {"schema": 1, "baseline_version": 1, "baseline_id": module.BASELINE_ID,
        "frozen_public_baseline": True, "schema_sha256": schema.fingerprint,
        "master_version": "fixture-story-master", "source_repository": module._REPOSITORY,
        "source_commit": module._COMMIT, "sanitization": module._SANITIZATION, "catalogs": entries}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    state = State(tmp_path / "profiles.sqlite")
    identity = state.ensure_profile("player")
    user = schema.response_type("/api.User/Get")()
    user.user.name = "Kept manager"
    user.userPublic.serverUserId, user.userPublic.publicUserId = identity["server_id"], identity["public_id"]
    story = user.stories.add(storyId="story-a", statusType=2)
    story.ParseFromString(story.SerializeToString() + _VarintBytes(60001 << 3) + _VarintBytes(19))
    raw = user.SerializeToString() + _VarintBytes(60000 << 3) + _VarintBytes(17)
    state.save_snapshot("player", raw, schema.fingerprint, starter_version=4)
    token, _ = state.login("player")
    return module.StoryCatalog(schema, master), state, master, rows, token


def dump(state):
    with state.connect() as db:
        return tuple(db.iterdump())


def test_pure_validation_and_both_lists_preserve_all_profile_read_state(game):
    provider, state, master, *_ = game
    before = dump(state)
    report = module.validate_story_catalog(provider.schema, master, provider.directory)
    assert report["all_master_links_valid"] and report["account_state_mutations"] is False
    assert report["counts"]["referenced_stories"] == 3
    for path in (EVENT, EXTRA):
        raw = provider.handle(path, b"")
        response = provider.schema.response_type(path).FromString(raw)
        assert response.infos and response.commonResponse.HasField("updatedData")
        assert response.commonResponse.HasField("deletedData")
        assert not response.commonResponse.updatedData.ListFields() and not response.commonResponse.deletedData.ListFields()
        assert provider.handle(path, b"") == raw
    assert dump(state) == before and state.authenticated(game[4], "player")
    assert provider.schema.response_type("/api.User/Get").FromString(state.snapshot("player")[0]).stories[0].statusType == 2


def test_home_uses_identical_extra_dtos_and_preserves_existing_account_override(game):
    provider = game[0]
    response = provider.schema.response_type("/api.Home/Enter")()
    response.commonResponse.updatedData.SetInParent()
    before_common = response.commonResponse.SerializeToString()
    provider.fill_home(response)
    extra = provider.schema.response_type(EXTRA).FromString(provider.handle(EXTRA, b""))
    assert list(response.extraStoryPartInfos) == list(extra.infos)
    assert response.commonResponse.SerializeToString() == before_common
    existing = provider.schema.response_type("/api.Home/Enter")()
    existing.extraStoryPartInfos.add(id="account-specific", unlocked=False)
    before = existing.SerializeToString()
    provider.fill_home(existing)
    assert existing.SerializeToString() == before


@pytest.mark.parametrize("change", ("event-missing", "event-episode", "extra-parent", "part-link", "story-missing", "story-enum"))
def test_master_link_errors_fail_closed(game, change):
    provider, _, master, rows, _ = game
    if change == "event-missing":
        rows["EventStory"][0]["id"] = "missing-event"
    elif change == "event-episode":
        rows["EventStory"][0]["episodes"].append({"episode": 3, "storyId": "story-a"})
    elif change == "extra-parent":
        rows["ExtraStory"][0]["extraStoryPartId"] = "other-part"
    elif change == "part-link":
        rows["ExtraStoryPart"][0]["extraStoryIds"] = []
    elif change == "story-missing":
        rows["Story"].pop()
    else:
        rows["Story"][0]["advPlayTypes"] = [99999]
    for table, values in rows.items():
        (master / (table + ".json")).write_text(json.dumps(values))
    with pytest.raises(ValueError):
        module.validate_story_catalog(provider.schema, master, provider.directory)
    with pytest.raises(RpcFailure) as error:
        provider.handle(EVENT, b"")
    assert error.value.code == RpcCode.FAILED_PRECONDITION


@pytest.mark.parametrize("change", ("version", "schema", "path", "source", "sanitization", "list-root"))
def test_manifest_tampering_is_rejected(game, change):
    provider = game[0]
    path = provider.directory / "manifest.json"
    manifest = json.loads(path.read_text())
    if change == "version":
        manifest["baseline_version"] = 2
    elif change == "schema":
        manifest["schema_sha256"] = "different-schema"
    elif change == "path":
        manifest["catalogs"][0]["file"] = "../outside.pb"
    elif change == "source":
        manifest["catalogs"][0]["source"]["raw_sha256"] = "wrong-source"
    elif change == "sanitization":
        manifest["sanitization"] = {}
    else:
        manifest = []
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        module.validate_story_catalog(provider.schema, game[2], provider.directory)


def test_corrupt_payload_and_malformed_request_are_distinct_failures(game):
    provider = game[0]
    with pytest.raises(RpcFailure) as error:
        provider.handle(EVENT, b"\x0a\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    path = provider.directory / "story-list-event.pb"
    path.write_bytes(path.read_bytes() + b"\x80")
    with pytest.raises(RpcFailure) as error:
        provider.handle(EVENT, b"")
    assert error.value.code == RpcCode.FAILED_PRECONDITION


def test_missing_bundle_disables_fallback_and_read_actions_remain_unsupported(game, tmp_path):
    assert module.StoryCatalog(None).handle(EVENT, b"") is None
    disabled = module.StoryCatalog(game[0].schema, tmp_path / "absent/master")
    assert disabled.handle(EVENT, b"") is None
    with pytest.raises(ValueError):
        module.validate_story_catalog(game[0].schema, game[2], tmp_path / "missing")
    assert game[0].handle("/api.Story/Read", b"") is None
    assert game[0].handle("/api.Story/ReadExtra", b"") is None
