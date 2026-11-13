"""QA-only dispatch to the game's existing software AES, without changing AES.

The supported library already contains software CBC/ECB implementations with
the same C ABI as its ARM crypto implementations. Four entry branches select
those implementations on an emulator whose translator lacks AESIMC.
"""
from __future__ import annotations

import hashlib
import struct


ORIGINAL_SHA256 = "f8f64ab5424b6f692464e23cf47af9d399c4072b700c196e7b321e670b93fcc4"
ROUTES = {
    "AES_ECB_encrypt_Native": (0x2CB0, "AES_ECB_encrypt_C", 0x2208),
    "AES_ECB_decrypt_Native": (0x3118, "AES_ECB_decrypt_C", 0x2308),
    "AES_CBC_encrypt_Native": (0x372C, "AES_CBC_encrypt_C", 0x24C8),
    "AES_CBC_decrypt_Native": (0x3BC8, "AES_CBC_decrypt_C", 0x27FC),
}


class Image:
    def __init__(self, raw):
        if raw[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", raw, 18)[0] != 183:
            raise ValueError("Expected a little-endian ARM64 ELF")
        self.raw = raw
        self.segments = []
        for i in range(struct.unpack_from("<H", raw, 56)[0]):
            p = struct.unpack_from("<Q", raw, 32)[0] + i * struct.unpack_from("<H", raw, 54)[0]
            kind, flags, offset, address, _, files, memory, alignment = struct.unpack_from("<II6Q", raw, p)
            if kind == 1:
                self.segments.append((address, offset, files, memory))
        sections = []
        for i in range(struct.unpack_from("<H", raw, 60)[0]):
            p = struct.unpack_from("<Q", raw, 40)[0] + i * struct.unpack_from("<H", raw, 58)[0]
            sections.append(struct.unpack_from("<II4QII2Q", raw, p))
        self.symbols, self.relocations = {}, []
        for section in sections:
            if section[1] != 11:
                continue
            strings = sections[section[6]]
            symbols = []
            for offset in range(section[4], section[4] + section[5], section[9]):
                name, info, other, index, address, size = struct.unpack_from("<IBBHQQ", raw, offset)
                start = strings[4] + name
                name = raw[start:raw.index(b"\0", start)].decode("ascii")
                symbols.append((name, address, size))
                if address:
                    self.symbols[name] = (address, size)
            for relocation in sections:
                if relocation[1] == 4 and sections[relocation[6]] == section:
                    for offset in range(relocation[4], relocation[4] + relocation[5], relocation[9]):
                        target, info, addend = struct.unpack_from("<QQq", raw, offset)
                        symbol = symbols[info >> 32]
                        self.relocations.append((target, info & 0xFFFFFFFF, addend, symbol))

    def offset(self, address):
        for start, offset, size, _ in self.segments:
            if start <= address < start + size:
                return offset + address - start
        raise ValueError("ELF address is outside file-backed segments")


def patch_library(raw: bytes):
    if hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("FastAES does not match the audited 6.1.1 library")
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

    image = Image(raw)
    # These contiguous functions are KeyExpansion, Cipher, InvCipher, XorWithIv
    # and all four _C entry points. Their direct helper calls remain software.
    software = raw[image.offset(0x1260):image.offset(0x2AD8)]
    instructions = list(Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(software, 0x1260))
    if sum(item.size for item in instructions) != len(software):
        raise ValueError("Software AES range did not disassemble completely")
    if any(item.mnemonic.startswith(("aes", "sha", "pmull")) for item in instructions):
        raise ValueError("Software AES unexpectedly contains crypto extension instructions")
    patched, routes = bytearray(raw), []
    for name, (source, target_name, target) in ROUTES.items():
        if image.symbols.get(name, (None,))[0] != source or image.symbols.get(target_name, (None,))[0] != target:
            raise ValueError("Audited FastAES export addresses differ")
        offset = image.offset(source)
        branch = struct.pack("<I", 0x14000000 | (((target - source) // 4) & 0x3FFFFFF))
        patched[offset:offset + 4] = branch
        routes.append({"export": name, "target": target_name, "rva": hex(source),
                       "target_rva": hex(target), "file_offset": offset,
                       "original_hex": raw[offset:offset + 4].hex(), "patched_hex": branch.hex()})
    return bytes(patched), {"qa_only": True, "exact_production_client": False,
        "original_sha256": ORIGINAL_SHA256, "patched_sha256": hashlib.sha256(patched).hexdigest(),
        "changed_instruction_bytes": 16, "software_crypto_instructions": 0, "routes": routes}


def emulate(raw, name, payload, key, iv, padding, encrypt):
    """Execute real ARM64 AES code; hooks implement only libc byte operations."""
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn import arm64_const as reg

    image, base = Image(raw), 0x1000000
    machine = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    # The complete audited software AES code is under 8KiB. Repeated vector
    # loops need the same translated blocks rather than the default big cache.
    machine.ctl_set_tcg_buffer_size(1024 * 1024)
    machine.mem_map(base, 0x10000)
    for address, offset, size, _ in image.segments:
        machine.mem_write(base + address, raw[offset:offset + size])
    machine.mem_map(0x40000000, 0x20000)
    machine.mem_map(0x50000000, 0x20000)
    machine.mem_map(0x60000000, 0x1000)
    machine.mem_map(0x70000000, 0x10000)
    machine.mem_map(0x77700000, 0x1000)
    hooks = {}
    for index, (target, kind, addend, (symbol, address, _)) in enumerate(image.relocations):
        if kind == 1027:
            value = base + addend
        elif address:
            value = base + address
        else:
            value = 0x70000000 + index * 0x100
            hooks[value] = symbol
        machine.mem_write(base + target, struct.pack("<Q", value))

    def libc(cpu, address, size, unused):
        if address not in hooks:
            return
        symbol = hooks[address]
        out, source, length = (cpu.reg_read(r) for r in (reg.UC_ARM64_REG_X0, reg.UC_ARM64_REG_X1, reg.UC_ARM64_REG_X2))
        if symbol in ("memcpy", "__memcpy_chk"):
            cpu.mem_write(out, bytes(cpu.mem_read(source, length)))
        elif symbol == "memset":
            cpu.mem_write(out, bytes([source & 255]) * length)
        else:
            raise RuntimeError("Unexpected libc call in software AES: " + symbol)
        cpu.reg_write(reg.UC_ARM64_REG_PC, cpu.reg_read(reg.UC_ARM64_REG_X30))

    machine.hook_add(UC_HOOK_CODE, libc)
    output, incoming, key_address, iv_address = 0x40000000, 0x40004000, 0x40008000, 0x40009000
    machine.mem_write(output, b"\xa5" * (len(payload) + 32))
    if payload:
        machine.mem_write(incoming, payload)
    machine.mem_write(key_address, key)
    machine.mem_write(iv_address, iv)
    arguments = ([output, len(payload) + 16, incoming, len(payload), key_address, len(key), iv_address, padding]
                 if encrypt else [output, incoming, len(payload), key_address, len(key), iv_address, padding])
    for i, value in enumerate(arguments):
        machine.reg_write(getattr(reg, "UC_ARM64_REG_X" + str(i)), value)
    machine.reg_write(reg.UC_ARM64_REG_TPIDR_EL0, 0x60000000)
    machine.reg_write(reg.UC_ARM64_REG_SP, 0x50010000)
    machine.reg_write(reg.UC_ARM64_REG_X30, 0x77700000)
    machine.reg_write(reg.UC_ARM64_REG_X19, 0x1122334455667788)
    machine.emu_start(base + image.symbols[name][0], 0x77700000, count=2_000_000)
    if machine.reg_read(reg.UC_ARM64_REG_PC) != 0x77700000:
        raise ValueError("AES did not return before the instruction limit")
    if machine.reg_read(reg.UC_ARM64_REG_SP) != 0x50010000 or machine.reg_read(reg.UC_ARM64_REG_X19) != 0x1122334455667788:
        raise ValueError("AES violated the caller's ABI")
    length = machine.reg_read(reg.UC_ARM64_REG_W0)
    if length > len(payload) + 16:
        raise ValueError("AES returned an unexpected length")
    if bytes(machine.mem_read(incoming, len(payload))) != payload or bytes(machine.mem_read(key_address, len(key))) != key or bytes(machine.mem_read(iv_address, 16)) != iv:
        raise ValueError("AES modified the input, key or IV")
    return bytes(machine.mem_read(output, length))


def verify_vectors(original, patched):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    first = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    known = (
        ("2b7e151628aed2a6abf7158809cf4f3c", "3ad77bb40d7a3660a89ecaf32466ef97", "7649abac8119b246cee98e9b12e9197d"),
        ("8e73b0f7da0e6452c810f32b809079e562f8ead2522c6b7b", "bd334f1d6e45f25ff712a214571fa5cc", "4f021db243bc633d7178183a9fa071e8"),
        ("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4", "f3eed1bdb5d2a03c064b5a7e3db181f8", "f58c4c04d6e5f1ba779eabfb5f7bfbd6"),
    )
    count = 0
    for key_hex, ecb_known, cbc_known in known:
        key = bytes.fromhex(key_hex)
        for mode, expected_first in (("ECB", ecb_known), ("CBC", cbc_known)):
            def encrypt(data):
                cipher = AES.new(key, AES.MODE_ECB) if mode == "ECB" else AES.new(key, AES.MODE_CBC, iv)
                return cipher.encrypt(data)
            if encrypt(first).hex() != expected_first:
                raise ValueError("NIST SP800-38A oracle mismatch")
            vectors = [(1, first * blocks) for blocks in (1, 2, 4)]
            vectors += [(2, bytes((i * 29 + 7) % 256 for i in range(length))) for length in (0, 1, 15, 16, 17, 31, 32, 63, 64)]
            for padding, plain in vectors:
                encrypted = encrypt(pad(plain, 16) if padding == 2 else plain)
                for image, suffix in ((original, "C"), (patched, "Native")):
                    for operation, source, expected in (("encrypt", plain, encrypted), ("decrypt", encrypted, plain)):
                        name = f"AES_{mode}_{operation}_{suffix}"
                        actual = emulate(image, name, source, key, iv, padding, operation == "encrypt")
                        if actual != expected:
                            raise ValueError(f"Software AES vector mismatch: {name}, key={len(key)}, padding={padding}, length={len(plain)}")
                        count += 1
    return {"arm64_execution_checks": count, "nist_sp800_38a": True, "modes": ["CBC", "ECB"],
            "key_bytes": [16, 24, 32], "padding": {"1": "None", "2": "PKCS7"},
            "original_software_and_patched_exports_match_oracle": True,
            "input_key_iv_preserved": True, "caller_abi_preserved": True}
