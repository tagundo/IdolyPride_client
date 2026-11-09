#!/usr/bin/env python3
"""Inspect PlayCover's PlayChain and optionally export one Firebase archive.

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
import sqlite3
import sys
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


def export_archive(bundle: str, output: Path, home: Path, google_app_id: str | None = None) -> None:
    settings_path, database_path = _paths(bundle, home)
    settings = _settings(settings_path)
    if settings is None or settings.get("playChain") is not True:
        raise ExportError("PlayChain is not already enabled for this app. " + _IN_PROCESS)
    if google_app_id is not None and not _GOOGLE_APP_ID.fullmatch(google_app_id):
        raise ExportError("Invalid iOS Google app identifier")
    try:
        with closing(_connect(database_path)) as database:
            _check_schema(database)
            query = ('SELECT "v_Data" FROM "genp" WHERE "acct" IN (?, ?) '
                     'AND substr("svce", 1, ?) = ?')
            parameters = [*ACCOUNTS, len(_SERVICE_PREFIX), _SERVICE_PREFIX]
            if google_app_id is not None:
                query += ' AND "svce" = ?'
                parameters.append(_SERVICE_PREFIX + google_app_id)
            rows = database.execute(query + " LIMIT 2", parameters).fetchall()
    except sqlite3.Error:
        raise ExportError("Cannot read the scoped Firebase archive from PlayChain") from None
    if not rows:
        raise ExportError("No recognized Firebase user archive matched. " + _IN_PROCESS)
    if len(rows) != 1:
        raise ExportError("Multiple Firebase archives matched; specify the IPA or Google app identifier")
    blob = rows[0][0]
    try:
        value = plistlib.loads(blob)
    except (ValueError, TypeError, plistlib.InvalidFileException):
        raise ExportError("Matched record is not a Firebase NSKeyedArchiver archive") from None
    if (not isinstance(blob, bytes) or not isinstance(value, dict)
            or value.get("$archiver") != "NSKeyedArchiver"
            or not isinstance(value.get("$objects"), list) or not isinstance(value.get("$top"), dict)):
        raise ExportError("Matched record is not a Firebase NSKeyedArchiver archive")
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
    parser.add_argument("--output", type=Path, help="New private file for one Firebase user archive")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--google-app-id", help="Public iOS GOOGLE_APP_ID to scope the Firebase service")
    scope.add_argument("--ipa", type=Path, help="Read public GOOGLE_APP_ID from this installed game's source IPA")
    args = parser.parse_args(argv)
    if args.output and not args.bundle:
        parser.error("--output requires an explicit --bundle")
    try:
        if args.output:
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
