"""Package an isolated PlayCover client pointed at a user-selected local server.

PlayCover must re-sign the resulting IPA. The default build combines API/Octo
routing and HTTP transport with version-locked local authentication bootstrap
patches. An optional verified presentation bridge is composed after bootstrap.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import struct
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from urllib.parse import urlsplit

from .client_patch import literal_rows, patch_metadata


@dataclass(frozen=True)
class IOSProfile:
    ipa_sha256: str
    unity_sha256: str
    metadata_sha256: str
    game_version: str = "6.1.1"
    game_build: str = "156"
    octo_literal_index: int = 29810
    unity_settings_sha256: str = "c1e01c54c9e6da21cfbffd30f0f602b387a67f5c03ccb12a71c2b9183d77d56c"
    unity_settings_patched_sha256: str = "1c49cb988699c2344f0c1e186ad8cd1ba59984fe200cf243a7c524d07ba1644c"
    unity_settings_size: int = 20895388
    unity_http_offset: int = 2120


PROFILE_6_1_1 = IOSProfile(
    ipa_sha256="33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848",
    unity_sha256="b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",
    metadata_sha256="d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda",
)
DEFAULT_ENDPOINT = "http://127.0.0.1:50051"
DEFAULT_BUNDLE_ID = "game.qualiarts.idolypride.local"
_METADATA = "Data/Managed/Metadata/global-metadata.dat"
_UNITY = "Frameworks/UnityFramework.framework/UnityFramework"
_UNITY_SETTINGS = "Data/globalgamemanagers"
_OFFICIAL_OCTO = b"https://api.octo-cloud.com/"
_LOCAL_OCTO = b"http://127.0.0.1:8080/"
_PRESENTATION = "Frameworks/IdolyPresentation.dylib"
_PRESENTATION_LOAD = "@loader_path/../IdolyPresentation.dylib"
_MAX_PRESENTATION_PLAN_BYTES = 256 * 1024
_MAX_PRESENTATION_LIBRARY_BYTES = 8 * 1024 * 1024
_MAX_PRESENTATION_BUILD_BYTES = 64 * 1024
_COPY_BYTES = 128 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def macho_info(data: bytes) -> dict:
    """Check that the executable is a decrypted little-endian ARM64 Mach-O."""
    if len(data) < 32 or data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Expected a thin 64-bit Mach-O executable")
    _, cpu, _, _, count, command_bytes, _, _ = struct.unpack_from("<8I", data)
    if cpu != 0x0100000C:
        raise ValueError("Expected an ARM64 iOS executable")
    cursor = 32
    command_end = cursor + command_bytes
    if command_end > len(data):
        raise ValueError("Mach-O load commands exceed file bounds")
    encryption = []
    for _ in range(count):
        if cursor + 8 > command_end:
            raise ValueError("Malformed Mach-O load commands")
        command, size = struct.unpack_from("<II", data, cursor)
        if size < 8 or cursor + size > command_end:
            raise ValueError("Malformed Mach-O load command size")
        if command in (0x21, 0x2C):
            if size < 20:
                raise ValueError("Malformed Mach-O encryption command")
            _, _, offset, length, cryptid = struct.unpack_from("<5I", data, cursor)
            if cryptid != 0:
                raise ValueError("Input executable is encrypted; use the decrypted IPA")
            encryption.append({"offset": offset, "bytes": length, "cryptid": cryptid})
        cursor += size
    if cursor != command_end:
        raise ValueError("Mach-O load command count does not match its size")
    return {"architecture": "arm64", "decrypted": True, "encryption_commands": encryption,
            "sha256": _sha256(data)}


def _is_signature(name: str) -> bool:
    return "/_CodeSignature/" in name or name.endswith("/embedded.mobileprovision")


def _bounded_file(path: Path, limit: int, label: str) -> bytes:
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError(f"Invalid {label} size")
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate presentation plan field")
        result[key] = value
    return result


def _patch_octo_origin(metadata: bytes, literal_index: int) -> tuple[bytes, dict]:
    """Change the one original SDK origin without moving metadata or SDK state."""
    header, rows = literal_rows(metadata)
    selected = [row for row in rows if row[3] == _OFFICIAL_OCTO]
    if len(selected) != 1 or selected[0][0] != literal_index:
        raise ValueError("Original iOS Octo origin literal does not match its profile")
    number, row_offset, data_index, value = selected[0]
    for other, _, index, data in rows:
        if other != number and max(index, data_index) < min(index + len(data), data_index + len(value)):
            raise ValueError("Octo origin overlaps another metadata literal")
    absolute = header[4] + data_index
    mutable = bytearray(metadata)
    struct.pack_into("<I", mutable, row_offset, len(_LOCAL_OCTO))
    mutable[absolute:absolute + len(value)] = _LOCAL_OCTO.ljust(len(value), b"\0")
    result = bytes(mutable)
    checked_header, checked = literal_rows(result)
    if (checked_header != header or len(result) != len(metadata)
            or checked[number][3] != _LOCAL_OCTO
            or any(before != after for before, after in zip(rows, checked) if before[0] != number)):
        raise ValueError("Octo origin replacement verification failed")
    return result, {"literal_index": number, "row_offset": row_offset, "value_offset": absolute,
                    "origin": _LOCAL_OCTO.decode("ascii"), "metadata_layout_preserved": True,
                    "input_sha256": _sha256(metadata), "output_sha256": _sha256(result)}


def _patch_unity_http(data: bytes, profile: IOSProfile) -> tuple[bytes, dict]:
    """Apply the audited iOS PlayerSettings HTTP transport policy, and nothing else."""
    if len(data) != profile.unity_settings_size or _sha256(data) != profile.unity_settings_sha256:
        raise ValueError("iOS Unity PlayerSettings SHA-256 or size differs from its profile")
    offset = profile.unity_http_offset
    if (len(data) < 40 or struct.unpack_from(">I", data, 8)[0] != 22
            or struct.unpack_from(">Q", data, 32)[0] != 1264
            or not 0 <= offset <= len(data) - 4 or struct.unpack_from("<i", data, offset)[0] != 0):
        raise ValueError("iOS Unity PlayerSettings HTTP field does not match its profile")
    mutable = bytearray(data)
    struct.pack_into("<i", mutable, offset, 2)
    result = bytes(mutable)
    if _sha256(result) != profile.unity_settings_patched_sha256:
        raise ValueError("iOS Unity HTTP transport output SHA-256 differs from its profile")
    return result, {"member": _UNITY_SETTINGS, "unity_version": "2022.3.57f1",
                    "serialized_file_version": 22, "player_settings_class_id": 129,
                    "player_settings_path_id": 1, "field": "insecureHttpOption",
                    "field_offset": offset, "original_value": 0, "value": 2,
                    "input_sha256": profile.unity_settings_sha256,
                    "output_sha256": profile.unity_settings_patched_sha256}


def _add_presentation_load(native: bytes) -> tuple[bytes, dict]:
    """Add one load command in verified zero header padding, without moving code."""
    macho_info(native)
    count, command_bytes = struct.unpack_from("<II", native, 16)
    old_end = 32 + command_bytes
    cursor = 32
    text_offsets = []
    load_commands = (0xC, 0x80000018, 0x8000001F, 0x80000023, 0x20)
    for _ in range(count):
        command, size = struct.unpack_from("<II", native, cursor)
        if size % 8:
            raise ValueError("Unaligned Mach-O load command")
        if command in load_commands:
            if size < 24:
                raise ValueError("Malformed dylib load command")
            name_offset = struct.unpack_from("<I", native, cursor + 8)[0]
            if not 24 <= name_offset < size:
                raise ValueError("Malformed dylib load path")
            end = native.find(b"\0", cursor + name_offset, cursor + size)
            if end < 0:
                raise ValueError("Unterminated dylib load path")
            if native[cursor + name_offset:end].rsplit(b"/", 1)[-1] == b"IdolyPresentation.dylib":
                raise ValueError("Presentation dylib load command already exists")
        if command == 0x19:
            if size < 72:
                raise ValueError("Truncated Mach-O segment")
            sections = struct.unpack_from("<I", native, cursor + 64)[0]
            if size != 72 + sections * 80:
                raise ValueError("Malformed Mach-O section table")
            if native[cursor + 8:cursor + 24].rstrip(b"\0") == b"__TEXT":
                file_offset, file_bytes = struct.unpack_from("<QQ", native, cursor + 40)
                if file_offset + file_bytes > len(native):
                    raise ValueError("Mach-O text segment exceeds file bounds")
                for index in range(sections):
                    section = cursor + 72 + index * 80
                    length = struct.unpack_from("<Q", native, section + 40)[0]
                    offset = struct.unpack_from("<I", native, section + 48)[0]
                    flags = struct.unpack_from("<I", native, section + 64)[0]
                    if length and offset and flags & 0xFF not in (1, 12, 18):
                        if offset < file_offset or offset + length > file_offset + file_bytes:
                            raise ValueError("Mach-O text section exceeds segment bounds")
                        text_offsets.append(offset)
        cursor += size
    if not text_offsets:
        raise ValueError("Cannot establish free Mach-O header padding")
    path = _PRESENTATION_LOAD.encode("ascii") + b"\0"
    size = (24 + len(path) + 7) & ~7
    first_section = min(text_offsets)
    if old_end + size > first_section or any(native[old_end:old_end + size]):
        raise ValueError("No verified zero header padding; refusing to move code")
    output = bytearray(native)
    command = struct.pack("<6I", 0xC, size, 24, 0, 0x10000, 0x10000) + path
    output[old_end:old_end + size] = command.ljust(size, b"\0")
    struct.pack_into("<II", output, 16, count + 1, command_bytes + size)
    return bytes(output), {"path": _PRESENTATION_LOAD, "load_command_offset": old_end,
                           "load_command_size": size, "first_text_section_offset": first_section,
                           "code_moved": False}


def _verify_zip_member(archive: ZipFile, name: str, expected: bytes) -> None:
    digest = hashlib.sha256()
    count = 0
    with archive.open(name) as stream:
        for block in iter(lambda: stream.read(_COPY_BYTES), b""):
            count += len(block)
            digest.update(block)
    if count != len(expected) or digest.hexdigest() != _sha256(expected):
        raise ValueError("Output IPA member verification failed")


def package_ios_client(source: Path, output: Path, endpoint: str = DEFAULT_ENDPOINT, *,
                       native_library: Path | None = None,
                       presentation_library: Path | None = None,
                       presentation_plan: Path | None = None,
                       bundle_id: str = DEFAULT_BUNDLE_ID,
                       bootstrap: bool = True,
                       profile: IOSProfile = PROFILE_6_1_1) -> dict:
    """Write a new isolated local-client IPA and a sibling .report.json file.

    The known original binary receives local bootstrap hooks by default.
    Set bootstrap=False only for a host-redirection diagnostic build.
    Input hashes lock the package to the verified client build. An optional
    explicit native replacement can add separately verified bootstrap hooks;
    this packager only checks its Mach-O architecture and encryption state.
    Presentation requires the default bootstrap, its paired plan and a native
    build receipt binding the iOS dylib to the plan's generated profile header.
    """
    source, output = Path(source), Path(output)
    report_path = output.with_suffix(".report.json")
    if output.exists() or report_path.exists():
        raise ValueError("Output already exists; choose a new IPA filename")
    presentation_enabled = presentation_library is not None or presentation_plan is not None
    if (presentation_library is None) != (presentation_plan is None):
        raise ValueError("Presentation library and plan must be supplied together")
    if presentation_enabled and (native_library is not None or not bootstrap):
        raise ValueError("Presentation requires the default bootstrap without a native override or host-only mode")
    library = plan = presentation_report = None
    if presentation_enabled:
        library = _bounded_file(presentation_library, _MAX_PRESENTATION_LIBRARY_BYTES, "presentation library")
        library_info = macho_info(library)
        if struct.unpack_from("<I", library, 12)[0] != 6:
            raise ValueError("Presentation library must be an ARM64 Mach-O dylib")
        plan_bytes = _bounded_file(presentation_plan, _MAX_PRESENTATION_PLAN_BYTES, "presentation plan")
        plan = json.loads(plan_bytes, object_pairs_hook=_unique_object)
        if not isinstance(plan, dict):
            raise ValueError("Presentation plan must be a JSON object")
        build_path = Path(presentation_library).with_suffix(".build.json")
        build_bytes = _bounded_file(build_path, _MAX_PRESENTATION_BUILD_BYTES, "presentation build receipt")
        build = json.loads(build_bytes, object_pairs_hook=_unique_object)
        header_sha = plan.get("profile_header_sha256")
        if (not isinstance(build, dict) or type(build.get("schema")) is not int or build["schema"] != 1
                or build.get("target") != "arm64-apple-ios13.0"
                or not isinstance(header_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", header_sha)
                or build.get("profile_header_sha256") != header_sha
                or build.get("sha256") != library_info["sha256"]
                or type(build.get("bytes")) is not int or build["bytes"] != len(library)):
            raise ValueError("Presentation build receipt does not match the iOS dylib and plan")
        if "library_sha256" in plan and plan["library_sha256"] != library_info["sha256"]:
            raise ValueError("Presentation plan library SHA-256 mismatch")
    if (not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", bundle_id)
            or not (bundle_id == DEFAULT_BUNDLE_ID or bundle_id.startswith(DEFAULT_BUNDLE_ID + "."))):
        raise ValueError("Use an isolated bundle ID under game.qualiarts.idolypride.local")
    source_sha = _file_sha256(source)
    if source_sha != profile.ipa_sha256:
        raise ValueError("IPA SHA-256 differs from the verified client profile")
    with ZipFile(source) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Input IPA contains duplicate ZIP entries")
        infos = [name for name in names if name.startswith("Payload/")
                 and name.endswith(".app/Info.plist") and name.count("/") == 2]
        if len(infos) != 1:
            raise ValueError("Input IPA must contain exactly one top-level app")
        info_name = infos[0]
        app = info_name.removesuffix("Info.plist")
        presentation_name = app + _PRESENTATION
        if presentation_enabled and presentation_name in names:
            raise ValueError("Input IPA already contains the presentation library")
        info = plistlib.loads(archive.read(info_name))
        if (info.get("CFBundleIdentifier"), info.get("CFBundleShortVersionString"), info.get("CFBundleVersion")) != (
            "game.qualiarts.idolypride", profile.game_version, profile.game_build,
        ):
            raise ValueError("Input IPA game identity/version differs from the verified profile")
        executable_name = info.get("CFBundleExecutable")
        if not isinstance(executable_name, str) or not executable_name or "/" in executable_name or executable_name in (".", ".."):
            raise ValueError("Invalid app executable name")
        metadata_name, unity_name = app + _METADATA, app + _UNITY
        metadata, unity = archive.read(metadata_name), archive.read(unity_name)
        if _sha256(metadata) != profile.metadata_sha256 or _sha256(unity) != profile.unity_sha256:
            raise ValueError("Game native library or metadata SHA-256 differs from the verified profile")
        source_unity = macho_info(unity)
        main_executable = macho_info(archive.read(app + executable_name))
        octo_metadata, octo_report = _patch_octo_origin(metadata, profile.octo_literal_index)
        del metadata
        patched_metadata, metadata_report = patch_metadata(octo_metadata, endpoint)
        del octo_metadata
        settings_name = app + _UNITY_SETTINGS
        unity_settings, unity_http_report = _patch_unity_http(archive.read(settings_name), profile)
        endpoint = metadata_report["endpoint"]
        bootstrap_report = None
        if native_library is not None:
            unity = Path(native_library).read_bytes()
        elif bootstrap:
            from .native_bootstrap import patch_native
            unity, bootstrap_report = patch_native(unity, "ios")
        if presentation_enabled:
            from .ios_presentation import patch_presentation
            unity, patch_report = patch_presentation(unity, plan, bootstrap_report=bootstrap_report)
            unity, load_report = _add_presentation_load(unity)
            presentation_report = {"patch": patch_report, "load_command": load_report,
                                   "library": library_info, "library_bytes": len(library),
                                   "library_member": presentation_name,
                                   "plan_sha256": _sha256(plan_bytes), "bootstrap_composed": True,
                                   "build_receipt": {"name": build_path.name, "sha256": _sha256(build_bytes)},
                                   "device_verified": False}
        output_unity = macho_info(unity)
        info["CFBundleIdentifier"] = bundle_id
        info["CFBundleDisplayName"] = "아이프라 로컬"
        info["CFBundleName"] = "IdolyPrideLocal"
        info["CFBundleVersion"] = profile.game_build + ".9002"
        # The local login does not use the original federated-login callbacks.
        # Register one isolated scheme so both apps can coexist without stealing
        # the original game's deep links or Google/Twitter callback URLs.
        info["CFBundleURLTypes"] = [{"CFBundleTypeRole": "Editor", "CFBundleURLName": bundle_id,
                                     "CFBundleURLSchemes": [bundle_id]}]
        # The local API and master downloads use numerical loopback/LAN hosts.
        # Domain exceptions do not cover numerical IPs on the iOS 13 target.
        # Octo remains numerical loopback HTTP even when the API uses HTTPS.
        if urlsplit(endpoint).scheme == "http" or _LOCAL_OCTO.startswith(b"http://"):
            ats = dict(info.get("NSAppTransportSecurity", {}))
            ats["NSAllowsArbitraryLoads"] = True
            ats.pop("NSAllowsLocalNetworking", None)
            ats.pop("NSAllowsArbitraryLoadsForMedia", None)
            ats.pop("NSAllowsArbitraryLoadsInWebContent", None)
            info["NSAppTransportSecurity"] = ats
        info["NSLocalNetworkUsageDescription"] = "같은 기기 또는 로컬 네트워크의 아이프라 서버에 연결합니다."
        info_bytes = plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False)
        replacements = {metadata_name: patched_metadata, unity_name: unity, info_name: info_bytes,
                        settings_name: unity_settings}
        if presentation_enabled:
            replacements[presentation_name] = library
        stage = "local-api-bootstrap-presentation-client" if presentation_enabled else (
            "local-api-and-bootstrap-client" if bootstrap_report else "local-api-host-client")
        report = {"stage": stage, "source_sha256": source_sha,
                  "endpoint": endpoint, "game_version": profile.game_version,
                  "source_build": profile.game_build, "bundle_build": info["CFBundleVersion"],
                  "bundle_id": bundle_id, "display_name": info["CFBundleDisplayName"],
                  "url_schemes": [bundle_id],
                  "metadata": metadata_report, "octo_metadata": octo_report,
                  "unity_http_transport": unity_http_report, "source_unity": source_unity,
                  "output_unity": output_unity, "main_executable": main_executable,
                  "native_replacement": native_library is not None,
                  "bootstrap_patch": bootstrap_report,
                  "presentation_patch": presentation_report,
                  "signing": "Import in PlayCover, which must re-sign the app and embedded binaries",
                  "device_verified": False,
                  "scope": "API/resource routing, HTTP transport, selected bootstrap hooks and optional presentation bridge; gameplay/device execution remains unverified"}
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ios-local-client-", dir=output.parent) as temporary:
            staged = Path(temporary) / "client.ipa"
            with ZipFile(staged, "w") as packaged:
                for item in archive.infolist():
                    if _is_signature(item.filename):
                        continue
                    data = replacements.get(item.filename)
                    if data is None:
                        with archive.open(item) as original, packaged.open(item, "w") as destination:
                            shutil.copyfileobj(original, destination, _COPY_BYTES)
                    else:
                        packaged.writestr(item, data, compress_type=item.compress_type, compresslevel=6)
                if presentation_enabled:
                    item = ZipInfo(presentation_name)
                    item.create_system = 3
                    item.external_attr = 0o100755 << 16
                    packaged.writestr(item, library, compress_type=ZIP_DEFLATED, compresslevel=6)
            with ZipFile(staged) as check:
                if check.testzip() is not None:
                    raise ValueError("Output IPA failed ZIP CRC verification")
                for name, data in replacements.items():
                    _verify_zip_member(check, name, data)
                if any(_is_signature(name) for name in check.namelist()):
                    raise ValueError("Output IPA contains stale resource signatures")
                final_info = plistlib.loads(check.read(info_name))
                if final_info["CFBundleIdentifier"] != bundle_id:
                    raise ValueError("Output IPA bundle identity verification failed")
            report.update({"output_sha256": _file_sha256(staged), "output_bytes": staged.stat().st_size,
                           "verification": {"zip_crc": True, "modified_members": True,
                                            "isolated_bundle_identity": True, "stale_signatures_removed": True}})
            if output.exists() or report_path.exists():
                raise ValueError("Output appeared during packaging; existing files were preserved")
            staged.rename(output)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
