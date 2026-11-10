#!/usr/bin/env python3
"""Reuse the exact released public data for the v0.3.1 code-only patch.

No archive generation or user-state copying is performed. The CLI pins the
existing asset's bytes, verifies every declared public member, then uses the
same public-path installer as the Mac app to prepare the CI references.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
from zipfile import ZipFile


SOURCE_RELEASE = "local-server-v0.3.0"
SOURCE_ASSET_ID = 732944285
PINNED_BYTES = 80929314
PINNED_SHA256 = "3139ea69af1305a231ca09a3caab88a4496f1663c7a3af30892c588ed2cbc436"

_SPEC = importlib.util.spec_from_file_location(
    "fixed_patch_public_paths", Path(__file__).resolve().parents[1] / "macos-server/payload.py")
_PATHS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PATHS)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(source, output, workspace):
    source, output, workspace = Path(source), Path(output), Path(workspace).resolve()
    if source.stat().st_size != PINNED_BYTES or digest(source) != PINNED_SHA256:
        raise ValueError("Fixed patch data does not match the released asset pin")
    data = workspace / "data"
    if not data.resolve().is_relative_to(workspace):
        raise ValueError("The CI data folder is outside the workspace")
    with ZipFile(source) as archive:
        entries = {}
        for info in archive.infolist():
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Fixed patch data has a directory or symbolic-link member")
            relative = _PATHS.member_path(info.filename)
            if info.filename in entries:
                raise ValueError("Fixed patch data has duplicate members")
            target = data / relative
            if not target.resolve().is_relative_to(data.resolve()):
                raise ValueError("Fixed patch data would escape its public destination")
            entries[info.filename] = info
        manifest = json.loads(archive.read("data/payload-manifest.json"))
        if manifest.get("schema") != 1 or len(manifest.get("tables", {})) != 40 or "Mission" not in manifest["tables"]:
            raise ValueError("Fixed patch data does not contain the verified 40-table catalog")
        records = manifest.get("files")
        if not isinstance(records, list):
            raise ValueError("Fixed patch data has no file manifest")
        declared = {row["path"] for row in records}
        if len(declared) != len(records) or set(entries) != declared | {"data/payload-manifest.json"}:
            raise ValueError("Fixed patch manifest does not cover exactly the archive")
        for row in records:
            raw = archive.read(row["path"])
            if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError("Fixed patch public member failed its manifest hash")
        pack_count = sum(name.startswith("data/original-master/assets/master/") for name in entries)
        if pack_count != 202:
            raise ValueError("Fixed patch data does not preserve all 202 original packs")
        for name in entries:
            target = workspace / name
            if target.exists() and (not target.is_file() or target.read_bytes() != archive.read(name)):
                raise ValueError("An existing CI reference differs from the pinned public data")
    if output.exists() and (not output.is_file() or digest(output) != PINNED_SHA256):
        raise ValueError("The output payload is not the pinned data")
    # Validation finishes before any extraction or output mutation.
    installed = _PATHS.install_payload(source, data)
    output.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != output.resolve():
        shutil.copyfile(source, output)
    if digest(output) != PINNED_SHA256:
        raise ValueError("Fixed patch output changed during preparation")
    return {
        "schema": 1, "reused_released_payload": True,
        "source_release": SOURCE_RELEASE, "source_asset_id": SOURCE_ASSET_ID,
        "payload_bytes": PINNED_BYTES, "payload_sha256": PINNED_SHA256,
        "file_count": len(entries), "master_table_count": 40,
        "original_master_pack_count": pack_count,
        "every_manifest_member_verified": True,
        "payload_rebuilt": False, "private_state_copied": False,
        "public_references": installed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source, args.output, args.workspace)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
