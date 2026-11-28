"""Pinned public-cohort installation, recovery and lifetime reader leases.

Only manifest-listed public files are managed. Account databases, profiles,
settings, resource caches and unlisted files are never read, copied or removed.
"""
from __future__ import annotations

from contextlib import contextmanager

import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import uuid
from zipfile import ZipFile

POLICY = "latest-cohort-overlay-v1"
MANIFEST = "data/payload-manifest.json"
LOCK = ".public-payload.lock"
PENDING = ".public-payload-transaction"
STATE = ".public-payload-state.json"
BACKUPS = ".public-payload-backups"
MAX_SOURCE = 512 * 1024 * 1024
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_META = 2 * 1024 * 1024
MAX_MEMBERS = 2048
SHA = re.compile(r"[0-9a-f]{64}")
TABLES = frozenset((
    "Accessory", "Area", "AreaGroup", "Card", "CardImage", "CardLevel", "CardLevelRelease",
    "CardParameter", "CardRarity", "Character", "CharacterActivityLevel", "ComboAdvantage",
    "CompanyEnjoyCharacterLevel", "CompanyEnjoyCharacterLevelSetting", "CompanyGrade", "CompanyTrustLevel",
    "Condition", "Consumption", "Costume", "Decoration", "Emblem", "EventMission", "EventStory",
    "ExcursionGazeReaction", "ExcursionPlace", "ExcursionPlaceSetting", "ExtraStory", "ExtraStoryPart",
    "Hair", "HierarchyDetailGrade", "HierarchyGrade", "HomeTalk", "Item", "LoveCatalog", "LoveColor",
    "LoveHomeAction", "LoveLevel", "LoveStoryEpisode", "ManagerLevel", "Message", "MessageGroup", "Mission",
    "Music", "MusicChartPattern", "PhotoActivity", "PhotoExpression", "PhotoPose", "PhotoPoseMotion",
    "PhotoQuestMusic", "PhotoQuestStage", "Quest", "QuestAudienceAdvantage", "QuestPressure",
    "QuestStaminaConsumption", "Reward", "Setting", "Skill", "SkillEfficacy", "SkillTarget", "SkillTrigger",
    "Stage", "Story", "StoryPart", "Tutorial"))


def _need(condition, code="public_payload_invalid"):
    if not condition:
        raise ValueError(code)


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_bound(stream, size):
    stream.seek(max(0, size-65557))
    tail = stream.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    _need(offset >= 0 and offset+22 <= len(tail))
    _, disk, directory_disk, disk_entries, entries, extent, start, comment = struct.unpack(
        "<4s4H2LH", tail[offset:offset+22])
    _need(disk == directory_disk == 0 and disk_entries == entries and 0 < entries <= MAX_MEMBERS
          and 0 < extent <= MAX_META and start+extent == size-len(tail)+offset
          and offset+22+comment == len(tail))
    stream.seek(0)


@contextmanager
def _pinned_archive(source, expected_sha256, expected_bytes):
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _need(stat.S_ISREG(info.st_mode) and info.st_size == expected_bytes,
              "public_payload_pin_mismatch")
        _need(hashlib.file_digest(stream, "sha256").hexdigest() == expected_sha256,
              "public_payload_pin_mismatch")
        snapshot = _file_identity(info)
        def unchanged():
            _need(_file_identity(os.fstat(stream.fileno())) == snapshot,
                  "public_payload_source_changed")
        unchanged()
        _directory_bound(stream, expected_bytes)
        with ZipFile(stream) as archive:
            yield archive, unchanged


def _regular(path):
    info = path.lstat()
    _need(stat.S_ISREG(info.st_mode), "public_payload_unsafe_path")
    return info


def _root(path):
    path = Path(path)
    _need(not path.is_symlink(), "public_payload_unsafe_path")
    _directory(path, parents=True)
    return path.resolve()


def _relative(relative):
    from .public_payload import member_path
    _need(type(relative) is str and relative.startswith("data/") and relative.isprintable()
          and len(relative.encode("utf-8")) <= 512)
    admitted = member_path(relative)
    _need(relative == "data/"+admitted, "public_payload_unsafe_path")
    return admitted


