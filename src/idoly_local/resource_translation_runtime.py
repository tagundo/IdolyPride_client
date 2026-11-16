"""Select prepared resource data and advance the client's cached revision.

Language switches (including returning to Japanese) publish a newer complete
manifest, so cached SDK metadata cannot leave text from the previous language.
Only a small public-data fingerprint and revision are persisted, never a player.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import zlib
from zipfile import BadZipFile

from google.protobuf.message import DecodeError

from .octo_manifest import Database
from .resource_translation import load_resource_translation

_LOCK = threading.Lock()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate resource language revision field")
        result[key] = value
    return result


def _state(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 8192:
            raise ValueError("Invalid resource language revision state")
        raw = os.read(descriptor, 8193)
    finally:
        os.close(descriptor)
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    if (not isinstance(value, dict) or set(value) != {"schema", "fingerprint", "revision"}
            or type(value["schema"]) is not int or value["schema"] != 1 or type(value["revision"]) is not int
            or not 1 <= value["revision"] <= 2**31 - 1
            or not isinstance(value["fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["fingerprint"])):
        raise ValueError("Invalid resource language revision state")
    return value


def pin_manifest_revision(raw, state_path, *, language, preserve_original=False,
                          sdk_identity_compat=False):
    """Return (complete manifest, accepts older revisions), with atomic state."""
    if language not in ("ja", "ko", "en"):
        raise ValueError("Unknown resource language")
    if type(sdk_identity_compat) is not bool:
        raise ValueError("SDK identity compatibility must be a boolean")
    database = Database.FromString(raw)
    identity = hashlib.sha256()
    if sdk_identity_compat:
        # A cached revision from the old, overlong SDK object names must receive
        # a complete update once, even though the packaged resource bytes match.
        identity.update(b"octo-sdk-six-byte-object-name-v1\0")
    identity.update(language.encode("ascii"))
    identity.update(b"\0")
    identity.update(raw)
    fingerprint = identity.hexdigest()
    minimum_revision = database.revision + int(sdk_identity_compat)
    state_path = Path(state_path)
    with _LOCK:
        previous = _state(state_path)
        if previous is None and preserve_original and not sdk_identity_compat:
            return raw, False
        revision = (max(minimum_revision, previous["revision"])
                    if previous and previous["fingerprint"] == fingerprint
                    else max(minimum_revision, previous["revision"] + 1 if previous else minimum_revision))
        if revision > 2**31 - 1:
            raise ValueError("Resource language revision is exhausted")
        state = {"schema": 1, "fingerprint": fingerprint, "revision": revision}
        if state != previous:
            temporary = state_path.with_name("." + state_path.name + "." + secrets.token_hex(6))
            try:
                with temporary.open("xb") as target:
                    target.write(json.dumps(state, sort_keys=True, separators=(",", ":")).encode("ascii"))
                    target.flush(); os.fsync(target.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, state_path)
            finally:
                temporary.unlink(missing_ok=True)
        database.revision = revision
        # A complete snapshot sent in place of an unavailable historical delta
        # explicitly updates each existing row. IDs/hashes/dependencies stay
        # unchanged, so identical original bundles remain valid in the SDK cache.
        for rows in (database.assetBundleList, database.resourceList):
            for row in rows:
                if row.state != 4:
                    row.state = 2
        return database.SerializeToString(deterministic=True), True


def select_resource_translation(original, data_dir, cache_root, *, language, platform):
    if language not in ("ja", "ko", "en") or platform not in ("android", "ios"):
        raise ValueError("Unknown resource translation selection")
    layer = None
    if language != "ja":
        from .bundled_translations import resolve_translation_root
        directory = resolve_translation_root(cache_root, platform=platform) / language / platform
        if directory.exists():
            layer = load_resource_translation(directory, original, language=language,
                data_dir=data_dir, platform=platform)
    raw = original if layer is None else layer.manifest
    try:
        raw, compatible = pin_manifest_revision(raw,
            Path(data_dir) / ("client-resource-revision-" + platform + ".json"),
            language=language, preserve_original=layer is None,
            sdk_identity_compat=layer is not None)
        return raw, layer, compatible
    except BaseException:
        if layer is not None:
            layer.close()
        raise


def validate_prepared_translations(directory, data_dir, *, platform):
    """Check prepared language semantics before an installer switches pointers.

    Opening the compressed object index does not expand story scripts. Each
    language is closed before the next is prepared, keeping the startup peak
    bounded and preserving the prior selected package on any incompatibility.
    """
    from .octo_runtime import _platform_archive, load_octo_archive
    archive_name, _cache_name, _version, _revision = _platform_archive(platform)
    archived = load_octo_archive(Path(data_dir) / archive_name, platform=platform)
    if archived is None:
        raise ValueError("Core resource manifest is required before language preparation")
    _settings, original = archived
    results = {}
    for language in ("ko", "en"):
        selected = Path(directory) / language / platform
        if not selected.exists():
            continue
        try:
            layer = load_resource_translation(selected, original, language=language,
                data_dir=data_dir, platform=platform)
        except (DecodeError, BadZipFile, zlib.error, UnicodeError, RecursionError):
            raise ValueError("Prepared language resource format is invalid") from None
        try:
            results[language] = dict(layer.report["coverage"])
        finally:
            layer.close()
            # Do not retain this report/manifest while the next constructor
            # allocates its two complete parsed catalogs.
            del layer
    if not results:
        raise ValueError("Prepared package contains no compatible language resources")
    return results
