"""Versioned server capacity guards using metadata only, never large assets."""
import io
from pathlib import Path
import struct
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from tools import build_android_server_manual as tool


def inventory():
    """Represent the pinned APK shape without allocating its asset contents."""
    result = {}
    names = tool.MUTABLE_NAMES | tool.REMOVED_NAMES | tool.NATIVE_NAMES | {
        "classes.dex", "assets/chaquopy/bootstrap.imy"}
    for name in names:
        info = ZipInfo(name)
        info.compress_type = ZIP_STORED
        info.file_size = 128
        result[name] = info
    result[tool.pybundle.PAYLOAD].file_size = 84_041_457
    result[tool.pybundle.APP].compress_type = ZIP_DEFLATED
    # The actual pinned APK has roughly 30 MiB expanded outside ServerData.zip.
    for name in tool.NATIVE_NAMES:
        result[name].file_size = 3 * tool.MIB
        result[name].compress_type = ZIP_DEFLATED
    return result


def exact_sizes(payload_bytes):
    return {name: payload_bytes if name == tool.pybundle.PAYLOAD else 128
            for name in tool.MUTABLE_NAMES}


def test_payload_capacity_grows_without_relaxing_pinned_baseline_or_runtime_limits():
    assert tool.MAX_APK == 100 * tool.MIB
    assert tool.pybundle.MAX_APK == 128 * tool.MIB
    assert tool.pybundle.MAX_EXPANDED == 256 * tool.MIB
    assert tool.pybundle.MAX_MEMBERS == 512
    assert tool.pybundle.MAX_APP == 8 * tool.MIB
    assert tool.MAX_PAYLOAD == 256 * tool.MIB
    assert tool.MAX_PAYLOAD_MEMBERS == 1024
    assert tool.MAX_SERVER_APK == tool.MAX_SERVER_EXPANDED == 384 * tool.MIB
    assert tool.MIN_HEADROOM == 1024 * tool.MIB
    assert tool.SERVER_STAGE_HEADROOM == 512 * tool.MIB
    assert tool.MIN_ROOT_FREE == 150 * tool.MIB
    assert tool.MAX_CLEAN_INACTIVE_CREDIT == 256 * tool.MIB


@pytest.mark.parametrize("payload_mib", [101, 190, 220, 256])
def test_large_public_payload_has_bounded_one_apk_and_metadata_capacity(payload_mib):
    payload_bytes = payload_mib * tool.MIB
    plan = tool.capacity_plan(inventory(), payload_bytes)
    assert plan["schema"] == 1 and plan["policy"] == "server-library-single-apk-v2"
    assert plan["payload_bytes"] == payload_bytes
    assert payload_bytes < plan["apk_bytes"] <= tool.MAX_SERVER_APK
    assert plan["apk_bytes"] % tool.MIB == 0
    assert payload_bytes < plan["expanded_bytes"] <= tool.MAX_SERVER_EXPANDED
    assert plan["full_apk_copies"] == 1
    assert plan["staging_bytes"] == plan["apk_bytes"] + tool.SERVER_APK_METADATA_STAGING
    assert plan["staging_bytes"] <= tool.MAX_SERVER_APK + 8 * tool.MIB


def test_exact_compiled_sizes_reduce_conservative_default_reservation():
    payload_bytes = 220 * tool.MIB
    conservative = tool.capacity_plan(inventory(), payload_bytes)
    exact = tool.capacity_plan(inventory(), payload_bytes, exact_sizes(payload_bytes))
    assert exact["apk_bytes"] < conservative["apk_bytes"]
    assert exact["expanded_bytes"] < conservative["expanded_bytes"]
    assert exact["staging_bytes"] < conservative["staging_bytes"]


