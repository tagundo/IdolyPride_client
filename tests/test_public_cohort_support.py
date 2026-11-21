"""Synthetic authority exercises the real read-only cohort trust boundary."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from idoly_local import latest_cohort_pins as pins
from idoly_local import public_cohort_support as support

VERSION = "6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11"
SCHEMA = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
ROLES = ("story_reads", "media_access", "panorama", "dream", "main_live", "octo")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode()


@pytest.fixture(autouse=True)
def empty_caches():
    with support._LOCK:
        support._VERIFIED.clear()
        support._CONTROLS.clear()
    yield
    with support._LOCK:
        support._VERIFIED.clear()
        support._CONTROLS.clear()


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    def create(name="data"):
        root = tmp_path / name
        master = root / "master-json"
        master.mkdir(parents=True)
        (master / "!version.txt").write_text(VERSION)
        member = master / "Story.json"
        member.write_bytes(b'["one"]\n')
        features = {}
        for role in ROLES:
            receipt = {"source": "synthetic contract", "verified": True}
            features[role] = {"status": "PASS", "scope": role, "master_version": VERSION,
                "schema_sha256": SCHEMA, "receipt": receipt,
                "receipt_sha256": hashlib.sha256(canonical(receipt)).hexdigest()}
        proof = {"schema": 1, "master_version": VERSION, "features": features}
        path = root / "latest-semantic-controls.json"

        def write_proof(value=proof):
            raw = canonical(value) + b"\n"
            path.write_bytes(raw)
            monkeypatch.setattr(pins, "CONTROLS_SHA256", hashlib.sha256(raw).hexdigest())

        write_proof()
        row = {"path": "master-json/Story.json", "bytes": member.stat().st_size,
               "sha256": hashlib.sha256(member.read_bytes()).hexdigest()}
        monkeypatch.setattr(pins, "MASTER_VERSION", VERSION)
        monkeypatch.setattr(pins, "FEATURE_FILES", {role: [dict(row)] for role in ROLES[:-1]})
        return SimpleNamespace(root=root, master=master, member=member, proof=proof,
                               proof_path=path, row=row, write_proof=write_proof)
    return create


@pytest.mark.parametrize("role", ROLES[:-1])
def test_exact_approved_cohort_is_read_only_and_opens_only_public_members(cohort, monkeypatch, role):
    value = cohort()
    private = {name: b"private canary" for name in ("state.db", "accounts.json", "ios-host.json")}
    for name, raw in private.items():
        (value.root / name).write_bytes(raw)
    before = {path: path.read_bytes() for path in value.root.rglob("*") if path.is_file()}
    opened = []
    original = support._open_member

    def record(root, name):
        opened.append(name)
        return original(root, name)

    monkeypatch.setattr(support, "_open_member", record)
    assert support.require_master_cohort(value.master, role) is None
    assert set(opened) == {"master-json/!version.txt", "latest-semantic-controls.json", "master-json/Story.json"}
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("change", ["empty", "controls-none", "registry-list", "registry-bool",
    "registry-role", "rows-empty", "row-extra", "size-bool", "size-bound", "digest-type", "version-type"])
def test_missing_or_malformed_generated_authority_fails_closed(cohort, monkeypatch, change):
    value = cohort()
    if change == "empty": monkeypatch.setattr(pins, "FEATURE_FILES", {})
    elif change == "controls-none": monkeypatch.setattr(pins, "CONTROLS_SHA256", None)
    elif change == "registry-list": monkeypatch.setattr(pins, "FEATURE_FILES", [])
    elif change == "registry-bool": monkeypatch.setattr(pins, "FEATURE_FILES", True)
    elif change == "registry-role": monkeypatch.setattr(pins, "FEATURE_FILES", {"future": [value.row]})
    elif change == "rows-empty": pins.FEATURE_FILES["story_reads"] = []
    elif change == "row-extra": pins.FEATURE_FILES["story_reads"][0]["private"] = "ignored"
    elif change == "size-bool": pins.FEATURE_FILES["story_reads"][0]["bytes"] = True
    elif change == "size-bound": pins.FEATURE_FILES["story_reads"][0]["bytes"] = 64 * 1024**2 + 1
    elif change == "digest-type": pins.FEATURE_FILES["story_reads"][0]["sha256"] = None
    else: monkeypatch.setattr(pins, "MASTER_VERSION", True)
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")


@pytest.mark.parametrize("change", ["missing-role", "other-version", "schema-bool", "envelope-extra",
    "wrong-scope", "wrong-schema", "empty-receipt", "receipt-digest", "unselected-envelope"])
def test_all_six_envelopes_are_checked_even_for_one_selected_role(cohort, change):
    value = cohort()
    proof = copy.deepcopy(value.proof)
    target = proof["features"]["story_reads"]
    if change == "missing-role": del proof["features"]["octo"]
    elif change == "other-version": proof["master_version"] = "f" * 64
    elif change == "schema-bool": proof["schema"] = True
    elif change == "envelope-extra": target["unexpected"] = "value"
    elif change == "wrong-scope": target["scope"] = "panorama"
    elif change == "wrong-schema": target["schema_sha256"] = "f" * 64
    elif change == "empty-receipt": target["receipt"] = {}
    elif change == "receipt-digest": target["receipt"]["verified"] = 1
    else: proof["features"]["octo"]["status"] = "FAIL"
    value.write_proof(proof)
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")
    assert not support._CONTROLS


@pytest.mark.parametrize("role", ["future", "octo", None, True, [], {}])
def test_unknown_or_nonstring_roles_do_not_open_any_file(cohort, monkeypatch, role):
    value = cohort()
    monkeypatch.setattr(support, "_open_member", lambda *_: pytest.fail("unknown role opened a file"))
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, role)


@pytest.mark.parametrize("source", [None, "", True, 3, [], {}])
def test_invalid_source_types_have_the_declared_valueerror_contract(cohort, source):
    cohort()
    with pytest.raises(ValueError):
        support.require_master_cohort(source, "story_reads")


@pytest.mark.parametrize("field", ["MASTER_VERSION", "CONTROLS_SHA256", "FEATURE_FILES"])
def test_missing_generated_fields_fail_closed_cleanly(cohort, monkeypatch, field):
    value = cohort()
    monkeypatch.delattr(pins, field)
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")


@pytest.mark.parametrize("kind", ["duplicate", "nonfinite", "oversize", "deep"])
def test_control_json_is_strict_bounded_and_invalid_shapes_are_never_cached(cohort, monkeypatch, kind):
    value = cohort()
    raw = {"duplicate": b'{"schema":1,"schema":1}', "nonfinite": b'{"value":NaN}',
           "oversize": b" " * (512 * 1024 + 1),
           "deep": b"[" * 2000 + b"0" + b"]" * 2000}[kind]
    value.proof_path.write_bytes(raw)
    monkeypatch.setattr(pins, "CONTROLS_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")
    assert not support._CONTROLS


@pytest.mark.parametrize("name", ["state.db", "profiles/save.json", "resource-cache/settings.json",
    "../state.db", "/private/state.db", "master-json/../state.db", "master-json//Story.json",
    "master-json/./Story.json", "master-json\\Story.json", "master-json/\nStory.json"])
def test_private_or_noncanonical_member_paths_are_rejected_before_open(cohort, monkeypatch, name):
    value = cohort()
    pins.FEATURE_FILES["story_reads"][0]["path"] = name
    original = support._open_member

    def open_(root, requested):
        assert requested in ("master-json/!version.txt", "latest-semantic-controls.json")
        return original(root, requested)

    monkeypatch.setattr(support, "_open_member", open_)
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")


@pytest.mark.parametrize("kind", ["leaf", "parent", "controls", "fifo", "master"])
def test_symlinks_and_nonregular_nodes_cannot_escape_public_root(cohort, tmp_path, kind):
    value = cohort()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.json").write_bytes(value.member.read_bytes())
    if kind == "leaf":
        value.member.unlink()
        value.member.symlink_to(outside / "file.json")
    elif kind == "parent":
        (value.root / "original-master").symlink_to(outside, target_is_directory=True)
        pins.FEATURE_FILES["story_reads"][0]["path"] = "original-master/file.json"
    elif kind == "controls":
        value.proof_path.unlink()
        value.proof_path.symlink_to(outside / "file.json")
    elif kind == "fifo":
        value.member.unlink()
        os.mkfifo(value.member)
    else:
        moved = value.root / "moved"
        value.master.rename(moved)
        value.master.symlink_to(moved, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        support.require_master_cohort(value.master, "story_reads")


def test_partial_registry_keeps_other_roles_closed(cohort, monkeypatch):
    value = cohort()
    monkeypatch.setattr(pins, "FEATURE_FILES", {"story_reads": [value.row]})
    support.require_master_cohort(value.master, "story_reads")
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "panorama")


@pytest.mark.parametrize("change", ["too-many", "duplicate", "unsorted"])
def test_member_inventory_count_and_order_are_strict(cohort, change):
    value = cohort()
    if change == "too-many":
        rows = [{**value.row, "path": "master-json/" + str(number).zfill(3) + ".json"} for number in range(257)]
    elif change == "duplicate":
        rows = [dict(value.row), dict(value.row)]
    else:
        rows = [{**value.row, "path": "master-json/z.json"}, {**value.row, "path": "master-json/a.json"}]
    pins.FEATURE_FILES["story_reads"] = rows
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")


@pytest.mark.parametrize("change", ["version", "controls", "member", "size"])
def test_changed_revision_or_bytes_fail_after_previous_success(cohort, change):
    value = cohort()
    support.require_master_cohort(value.master, "story_reads")
    if change == "version": (value.master / "!version.txt").write_text("f" * 64)
    elif change == "controls": value.proof_path.write_text("{}")
    elif change == "member": value.member.write_bytes(b'["two"]\n')
    else: value.member.write_bytes(b"larger public content")
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")


def test_metadata_mutation_during_validation_is_not_cached(cohort, monkeypatch):
    value = cohort()
    original = support._parse_controls

    def mutate(raw, version):
        result = original(raw, version)
        value.proof_path.write_bytes(raw + b" ")
        return result

    monkeypatch.setattr(support, "_parse_controls", mutate)
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")
    assert not support._CONTROLS and not support._VERIFIED


def test_member_mutation_during_hash_is_not_cached(cohort, monkeypatch):
    value = cohort()
    original = hashlib.sha256
    changed = []

    class Digest:
        def __init__(self, raw=b""): self.inner = original(raw)
        def update(self, block):
            self.inner.update(block)
            if block == b'["one"]\n' and not changed:
                changed.append(True)
                value.member.write_bytes(b'["two"]\n')
        def hexdigest(self): return self.inner.hexdigest()

    monkeypatch.setattr(support.hashlib, "sha256", Digest)
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")
    assert changed and not support._VERIFIED


@pytest.mark.parametrize("change", ["inode", "mode", "mtime"])
def test_member_cache_rehashes_when_any_source_identity_changes(cohort, monkeypatch, change):
    value = cohort()
    count = []
    original = hashlib.sha256

    class Digest:
        def __init__(self, raw=b""): self.inner = original(raw)
        def update(self, block):
            if block == b'["one"]\n': count.append(True)
            self.inner.update(block)
        def hexdigest(self): return self.inner.hexdigest()

    monkeypatch.setattr(support.hashlib, "sha256", Digest)
    support.require_master_cohort(value.master, "story_reads")
    support.require_master_cohort(value.master, "story_reads")
    assert len(count) == 1
    if change == "inode":
        replacement = value.master / "replacement"
        replacement.write_bytes(value.member.read_bytes())
        os.replace(replacement, value.member)
    elif change == "mode":
        value.member.chmod(stat.S_IMODE(value.member.stat().st_mode) ^ stat.S_IXUSR)
    else:
        info = value.member.stat()
        os.utime(value.member, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
    support.require_master_cohort(value.master, "story_reads")
    assert len(count) == 2


def test_member_cache_hit_rechecks_open_descriptor_identity(cohort, monkeypatch):
    value = cohort()
    support.require_master_cohort(value.master, "story_reads")
    inode, original, calls = value.member.stat().st_ino, support._identity, []

    def identity(info):
        result = original(info)
        if info.st_ino == inode:
            calls.append(True)
            if len(calls) == 2:
                result = (*result[:-1], result[-1] + 1)
        return result

    monkeypatch.setattr(support, "_identity", identity)
    with pytest.raises(ValueError):
        support.require_master_cohort(value.master, "story_reads")
    assert len(calls) >= 2


def test_controls_cache_reuses_validation_and_both_caches_have_fixed_lru_bounds(cohort, monkeypatch):
    calls = []
    original = support._parse_controls
    monkeypatch.setattr(support, "_parse_controls", lambda *args: (calls.append(True), original(*args))[1])
    first = cohort("root-0")
    support.require_master_cohort(first.master, "story_reads")
    support.require_master_cohort(first.master, "story_reads")
    assert len(calls) == 1
    for number in range(1, 17):
        value = cohort("root-" + str(number))
        support.require_master_cohort(value.master, "story_reads")
    assert support._MAX_CONTROLS_CACHE == 16 and len(support._CONTROLS) == 16
    assert not any(key[0] == str(first.root) for key in support._CONTROLS)
    for number in range(513):
        path = first.master / ("member-" + str(number) + ".json")
        path.write_bytes(b"x")
        support._verify_file(first.root, {"path": "master-json/" + path.name, "bytes": 1,
                                         "sha256": hashlib.sha256(b"x").hexdigest()})
    assert support._MAX_MEMBER_CACHE == 512 and len(support._VERIFIED) == 512


def test_cache_identity_includes_all_required_fstat_fields():
    values = dict(st_dev=1, st_ino=2, st_mode=3, st_size=4, st_mtime_ns=5, st_ctime_ns=6)
    assert support._identity(SimpleNamespace(**values)) == (1, 2, 3, 4, 5, 6)
