#!/usr/bin/env python3
"""Emulate bounded original iOS cache snippets with synthetic managed objects.

The input is the pinned, unmodified 6.1.1 UnityFramework. This executes a few
ARM64 instructions in Unicorn, not an application, server, account or native
operating-system process. No game files are created or changed. This proof does
not replace device validation of a shared store or Unity's file readers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import stat
import struct
import zipfile


PINNED_NATIVE_SHA256 = "b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf"
PINNED_METADATA_SHA256 = "d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda"
PINNED_IPA_SHA256 = "33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848"
PINNED_IPA_BYTES = 146438450
MIB = 1024 * 1024
TRANSLATOR_BYTES = 16 * MIB

# These VAs belong only to the native SHA above, not to arbitrary game builds.
GET_FILE_PATH = 0x6E9F1FC
IS_CACHED = 0x6E9F1E0
BASE_IS_CACHED = 0x6E9D018
GET_CACHING_TYPE = 0x6E7F578
SET_CACHING_TYPE = 0x6E7F580
DOWNLOADER_UPDATE = 0x6E898A0


class ProofError(ValueError):
    """A pinned-input or bounded-emulation requirement was not met."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise ProofError(code)


def _segments(native: bytes) -> list[tuple[int, int, int]]:
    _need(len(native) >= 32, "native_header_bound")
    magic, cpu, _, _, count, command_bytes, _, _ = struct.unpack_from("<8I", native)
    _need(magic == 0xFEEDFACF and cpu == 0x0100000C, "native_macho_arm64_required")
    command_end = 32 + command_bytes
    _need(count <= 4096 and command_end <= len(native), "native_commands_bound")
    cursor, segments = 32, []
    for _ in range(count):
        _need(cursor + 8 <= command_end, "native_command_bound")
        command, size = struct.unpack_from("<II", native, cursor)
        _need(size >= 8 and cursor + size <= command_end, "native_command_bound")
        if command == 0x19:  # LC_SEGMENT_64
            _need(size >= 72, "native_segment_bound")
            _, address, _, offset, file_bytes = struct.unpack_from("<16s4Q", native, cursor + 8)
            _need(offset <= len(native) and file_bytes <= len(native) - offset,
                  "native_segment_bound")
            segments.append((address, address + file_bytes, offset))
        cursor += size
    _need(cursor == command_end and bool(segments), "native_commands_bound")
    return segments


