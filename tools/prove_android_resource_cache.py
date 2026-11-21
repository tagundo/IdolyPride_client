#!/usr/bin/env python3
"""Hermetically execute pinned Android SDK leaf methods with synthetic memory.

No game process, account data, network or game callback is executed. External
String.get_Chars / base virtual calls are explicit stubs. This verifies ABI and
field representation only, not physical-device shared-path compatibility.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
NATIVE_SHA256 = '68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3'

def prove_original_code(binary: bytes) -> dict:
    if type(binary) is not bytes or hashlib.sha256(binary).hexdigest() != NATIVE_SHA256:
        raise ValueError('Original Android native SHA256 differs')
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_X30, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_W0, UC_ARM64_REG_W1, UC_ARM64_REG_PC
    phoff = struct.unpack_from('<Q', binary, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', binary, 54)
    segments = []
    for i in range(phnum):
        typ, flags, off, addr, _, size, _, _ = struct.unpack_from('<II6Q', binary, phoff + i * phsize)
        if typ == 1:
            segments.append((addr, addr + size, off))

    def fileoff(address):
        return next((off + address - start for start, end, off in segments if start <= address < end))

    def code(uc, address, count=4096):
        base = address & ~4095
        uc.mem_map(base, 4096)
        uc.mem_write(base, binary[fileoff(base):fileoff(base) + 4096])

    def machine():
        uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.ctl_set_tcg_buffer_size(16 * 1024 * 1024)
        uc.mem_map(536870912, 65536)
        uc.mem_map(805306368, 65536)
        uc.mem_map(1073741824, 4096)
        uc.reg_write(UC_ARM64_REG_SP, 536903680)
        uc.reg_write(UC_ARM64_REG_X30, 1073741824)
        return uc
    results = []
    for size in [1, 16384, 0, -1]:
        uc = machine()
        code(uc, 141999724)
        uc.mem_map(141991936, 4096)
        args = [805306624, 805310464, 805314560, 805318656, 805322752]
        for i, value in enumerate(args):
            uc.reg_write(UC_ARM64_REG_X0 + i, value)
        uc.mem_write(args[3] + 40, struct.pack('<i', size))
        seen = []

        def hook(u, a, s, user):
            if a == 141992500:
                seen.append([u.reg_read(UC_ARM64_REG_X0 + i) for i in range(5)])
                u.reg_write(UC_ARM64_REG_X0, 3)
                u.emu_stop()
        uc.hook_add(UC_HOOK_CODE, hook)
        uc.emu_start(141999724, 0, count=32)
        expected = [*args[:3], size & (1 << 64) - 1, 0]
        if not seen == [expected]:
            raise ValueError('Original instruction proof mismatch')
        if not uc.reg_read(UC_ARM64_REG_X0) == 3:
            raise ValueError('Original instruction proof mismatch')
        results.append({'case': 'IsCached original tailcall', 'size': size, 'forwarded_size_signed_i64': size, 'auto_delete_argument': False, 'result_latest': 3})
    uc = machine()
    code(uc, 141999752)
    selfp, bucket, filename, item, klass, method, path = (805306624, 805310464, 805314560, 805318656, 805326848, 805330944, 805335040)
    uc.mem_write(selfp, struct.pack('<Q', klass))
    uc.mem_write(klass + 536, struct.pack('<QQ', 1073742080, method))
    for i, v in enumerate([selfp, bucket, filename, item, 1911]):
        uc.reg_write(UC_ARM64_REG_X0 + i, v)
    seen = []

    def pathhook(u, a, s, user):
        if a == 1073742080:
            seen.append([u.reg_read(UC_ARM64_REG_X0 + i) for i in range(4)])
            u.reg_write(UC_ARM64_REG_X0, path)
            u.emu_stop()
    uc.hook_add(UC_HOOK_CODE, pathhook)
    uc.emu_start(141999752, 0, count=16)
    if not (seen == [[selfp, bucket, filename, method]] and uc.reg_read(UC_ARM64_REG_X0) == path):
        raise ValueError('Original instruction proof mismatch')
    results.append({'case': 'GetFilePath original virtual tailcall', 'item_not_forwarded_to_base': True, 'returns_base_managed_string_unmodified': True})
    for value in ['Ab0_zZ', '12345', '1234567']:
        uc = machine()
        code(uc, 141939300)
        uc.mem_map(139223040, 4096)
        dest, text = (805306624, 805310464)
        uc.mem_write(dest, b'\xcc' * 8)
        uc.mem_write(text + 16, struct.pack('<I', len(value)) + value.encode('utf-16le'))
        uc.reg_write(UC_ARM64_REG_X0, dest)
        uc.reg_write(UC_ARM64_REG_X1, text)

        def chars(u, a, s, user):
            if a == 139225216:
                i = u.reg_read(UC_ARM64_REG_W1)
                u.reg_write(UC_ARM64_REG_W0, ord(value[i]))
                u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30))
            elif a == 1073741824:
                u.emu_stop()
        uc.hook_add(UC_HOOK_CODE, chars)
        uc.emu_start(141939300, 0, count=256)
        output = bytes(uc.mem_read(dest, 8))
        expected = value.encode() + b'\xcc' * 2 if len(value) == 6 else b'\xcc' * 8
        if not output == expected:
            raise ValueError('Original instruction proof mismatch')
        results.append({'case': 'ObjectName.Set original code', 'input': value, 'writes_exactly_six_ascii_bytes': len(value) == 6, 'other_lengths_unchanged': len(value) != 6})
    uc = machine()
    code(uc, 141873996)
    settings = 805306624
    uc.mem_write(settings + 56, bytes.fromhex('aabbccdd'))
    uc.reg_write(UC_ARM64_REG_X0, settings)
    uc.reg_write(UC_ARM64_REG_W1, 2)

    def returnhook(u, a, s, user):
        if a == 1073741824:
            u.emu_stop()
    uc.hook_add(UC_HOOK_CODE, returnhook)
    uc.emu_start(141873996, 0, count=16)
    if not bytes(uc.mem_read(settings + 56, 4)) == bytes.fromhex('02bbccdd'):
        raise ValueError('Original instruction proof mismatch')
    results.append({'case': 'OctoFullSettings.set_CachingType original code', 'mode': 2, 'field_width_bytes': 1, 'adjacent_bytes_preserved': True})
    uc = machine()
    code(uc, 141918464)
    uc.mem_map(168230912, 4096)
    uc.mem_write(168232714, b'\x01')
    instance, pending = (805306624, 805306880)
    uc.mem_write(instance + 56, struct.pack('<Q', pending))
    uc.mem_write(pending + 24, struct.pack('<I', 0))
    uc.reg_write(UC_ARM64_REG_X0, instance)
    uc.hook_add(UC_HOOK_CODE, returnhook)
    uc.emu_start(141918464, 0, count=32)
    if not uc.reg_read(UC_ARM64_REG_PC) == 1073741824:
        raise ValueError('Original instruction proof mismatch')
    results.append({'case': 'Downloader.Update original code', 'pending_count': 0, 'returns_without_external_call': True, 'metadata_initialized': True})
    for value in ['0123456789abcdef0011aabbccddeeff', '0123456789ABCDEF0011AABBCCDDEEFF']:
        uc = machine()
        code(uc, 141885480)
        uc.mem_map(168230912, 4096)
        uc.mem_write(168232618, b'\x01')
        uc.mem_map(161263616, 4096)
        uc.mem_map(139223040, 4096)
        dest, text, klass = (805306624, 805310464, 805314560)
        uc.mem_write(161267568, struct.pack('<Q', 805318656))
        uc.mem_write(805318656, struct.pack('<Q', klass))
        uc.mem_write(klass + 224, struct.pack('<I', 1))
        uc.mem_write(dest, b'\xcc' * 16)
        uc.mem_write(text + 16, struct.pack('<I', len(value)) + value.encode('utf-16le'))
        uc.reg_write(UC_ARM64_REG_X0, dest)
        uc.reg_write(UC_ARM64_REG_X1, text)

        def md5chars(u, a, s, user):
            if a == 139225216:
                i = u.reg_read(UC_ARM64_REG_W1)
                u.reg_write(UC_ARM64_REG_W0, ord(value[i]))
                u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30))
            elif a == 1073741824:
                u.emu_stop()
        uc.hook_add(UC_HOOK_CODE, md5chars)
        uc.emu_start(141885480, 0, count=1500)
        if not bytes(uc.mem_read(dest, 16)) == bytes.fromhex(value):
            raise ValueError('Original instruction proof mismatch')
        results.append({'case': 'MD5Value.Set original code', 'hex_case': 'upper' if value.isupper() else 'lower', 'raw16_match_standard_hex_decode': True})
    return {'schema': 1, 'status': 'PASS_HERMETIC_ORIGINAL_CODE', 'platform': 'android', 'native_sha256': NATIVE_SHA256, 'actual_gameplay_executed': False, 'external_calls_are_stubs': True, 'cases': results}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3,) * 2)
    if not 1 <= args.native.stat().st_size <= 256 * 1024 ** 2:
        parser.error('Native file exceeds input bounds')
    result = prove_original_code(args.native.read_bytes())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'cases': len(result['cases'])}))
if __name__ == '__main__':
    main()
