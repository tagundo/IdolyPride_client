#!/usr/bin/env python3
"""Recover embedded protobuf descriptors from the user's ARM64 Android client.

Reads APK/XAPK bytes only; it does not launch, patch, or redistribute the game.
Supported boundary: little-endian AArch64 ELF + IL2CPP metadata version 31.
The ARM64 dataflow recognizes generated Reflection .cctor string-array initializers.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import struct
from zipfile import BadZipFile, ZipFile

try:
    import capstone
    from capstone import arm64
    from google.protobuf.descriptor_pb2 import FileDescriptorProto, FileDescriptorSet
    from google.protobuf.descriptor_pool import DescriptorPool
    from google.protobuf.message import DecodeError
except ImportError as exc:
    raise SystemExit("Install extraction dependencies: uv sync --extra extract") from exc

METADATA_NAME = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
LIBRARY_NAME = "lib/arm64-v8a/libil2cpp.so"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_client(path: Path, native: Path | None) -> tuple[bytes, bytes, dict]:
    """Read named members without extracting arbitrary ZIP paths."""
    raw = path.read_bytes()
    sources = {path.name: sha256(raw)}
    metadata = library = None
    version = None

    def read_apk(contents: bytes):
        nonlocal metadata, library
        with ZipFile(BytesIO(contents)) as archive:
            names = set(archive.namelist())
            if METADATA_NAME in names:
                if metadata is not None:
                    raise ValueError("Client contains more than one metadata file")
                metadata = archive.read(METADATA_NAME)
            if LIBRARY_NAME in names:
                if library is not None:
                    raise ValueError("Client contains more than one ARM64 libil2cpp.so")
                library = archive.read(LIBRARY_NAME)

    with ZipFile(BytesIO(raw)) as archive:
        apk_names = [n for n in archive.namelist() if n.endswith(".apk")]
        if apk_names:
            if "manifest.json" in archive.namelist():
                manifest = json.loads(archive.read("manifest.json"))
                version = {k: manifest.get(k) for k in
                           ("package_name", "version_name", "version_code")}
            for name in apk_names:
                contents = archive.read(name)
                sources[name] = sha256(contents)
                read_apk(contents)
        else:
            read_apk(raw)
    if native:
        contents = native.read_bytes()
        sources[native.name] = sha256(contents)
        if contents.startswith(b"\x7fELF"):
            if library is not None:
                raise ValueError("Native library provided twice")
            library = contents
        else:
            read_apk(contents)
    if metadata is None or library is None:
        raise ValueError("Need IL2CPP metadata and ARM64 library; for split APK use --native config.arm64_v8a.apk")
    sources[METADATA_NAME] = sha256(metadata)
    sources[LIBRARY_NAME] = sha256(library)
    return metadata, library, {"client": version, "source_sha256": sources}


class ClientImage:
    def __init__(self, metadata: bytes, native: bytes):
        self.metadata, self.native = metadata, native
        self.header = struct.unpack_from("<64I", metadata)
        if self.header[:2] != (0xFAB11BAF, 31):
            raise ValueError("Only IL2CPP metadata version 31 is supported")
        if native[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", native, 18)[0] != 183:
            raise ValueError("Need a little-endian 64-bit ARM ELF library")
        self.segments = []
        phoff = struct.unpack_from("<Q", native, 32)[0]
        phsize, phnum = struct.unpack_from("<HH", native, 54)
        for i in range(phnum):
            typ, _, offset, address, _, size, _, _ = struct.unpack_from("<II6Q", native, phoff + i * phsize)
            if typ == 1:
                self.segments.append((address, address + size, offset))
        self.relocations = {}
        shoff = struct.unpack_from("<Q", native, 40)[0]
        shsize, shnum = struct.unpack_from("<HH", native, 58)
        for i in range(shnum):
            _, typ, _, _, offset, size, _, _, _, entsize = struct.unpack_from("<II4QII2Q", native, shoff + i * shsize)
            if typ == 4:  # ELF SHT_RELA, R_AARCH64_RELATIVE
                if entsize != 24:
                    raise ValueError("Unexpected ELF RELA entry size")
                for p in range(offset, offset + size, entsize):
                    address, info, addend = struct.unpack_from("<QQq", native, p)
                    if info & 0xFFFFFFFF == 1027:
                        self.relocations[address] = addend
        h = self.header
        self.literals = {}
        for i, p in enumerate(range(h[2], h[2] + h[3], 8)):
            length, index = struct.unpack_from("<II", metadata, p)
            self.literals[i] = metadata[h[4] + index:h[4] + index + length]
        self.disassembler = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        self.disassembler.detail = True

    def file_offset(self, address):
        for start, end, offset in self.segments:
            if start <= address < end:
                return offset + address - start
        raise ValueError("Address outside file-backed ELF segment")

    def virtual_address(self, offset):
        for start, end, file_offset in self.segments:
            if file_offset <= offset < file_offset + end - start:
                return start + offset - file_offset
        raise ValueError("File offset outside ELF load segments")

    def read_pointer(self, address):
        if address in self.relocations:
            return self.relocations[address]
        return struct.unpack_from("<Q", self.native, self.file_offset(address))[0]

    def string(self, index):
        start = self.header[6] + index
        return self.metadata[start:self.metadata.index(b"\0", start)].decode("utf-8")

    def reflection_constructors(self):
        h, m, b = self.header, self.metadata, self.native
        images = []
        for p in range(h[42], h[42] + h[43], 40):
            row = struct.unpack_from("<10i", m, p)
            images.append((row[2], row[2] + row[3], self.string(row[0])))
        types = []
        for i, p in enumerate(range(h[40], h[40] + h[41], 88)):
            row = struct.unpack_from("<16I8H2I", m, p)
            name = self.string(row[0])
            namespace = self.string(row[1])
            if not name.endswith("Reflection") or namespace == "UnityEngine":
                continue
            module = next(name for start, end, name in images if start <= i < end)
            for j in range(row[9], row[9] + row[16]):
                method = struct.unpack_from("<7I4H", m, h[12] + j * 36)
                if self.string(method[0]) == ".cctor":
                    types.append((namespace + "." + name, module, method[6] & 0xFFFFFF))
        reverse = {}
        for address, addend in self.relocations.items():
            reverse.setdefault(addend, []).append(address)
        modules = {}
        for module in {module for _, module, _ in types}:
            start = b.find(module.encode() + b"\0")
            if start < 0:
                raise ValueError(f"Missing codegen module name: {module}")
            candidates = []
            for address in reverse.get(self.virtual_address(start), []):
                try:
                    count, table = self.read_pointer(address + 8), self.read_pointer(address + 16)
                    if 0 < count < 1000000:
                        self.file_offset(table + (count - 1) * 8)
                        candidates.append((count, table))
                except (ValueError, struct.error):
                    continue
            if len(candidates) != 1:
                raise ValueError(f"Ambiguous codegen module table: {module}")
            modules[module] = candidates[0]
        result = []
        for name, module, token in types:
            count, table = modules[module]
            if not 1 <= token <= count:
                raise ValueError(f"Method row outside module: {name}")
            rva = self.read_pointer(table + (token - 1) * 8)
            if rva:
                result.append((name, rva))
        return result

    def recover(self, rva):
        """Track string literals into consecutive generated array slots."""
        cs = self.disassembler
        registers, groups, current, direct = {}, [], {}, []

        def regname(op):
            return cs.reg_name(op.reg).replace("w", "x", 1)

        def read_value(address):
            value = self.read_pointer(address)
            if 0xA0000000 <= value < 0xC0000000 and value & 1:
                return ("str", (value & 0x1FFFFFFF) >> 1)
            return ("addr", value)

        start = self.file_offset(rva)
        end = self.native.find(b"\xc0\x03\x5f\xd6", start, start + 1024 * 1024)
        while end >= 0 and (end - start) % 4:
            end = self.native.find(b"\xc0\x03\x5f\xd6", end + 1, start + 1024 * 1024)
        if end < 0:
            raise ValueError("No ARM64 RET within 1 MiB constructor bound")
        for ins in cs.disasm(self.native[start:end + 4], rva):
            ops = ins.operands
            if ins.mnemonic == "adrp":
                registers[regname(ops[0])] = ("addr", ops[1].imm)
            elif ins.mnemonic == "add" and len(ops) == 3 and ops[2].type == arm64.ARM64_OP_IMM:
                value = registers.get(regname(ops[1]))
                registers[regname(ops[0])] = ("addr", value[1] + ops[2].imm) if value and value[0] == "addr" else None
            elif ins.mnemonic == "mov":
                registers[regname(ops[0])] = registers.get(regname(ops[1])) if ops[1].type == arm64.ARM64_OP_REG else ("addr", ops[1].imm)
            elif ins.mnemonic == "ldr" and ops[1].type == arm64.ARM64_OP_MEM:
                value = registers.get(cs.reg_name(ops[1].mem.base))
                try:
                    value = read_value(value[1] + ops[1].mem.disp) if value and value[0] == "addr" else None
                except (ValueError, struct.error):
                    value = None
                registers[regname(ops[0])] = value
                if value and value[0] == "str":
                    direct.append(value[1])
            elif ins.mnemonic in ("str", "stp"):
                mem = next((op for op in ops if op.type == arm64.ARM64_OP_MEM), None)
                if mem is None:
                    continue
                values = [registers.get(regname(op)) for op in ops if op.type == arm64.ARM64_OP_REG]
                for j, value in enumerate(values):
                    displacement = mem.mem.disp + j * 8
                    if not value or value[0] != "str" or displacement < 32 or displacement % 8:
                        continue
                    index = (displacement - 32) // 8
                    if index == 0 and current:
                        groups.append(current)
                        current = {}
                    current[index] = value[1]
            elif ins.mnemonic == "bl":
                for i in range(19):
                    registers.pop("x" + str(i), None)
        if current:
            groups.append(current)
        candidates = []
        for group in groups:
            if sorted(group) == list(range(max(group) + 1)):
                candidates.append([group[i] for i in range(len(group))])
        candidates.extend([index] for index in set(direct))
        valid = {}
        for indices in candidates:
            try:
                raw = base64.b64decode(b"".join(self.literals[i] for i in indices), validate=True)
                descriptor = FileDescriptorProto.FromString(raw)
                if not isinstance(descriptor.name, str) or not descriptor.name.endswith(".proto"):
                    continue
                old = valid.get(descriptor.name)
                # A first 60-byte chunk may itself parse as a valid partial descriptor.
                if old is None or len(raw) > len(old[1]):
                    valid[descriptor.name] = (descriptor, raw, len(indices))
            except (ValueError, KeyError, DecodeError):
                continue
        if len(valid) != 1:
            raise ValueError(f"Constructor has {len(valid)} valid descriptor candidates")
        return next(iter(valid.values()))


def extract(metadata: bytes, native: bytes):
    image = ClientImage(metadata, native)
    constructors = image.reflection_constructors()
    found, evidence = {}, []
    for name, rva in constructors:
        try:
            descriptor, raw, chunks = image.recover(rva)
        except ValueError as exc:
            raise ValueError(f"Cannot recover {name}: {exc}") from exc
        if descriptor.name in found:
            raise ValueError(f"Duplicate descriptor: {descriptor.name}")
        found[descriptor.name] = descriptor
        evidence.append({"file": descriptor.name, "reflection_type": name, "cctor_rva": hex(rva),
                         "chunks": chunks, "bytes": len(raw), "sha256": sha256(raw)})
    missing = {dep for f in found.values() for dep in f.dependency} - found.keys()
    if missing:
        raise ValueError("Missing protobuf dependencies: " + ", ".join(sorted(missing)))
    pool, pending = DescriptorPool(), dict(found)
    while pending:
        progress = False
        for name, descriptor in list(pending.items()):
            if any(dep in pending for dep in descriptor.dependency):
                continue
            pool.AddSerializedFile(descriptor.SerializeToString())
            del pending[name]
            progress = True
        if not progress:
            raise ValueError("Cyclic protobuf dependencies")
    result = FileDescriptorSet()
    result.file.extend(found.values())
    return result.SerializeToString(), {
        "extractor_version": 1, "metadata_version": 31, "architecture": "arm64-v8a",
        "reflection_constructors": len(constructors), "recovered_files": len(found),
        "top_level_messages": sum(len(f.message_type) for f in found.values()),
        "services": sum(len(f.service) for f in found.values()),
        "methods": sum(len(s.method) for f in found.values() for s in f.service),
        "missing_dependencies": [], "descriptor_pool_validated": True, "files": evidence,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", type=Path, help="User-provided ARM64 APK or XAPK")
    parser.add_argument("--native", type=Path, help="Split ARM64 APK or extracted libil2cpp.so")
    parser.add_argument("--output", required=True, type=Path, help="Output FileDescriptorSet .pb")
    args = parser.parse_args()
    try:
        metadata, native, source = read_client(args.client, args.native)
        result, evidence = extract(metadata, native)
    except (ValueError, OSError, BadZipFile, struct.error) as exc:
        parser.exit(1, f"Schema extraction failed: {exc}\n")
    evidence.update(source, descriptor_sha256=sha256(result), descriptor_bytes=len(result))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    args.output.with_suffix(".evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Recovered {evidence['recovered_files']} protobuf files, {evidence['services']} services, "
          f"{evidence['methods']} methods; dependency closure and DescriptorPool validated.")
    print(args.output)


if __name__ == "__main__":
    main()