def prove_original_code(native: bytes) -> dict:
    """Return seven reproducible original-code proofs, or fail closed.

    This function does not read files, download inputs, alter process limits, or
    access accounts. Unicorn is imported only after the original SHA is checked.
    Each synthetic execution is capped at 128 instructions with a 16 MiB code
    translator and a small explicitly mapped address space.
    """
    _need(type(native) is bytes and len(native) <= 256 * MIB, "native_size_bound")
    digest = hashlib.sha256(native).hexdigest()
    _need(digest == PINNED_NATIVE_SHA256, "native_sha256_differs")
    segments = _segments(native)

    def original(address: int, size: int) -> bytes:
        for start, end, offset in segments:
            if start <= address and size <= end - address:
                begin = offset + address - start
                return native[begin:begin + size]
        raise ProofError("native_window_bound")

    try:
        from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM
        from unicorn.arm64_const import (
            UC_ARM64_REG_LR, UC_ARM64_REG_SP, UC_ARM64_REG_X0,
            UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
            UC_ARM64_REG_X4, UC_ARM64_REG_X5,
        )
    except ImportError:
        raise ProofError("unicorn_unavailable") from None

    registers = (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
                 UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5)
    return_address = 0x30000000

    def emulate(entry, code, arguments, prepare, stop, inspect=None):
        try:
            engine = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
            engine.ctl_set_tcg_buffer_size(TRANSLATOR_BYTES)
            for page in {entry & ~4095, stop & ~4095, return_address}:
                engine.mem_map(page, 4096)
            engine.mem_write(entry, code)
            engine.mem_map(0x10000000, 0x10000)
            engine.mem_map(0x40000000, 0x10000)
            engine.reg_write(UC_ARM64_REG_SP, 0x40008000)
            engine.reg_write(UC_ARM64_REG_LR, return_address)
            for register, value in zip(registers, arguments):
                engine.reg_write(register, value)
            prepare(engine)
            stopped = []

            def reached_stop(current, pc, _size, _data):
                if pc == stop:
                    stopped.append([current.reg_read(register) for register in registers])
                    current.emu_stop()

            engine.hook_add(UC_HOOK_CODE, reached_stop)
            engine.emu_start(entry, 0, count=128)
            _need(len(stopped) == 1, "emulation_stop_not_reached")
            extra = inspect(engine) if inspect else None
            return stopped[0], extra
        except UcError:
            raise ProofError("emulation_fault") from None

    obj, klass = 0x10000100, 0x10001000
    bucket, filename, item = 0x10002000, 0x10003000, 0x10004000
    method, callee_method, virtual_target = 0x10005000, 0x10006000, 0x20000000
    cases = []

    # The original wrapper replaces its item argument with the virtual target's
    # MethodInfo, while preserving this, bucket and filename.
    code = original(GET_FILE_PATH, 16)

    def prepare_virtual(engine):
        engine.mem_write(obj, struct.pack("<Q", klass))
        engine.mem_write(klass + 0x218, struct.pack("<QQ", virtual_target, callee_method))

    seen, _ = emulate(GET_FILE_PATH, code,
                      [obj, bucket, filename, item, method, 0x55555555],
                      prepare_virtual, virtual_target)
    _need(seen[:4] == [obj, bucket, filename, callee_method], "filepath_forwarding_differs")
    cases.append({"method": "OctoCaching.GetFilePath", "virtual_address": hex(GET_FILE_PATH),
                  "original_prefix": code.hex(),
                  "forwarded_this_bucket_filename_and_methodinfo": True})

    # The cache wrapper sign extends Item.size (+0x28), then tailcalls its base
    # with the original strings and a zero default argument.
    code = original(IS_CACHED, 16)
    for size in (0, 123456, 2147483647, -1):
        def prepare_size(engine):
            engine.mem_write(item + 0x28, struct.pack("<i", size))

        seen, _ = emulate(IS_CACHED, code,
                          [obj, bucket, filename, item, method, 0x55555555],
                          prepare_size, BASE_IS_CACHED)
        _need(seen[:3] == [obj, bucket, filename]
              and seen[3] == size % (1 << 64) and seen[4] == 0,
              "cache_size_forwarding_differs")
        cases.append({"method": "OctoCaching.IsCached", "virtual_address": hex(IS_CACHED),
                      "original_prefix": code.hex(), "item_size": size,
                      "signed_size_forwarded": True, "default_argument_zero": True})

    # These accessors are only eight bytes each. Executing the actual STRB
    # setter proves field width without overwriting adjacent configuration.
    setter, getter = original(SET_CACHING_TYPE, 8), original(GET_CACHING_TYPE, 8)
    _, written = emulate(
        SET_CACHING_TYPE, setter, [obj, 2, method, 0, 0, 0],
        lambda engine: engine.mem_write(obj + 0x38, bytes.fromhex("aabbccdd")),
        return_address, lambda engine: bytes(engine.mem_read(obj + 0x38, 4)))
    _need(written == bytes.fromhex("02bbccdd"), "settings_field_width_differs")
    seen, _ = emulate(
        GET_CACHING_TYPE, getter, [obj, method, 0, 0, 0, 0],
        lambda engine: engine.mem_write(obj + 0x38, bytes.fromhex("02bbccdd")), return_address)
    _need(seen[0] == 2, "settings_roundtrip_differs")
    cases.append({"method": "OctoFullSettings.CachingType",
                  "setter_virtual_address": hex(SET_CACHING_TYPE),
                  "getter_virtual_address": hex(GET_CACHING_TYPE),
                  "setter_prefix": setter.hex(), "getter_prefix": getter.hex(),
                  "field_offset": 0x38, "field_width_bytes": 1, "roundtrip_value": 2,
                  "adjacent_three_bytes_preserved": True})

    # Skip already-completed metadata initialization, provide an empty managed
    # list and verify the original frame callback returns without external calls.
    code = original(DOWNLOADER_UPDATE, 224)

    def prepare_empty_update(engine):
        engine.mem_map(0xA914000, 4096)
        engine.mem_write(0xA914101, b"\x01")
        engine.mem_write(obj + 0x38, struct.pack("<Q", bucket))
        engine.mem_write(bucket + 0x18, struct.pack("<I", 0))

    emulate(DOWNLOADER_UPDATE, code, [obj, method, 0, 0, 0, 0],
            prepare_empty_update, return_address)
    cases.append({"method": "Downloader.Update", "virtual_address": hex(DOWNLOADER_UPDATE),
                  "original_prefix": code[:16].hex(), "pending_list_empty": True,
                  "returned_without_external_calls": True})
    return {"schema": 1, "platform": "ios", "source_native_sha256": digest,
            "native_snippets_emulated": True, "game_app_launched": False,
            "accounts_accessed": False, "translator_buffer_bytes": TRANSLATOR_BYTES,
            "instruction_limit_per_case": 128, "cases": cases,
            "status": "PASS_SYNTHETIC_ORIGINAL_SNIPPETS"}


def _read_pinned_ipa(path: Path) -> tuple[bytes, bytes]:
    # Hash and read through the same open descriptor. A different archive must
    # never reach ZIP decompression, even when it imitates the expected layout.
    with path.open("rb") as incoming:
        info = incoming.fileno()
        import os
        source = os.fstat(info)
        _need(stat.S_ISREG(source.st_mode) and source.st_size == PINNED_IPA_BYTES,
              "ipa_size_differs")
        _need(hashlib.file_digest(incoming, "sha256").hexdigest() == PINNED_IPA_SHA256,
              "ipa_sha256_differs")
        incoming.seek(0)
        with zipfile.ZipFile(incoming) as archive:
            _need(len(archive.infolist()) <= 10000, "ipa_entry_count_bound")
            natives = [entry for entry in archive.infolist()
                       if entry.filename.endswith("/Frameworks/UnityFramework.framework/UnityFramework")]
            metadatas = [entry for entry in archive.infolist()
                         if entry.filename.endswith("/Data/Managed/Metadata/global-metadata.dat")]
            _need(len(natives) == len(metadatas) == 1, "ipa_input_entries_differ")
            _need(natives[0].file_size <= 256 * MIB and metadatas[0].file_size <= 64 * MIB,
                  "ipa_entry_size_bound")
            native, metadata = archive.read(natives[0]), archive.read(metadatas[0])
    _need(hashlib.sha256(metadata).hexdigest() == PINNED_METADATA_SHA256,
          "metadata_sha256_differs")
    return native, metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipa", type=Path, required=True, help="Pinned original 6.1.1 IPA/ZIP")
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout")
    args = parser.parse_args(argv)
    # CLI-only bound; importing or invoking the pure proof does not change limits.
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    bound = 3 * 1024 ** 3
    resource.setrlimit(resource.RLIMIT_AS, (min(soft, bound) if soft >= 0 else bound, hard))
    native, metadata = _read_pinned_ipa(args.ipa)
    result = prove_original_code(native)
    result["source_metadata_sha256"] = hashlib.sha256(metadata).hexdigest()
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
