"""Small synthetic boundaries; no Android tool, signing key or emulator needed."""
import copy
import hashlib
import errno
import io
import json
import os
from pathlib import Path
import re
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
            + b''.join(b'<uses-permission android:name="' + permission.encode() + b'"/>'
                       for permission in sorted(tool.SERVER_PERMISSIONS)) +
            b'<application android:allowBackup="false" android:usesCleartextTraffic="true">'
            b'<activity android:name=".MainActivity" android:exported="true"/>'
            b'<service android:name=".ServerService" android:exported="false"/>'
            + raw + b'</application></manifest>')


def test_generated_manifest_preserves_source_policy_and_required_merged_flags():
    root = ET.fromstring(tool.manifest_xml(manifest()))
    assert root.attrib == {"package": tool.PACKAGE, tool.ANDROID + "versionCode": "43",
                           tool.ANDROID + "versionName": "0.3.24"}
    assert root.find("uses-sdk").attrib == {tool.ANDROID + "minSdkVersion": "26",
                                           tool.ANDROID + "targetSdkVersion": "34"}
    app = root.find("application")
    assert app.get(tool.ANDROID + "allowBackup") == "false"
    assert app.get(tool.ANDROID + "usesCleartextTraffic") == "true"
    assert app.get(tool.ANDROID + "extractNativeLibs") == "true"
    assert app.get(tool.ANDROID + "debuggable") == "false"
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


@pytest.mark.parametrize("change", ["missing-permission", "installer-permission", "sdk-permission", "duplicate-permission"])
def test_release_manifest_rejects_installation_or_unexpected_permission_inventory(change):
    raw = manifest()
    if change == "missing-permission":
        raw = raw.replace(b'<uses-permission android:name="android.permission.INTERNET"/>', b'')
    else:
        name = "android.permission.REQUEST_INSTALL_PACKAGES" if change == "installer-permission" else "android.permission.INTERNET"
        tag = "uses-permission-sdk-23" if change == "sdk-permission" else "uses-permission"
        raw = raw.replace(b'<application', ('<' + tag + ' android:name="' + name + '"/><application').encode(), 1)
    with pytest.raises(ValueError, match="permission"):
        tool.manifest_xml(raw)


@pytest.mark.parametrize("extra", [b'<activity android:name=".PresentationInstallActivity" android:exported="false"/>',
                                   b'<service android:name=".Other" android:exported="false"/>'])
def test_release_manifest_rejects_old_installer_callback_or_extra_components(extra):
    with pytest.raises(ValueError, match="component inventory"):
        tool.manifest_xml(manifest(extra))


@pytest.mark.parametrize("name,old,new", [(b"MainActivity", b"true", b"false"),
                                           (b"ServerService", b"false", b"true")])
def test_release_component_export_policy_is_fixed(name, old, new):
    raw = manifest().replace(b'name=".' + name + b'" android:exported="' + old + b'"',
                             b'name=".' + name + b'" android:exported="' + new + b'"')
    with pytest.raises(ValueError, match="export policy"):
        tool.manifest_xml(raw)


def test_build_config_binds_new_version_and_exact_payload_hash():
    raw = tool.build_config("a" * 64).decode()
    assert 'VERSION_CODE = 43;' in raw and 'VERSION_NAME = "0.3.24";' in raw
    assert 'DEBUG = Boolean.parseBoolean("false");' in raw and 'BUILD_TYPE = "release";' in raw
    assert 'SERVER_DATA_SHA256 = "' + "a" * 64 + '";' in raw
    with pytest.raises(ValueError):
        tool.build_config('"; injected')


def test_frozen_source_ignores_worktree_and_requires_exact_inventory(tmp_path, monkeypatch):
    expected = {name: b"committed public source" for name in tool.SOURCE_FILES}
    expected[tool.GRADLE] = b'gradleProperty("serverVersionCode").orElse("43")\ngradleProperty("serverVersionName").orElse("0.3.24")'
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
    names = ("tools/build_android_server_manual.py", "tools/repack_android_server_python.py",
             tool.PAYLOAD_INVENTORY,
             "src/idoly_local/media_master_build.py", "src/idoly_local/media_outfit_policy.py")
    frozen = {name: (root / name).read_bytes() for name in names}
    def git(_root, *args, limit):
        return frozen[args[2].split(":", 1)[1]]
    monkeypatch.setattr(tool.pybundle, "_git", git)
    assert tool.tool_sources(root, "a" * 40) == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in frozen.items()}
    frozen[names[0]] = b"different builder source at declared commit"
    with pytest.raises(ValueError, match="differs from the frozen source"):
        tool.tool_sources(root, "a" * 40)


