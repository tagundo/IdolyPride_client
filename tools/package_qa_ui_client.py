#!/usr/bin/env python3
"""Append a token-protected Unity UI probe to an explicitly pinned emulator input.

The default input is the existing diagnostic software-AES/no-store intermediate.
The separate normal-local profile preserves the published local client's AES,
store code and six existing bootstrap patches. Neither profile is the original
game. No cloning, new bootstrap patches, account data or publication occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import struct
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from idoly_local.android_package import ANDROID, AndroidPackagingError, METADATA_NAME, _run, _tools


ROOT = Path(__file__).resolve().parents[1]
JAVA_ROOT = ROOT / "qa-game-ui/java"
JAVA_FILES = {"NativeUiBridge.java", "UnityDispatcher.java", "LoopbackUiServer.java", "QaUiProvider.java"}
PACKAGE = "game.qualiarts.idolypride.local.diagnostics"
NORMAL_PACKAGE = "game.qualiarts.idolypride.local"
DIAGNOSTIC_PROFILE = "diagnostic-aes"
NORMAL_PROFILE = "normal-local"
INPUT_PROFILES = {DIAGNOSTIC_PROFILE: PACKAGE, NORMAL_PROFILE: NORMAL_PACKAGE}
PROVIDER = "game.qualiarts.idolypride.qa.ui.QaUiProvider"
AUTHORITY = PACKAGE + ".qa.ui"
MARKER = "assets/idoly-qa-ui.json"
AES_MARKER = "assets/idoly-qa-only-software-aes.json"
NATIVE = "lib/arm64-v8a/libidoly_qa_ui_bridge.so"
IL2CPP = "lib/arm64-v8a/libil2cpp.so"
FAST_AES = "lib/arm64-v8a/libFastAES.so"
PINNED_DIAGNOSTIC = "f5be0c0e19c2a17ea28ffa0c3205a49f5ab004f013e2e67e319aa192ca1995df"
PINNED_NATIVE_BEFORE = "4517381b0dbeae559d79832797f0c57c78ba6f37cf7d3544a58d0f31f2b8def3"
PINNED_NATIVE_ORIGINAL = "68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3"
PINNED_NO_STORE = "ffd7c1b0656a3d4026c1c22d01b197a924d74d82ba9b32f4422db8a54a35d7dd"
PINNED_METADATA = "681390058fdfbb1f54d3d0f09b9d66ad03312696e07caee4890d3cb1e1a898c0"
PINNED_METADATA_ORIGINAL = "f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e"
PINNED_AES_BEFORE = "f8f64ab5424b6f692464e23cf47af9d399c4072b700c196e7b321e670b93fcc4"
PINNED_SOFTWARE_AES = "f301b2ebd1afd4201c71d24b5ce65a1791d59029ea172801a41f2c3cb99caa86"
PINNED_NORMAL = "28ecc6a617867d0842a5e88eac3d5736199809a49d4d433ce47816d6a40ba77b"
PINNED_NORMAL_BYTES = 159483201
PINNED_NORMAL_CERT = "86fbcf5674eb086f74a95756d68a8db52e203b418d3874b440ecabdf259d6a81"
PINNED_XAPK = "ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36"
PINNED_UNITY = "c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85"
PINNED_NORMAL_DEX = {
    "classes.dex": "7fb72c0f03eb06dde0d32a4b78df4e5aa9c07e1f218f5047e40d1222e09d8d2c",
    "classes2.dex": "9267992faab11f547059af814d01cac57afbada2771398ccc4fcc25a4608c2f0",
    "classes3.dex": "b0a204747eca560b03d5805f0ec563c24e9f49863c4d3cbd276595ab043579ce",
    "classes4.dex": "9a7c23c5388cad7552323d225e3081e1a3c94c221ba50889889a281e94f9cf21"}
BOOTSTRAP_METHODS = {"SeedWrapper.IsInitialized", "SeedWrapper.SeedId", "SeedWrapper.InitializeAsync",
                     "SeedWrapper.RefreshSeedIdAsync", "AccountManager.IsCreatedUser", "AccountManager.GetFirebaseIdTokenAsync"}
DEX_NAME = re.compile(r"classes(?P<index>[2-9][0-9]*|1[0-9]+)?\.dex")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def member_digest(archive, name):
    with archive.open(name) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def signature_member(name):
    upper = name.upper()
    return upper == "META-INF/MANIFEST.MF" or (upper.startswith("META-INF/") and upper.count("/") == 1
        and upper.endswith((".SF", ".RSA", ".DSA", ".EC")))


def inventory(archive):
    names = archive.namelist()
    if len(names) != len(set(names)) or any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                                        or "\\" in name for name in names):
        raise AndroidPackagingError("QA input has duplicate or unsafe ZIP member names")
    return {name: member_digest(archive, name) for name in names if not signature_member(name)}


def profile_package(input_profile):
    if input_profile not in INPUT_PROFILES:
        raise AndroidPackagingError("Choose an explicit supported QA input profile")
    return INPUT_PROFILES[input_profile]


def validate_normal_input(source, expected_source_sha256):
    if (expected_source_sha256 != PINNED_NORMAL or digest(source) != PINNED_NORMAL
            or Path(source).stat().st_size != PINNED_NORMAL_BYTES):
        raise AndroidPackagingError("Normal-local requires the exact pinned published local APK")
    with ZipFile(source) as archive:
        members = inventory(archive)
        if (any(name.startswith("assets/idoly-") and name != "assets/idoly-local.json" for name in members)
                or NATIVE in members):
            raise AndroidPackagingError("Normal-local input must have no prior QA adaptations or UI probe")
        if (members.get(IL2CPP) != PINNED_NATIVE_BEFORE or members.get(FAST_AES) != PINNED_AES_BEFORE
                or members.get(METADATA_NAME) != PINNED_METADATA
                or members.get("lib/arm64-v8a/libunity.so") != PINNED_UNITY
                or {name: value for name, value in members.items() if DEX_NAME.fullmatch(name)} != PINNED_NORMAL_DEX):
            raise AndroidPackagingError("Normal-local native, original AES, metadata or DEX bytes differ")
        local = json.loads(archive.read("assets/idoly-local.json"))
        if not isinstance(local, dict):
            raise AndroidPackagingError("Normal-local provenance must be an object")
        patch, bootstrap = local.get("metadata_patch"), local.get("native_bootstrap")
        if (local.get("package") != NORMAL_PACKAGE or local.get("original_package") != "game.qualiarts.idolypride"
                or local.get("input_sha256") != PINNED_XAPK or local.get("endpoint") != "http://127.0.0.1:50051"
                or local.get("native_override") is not False or local.get("native_output_sha256") != PINNED_NATIVE_BEFORE
                or local.get("native_original_sha256") != PINNED_NATIVE_ORIGINAL
                or not isinstance(patch, dict) or patch.get("input_sha256") != PINNED_METADATA_ORIGINAL
                or patch.get("output_sha256") != PINNED_METADATA or not isinstance(bootstrap, dict)
                or bootstrap.get("input_sha256") != PINNED_NATIVE_ORIGINAL
                or bootstrap.get("output_sha256") != PINNED_NATIVE_BEFORE
                or not isinstance(bootstrap.get("patches"), list) or len(bootstrap["patches"]) != 6
                or {row.get("method") for row in bootstrap["patches"] if isinstance(row, dict)} != BOOTSTRAP_METHODS):
            raise AndroidPackagingError("Normal-local identity or six-bootstrap provenance differs")
    return members, {"original_source_sha256": PINNED_XAPK, "normal_local_apk_sha256": PINNED_NORMAL,
        "input_certificate_sha256": PINNED_NORMAL_CERT, "metadata_original_sha256": PINNED_METADATA_ORIGINAL,
        "metadata_sha256": PINNED_METADATA, "native_bootstrap_sha256": PINNED_NATIVE_BEFORE,
        "original_aes_sha256": PINNED_AES_BEFORE}


def verify_normal_signature(source, sdk):
    verification = _run([sdk / "apksigner", "verify", "--verbose", "--print-certs", source], "Normal-local input signature verification")
    signers = [line.split(": ", 1)[-1] for line in verification.stdout.splitlines() if "certificate SHA-256 digest:" in line]
    if signers != [PINNED_NORMAL_CERT]:
        raise AndroidPackagingError("Normal-local signer differs from its published certificate")


def validate_input(source, qa_aes_report, expected_source_sha256, input_profile=DIAGNOSTIC_PROFILE):
    """Bind the audited original and both existing QA adaptations to this APK."""
    profile_package(input_profile)
    if input_profile == NORMAL_PROFILE:
        if qa_aes_report is not None:
            raise AndroidPackagingError("Normal-local must not receive a diagnostic QA AES report")
        return validate_normal_input(source, expected_source_sha256)
    if qa_aes_report is None:
        raise AndroidPackagingError("The diagnostic-AES profile requires its existing QA AES report")
    if not isinstance(expected_source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256):
        raise AndroidPackagingError("Provide the exact intermediate APK SHA-256")
    if digest(source) != expected_source_sha256:
        raise AndroidPackagingError("QA intermediate APK SHA-256 differs from the explicit input")
    report = json.loads(Path(qa_aes_report).read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise AndroidPackagingError("Expected the existing QA AES report object")
    if (report.get("source_apk_sha256") != PINNED_DIAGNOSTIC
            or report.get("original_source_sha256", PINNED_DIAGNOSTIC) != PINNED_DIAGNOSTIC
            or report.get("output_apk_sha256") != expected_source_sha256
            or report.get("output_bytes") != Path(source).stat().st_size
            or report.get("qa_only") is not True or report.get("exact_production_client") is not False
            or report.get("production_client_modified") is not False
            or report.get("original_sha256") != PINNED_AES_BEFORE
            or report.get("patched_sha256") != PINNED_SOFTWARE_AES):
        raise AndroidPackagingError("QA AES report does not describe the pinned diagnostic intermediate")
    verification = report.get("verification", {})
    if not isinstance(verification, dict) or not all(verification.get(key) is True for key in
            ("nist_sp800_38a", "original_software_and_patched_exports_match_oracle", "input_key_iv_preserved", "caller_abi_preserved")):
        raise AndroidPackagingError("QA AES execution verification is missing")
    iap = report.get("iap_qa", {})
    if (not isinstance(iap, dict) or iap.get("qa_only") is not True or iap.get("emulator_no_store") is not True
            or iap.get("exact_production_client") is not False or iap.get("original_sha256") != PINNED_NATIVE_BEFORE
            or iap.get("patched_sha256") != PINNED_NO_STORE or iap.get("store_initialized") is not False
            or iap.get("purchase_receipt_grant_functions_modified") is not False):
        raise AndroidPackagingError("The audited emulator no-store adaptation is required")
    checked = iap.get("verification", {})
    if (not isinstance(checked, dict) or checked.get("real_managed_factory_and_success_getter_executed") is not True
            or checked.get("hidden_x8_preserved_across_runtime_calls") is not True
            or checked.get("store_purchase_or_grant_code_executed") is not False):
        raise AndroidPackagingError("QA no-store managed ABI verification is missing")
    with ZipFile(source) as archive:
        members = inventory(archive)
        if MARKER in members or NATIVE in members or AES_MARKER not in members:
            raise AndroidPackagingError("Expected an AES intermediate without a prior UI probe")
        if (members.get(IL2CPP) != PINNED_NO_STORE or members.get(FAST_AES) != PINNED_SOFTWARE_AES
                or members.get(METADATA_NAME) != PINNED_METADATA):
            raise AndroidPackagingError("Intermediate native/managed hashes differ from the audited QA input")
        marker = json.loads(archive.read(AES_MARKER))
        if not isinstance(marker, dict) or any(marker.get(key) != report.get(key) for key in
                ("qa_only", "source_apk_sha256", "original_sha256", "patched_sha256", "iap_qa")):
            raise AndroidPackagingError("Embedded AES marker and supplied report disagree")
        local = json.loads(archive.read("assets/idoly-local.json"))
        patch = local.get("metadata_patch", {}) if isinstance(local, dict) else None
        if (not isinstance(local, dict) or not isinstance(patch, dict)
                or local.get("package") != PACKAGE or local.get("native_output_sha256") != PINNED_NATIVE_BEFORE
                or patch.get("input_sha256") != PINNED_METADATA_ORIGINAL or patch.get("output_sha256") != PINNED_METADATA):
            raise AndroidPackagingError("Diagnostic identity or managed metadata provenance differs")
    # Copy only pinned, safe provenance; arbitrary report fields and paths are
    # deliberately excluded, including any accidental runtime credentials.
    return members, {"original_source_sha256": PINNED_DIAGNOSTIC,
        "qa_aes_report_sha256": digest(qa_aes_report), "metadata_original_sha256": PINNED_METADATA_ORIGINAL,
        "metadata_sha256": PINNED_METADATA, "native_pre_no_store_sha256": PINNED_NATIVE_BEFORE,
        "native_no_store_sha256": PINNED_NO_STORE, "software_aes_sha256": PINNED_SOFTWARE_AES}


def add_provider(decoded, input_profile=DIAGNOSTIC_PROFILE):
    package_name = profile_package(input_profile)
    authority = package_name + ".qa.ui"
    path = Path(decoded) / "AndroidManifest.xml"
    tree = ET.parse(path)
    manifest = tree.getroot()
    application = manifest.find("application")
    if manifest.get("package") != package_name or manifest.get(ANDROID + "sharedUserId") or application is None:
        raise AndroidPackagingError("UI QA requires the unchanged package selected by its input profile")
    if any(node.get(ANDROID + "name") == PROVIDER or authority in node.get(ANDROID + "authorities", "").split(";")
           for node in application):
        raise AndroidPackagingError("QA UI provider or authority already exists")
    application.set(ANDROID + "debuggable", "true")
    ET.SubElement(application, "provider", {ANDROID + "name": PROVIDER, ANDROID + "authorities": authority,
        ANDROID + "exported": "false", ANDROID + "initOrder": "2"})
    tree.write(path, encoding="utf-8", xml_declaration=True)
    names = [p.name for p in (Path(decoded) / "dex").iterdir() if DEX_NAME.fullmatch(p.name)]
    if "classes.dex" not in names:
        raise AndroidPackagingError("Decoded QA input has no preserved primary DEX")
    highest = max(int(DEX_NAME.fullmatch(name).group("index") or 1) for name in names)
    return "classes" + str(highest + 1) + ".dex"


def compile_dex(work, java, build_tools, android_jar):
    javac = Path(java).with_name("javac")
    if not javac.is_file() or not Path(android_jar).is_file() or not (build_tools / "d8").is_file():
        raise AndroidPackagingError("UI QA requires javac, SDK34 android.jar and d8")
    sources = sorted(JAVA_ROOT.rglob("*.java"))
    if len(sources) != len(JAVA_FILES) or {p.name for p in sources} != JAVA_FILES or any(
            not p.resolve().is_relative_to(JAVA_ROOT.resolve()) for p in sources):
        raise AndroidPackagingError("QA UI Java source inventory differs from its four fixed sources")
    classes, output = work / "ui-classes", work / "ui-dex"
    classes.mkdir()
    output.mkdir()
    _run([javac, "--release", "8", "-encoding", "UTF-8", "-classpath", android_jar, "-d", classes, *sources], "QA UI Java compilation")
    # Include every generated class (also nested/anonymous classes), not just
    # the four top-level classes, so D8 cannot silently omit a callback.
    _run([build_tools / "d8", "--release", "--min-api", "28", "--lib", android_jar,
          "--output", output, *sorted(classes.rglob("*.class"))], "QA UI DEX compilation")
    if sorted(p.name for p in output.iterdir()) != ["classes.dex"]:
        raise AndroidPackagingError("QA UI must compile into exactly one added DEX")
    dex = output / "classes.dex"
    if b"Lgame/qualiarts/idolypride/qa/ui/QaUiProvider;" not in dex.read_bytes():
        raise AndroidPackagingError("Compiled QA UI DEX is missing its fixed provider")
    return dex, {str(p.relative_to(ROOT)): digest(p) for p in sources}


def verify_provider_xml(xml, input_profile=DIAGNOSTIC_PROFILE):
    authority = profile_package(input_profile) + ".qa.ui"
    lines = xml.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        match = re.match(r"(\s*)E: provider\b", line)
        if not match:
            continue
        end = index + 1
        while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > len(match[1])):
            end += 1
        block = "\n".join(lines[index:end])
        if PROVIDER in block:
            blocks.append(block)
    def boolean(text, attribute, expected):
        # SDK34 variants print either literal booleans or typed hex values.
        value = r"(?:true|\(type 0x12\)0x(?:ffffffff|1))" if expected else r"(?:false|\(type 0x12\)0x0)"
        return re.search(r"android:" + attribute + r"(?:\([^\n)]*\))?\s*=\s*" + value + r"(?:\s|$)", text) is not None
    if (len(blocks) != 1 or authority not in blocks[0]
            or not boolean(blocks[0], "exported", False) or not boolean(xml, "debuggable", True)):
        raise AndroidPackagingError("Compiled QA provider/exported/debuggable manifest contract differs")


def package(source, output, *, qa_aes_report=None, expected_source_sha256, native_library, emulator_only=False,
            input_profile=DIAGNOSTIC_PROFILE, apkeditor=None, build_tools=None, java=None, android_jar=None, report_path=None):
    if emulator_only is not True:
        raise AndroidPackagingError("Explicit --emulator-only is required for this QA APK")
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    report_path = Path(report_path).resolve() if report_path else output.with_suffix(output.suffix + ".evidence.json")
    if output.suffix != ".apk" or output.exists() or report_path.exists() or output == source or output == report_path:
        raise AndroidPackagingError("Choose a new .apk and report path; existing clients/outputs are preserved")
    package_name = profile_package(input_profile)
    members, provenance = validate_input(source, qa_aes_report, expected_source_sha256, input_profile)
    native_library = Path(native_library).resolve(strict=True)
    native = native_library.read_bytes()
    if (native_library.name != Path(NATIVE).name or len(native) < 64 or native[:7] != b"\x7fELF\x02\x01\x01"
            or struct.unpack_from("<HH", native, 16) != (3, 183)):
        raise AndroidPackagingError("Expected the separate ARM64 libidoly_qa_ui_bridge.so")
    editor, sdk, executable = _tools(apkeditor, build_tools, java)
    if input_profile == NORMAL_PROFILE:
        verify_normal_signature(source, sdk)
    executable = Path(shutil.which(str(executable)) or executable).resolve()
    keytool = executable.with_name("keytool")
    if not keytool.is_file():
        raise AndroidPackagingError("A JDK with keytool is required")
    platform = Path(android_jar).resolve() if android_jar else sdk.parent.parent / "platforms/android-34/android.jar"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".idoly-qa-ui-", dir=output.parent) as temporary:
        work = Path(temporary)
        dex, java_hashes = compile_dex(work, executable, sdk, platform)
        decoded = work / "decoded"
        _run([executable, "-jar", editor, "d", "-dex", "-t", "xml", "-i", source, "-o", decoded], "QA UI manifest decode")
        added_dex = add_provider(decoded, input_profile)
        rebuilt = work / "manifest-build.apk"
        _run([executable, "-jar", editor, "b", "-i", decoded, "-o", rebuilt], "QA UI manifest rebuild")
        with ZipFile(rebuilt) as archive:
            manifest = archive.read("AndroidManifest.xml")
        marker = {"schema": 1, "qa_only": True, "emulator_only": True, "package": package_name,
            "input_profile": input_profile, "authority": package_name + ".qa.ui",
            "provider": PROVIDER, "exported": False, "debuggable": True, "loopback_only": True,
            "original_source_sha256": provenance["original_source_sha256"],
            "input_apk_sha256": expected_source_sha256, "provenance": provenance,
            "source_sha256": java_hashes, "native_library_sha256": digest(native_library), "added_dex": added_dex}
        additions = {added_dex: dex.read_bytes(), NATIVE: native,
                     MARKER: (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")}
        if set(additions) & set(members):
            raise AndroidPackagingError("QA UI additions collide with existing APK members")
        unsigned, aligned, signed = (work / name for name in ("unsigned.apk", "aligned.apk", "signed.apk"))
        # Use only the rebuilt manifest. Copy all original resources/executables
        # directly, preventing APKEditor normalization from changing their bytes.
        with ZipFile(source) as incoming, ZipFile(unsigned, "w", allowZip64=True) as outgoing:
            for item in incoming.infolist():
                if signature_member(item.filename):
                    continue
                if item.filename == "AndroidManifest.xml":
                    outgoing.writestr(item, manifest)
                else:
                    with incoming.open(item) as src, outgoing.open(item, "w") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
            for name, raw in additions.items():
                item = ZipInfo(name)
                item.compress_type = ZIP_DEFLATED if name == MARKER else ZIP_STORED
                item.external_attr = 0o100644 << 16
                outgoing.writestr(item, raw)
        _run([sdk / "zipalign", "-f", "16384", unsigned, aligned], "QA UI APK alignment")
        environment = dict(os.environ, IDOLY_QA_UI_KEY_PASSWORD=secrets.token_urlsafe(32))
        key = work / "ephemeral-qa-ui.p12"
        _run([keytool, "-genkeypair", "-keystore", key, "-storetype", "PKCS12", "-alias", "qa-ui-only",
              "-keyalg", "RSA", "-keysize", "2048", "-validity", "30", "-dname", "CN=Idoly disposable emulator UI QA only",
              "-storepass:env", "IDOLY_QA_UI_KEY_PASSWORD", "-keypass:env", "IDOLY_QA_UI_KEY_PASSWORD"], "QA UI ephemeral signing key", environment)
        _run([sdk / "apksigner", "sign", "--ks", key, "--ks-key-alias", "qa-ui-only", "--ks-pass", "env:IDOLY_QA_UI_KEY_PASSWORD",
              "--key-pass", "env:IDOLY_QA_UI_KEY_PASSWORD", "--out", signed, aligned], "QA UI APK signing", environment)
        verification = _run([sdk / "apksigner", "verify", "--verbose", "--print-certs", signed], "QA UI signature verification")
        _run([sdk / "zipalign", "-c", "16384", signed], "QA UI alignment verification")
        badging = _run([sdk / "aapt2", "dump", "badging", signed], "QA UI package verification").stdout
        xml = _run([sdk / "aapt2", "dump", "xmltree", signed, "--file", "AndroidManifest.xml"], "QA UI provider verification").stdout
        if f"package: name='{package_name}'" not in badging:
            raise AndroidPackagingError("QA output changed its input profile's package identity")
        verify_provider_xml(xml, input_profile)
        expected = {**members, "AndroidManifest.xml": hashlib.sha256(manifest).hexdigest(),
                    **{name: hashlib.sha256(raw).hexdigest() for name, raw in additions.items()}}
        with ZipFile(signed) as archive:
            if archive.testzip() is not None or inventory(archive) != expected:
                raise AndroidPackagingError("QA APK changed an original member beyond manifest/signatures/additions")
        if digest(source) != expected_source_sha256:
            raise AndroidPackagingError("QA source APK changed while packaging")
        report = {"schema": 1, "qa_only": True, "emulator_only": True, "package": package_name,
            "input_profile": input_profile, "input_is_original_client": False,
            "software_aes_and_no_store_input": input_profile == DIAGNOSTIC_PROFILE,
            "production_client_modified": False, "original_source_sha256": provenance["original_source_sha256"],
            "source_apk_sha256": expected_source_sha256, "output_apk_sha256": digest(signed), "output_bytes": signed.stat().st_size,
            "qa_ui": marker, "changed_apk_members": ["AndroidManifest.xml", *additions],
            "all_existing_members_preserved_except_manifest_and_signatures": True,
            "preserved_dex_sha256": {name: value for name, value in members.items() if DEX_NAME.fullmatch(name)},
            "preserved_metadata_sha256": members[METADATA_NAME], "preserved_il2cpp_sha256": members[IL2CPP],
            "preserved_aes_sha256": members[FAST_AES],
            "signature": "ephemeral QA key; disposable emulator installation only",
            "signer_sha256": [line.split(": ", 1)[-1] for line in verification.stdout.splitlines() if "certificate SHA-256 digest:" in line]}
        with output.open("xb") as dst, signed.open("rb") as src:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-profile", choices=tuple(INPUT_PROFILES), default=DIAGNOSTIC_PROFILE)
    parser.add_argument("--qa-aes-report", type=Path)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--native-library", type=Path, required=True)
    parser.add_argument("--emulator-only", action="store_true", required=True)
    parser.add_argument("--apkeditor", type=Path)
    parser.add_argument("--build-tools", type=Path)
    parser.add_argument("--java")
    parser.add_argument("--android-jar", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = package(args.source, args.output, qa_aes_report=args.qa_aes_report,
            expected_source_sha256=args.expected_source_sha256, native_library=args.native_library,
            emulator_only=args.emulator_only, input_profile=args.input_profile, apkeditor=args.apkeditor, build_tools=args.build_tools,
            java=args.java, android_jar=args.android_jar, report_path=args.report)
    except (AndroidPackagingError, OSError, ValueError, KeyError) as error:
        parser.exit(1, f"QA UI packaging failed: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
