"""Static Octo audit fixtures; no asset fetches, client execution or ABI claims."""
import importlib.util
import io
from pathlib import Path
import struct
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

SPEC = importlib.util.spec_from_file_location("game_resource_cache_audit",
    Path(__file__).resolve().parents[1] / "tools/audit_game_resource_cache.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def fixture(worker="Worker", worker_method="Tick"):
    strings = bytearray(b"\0")
    names = {}
    def name(value):
        if value not in names:
            names[value] = len(strings)
            strings.extend(value.encode() + b"\0")
        return names[value]
    for value in ("Octo.dll", "Qua.dll", "FileCache", worker, "Home",
                  "Octo.Storage", "Octo.Network", "Qua", "GetPath",
                  worker_method, "DeleteFile", "_cacheRoot", "objectName"):
        name(value)
    header = [0] * 64
    header[:2] = [0xFAB11BAF, 31]
    raw = bytearray(256)
    def section(index, data):
        while len(raw) % 4:
            raw.append(0)
        header[index:index + 2] = [len(raw), len(data)]
        raw.extend(data)
    section(6, strings)
    methods = bytearray()
    for index, method_name in enumerate(("GetPath", worker_method, "DeleteFile")):
        row = [name(method_name), index, 5, 0x0800FFFF,
               0 if index == 0 else 0xFFFFFFFF, 0xFFFFFFFF,
               0x06000001 + index, 6, 0, 0, 1 if index == 0 else 0]
        methods.extend(struct.pack("<7I4H", *row))
    section(12, methods)
    section(22, struct.pack("<3I", name("objectName"), 0x08000001, 7))
    section(24, struct.pack("<3I", name("_cacheRoot"), 12, 0x04000001))
    types = bytearray()
    for index, (type_name, namespace) in enumerate((("FileCache", "Octo.Storage"),
                                                   (worker, "Octo.Network"), ("Home", "Qua"))):
        row = [0] * 26
        row[0:3] = [name(type_name), name(namespace), 200 + index]
        row[8], row[9] = (0 if index == 0 else 0xFFFFFFFF), index
        row[16], row[18], row[25] = 1, int(index == 0), 0x02000001 + index
        types.extend(struct.pack("<16I8H2I", *row))
    section(40, types)
    images = struct.pack("<10i", name("Octo.dll"), 0, 0, 2, -1, 0, -1, 1, 0, 0)
    images += struct.pack("<10i", name("Qua.dll"), 1, 2, 1, -1, 0, -1, 2, 0, 0)
    section(42, images)
    struct.pack_into("<64I", raw, 0, *header)
    return bytes(raw), header


def patch_u32(raw, offset, value):
    result = bytearray(raw)
    struct.pack_into("<I", result, offset, value)
    return bytes(result)


def test_v31_parameter_start_four_selected_scope_and_foreign_module():
    raw, _ = fixture()
    result = audit.inspect_metadata(raw)
    assert [row["type"] for row in result["methods"]] == ["Octo.Storage.FileCache"]
    method = result["methods"][0]
    assert method["name"] == "GetPath"
    assert method["parameters"] == [{"name": "objectName", "metadata_type_index": 7, "token": "0x8000001"}]
    assert result["types"][0]["fields"][0]["name"] == "_cacheRoot"
    assert method["return_metadata_type_index"] == 5
    assert not any("Qua" in row["type"] for row in result["methods"])


def test_async_type_and_zero_count_unsigned_sentinels_are_supported():
    raw, _ = fixture("<DownloadAsync>d__0", "MoveNext")
    result = audit.inspect_metadata(raw)
    method = result["methods"][1]
    assert method["name"] == "MoveNext" and method["parameters"] == []
    assert result["types"][1]["fields"] == []


@pytest.mark.parametrize("damage", ["short", "version", "section", "misaligned-table",
    "overlap", "string-index", "no-terminator", "method-owner", "method-token",
    "method-start", "parameter-start", "field-start", "duplicate-octo-image"])
def test_malformed_metadata_never_yields_an_inventory(damage):
    raw, header = fixture()
    if damage == "short":
        raw = raw[:255]
    elif damage == "version":
        raw = patch_u32(raw, 4, 29)
    elif damage == "section":
        raw = patch_u32(raw, 40 * 4, len(raw) + 4)
    elif damage == "misaligned-table":
        raw = patch_u32(raw, 13 * 4, header[13] - 1)
    elif damage == "overlap":
        raw = patch_u32(raw, 40 * 4, header[12])
    elif damage == "string-index":
        raw = patch_u32(raw, header[40], header[7] + 1)
    elif damage == "no-terminator":
        data = bytearray(raw)
        data[header[6]:header[6] + header[7]] = b"x" * header[7]
        raw = bytes(data)
    elif damage == "method-owner":
        raw = patch_u32(raw, header[12] + 4, 99)
    elif damage == "method-token":
        raw = patch_u32(raw, header[12] + 6 * 4, 0x04000001)
    elif damage == "method-start":
        raw = patch_u32(raw, header[40] + 9 * 4, 0xFFFFFFFF)
    elif damage == "parameter-start":
        raw = patch_u32(raw, header[12] + 4 * 4, 0xFFFFFFFF)
    elif damage == "field-start":
        raw = patch_u32(raw, header[40] + 8 * 4, 0xFFFFFFFF)
    elif damage == "duplicate-octo-image":
        raw = patch_u32(raw, header[42] + 40, struct.unpack_from("<I", raw, header[42])[0])
    with pytest.raises(audit.AuditError):
        audit.inspect_metadata(raw)


@pytest.mark.parametrize("limit", ["MAX_SELECTED_METHODS", "MAX_SELECTED_TYPES"])
def test_selected_inventory_cap_is_enforced(monkeypatch, limit):
    monkeypatch.setattr(audit, limit, 0)
    with pytest.raises(audit.AuditError, match="selected_metadata_bound"):
        audit.inspect_metadata(fixture()[0])


def test_wrong_module_namespace_cannot_be_selected():
    raw, header = fixture("FileWorker", "Load")
    assert len(audit.inspect_metadata(raw)["methods"]) == 2
    # A compiler-generated helper can live in Octo.dll without being an Octo type.
    qua_index = struct.unpack_from("<I", raw, header[40] + 2 * 88 + 4)[0]
    raw = patch_u32(raw, header[40] + 88 + 4, qua_index)
    result = audit.inspect_metadata(raw)
    assert len(result["methods"]) == 1


class FakeDisassembler:
    def disasm_lite(self, data, address, count):
        assert count <= audit.MAX_INSTRUCTIONS
        yield address, 4, "ret", ""


class FakeImage:
    def __init__(self, pointer=0x1400):
        self.native = bytes(2048)
        self.disassembler = FakeDisassembler()
        self.pointer = pointer
        self.seen = []
    def file_offset(self, address):
        if not 0x1000 <= address < 0x1800:
            raise ValueError("fixture range")
        return address - 0x1000
    def read_pointer(self, address):
        self.seen.append(address)
        return self.pointer


def test_module_token_row_not_global_metadata_index_controls_native_lookup():
    image = FakeImage()
    method = {"token_row": 611, "metadata_method_index": 197134}
    result = audit.method_window(image, method, 0x2000, 700, [(0x1000, 0x1800)])
    assert image.seen == [0x2000 + 610 * 8]
    assert result["virtual_address"] == "0x1400" and len(result["prefix16"]) == 32
    assert result["function_extent_or_native_abi_verified"] is False


def test_abstract_or_generic_null_pointer_is_reported_without_invention():
    result = audit.method_window(FakeImage(0), {"token_row": 1}, 0x2000, 2, [])
    assert result == {"status": "no_direct_native_pointer"}


@pytest.mark.parametrize("row,pointer,ranges", [(0, 0x1400, [(0x1000, 0x1800)]),
    (8, 0x1400, [(0x1000, 0x1800)]), (1, 0x1401, [(0x1000, 0x1800)]),
    (1, 0x1400, [(0x1000, 0x1200)]), (1, 0x1400, [(0x1000, 0x1800), (0x1400, 0x1800)])])
def test_native_pointer_scope_and_token_boundaries_fail_closed(row, pointer, ranges):
    with pytest.raises(audit.AuditError):
        audit.method_window(FakeImage(pointer), {"token_row": row}, 0x2000, 7, ranges)


def test_entire_instruction_window_must_remain_contiguous_file_backed():
    image = FakeImage()
    original = image.file_offset
    image.file_offset = lambda address: original(address) + (4 if address != 0x1400 else 0)
    with pytest.raises(audit.AuditError, match="native_method_window_bound"):
        audit.method_window(image, {"token_row": 1}, 0x2000, 7, [(0x1000, 0x1800)])


class ModuleImage:
    def __init__(self, ambiguous=False):
        data = bytearray(512)
        data[64:73] = b"Octo.dll\0"
        struct.pack_into("<3Q", data, 0, 0x1040, 7, 0x1100)
        if ambiguous:
            struct.pack_into("<3Q", data, 32, 0x1040, 7, 0x1180)
        self.native = bytes(data)
        self.module_segment = (0, 56 if ambiguous else 24)
    def file_offset(self, address):
        if not 0x1000 <= address < 0x1200:
            raise ValueError("fixture range")
        return address - 0x1000


def test_macho_codegen_module_requires_unique_valid_table():
    assert audit.module_table(ModuleImage(), "ios", 6) == (7, 0x1100)
    with pytest.raises(audit.AuditError, match="octo_codegen_table_missing_or_ambiguous"):
        audit.module_table(ModuleImage(True), "ios", 6)


def elf_fixture():
    data = bytearray(256)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 18, 183)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<II6Q", data, 64, 1, 5, 0, 0x1000, 0, 256, 256, 4096)
    return bytes(data)


