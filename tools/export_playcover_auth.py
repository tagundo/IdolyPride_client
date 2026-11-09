#!/usr/bin/env python3
"""Inspect PlayCover's PlayChain and optionally back up scoped Firebase archives.

Local files only; no network, native Keychain access, flag changes or token output.
Storage layout follows PlayTools fbc88801b63c791e4ef597a2746676c69864ccc6,
PlayedAppleDB.swift. Firebase account names follow firebase-ios-sdk 11.14.0.
The archive is not the game's current x-auth-token request metadata.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import sys
import tempfile
from zipfile import BadZipFile, ZipFile


BUNDLES = ("game.qualiarts.idolypride", "game.qualiarts.idolypride.kr")
ACCOUNTS = (
    "firebase_auth_1___FIRAPP_DEFAULT_firebase_user",
    "firebase_auth_firebase_user",
)
_SERVICE_PREFIX = "firebase_auth_"
_GOOGLE_APP_ID = re.compile(r"[0-9]+:[0-9]+:ios:[a-fA-F0-9]+\Z")
_COLUMNS = {"agrp", "acct", "svce", "v_Data"}
_IN_PROCESS = "An in-process export is required; keep PlayChain and its debugging setting unchanged."


class ExportError(ValueError):
    """A fixed, credential-free message suitable for local CLI output."""


def _paths(bundle: str, home: Path) -> tuple[Path, Path]:
    if bundle not in BUNDLES:
        raise ExportError("Unsupported bundle identifier")
    root = home / "Library/Containers/io.playcover.PlayCover"
    return root / "App Settings" / f"{bundle}.plist", root / "PlayChain" / f"{bundle}.db"


def _settings(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        raise ExportError("Cannot read this app's PlayCover settings") from None
    if not isinstance(value, dict):
        raise ExportError("Unrecognized PlayCover settings format")
    return value


def _connect(path: Path):
    if not path.is_file():
        raise ExportError("PlayChain database is absent. " + _IN_PROCESS)
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error:
        raise ExportError("Cannot open PlayChain database read-only") from None


def _check_schema(database) -> None:
    columns = {row[1] for row in database.execute('PRAGMA table_info("genp")')}
    if not _COLUMNS.issubset(columns):
        raise ExportError("Unrecognized PlayChain schema; no data was exported")


def inspect_bundle(bundle: str, home: Path) -> dict:
    settings_path, database_path = _paths(bundle, home)
    result = {"bundle": bundle, "settings_present": settings_path.is_file(),
              "playchain": None, "debugging": None, "database_present": database_path.is_file(),
              "schema": "absent"}
    try:
        settings = _settings(settings_path)
        if settings is not None:
            result["playchain"] = settings.get("playChain") if type(settings.get("playChain")) is bool else None
            result["debugging"] = settings.get("playChainDebugging") if type(settings.get("playChainDebugging")) is bool else None
        if database_path.is_file():
            with closing(_connect(database_path)) as database:
                _check_schema(database)
            result["schema"] = "recognized"
    except (ExportError, sqlite3.Error):
        result["schema"] = "unrecognized"
    return result


def google_app_id_from_ipa(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith("/GoogleService-Info.plist")]
            values = {plistlib.loads(archive.read(name)).get("GOOGLE_APP_ID") for name in names}
    except (OSError, BadZipFile, ValueError, TypeError, AttributeError, plistlib.InvalidFileException):
        raise ExportError("Cannot read public GoogleService-Info from the IPA") from None
    if len(values) != 1:
        raise ExportError("IPA has missing or ambiguous Google app identifiers")
    value = values.pop()
    if not isinstance(value, str) or not _GOOGLE_APP_ID.fullmatch(value):
        raise ExportError("IPA has an invalid iOS Google app identifier")
    return value


def _archive_rows(database_path: Path, google_app_id: str | None) -> list[tuple]:
    if google_app_id is not None and not _GOOGLE_APP_ID.fullmatch(google_app_id):
        raise ExportError("Invalid iOS Google app identifier")
    try:
        with closing(_connect(database_path)) as database:
            _check_schema(database)
            query = ('SELECT "agrp", "acct", "v_Data" FROM "genp" WHERE "acct" IN (?, ?) '
                     'AND substr("svce", 1, ?) = ?')
            parameters = [*ACCOUNTS, len(_SERVICE_PREFIX), _SERVICE_PREFIX]
            if google_app_id is not None:
                query += ' AND "svce" = ?'
                parameters.append(_SERVICE_PREFIX + google_app_id)
            return database.execute(query + ' ORDER BY "agrp", "acct"', parameters).fetchall()
    except sqlite3.Error:
        raise ExportError("Cannot read the scoped Firebase archive from PlayChain") from None


def diagnose_archives(bundle: str, home: Path, google_app_id: str | None = None) -> dict:
    """Return counts only; opaque groups and archives are never returned."""
    _, database_path = _paths(bundle, home)
    rows = _archive_rows(database_path, google_app_id)
    groups = {}
    for group, account, blob in rows:
        groups.setdefault(group, []).append((account, blob))

    def counts(records):
        return {"matched_rows": len(records), "distinct_archive_count": len({blob for _, blob in records}),
                "counts_by_account_kind": {
                    "default": sum(account == ACCOUNTS[0] for account, _ in records),
                    "shared": sum(account == ACCOUNTS[1] for account, _ in records)}}

    result = counts([(account, blob) for _, account, blob in rows])
    result["groups"] = [{"group_number": number, **counts(records)}
                        for number, records in enumerate(groups.values(), start=1)]
    return result


def _export_rows(bundle: str, home: Path, google_app_id: str | None) -> list[tuple]:
    settings_path, database_path = _paths(bundle, home)
    settings = _settings(settings_path)
    if settings is None or settings.get("playChain") is not True:
        raise ExportError("PlayChain is not already enabled for this app. " + _IN_PROCESS)
    rows = _archive_rows(database_path, google_app_id)
    if not rows:
        raise ExportError("No recognized Firebase user archive matched. " + _IN_PROCESS)
    return rows


def _validate_archive(blob: bytes) -> None:
    try:
        value = plistlib.loads(blob)
    except (ValueError, TypeError, plistlib.InvalidFileException):
        raise ExportError("Matched record is not a Firebase NSKeyedArchiver archive") from None
    if (not isinstance(blob, bytes) or not isinstance(value, dict)
            or value.get("$archiver") != "NSKeyedArchiver"
            or not isinstance(value.get("$objects"), list) or not isinstance(value.get("$top"), dict)):
        raise ExportError("Matched record is not a Firebase NSKeyedArchiver archive")


def _write_private(path: Path, contents: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(contents)


def export_archives(bundle: str, output_dir: Path, home: Path,
                    google_app_id: str | None = None) -> dict:
    """Back up every distinct scoped archive; never infer an active account.

    Validate all records before writing. Only a fully populated staging directory
    is published; the requested destination must not already exist.
    """
    output_dir = Path(output_dir)
    if os.path.lexists(output_dir):
        raise ExportError("Output directory already exists; choose a new private directory")
    rows = _export_rows(bundle, home, google_app_id)
    archives = list(dict.fromkeys(row[2] for row in rows))
    for blob in archives:
        _validate_archive(blob)
    manifest = {"matched_rows": len(rows), "distinct_archive_count": len(archives),
                "files": [f"{index:03d}.archive" for index in range(1, len(archives) + 1)]}
    staging = None
    try:
        output_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = Path(tempfile.mkdtemp(dir=output_dir.parent, prefix=".firebase-archives-"))
        staging.chmod(0o700)
        for filename, blob in zip(manifest["files"], archives):
            _write_private(staging / filename, blob)
        _write_private(staging / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        if os.path.lexists(output_dir):
            raise ExportError("Output directory already exists; choose a new private directory")
        staging.rename(output_dir)
        staging = None
    except OSError:
        raise ExportError("Cannot save the private Firebase archive backup") from None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    return {"matched_rows": len(rows), "distinct_archive_count": len(archives),
            "saved_archives": len(archives)}


def export_archive(bundle: str, output: Path, home: Path, google_app_id: str | None = None) -> None:
    rows = _export_rows(bundle, home, google_app_id)
    # Repeated PlayChain rows may contain exactly the same opaque archive.
    # Exporting those identical bytes requires no guess about an active group.
    archives = {row[2] for row in rows}
    if len(archives) != 1:
        raise ExportError("Multiple distinct Firebase archives matched; specify --ipa or --google-app-id. "
                          "If already scoped, run --bundle <installed-bundle> "
                          "--google-app-id <public-app-id> --diagnose for redacted counts. "
                          "Use --output-dir to back up all scoped archives without selecting an active account.")
    blob = archives.pop()
    _validate_archive(blob)
    try:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ExportError("Output already exists; choose a new private archive filename") from None
    except OSError:
        raise ExportError("Cannot create a private archive output file") from None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(blob)
    except OSError:
        output.unlink(missing_ok=True)
        raise ExportError("Cannot save the private archive output file") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", choices=BUNDLES, help="Exact installed game bundle identifier")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--output", type=Path, help="New private file for one distinct Firebase user archive")
    action.add_argument("--output-dir", type=Path, help="New private directory backing up every distinct scoped archive")
    action.add_argument("--diagnose", action="store_true", help="Print only scoped archive, account-kind and numbered-group counts")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--google-app-id", help="Public iOS GOOGLE_APP_ID to scope the Firebase service")
    scope.add_argument("--ipa", type=Path, help="Read public GOOGLE_APP_ID from this installed game's source IPA")
    args = parser.parse_args(argv)
    if (args.output or args.output_dir or args.diagnose) and not args.bundle:
        parser.error("--output, --output-dir and --diagnose require an explicit --bundle")
    try:
        if args.diagnose:
            app_id = google_app_id_from_ipa(args.ipa) if args.ipa else args.google_app_id
            print(json.dumps(diagnose_archives(args.bundle, Path.home(), app_id), indent=2))
        elif args.output_dir:
            app_id = google_app_id_from_ipa(args.ipa) if args.ipa else args.google_app_id
            print(json.dumps(export_archives(args.bundle, args.output_dir, Path.home(), app_id), indent=2))
        elif args.output:
            app_id = google_app_id_from_ipa(args.ipa) if args.ipa else args.google_app_id
            export_archive(args.bundle, args.output, Path.home(), app_id)
            print("Exported one Firebase user archive with mode 0600; no token values were printed.")
            print("This archive is not game-session metadata; do not upload it to chat.")
        else:
            bundles = (args.bundle,) if args.bundle else BUNDLES
            print(json.dumps([inspect_bundle(bundle, Path.home()) for bundle in bundles], indent=2))
    except ExportError as error:
        print(f"Export blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
