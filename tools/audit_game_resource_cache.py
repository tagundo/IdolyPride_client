#!/usr/bin/env python3
"""Read only the pinned 6.1.1 Octo metadata and small native instruction windows.

This is a static inventory for a future shared resource store. It neither runs
client code nor changes SDK paths, caches, APKs, IPAs, accounts or release files.
Raw metadata type indices are not native ABI declarations.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import stat
import struct
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
REPO = "tagundo/IdolyPride_client"
MIB = 1024 * 1024
PINS = {
    "android": {"asset_id": 725772331, "bytes": 167699540,
        "sha256": "ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36",
        "metadata": "f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e",
        "native": "68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3"},
    "ios": {"asset_id": 725761399, "bytes": 146438450,
        "sha256": "33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848",
        "metadata": "d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda",
        "native": "b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf"},
}
SOURCE_FILES = (
    "tools/audit_game_resource_cache.py",
    "tests/test_game_resource_cache_audit.py",
    ".github/workflows/audit-game-resource-cache.yml",
    "tools/extract_client_schema.py", "tools/extract_ios_schema.py",
    "client-presentation/native/profile.json", "client-presentation/ios/profile.json",
    "pyproject.toml", "uv.lock",
)
HOSTS = frozenset(("api.github.com", "github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com", "github-cloud.githubusercontent.com",
    "github-cloud.s3.amazonaws.com"))
MAX_METADATA = 64 * MIB
MAX_NATIVE = 256 * MIB
MAX_TYPES = 400000
MAX_METHODS = 1000000
MAX_PARAMETERS = 2000000
MAX_IMAGES = 4096
MAX_SELECTED_TYPES = 1024
MAX_SELECTED_METHODS = 2048
MAX_FIELDS_PER_TYPE = 2048
MAX_PARAMETERS_PER_METHOD = 128
MAX_REPORT = 4 * MIB
MAX_SUMMARY = 32 * 1024
WINDOW_BYTES = 256
MAX_INSTRUCTIONS = 64
REPORTED_INSTRUCTIONS = 12
SELECT = re.compile(r"cache|storage|database|path|download|file|resource|asset|"
                    r"decrypt|decompress|uncompress|unpack|checksum|hash|md5|"
                    r"exist|delete|remove|read|write|save|store|octomanager", re.I)


class AuditError(ValueError):
    pass


def need(value, code):
    if not value:
        raise AuditError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    with Path(path).open("rb") as incoming:
        return hashlib.file_digest(incoming, "sha256").hexdigest()


def table(raw, header, offset_index, stride, maximum):
    offset, size = header[offset_index:offset_index + 2]
    need(size % stride == 0 and size // stride <= maximum, "metadata_table_bound")
    need((not size and offset <= len(raw)) or
         256 <= offset <= len(raw) and size <= len(raw) - offset, "metadata_table_bound")
    return offset, size // stride


def metadata_string(raw, header, index):
    start, size = header[6:8]
    need(type(index) is int and 0 <= index < size, "metadata_string_bound")
    begin = start + index
    end = raw.find(b"\0", begin, min(start + size, begin + 513))
    need(end >= begin, "metadata_string_bound")
    try:
        value = raw[begin:end].decode("utf-8")
    except UnicodeError:
        raise AuditError("metadata_string_encoding") from None
    need(all(c.isprintable() for c in value), "metadata_string_encoding")
    return value


def selected_name(type_name, method_name):
    return SELECT.search(type_name) is not None or SELECT.search(method_name) is not None


def inspect_metadata(raw):
    need(type(raw) is bytes and 256 <= len(raw) <= MAX_METADATA, "metadata_size_bound")
    header = struct.unpack_from("<64I", raw)
    need(header[:2] == (0xFAB11BAF, 31), "metadata_version_differs")
    for index in range(2, 64, 2):
        offset, size = header[index:index + 2]
        need((not size and offset <= len(raw)) or
             256 <= offset <= len(raw) and size <= len(raw) - offset, "metadata_section_bound")
    image_offset, image_count = table(raw, header, 42, 40, MAX_IMAGES)
    type_offset, type_count = table(raw, header, 40, 88, MAX_TYPES)
    method_offset, method_count = table(raw, header, 12, 36, MAX_METHODS)
    parameter_offset, parameter_count = table(raw, header, 22, 12, MAX_PARAMETERS)
    field_offset, field_count = table(raw, header, 24, 12, MAX_PARAMETERS)
    literal_offset, literal_count = table(raw, header, 2, 8, MAX_METHODS)
    for cursor in range(literal_offset, literal_offset + literal_count * 8, 8):
        length, index = struct.unpack_from("<II", raw, cursor)
        need(index <= header[5] and length <= header[5] - index, "metadata_literal_bound")
    intervals = sorted((header[i], header[i] + header[i + 1]) for i in (6, 12, 22, 24, 40, 42) if header[i + 1])
    need(all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:])),
         "metadata_sections_overlap")
    images = []
    for cursor in range(image_offset, image_offset + image_count * 40, 40):
        row = struct.unpack_from("<10i", raw, cursor)
        need(0 <= row[2] <= type_count and 0 <= row[3] <= type_count - row[2], "metadata_image_type_bound")
        images.append((metadata_string(raw, header, row[0]), row[2], row[3]))
    octo = [row for row in images if row[0] == "Octo.dll"]
    need(len(octo) == 1, "octo_image_missing_or_duplicate")
    _, first_type, count = octo[0]
    chosen_types, chosen_methods = [], []
    for type_index in range(first_type, first_type + count):
        row = struct.unpack_from("<16I8H2I", raw, type_offset + type_index * 88)
        name = metadata_string(raw, header, row[0])
        namespace = metadata_string(raw, header, row[1])
        if not (namespace == "Octo" or namespace.startswith("Octo.")):
            continue
        method_start, nmethods = row[9], row[16]
        field_start, nfields = row[8], row[18]
        need(nmethods <= 65535 and (not nmethods or
             method_start <= method_count and nmethods <= method_count - method_start), "metadata_method_bound")
        need(nfields <= MAX_FIELDS_PER_TYPE and (not nfields or
             field_start <= field_count and nfields <= field_count - field_start), "metadata_field_bound")
        full_name = namespace + "." + name
        picked = []
        for index in range(method_start, method_start + nmethods):
            method = struct.unpack_from("<7I4H", raw, method_offset + index * 36)
            method_name = metadata_string(raw, header, method[0])
            need(method[1] == type_index and method[6] >> 24 == 6 and method[6] & 0xFFFFFF,
                 "metadata_method_identity")
            if not selected_name(full_name, method_name):
                continue
            need(len(chosen_methods) + len(picked) < MAX_SELECTED_METHODS, "selected_metadata_bound")
            start, nparameters = method[4], method[10]
            need(nparameters <= MAX_PARAMETERS_PER_METHOD and (not nparameters or
                 start <= parameter_count and nparameters <= parameter_count - start), "metadata_parameter_bound")
            parameters = []
            for parameter_index in range(start, start + nparameters):
                parameter = struct.unpack_from("<3I", raw, parameter_offset + parameter_index * 12)
                parameters.append({"name": metadata_string(raw, header, parameter[0]),
                                   "metadata_type_index": parameter[2], "token": hex(parameter[1])})
            item = {"type": full_name, "type_definition_index": type_index,
                "metadata_method_index": index, "name": method_name,
                "token": hex(method[6]), "token_row": method[6] & 0xFFFFFF,
                "flags": method[7], "implementation_flags": method[8],
                "return_metadata_type_index": method[2], "parameters": parameters}
            picked.append(item)
        if not picked and SELECT.search(full_name) is None:
            continue
        need(len(chosen_types) < MAX_SELECTED_TYPES, "selected_metadata_bound")
        fields = []
        for index in range(field_start, field_start + nfields):
            field = struct.unpack_from("<3I", raw, field_offset + index * 12)
            fields.append({"name": metadata_string(raw, header, field[0]),
                           "metadata_type_index": field[1], "token": hex(field[2])})
        chosen_types.append({"name": full_name, "type_definition_index": type_index,
                             "metadata_type_index": row[2], "fields": fields})
        chosen_methods.extend(picked)
        need(len(chosen_types) <= MAX_SELECTED_TYPES and len(chosen_methods) <= MAX_SELECTED_METHODS,
             "selected_metadata_bound")
    need(chosen_methods, "octo_selected_methods_missing")
    return {"metadata_version": 31, "octo_type_count": count, "types": chosen_types, "methods": chosen_methods}


def executable_ranges(native, platform):
    need(type(native) is bytes and 64 <= len(native) <= MAX_NATIVE, "native_size_bound")
    ranges = []
    if platform == "android":
        need(native[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", native, 18)[0] == 183,
             "native_platform_differs")
        offset = struct.unpack_from("<Q", native, 32)[0]
        stride, count = struct.unpack_from("<HH", native, 54)
        need(stride == 56 and 0 < count <= 4096 and 64 <= offset <= len(native)
             and count * stride <= len(native) - offset, "native_header_bound")
        for index in range(count):
            kind, flags, file_offset, address, _, size, _, _ = struct.unpack_from("<II6Q", native, offset + index * stride)
            need(file_offset <= len(native) and size <= len(native) - file_offset, "native_segment_bound")
            if kind == 1 and flags & 1 and size:
                ranges.append((address, address + size))
    elif platform == "ios":
        need(native[:4] == b"\xcf\xfa\xed\xfe" and struct.unpack_from("<I", native, 4)[0] == 0x0100000C,
             "native_platform_differs")
        count, size = struct.unpack_from("<II", native, 16)
        need(0 < count <= 4096 and size <= len(native) - 32, "native_header_bound")
        cursor, end = 32, 32 + size
        for _ in range(count):
            need(cursor + 8 <= end, "native_header_bound")
            kind, length = struct.unpack_from("<II", native, cursor)
            need(length >= 8 and length <= end - cursor, "native_header_bound")
            if kind == 0x19:
                need(length >= 72, "native_segment_bound")
                address, _, file_offset, file_size = struct.unpack_from("<4Q", native, cursor + 24)
                initprot = struct.unpack_from("<I", native, cursor + 60)[0]
                need(file_offset <= len(native) and file_size <= len(native) - file_offset, "native_segment_bound")
                if initprot & 4 and file_size:
                    ranges.append((address, address + file_size))
            elif kind in (0x21, 0x2C):
                need(length >= 20 and struct.unpack_from("<I", native, cursor + 16)[0] == 0,
                     "native_encrypted")
            cursor += length
        need(cursor == end, "native_header_bound")
    else:
        raise AuditError("native_platform_differs")
    need(ranges, "native_executable_segment_missing")
    return ranges


def module_table(image, platform, largest_row):
    native = image.native
    candidates = set()
    if platform == "android":
        locations, cursor = set(), 0
        while True:
            cursor = native.find(b"Octo.dll\0", cursor)
            if cursor < 0:
                break
            need(len(locations) < 32, "codegen_name_bound")
            locations.add(image.virtual_address(cursor))
            cursor += 1
        need(locations, "octo_codegen_module_missing")
        iterator = ((address, image.read_pointer(address + 8), image.read_pointer(address + 16))
                    for address, addend in image.relocations.items() if addend in locations)
    else:
        offset, size = image.module_segment
        need(0 <= offset <= len(native) and 24 <= size <= len(native) - offset and size <= 128 * MIB,
             "codegen_segment_bound")
        iterator = (struct.unpack_from("<3Q", native, cursor) for cursor in range(offset, offset + size - 23, 8))
    for name, count, table_address in iterator:
        if not largest_row <= count <= MAX_METHODS or table_address % 8:
            continue
        try:
            if platform == "ios":
                name_offset = image.file_offset(name)
                if native[name_offset:name_offset + 9] != b"Octo.dll\0":
                    continue
            image.file_offset(table_address)
            image.file_offset(table_address + (count - 1) * 8)
        except (ValueError, struct.error):
            continue
        candidates.add((count, table_address))
    need(len(candidates) == 1, "octo_codegen_table_missing_or_ambiguous")
    return next(iter(candidates))


def safe_path_literal(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= 256:
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeError:
        return None
    if (re.fullmatch(r"[-A-Za-z0-9._/\\]+", text) is None or "://" in text
            or any(c in text for c in "?&=")
            or re.search(r"authorization|credential|password|token|secret|api.?key", text, re.I)):
        return None
    pattern = r"(?:^|[/\\._-])(?:cache|octocache|octo|assetbundles?|resources?|downloads?)(?:[/\\._-]|$)|\.(?:db|bin|dat|cache|tmp)$"
    return text if re.search(pattern, text, re.I) else None


def literal_references(image, data, address, arm64):
    """Same v31 encoded-literal rule as ClientImage.recover; bounded prefix only."""
    if arm64 is None:
        return []
    cs, registers, found, seen = image.disassembler, {}, [], set()
    def register(number):
        name = cs.reg_name(number)
        return "x" + name[1:] if name.startswith("w") else name
    for instruction in cs.disasm(data, address, count=MAX_INSTRUCTIONS):
        operands = instruction.operands
        before = dict(registers)
        for number in instruction.regs_access()[1]:
            registers.pop(register(number), None)
        mnemonic = instruction.mnemonic
        if mnemonic in ("adrp", "adr") and len(operands) == 2 and operands[1].type == arm64.ARM64_OP_IMM:
            registers[register(operands[0].reg)] = operands[1].imm
        elif (mnemonic == "add" and len(operands) == 3 and operands[1].type == arm64.ARM64_OP_REG
                and operands[2].type == arm64.ARM64_OP_IMM
                and not getattr(getattr(operands[2], "shift", None), "value", 0)
                and cs.reg_name(operands[0].reg).startswith("x")
                and cs.reg_name(operands[1].reg).startswith("x")):
            value = before.get(register(operands[1].reg))
            if value is not None:
                registers[register(operands[0].reg)] = value + operands[2].imm
        elif (mnemonic == "mov" and len(operands) == 2 and operands[1].type == arm64.ARM64_OP_REG
              and cs.reg_name(operands[0].reg).startswith("x")
              and cs.reg_name(operands[1].reg).startswith("x")):
            value = before.get(register(operands[1].reg))
            if value is not None:
                registers[register(operands[0].reg)] = value
        elif (mnemonic == "ldr" and len(operands) == 2 and operands[1].type == arm64.ARM64_OP_MEM
              and not operands[1].mem.index
              and cs.reg_name(operands[0].reg).startswith("x")
              and cs.reg_name(operands[1].mem.base).startswith("x")):
            base = before.get(register(operands[1].mem.base))
            if base is not None:
                slot = base + operands[1].mem.disp
                try:
                    value = image.read_pointer(slot)
                except (ValueError, struct.error):
                    value = None
                if value is not None:
                    if 0xA0000000 <= value < 0xC0000000 and value & 1:
                        index = (value & 0x1FFFFFFF) >> 1
                        raw = image.literals.get(index)
                        text = safe_path_literal(raw)
                        identity = index, slot
                        if text is not None and identity not in seen:
                            need(len(found) < 16, "literal_reference_bound")
                            found.append({"instruction_virtual_address": hex(instruction.address),
                                "pointer_slot_virtual_address": hex(slot), "metadata_literal_index": index,
                                "literal": text, "literal_sha256": sha(raw)})
                            seen.add(identity)
                    else:
                        registers[register(operands[0].reg)] = value
        if mnemonic in ("bl", "blr"):
            for index in range(19):
                registers.pop("x" + str(index), None)
        if mnemonic in ("ret", "b", "br"):
            break
    return found


def method_window(image, method, table_address, count, ranges, arm64=None):
    row = method["token_row"]
    need(type(row) is int and 1 <= row <= count, "method_token_outside_codegen")
    address = image.read_pointer(table_address + (row - 1) * 8)
    if address == 0:
        return {"status": "no_direct_native_pointer"}
    need(type(address) is int and address % 4 == 0, "native_method_pointer_invalid")
    containing = [(start, end) for start, end in ranges if start <= address < end]
    need(len(containing) == 1, "native_method_not_executable")
    amount = min(WINDOW_BYTES, containing[0][1] - address)
    amount -= amount % 4
    need(amount >= 4, "native_method_window_bound")
    offset = image.file_offset(address)
    need(offset >= 0 and amount <= len(image.native) - offset
         and image.file_offset(address + amount - 1) == offset + amount - 1,
         "native_method_window_bound")
    data = image.native[offset:offset + amount]
    instructions, targets = [], []
    decoded = 0
    for location, size, mnemonic, operands in image.disassembler.disasm_lite(data, address, count=MAX_INSTRUCTIONS):
        need(size == 4 and address <= location < address + amount and len(mnemonic) <= 32
             and len(operands) <= 256 and all(32 <= ord(c) < 127 for c in mnemonic + operands),
             "native_instruction_bound")
        decoded += 1
        if len(instructions) < REPORTED_INSTRUCTIONS:
            instructions.append({"offset": location - address, "mnemonic": mnemonic, "operands": operands})
        if mnemonic in ("bl", "b") and re.fullmatch(r"#?0x[0-9a-f]+", operands):
            targets.append(operands.removeprefix("#"))
        if mnemonic in ("ret", "b", "br"):
            break
    need(decoded, "native_method_not_decodable")
    return {"status": "static_prefix_only", "virtual_address": hex(address), "file_offset": offset,
        "prefix16": data[:16].hex(), "window_bytes": amount, "window_sha256": sha(data),
        "decoded_instructions": decoded, "instruction_prefix": instructions,
        "path_literal_references": literal_references(image, data, address, arm64),
        "direct_branch_targets": list(dict.fromkeys(targets))[:32],
        "function_extent_or_native_abi_verified": False}


def binding(source, run, environment, checkout):
    need(type(source) is str and re.fullmatch(r"[0-9a-f]{40}", source) is not None
         and type(run) is int and run > 0, "source_run_binding_invalid")
    need(environment.get("GITHUB_ACTIONS") == "true"
         and environment.get("GITHUB_REPOSITORY") == REPO
         and environment.get("GITHUB_SHA") == source
         and environment.get("GITHUB_RUN_ID") == str(run)
         and checkout == source, "source_run_binding_invalid")
    return {"source_commit": source, "run_id": run}


class Guard:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.oom = None
        self.samples = 0
        self.minimum_disk = None
        self.minimum_memory = None
        self.check(entry=True)

    def check(self, entry=False):
        disk = shutil.disk_usage(self.directory).free
        cgroup = Path("/sys/fs/cgroup")
        limit_path, current_path = cgroup / "memory.max", cgroup / "memory.current"
        limit = limit_path.read_text().strip() if limit_path.is_file() else "max"
        if limit.isdigit():
            memory = int(limit) - int(current_path.read_text())
        else:
            values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
            memory = int(values["MemAvailable"].split()[0]) * 1024
        event_path = cgroup / "memory.events"
        if event_path.is_file():
            events = dict(line.split() for line in event_path.read_text().splitlines())
            value = int(events["oom_kill"])
            if self.oom is None:
                self.oom = value
            need(value == self.oom, "audit_oom_baseline_changed")
        need(disk >= (4096 if entry else 1024) * MIB, "audit_disk_floor")
        need(memory >= (2048 if entry else 512) * MIB, "audit_memory_floor")
        self.samples += 1
        self.minimum_disk = disk if self.minimum_disk is None else min(self.minimum_disk, disk)
        self.minimum_memory = memory if self.minimum_memory is None else min(self.minimum_memory, memory)

    def report(self):
        return {"samples": self.samples, "minimum_disk_bytes": self.minimum_disk,
                "minimum_memory_headroom_bytes": self.minimum_memory, "oom_kill_baseline": self.oom}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def approved_url(url):
    parsed = urlsplit(url)
    need(parsed.scheme == "https" and parsed.hostname in HOSTS and parsed.port in (None, 443)
         and not parsed.username and not parsed.password and not parsed.fragment, "asset_origin_invalid")
    return parsed


def fetch_asset(platform, target, guard, token):
    pin = PINS[platform]
    url = "https://api.github.com/repos/" + REPO + "/releases/assets/" + str(pin["asset_id"])
    opener = build_opener(NoRedirect())
    deadline = time.monotonic() + 240
    response = None
    for _ in range(6):
        parsed = approved_url(url)
        headers = {"Accept": "application/octet-stream", "Accept-Encoding": "identity",
                   "User-Agent": "idoly-static-cache-audit"}
        if parsed.hostname == "api.github.com":
            headers["Authorization"] = "Bearer " + token
        try:
            response = opener.open(Request(url, headers=headers), timeout=30)
            break
        except HTTPError as error:
            need(error.code in (301, 302, 303, 307, 308), "asset_http_failure")
            url = error.headers.get("Location", "")
    need(response is not None and response.status == 200, "asset_redirect_bound")
    digest, total = hashlib.sha256(), 0
    with response, Path(target).open("xb") as outgoing:
        while True:
            guard.check()
            need(time.monotonic() < deadline, "asset_total_timeout")
            block = response.read(128 * 1024)
            if not block:
                break
            total += len(block)
            need(total <= pin["bytes"], "asset_size_differs")
            digest.update(block)
            outgoing.write(block)
    need(total == pin["bytes"] and digest.hexdigest() == pin["sha256"], "asset_sha256_differs")
    return {"asset_id": pin["asset_id"], "bytes": total, "sha256": digest.hexdigest()}


def load_helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def audit_platform(platform, path, android_helper, ios_helper, guard):
    pin = PINS[platform]
    need(Path(path).stat().st_size == pin["bytes"] and file_digest(path) == pin["sha256"],
         "original_archive_pin_differs")
    if platform == "android":
        metadata, native, origin = android_helper.read_client(Path(path), None)
    else:
        metadata, native, origin = ios_helper.read_ipa(Path(path))
    guard.check()
    need(sha(metadata) == pin["metadata"] and sha(native) == pin["native"], "original_component_pin_differs")
    inventory = inspect_metadata(metadata)
    ranges = executable_ranges(native, platform)
    image = (android_helper.ClientImage(metadata, native) if platform == "android"
             else ios_helper.MachOClientImage(metadata, native))
    guard.check()
    count, table_address = module_table(image, platform, max(row["token_row"] for row in inventory["methods"]))
    for index, method in enumerate(inventory["methods"]):
        if index % 32 == 0:
            guard.check()
        method["native"] = method_window(image, method, table_address, count, ranges, arm64=android_helper.arm64)
    need(any(row["native"]["status"] == "static_prefix_only" for row in inventory["methods"]),
         "octo_native_evidence_missing")
    result = {"platform": platform, "archive": {"asset_id": pin["asset_id"], "bytes": pin["bytes"], "sha256": pin["sha256"]},
        "metadata_sha256": sha(metadata), "native_sha256": sha(native),
        "codegen_module": "Octo.dll", "codegen_method_count": count, "codegen_table": hex(table_address),
        "inventory": inventory, "source_member_hashes": origin["source_sha256"],
        "native_abi_verified": False, "storage_layout_verified": False,
        "transformation_behavior_verified": False, "direct_file_reuse_implemented": False,
        "game_code_executed": False}
    del image, metadata, native
    gc.collect()
    guard.check()
    return result


def public_summary(platform_result, source, run):
    """Bounded completed-job log evidence when artifact download is unavailable."""
    need(type(source) is str and re.fullmatch(r"[0-9a-f]{40}", source) is not None
         and type(run) is int and run > 0, "public_summary_binding_invalid")
    platform = platform_result.get("platform")
    need(platform in PINS, "public_summary_platform_invalid")
    pin = PINS[platform]
    need(platform_result.get("archive") == {key: pin[key] for key in ("asset_id", "bytes", "sha256")}
         and platform_result.get("metadata_sha256") == pin["metadata"]
         and platform_result.get("native_sha256") == pin["native"], "public_summary_pin_invalid")
    flags = ("native_abi_verified", "storage_layout_verified", "transformation_behavior_verified",
             "direct_file_reuse_implemented", "game_code_executed")
    need(all(platform_result.get(key) is False for key in flags), "public_summary_scope_invalid")
    names, literals = [], []
    for method in platform_result["inventory"]["methods"]:
        type_name, method_name = method["type"], method["name"]
        need(type(type_name) is str and type(method_name) is str and type_name.startswith("Octo.")
             and len(type_name) <= 1025 and len(method_name) <= 512,
             "public_summary_method_invalid")
        qualified = type_name + "." + method_name
        if (re.search(r"storage|cache|path|file", qualified, re.I)
                and len(qualified) <= 768 and len(names) < 24 and qualified not in names):
            names.append(qualified)
        for reference in method.get("native", {}).get("path_literal_references", []):
            text = reference["literal"]
            need(type(text) is str and text.isascii()
                 and safe_path_literal(text.encode("ascii")) == text, "public_summary_literal_invalid")
            if len(literals) < 16 and text not in literals:
                literals.append(text)
    summary = {"idoly_static_cache_summary": 1, "status": "STATIC_PLATFORM_INVENTORY",
        "source_commit": source, "run_id": run, "platform": platform,
        "archive": platform_result["archive"], "metadata_sha256": pin["metadata"], "native_sha256": pin["native"],
        "selected_method_count": len(platform_result["inventory"]["methods"]),
        "storage_cache_path_methods": names, "whitelisted_path_literals": literals,
        **{key: False for key in flags}}
    need(len(json.dumps(summary, ensure_ascii=True, sort_keys=True).encode()) <= MAX_SUMMARY,
         "public_summary_bound")
    return summary


def write_report(path, value):
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    need(len(raw) <= MAX_REPORT, "audit_report_bound")
    path.write_bytes(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    output_ready = False
    stage, guard = "entry", None
    result = {"schema": 1, "status": "FAIL", "scope": "static-original-selected-Octo-methods",
              "game_code_executed": False, "direct_file_reuse_implemented": False}
    try:
        os.umask(0o077)
        need(sys.platform.startswith("linux") and __debug__, "owned_linux_runner_required")
        result.update(binding(args.source_commit, args.run_id, os.environ,
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10).strip()))
        need(subprocess.run(["git", "diff", "--quiet", "--", *SOURCE_FILES], cwd=ROOT, timeout=10).returncode == 0,
             "audit_source_worktree_changed")
        runner = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        for path in (args.work, args.output):
            need(path.is_absolute() and path.parent.resolve(strict=True) == runner
                 and not path.exists() and not path.is_symlink(), "fresh_owned_directory_required")
        need(args.work != args.output, "owned_directories_overlap")
        guard = Guard(runner)
        resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 * MIB, 3 * 1024 * MIB))
        args.work.mkdir(mode=0o700)
        args.output.mkdir(mode=0o700)
        output_ready = True
        result["source_sha256"] = {name: file_digest(ROOT / name) for name in SOURCE_FILES}
        stage = "load_static_helpers"
        sys.path.insert(0, str(ROOT / "tools"))
        android_helper = load_helper("extract_client_schema", ROOT / "tools/extract_client_schema.py")
        ios_helper = load_helper("extract_ios_schema", ROOT / "tools/extract_ios_schema.py")
        result["platforms"] = []
        for platform in ("android", "ios"):
            stage = "fetch_" + platform
            path = args.work / ("original-" + platform + ".zip")
            fetch_asset(platform, path, guard, os.environ["GH_TOKEN"])
            stage = "inspect_" + platform
            platform_result = audit_platform(platform, path, android_helper, ios_helper, guard)
            result["platforms"].append(platform_result)
            print(json.dumps(public_summary(platform_result, args.source_commit, args.run_id),
                             ensure_ascii=True, sort_keys=True))
            path.unlink()
        result.update(status="PASS_STATIC_INVENTORY", resources=guard.report(),
            native_abi_verified=False, storage_layout_verified=False, full_il2cpp_dump_generated=False)
        write_report(args.output / "resource-cache-audit.json", result)
        print(json.dumps({"status": result["status"], "source_commit": args.source_commit,
            "run_id": args.run_id, "selected_methods": {row["platform"]: len(row["inventory"]["methods"])
                                                     for row in result["platforms"]},
            "direct_file_reuse_implemented": False}))
        return 0
    except BaseException as error:
        result.update(status="FAIL", failed_stage=stage,
            error_code=str(error) if type(error) is AuditError else "static_cache_audit_failed")
        if guard is not None:
            result["resources"] = guard.report()
        if output_ready:
            try:
                write_report(args.output / "resource-cache-audit.json", result)
            except BaseException:
                pass
        print(json.dumps({"status": "FAIL", "stage": stage, "error_code": result["error_code"]}))
        return 1
    finally:
        if output_ready and args.work.is_dir() and not args.work.is_symlink():
            shutil.rmtree(args.work)


if __name__ == "__main__":
    raise SystemExit(main())