def test_versioned_catalog_inventory_keeps_exact_source_and_platform_boundaries():
    value = tool.load_payload_inventory()
    assert len(value["additions"]) == 260 and len(value["ios_public_files"]) == 2
    assert value["base_payload"] == tool.BASE_PUBLIC_PAYLOAD
    assert value["prebuilt_catalogs"]["device_verified"] is False
    assert len({row["path"] for row in value["additions"] + value["ios_public_files"]}) == 262


@pytest.mark.parametrize("change", ["base", "duplicate", "private", "size", "digest", "ios", "extra", "device"])
def test_versioned_catalog_inventory_rejects_unapproved_or_inconsistent_rows(tmp_path, change):
    value = tool.load_payload_inventory()
    if change == "base": value["base_payload"]["sha256"] = "0" * 64
    elif change == "duplicate": value["additions"][1] = value["additions"][0]
    elif change == "private": value["additions"][0]["path"] = "data/state.db"
    elif change == "size": value["additions"][0]["bytes"] = tool.MAX_JSON + 1
    elif change == "digest": value["additions"][0]["sha256"] = "0" * 64
    elif change == "ios": value["ios_public_files"][0]["path"] = "data/public-octo/settings.json"
    elif change == "extra": value["unexpected"] = True
    else: value["prebuilt_catalogs"]["device_verified"] = True
    path = tmp_path / "catalogs.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="catalog"):
        tool.load_payload_inventory(path)


def test_commit_epoch_accepts_the_actual_git_bytes_return_type():
    assert tool.validate_epoch(b"1794415775", 1794415775) is None


@pytest.mark.parametrize("raw", [b"", b"-1", b"1.5", b"1\n2", b" 1794415775", b"1794415775\n",
                                  b"not-a-timestamp", "1794415775", None])
def test_commit_epoch_rejects_malformed_git_bytes(raw):
    with pytest.raises(ValueError, match="Epoch must match"):
        tool.validate_epoch(raw, 1794415775)


@pytest.mark.parametrize("expected", [1794415774, "1794415775", True])
def test_commit_epoch_rejects_mismatched_or_non_integer_expected_value(expected):
    with pytest.raises(ValueError, match="Epoch must match"):
        tool.validate_epoch(b"1794415775", expected)


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
def payload_case(tmp_path, monkeypatch):
    from test_media_master_build import original_tag, original_rows, media_tag
    old = {f"data/master-json/Table{index:02}.json": b'[{"id":"public"}]' for index in range(37)}
    rows = original_rows()
    old.update({"data/master-json/" + table + ".json": json.dumps(rows[table]).encode()
                for table in ("Costume", "Hair", "EventStory")})
    old["data/protocol/idolypride-6.1.1.pb"] = b"synthetic public descriptor"
    old["data/master-json/!version.txt"] = b"synthetic-public"
    tag = original_tag()
    old["data/original-master/master-tag.json"] = json.dumps(tag).encode()
    type_name = next(x["fileName"] for x in tag["masterTagPacks"] if x["type"] == "CostumeType")
    old["data/original-master/assets/master/" + type_name] = b"synthetic original CostumeType pack"
    monkeypatch.setattr(tool.media_master, "COSTUME_TYPE_PACK_SHA256", hashlib.sha256(
        old["data/original-master/assets/master/" + type_name]).hexdigest())
    new = {**old, **{"data/master-json/" + name + ".json": b'[{"id":"new-public"}]' for name in tool.EXTRA_TABLES}}
    for table, values in rows.items():
        new["data/master-json/" + table + ".json"] = json.dumps(values).encode()
    monkeypatch.setattr(tool, "ADDED_JSON_SHA256", {table: hashlib.sha256(
        new["data/master-json/" + table + ".json"]).hexdigest() for table in tool.EXTRA_TABLES})
    proofs = {name: {"bytes": 4096, "sha256": hashlib.sha256(b"x" * 4096).hexdigest()}
              for name in tool.media_master.PACK_NAMES.values()}
    new[tool.media_master.TAG_MEMBER] = json.dumps(media_tag(tag, rows, proofs)).encode()
    new.update({member: b"x" * 4096 for member in tool.media_master.PACK_MEMBERS.values()})
    baseline = tmp_path / "baseline.apk"
    baseline.write_bytes(zip_bytes({tool.pybundle.PAYLOAD: zip_bytes(public_payload(old))}))
    payload = tmp_path / "public.zip"
    def write(files=None):
        payload.write_bytes(zip_bytes(public_payload(new if files is None else files)))
        return tool.pybundle.digest(payload)
    return baseline, payload, new, write


