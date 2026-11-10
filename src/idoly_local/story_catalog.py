"""Two immutable, observed public story catalogs; never story read progress.

The pinned fresh official ListEvent and Home.Enter captures contain only IDs
and eligibility in these DTOs. The client reads progress separately from
UserStory. No UserStory row, reward, condition or account update is applied.
This versioned baseline intentionally does not unlock every current master row.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from google.protobuf import message_factory
from google.protobuf.json_format import ParseDict, ParseError
from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


BASELINE_ID = "fresh-official-2026-10-25"
BASELINE_VERSION = 1
_COMMIT = "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02"
_REPOSITORY = "Project-Hoshimi/sumire-sr-data"
_SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
_SANITIZATION = {"dto_only": True, "common_response_empty": True, "user_story_state_absent": True}
_EXPECTED = {"event_infos": 55, "event_episodes": 272, "extra_parts": 3,
             "extra_stories": 41, "extra_episodes": 154, "referenced_stories": 425}
_SOURCES = {
    "event": {"method": "/api.Story/ListEvent", "file": "story-list-event.pb", "bytes": 2898,
              "sha256": "830ce025b2866706bb5b26f7ab54d5b63c8d87b6c33623e8b4c465c32c4e9252",
              "capture": "00016", "capture_method": "Story%3AListEvent", "field": "infos",
              "raw_bytes": 2898, "raw_sha256": "830ce025b2866706bb5b26f7ab54d5b63c8d87b6c33623e8b4c465c32c4e9252",
              "git_blob_sha1": "4f55a79af7cb050b143faf5c554ce2aacf183caf"},
    "extra": {"method": "/api.Story/ListExtra", "file": "story-list-extra.pb", "bytes": 2803,
              "sha256": "53972ca1710d59ca2d379e172ecda4d717edb0ab8627a08bd070793945ef925f",
              "capture": "00033", "capture_method": "Home%3AEnter", "field": "extraStoryPartInfos",
              "raw_bytes": 25011, "raw_sha256": "d956979f9d04a6a69ffc640ba6c2650f5bc7f34ece0236b466b37bdfcee5a193",
              "git_blob_sha1": "752438f94c1dcb40fc909d6254ffc8a7bbce40ef"},
}


def _require(condition, detail):
    if not condition:
        raise ValueError("Invalid public story catalog: " + detail)


def _source_url(pin):
    return ("https://raw.githubusercontent.com/" + _REPOSITORY + "/" + _COMMIT
            + "/captures/2026-10-25_fresh_official/raw/" + pin["capture"]
            + ".resp-plain." + pin["capture_method"] + ".bin")


def _known_message(message):
    clean = type(message)()
    clean.CopyFrom(message)
    clean.DiscardUnknownFields()
    _require(clean.SerializeToString(deterministic=True) == message.SerializeToString(deterministic=True),
             "unknown protobuf fields")
    for field, value in message.ListFields():
        for item in value if field.is_repeated else (value,):
            if field.message_type is not None:
                _known_message(item)
            elif field.enum_type is not None:
                _require(item in field.enum_type.values_by_number, "unknown enum value")


def _episodes(rows):
    result = {}
    for row in rows:
        _require(type(row.episode) is int and row.episode > 0 and row.episode not in result,
                 "duplicate or invalid episode number")
        result[row.episode] = row
    return result


def _validate_links(schema, catalog, event, extra):
    """Pure profile-independent referential checks for the frozen DTOs."""
    tables = {name: catalog.ids(name, required=True)
              for name in ("EventStory", "ExtraStoryPart", "ExtraStory", "Story")}
    parsed = {}

    def master(table, identity):
        _require(bool(identity) and identity in tables[table], "missing " + table + " reference")
        key = table, identity
        if key not in parsed:
            cls = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master." + table))
            message = cls()
            ParseDict(tables[table][identity], message)
            _known_message(message)
            parsed[key] = message
        return parsed[key]

    counts = {name: 0 for name in _EXPECTED}
    stories, seen_events, seen_parts = set(), set(), set()
    for info in event.infos:
        _require(info.id not in seen_events, "duplicate event identity")
        seen_events.add(info.id)
        definition = master("EventStory", info.id)
        episodes = _episodes(definition.episodes)
        selected = _episodes(info.episodes)
        _require(set(selected) == set(episodes), "public event episodes differ from the master")
        counts["event_infos"] += 1
        for number, episode in selected.items():
            _require(episode.unlocked, "public event eligibility changed")
            identity = episodes[number].storyId
            master("Story", identity)
            stories.add(identity)
            counts["event_episodes"] += 1
    for part in extra.infos:
        _require(part.id not in seen_parts and part.unlocked, "duplicate or locked public part")
        seen_parts.add(part.id)
        definition = master("ExtraStoryPart", part.id)
        allowed = list(definition.extraStoryIds)
        _require(len(allowed) == len(set(allowed)), "duplicate extra master references")
        seen_stories = set()
        counts["extra_parts"] += 1
        for info in part.stories:
            _require(info.id not in seen_stories and info.id in allowed and info.unlocked,
                     "invalid public extra story eligibility")
            seen_stories.add(info.id)
            definition = master("ExtraStory", info.id)
            _require(definition.extraStoryPartId == part.id, "extra story belongs to a different part")
            episodes = _episodes(definition.episodes)
            selected = _episodes(info.episodes)
            counts["extra_stories"] += 1
            for number, episode in selected.items():
                _require(number in episodes and episode.unlocked, "invalid public extra episode")
                identity = episodes[number].storyId
                master("Story", identity)
                stories.add(identity)
                counts["extra_episodes"] += 1
    counts["referenced_stories"] = len(stories)
    _require(counts == _EXPECTED, "frozen public baseline counts changed")
    return counts


def _load(schema, master_dir, directory):
    catalog = _Catalog(Path(master_dir))
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    _require(isinstance(manifest, dict), "manifest must be an object")
    _require(type(manifest.get("schema")) is int and manifest["schema"] == 1
             and type(manifest.get("baseline_version")) is int
             and manifest["baseline_version"] == BASELINE_VERSION
             and manifest.get("baseline_id") == BASELINE_ID
             and manifest.get("frozen_public_baseline") is True, "unsupported baseline version")
    _require(schema.fingerprint == _SCHEMA_SHA256 and manifest.get("schema_sha256") == schema.fingerprint,
             "schema fingerprint differs")
    version = catalog.version()
    _require(isinstance(version, str) and bool(version) and manifest.get("master_version") == version,
             "master version differs")
    _require(manifest.get("source_repository") == _REPOSITORY and manifest.get("source_commit") == _COMMIT,
             "source provenance differs")
    _require(manifest.get("sanitization") == _SANITIZATION, "sanitization contract differs")
    entries = manifest.get("catalogs")
    _require(isinstance(entries, list) and len(entries) == 2, "two public catalog files are required")
    payloads, responses, hashes = {}, {}, {}
    for entry in entries:
        _require(isinstance(entry, dict), "invalid catalog entry")
        kind = entry.get("kind")
        _require(kind in _SOURCES and kind not in responses, "unknown or duplicate catalog kind")
        pin = _SOURCES[kind]
        _require(all(entry.get(key) == pin[key] for key in ("method", "file", "bytes", "sha256")),
                 "catalog file pin differs")
        source = entry.get("source")
        _require(isinstance(source, dict) and source.get("source_url") == _source_url(pin)
                 and source.get("source_commit") == _COMMIT
                 and all(source.get(key) == pin[key] for key in ("raw_bytes", "raw_sha256", "git_blob_sha1", "field")),
                 "raw source pin differs")
        raw = (directory / pin["file"]).read_bytes()
        _require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
                 "catalog file digest differs")
        response = schema.response_type(pin["method"]).FromString(raw)
        _known_message(response)
        _require(response.HasField("commonResponse")
                 and response.commonResponse.HasField("updatedData")
                 and response.commonResponse.HasField("deletedData")
                 and not response.commonResponse.updatedData.ListFields()
                 and not response.commonResponse.deletedData.ListFields(), "account mutations are forbidden")
        payloads[pin["method"]] = raw
        responses[kind] = response
        hashes[kind] = {"bytes": len(raw), "sha256": pin["sha256"]}
    counts = _validate_links(schema, catalog, responses["event"], responses["extra"])
    report = {"baseline_id": BASELINE_ID, "baseline_version": BASELINE_VERSION,
              "schema_sha256": schema.fingerprint, "master_version": version,
              "counts": counts, "catalogs": hashes, "all_master_links_valid": True,
              "account_state_mutations": False}
    return payloads, report


def validate_story_catalog(schema, master_dir: Path, directory: Path) -> dict:
    """Strict builder validation; missing data is an error, not an empty list."""
    try:
        return _load(schema, master_dir, directory)[1]
    except (OSError, DecodeError, ParseError, RpcFailure, KeyError, TypeError) as error:
        raise ValueError("Invalid public story catalog: local data or schema is unavailable") from error


class StoryCatalog:
    """Serve the frozen public fallback after account fixtures and authentication."""

    def __init__(self, schema, master_dir: Path | None = None):
        self.schema = schema
        self.master_dir = Path(master_dir) if master_dir is not None else None
        self.directory = self.master_dir.parent / "public-story" if self.master_dir is not None else None
        self._payloads = None

    def _enabled(self):
        return self.directory is not None and self.directory.is_dir()

    def _templates(self):
        if self._payloads is None:
            try:
                self._payloads, _ = _load(self.schema, self.master_dir, self.directory)
            except (OSError, ValueError, DecodeError, ParseError, RpcFailure, KeyError, TypeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Public story catalog failed its local validation") from None
        return self._payloads

    def handle(self, path, plain):
        if path not in (pin["method"] for pin in _SOURCES.values()) or not self._enabled():
            return None
        if path not in self.schema.methods:
            return None
        try:
            self.schema.request_type(path).FromString(plain)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed story catalog request") from None
        return self._templates()[path]

    def fill_home(self, result) -> None:
        if (not self._enabled() or "extraStoryPartInfos" not in result.DESCRIPTOR.fields_by_name
                or result.extraStoryPartInfos):
            return
        path = _SOURCES["extra"]["method"]
        if path not in self.schema.methods:
            return
        extra = self.schema.response_type(path).FromString(self._templates()[path])
        result.extraStoryPartInfos.extend(extra.infos)
