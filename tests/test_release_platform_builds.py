"""Portable release trust-boundary tests; no downloads, tools or device work."""
import hashlib
import json
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
             "main_live":{"platform":"Android native","quest_id":"qt-main-1-001-01","ruleset":"live-v5","chart_count":183,"beat_count":855},
            "account_management":{"scope":"Android emulator native UI and real document provider",
                "archive_filename_observed":"IdolyPride-Account-"+"a"*32+".zip",
                "owned_tables":["profiles","snapshots","profile_settings","starter_profiles","profile_lesson_progress","preference_receipts","main_live_attempts","profile_love_progress"],
                "imported_sessions":0,"physical_device_tested":False},
            "native_event_settings":{"scope":"Android emulator native event settings and encrypted Home RPC",
                "event_id":"love-23-0514","settings_revision":1,"start_time_ms":1000,"end_time_ms":1000+30*24*60*60*1000,
                "ruleset_sha256":"a"*64,"saved_file_verified":True,"effective_match":True,"home_event_verified":True,
                "progress_preserved":True,"selection_restored":True,"physical_device_tested":False,"gameplay_tested":False}}


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
    names=list(builds.COMMON_SOURCE_FILES)+["tools/release_platform_builds.py"]
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
        if name=="aapt":return "package: name='"+builds.ANDROID_PACKAGE+"' versionCode='"+("52" if wrong_version else "53")+"' versionName='0.3.36'\n"+("application-debuggable\n" if debuggable else "")
        assert name=="zipalign";return "Verification successful"
    monkeypatch.setattr(builds,"capture",capture)
    return target,{"library_bytes":len(engine),"library_sha256":hashlib.sha256(engine).hexdigest()}


def test_arm_apk_requires_exact_identity_signer_and_embedded_bytes(monkeypatch,tmp_path):
    target,engine=apk_fixture(monkeypatch,tmp_path)
    result=builds.check_apk(target,"arm64-v8a",{},engine,tmp_path)
    assert result["certificate_sha256"]==builds.ANDROID_CERT and result["build_number"]==53


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


@pytest.mark.parametrize("field,value", [("event_id", "unsupported-event"), ("effective_match", 1),
    ("progress_preserved", False), ("settings_revision", True), ("gameplay_tested", True)])
def test_native_event_scope_cannot_be_replaced_by_a_summary_flag(field, value):
    report = passed_qa()
    report["native_event_settings"][field] = value
    with pytest.raises(builds.BuildError, match="native_event_settings"):
        builds.validate_android_qa(report)


