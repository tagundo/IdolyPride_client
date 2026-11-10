#!/usr/bin/env python3
"""Check the native live C ABI without master data or account fixtures.

Runs on the host Linux/macOS architecture. This checks versioning, invalid
input handling, buffer ownership and concurrent calls; it does not simulate a
live or validate official scores. Loaded Go libraries remain loaded for the
process lifetime.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import json
from pathlib import Path
import platform
import sys


ABI_VERSION = 1
MAX_BYTES = 16 * 1024 * 1024
_LOADED_LIBRARIES: list[ctypes.CDLL] = []
_CONFIGURED_LIBRARIES: dict[str, ctypes.CDLL] = {}


class ABIError(RuntimeError):
    """The library did not satisfy the documented C ABI."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ABIError(message)


def _load(path: Path):
    key = str(path)
    if key in _CONFIGURED_LIBRARIES:
        return _CONFIGURED_LIBRARIES[key]
    try:
        library = ctypes.CDLL(key)
        # Retain even a rejected Go library; unloading a running Go runtime is
        # not part of this API's lifecycle contract.
        _LOADED_LIBRARIES.append(library)
        library.IdolyLiveABIVersion.argtypes = []
        library.IdolyLiveABIVersion.restype = ctypes.c_uint32
        library.IdolyLiveFree.argtypes = [ctypes.c_void_p]
        library.IdolyLiveFree.restype = None
        library.IdolyLiveSimulate.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t)]
        library.IdolyLiveSimulate.restype = ctypes.c_int
    except (OSError, AttributeError) as error:
        raise ABIError("Cannot load the library's three C ABI symbols") from error
    _CONFIGURED_LIBRARIES[key] = library
    return library


def _invalid_call(library, name: str, payload: bytes | None, *, length: int | None = None,
                  missing_output: int | None = None) -> dict:
    # Allocate the complete declared input, including the oversized case, so
    # these checks never rely on an unreadable pointer/length pair.
    data = ctypes.create_string_buffer(payload) if payload is not None else None
    before = data.raw if data is not None else None
    output, failure = ctypes.c_void_p(), ctypes.c_void_p()
    output_length, failure_length = ctypes.c_size_t(), ctypes.c_size_t()
    slots = [ctypes.byref(output), ctypes.byref(output_length),
             ctypes.byref(failure), ctypes.byref(failure_length)]
    if missing_output is not None:
        slots[missing_output] = None
    declared = len(payload) if payload is not None else 0
    if length is not None:
        declared = length
    code = library.IdolyLiveSimulate(data, declared, *slots)
    try:
        _require(code == 1, name + ": expected invalid-input status 1")
        _require(data is None or data.raw == before, name + ": caller input was modified")
        if missing_output is None:
            _require(output.value is None and output_length.value == 0,
                     name + ": failed call returned a result buffer")
            _require(failure.value is not None and 0 < failure_length.value <= MAX_BYTES,
                     name + ": missing or invalid error buffer length")
            raw_error = ctypes.string_at(failure, failure_length.value)
            try:
                raw_error.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise ABIError(name + ": error buffer is not UTF-8") from error
        return {"name": name, "status": code, "error_bytes": failure_length.value}
    finally:
        # Distinct output slots are supplied above. If a broken implementation
        # aliases allocations, avoid a second free while failing the contract.
        freed = set()
        for pointer in (output, failure):
            if pointer.value is not None and pointer.value not in freed:
                freed.add(pointer.value)
                library.IdolyLiveFree(pointer)


def check_abi(library: Path) -> dict:
    """Exercise the actual ABI and return a JSON-serializable success report.

    Raises ABIError/OSError for a failed check. No fixtures, subprocesses,
    downloads or simulation inputs are needed.
    """
    path = Path(library).resolve(strict=True)
    _require(path.is_file(), "Library must be a regular file")
    native = _load(path)
    version = native.IdolyLiveABIVersion()
    _require(version == ABI_VERSION, "Unsupported C ABI version: " + str(version))
    native.IdolyLiveFree(None)
    cases = [
        ("empty-object", b"{}", {}),
        ("malformed-json", b"{", {}),
        ("invalid-utf8-json", b"\xff", {}),
        ("wrong-json-type", b"[]", {}),
        ("unknown-input-version", b'{"input_version":2}', {}),
        ("unknown-json-field", b'{"input_version":1,"unknown_field":true}', {}),
        ("trailing-json-value", b'{"input_version":1}{}', {}),
        ("null-input", None, {}),
        ("null-input-positive-length", None, {"length": 1}),
        ("empty-input", b"", {}),
    ]
    results = [_invalid_call(native, name, payload, **options) for name, payload, options in cases]
    results.append(_invalid_call(native, "oversized-input", b" " * (MAX_BYTES + 1)))
    for slot in range(4):
        results.append(_invalid_call(native, "missing-output-slot-" + str(slot), b"{}",
                                     missing_output=slot))
    for index in range(16):
        _invalid_call(native, "repeated-invalid-" + str(index), b"{}")
    with ThreadPoolExecutor(max_workers=4) as executor:
        parallel = list(executor.map(
            lambda index: _invalid_call(native, "parallel-invalid-" + str(index), b"{}"), range(16)))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"format": 1, "ok": True, "library": str(path),
        "library_sha256": digest.hexdigest(), "platform": platform.system(), "machine": platform.machine(),
        "abi_version": version, "invalid_cases": results,
        "repeated_invalid_calls": 16, "parallel_invalid_calls": len(parallel), "parallel_workers": 4,
        "input_immutable": True, "error_buffers_caller_freed": True, "null_free_checked": True,
        "required_output_slots_checked": True, "full_simulation_tested": False,
        "official_score_equivalence": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True, help="Host-native .so or .dylib to load")
    parser.add_argument("--report", type=Path, help="Optional JSON report; stdout always receives the report")
    args = parser.parse_args(argv)
    try:
        report = check_abi(args.library)
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(serialized, encoding="utf-8")
    except (ABIError, OSError) as error:
        print("Native live ABI check failed: " + str(error), file=sys.stderr)
        return 1
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
