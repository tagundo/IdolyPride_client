"""A code-only native patch must reuse public data without touching user state."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
from zipfile import ZipFile, ZipInfo

import pytest


SPEC = importlib.util.spec_from_file_location(
    "prepare_fixed_patch_payload", Path(__file__).resolve().parents[1] / "tools/prepare_fixed_patch_payload.py")
payload = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(payload)


def public_members():
    members = {
        "data/protocol/idolypride-6.1.1.pb": b"synthetic descriptor",
        "data/original-master/master-tag.json": b'{"tag":"synthetic"}',
        "data/master-json/!version.txt": b"synthetic version",
    }
    tables = ["Mission", *(f"Table{index}" for index in range(39))]
    members.update({f"data/master-json/{name}.json": b"[]" for name in tables})
    members.update({f"data/original-master/assets/master/{index:064x}": bytes([index % 256])
                    for index in range(202)})
    manifest = {"schema": 1, "tables": dict.fromkeys(tables, "synthetic"), "files": [
        {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for name, raw in members.items()]}
    members["data/payload-manifest.json"] = json.dumps(manifest).encode()
    return members


def write_archive(path, members, *, duplicate=None, symlink=None):
    with ZipFile(path, "w") as archive:
        for name, raw in members.items():
            if name == symlink:
                entry = ZipInfo(name)
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(entry, raw)
            else:
                archive.writestr(name, raw)
        if duplicate:
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(duplicate, members[duplicate])


def pin_synthetic(monkeypatch, path):
    monkeypatch.setattr(payload, "PINNED_BYTES", path.stat().st_size)
    monkeypatch.setattr(payload, "PINNED_SHA256", payload.digest(path))


def test_reuse_preserves_exact_archive_and_unrelated_user_state(tmp_path, monkeypatch):
    members = public_members()
    source, output, workspace = tmp_path / "released.zip", tmp_path / "patch.zip", tmp_path / "workspace"
    write_archive(source, members)
    pin_synthetic(monkeypatch, source)
    data = workspace / "data"
    (data / "protocol").mkdir(parents=True)
    (data / "protocol/idolypride-6.1.1.pb").write_bytes(members["data/protocol/idolypride-6.1.1.pb"])
    (data / "state.db").write_bytes(b"unrelated synthetic user progress")
    report = payload.prepare(source, output, workspace)
    assert output.read_bytes() == source.read_bytes()
    assert (data / "state.db").read_bytes() == b"unrelated synthetic user progress"
    for name, raw in members.items():
        assert (workspace / name).read_bytes() == raw
    assert report["payload_rebuilt"] is False and report["private_state_copied"] is False
    assert report["master_table_count"] == 40 and report["original_master_pack_count"] == 202
    assert report["public_references"]["preserved"] == 1
    assert payload.prepare(source, output, workspace)["public_references"]["copied"] == 0


def test_wrong_released_pin_is_rejected_before_any_output(tmp_path):
    source = tmp_path / "different.zip"
    write_archive(source, public_members())
    with pytest.raises(ValueError, match="released asset pin"):
        payload.prepare(source, tmp_path / "out.zip", tmp_path / "workspace")
    assert not (tmp_path / "workspace").exists() and not (tmp_path / "out.zip").exists()


@pytest.mark.parametrize("problem", ("duplicate", "private", "traversal", "symlink", "unlisted", "member_hash", "missing_pack"))
def test_unsafe_or_incomplete_manifest_is_rejected_without_extraction(tmp_path, monkeypatch, problem):
    source, output, workspace = tmp_path / "input.zip", tmp_path / "out.zip", tmp_path / "workspace"
    members = public_members()
    duplicate = symlink = None
    if problem == "duplicate":
        duplicate = "data/protocol/idolypride-6.1.1.pb"
    elif problem == "private":
        members["data/state.db"] = b"must not install"
    elif problem == "traversal":
        members["data/master-json/../../outside"] = b"must not install"
    elif problem == "symlink":
        symlink = "data/protocol/idolypride-6.1.1.pb"
    elif problem == "unlisted":
        members["data/master-json/Extra.json"] = b"[]"
    elif problem == "member_hash":
        members["data/protocol/idolypride-6.1.1.pb"] += b"changed"
    else:
        name = next(name for name in members if "/assets/master/" in name)
        del members[name]
        manifest = json.loads(members["data/payload-manifest.json"])
        manifest["files"] = [row for row in manifest["files"] if row["path"] != name]
        members["data/payload-manifest.json"] = json.dumps(manifest).encode()
    write_archive(source, members, duplicate=duplicate, symlink=symlink)
    pin_synthetic(monkeypatch, source)
    with pytest.raises(ValueError):
        payload.prepare(source, output, workspace)
    assert not workspace.exists() and not output.exists()


@pytest.mark.parametrize("conflict", ("public_file", "output_file", "data_symlink"))
def test_existing_unrelated_files_and_outside_destinations_are_not_overwritten(tmp_path, monkeypatch, conflict):
    source, output, workspace = tmp_path / "input.zip", tmp_path / "out.zip", tmp_path / "workspace"
    write_archive(source, public_members())
    pin_synthetic(monkeypatch, source)
    protected = None
    if conflict == "public_file":
        protected = workspace / "data/protocol/idolypride-6.1.1.pb"
        protected.parent.mkdir(parents=True)
        protected.write_bytes(b"existing unrelated data")
    elif conflict == "output_file":
        protected = output
        protected.write_bytes(b"existing unrelated archive")
    else:
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (workspace / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        payload.prepare(source, output, workspace)
    if protected:
        assert protected.read_bytes().startswith(b"existing unrelated")
    else:
        assert not list(outside.iterdir())
