"""Frozen resume boundary checks; no network, native fixture or publication."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

SPEC=importlib.util.spec_from_file_location("verified_release_resume",Path(__file__).resolve().parents[1]/"tools/resume_verified_release_20261117.py")
resume=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(resume)

def evidence():
    return {"schema":1,"status":"FAIL","source_commit":resume.BUILD_SOURCE,"run_id":resume.BUILD_RUN,
        "version":resume.VERSION,"release_version":resume.VERSION,"tag":"v"+resume.VERSION,
        "server_version":"0.3.37","build_number":54,"ipa_version":"156.9117",
        "error_type":"ReleaseError","error_code":"release_staging_inventory_invalid",
        "all_qa_passed":True,"whole_API_archive_digests_verified":True,
        "android_clients_packaging_QA_verified":True,"release_published":False,"release_assets_uploaded":False,
        "companions":[],"input_artifacts":deepcopy(resume.EXPECTED_BINDINGS),"artifacts":deepcopy(resume.NATIVES),
        "android_clients":deepcopy(resume.CLIENTS),"performance":{},
        "release_name_mapping":{row["source_name"]:row["name"] for row in [*resume.NATIVES,*resume.CLIENTS]}}

def metadata():
    return {"id":resume.PROOF_ARTIFACT,"name":"optimized-release-publication-proof-"+resume.BUILD_SOURCE,
        "size_in_bytes":resume.PROOF_BYTES,"digest":"sha256:"+resume.PROOF_SHA256,"expired":False,
        "workflow_run":{"id":resume.BUILD_RUN,"head_sha":resume.BUILD_SOURCE}}

def test_only_exact_failed_coherent_build_can_resume_without_rebuilding():
    value=evidence();assert resume.validate_failure_evidence(value,deepcopy(resume.EXPECTED_PUBLICATION)) is value
    resume.validate_proof_artifact(metadata());resume.validate_context("a"*40,123)
    assert len(resume.NATIVES)==2 and len(resume.CLIENTS)==3
    assert {row["language"] for row in resume.CLIENTS}=={"ko","ja","en"}
    assert not any("macOS" in row["name"] for row in [*resume.NATIVES,*resume.CLIENTS])

@pytest.mark.parametrize("damage",["source","run","boolean-run","date","different-error","false-qa","bool-qa",
    "false-archive","false-clients","companions","extra-native","missing-native","extra-client","client-sha",
    "native-sha","artifact-pin","owned-release","already-published","already-uploaded"])
def test_wrong_or_partial_publication_evidence_never_becomes_resumable(damage):
    value=evidence()
    if damage=="source":value["source_commit"]="a"*40
    elif damage=="run":value["run_id"]+=1
    elif damage=="boolean-run":value["run_id"]=True
    elif damage=="date":value["release_version"]="2026.11.17.3"
    elif damage=="different-error":value["error_code"]="binary_download_sha256_differs"
    elif damage=="false-qa":value["all_qa_passed"]=False
    elif damage=="bool-qa":value["all_qa_passed"]=1
    elif damage=="false-archive":value["whole_API_archive_digests_verified"]=False
    elif damage=="false-clients":value["android_clients_packaging_QA_verified"]=False
    elif damage=="companions":value["companions"]=[{}]
    elif damage=="extra-native":value["artifacts"].append(deepcopy(value["artifacts"][0]))
    elif damage=="missing-native":value["artifacts"].pop()
    elif damage=="extra-client":value["android_clients"].append(deepcopy(value["android_clients"][0]))
    elif damage=="client-sha":value["android_clients"][0]["sha256"]="0"*64
    elif damage=="native-sha":value["artifacts"][0]["sha256"]="0"*64
    elif damage=="artifact-pin":value["input_artifacts"]["android-clients"]["archive_sha256"]="0"*64
    elif damage=="owned-release":value["owned_release_id"]=1
    elif damage=="already-published":value["release_published"]=True
    elif damage=="already-uploaded":value["release_assets_uploaded"]=True
    with pytest.raises(resume.ResumeError):resume.validate_failure_evidence(value,deepcopy(resume.EXPECTED_PUBLICATION))

@pytest.mark.parametrize("damage",["commit","source","missing-receipt","receipt-false","receipt-bool","receipt-sha"])
def test_original_native_whole_download_receipts_are_mandatory(damage):
    publication=deepcopy(resume.EXPECTED_PUBLICATION)
    if damage=="commit":publication["commit"]="a"*40
    elif damage=="source":publication["source_commit"]="a"*40
    elif damage=="missing-receipt":publication["artifacts"].pop()
    elif damage=="receipt-false":publication["artifacts"][0]["complete_download_verified"]=False
    elif damage=="receipt-bool":publication["artifacts"][0]["complete_download_verified"]=1
    elif damage=="receipt-sha":publication["artifacts"][0]["sha256"]="0"*64
    with pytest.raises(resume.ResumeError):resume.validate_failure_evidence(evidence(),publication)

@pytest.mark.parametrize("key,value",[("id",1),("size_in_bytes",3221),("digest","sha256:"+"0"*64),
    ("expired",True),("expired",0),("name","other")])
def test_failed_proof_api_pin_cannot_be_substituted(key,value):
    row=metadata();row[key]=value
    with pytest.raises(resume.ResumeError):resume.validate_proof_artifact(row)

@pytest.mark.parametrize("source,run",[(resume.BUILD_SOURCE,123),("a"*40,resume.BUILD_RUN),("a"*40,True),("wrong",123)])
def test_control_identity_cannot_impersonate_the_original_build_context(source,run):
    with pytest.raises(resume.ResumeError):resume.validate_context(source,run)
