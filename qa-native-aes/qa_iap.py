"""Opt-in emulator QA patch for one store initializer, never transactions.

The original managed success factory still allocates PurchaseInitResult. This
only lets a disposable emulator without a Play account observe later game UI;
it does not initialize a store or modify purchase, receipt or grant functions.
"""
from __future__ import annotations

import hashlib
import struct

from qa_fast_aes import Image


ORIGINAL_SHA256 = "4517381b0dbeae559d79832797f0c57c78ba6f37cf7d3544a58d0f31f2b8def3"
INITIALIZE = 0x87B61AC
FACTORY = 0x87B520C
IS_SUCCESS = 0x87B51EC
ORIGINAL_PROLOGUE = bytes.fromhex("ffc303d1fe5300f9fa670ba9f85f0ca9f6570da9f44f0ea9dac500d0d9900090")
FACTORY_BODY = bytes.fromhex(
    "fe0f1ef8f44f01a9d3c500f0d49000b0686a6b3994a644f9c8000037c09000b0"
    "00a444f94793e79628008052686a2b39800240f9d593e796e1031faaf30300aa"
    "692afb97e00313aaf44f41a9fe0742f8c0035fd6")
SUCCESS_GETTER = bytes.fromhex("080840f91f0100f1e0179f1ac0035fd6")


