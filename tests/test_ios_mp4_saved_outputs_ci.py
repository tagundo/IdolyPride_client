"""The Apple-only Save check must reject skips and incomplete source evidence."""
from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET

import pytest

from tools import verify_ios_mp4_saved_outputs as check


def junit(tmp_path, *, count=None, missing=None, outcome=None):
    root=ET.Element("testsuites");suite=ET.SubElement(root,"testsuite")
    names=[Path(name).stem for name in check.TESTS]
    if missing:names.remove(missing)
    for index in range(check.EXPECTED_TESTS if count is None else count):
        case=ET.SubElement(suite,"testcase",classname=names[index%len(names)],name="case_"+str(index))
        if outcome and index==0:ET.SubElement(case,outcome)
    path=tmp_path/"tests.xml";path.write_bytes(ET.tostring(root));return path


def test_all_required_real_apple_test_cases_must_have_no_skips(tmp_path):
    assert check.junit_summary(junit(tmp_path))=={"tests":49,"skipped":0,"errors":0,"failures":0}


@pytest.mark.parametrize("outcome",["skipped","error","failure"])
def test_a_single_required_apple_skip_or_failure_rejects_proof(tmp_path,outcome):
    with pytest.raises(ValueError,match="required_apple_tests_did_not_pass"):
        check.junit_summary(junit(tmp_path,outcome=outcome))


def test_junit_cannot_drop_a_test_file_or_test_case(tmp_path):
    for options in ({"count":48},{"missing":"test_ios_mp4_save_lifecycle"}):
        with pytest.raises(ValueError,match="required_test_cases_missing"):
            check.junit_summary(junit(tmp_path,**options))


def ui_receipt():
    names=("IdolyMP4UI.m","IdolyMP4UI.h","IdolySettings.m","IdolyMP4Library.m","IdolyMP4Library.h","MP4CompletedFilePolicy.h")
    hashes={"ios-unified/native/"+name:"a"*64 for name in names}
    commands=[]
    for sdk,target in (("iPhoneOS","arm64-apple-ios13.0"),("iPhoneSimulator","arm64-apple-ios13.0-simulator")):
        commands.append(["/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang",
            "-target",target,"-isysroot","/Applications/Xcode.app/Contents/Developer/Platforms/"+sdk+".platform/Developer/SDKs/"+sdk+".sdk",
            "-fsyntax-only",*[str(check.ROOT/"ios-unified/native"/name) for name in ("IdolyMP4UI.m","IdolySettings.m","IdolyMP4Library.m")]])
    return {"schema":1,"status":"PASS_APPLE_UIKIT_COMPILE_ONLY","commands":commands,
            "source_sha256":{name:"a"*64 for name in names},"actual_game_mv_verified":False,"actual_files_provider_verified":False},hashes


def test_uikit_receipt_requires_both_real_sdk_targets_and_exact_library_bytes():
    receipt,hashes=ui_receipt();check.validate_ui_receipt(receipt,hashes)
    receipt["source_sha256"]["IdolyMP4Library.m"]="b"*64
    with pytest.raises(ValueError,match="uikit_source_bytes_differ"):check.validate_ui_receipt(receipt,hashes)
    receipt,hashes=ui_receipt();receipt["commands"].pop()
    with pytest.raises(ValueError,match="uikit_targets_missing"):check.validate_ui_receipt(receipt,hashes)
    receipt,hashes=ui_receipt();receipt["commands"][1][receipt["commands"][1].index("-isysroot")+1]="/tmp/fake-sdk"
    with pytest.raises(ValueError,match="uikit_target_differs"):check.validate_ui_receipt(receipt,hashes)


def test_compile_evidence_cannot_claim_game_or_files_provider_execution():
    for key in ("actual_game_mv_verified","actual_files_provider_verified"):
        receipt,hashes=ui_receipt();receipt[key]=True
        with pytest.raises(ValueError,match="uikit_compile_report_invalid"):check.validate_ui_receipt(receipt,hashes)


def test_linux_cannot_silently_report_apple_checks_passed(tmp_path,monkeypatch):
    monkeypatch.setattr(check.platform,"system",lambda:"Linux")
    monkeypatch.setattr(sys,"argv",["verify", "--source-commit","a"*40,"--run-id","1","--output-directory",str(tmp_path)])
    assert check.main()==1
    report=json.loads((tmp_path/"verification.json").read_text())
    assert report["status"]=="FAIL" and report["error_code"]=="actual_apple_sdk_and_node_required"
    assert report["actual_game_mv_verified"] is False and report["actual_files_provider_verified"] is False
    assert report["product_package_built"] is False


def test_dedicated_workflow_uses_exact_source_and_never_packages_or_releases():
    workflow=(check.ROOT/".github/workflows/verify-ios-mp4-save.yml").read_text()
    assert "runs-on: macos-15" in workflow and "ref: ${{ github.sha }}" in workflow
    assert '--source-commit "$GITHUB_SHA" --run-id "$GITHUB_RUN_ID"' in workflow
    assert "verify_ios_mp4_saved_outputs.py" in workflow and "contents: read" in workflow
    assert "if: always()" in workflow and "if-no-files-found: error" in workflow
    for forbidden in ("continue-on-error", "ci_build.py", "build-mp4-preview.yml", "gh release", "build_android", "upload_draft"):
        assert forbidden not in workflow
    assert set(check.TESTS)=={"tests/test_ios_mp4_completed_library.py","tests/test_ios_mp4_save_lifecycle.py",
                              "tests/test_ios_mp4_queue_host.py","tests/test_ios_mp4_completed_ui.py"}
    assert all((check.ROOT/name).is_file() for name in check.SOURCES)