def test_executable_ranges_require_actual_arm64_file_backing():
    data = elf_fixture()
    assert audit.executable_ranges(data, "android") == [(0x1000, 0x1100)]
    for bad in (patch_u32(data, 64 + 4, 4), patch_u32(data, 64 + 32, 257)):
        with pytest.raises(audit.AuditError):
            audit.executable_ranges(bad, "android")
    with pytest.raises(audit.AuditError):
        audit.executable_ranges(data, "ios")


def context():
    return {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": audit.REPO,
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123"}


def test_source_and_run_binding_are_explicit():
    assert audit.binding("a" * 40, 123, context(), "a" * 40) == {"source_commit": "a" * 40, "run_id": 123}


@pytest.mark.parametrize("damage", ["checkout", "source", "run", "boolean-run", "repository", "owned-runner"])
def test_wrong_source_run_or_runner_binding_is_rejected(damage):
    environment, source, run, checkout = context(), "a" * 40, 123, "a" * 40
    if damage == "checkout": checkout = "b" * 40
    elif damage == "source": source = "bad"
    elif damage == "run": environment["GITHUB_RUN_ID"] = "456"
    elif damage == "boolean-run": run = True
    elif damage == "repository": environment["GITHUB_REPOSITORY"] = "other/repo"
    elif damage == "owned-runner": environment["GITHUB_ACTIONS"] = "false"
    with pytest.raises(audit.AuditError, match="source_run_binding_invalid"):
        audit.binding(source, run, environment, checkout)


@pytest.mark.parametrize("url", ["http://github.com/a", "https://evil.example/a",
    "https://user:password@github.com/a", "https://github.com:444/a", "https://github.com/a#fragment"])
def test_input_origin_boundary(url):
    with pytest.raises(audit.AuditError, match="asset_origin_invalid"):
        audit.approved_url(url)


def test_report_bound_does_not_emit_an_oversized_dump(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "MAX_REPORT", 8)
    target = tmp_path / "report.json"
    with pytest.raises(audit.AuditError, match="audit_report_bound"):
        audit.write_report(target, {"large": "x" * 20})
    assert not target.exists()


class Response(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class TinyGuard:
    def check(self): pass


def test_asset_redirect_never_forwards_repository_credentials(tmp_path, monkeypatch):
    requests = []
    data = b"PKfixture"
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise HTTPError(request.full_url, 302, "fixture", {"Location": "https://release-assets.githubusercontent.com/fixed"}, None)
            return Response(data)
    monkeypatch.setattr(audit, "build_opener", lambda *_: Opener())
    monkeypatch.setitem(audit.PINS, "android", {"asset_id": 1, "bytes": len(data), "sha256": audit.sha(data)})
    target = tmp_path / "input.zip"
    audit.fetch_asset("android", target, TinyGuard(), "fixture-token")
    assert requests[0].get_header("Authorization") == "Bearer fixture-token"
    assert requests[1].get_header("Authorization") is None
    assert target.read_bytes() == data


def test_asset_complete_size_and_digest_are_required(tmp_path, monkeypatch):
    class Opener:
        def open(self, request, timeout): return Response(b"wrong")
    monkeypatch.setattr(audit, "build_opener", lambda *_: Opener())
    monkeypatch.setitem(audit.PINS, "android", {"asset_id": 1, "bytes": 5, "sha256": "0" * 64})
    with pytest.raises(audit.AuditError, match="asset_sha256_differs"):
        audit.fetch_asset("android", tmp_path / "input.zip", TinyGuard(), "fixture-token")


def test_selected_cap_precedes_parameter_allocation(monkeypatch):
    raw, header = fixture()
    raw = patch_u32(raw, header[12] + 4 * 4, 0xFFFFFFFF)
    monkeypatch.setattr(audit, "MAX_SELECTED_METHODS", 0)
    with pytest.raises(audit.AuditError, match="selected_metadata_bound"):
        audit.inspect_metadata(raw)


@pytest.mark.parametrize("raw", [b"octo-cache", b"assetbundle", b"cache/index.db"])
def test_only_short_static_path_literals_are_displayed(raw):
    assert audit.safe_path_literal(raw) == raw.decode("ascii")


@pytest.mark.parametrize("raw", [b"https://example.com/cache", b"cache?token=abc", b"https:cache.db", b"authorization_cache",
    b"cache/password.dat", b"random dialogue", b"\xffcache", b"cache\npath", b"cache/" + b"x" * 260])
def test_path_literal_filter_excludes_urls_queries_credentials_and_unbounded_text(raw):
    assert audit.safe_path_literal(raw) is None


def detailed_instruction(mnemonic, operands, address, writes=()):
    return SimpleNamespace(mnemonic=mnemonic, operands=operands, address=address,
                           regs_access=lambda: ([], list(writes)))


def test_original_encoded_literal_slot_has_actual_instruction_and_slot_addresses():
    arm64 = SimpleNamespace(ARM64_OP_REG=1, ARM64_OP_IMM=2, ARM64_OP_MEM=3)
    reg = lambda value: SimpleNamespace(type=1, reg=value)
    imm = lambda value: SimpleNamespace(type=2, imm=value)
    mem = lambda base: SimpleNamespace(type=3, mem=SimpleNamespace(base=base, disp=0, index=0))
    sequence = [
        detailed_instruction("adrp", [reg(1), imm(0x1000)], 0x1400, [1]),
        detailed_instruction("add", [reg(1), reg(1), imm(0x80)], 0x1404, [1]),
        detailed_instruction("ldr", [reg(2), mem(1)], 0x1408, [2]),
        detailed_instruction("ret", [], 0x140C),
    ]
    class DetailedCS:
        def reg_name(self, number): return "x" + str(number)
        def disasm(self, data, address, count): return iter(sequence)
    image = SimpleNamespace(disassembler=DetailedCS(), literals={1: b"octo-cache"},
                            read_pointer=lambda slot: 0xA0000003 if slot == 0x1080 else 0)
    result = audit.literal_references(image, bytes(256), 0x1400, arm64)
    assert result == [{"instruction_virtual_address": "0x1408",
        "pointer_slot_virtual_address": "0x1080", "metadata_literal_index": 1,
        "literal": "octo-cache", "literal_sha256": audit.sha(b"octo-cache")}]
    for call in ("bl", "blr"):
        sequence.insert(2, detailed_instruction(call, [], 0x1406))
        assert audit.literal_references(image, bytes(256), 0x1400, arm64) == []
        sequence.pop(2)


@pytest.mark.parametrize("narrow", ["mov", "ldr"])
def test_32bit_register_operations_cannot_preserve_a_64bit_literal_pointer(narrow):
    arm64 = SimpleNamespace(ARM64_OP_REG=1, ARM64_OP_IMM=2, ARM64_OP_MEM=3)
    reg = lambda value: SimpleNamespace(type=1, reg=value)
    imm = lambda value: SimpleNamespace(type=2, imm=value)
    mem = lambda base: SimpleNamespace(type=3, mem=SimpleNamespace(base=base, disp=0, index=0))
    sequence = [detailed_instruction("adrp", [reg(1), imm(0x100001000)], 0x1400, [1])]
    if narrow == "mov":
        sequence += [detailed_instruction("mov", [reg(103), reg(101)], 0x1404, [103]),
                     detailed_instruction("ldr", [reg(2), mem(3)], 0x1408, [2])]
    else:
        sequence += [detailed_instruction("ldr", [reg(102), mem(1)], 0x1404, [102])]
    class DetailedCS:
        def reg_name(self, number):
            return ("w" + str(number - 100)) if number >= 100 else ("x" + str(number))
        def disasm(self, data, address, count): return iter(sequence)
    image = SimpleNamespace(disassembler=DetailedCS(), literals={1: b"octo-cache"},
                            read_pointer=lambda slot: 0xA0000003)
    assert audit.literal_references(image, bytes(256), 0x1400, arm64) == []


def summary_fixture():
    pin = audit.PINS["android"]
    return {"platform": "android", "archive": {key: pin[key] for key in ("asset_id", "bytes", "sha256")},
        "metadata_sha256": pin["metadata"], "native_sha256": pin["native"],
        "native_abi_verified": False, "storage_layout_verified": False,
        "transformation_behavior_verified": False, "direct_file_reuse_implemented": False,
        "game_code_executed": False,
        "inventory": {"methods": [{"type": "Octo.Storage.FileCache", "name": "GetPath" + str(index),
            "native": {"path_literal_references": [{"literal": "cache/" + str(index) + ".db"}]}}
            for index in range(40)]}}


def test_public_job_summary_uses_validated_short_names_and_whitelisted_literals_only():
    result = audit.public_summary(summary_fixture(), "a" * 40, 123)
    assert len(result["storage_cache_path_methods"]) == 24
    assert len(result["whitelisted_path_literals"]) == 16
    assert result["selected_method_count"] == 40
    assert result["native_abi_verified"] is False and result["direct_file_reuse_implemented"] is False
    assert result["source_commit"] == "a" * 40 and result["run_id"] == 123


@pytest.mark.parametrize("damage", ["url", "pin", "claim", "binding", "cap"])
def test_public_summary_cannot_expand_scope_or_expose_unvalidated_text(damage, monkeypatch):
    value, source, run = summary_fixture(), "a" * 40, 123
    if damage == "url":
        value["inventory"]["methods"][0]["native"]["path_literal_references"][0]["literal"] = "https:cache.db"
    elif damage == "pin": value["native_sha256"] = "0" * 64
    elif damage == "claim": value["direct_file_reuse_implemented"] = True
    elif damage == "binding": run = True
    elif damage == "cap": monkeypatch.setattr(audit, "MAX_SUMMARY", 8)
    with pytest.raises(audit.AuditError):
        audit.public_summary(value, source, run)
