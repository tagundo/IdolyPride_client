#!/usr/bin/env python3
"""Add the integrated server to the verified v0.3.31 Unity load dependencies.

Only a zero-filled load-command reservation and the two command counters
change. Code, static presentation gateways, and every existing file offset
remain unchanged. A sideloading tool must subsequently sign the finished app.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct
from zipfile import ZipFile

SOURCE_IPA_SHA256 = "d872903da8d79bf4a255888f9d5a952198ff47268cfcf7c35e8ac437b56e72a1"
SOURCE_IPA_BYTES = 150132823
UNITY_SHA256 = "7455d0faecdb7100794021ba3a2c49ada2ad391ed035eac66c787b7ea01ae6c8"
UNITY_MEMBER = "Payload/IDOLY PRIDE.app/Frameworks/UnityFramework.framework/UnityFramework"
DEPENDENCY = "@rpath/IdolyEmbeddedServer.framework/IdolyEmbeddedServer"
PRESENTATION = "@loader_path/../IdolyPresentation.dylib"
MAX_HEADER = 256 * 1024
MAX_UNITY = 256 * 1024 * 1024
CHUNK = 128 * 1024


def need(value, message):
    if not value:
        raise ValueError(message)


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for raw in iter(lambda: stream.read(CHUNK), b""):
            h.update(raw)
    return h.hexdigest()


def patched_header(raw: bytes, file_bytes: int):
    need(32 <= len(raw) <= MAX_HEADER and len(raw) <= file_bytes <= MAX_UNITY,
         "Bounded complete header required")
    magic, cpu, _, kind, count, command_bytes, _, _ = struct.unpack_from("<8I", raw)
    need(magic == 0xFEEDFACF and cpu == 0x0100000C and kind == 6,
         "Expected the thin arm64 Unity dynamic library")
    end = 32 + command_bytes
    need(0 < count <= 1024 and end <= len(raw), "Invalid command table bounds")
    at, first_section, platforms = 32, file_bytes, []
    dependencies, rpaths = [], []
    for _ in range(count):
        need(at + 8 <= end, "Truncated load command")
        command, size = struct.unpack_from("<II", raw, at)
        need(size >= 8 and size % 8 == 0 and at + size <= end,
             "Invalid load command extent")
        if command == 0x32:
            need(size >= 24, "Truncated platform command")
            platforms.append(struct.unpack_from("<I", raw, at + 8)[0])
        elif command in (0x21, 0x2C):
            need(size >= 20 and struct.unpack_from("<I", raw, at + 16)[0] == 0,
                 "Encrypted Unity input")
        elif command == 0x19:
            need(size >= 72, "Truncated segment")
            sections = struct.unpack_from("<I", raw, at + 64)[0]
            need(72 + 80 * sections <= size, "Truncated section table")
            for index in range(sections):
                section = at + 72 + index * 80
                length = struct.unpack_from("<Q", raw, section + 40)[0]
                offset = struct.unpack_from("<I", raw, section + 48)[0]
                flags = struct.unpack_from("<I", raw, section + 64)[0] & 0xFF
                if length and offset and flags not in (1, 0xC, 0x12):
                    need(offset + length <= file_bytes, "Section outside file")
                    first_section = min(first_section, offset)
        if command in (0xC, 0x80000018, 0x8000001C):
            minimum = 12 if command == 0x8000001C else 24
            need(size >= minimum, "Truncated load path")
            offset = struct.unpack_from("<I", raw, at + 8)[0]
            need(minimum <= offset < size, "Invalid load path offset")
            path = raw[at + offset:at + size]
            need(b"\0" in path, "Unterminated load path")
            path = path.split(b"\0", 1)[0].decode("utf-8")
            (rpaths if command == 0x8000001C else dependencies).append(path)
        at += size
    need(at == end and platforms == [2], "Expected an actual iOS device image")
    need(PRESENTATION in dependencies and DEPENDENCY not in dependencies,
         "Expected existing presentation and no previous integrated server")
    need("@executable_path/Frameworks" in rpaths,
         "Integrated dependency requires the original app Frameworks rpath")
    name = DEPENDENCY.encode("ascii") + b"\0"
    length = (24 + len(name) + 7) & ~7
    need(end + length <= min(first_section, len(raw)), "No load command reservation")
    need(raw[end:end + length] == b"\0" * length,
         "Load command reservation is not empty")
    # No minimum library compatibility version is imposed on the new framework.
    load = struct.pack("<6I", 0xC, length, 24, 0, 0, 0) + name
    load += b"\0" * (length - len(load))
    output = bytearray(raw)
    struct.pack_into("<II", output, 16, count + 1, command_bytes + length)
    output[end:end + length] = load
    return bytes(output), {"offset": end, "bytes": length,
        "previous_command_count": count, "previous_command_bytes": command_bytes,
        "dependency": DEPENDENCY, "platform": 2,
        "only_changed_ranges": [[16, 8], [end, length]],
        "original_code_and_file_offsets_preserved": True}


def patch_ipa(source, output):
    source, output = Path(source), Path(output)
    old = source.lstat()
    need(stat.S_ISREG(old.st_mode) and old.st_size == SOURCE_IPA_BYTES,
         "Expected the verified v0.3.31 Korean IPA")
    need(file_sha(source) == SOURCE_IPA_SHA256, "Source IPA SHA differs")
    partial = output.with_suffix(output.suffix + ".partial")
    need(not output.exists() and not output.is_symlink()
         and not partial.exists() and not partial.is_symlink(), "Fresh output required")
    output.parent.mkdir(parents=True, exist_ok=True)
    before, after = hashlib.sha256(), hashlib.sha256()
    with ZipFile(source) as archive:
        need(archive.namelist().count(UNITY_MEMBER) == 1, "Missing/duplicate Unity member")
        size = archive.getinfo(UNITY_MEMBER).file_size
        need(0 < size <= MAX_UNITY, "Unity member too large")
        with archive.open(UNITY_MEMBER) as incoming:
            header = incoming.read(min(MAX_HEADER, size))
            replacement, change = patched_header(header, size)
            with partial.open("xb") as destination:
                before.update(header); after.update(replacement)
                destination.write(replacement)
                copied = len(header)
                for raw in iter(lambda: incoming.read(CHUNK), b""):
                    before.update(raw); after.update(raw)
                    destination.write(raw); copied += len(raw)
            need(copied == size and before.hexdigest() == UNITY_SHA256,
                 "Complete original Unity SHA/size differs")
    stable = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    need(stable(source.lstat()) == stable(old) and partial.stat().st_size == size,
         "Input/output identity changed")
    partial.rename(output)
    report = {"schema": 1, "source_ipa_sha256": SOURCE_IPA_SHA256,
        "input_unity_sha256": before.hexdigest(), "output_unity_sha256": after.hexdigest(),
        "output_bytes": size, "member": UNITY_MEMBER, "change": change,
        "requires_app_resigning": True, "device_execution_verified": False}
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ipa", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(patch_ipa(args.source_ipa, args.output)))


if __name__ == "__main__":
    main()