def test_payload_extends_only_fourteen_public_tables_and_verifies_actual_file_provenance(payload_case):
    baseline, payload, _files, write = payload_case
    digest = write()
    with ZipFile(baseline) as archive:
        report = tool.validate_payload(payload, digest, archive)
    assert len(report["tables"]) == 54 and report["sha256"] == digest


@pytest.mark.parametrize("change", [None, "changed-catalog", "changed-proof", "extra-provenance"])
def test_versioned_payload_catalog_is_bound_to_external_frozen_inventory(payload_case, change):
    baseline, payload, files, _write = payload_case
    inventory = tool.load_payload_inventory()
    for row in inventory["additions"] + inventory["ios_public_files"]:
        raw = ("synthetic original public catalog " + row["path"]).encode()
        files[row["path"]] = raw
        row["bytes"], row["sha256"] = len(raw), hashlib.sha256(raw).hexdigest()
    if change == "changed-catalog":
        files[inventory["additions"][0]["path"]] += b" changed after source freeze"
    members = public_payload(files)
    proof = json.loads(members[tool.PAYLOAD_MANIFEST])
    proof["prebuilt_catalogs"] = copy.deepcopy(inventory["prebuilt_catalogs"])
    if change == "changed-proof": proof["prebuilt_catalogs"]["scope"] = ["unapproved claim"]
    if change == "extra-provenance": proof["private_state"] = "must never be allowed"
    members[tool.PAYLOAD_MANIFEST] = json.dumps(proof).encode()
    payload.write_bytes(zip_bytes(members))
    with ZipFile(baseline) as archive:
        if change:
            with pytest.raises(ValueError, match="catalog|provenance"):
                tool.validate_payload(payload, tool.pybundle.digest(payload), archive, catalog_inventory=inventory)
        else:
            report = tool.validate_payload(payload, tool.pybundle.digest(payload), archive, catalog_inventory=inventory)
            assert report["prebuilt_catalogs"] == inventory["prebuilt_catalogs"]
            assert report["members"] == len(files) + 1


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


@pytest.mark.parametrize("table", ["CompanyGrade", "CompanyTrustLevel", "CompanyEnjoyCharacterLevel",
                                   "CompanyEnjoyCharacterLevelSetting"])
def test_company_menu_public_tables_must_all_exist_and_be_nonempty(payload_case, table):
    baseline, payload, original, write = payload_case
    for empty in (False, True):
        files = dict(original)
        if empty:
            files["data/master-json/" + table + ".json"] = b"[]"
        else:
            files.pop("data/master-json/" + table + ".json")
        digest = write(files)
        with ZipFile(baseline) as archive, pytest.raises(ValueError):
            tool.validate_payload(payload, digest, archive)


