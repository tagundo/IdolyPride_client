"""QA UI packaging guards and preservation contract, without a game runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest


spec = importlib.util.spec_from_file_location("qa_ui_packager", Path(__file__).resolve().parents[1] / "tools/package_qa_ui_client.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


@pytest.mark.parametrize("value", [1, 1800000, 7200000, 21600000])
def test_public_observer_session_integer_range(value):
    assert qa.validate_session_millis(value) == value


@pytest.mark.parametrize("value", [True, False, None, 0, -1, 21600001, 1800000.0, "21600000"])
def test_public_observer_session_rejects_bool_noninteger_and_unbounded(value):
    with pytest.raises(qa.AndroidPackagingError):
        qa.validate_session_millis(value)


def test_observer_default_remains_thirty_minutes_and_cli_documents_six_hour_cap(capsys):
    assert qa.DEFAULT_SESSION_MILLIS == 1800000
    assert qa.MAX_SESSION_MILLIS == 21600000
    with pytest.raises(SystemExit) as result:
        qa.main(["--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert "default30min" in help_text and "maximum6h" in help_text


def test_session_refresh_unknown_source_precedes_signing_or_output_access(tmp_path):
    source = tmp_path / "unknown.apk"
    source.write_bytes(b"not the pinned QA APK")
    output = tmp_path / "not-created/new.apk"
    with pytest.raises(qa.AndroidPackagingError, match="exact pinned"):
        qa.refresh_session(source, output, expected_source_sha256="0" * 64,
                           emulator_only=True, session_millis=7200000)
    assert not output.parent.exists()


def test_session_repack_changes_only_observer_dex_and_public_marker(tmp_path):
    source, output = tmp_path / "input.apk", tmp_path / "output.apk"
    members = {"classes.dex": b"game SDK", "classes5.dex": b"old QA observer",
               qa.MARKER: b"old public QA marker", qa.NATIVE: b"unchanged native observer",
               qa.METADATA_NAME: b"cached metadata must not change", "assets/bin/Data/globalgamemanagers": b"GMM",
               "assets/bin/Data/unity_app_guid": b"c07eb3a7-ce76-523d-8bfa-19c3a9eb6b36",
               "AndroidManifest.xml": b"manifest", "res/xml/network_security_config.xml": b"NSC"}
    with ZipFile(source, "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    changes = {"classes5.dex": b"new QA observer", qa.MARKER: b'{"session_millis":7200000}'}
    qa.repack_session(source, output, changes)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == set(members)
        for name, raw in members.items():
            assert archive.read(name) == changes.get(name, raw)
    with pytest.raises(qa.AndroidPackagingError, match="only observer"):
        qa.repack_session(source, tmp_path / "forbidden.apk", {**changes, qa.NATIVE: b"not allowed"})


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


def compiled_unified_manifest(*, probe=False):
    xml='''N: android=http://schemas.android.com/apk/res/android (line=2)
  E: manifest (line=2)
    A: package="game.qualiarts.idolypride.local.diagnostics" (Raw: "game.qualiarts.idolypride.local.diagnostics")
    E: uses-sdk (line=3)
      A: android:targetSdkVersion(0x01010270)=36
    E: application (line=4)
      A: android:appComponentFactory(0x0101057a)="game.qualiarts.idolypride.localserver.UnifiedComponentFactory"
      A: android:debuggable(0x0101000f)=false
      E: activity (line=5)
        A: android:name(0x01010003)="game.qualiarts.idolypride.localserver.MainActivity"
        A: android:theme(0x01010000)=@0x01030238
        E: intent-filter (line=6)
          E: action (line=7)
            A: android:name(0x01010003)="android.intent.action.MAIN"
      E: activity (line=8)
        A: android:name(0x01010003)="game.qualiarts.idolypride.localserver.UnifiedGameActivity"
      E: activity-alias (line=9)
        A: android:name(0x01010003)="com.google.firebase.MessagingUnityPlayerActivity"
        A: android:targetActivity(0x01010202)="game.qualiarts.idolypride.localserver.MainActivity"
'''
    if probe:
        xml=xml.replace('debuggable(0x0101000f)=false','debuggable(0x0101000f)=true')
        xml+='''      E: provider (line=10)
        A: android:name(0x01010003)="game.qualiarts.idolypride.qa.ui.QaUiProvider"
        A: android:exported(0x01010010)=false
'''
    return xml


def test_observer_compiled_manifest_preserves_actual_factory_and_activity_tree():
    before,after=compiled_unified_manifest(),compiled_unified_manifest(probe=True)
    after=after.replace('(line=5)','(line=400)').replace('android:theme','http://schemas.android.com/apk/res/android:theme')
    assert qa.verify_manifest_preserved(before,after,qa.UNIFIED_PROFILE)=={
        'compiled_manifest_structure_preserved':True,'manifest_factory_and_activities_preserved':True}


@pytest.mark.parametrize('old,new',[
    ('localserver.UnifiedComponentFactory','localserver.OtherFactory'),
    ('appComponentFactory(0x0101057a)','appComponentFactory(0x0101057b)'),
    ('localserver.MainActivity','localserver.OtherActivity'),
    ('localserver.UnifiedGameActivity','localserver.OtherGameActivity'),
    ('targetActivity(0x01010202)','targetActivity(0x01010203)'),
    ('@0x01030238','@0x01030239'),
    ('android.intent.action.MAIN','android.intent.action.VIEW'),
    ('targetSdkVersion(0x01010270)=36','targetSdkVersion(0x01010270)=35'),
])
def test_observer_manifest_rejects_factory_bypass_and_nested_launch_contract_drift(old,new):
    with pytest.raises(qa.AndroidPackagingError,match='changed application factory/activity'):
        qa.verify_manifest_preserved(compiled_unified_manifest(),compiled_unified_manifest(probe=True).replace(old,new),qa.UNIFIED_PROFILE)


def test_observer_manifest_rejects_missing_factory_in_current_product_input():
    before=compiled_unified_manifest().replace('localserver.UnifiedComponentFactory','localserver.OtherFactory')
    with pytest.raises(qa.AndroidPackagingError,match='exact launcher component factory'):
        qa.verify_manifest_preserved(before,compiled_unified_manifest(probe=True),qa.UNIFIED_PROFILE)


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


@pytest.fixture
def normal_local(tmp_path, monkeypatch):
    payload = {qa.IL2CPP: b"normal bootstrap, original store", qa.FAST_AES: b"original AES",
        qa.METADATA_NAME: b"normal local endpoint metadata", "lib/arm64-v8a/libunity.so": b"original Unity GLES"}
    for name in qa.PINNED_NORMAL_DEX:
        payload[name] = name.encode()
    for key, name in (("PINNED_NATIVE_BEFORE", qa.IL2CPP), ("PINNED_AES_BEFORE", qa.FAST_AES),
                      ("PINNED_METADATA", qa.METADATA_NAME), ("PINNED_UNITY", "lib/arm64-v8a/libunity.so")):
        monkeypatch.setattr(qa, key, hashlib.sha256(payload[name]).hexdigest())
    monkeypatch.setattr(qa, "PINNED_NORMAL_DEX", {name: hashlib.sha256(payload[name]).hexdigest()
                                               for name in qa.PINNED_NORMAL_DEX})
    marker = {"package": qa.NORMAL_PACKAGE, "original_package": "game.qualiarts.idolypride",
        "input_sha256": qa.PINNED_XAPK, "endpoint": "http://127.0.0.1:50051", "native_override": False,
        "native_output_sha256": qa.PINNED_NATIVE_BEFORE, "native_original_sha256": qa.PINNED_NATIVE_ORIGINAL,
        "metadata_patch": {"input_sha256": qa.PINNED_METADATA_ORIGINAL, "output_sha256": qa.PINNED_METADATA},
        "native_bootstrap": {"input_sha256": qa.PINNED_NATIVE_ORIGINAL, "output_sha256": qa.PINNED_NATIVE_BEFORE,
            "patches": [{"method": method} for method in sorted(qa.BOOTSTRAP_METHODS)]}}
    return tmp_path / "normal.apk", payload, marker


def write_normal_fixture(normal_local, monkeypatch):
    source, payload, marker = normal_local
    with ZipFile(source, "w") as archive:
        for name, raw in payload.items():
            archive.writestr(name, raw)
        archive.writestr("assets/idoly-local.json", json.dumps(marker))
    monkeypatch.setattr(qa, "PINNED_NORMAL", qa.digest(source))
    monkeypatch.setattr(qa, "PINNED_NORMAL_BYTES", source.stat().st_size)
    return source


def test_normal_local_requires_explicit_separate_profile_and_never_uses_diagnostic_report(normal_local, monkeypatch):
    source = write_normal_fixture(normal_local, monkeypatch)
    members, provenance = qa.validate_input(source, None, qa.PINNED_NORMAL, qa.NORMAL_PROFILE)
    assert members[qa.FAST_AES] == qa.PINNED_AES_BEFORE
    assert provenance["normal_local_apk_sha256"] == qa.PINNED_NORMAL
    assert provenance["original_source_sha256"] == qa.PINNED_XAPK
    assert "software_aes_sha256" not in provenance and "native_no_store_sha256" not in provenance
    with pytest.raises(qa.AndroidPackagingError, match="requires.*QA AES report"):
        qa.validate_input(source, None, qa.PINNED_NORMAL)
    with pytest.raises(qa.AndroidPackagingError, match="must not receive"):
        qa.validate_input(source, Path("missing-report.json"), qa.PINNED_NORMAL, qa.NORMAL_PROFILE)


@pytest.mark.parametrize("change", ("wrong-hash", "wrong-size", "aes", "native", "unity", "dex",
    "extra-dex", "qa-marker", "ui-library", "package", "override", "original-native", "missing-bootstrap"))
def test_normal_local_rejects_adaptations_and_wrong_provenance(normal_local, monkeypatch, change):
    _, payload, marker = normal_local
    names = {"aes": qa.FAST_AES, "native": qa.IL2CPP, "unity": "lib/arm64-v8a/libunity.so", "dex": "classes2.dex"}
    if change in names:
        payload[names[change]] = b"changed adaptation"
    elif change == "extra-dex":
        payload["classes5.dex"] = b"preexisting observer"
    elif change == "qa-marker":
        payload[qa.AES_MARKER] = b"{}"
    elif change == "ui-library":
        payload[qa.NATIVE] = b"prior UI observer"
    elif change == "package":
        marker["package"] = qa.PACKAGE
    elif change == "override":
        marker["native_override"] = True
    elif change == "original-native":
        marker["native_original_sha256"] = "0" * 64
    elif change == "missing-bootstrap":
        marker["native_bootstrap"]["patches"].pop()
    source = write_normal_fixture(normal_local, monkeypatch)
    expected = qa.PINNED_NORMAL
    if change == "wrong-hash":
        expected = "0" * 64
    elif change == "wrong-size":
        monkeypatch.setattr(qa, "PINNED_NORMAL_BYTES", source.stat().st_size + 1)
    with pytest.raises(qa.AndroidPackagingError):
        qa.validate_input(source, None, expected, qa.NORMAL_PROFILE)


def test_normal_profile_manifest_keeps_identity_fixed_authority_and_original_dex(tmp_path):
    root = decoded(tmp_path, qa.NORMAL_PACKAGE)
    before = {p.name: p.read_bytes() for p in (root / "dex").iterdir()}
    assert qa.add_provider(root, qa.NORMAL_PROFILE) == "classes11.dex"
    tree = ET.parse(root / "AndroidManifest.xml").getroot()
    assert tree.get("package") == qa.NORMAL_PACKAGE
    provider = tree.find("application").findall("provider")[-1]
    assert provider.get(qa.ANDROID + "authorities") == qa.NORMAL_PACKAGE + ".qa.ui"
    assert provider.get(qa.ANDROID + "exported") == "false"
    assert before == {p.name: p.read_bytes() for p in (root / "dex").iterdir()}
    with pytest.raises(qa.AndroidPackagingError):
        qa.add_provider(root)


@pytest.mark.parametrize("signers", ([], ["0" * 64], [qa.PINNED_NORMAL_CERT, qa.PINNED_NORMAL_CERT]))
def test_normal_signature_rejects_missing_wrong_or_multiple_signers(monkeypatch, signers):
    monkeypatch.setattr(qa, "_run", lambda *args: SimpleNamespace(stdout="\n".join(
        f"Signer #{i} certificate SHA-256 digest: {value}" for i, value in enumerate(signers, 1))))
    with pytest.raises(qa.AndroidPackagingError, match="signer"):
        qa.verify_normal_signature(Path("normal.apk"), Path("build-tools"))


def test_normal_signature_requires_published_cert_and_java_guard_pins_same_input(monkeypatch):
    monkeypatch.setattr(qa, "_run", lambda *args: SimpleNamespace(
        stdout=f"Signer #1 certificate SHA-256 digest: {qa.PINNED_NORMAL_CERT}\n"))
    qa.verify_normal_signature(Path("normal.apk"), Path("build-tools"))
    provider = (qa.JAVA_ROOT / "game/qualiarts/idolypride/qa/ui/QaUiProvider.java").read_text()
    assert f'NORMAL_INPUT_SHA256 = "{qa.PINNED_NORMAL}"' in provider
    assert f'NORMAL_PACKAGE = "{qa.NORMAL_PACKAGE}"' in provider


def test_caller_managed_qa_key_is_reused_without_creating_or_exposing_secrets(tmp_path, monkeypatch):
    key = tmp_path / "private-qa.p12"
    key.write_bytes(b"synthetic key fixture")
    key.chmod(0o600)
    monkeypatch.setenv("IDOLY_QA_UI_KEY_PASSWORD", "synthetic-test-password")
    selected, environment = qa.qa_signing_material(key)
    assert selected == key and selected.read_bytes() == b"synthetic key fixture"
    assert environment["IDOLY_QA_UI_KEY_PASSWORD"] == "synthetic-test-password"
    assert list(tmp_path.iterdir()) == [key]


@pytest.mark.parametrize("problem", ("directory", "group-readable", "missing-password"))
def test_caller_managed_qa_key_fails_closed_on_unsafe_material(tmp_path, monkeypatch, problem):
    key = tmp_path / "private-qa.p12"
    if problem == "directory":
        key.mkdir(mode=0o700)
    else:
        key.write_bytes(b"synthetic key fixture")
        key.chmod(0o640 if problem == "group-readable" else 0o600)
    monkeypatch.setenv("IDOLY_QA_UI_KEY_PASSWORD", "synthetic-test-password")
    if problem == "missing-password":
        monkeypatch.delenv("IDOLY_QA_UI_KEY_PASSWORD")
    with pytest.raises(qa.AndroidPackagingError):
        qa.qa_signing_material(key)


def test_default_qa_key_password_is_fresh_and_does_not_reuse_inherited_value(monkeypatch):
    monkeypatch.setenv("IDOLY_QA_UI_KEY_PASSWORD", "inherited-value-not-used-for-ephemeral-key")
    first, first_env = qa.qa_signing_material()
    second, second_env = qa.qa_signing_material()
    assert first is second is None
    assert first_env["IDOLY_QA_UI_KEY_PASSWORD"] != second_env["IDOLY_QA_UI_KEY_PASSWORD"]
    assert first_env["IDOLY_QA_UI_KEY_PASSWORD"] != "inherited-value-not-used-for-ephemeral-key"
