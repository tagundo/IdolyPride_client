"""Opt-in read-only catalog checks over the native engines' encrypted RPCs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


_SOURCE = "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02"
_PINS = {
    "event": (2898, "830ce025b2866706bb5b26f7ab54d5b63c8d87b6c33623e8b4c465c32c4e9252"),
    "extra": (2803, "53972ca1710d59ca2d379e172ecda4d717edb0ab8627a08bd070793945ef925f"),
}


def _require(condition, message):
    if not condition:
        raise RuntimeError("Story catalog QA: " + message)


def _bytes(value):
    return value.SerializeToString(deterministic=True)


def _empty_common(response):
    _require(response.HasField("commonResponse"), "catalog omitted its common response")
    expected = type(response.commonResponse)()
    expected.updatedData.SetInParent()
    expected.deletedData.SetInParent()
    _require(_bytes(response.commonResponse) == _bytes(expected),
             "catalog omitted the two empty common DTOs or returned account updates")


def _baseline(schema, directory):
    public = directory.parent / "public-story"
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    _require(manifest.get("schema") == manifest.get("baseline_version") == 1
             and manifest.get("baseline_id") == "fresh-official-2026-10-25"
             and manifest.get("frozen_public_baseline") is True
             and manifest.get("source_repository") == "Project-Hoshimi/sumire-sr-data"
             and manifest.get("source_commit") == _SOURCE
             and manifest.get("schema_sha256") == schema.fingerprint
             and manifest.get("master_version") == (directory / "!version.txt").read_text().strip()
             and manifest.get("sanitization") == {"dto_only": True, "common_response_empty": True,
                                                   "user_story_state_absent": True},
             "public story provenance/schema/master baseline differs")
    entries = manifest.get("catalogs", [])
    _require(len(entries) == 2 and {row.get("kind") for row in entries} == set(_PINS),
             "public story manifest must contain exactly event and extra catalogs")
    result = {}
    for kind, (size, digest) in _PINS.items():
        method, filename = "/api.Story/List" + kind.title(), "story-list-" + kind + ".pb"
        entry = next(row for row in entries if row["kind"] == kind)
        _require(entry.get("method") == method and entry.get("file") == filename
                 and entry.get("bytes") == size and entry.get("sha256") == digest
                 and entry.get("source", {}).get("source_commit") == _SOURCE,
                 "catalog manifest differs from its immutable public pin")
        raw = (public / filename).read_bytes()
        _require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
                 "public story body failed its immutable size/SHA-256 pin")
        message = schema.response_type(method).FromString(raw)
        _empty_common(message)
        result[kind] = message
    return result


def _masters(directory):
    tables = {}
    for name in ("EventStory", "ExtraStoryPart", "ExtraStory", "Story"):
        rows = json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))
        _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
                 "invalid public " + name + " table")
        indexed = {row.get("id"): row for row in rows}
        _require(len(indexed) == len(rows) and all(isinstance(key, str) and key for key in indexed),
                 "ambiguous public " + name + " identities")
        tables[name] = indexed
    return tables


def _episodes(infos, row, stories):
    definitions = row.get("episodes", [])
    indexed = {value.get("episode"): value for value in definitions}
    _require(len(indexed) == len(definitions) and len({info.episode for info in infos}) == len(infos),
             "duplicate master or catalog episode numbers")
    for info in infos:
        source = indexed.get(info.episode)
        _require(info.episode > 0 and source is not None and source.get("storyId") in stories,
                 "catalog episode does not resolve through the public Story table")


def _references(event, extra, tables):
    _require(len({row.id for row in event.infos}) == len(event.infos), "duplicate event catalog identities")
    for info in event.infos:
        _require(info.id in tables["EventStory"], "catalog event is absent from public EventStory")
        _episodes(info.episodes, tables["EventStory"][info.id], tables["Story"])
    _require(len({row.id for row in extra.infos}) == len(extra.infos), "duplicate extra part identities")
    seen = set()
    for part in extra.infos:
        definition = tables["ExtraStoryPart"].get(part.id)
        _require(definition is not None, "catalog extra part is absent from the public master")
        for info in part.stories:
            story = tables["ExtraStory"].get(info.id)
            _require(info.id not in seen and story is not None and story.get("extraStoryPartId") == part.id
                     and info.id in definition.get("extraStoryIds", []),
                     "catalog extra story does not belong to its public parent part")
            seen.add(info.id)
            _episodes(info.episodes, story, tables["Story"])


def run_story_catalog_checks(schema, invoke, master_dir):
    """Check frozen eligibility without interpreting or changing UserStory.Read."""
    directory = Path(master_dir)
    canonical = _baseline(schema, directory)
    tables = _masters(directory)

    def rpc(path, **fields):
        return invoke(path, schema.request_type(path)(**fields))

    before = rpc("/api.User/Get")
    event = rpc("/api.Story/ListEvent")
    extra = rpc("/api.Story/ListExtra")
    for kind, response in (("event", event), ("extra", extra)):
        _empty_common(response)
        _require(_bytes(response) == _bytes(canonical[kind]),
                 "real " + kind + " RPC differs from the frozen public eligibility baseline")
    _references(event, extra, tables)
    counts = (len(event.infos), sum(len(row.episodes) for row in event.infos), len(extra.infos),
              sum(len(row.stories) for row in extra.infos),
              sum(len(story.episodes) for part in extra.infos for story in part.stories))
    _require(counts == (55, 272, 3, 41, 154), "frozen public catalog counts differ")
    home = rpc("/api.Home/Enter", skipUpdate=True)
    _require([_bytes(row) for row in home.extraStoryPartInfos] == [_bytes(row) for row in extra.infos],
             "Home.extraStoryPartInfos differs from Story.ListExtra")
    _require(_bytes(rpc("/api.User/Get")) == _bytes(before),
             "story lists or Home.Enter modified the user's snapshot/read status")
    _require(_bytes(rpc("/api.Story/ListEvent")) == _bytes(event)
             and _bytes(rpc("/api.Story/ListExtra")) == _bytes(extra)
             and _bytes(rpc("/api.User/Get")) == _bytes(before),
             "repeated catalog reads changed eligibility or the user's snapshot")
    names = ("story_catalog_event_count", "story_catalog_event_episode_count", "story_catalog_extra_part_count",
             "story_catalog_extra_story_count", "story_catalog_extra_episode_count")
    return {"story_catalog_event": True, "story_catalog_extra": True,
            "story_catalog_home_consistent": True, "story_catalog_readonly": True,
            **dict(zip(names, counts)), "story_catalog_preserved_read_count": sum(row.statusType == 2 for row in before.stories),
            "story_catalog_snapshot_sha256": hashlib.sha256(_bytes(before)).hexdigest()}