def test_capacity_includes_retained_zip_names_extras_and_comments():
    infos = inventory()
    payload_bytes = 220 * tool.MIB
    small = tool.capacity_plan(infos, payload_bytes)
    # Legal ZIP metadata lengths: enough to cross MiB rounding boundaries.
    for name in tool.NATIVE_NAMES:
        infos[name].extra = b"\xfe\xca\x60\xea" + b"x" * 60_000
        infos[name].comment = b"public metadata" * 4_000
    large = tool.capacity_plan(infos, payload_bytes)
    assert large["expanded_bytes"] == small["expanded_bytes"]
    assert large["apk_bytes"] >= small["apk_bytes"] + tool.MIB
    assert large["staging_bytes"] >= small["staging_bytes"] + tool.MIB


def test_removed_installer_assets_do_not_consume_new_server_capacity():
    infos = inventory()
    original = tool.capacity_plan(infos, 220 * tool.MIB)
    for name in tool.LEGACY_PRESENTATION_ASSETS | tool.REMOVED_NAMES:
        info = ZipInfo(name)
        info.file_size = tool.MAX_SERVER_APK
        info.compress_type = ZIP_STORED
        infos[name] = info
    assert tool.capacity_plan(infos, 220 * tool.MIB) == original


@pytest.mark.parametrize("size", [0, -1, True, 1.5, "220", 256 * tool.MIB + 1])
def test_payload_size_requires_a_positive_bounded_integer(size):
    with pytest.raises(ValueError):
        tool.capacity_plan(inventory(), size)


@pytest.mark.parametrize("change", ["missing", "extra", "mismatched-payload", "negative", "boolean", "over-app-cap"])
def test_exact_replacement_inventory_and_caps_cannot_be_overridden(change):
    payload_bytes = 220 * tool.MIB
    sizes = exact_sizes(payload_bytes)
    if change == "missing":
        sizes.pop(tool.pybundle.APP)
    elif change == "extra":
        sizes["assets/unapproved.bin"] = 128
    elif change == "mismatched-payload":
        sizes[tool.pybundle.PAYLOAD] -= 1
    elif change == "negative":
        sizes[tool.pybundle.APP] = -1
    elif change == "boolean":
        sizes[tool.pybundle.APP] = True
    elif change == "over-app-cap":
        sizes[tool.pybundle.APP] = tool.pybundle.MAX_APP + 1
    with pytest.raises(ValueError):
        tool.capacity_plan(inventory(), payload_bytes, sizes)


@pytest.mark.parametrize("change", ["missing-payload", "compressed-payload", "oversized-retained", "negative-retained", "bad-compression"])
def test_unexpected_retained_archive_structure_or_size_fails_closed(change):
    infos = inventory()
    if change == "missing-payload":
        infos.pop(tool.pybundle.PAYLOAD)
    elif change == "compressed-payload":
        infos[tool.pybundle.PAYLOAD].compress_type = ZIP_DEFLATED
    elif change == "oversized-retained":
        infos["classes.dex"].file_size = tool.MAX_SERVER_EXPANDED
    elif change == "negative-retained":
        infos["classes.dex"].file_size = -1
    elif change == "bad-compression":
        infos["classes.dex"].compress_type = 12
    with pytest.raises(ValueError):
        tool.capacity_plan(infos, 220 * tool.MIB)


def test_only_explicit_payload_member_override_accepts_more_than_512_entries():
    target = io.BytesIO()
    with ZipFile(target, "w") as output:
        for index in range(513):
            output.writestr(f"data/public/item-{index}.json", b"{}")
    with ZipFile(io.BytesIO(target.getvalue())) as archive:
        with pytest.raises(ValueError, match="bound"):
            tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED)
        infos = tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED, member_limit=1024)
        assert len(infos) == 513


@pytest.mark.parametrize("member_limit", [0, -1, True, 1025])
def test_member_override_retains_a_hard_ceiling(member_limit):
    with ZipFile(io.BytesIO(b"PK\x05\x06" + b"\0" * 18)) as archive:
        with pytest.raises(ValueError, match="bound"):
            tool.pybundle._members(archive, tool.pybundle.MAX_EXPANDED, member_limit=member_limit)


