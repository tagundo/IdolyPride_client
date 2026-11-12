"""Verify a thin ARM64 ad-hoc CodeDirectory without treating empty CMS as X.509."""
from __future__ import annotations
import hashlib
from pathlib import Path
import struct


def verify_adhoc(path, *, info=None, resources=None, identifier=None):
    raw = Path(path).read_bytes()
    if len(raw) < 32 or struct.unpack_from("<IIII", raw) != (0xFEEDFACF, 0x100000C, 0, 2):
        raise ValueError("Expected a thin ARM64 Mach-O executable")
    count, size = struct.unpack_from("<II", raw, 16)
    at, end, signature, target = 32, 32+size, None, None
    for _ in range(count):
        if at+8 > end or end > len(raw): raise ValueError("Invalid Mach-O commands")
        command, length = struct.unpack_from("<II", raw, at)
        if length < 8 or at+length > end: raise ValueError("Invalid Mach-O command length")
        if command == 0x1D:
            if length != 16 or signature is not None: raise ValueError("Invalid signature command")
            signature = struct.unpack_from("<II", raw, at+8)
        if command == 0x32:
            if length < 24 or target is not None: raise ValueError("Invalid build version")
            target = struct.unpack_from("<II", raw, at+8)
        at += length
    if at != end or target != (1, 13 << 16) or signature is None:
        raise ValueError("Expected one macOS 13 signature/build version")
    offset, allocated = signature
    if offset < end or offset+allocated > len(raw): raise ValueError("Invalid signature bounds")
    magic, total, count = struct.unpack_from(">III", raw, offset)
    if magic != 0xFADE0CC0 or not 12+count*8 <= total <= allocated or count > 8:
        raise ValueError("Invalid signature superblob")
    blobs = {}
    ranges = []
    for i in range(count):
        slot, position = struct.unpack_from(">II", raw, offset+12+i*8)
        if slot in blobs or position < 12+count*8 or position+8 > total: raise ValueError("Invalid signature index")
        _, length = struct.unpack_from(">II", raw, offset+position)
        if length < 8 or position+length > total: raise ValueError("Invalid signature blob")
        if any(position < high and position+length > low for low, high in ranges): raise ValueError("Overlapping signature blob")
        ranges.append((position, position+length)); blobs[slot] = raw[offset+position:offset+position+length]
    cd = blobs.get(0, b"")
    if len(cd) < 88: raise ValueError("Missing modern CodeDirectory")
    magic, length, version, flags, hashes, ident, special, pages, limit = struct.unpack_from(">9I", cd)
    hash_size, algorithm, platform, exponent = struct.unpack_from("4B", cd, 36)
    if (magic != 0xFADE0C02 or length != len(cd) or version != 0x20400 or flags != 2
            or hash_size != 32 or algorithm != 2 or platform != 0 or not 12 <= exponent <= 16
            or special != 3 or limit != offset or pages != (limit+(1 << exponent)-1) >> exponent
            or hashes-special*32 < 88 or hashes+pages*32 > len(cd)):
        raise ValueError("Unexpected ad-hoc CodeDirectory policy/bounds")
    if not 88 <= ident < hashes-special*32: raise ValueError("Invalid signing identifier")
    identity = cd[ident:cd.index(b"\0", ident, hashes-special*32)].decode("utf-8")
    if identifier is not None and identity != identifier: raise ValueError("Signing identifier differs")
    for i in range(pages):
        digest = hashlib.sha256(raw[i*(1 << exponent):min((i+1)*(1 << exponent), limit)]).digest()
        if digest != cd[hashes+i*32:hashes+(i+1)*32]: raise ValueError("Code page digest differs")
    requirements = blobs.get(2)
    if requirements != struct.pack(">III", 0xFADE0C01, 12, 0): raise ValueError("Unexpected requirements")
    for slot, content in ((1, Path(info).read_bytes() if info else None), (2, requirements),
                          (3, Path(resources).read_bytes() if resources else None)):
        if content is None: raise ValueError("Bundle metadata is required for all special slots")
        if hashlib.sha256(content).digest() != cd[hashes-slot*32:hashes-(slot-1)*32]:
            raise ValueError("Signed special-slot digest differs")
    if set(blobs) not in ({0, 2}, {0, 2, 65536}): raise ValueError("Unexpected signature slots")
    if 65536 in blobs and blobs[65536] != struct.pack(">II", 0xFADE0B01, 8):
        raise ValueError("Ad-hoc signature must not contain a CMS identity")
    return {"ad_hoc": True, "code_page_sha256_verified": pages,
            "special_slots_verified": ["Info.plist", "requirements", "CodeResources"],
            "identifier": identity, "cdhash_sha256": hashlib.sha256(cd).hexdigest()[:40],
            "cms_identity": None, "actual_macos_codesign_execution": False}
