#!/usr/bin/env python3
"""Extract the completed-opening fixture inputs from the exact app under test.

The MV QA driver's QA-only --prepare-completed-opening reuses qa_game_boot's
profile fixture, which needs the server's protocol descriptor set and master
tables on the host. They are taken from the unified APK's own embedded
assets/ServerData.zip, the payload its embedded server runs on. The payload and
every extracted member must match the tracked Korean server-data pin before the
inputs are usable. Standard library only; no network and no game input. This is
setup for a disposable profile, never gameplay evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APK_MEMBER = "assets/ServerData.zip"
PROTOCOL = "data/protocol/idolypride-6.1.1.pb"
MASTER_PREFIX = "data/master-json/"
# The tutorial continuation reads these; Mission.json backs its mission-delta check.
REQUIRED_TABLES = ("Setting.json", "CardLevel.json", "Message.json", "Mission.json")
NAME = re.compile(r"[A-Za-z0-9_!][A-Za-z0-9_.!-]{0,127}")
HEX64 = re.compile(r"[0-9a-f]{64}")
CHUNK = 1024 * 1024
MAX_PAYLOAD = 1024 * 1024 * 1024


class FixtureInputError(ValueError):
    pass


def need(value, code):
    if not value:
        raise FixtureInputError(code)


def load_output_pin():
    """The tracked, self-verifying pin of the Korean ServerData payload."""
    spec = importlib.util.spec_from_file_location("actual_mv_korean_server_data_pin",
                                                  ROOT / "tools/korean_server_data_pin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_pin()["output"]


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pinned_rows(pin):
    need(type(pin) is dict and type(pin.get("bytes")) is int and 0 < pin["bytes"] <= MAX_PAYLOAD
         and type(pin.get("sha256")) is str and HEX64.fullmatch(pin["sha256"])
         and type(pin.get("members")) is list, "server_data_pin_invalid")
    rows = {}
    for row in pin["members"]:
        need(type(row) is dict and type(row.get("path")) is str and type(row.get("bytes")) is int
             and 0 <= row["bytes"] <= MAX_PAYLOAD and type(row.get("sha256")) is str
             and HEX64.fullmatch(row["sha256"]) and row["path"] not in rows, "server_data_pin_invalid")
        rows[row["path"]] = row
    wanted = sorted(path for path in rows if path == PROTOCOL or path.startswith(MASTER_PREFIX))
    need(PROTOCOL in rows and all(MASTER_PREFIX + name in rows for name in REQUIRED_TABLES),
         "fixture_inputs_not_pinned")
    for path in wanted:
        # One flat file per pinned name; nothing can leave the output directory.
        parts = PurePosixPath(path)
        need("\\" not in path and str(parts.parent) in ("data/protocol", "data/master-json")
             and NAME.fullmatch(parts.name) and parts.name not in (".", ".."), "fixture_input_path_unsafe")
    return rows, wanted


def single(archive, name, code):
    rows = [info for info in archive.infolist() if info.filename == name]
    need(len(rows) == 1, code)
    kind = stat.S_IFMT(rows[0].external_attr >> 16)
    need(not rows[0].is_dir() and kind in (0, stat.S_IFREG), code)
    return rows[0]


def copy_checked(archive, info, target, size, digest, code):
    need(info.file_size == size, code)
    hasher, total = hashlib.sha256(), 0
    with archive.open(info) as source, target.open("xb") as output:
        while chunk := source.read(CHUNK):
            total += len(chunk)
            need(total <= size, code)
            hasher.update(chunk)
            output.write(chunk)
    need(total == size and hasher.hexdigest() == digest, code)


def extract(apk, output, *, pin=None):
    """Write output/protocol/<descriptor set> and output/master-json/*; return a receipt."""
    pin = load_output_pin() if pin is None else pin
    rows, wanted = pinned_rows(pin)
    apk, output = Path(apk), Path(output)
    need(apk.is_file(), "unified_apk_unavailable")
    need(not output.exists() or (output.is_dir() and not output.is_symlink() and not any(output.iterdir())),
         "fixture_output_not_empty")
    output.mkdir(parents=True, exist_ok=True)
    try:
        files = []
        with tempfile.TemporaryDirectory(prefix=".server-data-", dir=output.parent) as scratch:
            payload = Path(scratch) / "ServerData.zip"
            with zipfile.ZipFile(apk) as archive:
                info = single(archive, APK_MEMBER, "server_data_member_unavailable")
                copy_checked(archive, info, payload, pin["bytes"], pin["sha256"], "server_data_differs_from_pin")
            with zipfile.ZipFile(payload) as data:
                present = sorted(info.filename for info in data.infolist() if not info.is_dir()
                                 and (info.filename == PROTOCOL or info.filename.startswith(MASTER_PREFIX)))
                need(present == wanted, "fixture_input_inventory_differs")
                for path in wanted:
                    row = rows[path]
                    folder = output / ("protocol" if path == PROTOCOL else "master-json")
                    folder.mkdir(exist_ok=True)
                    target = folder / PurePosixPath(path).name
                    copy_checked(data, single(data, path, "fixture_input_member_invalid"), target,
                                 row["bytes"], row["sha256"], "fixture_input_differs_from_pin")
                    files.append({"path": target.relative_to(output).as_posix(), "member": path,
                                  "bytes": row["bytes"], "sha256": row["sha256"]})
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return {"schema": 1, "qa_only": True, "purpose": "completed_opening_profile_fixture_setup",
            "gameplay_evidence": False,
            "source_apk": {"name": apk.name, "bytes": apk.stat().st_size, "sha256": sha(apk)},
            "server_data": {"member": APK_MEMBER, "bytes": pin["bytes"], "sha256": pin["sha256"],
                            "pin": "data/korean-master-data-pin.json output"},
            "descriptor_set": "protocol/" + PurePosixPath(PROTOCOL).name, "master_dir": "master-json",
            "master_files": sum(1 for row in files if row["path"].startswith("master-json/")),
            "files": files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True, help="the unified APK under test")
    parser.add_argument("--output", type=Path, required=True, help="new or empty fixture input directory")
    parser.add_argument("--receipt", type=Path, required=True, help="JSON receipt of every extracted file")
    args = parser.parse_args(argv)
    try:
        receipt = extract(args.apk, args.output)
    except (FixtureInputError, OSError, zipfile.BadZipFile) as error:
        code = str(error) if isinstance(error, FixtureInputError) else type(error).__name__
        print("fixture inputs rejected: " + code, file=sys.stderr)
        return 1
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: receipt[key] for key in ("server_data", "descriptor_set", "master_dir", "master_files")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