@pytest.mark.parametrize("same_device", [False, True])
def test_dynamic_staging_preserves_root_disk_reserve(monkeypatch, same_device):
    class Location:
        def __init__(self, name):
            self.name = name

        def stat(self):
            return SimpleNamespace(st_dev=1 if self.name == "root" or same_device else 2)

    monkeypatch.setattr(tool, "Path", lambda value: value)
    required = tool.capacity_plan(inventory(), 220 * tool.MIB)["staging_bytes"]
    floor = required + (tool.MIN_ROOT_FREE if same_device else 0)
    monkeypatch.setattr(tool.shutil, "disk_usage", lambda _: SimpleNamespace(free=floor))
    tool.staging_budget(Location("root"), Location("destination"), required)
    monkeypatch.setattr(tool.shutil, "disk_usage", lambda _: SimpleNamespace(free=floor - 1))
    with pytest.raises(ValueError, match="reserve"):
        tool.staging_budget(Location("root"), Location("destination"), required)


@pytest.fixture
def allocation_case(monkeypatch):
    calls = []
    state = {"direct": 0, "effective": 0, "tmpfs": True}
    monkeypatch.setattr(tool, "staging_budget", lambda root, destination, required: calls.append((root, destination, required)))

    def resource_guard(root):
        calls.append(("resource", root))
        return {"memory_direct_headroom": state["direct"],
                "memory_effective_headroom": state["effective"], "oom_kill": "2"}

    monkeypatch.setattr(tool, "_server_stage_guard", resource_guard)
    monkeypatch.setattr(tool, "_tmpfs", lambda _: state["tmpfs"])
    return state, calls


def test_tmpfs_peak_preserves_strict_direct_server_floor_without_cache_credit(allocation_case):
    state, calls = allocation_case
    future = tool.capacity_plan(inventory(), 220 * tool.MIB)["staging_bytes"]
    state["direct"] = tool.SERVER_STAGE_HEADROOM + future
    state["effective"] = state["direct"]
    report = tool._allocation_guard("root", "destination", future)
    assert calls == [("root", "destination", future), ("resource", "root")]
    assert report["future_staging_bytes"] == report["future_tmpfs_bytes"] == future
    assert report["projected_direct_headroom"] == report["ongoing_direct_floor"] == 512 * tool.MIB
    assert report["oom_kill"] == "2"
    state["direct"] -= 1
    with pytest.raises(ValueError, match="memory reserve"):
        tool._allocation_guard("root", "destination", future)
    state["direct"] += 1
    state["effective"] = 0  # Observed clean-cache credit is irrelevant to this direct reservation.
    assert tool._allocation_guard("root", "destination", future)["projected_direct_headroom"] == 512 * tool.MIB


def test_clean_credit_cannot_replace_projected_tmpfs_direct_floor(allocation_case):
    state, _ = allocation_case
    future = 300 * tool.MIB
    state["direct"] = tool.SERVER_STAGE_HEADROOM + future - 1
    state["effective"] = 16 * 1024 * tool.MIB
    with pytest.raises(ValueError, match="memory reserve"):
        tool._allocation_guard("root", "destination", future)


def test_non_tmpfs_staging_still_checks_server_memory_and_disk_guards(allocation_case, monkeypatch):
    state, calls = allocation_case
    state.update(tmpfs=False, direct=tool.SERVER_STAGE_HEADROOM, effective=0)
    report = tool._allocation_guard("root", "destination", 300 * tool.MIB)
    assert report["future_tmpfs_bytes"] == 0
    assert calls == [("root", "destination", 300 * tool.MIB), ("resource", "root")]

    def reject(_):
        raise ValueError("server resource guard")

    monkeypatch.setattr(tool, "_server_stage_guard", reject)
    with pytest.raises(ValueError, match="server resource guard"):
        tool._allocation_guard("root", "destination", 300 * tool.MIB)


