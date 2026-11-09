#!/usr/bin/env python3
"""Recover protobuf schemas from a user-provided decrypted ARM64 iOS IPA.

Reads the IPA without extracting or executing its contents. Shared ARM64
Reflection initializer analysis lives in extract_client_schema.py. This tool
supports IL2CPP metadata v31 and unencrypted, little-endian ARM64 Mach-O images.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import plistlib
import struct
from zipfile import BadZipFile, ZipFile

from extract_client_schema import ClientImage, capstone, sha256
from google.protobuf.descriptor_pb2 import FileDescriptorSet
from google.protobuf.descriptor_pool import DescriptorPool


_METADATA = "Data/Managed/Metadata/global-metadata.dat"
_UNITY = "Frameworks/UnityFramework.framework/UnityFramework"


def read_ipa(path: Path) -> tuple[bytes, bytes, dict]:
    raw = path.read_bytes()
    with ZipFile(BytesIO(raw)) as archive:
        names = archive.namelist()
        infos = [n for n in names if n.startswith("Payload/") and n.endswith(".app/Info.plist")
                 and n.count("/") == 2]
        if len(infos) != 1:
            raise ValueError("Need exactly one top-level application in the IPA")
        info_name = infos[0]
        info = plistlib.loads(archive.read(info_name))
        if not str(info.get("CFBundleIdentifier", "")).startswith("game.qualiarts.idolypride"):
            raise ValueError("Unexpected game bundle identifier")
        app = info_name.removesuffix("Info.plist")
        metadata = archive.read(app + _METADATA)
        native = archive.read(app + _UNITY)
    return metadata, native, {
        "platform": "ios",
        "client": {key: info.get(key) for key in
                   ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion", "MinimumOSVersion")},
        "source_sha256": {path.name: sha256(raw), _METADATA: sha256(metadata), _UNITY: sha256(native)},
    }


class MachOClientImage(ClientImage):
    """Mach-O address/module adapter for the shared ARM64 initializer decoder."""

    def __init__(self, metadata: bytes, native: bytes):
        self.metadata, self.native = metadata, native
        self.header = struct.unpack_from("<64I", metadata)
        if self.header[:2] != (0xFAB11BAF, 31):
            raise ValueError("Only IL2CPP metadata version 31 is supported")
        if native[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack_from("<I", native, 4)[0] != 0x0100000C:
            raise ValueError("Need a little-endian 64-bit ARM Mach-O UnityFramework")
        _, _, _, _, count, size, _, _ = struct.unpack_from("<8I", native)
        cursor = 32
        command_end = cursor + size
        self.segments = []
        self.module_segment = None
        self.encryption = []
        for _ in range(count):
            command, command_size = struct.unpack_from("<II", native, cursor)
            if command_size < 8 or cursor + command_size > command_end:
                raise ValueError("Malformed Mach-O load commands")
            if command == 0x19:  # LC_SEGMENT_64
                if command_size < 72:
                    raise ValueError("Malformed Mach-O segment")
                name, address, _, offset, file_size = struct.unpack_from("<16s4Q", native, cursor + 8)
                if offset + file_size > len(native):
                    raise ValueError("Mach-O segment exceeds file bounds")
                self.segments.append((address, address + file_size, offset))
                if name.rstrip(b"\0") == b"__DATA_CONST":
                    self.module_segment = (offset, file_size)
            elif command in (0x21, 0x2C):  # LC_ENCRYPTION_INFO[_64]
                _, _, crypto_offset, crypto_size, crypto_id = struct.unpack_from("<5I", native, cursor)
                self.encryption.append({"offset": crypto_offset, "bytes": crypto_size, "cryptid": crypto_id})
                if crypto_id != 0:
                    raise ValueError("UnityFramework is encrypted; provide the decrypted IPA")
            cursor += command_size
        if cursor != command_end or self.module_segment is None:
            raise ValueError("Missing or malformed Mach-O __DATA_CONST module segment")
        h = self.header
        self.literals = {}
        for index, cursor in enumerate(range(h[2], h[2] + h[3], 8)):
            length, offset = struct.unpack_from("<II", metadata, cursor)
            self.literals[index] = metadata[h[4] + offset:h[4] + offset + length]
        self.disassembler = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        self.disassembler.detail = True

    def file_offset(self, address):
        for start, end, offset in self.segments:
            if start <= address < end:
                return offset + address - start
        raise ValueError("Address outside a file-backed Mach-O segment")

    def read_pointer(self, address):
        return struct.unpack_from("<Q", self.native, self.file_offset(address))[0]

    def reflection_constructors(self):
        h, m, b = self.header, self.metadata, self.native
        images = []
        for offset in range(h[42], h[42] + h[43], 40):
            row = struct.unpack_from("<10i", m, offset)
            images.append((row[2], row[2] + row[3], self.string(row[0])))
        types = []
        for index, offset in enumerate(range(h[40], h[40] + h[41], 88)):
            row = struct.unpack_from("<16I8H2I", m, offset)
            name, namespace = self.string(row[0]), self.string(row[1])
            if not name.endswith("Reflection") or namespace == "UnityEngine":
                continue
            module = next(name for start, end, name in images if start <= index < end)
            for method_index in range(row[9], row[9] + row[16]):
                method = struct.unpack_from("<7I4H", m, h[12] + method_index * 36)
                if self.string(method[0]) == ".cctor":
                    types.append((namespace + "." + name, module, method[6] & 0xFFFFFF))
        modules = {}
        offset, size = self.module_segment
        needed = {module for _, module, _ in types}
        for cursor in range(offset, offset + size - 24, 8):
            name_address, count, table = struct.unpack_from("<3Q", b, cursor)
            if not 0 < count < 1000000:
                continue
            try:
                name_offset = self.file_offset(name_address)
                end = b.find(b"\0", name_offset, name_offset + 100)
                if end < 0:
                    continue
                text = b[name_offset:end]
                if not text.endswith(b".dll") or not all(32 <= c < 127 for c in text):
                    continue
                module = text.decode("ascii")
                if module not in needed:
                    continue
                self.file_offset(table)
                self.file_offset(table + (count - 1) * 8)
            except (ValueError, struct.error):
                continue
            if module in modules:
                raise ValueError(f"Ambiguous codegen module table: {module}")
            modules[module] = count, table
        missing = needed - modules.keys()
        if missing:
            raise ValueError("Missing codegen module tables: " + ", ".join(sorted(missing)))
        result = []
        for name, module, token in types:
            count, table = modules[module]
            if not 1 <= token <= count:
                raise ValueError(f"Method row outside module: {name}")
            address = self.read_pointer(table + (token - 1) * 8)
            if address:
                result.append((name, address))
        return result


def extract(metadata: bytes, native: bytes):
    image = MachOClientImage(metadata, native)
    constructors = image.reflection_constructors()
    found, files = {}, []
    for name, address in constructors:
        try:
            descriptor, raw, chunks = image.recover(address)
        except ValueError as exc:
            raise ValueError(f"Cannot recover {name}: {exc}") from exc
        if descriptor.name in found:
            raise ValueError(f"Duplicate descriptor: {descriptor.name}")
        found[descriptor.name] = descriptor
        files.append({"file": descriptor.name, "reflection_type": name, "cctor_rva": hex(address),
                      "chunks": chunks, "bytes": len(raw), "sha256": sha256(raw)})
    missing = {dep for file in found.values() for dep in file.dependency} - found.keys()
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
        "extractor_version": 1, "metadata_version": 31, "architecture": "arm64-ios",
        "reflection_constructors": len(constructors), "recovered_files": len(found),
        "top_level_messages": sum(len(file.message_type) for file in found.values()),
        "services": sum(len(file.service) for file in found.values()),
        "methods": sum(len(service.method) for file in found.values() for service in file.service),
        "missing_dependencies": [], "descriptor_pool_validated": True,
        "unity_encryption_commands": image.encryption, "files": files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", type=Path, help="User-provided decrypted ARM64 .ipa")
    parser.add_argument("--output", required=True, type=Path, help="Output FileDescriptorSet .pb")
    args = parser.parse_args()
    try:
        metadata, native, source = read_ipa(args.client)
        result, evidence = extract(metadata, native)
    except (ValueError, KeyError, OSError, BadZipFile, struct.error, plistlib.InvalidFileException) as exc:
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