def _target(root, relative):
    _need(not root.is_symlink() and (not os.path.lexists(root) or root.is_dir()), "public_payload_unsafe_path")
    admitted = _relative(relative)
    result = root
    for part in Path(admitted).parts:
        result = result / part
        if os.path.lexists(result):
            _need(not result.is_symlink(), "public_payload_unsafe_path")
            _need(result.is_dir() if result != root / admitted else result.is_file(),
                  "public_payload_unsafe_path")
    return result


def _directory(path, *, parents=False):
    _need(not path.is_symlink(), "public_payload_unsafe_path")
    if not os.path.lexists(path):
        if parents:
            _directory(path.parent, parents=True)
        path.mkdir(mode=0o700)
        _sync_directory(path.parent)
    _need(path.is_dir(), "public_payload_unsafe_path")
    return path


def _object(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result)
        result[key] = value
    return result


def _metadata(path):
    info = _regular(path)
    _need(info.st_size <= MAX_META)
    with path.open("rb") as stream:
        raw = stream.read(MAX_META+1)
    _need(len(raw) == info.st_size <= MAX_META)
    return json.loads(raw, object_pairs_hook=_object)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_file(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        _need(stat.S_ISREG(os.fstat(descriptor).st_mode), "public_payload_unsafe_path")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic(path, document):
    raw = (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)+"\n").encode()
    _need(len(raw) <= MAX_META)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".public-payload-", delete=False) as output:
            temporary = Path(output.name)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        _sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class _Lease:
    def __init__(self, root, *, exclusive):
        import fcntl
        self.descriptor = None
        path = root / LOCK
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(descriptor)
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 0,
                  "public_payload_unsafe_path")
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            self.descriptor = descriptor
        except BaseException as error:
            os.close(descriptor)
            if isinstance(error, OSError) and error.errno in (errno.EAGAIN, errno.EACCES):
                raise ValueError("public_payload_busy") from None
            raise

    def close(self):
        descriptor, self.descriptor = self.descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _matches(path, row):
    if not os.path.lexists(path):
        return False
    return _regular(path).st_size == row["bytes"] and _digest(path) == row["sha256"]


def _rows(value, *, include_manifest=False):
    _need(type(value) is list and 1 <= len(value) <= MAX_MEMBERS)
    names, total = [], 0
    for row in value:
        _need(type(row) is dict and set(row) == {"path", "bytes", "sha256"})
        _need(type(row["path"]) is str and type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_FILE)
        _need(type(row["sha256"]) is str and SHA.fullmatch(row["sha256"]))
        _relative(row["path"])
        names.append(row["path"])
        total += row["bytes"]
    _need(names == sorted(set(names)) and total <= MAX_TOTAL)
    _need((MANIFEST in names) is include_manifest)
    actual = {name[len("data/master-json/"):-5] for name in names
              if name.startswith("data/master-json/") and name.endswith(".json")}
    _need(actual == TABLES)
    _need({"data/protocol/idolypride-6.1.1.pb", "data/original-master/master-tag.json",
           "data/love-compatibility.json", "data/love-legacy-rules.json", "data/latest-semantic-controls.json",
           "data/public-octo/legacy-manifest.pb", "data/public-octo-ios/legacy-manifest.pb"} <= set(names))
    return value


def _identity(value):
    _need(type(value) is dict and set(value) == {"schema", "policy", "bytes", "sha256", "manifest_sha256", "master_version"})
    _need(type(value["schema"]) is int and value["schema"] == 1 and value["policy"] == POLICY)
    _need(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_SOURCE)
    _need(all(type(value[key]) is str and SHA.fullmatch(value[key])
              for key in ("sha256", "manifest_sha256", "master_version")))
    return value


def _validate_state(value):
    _need(type(value) is dict and set(value) == {"schema", "identity", "members"}
          and type(value["schema"]) is int and value["schema"] == 1)
    identity = _identity(value["identity"])
    rows = _rows(value["members"], include_manifest=True)
    manifest = next(row for row in rows if row["path"] == MANIFEST)
    _need(manifest["sha256"] == identity["manifest_sha256"])
    return value


def _state(root):
    path = root / STATE
    if not os.path.lexists(path):
        return None
    return _validate_state(_metadata(path))


