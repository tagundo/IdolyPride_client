"""Independent story QA contracts without requiring downloaded game data."""
import hashlib
import json

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.schema import Schema
from idoly_local import story_qa as qa


def _schema(path):
    file = descriptor_pb2.FileDescriptorProto(name="story-qa.proto", package="api", syntax="proto3")
    def message(name, fields=()):
        result = file.message_type.add(name=name)
        for name, number, kind, repeated in fields:
            field = result.field.add(name=name, number=number, label=3 if repeated else 1)
            if isinstance(kind, int):
                field.type = kind
            else:
                field.type, field.type_name = 11, ".api." + kind
        return result
    message("Empty")
    message("UserStory", (("storyId", 1, 9, False), ("statusType", 2, 5, False)))
    message("UserGet", (("stories", 1, "UserStory", True),))
    message("Common", (("updatedData", 1, "UserGet", False), ("deletedData", 2, "UserGet", False)))
    message("Episode", (("episode", 1, 5, False), ("unlocked", 2, 8, False)))
    message("Event", (("id", 1, 9, False), ("episodes", 2, "Episode", True)))
    message("ExtraStory", (("id", 1, 9, False), ("unlocked", 2, 8, False), ("episodes", 3, "Episode", True)))
    message("Part", (("id", 1, 9, False), ("unlocked", 2, 8, False), ("stories", 3, "ExtraStory", True)))
    message("Events", (("infos", 1, "Event", True), ("commonResponse", 9999, "Common", False)))
    message("Extras", (("infos", 1, "Part", True), ("commonResponse", 9999, "Common", False)))
    message("HomeRequest", (("skipUpdate", 1, 8, False),))
    message("HomeResponse", (("extraStoryPartInfos", 33, "Part", True),))
    for service, method, request, response in (("System", "Check", "Empty", "Empty"), ("User", "Get", "Empty", "UserGet"),
        ("Story", "ListEvent", "Empty", "Events"), ("Story", "ListExtra", "Empty", "Extras"),
        ("Home", "Enter", "HomeRequest", "HomeResponse")):
        target = next((row for row in file.service if row.name == service), None)
        if target is None:
            target = file.service.add(name=service)
        target.method.add(name=method, input_type=".api." + request, output_type=".api." + response)
    descriptor = descriptor_pb2.FileDescriptorSet()
    descriptor.file.add().CopyFrom(file)
    path.write_bytes(descriptor.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    schema = _schema(tmp_path / "schema.pb")
    master, public = tmp_path / "master-json", tmp_path / "public-story"
    master.mkdir()
    public.mkdir()
    tables = {name: [] for name in ("EventStory", "ExtraStoryPart", "ExtraStory", "Story")}
    event = schema.response_type("/api.Story/ListEvent")()
    extra = schema.response_type("/api.Story/ListExtra")()
    for i in range(55):
        identity = "event-" + str(i)
        info = event.infos.add(id=identity)
        row = {"id": identity, "episodes": []}
        for number in range(1, (5 if i < 52 else 4) + 1):
            story = identity + "-" + str(number)
            row["episodes"].append({"episode": number, "storyId": story})
            tables["Story"].append({"id": story})
            info.episodes.add(episode=number, unlocked=bool(number % 2))
        tables["EventStory"].append(row)
    index = 0
    for i, count in enumerate((14, 14, 13)):
        identity = "part-" + str(i)
        part = extra.infos.add(id=identity, unlocked=True)
        parent = {"id": identity, "extraStoryIds": []}
        for _ in range(count):
            story_id = "extra-" + str(index)
            parent["extraStoryIds"].append(story_id)
            info = part.stories.add(id=story_id, unlocked=bool(index % 2))
            row = {"id": story_id, "extraStoryPartId": identity, "episodes": []}
            for number in range(1, (4 if index < 31 else 3) + 1):
                episode_id = story_id + "-" + str(number)
                info.episodes.add(episode=number, unlocked=bool(number % 2))
                row["episodes"].append({"episode": number, "storyId": episode_id})
                tables["Story"].append({"id": episode_id})
            tables["ExtraStory"].append(row)
            index += 1
        tables["ExtraStoryPart"].append(parent)
    pins, entries = {}, []
    for kind, message in (("event", event), ("extra", extra)):
        message.commonResponse.updatedData.SetInParent()
        message.commonResponse.deletedData.SetInParent()
        raw = message.SerializeToString(deterministic=True)
        pins[kind] = (len(raw), hashlib.sha256(raw).hexdigest())
        filename = "story-list-" + kind + ".pb"
        (public / filename).write_bytes(raw)
        entries.append({"kind": kind, "method": "/api.Story/List" + kind.title(), "file": filename,
            "bytes": len(raw), "sha256": pins[kind][1], "source": {"source_commit": qa._SOURCE}})
    # The unit protocol uses independent IDs and wire descriptors; only its
    # trusted capture pins are substituted, never production eligibility logic.
    monkeypatch.setattr(qa, "_PINS", pins)
    manifest = {"schema": 1, "baseline_version": 1, "baseline_id": "fresh-official-2026-10-25",
        "frozen_public_baseline": True, "source_repository": "Project-Hoshimi/sumire-sr-data",
        "source_commit": qa._SOURCE, "schema_sha256": schema.fingerprint, "master_version": "fixture-master",
        "sanitization": {"dto_only": True, "common_response_empty": True, "user_story_state_absent": True},
        "catalogs": entries}
    (public / "manifest.json").write_text(json.dumps(manifest))
    (master / "!version.txt").write_text("fixture-master")
    for name, rows in tables.items():
        (master / (name + ".json")).write_text(json.dumps(rows))
    user = schema.response_type("/api.User/Get")()
    user.stories.add(storyId="event-0-1", statusType=2)
    user.stories.add(storyId="unrelated-read-story", statusType=2)
    user.MergeFromString(b"\x80\x4b\x7b")
    home = schema.response_type("/api.Home/Enter")()
    home.extraStoryPartInfos.extend(extra.infos)
    responses = {"/api.User/Get": user, "/api.Story/ListEvent": event,
                 "/api.Story/ListExtra": extra, "/api.Home/Enter": home}
    calls = []
    def invoke(path, request):
        if path == "/api.Home/Enter":
            assert request.skipUpdate is True
        calls.append(path)
        return type(responses[path]).FromString(responses[path].SerializeToString())
    return schema, master, public, tables, responses, calls, invoke


def test_frozen_eligibility_remains_exact_with_existing_read2_and_unknown_user_fields(catalog):
    schema, master, _public, _tables, responses, _calls, invoke = catalog
    saved = responses["/api.User/Get"].SerializeToString()
    result = qa.run_story_catalog_checks(schema, invoke, master)
    assert all(result[key] is True for key in ("story_catalog_event", "story_catalog_extra",
        "story_catalog_home_consistent", "story_catalog_readonly"))
    assert tuple(result[key] for key in ("story_catalog_event_count", "story_catalog_event_episode_count",
        "story_catalog_extra_part_count", "story_catalog_extra_story_count", "story_catalog_extra_episode_count")) == (55, 272, 3, 41, 154)
    assert result["story_catalog_preserved_read_count"] == 2
    assert responses["/api.User/Get"].SerializeToString() == saved


@pytest.mark.parametrize("fault", ("read-filtered-eligibility", "missing-empty-dto", "account-update",
                                  "home-extra", "user-read-state", "repeat-changed"))
def test_qa_rejects_wrong_eligibility_home_updates_or_read_state(catalog, fault):
    schema, master, _public, _tables, _responses, calls, real = catalog
    def invoke(path, request):
        result = real(path, request)
        if path == "/api.Story/ListEvent":
            if fault == "read-filtered-eligibility" or fault == "repeat-changed" and calls.count(path) == 2:
                result.infos[0].episodes[0].unlocked = False
            elif fault == "missing-empty-dto":
                result.commonResponse.ClearField("deletedData")
            elif fault == "account-update":
                result.commonResponse.updatedData.stories.add(storyId="unexpected", statusType=2)
        elif path == "/api.Home/Enter" and fault == "home-extra":
            result.extraStoryPartInfos[0].unlocked = False
        elif path == "/api.User/Get" and fault == "user-read-state" and calls.count(path) > 1:
            result.stories[0].statusType = 0
        return result
    with pytest.raises(RuntimeError):
        qa.run_story_catalog_checks(schema, invoke, master)


@pytest.mark.parametrize("fault", ("public-bytes", "manifest-schema", "event-link", "extra-parent", "part-membership"))
def test_qa_rejects_untrusted_public_baseline_or_broken_master_references(catalog, fault):
    schema, master, public, tables, _responses, _calls, invoke = catalog
    if fault == "public-bytes":
        path = public / "story-list-extra.pb"
        path.write_bytes(path.read_bytes() + b"\xa0\x06\x01")
    elif fault == "manifest-schema":
        path = public / "manifest.json"
        data = json.loads(path.read_text())
        data["schema_sha256"] = "wrong-schema"
        path.write_text(json.dumps(data))
    else:
        name = {"event-link": "EventStory", "extra-parent": "ExtraStory", "part-membership": "ExtraStoryPart"}[fault]
        if fault == "event-link":
            tables[name][0]["episodes"][0]["storyId"] = "unknown-story"
        elif fault == "extra-parent":
            tables[name][0]["extraStoryPartId"] = "wrong-part"
        else:
            tables[name][0]["extraStoryIds"] = []
        (master / (name + ".json")).write_text(json.dumps(tables[name]))
    with pytest.raises(RuntimeError):
        qa.run_story_catalog_checks(schema, invoke, master)
