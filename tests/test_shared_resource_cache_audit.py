"""Bounded native-contract parsing, with no client downloads or game process."""
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import audit_shared_resource_cache as audit
import prove_android_resource_cache as android
import prove_ios_resource_cache as ios


class TypeImage:
    """The raw pointer is zero where ELF RELA supplies the actual value."""

    def __init__(self):
        self.data = bytearray(512)
        self.relocations = {}

    @property
    def native(self):
        return bytes(self.data)

    def file_offset(self, address):
        if not 0 <= address < len(self.data):
            raise ValueError("Outside synthetic file")
        return address

    def read_pointer(self, address):
        return self.relocations.get(address, struct.unpack_from("<Q", self.data, address)[0])

    def type(self, address, kind, data=0, attributes=0):
        struct.pack_into("<QI", self.data, address, data, kind << 16 | attributes)


def test_generic_parameter_decodes_relocated_data_and_class_context():
    image = TypeImage()
    image.type(16, 21)
    image.relocations[16] = 64
    struct.pack_into("<QQ", image.data, 64, 144, 96)
    struct.pack_into("<I", image.data, 96, 1)
    struct.pack_into("<Q", image.data, 104, 128)
    struct.pack_into("<Q", image.data, 128, 176)
    image.type(144, 18, 1)
    image.type(176, 18, 2)
    assert audit.decode_type(image, 16, {1: "System.Action`1", 2: "Octo.DownloadError"}) == (
        "System.Action`1<Octo.DownloadError>")


def test_optional_boolean_remains_boolean_and_enum_retains_exact_type():
    image = TypeImage()
    image.type(16, 2, attributes=0x80001010)
    image.type(48, 17, 3)
    assert audit.decode_type(image, 16, {}) == "System.Boolean"
    assert audit.decode_type(image, 48, {3: "Octo.Caching.CacheState"}) == "Octo.Caching.CacheState"


def test_array_element_pointer_is_resolved_without_guessing_class():
    image = TypeImage()
    image.type(16, 29)
    image.relocations[16] = 48
    image.type(48, 5)
    assert audit.decode_type(image, 16, {}) == "System.Byte[]"


@pytest.mark.parametrize("damage", ["too-many-arguments", "recursive", "unknown-kind", "unknown-definition"])
def test_malformed_type_graphs_fail_closed(damage):
    image = TypeImage()
    image.type(16, 21, 64)
    struct.pack_into("<QQ", image.data, 64, 144, 96)
    struct.pack_into("<I", image.data, 96, 17)
    if damage == "recursive":
        image.type(16, 29, 16)
    elif damage == "unknown-kind":
        image.type(16, 255)
    elif damage == "unknown-definition":
        image.type(16, 18, 999)
    with pytest.raises(ValueError):
        audit.decode_type(image, 16, {})


def test_static_setup_and_instance_cache_have_different_native_arguments():
    parameters = [{"name": "settings", "type": "Octo.OctoFullSettings"},
                  {"name": "reset", "type": "System.Boolean"}]
    assert audit.native_parameters("Octo.OctoManager.Setup", True, parameters) == [
        "settings:Octo.OctoFullSettings", "reset:System.Boolean", "MethodInfo*"]
    assert audit.native_parameters("Octo.Caching.OctoCaching.IsCached", False, []) == [
        "this", "MethodInfo*"]


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_profile_extraction_rejects_unpinned_input_before_native_parsing(platform):
    with pytest.raises(ValueError, match="metadata SHA256 differs"):
        audit.extract_contracts(platform, b"untrusted", b"untrusted")


@pytest.mark.parametrize("prove", [android.prove_original_code, ios.prove_original_code])
def test_original_instruction_proofs_reject_unpinned_code_before_emulation(prove):
    with pytest.raises(ValueError):
        prove(b"untrusted native code")