def _installed(root, identity, rows):
    state = _state(root)
    return (state is not None and state["identity"] == identity and state["members"] == rows
            and all(_matches(_target(root, row["path"]), row) for row in rows))


def acquire_payload_read_lease(data_dir):
    root = _root(data_dir)
    lease = _Lease(root, exclusive=False)
    try:
        _need(not os.path.lexists(root / PENDING), "public_payload_recovery_required")
        state = _state(root)
        if state is not None:
            _need(all(_matches(_target(root, row["path"]), row) for row in state["members"]),
                  "public_payload_recovery_required")
        return lease
    except BaseException:
        lease.close()
        raise


def _journal(root, identity, rows):
    pending = root / PENDING
    if os.path.lexists(pending):
        _need(pending.is_dir() and not pending.is_symlink(), "public_payload_unsafe_path")
        value = _metadata(pending / "journal.json")
        _need(type(value) is dict and set(value) == {"schema", "identity", "members", "originals", "previous_state", "phase"})
        _need(type(value["schema"]) is int and value["schema"] == 1)
        _identity(value["identity"])
        _rows(value["members"], include_manifest=True)
        if value["previous_state"] is not None:
            _validate_state(value["previous_state"])
        _need(value["identity"] == identity and value["members"] == rows, "public_payload_pending_source_differs")
        _need(value["phase"] in ("staging", "committing", "committed"))
        _need(type(value["originals"]) is dict and set(value["originals"]) == {row["path"] for row in rows})
        for old in value["originals"].values():
            _need(old is None or type(old) is dict and set(old) == {"bytes", "sha256"}
                  and type(old["bytes"]) is int and 0 <= old["bytes"] <= MAX_FILE
                  and type(old["sha256"]) is str and SHA.fullmatch(old["sha256"]))
        return pending, value
    originals = {}
    for row in rows:
        target = _target(root, row["path"])
        if os.path.lexists(target):
            info = _regular(target)
            _need(info.st_size <= MAX_FILE)
            originals[row["path"]] = {"bytes": info.st_size, "sha256": _digest(target)}
        else:
            originals[row["path"]] = None
    value = {"schema": 1, "identity": identity, "members": rows, "originals": originals,
             "previous_state": _state(root), "phase": "staging"}
    # Publish the pending directory only after its complete journal is durable.
    # A crash before publication leaves the original public set untouched.
    initializing = Path(tempfile.mkdtemp(prefix=".public-payload-init-", dir=root))
    try:
        _atomic(initializing / "journal.json", value)
        _sync_directory(initializing)
        os.replace(initializing, pending)
        initializing = None
        _sync_directory(root)
    finally:
        if initializing is not None and os.path.lexists(initializing):
            shutil.rmtree(initializing)
    return pending, value


def _stage(archive, pending, rows):
    stage = pending / "staged"
    _directory(stage)
    for row in rows:
        target = _target(stage, row["path"])
        if _matches(target, row):
            continue
        _directory(target.parent, parents=True)
        temporary = None
        try:
            with archive.open(row["path"]) as incoming, tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=".public-payload-", delete=False) as output:
                temporary = Path(output.name)
                digest, count = hashlib.sha256(), 0
                while block := incoming.read(65536):
                    count += len(block)
                    _need(count <= row["bytes"])
                    digest.update(block)
                    output.write(block)
                _need(count == row["bytes"] and digest.hexdigest() == row["sha256"])
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            temporary = None
            _sync_directory(target.parent)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _commit(root, pending, journal):
    journal["phase"] = "committing"
    _atomic(pending / "journal.json", journal)
    backup = pending / "originals"
    _directory(backup)
    copied = 0
    for row in journal["members"]:
        target = _target(root, row["path"])
        if _matches(target, row):
            continue
        old = journal["originals"][row["path"]]
        saved = _target(backup, row["path"])
        if old is not None:
            if os.path.lexists(saved):
                _need(_matches(saved, old), "public_payload_recovery_required")
                _need(not os.path.lexists(target), "public_payload_recovery_required")
            else:
                _need(_matches(target, old), "public_payload_recovery_required")
                _directory(saved.parent, parents=True)
                _sync_file(target)
                os.replace(target, saved)
                _sync_directory(target.parent)
                _sync_directory(saved.parent)
        else:
            _need(not os.path.lexists(target), "public_payload_recovery_required")
        staged = _target(pending / "staged", row["path"])
        _need(_matches(staged, row), "public_payload_recovery_required")
        _directory(target.parent, parents=True)
        os.replace(staged, target)
        _sync_directory(target.parent)
        _sync_directory(staged.parent)
        copied += 1
    return copied