@pytest.mark.parametrize("change", ["missing-tag", "missing-pack", "extra-pack", "version", "unrelated-pack", "photo-default"])
def test_media_master_overlay_members_and_original_constraints_are_strict(payload_case, change):
    baseline, payload, original, write = payload_case
    files = dict(original)
    if change == "missing-tag":
        files.pop(tool.media_master.TAG_MEMBER)
    elif change == "missing-pack":
        files.pop(next(iter(tool.media_master.PACK_MEMBERS.values())))
    elif change == "extra-pack":
        files["data/original-master/assets/master/media-unapproved.db"] = b"x" * 4096
    elif change in ("version", "unrelated-pack"):
        tag = json.loads(files[tool.media_master.TAG_MEMBER])
        if change == "version": tag["version"] += "altered"
        else: tag["masterTagPacks"][-1]["downloadUrl"] += "altered"
        files[tool.media_master.TAG_MEMBER] = json.dumps(tag).encode()
    else:
        name = "data/master-json/PhotoActivity.json"
        rows = json.loads(files[name])
        rows[0]["forceCostumeTypeId"] = ""
        files[name] = json.dumps(rows).encode()
    digest = write(files)
    with ZipFile(baseline) as archive, pytest.raises(ValueError):
        tool.validate_payload(payload, digest, archive)


def test_approved_payload_hash_rejects_changed_encrypted_overlay_bytes(payload_case):
    baseline, payload, files, write = payload_case
    approved = write()
    changed = dict(files)
    changed[next(iter(tool.media_master.PACK_MEMBERS.values()))] = b"z" * 4096
    write(changed)
    with ZipFile(baseline) as archive, pytest.raises(ValueError, match="hash differs"):
        tool.validate_payload(payload, approved, archive)


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


def test_real_d8_init_class_descriptor_hyphen_is_valid_without_accepting_bad_names():
    name = "L" + tool.PACKAGE.replace(".", "/") + "/PresentationAddonInstaller$Attempt-IA;"
    assert tool.dex_classes(synthetic_dex([name])) == {name}
    for invalid in (name.replace("-IA", " bad"), name.replace("-IA", "*"), name.replace("-IA", ".bad")):
        with pytest.raises(ValueError, match="class names"):
            tool.dex_classes(synthetic_dex([invalid]))


@pytest.mark.parametrize("suffix", ["-IA;", "$$ExternalSyntheticLambda0;", "$$ExternalSyntheticApiModelOutline12;"])
def test_d8_synthetic_requires_exact_compiled_own_origin(suffix):
    origin = "L" + tool.PACKAGE.replace(".", "/") + "/PresentationAddonInstaller$Attempt"
    assert tool.own_synthetic(origin + suffix, {origin + ";"})
    assert not tool.own_synthetic(origin + suffix, set())
    foreign = origin.replace("/localserver/", "/foreign/")
    assert not tool.own_synthetic(foreign + suffix, {foreign + ";"})


@pytest.mark.parametrize("suffix", ["-CC;", "-IAextra;", "$$ExternalSyntheticBackport0;",
                                     "$$ExternalSyntheticLambda;", "$$ExternalSyntheticLambda0;extra"])
def test_unknown_d8_synthetic_kinds_or_malformed_suffixes_remain_rejected(suffix):
    origin = "L" + tool.PACKAGE.replace(".", "/") + "/PresentationAddonInstaller$Attempt"
    assert not tool.own_synthetic(origin + suffix, {origin + ";"})


def test_only_nine_server_sources_are_frozen_without_installer_or_client_builder():
    assert len(tool.JAVA_FILES) == 9
    assert {Path(name).stem for name in tool.JAVA_FILES} == {
        "MainActivity", "ServerService", "CryptoBridge", "PresentationSettings", "PlaybackSettings", "PlaybackStorage",
        "RenderingExperiment", "LibrarySettings", "ResourceTransfers"}
    assert not any("Installer" in name or "PresentationStorage" in name for name in tool.SOURCE_FILES)
    assert not hasattr(tool, "presentation")
    assert not hasattr(tool, "presentation_assets")


def test_gradle_python_exclusions_match_the_manual_server_dependency_boundary():
    gradle = (Path(tool.__file__).resolve().parents[1] / tool.GRADLE).read_text()
    excluded_paths = re.findall(r'"(idoly_local/[^"\n]+\.py)"', gradle)
    expected = {name.replace(".", "/") + ".py" for name in tool.pybundle.ANDROID_EXCLUDED_MODULES}
    assert len(excluded_paths) == len(expected) == 26
    assert set(excluded_paths) == expected


