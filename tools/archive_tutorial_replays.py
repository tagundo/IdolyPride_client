#!/usr/bin/env python3
"""Archive two pinned public tutorial demonstrations, removing account identity.

Only captured data from the immutable public data commit below is downloaded.
No official game API, login, account state, server implementation or simulation
code is used. The original bodies remain in memory and are never saved.
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


METHOD = "/api.Tutorial/StartQuest"
SOURCE_REPOSITORY = "Project-Hoshimi/sumire-sr-data"
SOURCE_COMMIT = "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02"
MAX_RESPONSE_BYTES = 64 * 1024
_SOURCE_ROOT = ("https://raw.githubusercontent.com/" + SOURCE_REPOSITORY + "/" + SOURCE_COMMIT
                + "/captures/2026-10-25_fresh_official/raw/")
_SOURCES = (
    {"kind": "short", "source_url": _SOURCE_ROOT + "00026.resp-plain.Tutorial%3AStartQuest.bin",
     "raw_bytes": 31314, "raw_sha256": "532c199a7fe2daaeedf7ba9cb0c28a988d4dc0e549bcfd30dadcdf274d56f8ae",
     "git_blob_sha1": "2a6c581866d41c91ebc0890d19656b72ef7090ca"},
    {"kind": "full", "source_url": _SOURCE_ROOT + "00028.resp-plain.Tutorial%3AStartQuest.bin",
     "raw_bytes": 32321, "raw_sha256": "0cd36f73aff5f733633528434a19af179797241f01195b0c4a2888d8736acd3c",
     "git_blob_sha1": "8d17c867ec2a6b30bf9a3fd938fc811f9cbeca1b"},
)


class TutorialArchiveError(ValueError):
    """A pinned source, schema or output did not pass validation."""


def _field(descriptor, name, number, kind, repeated=False):
    value = descriptor.fields_by_name.get(name)
    if (value is None or value.number != number or value.type != kind
            or value.is_repeated != repeated):
        raise TutorialArchiveError("Schema does not match the tutorial replay contract")
    return value.message_type


def _response_class(schema):
    try:
        response = schema.response_type(METHOD)
        result = _field(response.DESCRIPTOR, "result", 1, 11)
        _field(response.DESCRIPTOR, "rankPatterns", 2, 11, True)
        _field(response.DESCRIPTOR, "commonResponse", 9999, 11)
        user = _field(result, "userInfos", 1, 11, True)
        _field(result, "charts", 3, 11, True)
        _field(result, "isDisplayDetailAvailable", 6, 8)
        _field(result, "detailLogId", 8, 9)
        _field(user, "userId", 2, 9)
        _field(user, "name", 3, 9)
        deck = _field(user, "userDeck", 5, 11)
        _field(deck, "cards", 2, 11, True)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise TutorialArchiveError("Schema does not match the tutorial replay contract") from None
    return response


def sanitize_replay(schema, raw: bytes) -> bytes:
    """Copy the fixed demonstration and ranks into a new, identity-free reply."""
    response_class = _response_class(schema)
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise TutorialArchiveError("Public tutorial response has an invalid size")
    try:
        original = response_class.FromString(raw)
    except DecodeError:
        raise TutorialArchiveError("Public tutorial response is malformed") from None
    if (not original.HasField("result") or len(original.result.userInfos) != 1
            or len(original.result.userInfos[0].userDeck.cards) != 5
            or not original.result.charts or len(original.rankPatterns) != 3):
        raise TutorialArchiveError("Public tutorial response is not the fixed demonstration")
    result = response_class()
    result.result.CopyFrom(original.result)
    result.rankPatterns.extend(original.rankPatterns)
    understood = response_class()
    understood.CopyFrom(result)
    understood.DiscardUnknownFields()
    if understood.SerializeToString(deterministic=True) != result.SerializeToString(deterministic=True):
        raise TutorialArchiveError("Schema cannot fully preserve the public tutorial demonstration")
    result.result.userInfos[0].ClearField("userId")
    result.result.userInfos[0].ClearField("name")
    result.result.ClearField("detailLogId")
    result.result.isDisplayDetailAvailable = False
    result.commonResponse.SetInParent()
    # The result/ranks were checked above. No unreviewed account/envelope fields
    # are allowed into the fresh response.
    result.DiscardUnknownFields()
    sanitized = result.SerializeToString(deterministic=True)
    sensitive = (original.result.userInfos[0].userId, original.result.userInfos[0].name,
                 original.result.detailLogId)
    if any(value and value.encode("utf-8") in sanitized for value in sensitive):
        raise TutorialArchiveError("Identity material remains outside the expected replay fields")
    return sanitized


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TutorialArchiveError("Pinned public tutorial download redirected unexpectedly")


def _download(url: str, limit: int) -> bytes:
    request = Request(url, headers={"User-Agent": "IdolyPride-public-tutorial-archive/1"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            if response.status != 200:
                raise TutorialArchiveError("Pinned public tutorial download failed")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > limit):
                raise TutorialArchiveError("Public tutorial download exceeds its size limit")
            raw = response.read(limit + 1)
    except (OSError, URLError):
        raise TutorialArchiveError("Pinned public tutorial download failed") from None
    if len(raw) > limit:
        raise TutorialArchiveError("Public tutorial download exceeds its size limit")
    return raw


def _verify_source(raw, source):
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES or len(raw) != source["raw_bytes"]:
        raise TutorialArchiveError("Pinned public tutorial response size did not match")
    if hashlib.sha256(raw).hexdigest() != source["raw_sha256"]:
        raise TutorialArchiveError("Pinned public tutorial response SHA256 did not match")
    blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    if hashlib.sha1(blob).hexdigest() != source["git_blob_sha1"]:
        raise TutorialArchiveError("Pinned public tutorial Git blob identity did not match")


def _master_version(schema, master_tag):
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
        raise TutorialArchiveError("Cannot read a valid local MasterTag version") from None
    return version


def archive_tutorial_replays(schema, master_tag: Path, output: Path, *, fetch=None) -> dict:
    """Verify both pinned sources and atomically save only sanitized responses.

    ``fetch(url, limit)`` can supply an offline trusted byte source for testing.
    Pins are always checked. An existing output directory is never overwritten.
    """
    _response_class(schema)
    version = _master_version(schema, master_tag)
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise TutorialArchiveError("Tutorial output already exists; choose a new directory")
    fetch = fetch or _download
    payloads, entries = {}, []
    for source in _SOURCES:
        raw = fetch(source["source_url"], MAX_RESPONSE_BYTES)
        _verify_source(raw, source)
        safe = sanitize_replay(schema, raw)
        filename = "tutorial-" + source["kind"] + ".pb"
        payloads[filename] = safe
        entries.append({"kind": source["kind"], "quest_id": "qt-tutorial-" + source["kind"],
            "file": filename, "bytes": len(safe), "sha256": hashlib.sha256(safe).hexdigest(),
            "source": {**{name: source[name] for name in (
                "source_url", "raw_bytes", "raw_sha256", "git_blob_sha1")}, "source_commit": SOURCE_COMMIT}})
    manifest = {"schema": 1, "schema_sha256": schema.fingerprint, "master_version": version,
        "source_repository": SOURCE_REPOSITORY, "source_commit": SOURCE_COMMIT, "fixed_demo": True,
        "sanitization": {"user_identity_removed": True, "detail_log_removed": True,
                         "detail_available": False, "common_response_empty": True}, "replays": entries}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".public-tutorial-") as temporary:
        stage = Path(temporary) / "archive"
        stage.mkdir()
        for name, payload in payloads.items():
            path = stage / name
            path.write_bytes(payload)
            path.chmod(0o600)
        path = stage / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
        stage.rename(output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor-set", type=Path, default=Path("data/protocol/idolypride-6.1.1.pb"))
    parser.add_argument("--master-tag", type=Path, default=Path("data/original-master/master-tag.json"))
    parser.add_argument("--output", type=Path, default=Path("data/public-tutorial"))
    args = parser.parse_args(argv)
    try:
        schema = Schema.from_descriptor_set(args.descriptor_set)
        manifest = archive_tutorial_replays(schema, args.master_tag, args.output)
    except (TutorialArchiveError, OSError, ValueError, DecodeError) as error:
        if isinstance(error, TutorialArchiveError):
            parser.exit(1, f"Tutorial replay archive failed: {error}\n")
        parser.exit(1, "Tutorial replay archive failed: supplied schema or local output is unavailable\n")
    print(json.dumps({"archived": len(manifest["replays"]), "fixed_demo": True,
                      "schema_sha256": manifest["schema_sha256"],
                      "master_version": manifest["master_version"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
