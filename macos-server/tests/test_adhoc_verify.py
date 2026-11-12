from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import hashlib
import struct

import pytest

spec = spec_from_file_location("cross_adhoc_verify", Path(__file__).resolve().parents[1]/"cross/adhoc_verify.py")
verifier = module_from_spec(spec)
spec.loader.exec_module(verifier)


def fixture(tmp_path):
    info = tmp_path/"Info.plist"; info.write_bytes(b"info metadata")
    resources = tmp_path/"CodeResources"; resources.write_bytes(b"sealed resources")
    identity = b"game.idolypride.localserver\0"
    hash_offset = 88+len(identity)+96
    length = hash_offset+32
    total = 36+length+12+8
    raw = bytearray(struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 2, 2, 40, 0, 0))
    raw += struct.pack("<6I", 0x32, 24, 1, 13 << 16, 13 << 16, 0)
    raw += struct.pack("<4I", 0x1D, 16, 256, total)
    raw += bytes(256-len(raw))
    req = struct.pack(">III", 0xFADE0C01, 12, 0)
    cd = bytearray(struct.pack(">9I4B", 0xFADE0C02, length, 0x20400, 2, hash_offset, 88, 3, 1, 256, 32, 2, 0, 12))
    cd += bytes(88-len(cd))+identity
    cd += hashlib.sha256(resources.read_bytes()).digest()+hashlib.sha256(req).digest()+hashlib.sha256(info.read_bytes()).digest()
    cd += hashlib.sha256(raw).digest()
    raw += struct.pack(">III6I", 0xFADE0CC0, total, 3, 0, 36, 2, 36+length, 65536, 36+length+12)
    raw += cd+req+struct.pack(">II", 0xFADE0B01, 8)
    path = tmp_path/"executable"; path.write_bytes(raw)
    return path, info, resources


def test_adhoc_signature_checks_code_and_all_bundle_metadata(tmp_path):
    path, info, resources = fixture(tmp_path)
    result = verifier.verify_adhoc(path, info=info, resources=resources, identifier="game.idolypride.localserver")
    assert result["code_page_sha256_verified"] == 1
    assert result["special_slots_verified"] == ["Info.plist", "requirements", "CodeResources"]
    assert result["cms_identity"] is None


@pytest.mark.parametrize("part", ["code", "info", "resources"])
def test_corruption_is_rejected(tmp_path, part):
    path, info, resources = fixture(tmp_path)
    target = {"code": path, "info": info, "resources": resources}[part]
    raw = bytearray(target.read_bytes()); raw[100 if part == "code" else 0] ^= 1; target.write_bytes(raw)
    with pytest.raises(ValueError, match="digest differs"):
        verifier.verify_adhoc(path, info=info, resources=resources)


def test_identity_and_nonadhoc_flags_rejected(tmp_path):
    path, info, resources = fixture(tmp_path)
    with pytest.raises(ValueError, match="identifier differs"):
        verifier.verify_adhoc(path, info=info, resources=resources, identifier="wrong.bundle")
    raw=bytearray(path.read_bytes()); struct.pack_into(">I", raw, 256+36+12, 0); path.write_bytes(raw)
    with pytest.raises(ValueError, match="policy"):
        verifier.verify_adhoc(path, info=info, resources=resources)
