"""Exercise the package receipt verifier across real file-size boundaries."""
import hashlib
import json
import struct

import pytest

from tools import package_android_unified as package
from tools import stage_mp4_preview as delivery


@pytest.fixture
def native_receipt(tmp_path):
    # Minimal arm64 shared ELF with a correctly aligned load segment. This is a
    # receipt/file validation fixture, never evidence of device execution.
    image = bytearray(120)
    image[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HHI", image, 16, 3, 183, 1)
    struct.pack_into("<Q", image, 32, 64)
    struct.pack_into("<HH", image, 54, 56, 1)
    struct.pack_into("<IIQQQQQQ", image, 64, 1, 5, 0, 0, 0, len(image), len(image), 16384)
    library = tmp_path / "addon.so"
    library.write_bytes(image)
    root = tmp_path / "source"
    receipt_path = tmp_path / "receipt.json"
    sources = {}

    def source(name, size=1):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def validate():
        receipt_path.write_text(json.dumps({
            "schema": 1, "source_commit": "a" * 40, "abi": "arm64-v8a",
            "bytes": len(image), "sha256": hashlib.sha256(image).hexdigest(),
            "source_unchanged_during_build": True, "source_sha256": sources,
        }))
        return package.validate_native_bridge(library, receipt_path, root, "a" * 40)

    source("client-presentation/native/profile.json")
    source(package.NATIVE_BRIDGE_SOURCE, 2 * package.MIB + 512 * 1024)
    return source, validate, sources


def test_generated_bridge_source_over_two_mib_is_bound_to_its_receipt(native_receipt):
    _, validate, sources = native_receipt
    _, receipt = validate()
    assert receipt["source_sha256"] == sources


@pytest.mark.parametrize("name,size", [
    (package.NATIVE_BRIDGE_SOURCE, 4 * package.MIB + 1),
    ("client-presentation/native/another.hpp", 2 * package.MIB + 1),
])
def test_larger_bridge_allowance_does_not_admit_unbounded_or_other_sources(native_receipt, name, size):
    source, validate, _ = native_receipt
    source(name, size)
    with pytest.raises(ValueError, match="source is not regular or exceeds its byte bound"):
        validate()


def test_larger_translation_unit_still_requires_exact_compiled_bytes(native_receipt):
    source, validate, _ = native_receipt
    path = source(package.NATIVE_BRIDGE_SOURCE, 2 * package.MIB + 1)
    with path.open("r+b") as stream:
        stream.write(b"y")
    with pytest.raises(ValueError, match="source differs from current snapshot"):
        validate()


def test_native_receipt_input_count_remains_capped_at_sixty_four(native_receipt):
    source, validate, _ = native_receipt
    for index in range(62):
        source("client-presentation/native/receipt_" + str(index) + ".hpp")
    validate()
    source("client-presentation/native/one_too_many.hpp")
    with pytest.raises(ValueError, match="source receipt is incomplete"):
        validate()


def test_private_delivery_accepts_the_same_exact_larger_bridge(native_receipt, monkeypatch):
    source, _, values = native_receipt
    bridge = source(package.NATIVE_BRIDGE_SOURCE, 2 * package.MIB + 1)
    root = bridge.parents[2]
    monkeypatch.setattr(delivery, "ROOT", root)
    delivery.source_pins(values, root, set(values))


def test_private_delivery_does_not_extend_other_source_namespaces(tmp_path, monkeypatch):
    root = tmp_path / "root"
    base = root / "ios-unified/native"
    path = base / package.NATIVE_BRIDGE_SOURCE
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * (2 * package.MIB + 1))
    monkeypatch.setattr(delivery, "ROOT", root)
    values = {package.NATIVE_BRIDGE_SOURCE: hashlib.sha256(path.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match="regular_file_bound"):
        delivery.source_pins(values, base, set(values))
