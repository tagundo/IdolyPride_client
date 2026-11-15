"""Portable release trust-boundary tests; no downloads, tools or device work."""
import hashlib
import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest

SPEC=importlib.util.spec_from_file_location("release_platform_builds",Path(__file__).resolve().parents[1]/"tools/release_platform_builds.py")
builds=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builds)
SOURCE="a"*40


class Guard:
    def check(self):pass


def passed_qa():
    return {"ok":True,"target":"Android emulator","device_game_client_tested":False,
            **{key:True for key in builds.QA_FLAGS},
            "main_live":{"platform":"Android native","quest_id":"qt-main-1-001-01","ruleset":"live-v5","chart_count":183,"beat_count":855}}


def test_complete_native_x86_qa_receipt_is_accepted():
    report=passed_qa()
    assert builds.validate_android_qa(report) is report


@pytest.mark.parametrize("key",builds.QA_FLAGS)
def test_incomplete_preservation_or_engine_qa_is_rejected(key):
    report=passed_qa();report[key]=False
    with pytest.raises(builds.BuildError,match="preservation_or_engine"):
        builds.validate_android_qa(report)


@pytest.mark.parametrize("key,value",[("ok",1),("device_game_client_tested",True),("target","physical device")])
def test_qa_scope_and_boolean_types_are_strict(key,value):
    report=passed_qa();report[key]=value
    with pytest.raises(builds.BuildError):builds.validate_android_qa(report)


def test_wrong_ruleset_cannot_satisfy_engine_qa():
    report=passed_qa();report["main_live"]["ruleset"]="another"
    with pytest.raises(builds.BuildError,match="live_engine"):
        builds.validate_android_qa(report)


def test_source_binding_requires_clean_current_common_modules(monkeypatch,tmp_path):
    names=["src/idoly_local/"+name for name in ("app_runtime.py","diagnostics.py","resource_translation_runtime.py")]+["tools/release_platform_builds.py"]
    for name in names:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
    monkeypatch.setattr(builds,"ROOT",tmp_path)
    def capture(arguments,**kwargs):
        if arguments[1]=="rev-parse":return SOURCE
        if arguments[1]=="status":return ""
        assert arguments[1]=="ls-files"
        return "\n".join(names)+"\n"
    monkeypatch.setattr(builds,"capture",capture)
    pins=builds.source_binding(SOURCE)
    assert set(pins)==set(names)
    assert all(pins[name]==hashlib.sha256(name.encode()).hexdigest() for name in names)


def test_dirty_build_source_is_rejected_before_packaging(monkeypatch):
    def capture(arguments,**kwargs):
        return SOURCE if arguments[1]=="rev-parse" else " M src/idoly_local/app_runtime.py"
    monkeypatch.setattr(builds,"capture",capture)
    with pytest.raises(builds.BuildError,match="source_worktree_changed"):
        builds.source_binding(SOURCE)


def test_wrong_checkout_is_rejected(monkeypatch):
    monkeypatch.setattr(builds,"capture",lambda *args,**kwargs:"b"*40)
    with pytest.raises(builds.BuildError,match="frozen_source_required"):
        builds.source_binding(SOURCE)


@pytest.mark.parametrize("wrong_digest,wrong_size",[(False,False),(True,False),(False,True)])
def test_donor_member_is_streamed_and_pinned(tmp_path,wrong_digest,wrong_size):
    archive=tmp_path/"donor.zip";body=b"immutable public data"
    with ZipFile(archive,"w") as zipped:zipped.writestr("assets/ServerData.zip",body)
    pin={"bytes":len(body)+(1 if wrong_size else 0),"sha256":"f"*64 if wrong_digest else hashlib.sha256(body).hexdigest()}
    target=tmp_path/"ServerData.zip"
    with ZipFile(archive) as zipped:
        if wrong_digest or wrong_size:
            with pytest.raises(builds.BuildError):builds.copy_member(zipped,"assets/ServerData.zip",target,pin,Guard())
        else:builds.copy_member(zipped,"assets/ServerData.zip",target,pin,Guard())
    if not wrong_digest and not wrong_size:assert target.read_bytes()==body


def test_duplicate_donor_member_is_rejected(tmp_path):
    archive=tmp_path/"donor.zip"
    with ZipFile(archive,"w") as zipped:
        zipped.writestr("assets/ServerData.zip",b"a")
        with pytest.warns(UserWarning):zipped.writestr("assets/ServerData.zip",b"a")
    with ZipFile(archive) as zipped,pytest.raises(builds.BuildError,match="duplicate"):
        builds.copy_member(zipped,"assets/ServerData.zip",tmp_path/"out",{"bytes":1,"sha256":hashlib.sha256(b"a").hexdigest()},Guard())


