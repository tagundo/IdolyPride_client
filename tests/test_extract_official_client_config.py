"""Synthetic parser and source-integrity checks; never contact official services."""
import hashlib
import importlib.util
import io
from pathlib import Path
import plistlib
from zipfile import ZipFile, ZipInfo

import pytest

_PATH = Path(__file__).resolve().parents[1]/"tools/extract_official_client_config.py"
_SPEC = importlib.util.spec_from_file_location("public_client_config_extractor",_PATH)
extractor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(extractor)

KEY = "AIza" + "syntheticPublicAppValueOnly"*2
APP = "1:543065248020:ios:babf05d967621a37ab3201"
CERT = "AB"*20


def google():
    return {"API_KEY":KEY,"PROJECT_ID":extractor.PROJECT_ID,"GCM_SENDER_ID":extractor.PROJECT_NUMBER,
            "GOOGLE_APP_ID":APP,"BUNDLE_ID":extractor.BUNDLE_ID}


def info():
    return {"CFBundleIdentifier":extractor.BUNDLE_ID,"CFBundleShortVersionString":"6.1.1"}


def badging(*,split=False):
    return "package: name='game.qualiarts.idolypride' versionCode='414' versionName='6.1.1'" + (" split='config.arm64_v8a'" if split else "") + "\n"


def signature():
    return ("Verifies\nSigner #1 certificate SHA-1 digest: " + CERT.lower()
            + "\nSigner #1 certificate SHA-256 digest: " + extractor.CERT_SHA256 + "\n")


def resources():
    fields = {"google_api_key":KEY,"google_app_id":APP.replace(":ios:",":android:"),
              "project_id":extractor.PROJECT_ID,"gcm_defaultSenderId":extractor.PROJECT_NUMBER}
    return "Package name=game.qualiarts.idolypride id=0x7f\n" + "\n".join(
        '    resource 0x7f12345%01x string/%s\n      () "%s"' % (n,key,value)
        for n,(key,value) in enumerate(fields.items())) + "\n"


def test_ios_public_identity_and_version_are_bound_to_google_config():
    config = extractor.parse_ios_config(plistlib.dumps(google()),plistlib.dumps(info()))
    assert config == {"api_key":KEY,"project_id":extractor.PROJECT_ID,"project_number":extractor.PROJECT_NUMBER,
        "google_app_id":APP,"bundle_id":extractor.BUNDLE_ID,"app_version":"6.1.1"}
    assert set(config) == {"api_key","project_id","project_number","google_app_id","bundle_id","app_version"}


@pytest.mark.parametrize("field,value",[("PROJECT_ID","other-project"),("BUNDLE_ID","other.bundle"),
    ("GCM_SENDER_ID","123"),("GOOGLE_APP_ID",APP.replace(":ios:",":android:")),("API_KEY","private-password")])
def test_ios_scope_and_malformed_public_keys_are_rejected_without_echo(field,value):
    data = google();data[field]=value
    with pytest.raises(extractor.ConfigExtractionError) as failure:
        extractor.parse_ios_config(plistlib.dumps(data),plistlib.dumps(info()))
    assert value not in str(failure.value) and KEY not in str(failure.value)


@pytest.mark.parametrize("field,value",[("CFBundleIdentifier","other.bundle"),("CFBundleShortVersionString","6.1.2")])
def test_ios_app_info_must_match_original_scope(field,value):
    data=info();data[field]=value
    with pytest.raises(extractor.ConfigExtractionError):
        extractor.parse_ios_config(plistlib.dumps(google()),plistlib.dumps(data))


@pytest.mark.parametrize("raw",[b"",b"not plist",plistlib.dumps([google()])])
def test_ios_bad_metadata_fails_closed(raw):
    with pytest.raises(extractor.ConfigExtractionError):
        extractor.parse_ios_config(raw,plistlib.dumps(info()))


def test_android_default_public_resources_and_original_signature():
    fields=extractor.parse_android_resources(resources())
    assert fields["google_api_key"]==KEY and set(fields)==extractor._REQUIRED_ANDROID
    assert extractor.parse_android_certificate(signature())==CERT
    assert extractor.parse_android_badging(badging())["versionName"]=="6.1.1"
    assert extractor.parse_android_badging(badging(split=True))["split"]=="config.arm64_v8a"


@pytest.mark.parametrize("changed",[
    lambda text:text.replace("string/google_api_key","string/unrelated"),
    lambda text:text + '    resource 0x7f123450 string/google_api_key\n      (ja) "AIzaDifferentPublicAppKey1234567890"\n',
    lambda text:text.replace('() "'+KEY+'"','() 0x7f123456'),
])
def test_android_missing_alias_or_conflicting_locale_resource_rejected(changed):
    with pytest.raises(extractor.ConfigExtractionError):
        extractor.parse_android_resources(changed(resources()))


@pytest.mark.parametrize("raw",[
    "",signature().replace(extractor.CERT_SHA256,"ab"*32),
    signature()+signature().replace("#1","#2"),
    signature().replace(CERT.lower(),"a"*39),
])
def test_android_requires_one_pinned_original_signer(raw):
    with pytest.raises(extractor.ConfigExtractionError):
        extractor.parse_android_certificate(raw)


