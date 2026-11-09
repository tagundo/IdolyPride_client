"""Build an isolated, locally signed Android client from a supplied APK/XAPK.

The game input is never modified. APKEditor owns Android resource rebuilding;
the SDK tools own alignment and signing. The endpoint is selected at build time.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import subprocess
import tempfile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zipfile import ZipFile


ORIGINAL_PACKAGE = "game.qualiarts.idolypride"
LOCAL_PACKAGE = ORIGINAL_PACKAGE + ".local"
METADATA_NAME = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
LIBRARY_NAME = "lib/arm64-v8a/libil2cpp.so"
METADATA_SHA256_6_1_1 = "f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e"
ANDROID = "{http://schemas.android.com/apk/res/android}"
PROJECT = Path(__file__).resolve().parents[2]
ET.register_namespace("android", ANDROID[1:-1])


class AndroidPackagingError(ValueError):
    """An actionable packaging failure, without signing passwords."""


def _origin(endpoint: str):
    try:
        parsed = urlsplit(endpoint)
        valid = (parsed.scheme in ("http", "https") and parsed.hostname and parsed.port
                 and parsed.username is None and parsed.password is None
                 and not parsed.query and not parsed.fragment and parsed.path in ("", "/")
                 and all(32 < ord(char) < 127 for char in endpoint))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise AndroidPackagingError("Endpoint must be an HTTP(S) origin with an explicit port and no credentials")
    return parsed


def _renamed(value: str, old: str, new: str) -> str:
    return new + value[len(old):] if value == old or value.startswith(old + ".") else value


def configure_android(decoded: Path, endpoint: str, package: str = LOCAL_PACKAGE,
                      label: str = "아이프라 로컬") -> dict:
    """Configure an APKEditor XML decode for a separate local client identity.

    Local cleartext permission is scoped to the endpoint's hostname. The
    existing system CA policy for external HTTPS resource hosts is preserved.
    """
    parsed = _origin(endpoint)
    if (not isinstance(package, str) or not re.fullmatch(r"[A-Za-z][A-Za-z_0-9]*(?:\.[A-Za-z][A-Za-z_0-9]*)+", package)
            or package in (ORIGINAL_PACKAGE, "game.qualiarts.idolypride_kr")):
        raise AndroidPackagingError("Choose a distinct valid package identifier for the local client")
    if not isinstance(label, str) or not label.strip():
        raise AndroidPackagingError("A nonempty local client label is required")
    decoded = Path(decoded)
    path = decoded / "AndroidManifest.xml"
    manifest = ET.parse(path)
    root = manifest.getroot()
    old = root.get("package")
    if old != ORIGINAL_PACKAGE:
        raise AndroidPackagingError("Expected the original Idoly Pride Android package")
    if root.get(ANDROID + "sharedUserId"):
        raise AndroidPackagingError("A shared-user APK cannot be safely cloned with a local signing key")
    application = root.find("application")
    if application is None:
        raise AndroidPackagingError("APK manifest has no application")
    resource = decoded / "resources" / "package_1"
    resource_info_path = resource / "package.json"
    resource_info = json.loads(resource_info_path.read_text(encoding="utf-8"))
    if resource_info.get("package_name") != old:
        raise AndroidPackagingError("APK resources do not match the input package")
    authorities = 0
    components = {"application", "activity", "activity-alias", "service", "receiver", "provider", "instrumentation"}
    for element in root.iter():
        for attribute, value in list(element.attrib.items()):
            if attribute == ANDROID + "authorities":
                element.set(attribute, ";".join(_renamed(item, old, package) for item in value.split(";")))
                authorities += 1
            elif attribute in (ANDROID + "permission", ANDROID + "readPermission", ANDROID + "writePermission"):
                element.set(attribute, _renamed(value, old, package))
            elif attribute == ANDROID + "name" and element.tag in ("permission", "uses-permission", "uses-permission-sdk-23", "permission-tree", "permission-group"):
                element.set(attribute, _renamed(value, old, package))
            elif attribute == ANDROID + "scheme":
                element.set(attribute, package if value == "idolypride.android.app" else _renamed(value, old, package))
            elif attribute in (ANDROID + "name", ANDROID + "targetActivity") and element.tag in components:
                # Relative Java class names would otherwise resolve under the
                # new application ID, where the original DEX has no classes.
                if value.startswith("."):
                    element.set(attribute, old + value)
                elif "." not in value:
                    element.set(attribute, old + "." + value)
    root.set("package", package)
    application.set(ANDROID + "label", label)
    application.set(ANDROID + "usesCleartextTraffic", "false")
    security_ref = application.get(ANDROID + "networkSecurityConfig")
    if security_ref != "@xml/network_security_config":
        raise AndroidPackagingError("Unsupported game network security resource")
    security_path = resource / "res" / "xml" / "network_security_config.xml"
    security = ET.parse(security_path)
    security_root = security.getroot()
    domain = ET.SubElement(security_root, "domain-config", {"cleartextTrafficPermitted": "true" if parsed.scheme == "http" else "false"})
    ET.SubElement(domain, "domain", {"includeSubdomains": "false"}).text = parsed.hostname
    # These anchors apply only to the selected local host. Native gRPC handler
    # trust behavior still requires device verification for HTTPS endpoints.
    anchors = ET.SubElement(domain, "trust-anchors")
    ET.SubElement(anchors, "certificates", {"src": "system"})
    ET.SubElement(anchors, "certificates", {"src": "user"})
    resource_info["package_name"] = package
    manifest.write(path, encoding="utf-8", xml_declaration=True)
    security.write(security_path, encoding="utf-8", xml_declaration=True)
    resource_info_path.write_text(json.dumps(resource_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_path = resource / "res" / "values" / "public.xml"
    if public_path.exists():
        public = ET.parse(public_path)
        if public.getroot().get("package") == old:
            public.getroot().set("package", package)
            public.write(public_path, encoding="utf-8", xml_declaration=True)
    return {"original_package": old, "package": package, "label": label,
            "endpoint": endpoint.rstrip("/"), "provider_count": authorities,
            "cleartext_host": parsed.hostname if parsed.scheme == "http" else None}


def strip_apk_signatures(source: Path, target: Path) -> None:
    """Rewrite ZIP entries, dropping old JAR/APK signatures but keeping licenses."""
    if Path(source).resolve() == Path(target).resolve():
        raise AndroidPackagingError("Signature stripping requires a separate output")
    with ZipFile(source) as original, ZipFile(target, "w", allowZip64=True) as output:
        for entry in original.infolist():
            upper = entry.filename.upper()
            signature = upper == "META-INF/MANIFEST.MF" or (
                upper.startswith("META-INF/") and upper.count("/") == 1
                and upper.endswith((".SF", ".RSA", ".DSA", ".EC")))
            if signature:
                continue
            with original.open(entry) as incoming, output.open(entry, "w") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command, stage, env=None):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True, env=env)
    if result.returncode:
        # No password is ever present in command arguments or captured tool logs.
        detail = (result.stderr or result.stdout).strip()[-1600:]
        raise AndroidPackagingError(f"{stage} failed (exit {result.returncode}): {detail}")
    return result


def _tools(apkeditor, build_tools, java):
    editor = Path(apkeditor) if apkeditor else PROJECT.parent / "ipr-patcher" / "APKEditor.jar"
    if not editor.is_file():
        raise AndroidPackagingError("Provide APKEditor.jar with --apkeditor")
    if build_tools is None:
        sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        root = Path(sdk) if sdk else PROJECT.parent / ".setup" / "android-sdk"
        candidates = sorted((root / "build-tools").glob("*"), reverse=True)
        build_tools = next((item for item in candidates if (item / "apksigner").is_file()), None)
    if build_tools is None:
        raise AndroidPackagingError("Provide an Android SDK build-tools directory with --build-tools")
    sdk_tools = Path(build_tools)
    for name in ("zipalign", "apksigner", "aapt2"):
        if not (sdk_tools / name).is_file():
            raise AndroidPackagingError(f"Android build-tools is missing {name}")
    executable = java or shutil.which("java")
    if not executable:
        raise AndroidPackagingError("A JDK with java and keytool is required")
    return editor.resolve(), sdk_tools.resolve(), executable


def _signing(java, keystore, alias, storepass_env, keypass_env, signing_dir):
    environment = os.environ.copy()
    if keystore is not None:
        path = Path(keystore).resolve(strict=True)
        if not environment.get(storepass_env):
            raise AndroidPackagingError(f"Set the signing password in environment variable {storepass_env}")
        keypass_env = keypass_env or storepass_env
        if not environment.get(keypass_env):
            raise AndroidPackagingError(f"Set the key password in environment variable {keypass_env}")
        return path, alias, storepass_env, keypass_env, environment
    directory = Path(signing_dir or PROJECT / "data" / "client-signing").resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path, password_path = directory / "local-client.p12", directory / "local-client.password"
    generated_alias = "idoly-local"
    if path.exists() != password_path.exists():
        raise AndroidPackagingError("Local signing key/password pair is incomplete; preserve the existing files and choose another signing directory")
    if not path.exists():
        password = secrets.token_urlsafe(32)
        descriptor = os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(password)
        environment["IDOLY_GENERATED_KEY_PASSWORD"] = password
        keytool = Path(java).resolve().with_name("keytool")
        if not keytool.is_file():
            found = shutil.which("keytool")
            if not found:
                raise AndroidPackagingError("keytool is required to create a local development signing key")
            keytool = Path(found)
        try:
            _run([keytool, "-genkeypair", "-keystore", path, "-storetype", "PKCS12", "-alias", generated_alias,
                  "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000", "-dname", "CN=Idoly Pride Local Development",
                  "-storepass:env", "IDOLY_GENERATED_KEY_PASSWORD", "-keypass:env", "IDOLY_GENERATED_KEY_PASSWORD"],
                 "Development signing key generation", environment)
        except Exception:
            if not path.exists():
                password_path.unlink(missing_ok=True)
            raise
        path.chmod(0o600)
    environment["IDOLY_GENERATED_KEY_PASSWORD"] = password_path.read_text(encoding="ascii").strip()
    return path, generated_alias, "IDOLY_GENERATED_KEY_PASSWORD", "IDOLY_GENERATED_KEY_PASSWORD", environment


def package_android(source: Path, output: Path, *, endpoint: str = "http://127.0.0.1:50051",
                    package: str = LOCAL_PACKAGE, label: str = "아이프라 로컬", apkeditor: Path | None = None,
                    build_tools: Path | None = None, java: str | None = None, native_library: Path | None = None,
                    keystore: Path | None = None, alias: str = "idoly-local",
                    storepass_env: str = "IDOLY_CLIENT_KEYSTORE_PASSWORD", keypass_env: str | None = None,
                    signing_dir: Path | None = None) -> dict:
    """Merge, configure, align, sign and verify a separate local client APK.

    The default native patch bypasses online seed/Firebase bootstrap before the
    client calls the local Auth.Login RPC. Optional ``native_library`` supplies
    an independently patched, same-layout ARM64 libil2cpp.so instead. A report
    records static verification; actual startup still needs an Android device.
    """
    from .client_patch import patch_metadata

    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if output.exists() or output.with_suffix(output.suffix + ".evidence.json").exists():
        raise AndroidPackagingError("Output already exists; choose a new APK filename")
    if output.suffix.lower() != ".apk" or source.suffix.lower() not in (".apk", ".xapk"):
        raise AndroidPackagingError("Input must be APK/XAPK and output must be a new APK")
    _origin(endpoint)
    editor, sdk, java = _tools(apkeditor, build_tools, java)
    input_hash = _hash(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".android-package-", dir=output.parent) as temp:
        work = Path(temp)
        merged = source
        if source.suffix.lower() == ".xapk":
            merged = work / "merged.apk"
            _run([java, "-jar", editor, "m", "-i", source, "-o", merged, "-clean-meta", "-validate-modules"], "APK split merge")
        decoded = work / "decoded"
        _run([java, "-jar", editor, "d", "-dex", "-t", "xml", "-i", merged, "-o", decoded], "APK resource decode")
        report = configure_android(decoded, endpoint, package, label)
        metadata_path = decoded / "root" / METADATA_NAME
        library_path = decoded / "root" / LIBRARY_NAME
        if not metadata_path.is_file() or not library_path.is_file():
            raise AndroidPackagingError("Need a standalone ARM64 game APK or an XAPK containing its ARM64 split")
        original_metadata = metadata_path.read_bytes()
        if native_library is None and hashlib.sha256(original_metadata).hexdigest() != METADATA_SHA256_6_1_1:
            raise AndroidPackagingError("Default bootstrap requires the verified original 6.1.1 metadata")
        patched_metadata, metadata_evidence = patch_metadata(original_metadata, endpoint.rstrip("/"))
        metadata_path.write_bytes(patched_metadata)
        original_native = library_path.read_bytes()
        native_hash = hashlib.sha256(original_native).hexdigest()
        if native_library is not None:
            patched_native = Path(native_library).read_bytes()
            if (len(patched_native) != len(original_native) or patched_native[:64] != original_native[:64]
                    or patched_native[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", patched_native, 18)[0] != 183):
                raise AndroidPackagingError("Native override must preserve the original ARM64 ELF layout and size")
            bootstrap_evidence = {"custom_override": True}
        else:
            from .native_bootstrap import patch_native

            patched_native, bootstrap_evidence = patch_native(original_native, "android")
        library_path.write_bytes(patched_native)
        report.update({"schema_version": 1, "input_sha256": input_hash, "metadata_patch": metadata_evidence,
                       "native_original_sha256": native_hash, "native_output_sha256": _hash(library_path),
                       "native_override": native_library is not None, "native_bootstrap": bootstrap_evidence,
                       "device_tested": False})
        config = decoded / "root" / "assets" / "idoly-local.json"
        config.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        unsigned, cleaned, aligned, signed = (work / name for name in ("rebuilt.apk", "clean.apk", "aligned.apk", "signed.apk"))
        _run([java, "-jar", editor, "b", "-i", decoded, "-o", unsigned], "APK resource rebuild")
        strip_apk_signatures(unsigned, cleaned)
        # Applying 16 KiB alignment to every stored entry also page-aligns
        # uncompressed native libraries on both 4 KiB and 16 KiB Android devices.
        _run([sdk / "zipalign", "-f", "16384", cleaned, aligned], "APK alignment")
        key, key_alias, store_env, key_env, environment = _signing(java, keystore, alias, storepass_env, keypass_env, signing_dir)
        _run([sdk / "apksigner", "sign", "--ks", key, "--ks-key-alias", key_alias,
              "--ks-pass", "env:" + store_env, "--key-pass", "env:" + key_env,
              "--out", signed, aligned], "APK signing", environment)
        signature = _run([sdk / "apksigner", "verify", "--verbose", "--print-certs", signed], "APK signature verification")
        _run([sdk / "zipalign", "-c", "16384", signed], "APK alignment verification")
        badging = _run([sdk / "aapt2", "dump", "badging", signed], "APK manifest verification").stdout
        if f"package: name='{package}'" not in badging or "native-code: 'arm64-v8a'" not in badging:
            raise AndroidPackagingError("Rebuilt APK package or ARM64 library inventory did not match")
        with ZipFile(signed) as archive:
            if archive.read(METADATA_NAME) != patched_metadata:
                raise AndroidPackagingError("Rebuilt APK did not retain patched game metadata")
            if hashlib.sha256(archive.read(LIBRARY_NAME)).hexdigest() != report["native_output_sha256"]:
                raise AndroidPackagingError("Rebuilt APK did not retain the selected native library")
            names = set(archive.namelist())
            if not {"classes.dex", "lib/arm64-v8a/libunity.so"}.issubset(names):
                raise AndroidPackagingError("Rebuilt APK is missing required game executable files")
        if _hash(source) != input_hash:
            raise AndroidPackagingError("Input changed during packaging")
        report.update({"output_sha256": _hash(signed), "output_bytes": signed.stat().st_size,
                       "signature_verified": True, "alignment_bytes": 16384,
                       "signer": [line for line in signature.stdout.splitlines() if "certificate SHA-256 digest:" in line]})
        # Publication occurs only after all checks pass; a new output filename
        # is mandatory so the user's original client and installed app survive.
        with output.open("xb") as incoming, signed.open("rb") as outgoing:
            shutil.copyfileobj(outgoing, incoming, length=1024 * 1024)
        evidence = output.with_suffix(output.suffix + ".evidence.json")
        with evidence.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return report