@pytest.mark.parametrize("required", [0, -1, True, tool.MAX_SERVER_APK + tool.SERVER_APK_METADATA_STAGING + 1])
def test_invalid_staging_projection_is_rejected_before_filesystem_access(monkeypatch, required):
    monkeypatch.setattr(tool.shutil, "disk_usage", lambda _: pytest.fail("invalid size must not inspect disk"))
    with pytest.raises(ValueError, match="capacity"):
        tool._allocation_guard("root", "destination", required)


def test_tmpfs_detection_prefers_nested_mount_and_handles_escaped_paths(tmp_path, monkeypatch):
    destination = tmp_path / "public staging" / "nested"
    destination.mkdir(parents=True)
    escaped = str(destination.parent).replace(" ", r"\040")
    raw = (f"1 0 0:1 / / rw - ext4 root rw\n"
           f"2 1 0:2 / {escaped} rw - tmpfs tmpfs rw\n")

    class MountInfo:
        def open(self, mode):
            assert mode == "rb"
            return io.BytesIO(raw.encode())

    monkeypatch.setattr(tool, "Path", lambda value: MountInfo() if value == "/proc/self/mountinfo" else Path(value))
    assert tool._tmpfs(destination)
    raw += f"3 2 0:3 / {escaped}/nested rw - ext4 disk rw\n"
    assert not tool._tmpfs(destination)


def directory_zip(*, count=1, comment=b"", zip64=False):
    """Tiny real central records, optionally wrapped in a valid ZIP64 footer."""
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.comment = comment
        for index in range(count):
            archive.writestr(f"data/public/item-{index}.bin", b"x")
    raw = output.getvalue()
    eocd = len(raw) - 22 - len(comment)
    fields = struct.unpack_from("<4s4H2LH", raw, eocd)
    if not zip64:
        return bytearray(raw), {"eocd": eocd, "central": fields[6], "central_bytes": fields[5]}
    record = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
                         count, count, fields[5], fields[6])
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, eocd, 1)
    footer = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 65535, 65535,
                         0xffffffff, 0xffffffff, len(comment))
    return bytearray(raw[:eocd] + record + locator + footer + comment), {
        "eocd": eocd + 76, "central": fields[6], "central_bytes": fields[5],
        "zip64": eocd, "locator": eocd + 56}


@pytest.mark.parametrize("zip64,comment", [(False, b""), (False, b"x" * 65535), (True, b""), (True, b"public")])
def test_payload_directory_preflight_accepts_normal_and_zip64_single_disk(tmp_path, zip64, comment):
    raw, locations = directory_zip(zip64=zip64, comment=comment)
    path = tmp_path / "public-payload.zip"
    path.write_bytes(raw)
    assert tool.payload_directory_bounds(path) == {
        "members": 1, "central_directory_bytes": locations["central_bytes"]}


@pytest.mark.parametrize("change", [
    "declared-count-over-limit", "zero-count", "disk", "directory-disk", "different-disk-count",
    "truncated-comment", "missing-footer", "truncated-footer", "central-end", "too-small-central",
    "understated-count", "bad-central-signature", "empty-central-name", "oversized-central-name",
    "central-extra-past-end", "central-comment-past-end", "central-disk",
])
def test_malicious_directory_rejects_before_any_zipfile_index_allocation(tmp_path, monkeypatch, change):
    raw, locations = directory_zip(count=2 if change == "understated-count" else 1)
    eocd, central = locations["eocd"], locations["central"]
    if change in ("declared-count-over-limit", "zero-count", "understated-count"):
        count = {"declared-count-over-limit": 1025, "zero-count": 0, "understated-count": 1}[change]
        struct.pack_into("<2H", raw, eocd + 8, count, count)
    elif change in ("disk", "directory-disk", "different-disk-count"):
        struct.pack_into("<H", raw, eocd + {"disk": 4, "directory-disk": 6, "different-disk-count": 8}[change], 2)
    elif change == "truncated-comment":
        struct.pack_into("<H", raw, eocd + 20, 3)
    elif change == "missing-footer":
        raw[eocd:eocd + 4] = b"NONE"
    elif change == "truncated-footer":
        del raw[-5:]
    elif change == "central-end":
        struct.pack_into("<L", raw, eocd + 16, central + 1)
    elif change == "too-small-central":
        struct.pack_into("<2L", raw, eocd + 12, 45, eocd - 45)
    elif change == "bad-central-signature":
        raw[central:central + 4] = b"NONE"
    else:
        field, value = {"empty-central-name": (28, 0), "oversized-central-name": (28, 241),
                        "central-extra-past-end": (30, 65535), "central-comment-past-end": (32, 65535),
                        "central-disk": (34, 1)}[change]
        struct.pack_into("<H", raw, central + field, value)
    path = tmp_path / "untrusted-payload.zip"
    path.write_bytes(raw)

    def unexpected(*args, **kwargs):
        pytest.fail("Rejected directory must not construct ZipFile or open baseline assets")

    monkeypatch.setattr(tool, "ZipFile", unexpected)
    baseline = SimpleNamespace(open=unexpected)
    with pytest.raises(ValueError):
        tool._validate_legacy_base_structure(path, tool.pybundle.digest(path), baseline)