def apk_fixture(monkeypatch,tmp_path,*,wrong_cert=False,wrong_version=False,tampered=False,debuggable=False):
    data,translation,engine=b"publicdata",b"translations",b"source-built-engine"
    pin=lambda raw:{"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr(builds,"SERVER_DATA",pin(data))
    monkeypatch.setattr(builds,"TRANSLATIONS",{"android":pin(translation)})
    target=tmp_path/"server.apk"
    with ZipFile(target,"w") as zipped:
        zipped.writestr("assets/ServerData.zip",b"changed!!!" if tampered else data)
        zipped.writestr("assets/bundledTranslations.zip",translation)
        zipped.writestr("lib/arm64-v8a/libidoly_live.so",engine)
    def capture(arguments,**kwargs):
        name=Path(arguments[0]).name
        if name=="apksigner":return "Verified using v2 scheme (APK Signature Scheme v2): true\nSigner #1 certificate SHA-256 digest: "+("f"*64 if wrong_cert else builds.ANDROID_CERT)+"\n"
        if name=="aapt":return "package: name='"+builds.ANDROID_PACKAGE+"' versionCode='"+("49" if wrong_version else "50")+"' versionName='0.3.33'\n"+("application-debuggable\n" if debuggable else "")
        assert name=="zipalign";return "Verification successful"
    monkeypatch.setattr(builds,"capture",capture)
    return target,{"library_bytes":len(engine),"library_sha256":hashlib.sha256(engine).hexdigest()}


def test_arm_apk_requires_exact_identity_signer_and_embedded_bytes(monkeypatch,tmp_path):
    target,engine=apk_fixture(monkeypatch,tmp_path)
    result=builds.check_apk(target,"arm64-v8a",{},engine,tmp_path)
    assert result["certificate_sha256"]==builds.ANDROID_CERT and result["build_number"]==50


@pytest.mark.parametrize("change",["wrong_cert","wrong_version","tampered","debuggable"])
def test_changed_apk_identity_or_payload_fails(monkeypatch,tmp_path,change):
    target,engine=apk_fixture(monkeypatch,tmp_path,**{change:True})
    with pytest.raises(builds.BuildError):builds.check_apk(target,"arm64-v8a",{},engine,tmp_path)


def test_mac_native_execution_cannot_be_claimed_by_linux(monkeypatch,tmp_path):
    monkeypatch.setattr(builds.sys,"platform","linux")
    with pytest.raises(builds.BuildError,match="actual_Apple_Silicon"):
        builds.build_macos(tmp_path,tmp_path,SOURCE,{},Guard())


def test_base_reports_keep_physical_limits_explicit(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID","17")
    report=builds.base_report("android",SOURCE,{}, {})
    assert report["execution"]=={"actual_macos_execution":False,"actual_android_arm64_execution":False,"physical_PlayCover_execution":False}
    assert report["validation"]["live_engine_source_built"] is True


def test_build_cli_refuses_local_execution_before_any_tool(monkeypatch,tmp_path):
    monkeypatch.delenv("GITHUB_ACTIONS",raising=False)
    monkeypatch.setattr(builds.sys,"argv",["release_platform_builds.py","--platform","android","--source-commit",SOURCE,
        "--work",str(tmp_path/"work"),"--output",str(tmp_path/"output")])
    def forbidden(*args,**kwargs):raise AssertionError("No local tool is allowed")
    monkeypatch.setattr(builds,"source_binding",forbidden)
    with pytest.raises(builds.BuildError,match="owned_Actions"):
        builds.main()


def reference_payload(monkeypatch,tmp_path,*,missing=None,extra=None):
    files={"data/"+name:("fixture "+name).encode() for name in builds.QA_REFERENCE_FILES}
    files.update({"data/master-json/Setting.json":b"[]",
                  "data/public-fixtures/manifest.json":b"{}",
                  "data/public-fixtures/responses/public-sample.pb":b"",
                  "data/original-master/unneeded.bin":b"not a host QA reference"})
    if missing is not None:files.pop("data/"+missing)
    if extra is not None:files[extra]=b"unsafe"
    path=tmp_path/"ServerData.zip"
    with ZipFile(path,"w") as archive:
        for name,raw in files.items():archive.writestr(name,raw)
    monkeypatch.setattr(builds,"SERVER_DATA",{"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    return path,files


def test_pinned_qa_payload_extracts_complete_story_tutorial_and_master_references(monkeypatch,tmp_path):
    payload,files=reference_payload(monkeypatch,tmp_path)
    destination=tmp_path/"references"
    builds.extract_qa_references(payload,destination,Guard())
    actual={str(path.relative_to(destination)):path.read_bytes() for path in destination.rglob("*") if path.is_file()}
    expected={name.removeprefix("data/"):raw for name,raw in files.items()
              if not name.startswith(("data/original-master/","data/public-fixtures/"))}
    assert actual==expected
    assert builds.QA_REFERENCE_FILES<=actual.keys()
    assert "public-story/manifest.json" in actual and "public-story/story-list-event.pb" in actual
    assert "public-story/story-list-extra.pb" in actual
    # Valid protobuf public responses can be empty. They are runtime fixtures,
    # not host inputs for these QA helpers, and must not trip selected-ref bounds.
    assert files["data/public-fixtures/responses/public-sample.pb"] == b""
    assert not (destination/"public-fixtures").exists()


@pytest.mark.parametrize("missing",sorted(builds.QA_REFERENCE_FILES))
def test_incomplete_host_qa_reference_roster_is_rejected_before_emulator(monkeypatch,tmp_path,missing):
    payload,_files=reference_payload(monkeypatch,tmp_path,missing=missing)
    with pytest.raises(builds.BuildError,match="QA_references_missing"):
        builds.extract_qa_references(payload,tmp_path/"references",Guard())


@pytest.mark.parametrize("extra",["data/public-story/../escape.pb","data/public-tutorial/../../escape.pb"])
def test_public_reference_prefix_does_not_allow_path_escape(monkeypatch,tmp_path,extra):
    payload,_files=reference_payload(monkeypatch,tmp_path,extra=extra)
    with pytest.raises(builds.BuildError,match="QA_reference_path_invalid"):
        builds.extract_qa_references(payload,tmp_path/"references",Guard())
    assert not (tmp_path/"escape.pb").exists()