@pytest.mark.parametrize("legacy", [False, True])
def test_streaming_excludes_old_client_apks_without_accepting_new_assets(tmp_path, legacy):
    baseline, target = tmp_path / "baseline.apk", tmp_path / "server.apk"
    files = {"classes.dex": b"runtime", "classes2.dex": b"old own", "classes3.dex": b"old app"}
    if legacy:
        files.update({name: b"old client installation asset" for name in tool.LEGACY_PRESENTATION_ASSETS})
    baseline.write_bytes(zip_bytes(files))
    with ZipFile(baseline) as archive:
        infos = tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED)
        tool.stream_apk(archive, infos, target, {"classes2.dex": b"new server only"})
    with ZipFile(target) as archive:
        assert set(archive.namelist()) == {"classes.dex", "classes2.dex"}
    with ZipFile(baseline) as archive, pytest.raises(ValueError, match="existing approved server"):
        tool.stream_apk(archive, infos, tmp_path / "invalid.apk", {"assets/client.apk": b"new executable"})
    assert not (tmp_path / "invalid.apk").exists()


@pytest.mark.parametrize("name", ["assets/client.apk", "assets/presentation/extra.json"])
def test_unapproved_embedded_apk_or_presentation_asset_in_baseline_is_rejected(tmp_path, name):
    baseline = tmp_path / "baseline.apk"
    baseline.write_bytes(zip_bytes({"classes.dex": b"runtime", name: b"unapproved"}))
    with ZipFile(baseline) as archive, pytest.raises(ValueError, match="must not embed"):
        infos = tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED)
        tool.stream_apk(archive, infos, tmp_path / "invalid.apk", {})
    assert not (tmp_path / "invalid.apk").exists()


def linked_identity():
    badging = (f"package: name='{tool.PACKAGE}' versionCode='43' versionName='0.3.24'\n"
               "sdkVersion:'26'\ntargetSdkVersion:'34'\nnative-code: 'arm64-v8a'\n"
               + "".join("uses-permission: name='" + name + "'\n" for name in sorted(tool.SERVER_PERMISSIONS)))
    manifest_dump = ("A: android:extractNativeLibs(0x1)=true\nA: android:debuggable(0x2)=false\n"
                     "A: android:allowBackup(0x3)=false\n")
    return badging, manifest_dump


def test_linked_identity_requires_release_and_no_install_permission_or_callback():
    badging, manifest_dump = linked_identity()
    tool._identity(badging, manifest_dump)
    with pytest.raises(ValueError, match="identity"):
        tool._identity(badging.replace("versionCode='43' versionName='0.3.24'",
                                      "versionCode='42' versionName='0.3.23'"), manifest_dump)
    with pytest.raises(ValueError, match="identity"):
        tool._identity(badging, manifest_dump.replace("debuggable(0x2)=false", "debuggable(0x2)=true"))
    for forbidden in ("REQUEST_INSTALL_PACKAGES", "PresentationInstallActivity"):
        with pytest.raises(ValueError, match="permission or installer"):
            tool._identity(badging, manifest_dump + forbidden)
    with pytest.raises(ValueError, match="permission or installer"):
        tool._identity(badging + "uses-permission: name='android.permission.REQUEST_INSTALL_PACKAGES'\n", manifest_dump)


@pytest.mark.parametrize("tamper", [None, "classes.dex", "assets/chaquopy/bootstrap.imy"])
@pytest.mark.parametrize("legacy", [False, True])
def test_apk_audit_accepts_only_own_replacements_and_preserves_runtime_dependency_bytes(tmp_path, tamper, legacy):
    dependencies = {f"Lcom/chaquo/python/Type{index};" for index in range(27)}
    own = {"L" + tool.PACKAGE.replace(".", "/") + "/MainActivity;"}
    files = {name: b"old mutable" for name in tool.MUTABLE_NAMES | tool.REMOVED_NAMES}
    files.update({name: synthetic_elf() for name in tool.NATIVE_NAMES})
    files["classes.dex"] = synthetic_dex(sorted(dependencies))
    files["assets/chaquopy/bootstrap.imy"] = b"immutable Python runtime"
    if legacy:
        files.update({name: b"old executable client asset" for name in tool.LEGACY_PRESENTATION_ASSETS})
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
        assert report["removed_apk_members"] == sorted({"classes3.dex"} | (tool.LEGACY_PRESENTATION_ASSETS if legacy else set()))
        assert report["client_installer_code_absent"] and report["embedded_client_apks_absent"]
        assert len(report["native_elf_load_alignments"]) == 9


