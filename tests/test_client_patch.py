import struct

import pytest

from idoly_local.client_patch import DEFAULT_ENDPOINT, OFFICIAL_API, literal_rows, patch_metadata, validate_endpoint


def metadata_fixture():
    strings = [b"unchanged literal", OFFICIAL_API, b"another literal"]
    table_size = len(strings) * 8
    pool_start = 256 + table_size
    pool = b"".join(strings)
    gap = b"\0" * (-(pool_start + len(pool)) % 8)
    tail = b"OTHER TABLE DATA THAT MUST SURVIVE"
    header = [0] * 64
    header[:8] = [0xFAB11BAF, 31, 256, table_size, pool_start, len(pool), pool_start + len(pool) + len(gap), len(tail)]
    rows = b""
    index = 0
    for value in strings:
        rows += struct.pack("<II", len(value), index)
        index += len(value)
    return struct.pack("<64I", *header) + rows + pool + gap + tail


@pytest.mark.parametrize("endpoint", [DEFAULT_ENDPOINT, "http://192.168.100.200:50051", "http://[::1]:50051",
                                     "https://a-very-long-private-server-name.example.org:50051"])
def test_metadata_relocation_preserves_other_sections_and_literals(endpoint):
    original = metadata_fixture()
    old_header, old_rows = literal_rows(original)
    patched, report = patch_metadata(original, endpoint)
    header, rows = literal_rows(patched)
    assert rows[1][3] == endpoint.encode()
    assert rows[0][3] == old_rows[0][3]
    assert rows[2][3] == old_rows[2][3]
    assert header[7] == old_header[7]
    assert header[6] - old_header[6] == report["inserted_bytes"]
    assert header[6] % 8 == old_header[6] % 8
    assert patched[header[6]:] == original[old_header[6]:]
    assert report["literal_indexes"] == [1]
    assert report["input_sha256"] != report["output_sha256"]
    assert original == metadata_fixture()


@pytest.mark.parametrize("endpoint", ["http://u:p@localhost:50051", "http://localhost/path", "http://localhost?q=x",
                                     "http://localhost/#x", "ftp://localhost", "http://localhost:0",
                                     "http://localhost:65536", "http://localhost:xyz", "http://local host",
                                     "http://localhost\n", "http://localhost\\x", "http://"])
def test_rejects_invalid_server_origin(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_trailing_slash_normalized_and_repatch_requires_original_client():
    patched, report = patch_metadata(metadata_fixture(), DEFAULT_ENDPOINT + "/")
    assert report["endpoint"] == DEFAULT_ENDPOINT
    with pytest.raises(ValueError, match="unmodified"):
        patch_metadata(patched)


def test_rejects_truncated_table_or_literal_data():
    original = metadata_fixture()
    for broken in [original[:20], original[:280], original[:300]]:
        with pytest.raises(ValueError):
            patch_metadata(broken)
    broken = bytearray(original)
    struct.pack_into("<I", broken, 256 + 4, 0xFFFFFFF0)
    with pytest.raises(ValueError, match="outside"):
        patch_metadata(bytes(broken))