@pytest.mark.parametrize("damage", [None, "base", "proof", "output", "overlay"])
def test_native_inputs_use_only_verified_prepared_payload_with_original_donor_unchanged(monkeypatch, tmp_path, damage):
    from types import SimpleNamespace
    import shutil
    old, translated, prepared = b"old immutable base", b"unchanged translations", b"new source prepared payload"
    digest = lambda raw: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    donor = tmp_path / "original-donor.zip"
    with ZipFile(donor, "w") as archive:
        archive.writestr("assets/ServerData.zip", old)
        archive.writestr("assets/bundledTranslations.zip", translated)
    donor_raw = donor.read_bytes()
    monkeypatch.setattr(builds, "DONORS", {"android": {**digest(donor_raw), "prefix": "assets/"}})
    monkeypatch.setattr(builds, "BASE_SERVER_DATA", digest(old))
    monkeypatch.setattr(builds, "SERVER_DATA", digest(prepared))
    monkeypatch.setattr(builds, "TRANSLATIONS", {"android": digest(translated)})
    proof = {"schema": 1, "status": "PASS", "synthetic": "recording-contract"}
    repo = tmp_path / "repo"; (repo / "data").mkdir(parents=True)
    overlay = tmp_path / "work/latest-server-overlay.zip"
    monkeypatch.setattr(builds, "ROOT", repo)
    seen = []
    def source_pointer():
        seen.append(("source-pointer",))
        return digest(prepared)
    def fetch_overlay(path):
        assert path == overlay and not path.exists()
        path.write_bytes(prepared)
        seen.append(("fetch",))
        return digest(prepared)
    def verify_overlay(path):
        assert path == overlay and path.read_bytes() == prepared
        assert damage != "overlay", "fixed_overlay_pin_differs"
        seen.append(("overlay",))
    def upgrade(base, output, *, overlay_zip, report_path):
        assert overlay_zip == overlay
        assert base.read_bytes() == old and not output.exists()
        assert report_path == tmp_path / "work/server-data-preparation.json"
        report_path.write_text(json.dumps(proof))
        seen.append(("prepare", base.name, output.name))
        output.write_bytes(b"wrong output" if damage == "output" else prepared)
        if damage == "base": base.write_bytes(b"altered base")
        return dict(proof, synthetic="changed") if damage == "proof" else dict(proof)
    def verify_report(value):
        assert value == proof, "fixed_preparation_proof_differs"
        seen.append(("proof",))
        return dict(value)
    def verify_payload(path):
        assert path.read_bytes() == prepared, "fixed_payload_pin_differs"
        seen.append(("payload",))
        return digest(prepared)
    monkeypatch.setattr(builds, "LOVE_SERVER_DATA", SimpleNamespace(base_pin=lambda: digest(old),
        verify_upgrade_proof=verify_report, verify_payload=verify_payload, verify_overlay=verify_overlay,
        verify_source_pointer=source_pointer, fetch_overlay=fetch_overlay))
    def load(name, path):
        if str(path).endswith("fetch_inputs.py"):
            return SimpleNamespace(lfs_download=lambda record, target: shutil.copyfile(donor, target))
        assert str(path).endswith("prepare_latest_server_data.py")
        return SimpleNamespace(upgrade_server_data=upgrade)
    monkeypatch.setattr(builds, "module", load)
    work = tmp_path / "work"; work.mkdir()
    destination = work / "inputs"
    if damage:
        with pytest.raises((AssertionError, builds.BuildError)):
            builds.fetch_public_inputs("android", destination, work, Guard())
    else:
        report = builds.fetch_public_inputs("android", destination, work, Guard())
        assert report["server_data"] == digest(prepared) and report["server_data_provenance"] == proof
        assert (destination / "BaseServerData.zip").read_bytes() == old
        assert (destination / "ServerData.zip").read_bytes() == prepared
        assert (destination / "bundledTranslations.zip").read_bytes() == translated
        assert json.loads((work / "server-data-preparation.json").read_text()) == proof
        assert seen == [("source-pointer",), ("fetch",), ("overlay",),
            ("prepare", "BaseServerData.zip", "ServerData.zip"), ("proof",), ("payload",)]
    assert donor.read_bytes() == donor_raw


@pytest.mark.parametrize("kind", ["android", "ios"])
def test_input_only_fetch_preserves_the_exact_immutable_benchmark_base(monkeypatch, tmp_path, kind):
    from types import SimpleNamespace
    import shutil
    original, translations = b"fixed original reference bytes", b"fixed translations"
    pin = lambda raw: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    donor = tmp_path / "donor.zip"
    with ZipFile(donor, "w") as archive:
        archive.writestr("base/ServerData.zip", original)
        archive.writestr("base/bundledTranslations.zip", translations)
    monkeypatch.setattr(builds, "DONORS", {kind: {**pin(donor.read_bytes()), "prefix": "base/"}})
    monkeypatch.setattr(builds, "BASE_SERVER_DATA", pin(original))
    monkeypatch.setattr(builds, "TRANSLATIONS", {kind: pin(translations)})
    def load(name, path):
        assert str(path).endswith("fetch_inputs.py"), "Input-only preparation must not invoke a payload upgrade"
        return SimpleNamespace(lfs_download=lambda record, target: shutil.copyfile(donor, target))
    monkeypatch.setattr(builds, "module", load)
    work = tmp_path / "work"; work.mkdir()
    report = builds.fetch_public_inputs(kind, work / "inputs", work, Guard(), prepare=False)
    assert report["server_data"] == pin(original) and "server_data_provenance" not in report
    assert (work / "inputs/ServerData.zip").read_bytes() == original
    assert not (work / "inputs/BaseServerData.zip").exists()


