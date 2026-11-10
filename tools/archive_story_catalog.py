#!/usr/bin/env python3
"""Archive two pinned public story catalogs without copying account state.

Only the immutable public captures named below are downloaded. Official game
APIs are never contacted; source bodies stay in memory and are not saved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from google.protobuf.json_format import ParseDict, ParseError
from google.protobuf.message import DecodeError

from idoly_local.schema import Schema


SOURCE_REPOSITORY = "Project-Hoshimi/sumire-sr-data"
SOURCE_COMMIT = "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02"
BASELINE_ID = "fresh-official-2026-10-25"
DEFAULT_MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
MAX_RESPONSE_BYTES = 64 * 1024
_COUNTS = {"event": (55, 272), "extra": (3, 41, 154)}
_ROOT = ("https://raw.githubusercontent.com/" + SOURCE_REPOSITORY + "/" + SOURCE_COMMIT
         + "/captures/2026-10-25_fresh_official/raw/")
_SOURCES = (
    {"kind": "event", "method": "/api.Story/ListEvent", "field": "infos",
     "source_url": _ROOT + "00016.resp-plain.Story%3AListEvent.bin",
     "raw_bytes": 2898,
     "raw_sha256": "830ce025b2866706bb5b26f7ab54d5b63c8d87b6c33623e8b4c465c32c4e9252",
     "git_blob_sha1": "4f55a79af7cb050b143faf5c554ce2aacf183caf",
     "sanitized_bytes": 2898,
     "sanitized_sha256": "830ce025b2866706bb5b26f7ab54d5b63c8d87b6c33623e8b4c465c32c4e9252"},
    {"kind": "extra", "method": "/api.Story/ListExtra", "field": "extraStoryPartInfos",
     "source_url": _ROOT + "00033.resp-plain.Home%3AEnter.bin",
     "raw_bytes": 25011,
     "raw_sha256": "d956979f9d04a6a69ffc640ba6c2650f5bc7f34ece0236b466b37bdfcee5a193",
     "git_blob_sha1": "752438f94c1dcb40fc909d6254ffc8a7bbce40ef",
     "sanitized_bytes": 2803,
     "sanitized_sha256": "53972ca1710d59ca2d379e172ecda4d717edb0ab8627a08bd070793945ef925f"},
)


class StoryArchiveError(ValueError):
    """The pinned source, schema or local output failed validation."""


def _field(descriptor, name, number, kind, repeated=False):
    value = descriptor.fields_by_name.get(name)
    if (value is None or value.number != number or value.type != kind
            or value.is_repeated != repeated):
        raise StoryArchiveError("Schema does not match the story catalog contract")
    return value.message_type


def _dto_fields(descriptor, specifications):
    if set(descriptor.fields_by_name) != {row[0] for row in specifications}:
        raise StoryArchiveError("Schema does not match the story catalog DTO contract")
    return [_field(descriptor, *row) for row in specifications]


def _classes(schema):
    try:
        event = schema.response_type("/api.Story/ListEvent")
        extra = schema.response_type("/api.Story/ListExtra")
        home = schema.response_type("/api.Home/Enter")
        event_info = _field(event.DESCRIPTOR, "infos", 1, 11, True)
        _, episode = _dto_fields(event_info, [("id", 1, 9), ("episodes", 2, 11, True)])
        _dto_fields(episode, [("episode", 1, 5), ("unlocked", 2, 8)])
        part = _field(extra.DESCRIPTOR, "infos", 1, 11, True)
        _, _, story = _dto_fields(part, [("id", 1, 9), ("unlocked", 2, 8), ("stories", 3, 11, True)])
        _, _, episode = _dto_fields(story, [("id", 1, 9), ("unlocked", 2, 8), ("episodes", 3, 11, True)])
        _dto_fields(episode, [("episode", 1, 5), ("unlocked", 2, 8)])
        home_part = _field(home.DESCRIPTOR, "extraStoryPartInfos", 33, 11, True)
        if home_part.full_name != part.full_name:
            raise StoryArchiveError("Home and story catalogs use different DTO types")
        for response in (event, extra):
            common = _field(response.DESCRIPTOR, "commonResponse", 9999, 11)
            _field(common, "updatedData", 1, 11)
            _field(common, "deletedData", 2, 11)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise StoryArchiveError("Schema does not match the story catalog contract") from None
    return event, extra, home


def _parse(message, raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise StoryArchiveError("Public story response has an invalid size")
    try:
        return message.FromString(raw)
    except DecodeError:
        raise StoryArchiveError("Public story response is malformed") from None


def _known_dto(dto):
    understood = type(dto)()
    understood.CopyFrom(dto)
    understood.DiscardUnknownFields()
    if understood.SerializeToString(deterministic=True) != dto.SerializeToString(deterministic=True):
        raise StoryArchiveError("Public story DTO contains unknown protobuf fields")


def sanitize_story_catalog(schema, event_raw: bytes, home_raw: bytes) -> dict[str, bytes]:
    """Copy only reviewed catalog fields into fresh responses with empty common DTOs."""
    event_class, extra_class, home_class = _classes(schema)
    source_event, source_home = _parse(event_class, event_raw), _parse(home_class, home_raw)
    if not source_event.infos or not source_home.extraStoryPartInfos:
        raise StoryArchiveError("Public story response does not contain the expected catalog")
    event, extra = event_class(), extra_class()
    for info in source_event.infos:
        _known_dto(info)
        target = event.infos.add(id=info.id)
        for episode in info.episodes:
            target.episodes.add(episode=episode.episode, unlocked=episode.unlocked)
    for part in source_home.extraStoryPartInfos:
        _known_dto(part)
        target_part = extra.infos.add(id=part.id, unlocked=part.unlocked)
        for story in part.stories:
            target_story = target_part.stories.add(id=story.id, unlocked=story.unlocked)
            for episode in story.episodes:
                target_story.episodes.add(episode=episode.episode, unlocked=episode.unlocked)
    for response in (event, extra):
        response.commonResponse.updatedData.SetInParent()
        response.commonResponse.deletedData.SetInParent()
    return {"event": event.SerializeToString(deterministic=True),
            "extra": extra.SerializeToString(deterministic=True)}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise StoryArchiveError("Pinned public story download redirected unexpectedly")


def _download(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": "IdolyPride-public-story-archive/1"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            if response.status != 200:
                raise StoryArchiveError("Pinned public story download failed")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > limit):
                raise StoryArchiveError("Public story download exceeds its size limit")
            raw = response.read(limit + 1)
    except (OSError, URLError):
        raise StoryArchiveError("Pinned public story download failed") from None
    if len(raw) > limit:
        raise StoryArchiveError("Public story download exceeds its size limit")
    return raw


def _verify_source(raw, source):
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES or len(raw) != source["raw_bytes"]:
        raise StoryArchiveError("Pinned public story response size did not match")
    if hashlib.sha256(raw).hexdigest() != source["raw_sha256"]:
        raise StoryArchiveError("Pinned public story response SHA256 did not match")
    identity = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    if hashlib.sha1(identity).hexdigest() != source["git_blob_sha1"]:
        raise StoryArchiveError("Pinned public story Git blob identity did not match")


def _master_version(schema, master_tag):
    if master_tag is None:
        return DEFAULT_MASTER_VERSION
    try:
        path = Path(master_tag)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        tag = schema.response_type("/api.Master/Get")().masterTag
        ParseDict(value, tag)
        version = tag.version
        if (not version or len(version) > 256 or version != version.strip()
                or any(ord(char) < 33 or ord(char) > 126 for char in version)):
            raise ValueError()
    except (OSError, ValueError, TypeError, AttributeError, ParseError):
        raise StoryArchiveError("Cannot read a valid local MasterTag version") from None
    return version


def archive_story_catalog(schema, master_tag: Path | None, output: Path, *, fetch=None) -> dict:
    """Explicitly archive pinned public sources; never overwrite an existing output.

    ``fetch(url, limit)`` permits offline verification. Importing this module
    performs no downloads, and fetched account envelopes are never written.
    """
    _classes(schema)
    version = _master_version(schema, master_tag)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise StoryArchiveError("Story output already exists; choose a new directory")
    fetch = fetch or _download
    raw_sources = []
    for source in _SOURCES:
        raw = fetch(source["source_url"], MAX_RESPONSE_BYTES)
        _verify_source(raw, source)
        raw_sources.append(raw)
    payloads = sanitize_story_catalog(schema, *raw_sources)
    event_class, extra_class, _ = _classes(schema)
    event = event_class.FromString(payloads["event"])
    extra = extra_class.FromString(payloads["extra"])
    counts = {"event": (len(event.infos), sum(len(info.episodes) for info in event.infos)),
        "extra": (len(extra.infos), sum(len(part.stories) for part in extra.infos),
                  sum(len(story.episodes) for part in extra.infos for story in part.stories))}
    if counts != _COUNTS:
        raise StoryArchiveError("Pinned public story catalog counts did not match")
    entries = []
    for source in _SOURCES:
        safe = payloads[source["kind"]]
        if (len(safe) != source["sanitized_bytes"]
                or hashlib.sha256(safe).hexdigest() != source["sanitized_sha256"]):
            raise StoryArchiveError("Sanitized public story catalog identity did not match")
        entries.append({"kind": source["kind"], "method": source["method"],
            "file": "story-list-" + source["kind"] + ".pb", "bytes": len(safe),
            "sha256": hashlib.sha256(safe).hexdigest(), "source": {
                **{key: source[key] for key in ("source_url", "raw_bytes", "raw_sha256", "git_blob_sha1", "field")},
                "source_commit": SOURCE_COMMIT}})
    manifest = {"schema": 1, "baseline_version": 1, "baseline_id": BASELINE_ID,
        "schema_sha256": schema.fingerprint, "master_version": version,
        "source_repository": SOURCE_REPOSITORY, "source_commit": SOURCE_COMMIT,
        "frozen_public_baseline": True, "sanitization": {
            "dto_only": True, "common_response_empty": True, "user_story_state_absent": True},
        "catalogs": entries}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".public-story-") as temporary:
        stage = Path(temporary) / "archive"
        stage.mkdir()
        for entry in entries:
            path = stage / entry["file"]
            path.write_bytes(payloads[entry["kind"]])
            path.chmod(0o600)
        path = stage / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
        stage.rename(output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor-set", type=Path, default=Path("data/protocol/idolypride-6.1.1.pb"))
    parser.add_argument("--master-tag", type=Path, help="Optional local MasterTag version override")
    parser.add_argument("--output", type=Path, default=Path("data/public-story"))
    args = parser.parse_args(argv)
    try:
        schema = Schema.from_descriptor_set(args.descriptor_set)
        manifest = archive_story_catalog(schema, args.master_tag, args.output)
    except (StoryArchiveError, OSError, ValueError, DecodeError) as error:
        if isinstance(error, StoryArchiveError):
            parser.exit(1, f"Story catalog archive failed: {error}\n")
        parser.exit(1, "Story catalog archive failed: supplied schema or local output is unavailable\n")
    print(json.dumps({"archived": len(manifest["catalogs"]), "baseline_id": BASELINE_ID,
        "schema_sha256": manifest["schema_sha256"], "master_version": manifest["master_version"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
