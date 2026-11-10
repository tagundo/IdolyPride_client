"""Host-native adapter for the attributed Solis live-v5 C ABI, version 1.

The native engine receives prepared JSON and returns plain api.LiveResult
protobuf bytes. Schema validation and account settlement belong to the caller.
Go shared libraries remain loaded for the lifetime of this Python process.
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import threading

from .rpc import RpcCode, RpcFailure


_ABI_VERSION = 1
_MAX_BYTES = 16 * 1024 * 1024
_LOAD_LOCK = threading.Lock()
_LIBRARIES: dict[Path, ctypes.CDLL] = {}
# Retain rejected handles too: unloading a shared Go runtime is unsupported.
_LOADED_LIBRARIES: list[ctypes.CDLL] = []
_STATUS_CODES = {
    1: RpcCode.INVALID_ARGUMENT,
    2: RpcCode.UNIMPLEMENTED,
    3: RpcCode.DEADLINE_EXCEEDED,
    4: RpcCode.INTERNAL,
}


def _load(path: Path) -> ctypes.CDLL:
    try:
        canonical = Path(path).resolve(strict=True)
        if not canonical.is_file():
            raise OSError("Library is not a regular file")
    except (OSError, RuntimeError, TypeError, ValueError):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Native live engine library is unavailable") from None
    with _LOAD_LOCK:
        if canonical in _LIBRARIES:
            return _LIBRARIES[canonical]
        try:
            library = ctypes.CDLL(str(canonical))
            _LOADED_LIBRARIES.append(library)
            library.IdolyLiveABIVersion.argtypes = []
            library.IdolyLiveABIVersion.restype = ctypes.c_uint32
            library.IdolyLiveFree.argtypes = [ctypes.c_void_p]
            library.IdolyLiveFree.restype = None
            library.IdolyLiveSimulate.argtypes = [
                ctypes.c_void_p, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t),
            ]
            library.IdolyLiveSimulate.restype = ctypes.c_int
            if library.IdolyLiveABIVersion() != _ABI_VERSION:
                raise ValueError("Unsupported native live ABI")
        except Exception:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Native live engine cannot load C ABI version 1") from None
        _LIBRARIES[canonical] = library
        return library


def _serialize(prepared: dict) -> bytes:
    if not isinstance(prepared, dict):
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Prepared live input must be a JSON object")
    try:
        encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        chunks = []
        length = 0
        for part in encoder.iterencode(prepared):
            chunk = part.encode("utf-8")
            length += len(chunk)
            if length > _MAX_BYTES:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Prepared live input exceeds 16 MiB")
            chunks.append(chunk)
        return b"".join(chunks)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Prepared live input is not valid JSON") from None


def _invalid_response() -> RpcFailure:
    return RpcFailure(RpcCode.INTERNAL, "Native live engine returned an invalid C ABI response")


class NativeLiveEngine:
    """Load one host-native library and synchronously calculate prepared lives.

    Instances may be shared across threads. Every call owns distinct input and
    output slots; returned native allocations are copied and freed before return.
    """

    def __init__(self, library: Path):
        self._library = _load(library)

    def simulate(self, prepared: dict) -> bytes:
        raw = _serialize(prepared)
        data = ctypes.create_string_buffer(raw)
        output, failure = ctypes.c_void_p(), ctypes.c_void_p()
        output_length, failure_length = ctypes.c_size_t(), ctypes.c_size_t()
        try:
            status = self._library.IdolyLiveSimulate(
                data, len(raw), ctypes.byref(output), ctypes.byref(output_length),
                ctypes.byref(failure), ctypes.byref(failure_length),
            )
            # Check every length and both shapes before dereferencing anything.
            if output_length.value > _MAX_BYTES or failure_length.value > _MAX_BYTES:
                raise _invalid_response()
            if status == 0:
                if (output.value is None or output_length.value == 0
                        or failure.value is not None or failure_length.value != 0):
                    raise _invalid_response()
                return ctypes.string_at(output, output_length.value)
            if (status not in _STATUS_CODES or output.value is not None or output_length.value != 0
                    or failure.value is None or failure_length.value == 0):
                raise _invalid_response()
            detail = ctypes.string_at(failure, failure_length.value).decode("utf-8", errors="strict")
            raise RpcFailure(_STATUS_CODES[status], "Native live engine: " + detail)
        except RpcFailure:
            raise
        except Exception:
            raise _invalid_response() from None
        finally:
            freed = set()
            failed = False
            for pointer in (output, failure):
                if pointer.value is not None and pointer.value not in freed:
                    freed.add(pointer.value)
                    try:
                        self._library.IdolyLiveFree(pointer)
                    except Exception:
                        # Still attempt the other allocation if one release fails.
                        failed = True
            if failed:
                raise RpcFailure(RpcCode.INTERNAL, "Native live engine could not release its response") from None
