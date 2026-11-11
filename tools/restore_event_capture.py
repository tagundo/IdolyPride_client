#!/usr/bin/env python3
"""Restore a private event archive into a NEW local profile, entirely offline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from idoly_local.dream_capture import build_dream_catalog, read_capture_directory
from idoly_local.profiles import import_profile
from idoly_local.pvp_capture import build_pvp_catalog
from idoly_local.schema import Schema
from idoly_local.state import State

_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SNAPSHOT = "user-get.pb"
_DREAM = "dream-private-catalog.json"
_PVP = "pvp-catalog.json"


class RestoreError(RuntimeError):
    """Only fixed reason codes leave this tool, never private source details."""
    def __init__(self, code):
        self.code = code
        super().__init__("Event restoration stopped: " + code)


def _need(condition, code):
    if not condition:
        raise RestoreError(code)


def _write_private(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _catalog_bytes(data, limit):
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    _need(len(raw) <= limit, "catalog_size_invalid")
    return raw


def _same_source(source, catalog):
    _need(catalog.get("source_manifest_sha256") == source.source_manifest_sha256
          and catalog.get("master_version") == source.master_version
          and catalog.get("captured_at_ms") == source.captured_at_ms
          and catalog.get("owner") == {"server_user_id": source.owner[0],
                                      "public_user_id": source.owner[1]}, "source_changed")


def _publish(staging, output):
    """Reserve a new directory and publish files without replacing any path."""
    created, linked = False, []
    try:
        # mkdir is exclusive even if a file/symlink appears after preflight.
        output.mkdir(mode=0o700)
        created = True
        output.chmod(0o700)
        for source in sorted(staging.iterdir()):
            _need(source.is_file() and not source.is_symlink(), "staging_invalid")
            target = output / source.name
            # Same parent/filesystem; link cannot overwrite existing files.
            os.link(source, target, follow_symlinks=False)
            linked.append(target)
    except Exception:
        for target in reversed(linked):
            target.unlink(missing_ok=True)
        if created:
            try:
                # Preserve unrelated files if another process added anything.
                output.rmdir()
            except OSError:
                pass
        raise RestoreError("output_publish_failed") from None


def _restore_capture(schema, capture_directory, output, *, event, profile="preserved"):
    """Validate first, then import final User.Get and selected private catalogs.

    The original archive is never modified. Catalog times and raw snapshot bytes
    remain unchanged. No sessions, fixtures, rewards or gameplay are imported.
    """
    _need(event in ("dream", "venus", "both"), "event_invalid")
    _need(type(profile) is str and _PROFILE.fullmatch(profile), "profile_invalid")
    output = Path(output).absolute()
    _need(not os.path.lexists(output), "output_exists")
    try:
        source = read_capture_directory(schema, capture_directory)
    except Exception:
        raise RestoreError("archive_invalid") from None
    # Keep staging and restored files outside the immutable source archive.
    _need(not output.resolve().is_relative_to(Path(capture_directory).resolve()),
          "output_must_be_separate")
    catalogs = {}
    if event in ("dream", "both"):
        try:
            data = build_dream_catalog(schema, capture_directory)
        except Exception:
            raise RestoreError("dream_catalog_unavailable") from None
        _same_source(source, data)
        catalogs[_DREAM] = _catalog_bytes(data, 64 * 1024 * 1024)
    if event in ("venus", "both"):
        try:
            data = build_pvp_catalog(schema, capture_directory)
        except Exception:
            raise RestoreError("venus_catalog_unavailable") from None
        _same_source(source, data)
        catalogs[_PVP] = _catalog_bytes(data, 32 * 1024 * 1024)
    staging = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = Path(tempfile.mkdtemp(prefix=".idoly-event-restore-", dir=output.parent))
        staging.chmod(0o700)
        raw = source.records[-1].response_raw
        _write_private(staging / _SNAPSHOT, raw)
        # Create the database privately before SQLite opens it or creates WAL.
        _write_private(staging / "state.db", b"")
        state = State(staging / "state.db")
        try:
            import_profile(state, schema, profile, staging / _SNAPSHOT)
            identity = state.profile(profile)
            _need(identity is not None and (identity["server_id"], identity["public_id"]) == source.owner,
                  "snapshot_identity_mismatch")
            _need(state.snapshot(profile) == (raw, schema.fingerprint), "snapshot_identity_mismatch")
            with state.connect() as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            raise RestoreError("snapshot_import_failed") from None
        _need(not (staging / "state.db-wal").exists() and not (staging / "state.db-shm").exists(),
              "snapshot_import_failed")
        for name, raw_catalog in catalogs.items():
            _write_private(staging / name, raw_catalog)
        manifest = {"schema": 1, "event": event, "profile": profile,
            "schema_sha256": schema.fingerprint, "master_version": source.master_version,
            "source_manifest_sha256": source.source_manifest_sha256,
            "original_captured_at_ms": source.captured_at_ms,
            "snapshot": _SNAPSHOT, "state": "state.db", "catalogs": sorted(catalogs),
            "credentials_imported": False, "sessions_imported": False}
        _write_private(staging / "restore-manifest.json", _catalog_bytes(manifest, 65536))
        for path in staging.iterdir():
            path.chmod(0o600)
        _publish(staging, output)
        return {"status": "restored", "output": str(output.resolve()), "event": event,
                "snapshot_saved": True, "dream_catalog": _DREAM in catalogs,
                "pvp_catalog": _PVP in catalogs, "credentials_imported": False}
    except RestoreError:
        raise
    except Exception:
        raise RestoreError("local_restoration_failed") from None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def restore_capture(schema, capture_directory, output, *, event, profile="preserved"):
    """Public fixed-error boundary, including local path/preflight failures."""
    try:
        return _restore_capture(schema, capture_directory, output, event=event, profile=profile)
    except RestoreError:
        raise
    except Exception:
        raise RestoreError("local_restoration_failed") from None


def _serve_command(output, event, profile, descriptor):
    output = Path(output).resolve()
    command = ["python3", "-m", "idoly_local", "--descriptor-set", str(Path(descriptor).resolve()),
        "serve", "--state", str(output / "state.db"), "--profile", profile,
        "--fixtures", str(output / "empty-fixtures"), "--master-dir", "<matching-master-json>"]
    if event in ("dream", "both"):
        command.extend(("--dream-catalog", str(output / _DREAM)))
    if event in ("venus", "both"):
        command.extend(("--pvp-catalog", str(output / _PVP)))
    return shlex.join(command)


def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise RestoreError("arguments_invalid")
    parser = Parser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="Private collector archive directory")
    parser.add_argument("--event", choices=("dream", "venus", "both"), required=True)
    parser.add_argument("--output", type=Path, required=True, help="NEW private restoration directory")
    parser.add_argument("--profile", default="preserved")
    parser.add_argument("--descriptor-set", type=Path, default=_ROOT / "data/protocol/idolypride-6.1.1.pb")
    try:
        args = parser.parse_args(argv)
        schema = Schema.from_descriptor_set(args.descriptor_set)
        result = restore_capture(schema, args.archive, args.output, event=args.event, profile=args.profile)
        result["serve_command"] = _serve_command(args.output, args.event, args.profile, args.descriptor_set)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except RestoreError as error:
        print(json.dumps({"status": "failed", "code": error.code}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "local_restoration_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