@pytest.mark.parametrize("token", tool.FORBIDDEN_INSTALLER_DEX_TOKENS)
def test_apk_audit_rejects_retained_installer_references_even_with_approved_own_hash(tmp_path, token):
    dependencies = {"Lcom/chaquo/python/Python;"}
    own = {"L" + tool.PACKAGE.replace(".", "/") + "/MainActivity;"}
    files = {name: b"old mutable" for name in tool.MUTABLE_NAMES | tool.REMOVED_NAMES}
    files.update({name: synthetic_elf() for name in tool.NATIVE_NAMES})
    files["classes.dex"] = synthetic_dex(sorted(dependencies))
    baseline, candidate = tmp_path / "baseline.apk", tmp_path / "candidate.apk"
    baseline.write_bytes(zip_bytes(files))
    own_dex = bytearray(synthetic_dex(sorted(own)))
    own_dex.extend(token + b"\0")
    struct.pack_into("<I", own_dex, 32, len(own_dex))
    own_dex[12:32] = hashlib.sha1(own_dex[32:]).digest()
    struct.pack_into("<I", own_dex, 8, zlib.adler32(own_dex[12:]) & 0xffffffff)
    assert tool.dex_classes(bytes(own_dex)) == own
    replacements = {name: b"new approved input" for name in tool.MUTABLE_NAMES}
    replacements["classes2.dex"] = bytes(own_dex)
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in replacements.items()}
    with ZipFile(baseline) as archive:
        infos = tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED)
        before = tool.pybundle._hash_members(archive, infos)
        tool.stream_apk(archive, infos, candidate, replacements)
    with pytest.raises(ValueError, match="removed client installer code"):
        tool.audit_apk(candidate, before, infos, hashes, dependencies, own)


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


@pytest.fixture
def memory_guard_case(tmp_path, monkeypatch):
    cgroup, processes = tmp_path / "cgroup", tmp_path / "empty-proc"
    cgroup.mkdir()
    processes.mkdir()
    (cgroup / "memory.events").write_text("oom_kill 2\n")
    monkeypatch.setattr(tool, "CGROUP", cgroup)
    monkeypatch.setattr(tool, "Path", lambda value: processes if value == "/proc" else Path(value))
    monkeypatch.setattr(tool.shutil, "disk_usage", lambda _: SimpleNamespace(free=tool.MIN_ROOT_FREE))
    def configure(direct_mib=960, raw=None, **values):
        maximum = 16 * 1024 * tool.MIB
        (cgroup / "memory.max").write_text(str(maximum))
        (cgroup / "memory.current").write_text(str(maximum - direct_mib * tool.MIB))
        defaults = {"file": 512, "shmem": 256, "file_dirty": 0, "file_writeback": 0,
                    "inactive_file": 256, "slab_reclaimable": 1024}
        defaults.update(values)
        path = cgroup / "memory.stat"
        if raw is None:
            raw = "".join(f"{name} {amount * tool.MIB}\n" for name, amount in defaults.items())
        path.write_text(raw)
        return cgroup
    return configure


def test_resource_guard_credits_only_capped_clean_inactive_file_pages(memory_guard_case, tmp_path):
    memory_guard_case(direct_mib=768)
    report = tool._resource_guard(tmp_path)
    assert report["memory_direct_headroom"] == 768 * tool.MIB
    assert report["memory_clean_inactive_credit"] == 256 * tool.MIB
    assert report["memory_effective_headroom"] == tool.MIN_HEADROOM
    assert report["oom_kill"] == "2"
    assert tool.MIN_HEADROOM == 1024 * tool.MIB


