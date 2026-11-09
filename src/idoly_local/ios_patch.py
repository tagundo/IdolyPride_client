"""Package an isolated PlayCover client pointed at a user-selected local server.

PlayCover must re-sign the resulting IPA. The default build combines endpoint
redirection with the version-locked local authentication bootstrap patches.
The server's remaining gameplay services still need separate implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import tempfile
from zipfile import ZipFile
from urllib.parse import urlsplit

from .client_patch import patch_metadata


@dataclass(frozen=True)
class IOSProfile:
    ipa_sha256: str
    unity_sha256: str
    metadata_sha256: str
    game_version: str = "6.1.1"
    game_build: str = "156"


PROFILE_6_1_1 = IOSProfile(
    ipa_sha256="33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848",
    unity_sha256="b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",
    metadata_sha256="d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda",
)
DEFAULT_ENDPOINT = "http://127.0.0.1:50051"
DEFAULT_BUNDLE_ID = "game.qualiarts.idolypride.local"
_METADATA = "Data/Managed/Metadata/global-metadata.dat"
_UNITY = "Frameworks/UnityFramework.framework/UnityFramework"


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


def package_ios_client(source: Path, output: Path, endpoint: str = DEFAULT_ENDPOINT, *,
                       native_library: Path | None = None,
                       bundle_id: str = DEFAULT_BUNDLE_ID,
                       bootstrap: bool = True,
                       profile: IOSProfile = PROFILE_6_1_1) -> dict:
    """Write a new isolated local-client IPA and a sibling .report.json file.

    The known original binary receives local bootstrap hooks by default.
    Set bootstrap=False only for a host-redirection diagnostic build.
    Input hashes lock the package to the verified client build. An optional
    explicit native replacement can add separately verified bootstrap hooks;
    this packager only checks its Mach-O architecture and encryption state.
    """
    source, output = Path(source), Path(output)
    report_path = output.with_suffix(".report.json")
    if output.exists() or report_path.exists():
        raise ValueError("Output already exists; choose a new IPA filename")
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
        patched_metadata, metadata_report = patch_metadata(metadata, endpoint)
        endpoint = metadata_report["endpoint"]
        bootstrap_report = None
        if native_library is not None:
            unity = Path(native_library).read_bytes()
        elif bootstrap:
            from .native_bootstrap import patch_native
            unity, bootstrap_report = patch_native(unity, "ios")
        output_unity = macho_info(unity)
        info["CFBundleIdentifier"] = bundle_id
        info["CFBundleDisplayName"] = "아이프라 로컬"
        info["CFBundleName"] = "IdolyPrideLocal"
        info["CFBundleVersion"] = profile.game_build + ".9001"
        # The local login does not use the original federated-login callbacks.
        # Register one isolated scheme so both apps can coexist without stealing
        # the original game's deep links or Google/Twitter callback URLs.
        info["CFBundleURLTypes"] = [{"CFBundleTypeRole": "Editor", "CFBundleURLName": bundle_id,
                                     "CFBundleURLSchemes": [bundle_id]}]
        # The local API and master downloads use numerical loopback/LAN hosts.
        # Domain exceptions do not cover numerical IPs on the iOS 13 target.
        if urlsplit(endpoint).scheme == "http":
            ats = dict(info.get("NSAppTransportSecurity", {}))
            ats["NSAllowsArbitraryLoads"] = True
            ats.pop("NSAllowsLocalNetworking", None)
            ats.pop("NSAllowsArbitraryLoadsForMedia", None)
            ats.pop("NSAllowsArbitraryLoadsInWebContent", None)
            info["NSAppTransportSecurity"] = ats
        info["NSLocalNetworkUsageDescription"] = "같은 기기 또는 로컬 네트워크의 아이프라 서버에 연결합니다."
        info_bytes = plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False)
        replacements = {metadata_name: patched_metadata, unity_name: unity, info_name: info_bytes}
        report = {"stage": "local-api-and-bootstrap-client" if bootstrap_report else "local-api-host-client", "source_sha256": source_sha,
                  "endpoint": endpoint, "game_version": profile.game_version,
                  "source_build": profile.game_build, "bundle_build": info["CFBundleVersion"],
                  "bundle_id": bundle_id, "display_name": info["CFBundleDisplayName"],
                  "url_schemes": [bundle_id],
                  "metadata": metadata_report, "source_unity": source_unity,
                  "output_unity": output_unity, "main_executable": main_executable,
                  "native_replacement": native_library is not None,
                  "bootstrap_patch": bootstrap_report,
                  "signing": "Import in PlayCover, which must re-sign the app and embedded binaries",
                  "device_verified": False,
                  "scope": "API routing and selected native bootstrap hooks; gameplay/device execution remains unverified"}
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ios-local-client-", dir=output.parent) as temporary:
            staged = Path(temporary) / "client.ipa"
            with ZipFile(staged, "w") as packaged:
                for item in archive.infolist():
                    if _is_signature(item.filename):
                        continue
                    data = replacements.get(item.filename)
                    if data is None:
                        data = archive.read(item.filename)
                    packaged.writestr(item, data, compress_type=item.compress_type, compresslevel=6)
            with ZipFile(staged) as check:
                if check.testzip() is not None:
                    raise ValueError("Output IPA failed ZIP CRC verification")
                for name, data in replacements.items():
                    if check.read(name) != data:
                        raise ValueError("Output IPA member verification failed")
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