def _finish(root, pending, journal):
    rows = journal["members"]
    _need(all(_matches(_target(root, row["path"]), row) for row in rows), "public_payload_recovery_required")
    for row in rows:
        old = journal["originals"][row["path"]]
        if old is not None and old != {"bytes": row["bytes"], "sha256": row["sha256"]}:
            _need(_matches(_target(pending / "originals", row["path"]), old),
                  "public_payload_recovery_required")
    _atomic(root / STATE, {"schema": 1, "identity": journal["identity"], "members": rows})
    journal["phase"] = "committed"
    _atomic(pending / "journal.json", journal)
    stage = pending / "staged"
    if os.path.lexists(stage):
        _directory(stage)
        for row in rows:
            remaining = _target(stage, row["path"])
            if os.path.lexists(remaining):
                _need(_matches(remaining, row), "public_payload_recovery_required")
                remaining.unlink()
    backups = root / BACKUPS
    _need(not backups.is_symlink(), "public_payload_unsafe_path")
    _directory(backups)
    os.replace(pending, backups / uuid.uuid4().hex)
    _sync_directory(backups)
    _sync_directory(root)


def install_managed_payload(source, data_dir, *, expected_sha256, expected_bytes):
    source = Path(source)
    _need(type(expected_sha256) is str and SHA.fullmatch(expected_sha256)
          and type(expected_bytes) is int and 0 < expected_bytes <= MAX_SOURCE, "public_payload_pin_required")
    with _pinned_archive(source, expected_sha256, expected_bytes) as (archive, source_unchanged):
        infos = archive.infolist()
        _need(0 < len(infos) <= MAX_MEMBERS and len({info.filename for info in infos}) == len(infos))
        _need(all(not info.is_dir() and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
                  and not info.flag_bits & 1 for info in infos), "public_payload_unsafe_path")
        _need(archive.getinfo(MANIFEST).file_size <= MAX_META)
        raw = archive.read(MANIFEST)
        manifest = json.loads(raw, object_pairs_hook=_object)
        _need(type(manifest) is dict and type(manifest.get("schema")) is int and manifest["schema"] == 1)
        overlay = manifest.get("source_overlay", {})
        _need(type(overlay) is dict and overlay.get("operation") == POLICY
              and overlay.get("derivation") == "complete-public-member-replacement"
              and manifest.get("master_version") == overlay.get("master_version"))
        rows = _rows(manifest.get("files"))
        _need({info.filename for info in infos} == {row["path"] for row in rows} | {MANIFEST})
        _need(all(archive.getinfo(row["path"]).file_size == row["bytes"] for row in rows))
        identity = _identity({"schema": 1, "policy": POLICY, "bytes": expected_bytes,
            "sha256": expected_sha256, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "master_version": overlay.get("master_version")})
        rows = sorted([*rows, {"path": MANIFEST, "bytes": len(raw), "sha256": identity["manifest_sha256"]}],
                      key=lambda row: row["path"])
        source_unchanged()
        root = _root(data_dir)
        with _Lease(root, exclusive=False):
            if not os.path.lexists(root / PENDING) and _installed(root, identity, rows):
                return {"copied": 0, "preserved": len(rows)}
        with _Lease(root, exclusive=True):
            if not os.path.lexists(root / PENDING) and _installed(root, identity, rows):
                return {"copied": 0, "preserved": len(rows)}
            pending, journal = _journal(root, identity, rows)
            if not _installed(root, identity, rows):
                _need(shutil.disk_usage(root).free >= sum(row["bytes"] for row in rows)+4*MAX_META,
                      "public_payload_insufficient_space")
                _stage(archive, pending, rows)
                source_unchanged()
                copied = _commit(root, pending, journal)
            else:
                copied = 0
            _finish(root, pending, journal)
            return {"copied": copied, "preserved": len(rows)-copied}
