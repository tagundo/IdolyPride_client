"""QA UI packaging guards and preservation contract, without a game runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest


spec = importlib.util.spec_from_file_location("qa_ui_packager", Path(__file__).resolve().parents[1] / "tools/package_qa_ui_client.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


@pytest.fixture
def intermediate(tmp_path, monkeypatch):
    native, aes, metadata = b"audited no-store", b"audited software AES", b"unchanged managed metadata"
    for key, value in (("PINNED_NO_STORE", native), ("PINNED_SOFTWARE_AES", aes), ("PINNED_METADATA", metadata)):
        monkeypatch.setattr(qa, key, hashlib.sha256(value).hexdigest())
    report = {"qa_only": True, "exact_production_client": False, "production_client_modified": False,
        "source_apk_sha256": qa.PINNED_DIAGNOSTIC, "original_sha256": qa.PINNED_AES_BEFORE,
        "patched_sha256": qa.PINNED_SOFTWARE_AES,
        "verification": {key: True for key in ("nist_sp800_38a", "original_software_and_patched_exports_match_oracle",
                                                  "input_key_iv_preserved", "caller_abi_preserved")},
        "iap_qa": {"qa_only": True, "emulator_no_store": True, "exact_production_client": False,
            "original_sha256": qa.PINNED_NATIVE_BEFORE, "patched_sha256": qa.PINNED_NO_STORE,
            "store_initialized": False, "purchase_receipt_grant_functions_modified": False,
            "verification": {"real_managed_factory_and_success_getter_executed": True,
                "hidden_x8_preserved_across_runtime_calls": True, "store_purchase_or_grant_code_executed": False}}}
    source = tmp_path / "intermediate.apk"
    with ZipFile(source, "w") as archive:
        for name, raw in ((qa.IL2CPP, native), (qa.FAST_AES, aes), (qa.METADATA_NAME, metadata),
                          ("classes.dex", b"original primary dex"), ("classes2.dex", b"existing diagnostic dex"),
                          ("AndroidManifest.xml", b"unchanged until the manifest-only rebuild"),
                          ("resources.arsc", b"original resources"), ("META-INF/OLD.SF", b"old signature")):
            archive.writestr(name, raw)
        archive.writestr(qa.AES_MARKER, json.dumps(report))
        archive.writestr("assets/idoly-local.json", json.dumps({"package": qa.PACKAGE,
            "native_output_sha256": qa.PINNED_NATIVE_BEFORE, "metadata_patch": {
                "input_sha256": qa.PINNED_METADATA_ORIGINAL, "output_sha256": qa.PINNED_METADATA}}))
    report.update(output_apk_sha256=qa.digest(source), output_bytes=source.stat().st_size,
                  untrusted_runtime_token="FAKE_PRIVATE_TOKEN_MUST_NOT_ENTER_UI_PROVENANCE")
    path = tmp_path / "qa-aes-report.json"
    path.write_text(json.dumps(report))
    return source, path, report


def test_valid_aes_intermediate_binds_safe_provenance_without_tokens(intermediate):
    source, report_path, report = intermediate
    inventory, provenance = qa.validate_input(source, report_path, report["output_apk_sha256"])
    assert inventory[qa.IL2CPP] == qa.PINNED_NO_STORE
    assert inventory[qa.METADATA_NAME] == qa.PINNED_METADATA
    assert "META-INF/OLD.SF" not in inventory
    assert provenance["original_source_sha256"] == qa.PINNED_DIAGNOSTIC
    assert provenance["metadata_original_sha256"] == qa.PINNED_METADATA_ORIGINAL
    assert report["untrusted_runtime_token"] not in json.dumps(provenance)
    assert all(isinstance(value, str) and len(value) == 64 for value in provenance.values())


@pytest.mark.parametrize("changed", ("input-hash", "report-output", "original-diagnostic", "original-alias",
    "production", "no-store", "iap-library", "iap-abi", "aes-abi"))
def test_intermediate_requires_the_pinned_diagnostic_and_both_verified_adaptations(intermediate, changed):
    source, report_path, report = intermediate
    expected = report["output_apk_sha256"]
    if changed == "input-hash":
        expected = "0" * 64
    elif changed == "report-output":
        report["output_apk_sha256"] = "0" * 64
    elif changed == "original-diagnostic":
        report["source_apk_sha256"] = "0" * 64
    elif changed == "original-alias":
        report["original_source_sha256"] = "0" * 64
    elif changed == "production":
        report["production_client_modified"] = True
    elif changed == "no-store":
        report["iap_qa"]["emulator_no_store"] = False
    elif changed == "iap-library":
        report["iap_qa"]["patched_sha256"] = "0" * 64
    elif changed == "iap-abi":
        report["iap_qa"]["verification"]["hidden_x8_preserved_across_runtime_calls"] = False
    elif changed == "aes-abi":
        report["verification"]["caller_abi_preserved"] = False
    report_path.write_text(json.dumps(report))
    with pytest.raises(qa.AndroidPackagingError):
        qa.validate_input(source, report_path, expected)


def decoded(tmp_path, package=None):
    root = tmp_path / "decoded"
    (root / "dex").mkdir(parents=True)
    for name in ("classes.dex", "classes2.dex", "classes10.dex"):
        (root / "dex" / name).write_bytes(b"preserved DEX")
    (root / "AndroidManifest.xml").write_text(f'''<manifest xmlns:android="{qa.ANDROID[1:-1]}" package="{package or qa.PACKAGE}">
      <application android:debuggable="false"><provider android:name="ExistingProvider" android:authorities="{qa.PACKAGE}.bootstrap" android:exported="false" /></application>
    </manifest>''')
    return root


def test_manifest_only_adds_nonexported_provider_debuggable_and_next_dex(tmp_path):
    root = decoded(tmp_path)
    originals = {p.name: p.read_bytes() for p in (root / "dex").iterdir()}
    assert qa.add_provider(root) == "classes11.dex"
    manifest = ET.parse(root / "AndroidManifest.xml").getroot()
    assert manifest.get("package") == qa.PACKAGE
    application = manifest.find("application")
    assert application.get(qa.ANDROID + "debuggable") == "true"
    assert len(application.findall("provider")) == 2
    provider = application.findall("provider")[-1]
    assert provider.get(qa.ANDROID + "name") == qa.PROVIDER
    assert provider.get(qa.ANDROID + "authorities") == qa.AUTHORITY
    assert provider.get(qa.ANDROID + "exported") == "false"
    assert originals == {p.name: p.read_bytes() for p in (root / "dex").iterdir()}
    with pytest.raises(qa.AndroidPackagingError):
        qa.add_provider(root)


def test_manifest_cannot_repackage_production_identity(tmp_path):
    root = decoded(tmp_path, "game.qualiarts.idolypride")
    before = (root / "AndroidManifest.xml").read_bytes()
    with pytest.raises(qa.AndroidPackagingError):
        qa.add_provider(root)
    assert (root / "AndroidManifest.xml").read_bytes() == before


@pytest.mark.parametrize("bad", ("duplicate", "../private", "/absolute", "bad\\member"))
def test_inventory_rejects_duplicates_and_unsafe_zip_names(tmp_path, bad):
    path = tmp_path / "input.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("duplicate" if bad == "duplicate" else "normal", b"one")
        if bad == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr(bad, b"two")
        else:
            archive.writestr(bad, b"two")
    with ZipFile(path) as archive, pytest.raises(qa.AndroidPackagingError):
        qa.inventory(archive)


def test_explicit_emulator_opt_in_precedes_any_input_or_tool_access(tmp_path):
    with pytest.raises(qa.AndroidPackagingError, match="emulator-only"):
        qa.package(tmp_path / "missing.apk", tmp_path / "new.apk", qa_aes_report=tmp_path / "missing.json",
                   expected_source_sha256="0" * 64, native_library=tmp_path / "missing.so")


def test_compiled_provider_requires_nonexported_and_debuggable_contract():
    xml = f'''E: manifest
  E: application
    A: android:debuggable(0x0101000f)=(type 0x12)0xffffffff
    E: provider
      A: android:name(0x01010003)="{qa.PROVIDER}"
      A: android:authorities(0x01010018)="{qa.AUTHORITY}"
      A: android:exported(0x01010010)=(type 0x12)0x0
'''
    qa.verify_provider_xml(xml)
    with pytest.raises(qa.AndroidPackagingError):
        qa.verify_provider_xml(xml.replace("(type 0x12)0x0", "(type 0x12)0xffffffff"))
    # Observed output of the installed SDK34 aapt2 uses namespace URLs and
    # literal booleans, rather than the older typed-hex presentation.
    real_format = xml.replace("android:", "http://schemas.android.com/apk/res/android:")
    real_format = real_format.replace("(type 0x12)0xffffffff", "true").replace("(type 0x12)0x0", "false")
    qa.verify_provider_xml(real_format)
    with pytest.raises(qa.AndroidPackagingError):
        qa.verify_provider_xml(real_format.replace("debuggable(0x0101000f)=true", "debuggable(0x0101000f)=false"))
