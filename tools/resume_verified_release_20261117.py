#!/usr/bin/env python3
"""Resume only the SHA-frozen 2026.11.17.2 five-app build after optional-empty staging.

The build checkout remains 837f458; this separate control checkout does not
claim to have rebuilt or re-executed those applications. Read-only unless
--publish is explicitly given. No repository, tag, asset or pin arguments exist.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from urllib.request import Request
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

ROOT = Path(__file__).resolve().parents[1]
REPO = "tagundo/IdolyPride_client"
BUILD_SOURCE = "837f458a708fe0be4a01a38952d349efa54f3a02"
BUILD_RUN = 44015901340
VERSION = "2026.11.17.2"
PUBLICATION_COMMIT = "e763c674a43aa7b58f23f6b4f8e998e191061755"
PROOF_ARTIFACT = 14301175348
PROOF_BYTES = 3220
PROOF_SHA256 = "c38127290c54bb78af9754037f19421133c7a69f8702aa620fffeb211ba001da"
MIB = 1024 * 1024
CONTROL_SOURCES = ("tools/resume_verified_release_20261117.py",
    ".github/workflows/resume-verified-release-20261117.yml", "tests/test_resume_verified_release.py")
EXPECTED_BINDINGS = {'portable': {'source_commit': '837f458a708fe0be4a01a38952d349efa54f3a02', 'run_id': 44015901340, 'artifact_id': 14298454765, 'archive_bytes': 190816, 'archive_sha256': 'e5bde1b1bffd9cf77b9333dcf5f28f37fe6e421b0a62da188e8bd57ab06ee8de'}, 'performance': {'source_commit': '837f458a708fe0be4a01a38952d349efa54f3a02', 'run_id': 44015901340, 'artifact_id': 14299585430, 'archive_bytes': 20793, 'archive_sha256': '3d8e69f90ac6a369e491419d2dd9e81cb8f9bcab4b668c464cfa6118e86adb1f'}, 'android': {'source_commit': '837f458a708fe0be4a01a38952d349efa54f3a02', 'run_id': 44015901340, 'artifact_id': 14299628133, 'archive_bytes': 702949463, 'archive_sha256': 'f8b85e6622e96b2c1a6c818e75164c1eb908b93a886b2d2596bde642c0bcd83b'}, 'android-clients': {'source_commit': '837f458a708fe0be4a01a38952d349efa54f3a02', 'run_id': 44015901340, 'artifact_id': 14299115728, 'archive_bytes': 498427972, 'archive_sha256': '62bfa5e70b96b4ee4e143c82d7b9b2edb10df887d22be6cbc4ccef1c05ef358e'}, 'ios-unified': {'source_commit': '837f458a708fe0be4a01a38952d349efa54f3a02', 'run_id': 44015901340, 'artifact_id': 14300517067, 'archive_bytes': 563148983, 'archive_sha256': '1c1e16d44b5199e4e5f000a1bfedbc4c63ba891a1f41cf043510de6dca105b3f'}}
NATIVES = [{'name': 'IdolyPride-2026.11.17.2-Server-Android.apk', 'source_name': 'IdolyPride-Local-Server-Android.apk', 'bytes': 350605707, 'sha256': 'fc75a864d0b9306883439916c4a8df272ec7e8ff8d53dfa09e5ce594888b75b2'}, {'name': 'IdolyPride-2026.11.17.2-Unified-iOS.ipa', 'source_name': 'IdolyPride-6.1.1-Unified-iOS.ipa', 'bytes': 561043551, 'sha256': '0a4444a6a42003840e6fd2aced7d698ea7777c97cc15dc77593a840663e92490'}]
CLIENTS = [{'application_id': 'game.qualiarts.idolypride.local.diagnostics', 'bytes': 165128829, 'certificate_sha256': 'aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc', 'language': 'ko', 'name': 'IdolyPride-2026.11.17.2-Client-Android-arm64-ko.apk', 'sha256': 'f2b4555f2b56f5f388104a2e13a8cf0d50e3ffef3fca05d85281658d5a7366ae', 'version_code': 414, 'source_name': 'IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk'}, {'application_id': 'game.qualiarts.idolypride.local.diagnostics', 'bytes': 164276861, 'certificate_sha256': 'aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc', 'language': 'ja', 'name': 'IdolyPride-2026.11.17.2-Client-Android-arm64-ja.apk', 'sha256': '3cffdcdf99b48eb5819b8639b3a31bfa43f4ae5cc1c092bb5dbd984a6c080543', 'version_code': 414, 'source_name': 'IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk'}, {'application_id': 'game.qualiarts.idolypride.local.diagnostics', 'bytes': 164260477, 'certificate_sha256': 'aa4e9346ff9e542b263b70254df3e25b79211df16161208a3b509c4f113facfc', 'language': 'en', 'name': 'IdolyPride-2026.11.17.2-Client-Android-arm64-en.apk', 'sha256': '2bd373fbee1435c45000088fbf7996cbea8d577bf6015085e8c1101d82130baf', 'version_code': 414, 'source_name': 'IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk'}]
EXPECTED_PUBLICATION = {'schema': 1, 'source_commit': '837f458a708fe0be4a01a38952d349efa54f3a02', 'branch': 'downloads/optimized-v2026.11.17.2-source-837f458a708fe0be4a01a38952d349efa54f3a02', 'published': True, 'artifacts': [{'name': 'IdolyPride-2026.11.17.2-Server-Android.apk', 'sha256': 'fc75a864d0b9306883439916c4a8df272ec7e8ff8d53dfa09e5ce594888b75b2', 'bytes': 350605707, 'stage': 'verified', 'complete_download_verified': True}, {'name': 'IdolyPride-2026.11.17.2-Unified-iOS.ipa', 'sha256': '0a4444a6a42003840e6fd2aced7d698ea7777c97cc15dc77593a840663e92490', 'bytes': 561043551, 'stage': 'verified', 'complete_download_verified': True}], 'commit': 'e763c674a43aa7b58f23f6b4f8e998e191061755', 'tree': 'dcdd51b3c708eb5bf0e1acb41ccaedfec9397328'}


class ResumeError(ValueError):
    """Fixed public diagnostic codes only."""

def need(value, code):
    if not value: raise ResumeError(code)

def exact(value, expected):
    if type(value) is not type(expected):return False
    if type(value) is dict:return set(value)==set(expected) and all(exact(value[key],expected[key]) for key in expected)
    if type(value) is list:return len(value)==len(expected) and all(exact(a,b) for a,b in zip(value,expected))
    return value==expected

def digest(path):
    with Path(path).open("rb") as source:return hashlib.file_digest(source,"sha256").hexdigest()

def load_module(name, path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

def validate_context(control_source, control_run):
    need(type(control_source) is str and re.fullmatch(r"[0-9a-f]{40}",control_source) is not None
        and control_source!=BUILD_SOURCE and type(control_run) is int and control_run>0 and control_run!=BUILD_RUN,
        "resume_control_context_invalid")

def validate_proof_artifact(row):
    wanted={"id":PROOF_ARTIFACT,"name":"optimized-release-publication-proof-"+BUILD_SOURCE,
        "size_in_bytes":PROOF_BYTES,"digest":"sha256:"+PROOF_SHA256,"expired":False}
    need(type(row) is dict and all(exact(row.get(key),value) for key,value in wanted.items())
        and type(row.get("workflow_run")) is dict and exact(row["workflow_run"].get("id"),BUILD_RUN)
        and row["workflow_run"].get("head_sha")==BUILD_SOURCE,"resume_failed_proof_artifact_differs")

def validate_failure_evidence(proof, publication):
    need(type(proof) is dict and exact(proof.get("schema"),1)
        and proof.get("source_commit")==BUILD_SOURCE and exact(proof.get("run_id"),BUILD_RUN)
        and proof.get("status")=="FAIL" and proof.get("version")==VERSION and proof.get("release_version")==VERSION
        and proof.get("tag")=="v"+VERSION and proof.get("server_version")=="0.3.37"
        and exact(proof.get("build_number"),54) and proof.get("ipa_version")=="156.9117",
        "resume_failed_proof_identity_differs")
    need(proof.get("error_type")=="ReleaseError" and proof.get("error_code")=="release_staging_inventory_invalid",
        "resume_failure_not_optional_staging")
    need(all(proof.get(key) is True for key in ("all_qa_passed","whole_API_archive_digests_verified",
        "android_clients_packaging_QA_verified")),"resume_original_qa_not_verified")
    need(proof.get("release_published") is False and proof.get("release_assets_uploaded") is False
        and not any(key in proof for key in ("owned_release_id","release_asset_receipts","release")),
        "resume_original_release_may_exist")
    need(exact(proof.get("companions"),[]) and exact(proof.get("input_artifacts"),EXPECTED_BINDINGS)
        and exact(proof.get("artifacts"),NATIVES) and exact(proof.get("android_clients"),CLIENTS),
        "resume_exact_five_original_binaries_differ")
    names={row["source_name"]:row["name"] for row in [*NATIVES,*CLIENTS]}
    need(exact(proof.get("release_name_mapping"),names),"resume_original_name_mapping_differs")
    need(exact(publication,EXPECTED_PUBLICATION),"resume_native_lfs_receipts_differ")
    need(type(proof.get("performance")) is dict,"resume_original_metrics_missing")
    return proof

def validate_native_verification(value):
    need(type(value) is dict and exact(value.get("schema"),1) and value.get("source_commit")==BUILD_SOURCE
        and value.get("release_version")==VERSION and value.get("server_version")=="0.3.37"
        and value.get("ipa_version")=="156.9117","resume_native_verification_identity_differs")
    rows=value.get("artifacts")
    need(type(rows) is list and len(rows)==2 and all(type(row) is dict for row in rows)
        and all(exact({key:row.get(key) for key in wanted},wanted) for row,wanted in zip(rows,NATIVES)),
        "resume_native_verification_binaries_differ")
    validation=value.get("validation")
    need(type(validation) is dict and exact(validation.get("Actions_run"),BUILD_RUN)
        and validation.get("all_qa_passed") is True,"resume_native_verification_qa_differs")

def read_failed_archive(archive, publisher):
    with ZipFile(archive) as zipped:
        entries=zipped.infolist()
        need(len(entries)==2 and {row.filename for row in entries}=={"release-proof.json","publication.json"},
            "resume_failed_proof_member_set_differs")
        payload={}
        for row in entries:
            need(not row.is_dir() and not row.flag_bits&1 and stat.S_IFMT(row.external_attr>>16) in (0,stat.S_IFREG)
                and row.compress_type in (ZIP_STORED,ZIP_DEFLATED) and 0<row.file_size<=128*1024,
                "resume_failed_proof_member_invalid")
            raw=zipped.read(row);need(len(raw)==row.file_size,"resume_failed_proof_member_invalid")
            payload[row.filename]=publisher.decode(raw)
    validate_failure_evidence(payload["release-proof.json"],payload["publication.json"])
    return payload["release-proof.json"],payload["publication.json"]

def recheck_original_run(publisher, github):
    build=github.api("/actions/runs/"+str(BUILD_RUN))
    need(build.get("status")=="completed" and build.get("conclusion")=="failure","resume_original_run_not_completed_failure")
    bindings=publisher.validate_run(build,
        github.api("/actions/runs/"+str(BUILD_RUN)+"/jobs?filter=latest&per_page=100"),
        github.api("/actions/runs/"+str(BUILD_RUN)+"/artifacts?per_page=100"),BUILD_SOURCE,BUILD_RUN)
    need(exact(bindings,EXPECTED_BINDINGS),"resume_original_artifact_bindings_changed")
    validate_proof_artifact(github.api("/actions/artifacts/"+str(PROOF_ARTIFACT)))
    return bindings

def download_native(publisher, github, wanted, destination, guard):
    pointer=github.git_file(PUBLICATION_COMMIT,wanted["name"],256)
    expected=("version https://git-lfs.github.com/spec/v1\noid sha256:"+wanted["sha256"]
        +"\nsize "+str(wanted["bytes"])+"\n").encode()
    need(pointer==expected,"resume_immutable_lfs_pointer_differs")
    body=json.dumps({"operation":"download","transfers":["basic"],
        "objects":[{"oid":wanted["sha256"],"size":wanted["bytes"]}]}).encode()
    authorization="Basic "+base64.b64encode(("x-access-token:"+github.token).encode()).decode()
    request=Request("https://github.com/"+REPO+".git/info/lfs/objects/batch",data=body,method="POST",
        headers={"Authorization":authorization,"Accept":"application/vnd.git-lfs+json","Content-Type":"application/vnd.git-lfs+json"})
    with github.opener.open(request,timeout=60) as response:
        raw=response.read(MIB+1)
        need(response.status==200 and len(raw)<=MIB,"resume_lfs_batch_bound")
    objects=publisher.decode(raw).get("objects")
    need(type(objects) is list and len(objects)==1 and objects[0].get("oid")==wanted["sha256"]
        and exact(objects[0].get("size"),wanted["bytes"]) and not objects[0].get("error"),"resume_lfs_object_differs")
    action=objects[0].get("actions",{}).get("download",{});headers=action.get("header",{})
    need(type(headers) is dict and len(headers)<=16,"resume_lfs_headers_invalid")
    for key,value in headers.items():
        need(type(key) is str and re.fullmatch(r"[A-Za-z0-9-]{1,64}",key) is not None
            and key.lower() not in {"host","cookie","proxy-authorization"}
            and type(value) is str and len(value)<=4096 and github.token not in value
            and all(32<=ord(char)<127 for char in value),"resume_lfs_headers_invalid")
    target=action.get("href");need(type(target) is str and 0<len(target)<=16000,"resume_lfs_url_invalid")
    with github.binary_response(target,headers=headers) as response,destination.open("xb") as outgoing:
        publisher.verify_binary_stream(response,wanted,guard,outgoing)
    publisher.verified_file(destination.parent,{key:wanted[key] for key in ("name","bytes","sha256")})
    return {**wanted,"path":str(destination)}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--publish",action="store_true");args=parser.parse_args(argv)
    os.umask(0o077);state={"schema":1,"status":"FAIL","build_source_commit":BUILD_SOURCE,"build_run_id":BUILD_RUN,
        "release_version":VERSION,"native_publication_commit":PUBLICATION_COMMIT,"release_published":False,
        "release_assets_uploaded":False,"new_application_build_claimed":False,"new_device_or_gameplay_execution_claimed":False}
    publisher=delivery=github=guard=None;stage="entry";output_ready=False
    try:
        need(os.environ.get("GITHUB_ACTIONS")=="true" and os.environ.get("GITHUB_REPOSITORY")==REPO
            and sys.platform.startswith("linux") and __debug__,"resume_owned_github_runner_required")
        control_source=os.environ.get("GITHUB_SHA");raw_run=os.environ.get("GITHUB_RUN_ID","")
        need(raw_run.isdecimal(),"resume_control_context_invalid");control_run=int(raw_run);validate_context(control_source,control_run)
        build_root=(ROOT.parent/"build").resolve(strict=True)
        need(build_root!=ROOT.resolve() and not build_root.is_relative_to(ROOT.resolve())
            and not ROOT.resolve().is_relative_to(build_root),"resume_checkout_roots_overlap")
        for root,wanted in ((ROOT,control_source),(build_root,BUILD_SOURCE)):
            need(subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,timeout=10).decode().strip()==wanted,
                "resume_checkout_source_differs")
            need(subprocess.run(["git","diff","--quiet"],cwd=root,timeout=10).returncode==0,"resume_checkout_dirty")
        runner=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        for path in (args.work,args.output):
            need(path.is_absolute() and path.parent.resolve(strict=True)==runner and not path.exists()
                and not path.is_symlink(),"resume_fresh_owned_directory_required")
        need(args.work!=args.output,"resume_owned_directories_overlap")
        need(shutil.disk_usage(runner).free>=6*1024*MIB,"resume_entry_disk_floor")
        args.work.mkdir(mode=0o700);args.output.mkdir(mode=0o700);output_ready=True
        state.update(control_source_commit=control_source,control_run_id=control_run,
            control_source_sha256={name:digest(ROOT/name) for name in CONTROL_SOURCES})
        def save():
            raw=(json.dumps(state,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+"\n").encode()
            need(len(raw)<=MIB,"resume_report_bound")
            (args.output/"resume-proof.json").write_bytes(raw)
        save();stage="load_original_verifier"
        publisher=load_module("resume_frozen_837_publisher",build_root/"tools/publish_optimized_release.py")
        delivery=load_module("resume_frozen_837_delivery",build_root/"ios-unified/delivery.py")
        need(publisher.ROOT.resolve()==build_root and delivery.ROOT.resolve()==build_root,"resume_old_verifier_root_differs")
        publisher.configure_release(VERSION);need(publisher.COMPANIONS==(),"resume_frozen_companion_policy_differs")
        guard=delivery.Guard();github=publisher.GitHub(os.environ["GH_TOKEN"],delivery.OPENER)
        state["build_verifier_sha256"]={name:digest(build_root/name) for name in
            ("tools/publish_optimized_release.py","ios-unified/delivery.py")}
        stage="verify_original_gates";recheck_original_run(publisher,github);github.require_fresh()
        stage="fetch_failed_proof"
        proof_archive=args.work/"original-failure.zip"
        proof_binding={"artifact_id":PROOF_ARTIFACT,"archive_bytes":PROOF_BYTES,"archive_sha256":PROOF_SHA256}
        delivery.fetch_archive(proof_binding,github.token,proof_archive,guard)
        original,publication=read_failed_archive(proof_archive,publisher)
        state.update(failed_proof_artifact=proof_binding,original_qa_reused_from_exact_whole_SHA256_proof=True,
            all_qa_passed=True,original_input_artifacts=EXPECTED_BINDINGS)
        publisher.write_json(args.output/"original-release-proof.json",original)
        publisher.write_json(args.output/"original-publication.json",publication);save()
        stage="verify_native_metadata"
        verification_raw=github.git_file(PUBLICATION_COMMIT,"RELEASE-VERIFICATION.json",128*1024)
        validate_native_verification(publisher.decode(verification_raw))
        state["native_verification_sha256"]=hashlib.sha256(verification_raw).hexdigest()
        native_directory=args.work/"native";native_directory.mkdir(mode=0o700)
        stage="download_native_binaries"
        natives=[download_native(publisher,github,row,native_directory/row["name"],guard) for row in NATIVES]
        state["native_LFS_whole_SHA256_readbacks"]=[{**row,"complete_download_verified":True,
            "immutable_pointer_verified":True} for row in NATIVES];save()
        stage="download_android_clients"
        client_archive=args.work/"android-clients.zip"
        delivery.fetch_archive(EXPECTED_BINDINGS["android-clients"],github.token,client_archive,guard)
        client_directory=args.work/"android-clients"
        publisher.extract_generic(client_archive,client_directory,"android-clients",guard);client_archive.unlink()
        clients=publisher.validate_android_clients(client_directory,BUILD_SOURCE,BUILD_RUN)
        clients=publisher.stage_release_binaries(clients,args.work/"release-clients",guard)
        need(exact([{key:row[key] for key in CLIENTS[0]} for row in clients],CLIENTS),"resume_verified_clients_differ")
        binaries=natives+clients
        need(len(binaries)==5 and {row["name"] for row in binaries}==publisher.EXPECTED_RELEASE_ASSETS
            and {row["source_name"] for row in binaries}==publisher.INPUT_RELEASE_ASSETS,"resume_exact_five_asset_set_differs")
        state.update(status="READY_VERIFIED",artifacts=[{key:row[key] for key in ("name","source_name","bytes","sha256")} for row in binaries],
            clients_archive_whole_SHA256_verified=True,clients_original_packaging_QA_reverified=True,
            full_remote_download_SHA256_verified=True,resources=guard.report());save()
        body=publisher.release_body(BUILD_SOURCE,BUILD_RUN,publication,NATIVES,original["performance"],android_clients=CLIENTS,companions=[])
        body+="\n게시 단계 재개: 앱 빌드 소스 "+BUILD_SOURCE+" / Actions "+str(BUILD_RUN)+". 게시 제어 소스 "+control_source+" / Actions "+str(control_run)+"에서 같은 5개 파일을 다시 검증했습니다. 이 단계는 앱을 다시 빌드하거나 게임 검사를 새로 실행했다고 주장하지 않습니다.\n"
        (args.output/"RELEASE.md").write_text(body)
        if args.publish:
            stage="publish_verified_five";recheck_original_run(publisher,github)
            def save_assets(receipts):
                state["release_asset_receipts"]=[dict(row) for row in receipts]
                state["release_assets_uploaded"]=len(receipts)==5;save()
            released=github.publish(BUILD_SOURCE,body,binaries,guard,save_assets=save_assets,
                before_promote=lambda:recheck_original_run(publisher,github))
            state.update(status="PASS_PUBLISHED",release_published=True,release=released,
                full_release_asset_API_SHA256_verified=True,release_assets_uploaded=True,
                release_asset_receipts=github.asset_receipts,resources=guard.report());stage="write_published_receipt";save()
        print(json.dumps({"status":state["status"],"build_source_commit":BUILD_SOURCE,"build_run_id":BUILD_RUN,
            "control_source_commit":control_source,"control_run_id":control_run,"release_published":state["release_published"]}))
        return 0
    except BaseException as error:
        state.update(status="FAIL",failed_stage=stage,error_code="resume_failed")
        if isinstance(error,ResumeError):state["error_code"]=str(error)
        elif publisher is not None and delivery is not None:
            code=publisher.publication_failure_code(error,delivery)
            if code is not None:state["error_code"]=code
        if github is not None and github.owned_release_id is not None:
            try:
                restored=github.api("/releases/"+str(github.owned_release_id),method="PATCH",body={"draft":True})
                restored_ok=restored.get("id")==github.owned_release_id and restored.get("draft") is True
            except BaseException:restored_ok=False
            state.update(owned_release_id=github.owned_release_id,rollback_draft_restored=restored_ok,
                release_published=False if restored_ok else None)
        if guard is not None:state["resources"]=guard.report()
        if output_ready:
            try:
                raw=(json.dumps(state,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
                if len(raw)<=MIB:(args.output/"resume-proof.json").write_bytes(raw)
            except BaseException:pass
        print(json.dumps({"status":"FAIL","error_code":state["error_code"],"stage":stage}))
        return 1

if __name__=="__main__":raise SystemExit(main())
