import importlib.util
from pathlib import Path
import struct
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from idoly_local.client_patch import literal_rows


spec = importlib.util.spec_from_file_location(
    "octo_origin_tool", Path(__file__).resolve().parents[1] / "tools/patch_android_octo_origin.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def fixture(*, slot=tool.LITERAL_INDEX, duplicate=False, overlap=False):
    strings = [b"unchanged"] * (tool.LITERAL_INDEX + 2)
    strings[slot] = tool.ORIGINAL_ORIGIN
    if duplicate:
        strings[slot - 1] = tool.ORIGINAL_ORIGIN
    table_size = len(strings) * 8
    pool_start = 256 + table_size
    rows, pool = bytearray(), bytearray()
    for value in strings:
        rows += struct.pack("<II", len(value), len(pool))
        pool += value
    if overlap:
        origin_index = struct.unpack_from("<II", rows, slot * 8)[1]
        struct.pack_into("<II", rows, (slot + 1) * 8, 4, origin_index + 2)
    gap = b"\0" * (-(pool_start + len(pool)) % 8)
    tail = b"native-independent later metadata section\xff\x13"
    header = [0] * 64
    header[:8] = [0xFAB11BAF, 31, 256, table_size, pool_start, len(pool),
                  pool_start + len(pool) + len(gap), len(tail)]
    return struct.pack("<64I", *header) + rows + pool + gap + tail


@pytest.mark.parametrize("origin", [tool.DEFAULT_ORIGIN, "http://127.0.0.1:8082/", "http://127.0.0.1:65535"])
def test_exact_original_slot_patch_preserves_every_other_byte(origin):
    before = fixture()
    old_header, old_rows = literal_rows(before)
    after, report = tool.patch_octo_metadata(before, origin)
    header, rows = literal_rows(after)
    assert header == old_header
    assert len(after) == len(before)
    assert rows[tool.LITERAL_INDEX][3] == tool.normalize_origin(origin).encode()
    assert all(a[3] == b[3] for a, b in zip(old_rows, rows) if a[0] != tool.LITERAL_INDEX)
    row = old_rows[tool.LITERAL_INDEX]
    start = old_header[4] + row[2]
    allowed = set(range(row[1], row[1] + 4)) | set(range(start, start + len(row[3])))
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(before, after)))
    assert after[header[6]:] == before[old_header[6]:]
    assert report["all_other_literals_and_sections_unchanged"]


@pytest.mark.parametrize("options", [{"slot": tool.LITERAL_INDEX - 1}, {"duplicate": True}, {"overlap": True}])
def test_wrong_slot_duplicate_and_shared_allocation_fail_closed(options):
    with pytest.raises(ValueError, match="literal|overlap"):
        tool.patch_octo_metadata(fixture(**options))


@pytest.mark.parametrize("origin", ["http://localhost:8080/", "https://127.0.0.1:8080/",
    "http://127.0.0.1/", "http://127.0.0.1:0/", "http://127.0.0.1:65536/",
    "http://user:pass@127.0.0.1:8080/", "http://127.0.0.1:8080/path",
    "http://127.0.0.1:8080/?x=1", "http://127.0.0.1:8080/#x", "http://127.0.0.1:8080/\n", None])
def test_only_explicit_loopback_http_origin_allowed(origin):
    with pytest.raises(ValueError):
        tool.normalize_origin(origin)


def test_corrupt_literal_and_repatch_rejected():
    before = fixture()
    broken = bytearray(before)
    struct.pack_into("<I", broken, 256 + tool.LITERAL_INDEX * 8 + 4, 0xFFFFFFF0)
    with pytest.raises(ValueError):
        tool.patch_octo_metadata(bytes(broken))
    after, _ = tool.patch_octo_metadata(before)
    with pytest.raises(ValueError):
        tool.patch_octo_metadata(after)


def test_stream_repack_preserves_native_dex_manifest_sdk_marker_and_licenses(tmp_path):
    source, output = tmp_path / "input.apk", tmp_path / "output.apk"
    before = fixture()
    members = {tool.METADATA: before, "AndroidManifest.xml": b"manifest bytes",
        "classes.dex": b"real SDK code retained", "lib/arm64-v8a/libil2cpp.so": b"native code retained",
        "assets/idoly-qa-ui.json": b"existing observer provenance",
        "META-INF/library.kotlin_module": b"license metadata", "META-INF/OLD.SF": b"signature"}
    with ZipFile(source, "w", compression=ZIP_DEFLATED) as z:
        for name, raw in members.items():
            z.writestr(name, raw)
    after, _ = tool.patch_octo_metadata(before)
    tool.repack(source, output, after)
    with ZipFile(output) as z:
        assert z.read(tool.METADATA) == after
        assert "META-INF/OLD.SF" not in z.namelist()
        for name, raw in members.items():
            if name != tool.METADATA and not tool.signature_member(name):
                assert z.read(name) == raw
    with ZipFile(source) as z:
        assert z.read(tool.METADATA) == before


def test_public_and_qa_inputs_have_distinct_signing_identity():
    profiles = list(tool.PROFILES.values())
    assert {x["qa_only"] for x in profiles} == {True, False}
    assert len({x["signer"] for x in profiles}) == 2


def test_unknown_source_fails_before_key_access_or_output_creation(tmp_path):
    source = tmp_path / "unknown.apk"
    source.write_bytes(b"unsupported APK")
    output = tmp_path / "new-directory/output.apk"
    with pytest.raises(ValueError, match="pinned normal-local"):
        tool.package(source, output, keystore=tmp_path / "absent-private-key",
                     alias="alias", build_tools=tmp_path, java=tmp_path / "absent-java")
    assert not output.parent.exists()
    assert source.read_bytes() == b"unsupported APK"


def test_wrong_signer_fails_even_if_apk_signature_is_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_run", lambda *args: SimpleNamespace(
        stdout="Signer #1 certificate SHA-256 digest: " + "0" * 64 + "\n"))
    expected = next(x["signer"] for x in tool.PROFILES.values() if x["qa_only"])
    with pytest.raises(ValueError, match="certificate differs"):
        tool.verify_signer([], tmp_path / "candidate.apk", expected, {})
