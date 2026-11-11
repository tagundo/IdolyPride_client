"""Small synthetic boundaries; no Android tool, signing key or emulator needed."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo
import zlib
import xml.etree.ElementTree as ET

import pytest

from tools import build_android_server_manual as tool


def synthetic_dex(names):
    """Only the bounded tables read by dex_classes; never an installable APK."""
    count = len(names)
    string_offset, type_offset = 112, 112 + count * 4
    class_offset, data_offset = 112 + count * 8, 112 + count * 40
    raw = bytearray(data_offset)
    raw[:8] = b"dex\n038\0"
    struct.pack_into("<II", raw, 36, 112, 0x12345678)
    for at, offset in ((56, string_offset), (64, type_offset), (96, class_offset)):
        struct.pack_into("<II", raw, at, count, offset)
    for index, name in enumerate(names):
        encoded = name.encode("ascii")
        assert len(encoded) < 128
        struct.pack_into("<I", raw, string_offset + index * 4, len(raw))
        struct.pack_into("<I", raw, type_offset + index * 4, index)
        struct.pack_into("<I", raw, class_offset + index * 32, index)
        raw.extend(bytes([len(encoded)]) + encoded + b"\0")
    struct.pack_into("<I", raw, 32, len(raw))
    raw[12:32] = hashlib.sha1(raw[32:]).digest()
    struct.pack_into("<I", raw, 8, zlib.adler32(raw[12:]) & 0xffffffff)
    return bytes(raw)


def zip_bytes(files):
    target = io.BytesIO()
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return target.getvalue()


def manifest(raw=b""):
    return (b'<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
            b'<application android:allowBackup="false" android:usesCleartextTraffic="true">'
            b'<activity android:name=".MainActivity" android:exported="true"/>'
            b'<service android:name=".ServerService" android:exported="false"/>'
            + raw + b'</application></manifest>')


def test_generated_manifest_preserves_source_policy_and_required_merged_flags():
    root = ET.fromstring(tool.manifest_xml(manifest()))
    assert root.attrib == {"package": tool.PACKAGE, tool.ANDROID + "versionCode": "24",
                           tool.ANDROID + "versionName": "0.3.5"}
    assert root.find("uses-sdk").attrib == {tool.ANDROID + "minSdkVersion": "26",
                                           tool.ANDROID + "targetSdkVersion": "34"}
    app = root.find("application")
    assert app.get(tool.ANDROID + "allowBackup") == "false"
    assert app.get(tool.ANDROID + "usesCleartextTraffic") == "true"
    assert app.get(tool.ANDROID + "extractNativeLibs") == "true"
    assert app.get(tool.ANDROID + "debuggable") == "true"
    assert [(x.tag, x.get(tool.ANDROID + "name"), x.get(tool.ANDROID + "exported")) for x in app] == [
        ("activity", tool.PACKAGE + ".MainActivity", "true"),
        ("service", tool.PACKAGE + ".ServerService", "false")]


@pytest.mark.parametrize("extra", [b'<activity android:name=".MainActivity"/>', b'<provider android:name=".Other"/>'])
def test_duplicate_or_additional_manifest_components_rejected(extra):
    with pytest.raises(ValueError, match="component inventory"):
        tool.manifest_xml(manifest(extra))


def test_manifest_entity_and_backup_policy_rejected():
    for raw in (b'<!DOCTYPE manifest>' + manifest(), manifest().replace(b'allowBackup="false"', b'allowBackup="true"')):
        with pytest.raises(ValueError):
            tool.manifest_xml(raw)


def test_build_config_binds_new_version_and_exact_payload_hash():
    raw = tool.build_config("a" * 64).decode()
    assert 'VERSION_CODE = 24;' in raw and 'VERSION_NAME = "0.3.5";' in raw
    assert 'SERVER_DATA_SHA256 = "' + "a" * 64 + '";' in raw
    with pytest.raises(ValueError):
        tool.build_config('"; injected')


def test_frozen_source_ignores_worktree_and_requires_exact_inventory(tmp_path, monkeypatch):
    expected = {name: b"committed public source" for name in tool.SOURCE_FILES}
    expected[tool.GRADLE] = b'gradleProperty("serverVersionCode").orElse("24")\ngradleProperty("serverVersionName").orElse("0.3.5")'
    names = sorted(expected)
    listing = b"\0".join(b"100644 blob " + f"{index + 1:040x}".encode() + b"\t" + name.encode()
                           for index, name in enumerate(names)) + b"\0"
    blobs = {f"{index + 1:040x}": expected[name] for index, name in enumerate(names)}
    def git(_root, *args, limit):
        return listing if args[0] == "ls-tree" else blobs[args[2]]
    monkeypatch.setattr(tool.pybundle, "_git", git)
    (tmp_path / "uncommitted.java").write_text("must not enter the build")
    assert tool.source_blobs(tmp_path, "a" * 40) == expected
    listing += b"100644 blob " + b"f" * 40 + b"\t" + (tool.JAVA_ROOT + "Other.java").encode() + b"\0"
    with pytest.raises(ValueError, match="inventory"):
        tool.source_blobs(tmp_path, "a" * 40)


def test_executing_builder_and_compiler_helper_must_match_the_same_frozen_commit(monkeypatch):
    root = Path(tool.__file__).resolve().parents[1]
    names = ("tools/build_android_server_manual.py", "tools/repack_android_server_python.py")
    frozen = {name: (root / name).read_bytes() for name in names}
    def git(_root, *args, limit):
        return frozen[args[2].split(":", 1)[1]]
    monkeypatch.setattr(tool.pybundle, "_git", git)
    assert tool.tool_sources(root, "a" * 40) == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in frozen.items()}
    frozen[names[0]] = b"different builder source at declared commit"
    with pytest.raises(ValueError, match="differs from the frozen source"):
        tool.tool_sources(root, "a" * 40)


def test_dex_reads_definitions_not_referenced_strings_and_rejects_duplicate_or_bad_checksum():
    names = ["Lcom/chaquo/python/Python;", "Lcom/chaquo/python/PyObject;"]
    assert tool.dex_classes(synthetic_dex(names)) == set(names)
    with pytest.raises(ValueError, match="duplicated"):
        tool.dex_classes(synthetic_dex([names[0], names[0]]))
    corrupt = bytearray(synthetic_dex(names))
    corrupt[-2] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        tool.dex_classes(corrupt)


@pytest.mark.parametrize("raw", [b"", b"dex\n039\0" + b"\0" * 104, b"x" * (tool.MAX_DEX + 1)])
def test_wrong_dex_version_or_size_rejected(raw):
    with pytest.raises(ValueError):
        tool.dex_classes(raw)


def test_chaquopy_jar_must_match_both_original_hash_and_exact_dependency_class_roster(tmp_path, monkeypatch):
    names = [f"Lcom/chaquo/python/Type{index};" for index in range(27)]
    jar = tmp_path / "runtime.jar"
    jar.write_bytes(zip_bytes({name[1:-1] + ".class": b"synthetic class" for name in names}))
    monkeypatch.setattr(tool, "CHAQUOPY_SHA256", tool.pybundle.digest(jar))
    assert tool.dependency_classes(jar, synthetic_dex(names)) == set(names)
    with pytest.raises(ValueError, match="classes differ"):
        tool.dependency_classes(jar, synthetic_dex(names[:-1]))
    jar.write_bytes(jar.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="original public"):
        tool.dependency_classes(jar, synthetic_dex(names))


def public_payload(files):
    tables = {name[len("data/master-json/"):-5]: len(json.loads(raw)) for name, raw in files.items()
              if name.startswith("data/master-json/") and name.endswith(".json")}
    report = {"schema": 1, "master_version": "synthetic-public", "schema_sha256": "a" * 64,
              "tables": tables, "files": [{"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                                          for name, raw in files.items()]}
    return {**files, tool.PAYLOAD_MANIFEST: json.dumps(report).encode()}


@pytest.fixture
def payload_case(tmp_path):
    old = {f"data/master-json/Table{index:02}.json": b'[{"id":"public"}]' for index in range(40)}
    old["data/protocol/idolypride-6.1.1.pb"] = b"synthetic public descriptor"
    old["data/master-json/!version.txt"] = b"synthetic-public"
    new = {**old, **{"data/master-json/" + name + ".json": b'[{"id":"new-public"}]' for name in tool.EXTRA_TABLES}}
    baseline = tmp_path / "baseline.apk"
    baseline.write_bytes(zip_bytes({tool.pybundle.PAYLOAD: zip_bytes(public_payload(old))}))
    payload = tmp_path / "public.zip"
    def write(files=None):
        payload.write_bytes(zip_bytes(public_payload(new if files is None else files)))
        return tool.pybundle.digest(payload)
    return baseline, payload, new, write


def test_payload_extends_only_five_public_tables_and_verifies_actual_file_provenance(payload_case):
    baseline, payload, _files, write = payload_case
    digest = write()
    with ZipFile(baseline) as archive:
        report = tool.validate_payload(payload, digest, archive)
    assert len(report["tables"]) == 45 and report["sha256"] == digest


@pytest.mark.parametrize("change", ["private", "old-bytes", "missing", "empty-new"])
def test_payload_rejects_private_extra_mutated_old_or_incomplete_tables(payload_case, change):
    baseline, payload, original, write = payload_case
    files = dict(original)
    if change == "private":
        files["data/state.db"] = b"never bundle account state"
    elif change == "old-bytes":
        files["data/master-json/Table00.json"] = b'[{"id":"changed"}]'
    elif change == "missing":
        files.pop("data/master-json/StoryPart.json")
    else:
        files["data/master-json/StoryPart.json"] = b"[]"
    digest = write(files)
    with ZipFile(baseline) as archive, pytest.raises(ValueError):
        tool.validate_payload(payload, digest, archive)


@pytest.mark.parametrize("change", ["file-hash", "row-count-bool", "duplicate-path", "wrong-hash", "duplicate-member"])
def test_payload_rejects_forged_manifest_hash_and_duplicate_zip_members(payload_case, change):
    baseline, payload, files, write = payload_case
    values = public_payload(files)
    report = json.loads(values[tool.PAYLOAD_MANIFEST])
    if change == "file-hash":
        report["files"][0]["sha256"] = "0" * 64
    elif change == "row-count-bool":
        report["tables"]["StoryPart"] = True
    elif change == "duplicate-path":
        report["files"][0] = report["files"][1]
    values[tool.PAYLOAD_MANIFEST] = json.dumps(report).encode()
    payload.write_bytes(zip_bytes(values))
    if change == "duplicate-member":
        with ZipFile(payload, "a") as archive, pytest.warns(UserWarning):
            archive.writestr("data/master-json/StoryPart.json", b"[]")
    digest = "0" * 64 if change == "wrong-hash" else tool.pybundle.digest(payload)
    with ZipFile(baseline) as archive, pytest.raises(ValueError):
        tool.validate_payload(payload, digest, archive)


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_streaming_keeps_original_dependency_bytes_and_zero_metadata_without_whole_archive_read(tmp_path, monkeypatch, compression):
    baseline, target = tmp_path / "base.apk", tmp_path / "new.apk"
    with ZipFile(baseline, "w") as archive:
        for name, raw in {"classes.dex": b"immutable dependency DEX", "classes2.dex": b"old R",
                          "classes3.dex": b"old app", tool.pybundle.PAYLOAD: b"old payload"}.items():
            info = ZipInfo(name)
            info.compress_type = compression
            archive.writestr(info, raw)
            info.external_attr = 0
    payload = tmp_path / "new-public.zip"
    payload.write_bytes(b"new payload streamed from disk")
    monkeypatch.setattr(ZipFile, "read", lambda *args, **kwargs: pytest.fail("whole member read forbidden"))
    with ZipFile(baseline) as archive:
        infos = tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED)
        tool.stream_apk(archive, infos, target, {"classes2.dex": b"new own and R", tool.pybundle.PAYLOAD: payload})
    with ZipFile(target) as archive:
        assert "classes3.dex" not in archive.namelist()
        for info in archive.infolist():
            assert info.external_attr == 0 and info.compress_type == compression
        with archive.open("classes.dex") as stream:
            assert stream.read(1024) == b"immutable dependency DEX"
        with archive.open(tool.pybundle.PAYLOAD) as stream:
            assert stream.read(1024) == payload.read_bytes()


def synthetic_elf(align=16384):
    raw = bytearray(120)
    raw[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", raw, 16, 3, 183)
    struct.pack_into("<Q", raw, 32, 64)
    struct.pack_into("<HH", raw, 54, 56, 1)
    struct.pack_into("<IIQQQQQQ", raw, 64, 1, 5, 0, 0, 0, 120, 120, align)
    return bytes(raw)


def test_elf_load_alignment_is_checked_on_preserved_bytes():
    assert tool.elf_alignment(synthetic_elf()) == [16384]
    with pytest.raises(ValueError, match="16 KiB"):
        tool.elf_alignment(synthetic_elf(4096))


@pytest.mark.parametrize("tamper", [None, "classes.dex", "assets/chaquopy/bootstrap.imy"])
def test_apk_audit_accepts_only_own_replacements_and_preserves_runtime_dependency_bytes(tmp_path, tamper):
    dependencies = {f"Lcom/chaquo/python/Type{index};" for index in range(27)}
    own = {"L" + tool.PACKAGE.replace(".", "/") + "/MainActivity;"}
    files = {name: b"old mutable" for name in tool.MUTABLE_NAMES | tool.REMOVED_NAMES}
    files.update({name: synthetic_elf() for name in tool.NATIVE_NAMES})
    files["classes.dex"] = synthetic_dex(sorted(dependencies))
    files["assets/chaquopy/bootstrap.imy"] = b"immutable Python runtime"
    baseline, candidate = tmp_path / "baseline.apk", tmp_path / "candidate.apk"
    baseline.write_bytes(zip_bytes(files))
    replacements = {name: b"new approved input" for name in tool.MUTABLE_NAMES}
    replacements["classes2.dex"] = synthetic_dex(sorted(own))
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in replacements.items()}
    with ZipFile(baseline) as archive:
        infos = tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED)
        before = tool.pybundle._hash_members(archive, infos)
        tool.stream_apk(archive, infos, candidate, replacements)
    if tamper:
        with ZipFile(candidate) as archive:
            retained_infos = archive.infolist()
            changed = {info.filename: tool.pybundle._read(archive, info, tool.MAX_JSON) for info in retained_infos}
        changed[tamper] += b"tampered"
        with ZipFile(candidate, "w") as archive:
            for info in retained_infos:
                archive.writestr(info, changed[info.filename])
        with pytest.raises(ValueError, match="approved input"):
            tool.audit_apk(candidate, before, infos, hashes, dependencies, own)
    else:
        report = tool.audit_apk(candidate, before, infos, hashes, dependencies, own)
        assert report["all_other_member_bytes_and_metadata_preserved"] is True
        assert report["removed_apk_members"] == ["classes3.dex"]
        assert len(report["native_elf_load_alignments"]) == 9


def test_password_read_is_bounded_before_open_and_preserves_only_single_line(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-password"
    path.write_bytes(b"synthetic\r\n")
    assert tool.read_password(path) == "synthetic"
    path.write_bytes(b"x" * 4097)
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("oversized file must not be opened"))
    with pytest.raises(ValueError, match="format"):
        tool.read_password(path)


@pytest.mark.parametrize("same_device", [False, True])
def test_staging_reserves_root_space_before_first_apk_allocation(monkeypatch, same_device):
    class Location:
        def __init__(self, name): self.name = name
        def stat(self): return SimpleNamespace(st_dev=1 if self.name == "root" or same_device else 2)
    monkeypatch.setattr(tool, "Path", lambda value: value)
    minimum = tool.MAX_APK_STAGING + 8 * tool.MIB + (tool.MIN_ROOT_FREE if same_device else 0)
    monkeypatch.setattr(tool.shutil, "disk_usage", lambda _: SimpleNamespace(free=minimum))
    tool.staging_budget(Location("root"), Location("destination"))
    monkeypatch.setattr(tool.shutil, "disk_usage", lambda _: SimpleNamespace(free=minimum - 1))
    with pytest.raises(ValueError, match="reserve"):
        tool.staging_budget(Location("root"), Location("destination"))


def test_offline_subprocess_timeout_bounds_silent_pipe_and_reaps_child(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "_resource_guard", lambda _: {})
    started = time.monotonic()
    with pytest.raises(ValueError, match="timed out"):
        tool._run([sys.executable, "-c", "import time; time.sleep(30)"], root=tmp_path,
                  env={}, timeout=0.1)
    assert time.monotonic() - started < 3


def test_subprocess_failure_withholds_output_and_never_runs_if_resource_guard_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "_resource_guard", lambda _: {})
    with pytest.raises(ValueError, match="output withheld") as error:
        tool._run([sys.executable, "-c", "print('SYNTHETIC_PRIVATE_TEXT'); raise SystemExit(7)"],
                  root=tmp_path, env={}, timeout=3)
    assert "SYNTHETIC_PRIVATE_TEXT" not in str(error.value)
    def deferred(_root): raise ValueError("resource guard")
    monkeypatch.setattr(tool, "_resource_guard", deferred)
    monkeypatch.setattr(tool.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(ValueError, match="resource guard"):
        tool._run(["must-not-run"], root=tmp_path, env={})