def test_forged_small_count_cannot_hide_more_than_1024_actual_central_entries(tmp_path, monkeypatch):
    raw, locations = directory_zip(count=1025)
    struct.pack_into("<2H", raw, locations["eocd"] + 8, 1, 1)
    path = tmp_path / "many-tiny-entries.zip"
    path.write_bytes(raw)
    monkeypatch.setattr(tool, "ZipFile", lambda *a, **k: pytest.fail("must reject before ZipFile"))
    with pytest.raises(ValueError):
        tool.payload_directory_bounds(path)


def test_huge_sparse_central_directory_rejects_without_reading_it(tmp_path, monkeypatch):
    path = tmp_path / "sparse-directory.zip"
    central_bytes = 2 * tool.MIB + 1
    with path.open("wb") as stream:
        stream.seek(central_bytes)
        stream.write(struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1,
                                 central_bytes, 0, 0))
    monkeypatch.setattr(tool, "ZipFile", lambda *a, **k: pytest.fail("must reject before ZipFile"))
    with pytest.raises(ValueError, match="allocation bound"):
        tool.payload_directory_bounds(path)


@pytest.mark.parametrize("change", ["locator-signature", "locator-disk", "locator-disks", "record-offset",
                                     "record-signature", "record-width", "record-disk", "record-directory-disk",
                                     "record-count-mismatch", "record-count-over-limit", "record-central-end"])
def test_malformed_zip64_footers_are_bounded_before_zipfile(tmp_path, monkeypatch, change):
    raw, locations = directory_zip(zip64=True)
    record, locator = locations["zip64"], locations["locator"]
    if change == "locator-signature":
        raw[locator:locator + 4] = b"NONE"
    elif change == "locator-disk":
        struct.pack_into("<L", raw, locator + 4, 1)
    elif change == "locator-disks":
        struct.pack_into("<L", raw, locator + 16, 2)
    elif change == "record-offset":
        struct.pack_into("<Q", raw, locator + 8, len(raw))
    elif change == "record-signature":
        raw[record:record + 4] = b"NONE"
    elif change == "record-width":
        struct.pack_into("<Q", raw, record + 4, 43)
    elif change == "record-disk":
        struct.pack_into("<L", raw, record + 16, 1)
    elif change == "record-directory-disk":
        struct.pack_into("<L", raw, record + 20, 1)
    elif change == "record-count-mismatch":
        struct.pack_into("<Q", raw, record + 24, 2)
    elif change == "record-count-over-limit":
        struct.pack_into("<2Q", raw, record + 24, 1025, 1025)
    elif change == "record-central-end":
        struct.pack_into("<Q", raw, record + 48, locations["central"] + 1)
    path = tmp_path / "untrusted-zip64.zip"
    path.write_bytes(raw)
    monkeypatch.setattr(tool, "ZipFile", lambda *a, **k: pytest.fail("must reject before ZipFile"))
    with pytest.raises(ValueError):
        tool.payload_directory_bounds(path)