def test_resource_guard_subtracts_shmem_dirty_and_writeback_before_credit(memory_guard_case, tmp_path):
    memory_guard_case(direct_mib=980, file=512, shmem=300, file_dirty=96, file_writeback=64,
                      inactive_file=70)
    report = tool._resource_guard(tmp_path)
    assert report["memory_clean_inactive_credit"] == 52 * tool.MIB
    assert report["memory_effective_headroom"] == 1032 * tool.MIB


@pytest.mark.parametrize("direct_mib,values", [
    (767, {}),  # Even abundant clean cache cannot replace the 768 MiB direct floor.
    (768, {"inactive_file": 255}),
    (960, {"inactive_file": 63}),
    (960, {"inactive_file": 0}),
    (960, {"file": 512, "shmem": 512}),
    (960, {"file_dirty": 256}),
    (960, {"file_writeback": 256}),
    (960, {"file": 128, "shmem": 256}),
    (960, {"file": 0, "shmem": 0, "slab_reclaimable": 16384}),
])
def test_resource_guard_rejects_real_shortage_or_nonclean_cache(memory_guard_case, tmp_path, direct_mib, values):
    memory_guard_case(direct_mib=direct_mib, **values)
    with pytest.raises(ValueError, match="1 GiB"):
        tool._resource_guard(tmp_path)


@pytest.mark.parametrize("raw", ["", "file 999999999\n", "file -1\n", "file nan\n",
                                  "file 1\nfile 2\n", "file 1 extra\n", "x" * 65537])
def test_resource_guard_malformed_stats_add_zero_credit(memory_guard_case, tmp_path, raw):
    memory_guard_case(direct_mib=960, raw=raw)
    assert tool._memory_budget()["memory_clean_inactive_credit"] == 0
    with pytest.raises(ValueError, match="1 GiB"):
        tool._resource_guard(tmp_path)
    memory_guard_case(direct_mib=1024, raw=raw)
    assert tool._resource_guard(tmp_path)["memory_effective_headroom"] == tool.MIN_HEADROOM


def test_resource_guard_missing_stats_add_zero_credit(memory_guard_case, tmp_path):
    cgroup = memory_guard_case(direct_mib=960)
    (cgroup / "memory.stat").unlink()
    assert tool._memory_budget()["memory_clean_inactive_credit"] == 0
    with pytest.raises(ValueError, match="1 GiB"):
        tool._resource_guard(tmp_path)


def test_resource_guard_rereads_clean_cache_before_each_tool(memory_guard_case, tmp_path):
    memory_guard_case(direct_mib=960)
    assert tool._resource_guard(tmp_path)["memory_clean_inactive_credit"] == 256 * tool.MIB
    memory_guard_case(direct_mib=960, file_dirty=256)
    with pytest.raises(ValueError, match="1 GiB"):
        tool._resource_guard(tmp_path)


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


def public_cache_case(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-public-input.apk"
    path.write_bytes(b"public synthetic bytes" * 3000)
    path.chmod(0o640)
    expected = tool.pybundle.digest(path)
    monkeypatch.setitem(tool.PUBLIC_INPUT_HASHES, "baseline", expected)
    return path, expected, tool.PublicCacheAdvice()


def test_cache_hint_preserves_public_bytes_mode_mtime_and_uses_readonly_fd(tmp_path, monkeypatch):
    if not hasattr(os, "posix_fadvise"):
        pytest.skip("POSIX cache advice is unavailable")
    path, expected, cache = public_cache_case(tmp_path, monkeypatch)
    before = tool._file_identity(path.stat())
    opened, original_open = [], os.open
    def checked_open(name, flags, *args, **kwargs):
        opened.append(flags)
        assert flags & os.O_ACCMODE == os.O_RDONLY
        assert flags & os.O_NOFOLLOW
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(tool.os, "open", checked_open)
    cache.public("baseline", path, expected)
    cache.advise()
    assert tool._file_identity(path.stat()) == before
    assert tool.pybundle.digest(path) == expected
    assert opened and {event["role"] for event in cache.events} == {"baseline"}


@pytest.mark.parametrize("role", ["keystore", "password", "state.db", "VM-overlay", "other-file"])
def test_private_or_arbitrary_cache_roles_reject_before_open(tmp_path, monkeypatch, role):
    monkeypatch.setattr(tool.os, "open", lambda *a, **k: pytest.fail("must not open private inputs"))
    with pytest.raises(ValueError, match="explicitly pinned public"):
        tool.PublicCacheAdvice().public(role, tmp_path / "private", "a" * 64)


def test_cache_hint_requires_verified_hash_before_advice_and_rejects_symlinks(tmp_path, monkeypatch):
    path, expected, cache = public_cache_case(tmp_path, monkeypatch)
    monkeypatch.setattr(tool.os, "posix_fadvise", lambda *a: pytest.fail("unverified input must not be advised"), raising=False)
    path.write_bytes(b"different public bytes")
    with pytest.raises(ValueError, match="hash differs"):
        cache.public("baseline", path, expected)
    link = tmp_path / "linked-input.apk"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="stable regular"):
        cache.public("baseline", link, expected)
    assert not cache.events