def test_explicit_base_reference_extraction_remains_full_hash_bound(monkeypatch, tmp_path):
    payload, _files = reference_payload(monkeypatch, tmp_path)
    approved = dict(builds.SERVER_DATA)
    monkeypatch.setattr(builds, "BASE_SERVER_DATA", approved)
    monkeypatch.setattr(builds, "SERVER_DATA", {"bytes": approved["bytes"]+1, "sha256": "a"*64})
    with pytest.raises(builds.BuildError, match="pin_differs"):
        builds.extract_qa_references(payload, tmp_path / "wrong-default", Guard())
    builds.extract_qa_references(payload, tmp_path / "base-references", Guard(), expected_pin=approved)
    assert (tmp_path / "base-references/protocol/idolypride-6.1.1.pb").is_file()
    payload.write_bytes(payload.read_bytes()+b"tampered")
    with pytest.raises(builds.BuildError, match="pin_differs"):
        builds.extract_qa_references(payload, tmp_path / "tampered", Guard(), expected_pin=approved)


@pytest.mark.parametrize("pin", [{"bytes": 1, "sha256": "a"*64}, {"bytes": True, "sha256": "a"*64},
                                  {"bytes": 191343014, "sha256": "a"*64, "extra": True}])
def test_qa_reference_pin_override_cannot_admit_an_arbitrary_archive(tmp_path, pin):
    path = tmp_path / "not-approved.zip"; path.write_bytes(b"x")
    with pytest.raises(builds.BuildError, match="purpose_pin_invalid"):
        builds.extract_qa_references(path, tmp_path / "references", Guard(), expected_pin=pin)


def test_latest_native_source_closure_keeps_historical_base_separate():
    assert builds.LOVE_SERVER_DATA is builds.LATEST_SERVER_DATA
    assert builds.SERVER_DATA == builds.LATEST_SERVER_DATA.output_pin()
    assert builds.SERVER_DATA != builds.BASE_SERVER_DATA
    assert builds.BASE_SERVER_DATA == {"bytes":191343014,
        "sha256":"37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"}
    required = set(builds.LATEST_SERVER_DATA.SOURCE_COMPONENTS) | {
        "tools/latest_server_data_pin.py", "data/latest-server-data-pin.json",
        "data/latest-server-overlay.zip", "src/idoly_local/public_payload_transaction.py",
        "src/idoly_local/latest_cohort_pins.py", "src/idoly_local/love_compatibility_pins.py"}
    assert required <= set(builds.COMMON_SOURCE_FILES)


def test_legacy_native_callers_pass_latest_proof_and_scope_lfs_credentials():
    workflow = (builds.ROOT/".github/workflows/build-server-apps.yml").read_text()
    prepare = workflow.split("- name: Prepare the frozen latest Mac public cohort",1)[1].split("- name:",1)[0]
    assert "GH_TOKEN:" in prepare and "verifier.fetch_overlay(blob)" in prepare
    assert "upgrade_server_data(None,payload,overlay_zip=blob,report_path=proof)" in prepare
    mac = workflow.split("- name: Build the frozen engine and exercise the actual relocated SwiftUI app",1)[1].split("- name:",1)[0]
    assert '--server-data "$RUNNER_TEMP/latest-macos-payload/ServerData.zip"' in mac
    assert '--server-data-upgrade-proof "$RUNNER_TEMP/latest-macos-payload/server-data-preparation.json"' in mac
    ios = workflow.split("- name: Compile real iOS frameworks, compose IPA and run fresh Simulator core probe",1)[1].split("- name:",1)[0]
    assert "GH_TOKEN:" in ios and "ios-unified/ci_build.py" in ios


def test_native_metadata_requires_all_resource_runtime_guards():
    assert {"src/idoly_local/resource_archive.py", "src/idoly_local/resource_library.py",
        "src/idoly_local/resource_translation.py", "src/idoly_local/resource_translation_runtime.py",
        "src/idoly_local/octo_runtime.py"} <= set(builds.COMMON_SOURCE_FILES)
