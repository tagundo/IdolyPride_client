"""Small synthetic cohort/owned-state fixtures; no downloaded assets or real account.

The native release gates separately verify the actual pinned 64-table cohort.
"""
import hashlib
import json
import os
import select
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from zipfile import ZipFile, ZipInfo, ZipInfo

import pytest
from idoly_local import public_payload as public
from idoly_local import public_payload_transaction as tx

VERSION = "6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11"
TABLES = ("profiles", "snapshots", "profile_settings", "starter_profiles", "profile_lesson_progress",
          "preference_receipts", "main_live_attempts", "profile_love_progress")


def make_payload(path, *, generation="new", damage=None):
    files = {"data/protocol/idolypride-6.1.1.pb": b"synthetic protocol",
        "data/original-master/master-tag.json": json.dumps({"generation": generation}).encode(),
        "data/love-compatibility.json": b"{}", "data/love-legacy-rules.json": b"{}",
        "data/latest-semantic-controls.json": b"{}",
        "data/public-octo/legacy-manifest.pb": b"synthetic original Android catalog",
        "data/public-octo-ios/legacy-manifest.pb": b"synthetic original iOS catalog"}
    files.update({"data/master-json/"+name+".json": json.dumps({"generation": generation}).encode()
                  for name in tx.TABLES})
    files.update({"data/original-master/assets/master/"+str(index).zfill(32)+"-Synthetic.db":
                  (generation+" public pack "+str(index)).encode() for index in range(202)})
    manifest = {"schema": 1, "master_version": VERSION, "source_overlay": {
        "operation": tx.POLICY, "derivation": "complete-public-member-replacement", "master_version": VERSION},
        "files": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                  for name, raw in sorted(files.items())]}
    if damage is not None:
        damage(files, manifest)
    files[tx.MANIFEST] = json.dumps(manifest, sort_keys=True).encode()
    with ZipFile(path, "w") as archive:
        for name, raw in sorted(files.items()):
            archive.writestr(name, raw)
    return {"expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "expected_bytes": path.stat().st_size}, files


def seed_owned(data):
    data.mkdir(parents=True, exist_ok=True)
    for database in ("state.db", "media-state.db"):
        with sqlite3.connect(data/database) as connection:
            for table in TABLES:
                connection.execute("CREATE TABLE "+table+" (profile TEXT, response BLOB)")
                connection.execute("INSERT INTO "+table+" VALUES (?,?)", ("existing", b' { "unknown": [1, 2] } \n'+table.encode()))
    names = ("account-management/selection.json", "client-language.json", "server-events.json",
             "profiles/custom/keep.bin", "resource-cache/existing.bin", "master-json/CustomExtra.json",
             "original-master/assets/master/unlisted-existing.db")
    for name in names:
        path = data/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(("keep:"+name).encode())
    return {name: (data/name).read_bytes() for name in (*names, "state.db", "media-state.db")}


def assert_owned(data, before):
    assert {name: (data/name).read_bytes() for name in before} == before


def test_latest_cohort_replaces_existing_public_files_and_preserves_all_owned_raw_bytes(tmp_path):
    archive = tmp_path/"latest.zip"; pin, files = make_payload(archive)
    data = tmp_path/"data"; before = seed_owned(data)
    previous = {}
    for name in ("data/master-json/Card.json", "data/original-master/master-tag.json"):
        target = data/name.removeprefix("data/"); target.parent.mkdir(parents=True, exist_ok=True)
        previous[name] = b"old public bytes"; target.write_bytes(previous[name])
    result = public.install_payload(archive, data, **pin)
    assert result == {"copied": len(files), "preserved": 0}
    assert all((data/name.removeprefix("data/")).read_bytes() == raw for name, raw in files.items())
    assert_owned(data, before)
    backup = next((data/tx.BACKUPS).iterdir())
    assert all((backup/"originals"/name.removeprefix("data/")).read_bytes() == raw for name, raw in previous.items())
    assert not (data/tx.PENDING).exists()
    with public.acquire_payload_read_lease(data):
        assert public.install_payload(archive, data, **pin) == {"copied": 0, "preserved": len(files)}
    assert_owned(data, before)


@pytest.mark.parametrize("damage", ["missing-pin", "partial-pin", "wrong-sha", "wrong-size", "boolean-size"])
def test_latest_policy_requires_complete_native_pin_before_creating_destination(tmp_path, damage):
    archive = tmp_path/"latest.zip"; pin, _ = make_payload(archive)
    if damage == "missing-pin": pin = {}
    elif damage == "partial-pin": pin.pop("expected_bytes")
    elif damage == "wrong-sha": pin["expected_sha256"] = "0"*64
    elif damage == "wrong-size": pin["expected_bytes"] += 1
    else: pin["expected_bytes"] = True
    data = tmp_path/"data"
    with pytest.raises(ValueError, match="public_payload_pin"):
        public.install_payload(archive, data, **pin)
    assert not data.exists()


@pytest.mark.parametrize("damage", ["duplicate-row", "unsorted", "private", "alias", "self", "missing", "extra", "bool-bytes", "bad-sha", "unknown-policy", "wrong-tables"])
def test_pinned_manifest_still_rejects_unsafe_or_incoherent_inner_cohort(tmp_path, damage):
    def change(files, manifest):
        rows = manifest["files"]
        if damage == "duplicate-row": rows.append(dict(rows[0]))
        elif damage == "unsorted": rows.reverse()
        elif damage in ("private", "alias"):
            rows[0]["path"] = "data/state.db" if damage == "private" else "data//love-compatibility.json"
        elif damage == "self": rows.append({"path": tx.MANIFEST, "bytes": 0, "sha256": "0"*64})
        elif damage == "missing": files.pop(rows[0]["path"])
        elif damage == "extra": files["data/love-reference-extra.json"] = b"unlisted"
        elif damage == "bool-bytes": rows[0]["bytes"] = True
        elif damage == "bad-sha": rows[0]["sha256"] = "not-a-digest"
        elif damage == "unknown-policy": manifest["source_overlay"]["operation"] = "unknown-overlay"
        else:
            rows[:] = [row for row in rows if row["path"] != "data/master-json/CardImage.json"]
            files.pop("data/master-json/CardImage.json")
    archive = tmp_path/"bad.zip"; pin, _ = make_payload(archive, damage=change)
    data = tmp_path/"data"; before = seed_owned(data)
    with pytest.raises(ValueError): public.install_payload(archive, data, **pin)
    assert_owned(data, before)
    assert not (data/tx.STATE).exists() and not (data/tx.PENDING).exists()


@pytest.mark.parametrize("fault", ["member", "marker"])
def test_interrupted_commit_blocks_runtime_readers_then_recovers_using_same_exact_source(tmp_path, monkeypatch, fault):
    archive = tmp_path/"latest.zip"; pin, files = make_payload(archive)
    data = tmp_path/"data"; before = seed_owned(data)
    old = data/"master-json/Card.json"; old.write_bytes(b"old card bytes")
    replace = tx.os.replace
    class Interrupted(BaseException): pass
    def interrupt(source, target):
        replace(source, target)
        if ((fault == "member" and Path(target) == old and "staged" in Path(source).parts)
                or (fault == "marker" and Path(target) == data/tx.STATE)):
            raise Interrupted()
    monkeypatch.setattr(tx.os, "replace", interrupt)
    with pytest.raises(Interrupted): public.install_payload(archive, data, **pin)
    assert old.read_bytes() == files["data/master-json/Card.json"]
    assert (data/tx.PENDING/"originals/master-json/Card.json").read_bytes() == b"old card bytes"
    with pytest.raises(ValueError, match="recovery_required"): public.acquire_payload_read_lease(data)
    assert_owned(data, before)
    different = tmp_path/"different.zip"; other_pin, _ = make_payload(different, generation="another")
    with pytest.raises(ValueError, match="pending_source_differs"):
        public.install_payload(different, data, **other_pin)
    monkeypatch.setattr(tx.os, "replace", replace)
    public.install_payload(archive, data, **pin)
    with public.acquire_payload_read_lease(data): pass
    assert_owned(data, before)
    assert not (data/tx.PENDING).exists()
    backup = next((data/tx.BACKUPS).iterdir())
    assert (backup/"originals/master-json/Card.json").read_bytes() == b"old card bytes"


def test_destination_ancestor_symlink_is_rejected_without_touching_outside_or_owned_state(tmp_path):
    archive = tmp_path/"latest.zip"; pin, _ = make_payload(archive)
    data = tmp_path/"data"; before = seed_owned(data)
    outside = tmp_path/"outside"; outside.mkdir(); marker = outside/"marker"; marker.write_bytes(b"untouched")
    # Existing unrelated files and the database remain untouched, including when validation fails.
    (data/"protocol").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe_path"): public.install_payload(archive, data, **pin)
    assert list(outside.iterdir()) == [marker] and marker.read_bytes() == b"untouched"
    assert_owned(data, before)


def test_cross_process_active_reader_blocks_upgrade_without_retry_or_data_change(tmp_path):
    archive = tmp_path/"latest.zip"; pin, _ = make_payload(archive)
    data = tmp_path/"data"; before = seed_owned(data)
    code = ("import sys; from idoly_local.public_payload import acquire_payload_read_lease; "
            "lease=acquire_payload_read_lease(sys.argv[1]); print('locked',flush=True); "
            "sys.stdin.read(1); lease.close()")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/"src"))
    child = subprocess.Popen([sys.executable, "-c", code, str(data)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        assert select.select([child.stdout], [], [], 10)[0]
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError, match="busy"): public.install_payload(archive, data, **pin)
        assert not (data/tx.PENDING).exists(); assert_owned(data, before)
        child.communicate("x", timeout=10); assert child.returncode == 0
    finally:
        if child.poll() is None: child.kill(); child.communicate(timeout=10)
    public.install_payload(archive, data, **pin)
    assert_owned(data, before)


def test_runtime_retains_reader_lease_if_listener_cleanup_fails(tmp_path):
    from idoly_local.app_runtime import Runtime
    archive = tmp_path/"latest.zip"; pin, _ = make_payload(archive)
    data = tmp_path/"data"; seed_owned(data)
    runtime = Runtime("synthetic")
    runtime._payload_lease = public.acquire_payload_read_lease(data)
    class Broken:
        running = True
        def stop(self): raise OSError("synthetic cleanup failure")
    runtime._grpc = Broken()
    with pytest.raises(RuntimeError, match="cleanup"): runtime.stop()
    with pytest.raises(ValueError, match="busy"): public.install_payload(archive, data, **pin)
    runtime._grpc = None
    runtime.stop()
    public.install_payload(archive, data, **pin)


@pytest.mark.parametrize("damage", ["symlink", "duplicate"])
def test_pinned_zip_rejects_nonregular_and_duplicate_members_before_mutation(tmp_path, damage):
    archive = tmp_path/"latest.zip"; _, files = make_payload(archive)
    with ZipFile(archive, "w") as target:
        for name, raw in files.items():
            if damage == "symlink" and name == "data/love-compatibility.json":
                info = ZipInfo(name); info.create_system = 3; info.external_attr = (stat.S_IFLNK | 0o777) << 16
                target.writestr(info, raw)
            else: target.writestr(name, raw)
        if damage == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                target.writestr("data/love-compatibility.json", files["data/love-compatibility.json"])
    pin = {"expected_bytes": archive.stat().st_size, "expected_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    data = tmp_path/"data"; before = seed_owned(data)
    with pytest.raises(ValueError): public.install_payload(archive, data, **pin)
    assert_owned(data, before)
    assert not (data/tx.PENDING).exists() and not (data/tx.STATE).exists()


def test_changed_source_descriptor_cannot_commit_after_staging(tmp_path, monkeypatch):
    archive = tmp_path/"latest.zip"; pin, _ = make_payload(archive); original = archive.read_bytes()
    data = tmp_path/"data"; before = seed_owned(data)
    old = data/"master-json/Card.json"; old.write_bytes(b"old card bytes")
    stage = tx._stage
    def change_after_staging(*args):
        stage(*args)
        with archive.open("ab") as output: output.write(b"unexpected source mutation")
    monkeypatch.setattr(tx, "_stage", change_after_staging)
    with pytest.raises(ValueError, match="source_changed"): public.install_payload(archive, data, **pin)
    assert old.read_bytes() == b"old card bytes" and not (data/tx.STATE).exists()
    assert_owned(data, before)
    with pytest.raises(ValueError, match="recovery_required"): public.acquire_payload_read_lease(data)
    archive.write_bytes(original); monkeypatch.setattr(tx, "_stage", stage)
    public.install_payload(archive, data, **pin)
    assert_owned(data, before)



def test_second_cohort_backup_can_reconstruct_previous_public_set_and_marker(tmp_path):
    old_archive = tmp_path/"old-latest.zip"; old_pin, previous_files = make_payload(old_archive, generation="previous")
    data = tmp_path/"data"; before = seed_owned(data)
    public.install_payload(old_archive, data, **old_pin)
    previous_state = json.loads((data/tx.STATE).read_bytes())
    new_archive = tmp_path/"new-latest.zip"; new_pin, _ = make_payload(new_archive)
    public.install_payload(new_archive, data, **new_pin)
    candidates = [(path, json.loads((path/"journal.json").read_bytes())) for path in (data/tx.BACKUPS).iterdir()]
    backup, journal = next((path, journal) for path, journal in candidates
                           if journal["identity"]["sha256"] == new_pin["expected_sha256"])
    assert journal["previous_state"] == previous_state
    reconstructed = {}
    for name in previous_files:
        original = backup/"originals"/name.removeprefix("data/")
        reconstructed[name] = (original if original.exists() else data/name.removeprefix("data/")).read_bytes()
    assert reconstructed == previous_files
    assert_owned(data, before)



def test_central_directory_entry_bound_precedes_zipfile_allocation(tmp_path, monkeypatch):
    archive = tmp_path/"latest.zip"; _, _ = make_payload(archive)
    raw = bytearray(archive.read_bytes()); offset = raw.rfind(b"PK\x05\x06")
    raw[offset+8:offset+12] = (tx.MAX_MEMBERS+1).to_bytes(2, "little")*2
    archive.write_bytes(raw)
    pin = {"expected_bytes": len(raw), "expected_sha256": hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr(tx, "ZipFile", lambda *_: pytest.fail("must reject before central-directory allocation"))
    with pytest.raises(ValueError): public.install_payload(archive, tmp_path/"data", **pin)
    assert not (tmp_path/"data").exists()



def test_incomplete_initial_journal_is_never_published_as_a_pending_cohort(tmp_path, monkeypatch):
    archive = tmp_path/"latest.zip"; pin, _ = make_payload(archive)
    data = tmp_path/"data"; before = seed_owned(data)
    write = tx._atomic
    def interrupt(path, value):
        if path.name == "journal.json": raise OSError("synthetic initial journal failure")
        write(path, value)
    monkeypatch.setattr(tx, "_atomic", interrupt)
    with pytest.raises(OSError, match="initial journal"): public.install_payload(archive, data, **pin)
    assert not (data/tx.PENDING).exists() and not (data/tx.STATE).exists()
    assert_owned(data, before)
    with public.acquire_payload_read_lease(data): pass