def test_cache_advice_detects_path_replacement_between_lstat_and_open(tmp_path, monkeypatch):
    path, expected, cache = public_cache_case(tmp_path, monkeypatch)
    replacement = tmp_path / "other-public-file.apk"
    replacement.write_bytes(path.read_bytes())
    original_open = os.open
    def replaced(name, flags, *args, **kwargs):
        replacement.replace(path)
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(tool.os, "open", replaced)
    with pytest.raises(ValueError, match="changed while opening"):
        cache.public("baseline", path, expected)
    assert not cache.events


def test_cache_advice_detects_changed_registered_file_without_hinting_new_bytes(tmp_path, monkeypatch):
    path, expected, cache = public_cache_case(tmp_path, monkeypatch)
    monkeypatch.setattr(tool.os, "posix_fadvise", lambda *a: None, raising=False)
    cache.public("baseline", path, expected)
    path.write_bytes(b"changed after verification")
    monkeypatch.setattr(tool.os, "posix_fadvise", lambda *a: pytest.fail("changed file must not be advised"), raising=False)
    with pytest.raises(ValueError, match="stable regular"):
        cache.advise()


def test_only_completed_owned_apk_names_can_be_advised_and_removed_own_file_is_skipped(tmp_path, monkeypatch):
    work = tmp_path / "own-build"
    work.mkdir()
    (work / "unsigned.apk").write_bytes(b"synthetic own completed APK")
    monkeypatch.setattr(tool.os, "posix_fadvise", lambda *a: None, raising=False)
    cache = tool.PublicCacheAdvice()
    cache.own_directory(work)
    cache.completed_apk("unsigned.apk")
    for name in ("../state.db", "password", "unrelated.apk"):
        with pytest.raises(ValueError, match="completed APK"):
            cache.completed_apk(name)
    (work / "unsigned.apk").unlink()
    cache.advise()
    assert {event["role"] for event in cache.events} == {"own-unsigned.apk"}


def test_unsupported_cache_hint_still_runs_the_unchanged_memory_guard_before_spawn(tmp_path, monkeypatch):
    path, expected, cache = public_cache_case(tmp_path, monkeypatch)
    def unsupported(*args): raise OSError(errno.EOPNOTSUPP, "synthetic unsupported hint")
    monkeypatch.setattr(tool.os, "posix_fadvise", unsupported, raising=False)
    cache.public("baseline", path, expected)
    assert cache.events[-1]["result"] == "unsupported"
    order = []
    original_advise = cache.advise
    def advice():
        order.append("advice")
        original_advise()
    cache.advise = advice
    def guard(_root):
        order.append("strict-guard")
        raise ValueError("Defer build until at least 1 GiB cgroup headroom is available")
    monkeypatch.setattr(tool, "_resource_guard", guard)
    monkeypatch.setattr(tool.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn below strict threshold"))
    with pytest.raises(ValueError, match="1 GiB"):
        tool._run(["must-not-run"], root=tmp_path, env={}, cache=cache)
    assert order == ["advice", "strict-guard"]
    assert tool.MIN_HEADROOM == 1024 * 1024 * 1024