def initializer_stub():
    # UniTask<PurchaseInitResult> is 24 bytes, returned through hidden x8.
    # A real managed object is required: its IsSuccess getter reads Error+0x10.
    delta = FACTORY - (INITIALIZE + 12)
    words = (0xA9BF7BF3, 0xAA0803F3, 0xAA1F03E0,
             0x94000000 | ((delta // 4) & 0x3FFFFFF),
             0xA900027F, 0xF9000A7F, 0xA8C17BF3, 0xD65F03C0)
    return struct.pack("<8I", *words)


def _check_helpers(raw, image):
    for address, expected in ((FACTORY, FACTORY_BODY), (IS_SUCCESS, SUCCESS_GETTER)):
        offset = image.offset(address)
        if raw[offset:offset + len(expected)] != expected:
            raise ValueError("Audited managed IAP result factory/getter differs")


def patch_initializer(raw):
    if hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("IAP QA requires the audited 6.1.1 local-bootstrap library")
    image = Image(raw)
    _check_helpers(raw, image)
    offset = image.offset(INITIALIZE)
    if raw[offset:offset + 32] != ORIGINAL_PROLOGUE:
        raise ValueError("Audited UnityPurchaseManager.InitializeAsync prologue differs")
    patched = bytearray(raw)
    patched[offset:offset + 32] = initializer_stub()
    return bytes(patched), {
        "qa_only": True, "emulator_no_store": True, "exact_production_client": False,
        "original_sha256": ORIGINAL_SHA256,
        "patched_sha256": hashlib.sha256(patched).hexdigest(),
        "method": "Qua.InAppPurchasing.UnityPurchaseManager.InitializeAsync",
        "rva": hex(INITIALIZE), "file_offset": offset, "replacement_bytes": 32,
        "original_hex": ORIGINAL_PROLOGUE.hex(), "patched_hex": initializer_stub().hex(),
        "managed_factory": {"name": "PurchaseInitResult.CreateSuccessResult", "rva": hex(FACTORY)},
        "return": "24-byte UniTask: source=null, result=managed factory object, token=0",
        "store_initialized": False, "purchase_receipt_grant_functions_modified": False,
    }


def verify_abi(original, patched):
    """Execute the real stub, factory and IsSuccess getter under ARM64 Unicorn.

    Only IL2CPP metadata initialization, allocation and Object.ctor are hooked.
    No store code runs. Test both original factory initialization flag paths,
    including caller-saved x8 clobbering by runtime calls.
    """
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn import arm64_const as reg

    image = Image(original)
    _check_helpers(original, image)
    offset = image.offset(INITIALIZE)
    # The real inputs are large ELF images. Compare the same exact ranges
    # without allocating another pair of whole-image byte slices.
    original_view, patched_view = memoryview(original), memoryview(patched)
    if (len(patched) != len(original) or patched_view[offset:offset + 32] != initializer_stub()
            or patched_view[:offset] != original_view[:offset]
            or patched_view[offset + 32:] != original_view[offset + 32:]):
        raise ValueError("IAP verification permits only the 32-byte initializer replacement")
    for initialized in (False, True):
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        # These probes execute fewer than 220 instructions over three tiny
        # functions; a small translation cache preserves every ABI assertion.
        cpu.ctl_set_tcg_buffer_size(1024 * 1024)
        pages = set()

        def map_page(address):
            page = address & ~0xFFF
            if page not in pages:
                cpu.mem_map(page, 0x1000)
                pages.add(page)

        for address, size in ((INITIALIZE, 32), (FACTORY, len(FACTORY_BODY)), (IS_SUCCESS, len(SUCCESS_GETTER))):
            map_page(address)
            start = image.offset(address)
            cpu.mem_write(address, patched[start:start + size])
        metadata_init, allocate, object_ctor = 0x4199F4C, 0x419A194, 0x867FBF0
        flag, slot = 0xA070ADA, 0x99CE948
        handle, managed_class, result_object = 0x60002000, 0x60003000, 0x60001000
        result, stack, stop = 0x61000000, 0x62000800, 0x63000000
        for address in (metadata_init, allocate, object_ctor, flag, slot, handle, managed_class,
                        result_object, result, stack, stop):
            map_page(address)
        cpu.mem_write(flag, bytes([initialized]))
        cpu.mem_write(slot, struct.pack("<Q", handle))
        cpu.mem_write(handle, struct.pack("<Q", managed_class))
        cpu.mem_write(result, b"\xA5" * 32)
        calls = []

        def runtime(machine, address, size, unused):
            if address not in (metadata_init, allocate, object_ctor):
                return
            if machine.reg_read(reg.UC_ARM64_REG_SP) % 16:
                raise ValueError("Managed factory runtime call has a misaligned stack")
            arg0, arg1 = (machine.reg_read(r) for r in (reg.UC_ARM64_REG_X0, reg.UC_ARM64_REG_X1))
            expected = {metadata_init: handle, allocate: managed_class, object_ctor: result_object}[address]
            if arg0 != expected or (address == object_ctor and arg1 != 0):
                raise ValueError("Managed factory runtime call arguments differ")
            calls.append(address)
            # Real managed allocation zero-initializes its Error reference.
            if address == allocate:
                machine.mem_write(result_object, b"\0" * 32)
            return_to = machine.reg_read(reg.UC_ARM64_REG_X30)
            for number in range(18):
                machine.reg_write(getattr(reg, "UC_ARM64_REG_X" + str(number)), 0xDEAD0000 + number)
            machine.reg_write(reg.UC_ARM64_REG_X0, result_object if address == allocate else 0)
            machine.reg_write(reg.UC_ARM64_REG_PC, return_to)

        cpu.hook_add(UC_HOOK_CODE, runtime)
        saved = {number: 0xABC00000 + number for number in range(19, 30)}
        for number, value in saved.items():
            cpu.reg_write(getattr(reg, "UC_ARM64_REG_X" + str(number)), value)
        cpu.reg_write(reg.UC_ARM64_REG_SP, stack)
        cpu.reg_write(reg.UC_ARM64_REG_X8, result)
        cpu.reg_write(reg.UC_ARM64_REG_X30, stop)
        cpu.emu_start(INITIALIZE, stop, count=200)
        expected_calls = ([metadata_init] if not initialized else []) + [allocate, object_ctor]
        if calls != expected_calls or cpu.reg_read(reg.UC_ARM64_REG_PC) != stop:
            raise ValueError("Managed success factory did not execute and return exactly once")
        if (cpu.reg_read(reg.UC_ARM64_REG_SP) != stack or cpu.reg_read(reg.UC_ARM64_REG_X30) != stop or any(
                cpu.reg_read(getattr(reg, "UC_ARM64_REG_X" + str(number))) != value
                for number, value in saved.items())):
            raise ValueError("IAP QA initializer violated the caller's callee-saved ABI")
        if bytes(cpu.mem_read(result, 32)) != struct.pack("<QQQ", 0, result_object, 0) + b"\xA5" * 8:
            raise ValueError("IAP QA initializer returned a different UniTask or overwrote its boundary")
        if cpu.mem_read(flag, 1) != b"\x01":
            raise ValueError("Original factory metadata initialization flag was not respected")
        cpu.reg_write(reg.UC_ARM64_REG_X0, result_object)
        cpu.reg_write(reg.UC_ARM64_REG_X30, stop)
        cpu.emu_start(IS_SUCCESS, stop, count=20)
        if cpu.reg_read(reg.UC_ARM64_REG_W0) != 1:
            raise ValueError("Original PurchaseInitResult.IsSuccess rejected the factory object")
    return {"arm64_execution_checks": 2, "real_managed_factory_and_success_getter_executed": True,
            "runtime_hooks": ["metadata initialization", "managed allocation", "System.Object.ctor"],
            "factory_called_once": True, "hidden_x8_preserved_across_runtime_calls": True,
            "callee_saved_x19_through_x29_and_sp_preserved": True,
            "unitask_source_null_result_factory_object_token_zero": True,
            "return_buffer_boundary_preserved": True, "store_purchase_or_grant_code_executed": False}