@pytest.mark.parametrize("raw",[
    badging().replace("game.qualiarts.idolypride","other.bundle"),
    badging().replace("versionName='6.1.1'","versionName='6.2.0'"),
    badging().replace("versionCode='414'","versionCode='415'"),
    badging().replace("package:","not-package:"),
    badging().replace("versionCode='414'","versionCode='414' name='duplicate'"),
])
def test_android_badging_scope_or_duplicate_fields_fail_closed(raw):
    with pytest.raises(extractor.ConfigExtractionError):
        extractor.parse_android_badging(raw)


def test_source_pin_must_match_size_digest_and_regular_file(tmp_path,monkeypatch):
    raw=b"synthetic public original"
    path=tmp_path/"original.ipa";path.write_bytes(raw)
    pin={"asset_id":1,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    monkeypatch.setitem(extractor.PINS,"ios",pin)
    assert extractor.verify_source(path,"ios")==pin
    path.write_bytes(raw[:-1]+b"!")
    with pytest.raises(extractor.ConfigExtractionError,match="source_sha_mismatch"):
        extractor.verify_source(path,"ios")
    path.write_bytes(raw+b"x")
    with pytest.raises(extractor.ConfigExtractionError,match="source_size_mismatch"):
        extractor.verify_source(path,"ios")
    link=tmp_path/"link";link.symlink_to(path)
    with pytest.raises(extractor.ConfigExtractionError,match="source_not_regular"):
        extractor.verify_source(link,"ios")


def synthetic_ipa(path,*,duplicate=False):
    with ZipFile(path,"w") as out:
        out.writestr("Payload/IDOLY PRIDE.app/GoogleService-Info.plist",plistlib.dumps(google()))
        out.writestr("Payload/IDOLY PRIDE.app/Info.plist",plistlib.dumps(info()))
        if duplicate:
            out.writestr("Payload/Second.app/GoogleService-Info.plist",plistlib.dumps(google()))
    raw=path.read_bytes()
    return {"asset_id":1,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}


def test_ios_extraction_records_exact_members_and_never_executes_app(tmp_path,monkeypatch):
    path=tmp_path/"original.ipa";pin=synthetic_ipa(path)
    monkeypatch.setitem(extractor.PINS,"ios",pin)
    config,proof=extractor.extract_ios(path)
    assert config["api_key"]==KEY and proof["source"]==pin
    assert proof["identity_scope_verified"] and proof["app_executed"] is False
    assert {row["member"] for row in proof["members"]}=={
        "Payload/IDOLY PRIDE.app/GoogleService-Info.plist","Payload/IDOLY PRIDE.app/Info.plist"}
    with ZipFile(path) as archive:
        for row in proof["members"]:
            raw=archive.read(row["member"])
            assert row["bytes"]==len(raw) and row["sha256"]==hashlib.sha256(raw).hexdigest()


def test_ios_multiple_google_apps_are_not_arbitrarily_selected(tmp_path,monkeypatch):
    path=tmp_path/"original.ipa";pin=synthetic_ipa(path,duplicate=True)
    monkeypatch.setitem(extractor.PINS,"ios",pin)
    with pytest.raises(extractor.ConfigExtractionError,match="ios_google_config_ambiguous"):
        extractor.extract_ios(path)


@pytest.mark.parametrize("name",["../GoogleService-Info.plist","/absolute","dir\\file"])
def test_archive_traversal_or_platform_aliases_rejected(name):
    content=io.BytesIO()
    with ZipFile(content,"w") as archive:archive.writestr(name,b"x")
    with ZipFile(content) as archive:
        with pytest.raises(extractor.ConfigExtractionError,match="archive_member_invalid"):
            extractor.archive_inventory(archive)


def test_archive_symlink_and_enormous_metadata_rejected():
    content=io.BytesIO()
    with ZipFile(content,"w") as archive:
        entry=ZipInfo("config");entry.external_attr=0o120777 << 16
        archive.writestr(entry,b"target")
    with ZipFile(content) as archive:
        with pytest.raises(extractor.ConfigExtractionError,match="archive_member_invalid"):
            extractor.archive_inventory(archive)
    content=io.BytesIO()
    with ZipFile(content,"w") as archive:archive.writestr("config",b"x"*(extractor.MAX_METADATA+1))
    with ZipFile(content) as archive:
        with pytest.raises(extractor.ConfigExtractionError,match="metadata_size_invalid"):
            extractor.read_metadata(archive,"config")


def test_workflow_only_reads_original_assets_and_uploads_small_config():
    workflow=(_PATH.parents[1]/".github/workflows/verify-official-client-config.yml").read_text()
    assert "workflow_dispatch:" in workflow and "contents: read" in workflow
    assert "725761399" in workflow and "725772331" in workflow
    assert "branches: [feat/ios-unified-server]" in workflow
    assert "draft-release assets" in workflow and "contents: write" in workflow
    assert "actions/upload-artifact@v4" in workflow and "public-client-config.json" in workflow
    for forbidden in ("gh release","sideload","adb ","official-account-password"):
        assert forbidden not in workflow
