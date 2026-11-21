#!/usr/bin/env python3
"""Register one reviewed public source object in this repository's Git LFS.

This tool never creates commits, branches, tags, releases or download pointers.
The manually supplied preparation identities are checked before the first LFS
write. Signed storage URLs, returned headers and raw exception text are private
transport details and never enter the receipt or terminal output.
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
import stat
import struct
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import ssl
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
REPO = "tagundo/IdolyPride_client"
API = "https://api.github.com/repos/"+REPO
BATCH = "https://github.com/"+REPO+".git/info/lfs/objects/batch"
WORKFLOW = ".github/workflows/prepare-latest-server-data.yml"
STAGE = "initial"
MAX_BLOB, MAX_META, MAX_RECEIPT = 512*1024*1024, 2*1024*1024, 64*1024
CHUNK = 128*1024
PROOF_FILES = frozenset(("latest-server-data.report.json","latest-server-data.readback.json",
                        "latest-semantic-controls.json","latest-octo-proof.json"))
ERROR_CODES = frozenset(("registration_inputs_invalid","registration_ci_required","registration_source_differs",
    "registration_work_required","registration_run_differs","registration_artifact_differs",
    "registration_transport_refused","registration_origin_refused","registration_headers_refused",
    "registration_response_bound","registration_archive_invalid","registration_report_differs",
    "registration_readback_differs","registration_blob_differs","registration_source_components_differ",
    "registration_lfs_object_differs","registration_upload_refused","registration_verify_refused",
    "registration_receipt_bound","registration_failed"))


class RegistrationError(ValueError):
    def __init__(self, code):
        self.code = code if code in ERROR_CODES else "registration_failed"
        super().__init__(self.code)


def need(value, code):
    if not value:
        raise RegistrationError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False).encode()


def sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}",value) is not None


def positive(value):
    return type(value) is int and 0 < value <= 2**63-1


def pairs(values):
    result = {}
    for key,value in values:
        need(key not in result,"registration_report_differs")
        result[key] = value
    return result


def decode(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
    except (UnicodeError,ValueError,RecursionError) as error:
        if isinstance(error,RegistrationError):
            raise
        raise RegistrationError("registration_report_differs") from None


def helper():
    spec = importlib.util.spec_from_file_location("registration_latest_pin",ROOT/"tools/latest_server_data_pin.py")
    module = importlib.util.module_from_spec(spec);sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def authorized():
    need(os.environ.get("GITHUB_ACTIONS")=="true"
         and os.environ.get("GITHUB_REPOSITORY")==REPO
         and os.environ.get("GITHUB_EVENT_NAME")=="workflow_dispatch"
         and re.fullmatch(r"[1-9][0-9]*",os.environ.get("GITHUB_RUN_ID","")) is not None
         and os.environ.get("IDOLY_LFS_OBJECT_WRITE")=="reviewed-object-only",
         "registration_ci_required")


def validate_inputs(args):
    need(type(args.prep_source) is str and re.fullmatch(r"[0-9a-f]{40}",args.prep_source)
         and all(positive(getattr(args,key)) for key in ("prep_run","source_artifact_id","proof_artifact_id"))
         and args.source_artifact_id != args.proof_artifact_id
         and all(sha(getattr(args,key)) for key in ("source_artifact_sha256","proof_artifact_sha256",
                                                   "report_sha256","blob_sha256"))
         and type(args.blob_bytes) is int and 0 < args.blob_bytes <= MAX_BLOB,"registration_inputs_invalid")


def validate_artifact(value, args, role):
    identity = getattr(args,role+"_artifact_id")
    digest = getattr(args,role+"_artifact_sha256")
    limit = MAX_BLOB+1024*1024 if role=="source" else MAX_META
    need(type(value) is dict and type(value.get("id")) is int and value["id"]==identity
         and value.get("name")=="latest-server-data-"+role+"-"+args.prep_source
         and value.get("expired") is False and type(value.get("size_in_bytes")) is int
         and 0 < value["size_in_bytes"] <= limit and value.get("digest")=="sha256:"+digest
         and value.get("workflow_run",{}).get("id")==args.prep_run
         and value.get("workflow_run",{}).get("head_sha")==args.prep_source,
         "registration_artifact_differs")
    return {"artifact_id":identity,"archive_bytes":value["size_in_bytes"],"archive_sha256":digest}


def storage_url(value, token, *, artifact=False):
    need(type(value) is str and 0 < len(value)<=16000 and token not in value,"registration_origin_refused")
    try:
        parsed = urlsplit(value);host = parsed.hostname or "";port = parsed.port
    except ValueError:
        raise RegistrationError("registration_origin_refused") from None
    allowed = host in {"github-cloud.githubusercontent.com","objects.githubusercontent.com",
        "release-assets.githubusercontent.com","media.githubusercontent.com","lfs.github.com"}
    allowed = allowed or re.fullmatch(r"github-cloud\.s3(?:\.[a-z0-9-]+)?\.amazonaws\.com",host) is not None
    if artifact:
        allowed = allowed or host.endswith(".blob.core.windows.net") or host.endswith(".actions.githubusercontent.com")
    need(parsed.scheme=="https" and port in (None,443) and not parsed.username and not parsed.password
         and not parsed.fragment and allowed,"registration_origin_refused")
    return value


def action_request(action, token, *, method="GET", data=None, extra=None):
    need(type(action) is dict and set(action) <= {"href","header","expires_at","expires_in"}
         and "href" in action,"registration_headers_refused")
    href = storage_url(action["href"],token)
    headers = action.get("header",{})
    need(type(headers) is dict and len(headers)<=16,"registration_headers_refused")
    basic = base64.b64encode(("x-access-token:"+token).encode()).decode()
    for key,value in headers.items():
        need(type(key) is str and re.fullmatch(r"[A-Za-z0-9-]{1,64}",key)
             and key.lower() not in {"host","cookie","proxy-authorization","content-length","transfer-encoding","connection"}
             and type(value) is str and len(value)<=4096 and token not in value and basic not in value
             and all(32<=ord(c)<127 for c in value),"registration_headers_refused")
    return Request(href,method=method,data=data,headers={**headers,**(extra or {})})


def consume(response, wanted, outgoing=None):
    need(response.status==200,"registration_transport_refused")
    length = response.headers.get("Content-Length")
    need(length is None or length.isdigit() and int(length)==wanted["bytes"],"registration_blob_differs")
    value,count = hashlib.sha256(),0
    while block:=response.read(CHUNK):
        count += len(block)
        need(count<=wanted["bytes"],"registration_blob_differs")
        value.update(block)
        if outgoing is not None: outgoing.write(block)
    need(count==wanted["bytes"] and value.hexdigest()==wanted["sha256"],"registration_blob_differs")
    return count


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


class Service:
    def __init__(self,token,*,opener=None):
        need(type(token) is str and token and "\n" not in token,"registration_ci_required")
        self.token = token
        self.opener = opener or build_opener(NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))

    def api(self,path):
        need(type(path) is str and re.fullmatch(r"/actions/(?:runs|artifacts)/[1-9][0-9]*",path),
             "registration_transport_refused")
        request = Request(API+path,headers={"Authorization":"Bearer "+self.token,
            "Accept":"application/vnd.github+json","User-Agent":"idoly-public-source-registration"})
        with self.opener.open(request,timeout=30) as response:
            need(response.status==200,"registration_transport_refused")
            raw=response.read(MAX_META+1)
        need(len(raw)<=MAX_META,"registration_response_bound")
        return decode(raw)

    def download_artifact(self,row,path):
        request = Request(API+"/actions/artifacts/"+str(row["artifact_id"])+"/zip",
            headers={"Authorization":"Bearer "+self.token,"Accept":"application/vnd.github+json",
                     "User-Agent":"idoly-public-source-registration"})
        try:
            response = self.opener.open(request,timeout=30)
        except HTTPError as error:
            try:
                need(error.code==302,"registration_transport_refused")
                target = storage_url(error.headers.get("Location",""),self.token,artifact=True)
            finally:
                error.close()
        else:
            response.close()
            raise RegistrationError("registration_transport_refused")
        with self.opener.open(Request(target,headers={"Accept-Encoding":"identity"}),timeout=180) as response:
            with path.open("xb") as outgoing:
                consume(response,{"bytes":row["archive_bytes"],"sha256":row["archive_sha256"]},outgoing)

    def batch(self,operation,row):
        need(operation in ("upload","download"),"registration_inputs_invalid")
        body=canonical({"operation":operation,"transfers":["basic"],
                        "objects":[{"oid":row["sha256"],"size":row["bytes"]}]})
        basic=base64.b64encode(("x-access-token:"+self.token).encode()).decode()
        request=Request(BATCH,data=body,method="POST",headers={"Authorization":"Basic "+basic,
            "Accept":"application/vnd.git-lfs+json","Content-Type":"application/vnd.git-lfs+json"})
        with self.opener.open(request,timeout=30) as response:
            need(response.status==200,"registration_transport_refused")
            raw=response.read(MAX_META+1)
        need(len(raw)<=MAX_META,"registration_response_bound")
        value=decode(raw)
        objects=value.get("objects") if type(value) is dict else None
        need(type(objects) is list and len(objects)==1 and type(objects[0]) is dict
             and not objects[0].get("error") and objects[0].get("oid")==row["sha256"]
             and type(objects[0].get("size")) is int and objects[0]["size"]==row["bytes"],
             "registration_lfs_object_differs")
        actions=objects[0].get("actions",{})
        need(type(actions) is dict and set(actions)<=({"upload","verify"} if operation=="upload" else {"download"}),
             "registration_lfs_object_differs")
        for action in actions.values():action_request(action,self.token)
        return actions

    def upload(self,action,path,row):
        with path.open("rb") as incoming:
            before=os.fstat(incoming.fileno())
            need(stat.S_ISREG(before.st_mode) and before.st_size==row["bytes"],"registration_blob_differs")
            value,count=hashlib.sha256(),0
            while block:=incoming.read(CHUNK):
                count+=len(block);need(count<=row["bytes"],"registration_blob_differs");value.update(block)
            need(count==row["bytes"] and value.hexdigest()==row["sha256"],"registration_blob_differs")
            incoming.seek(0)
            request=action_request(action,self.token,method="PUT",data=incoming,extra={
                "Content-Length":str(row["bytes"]),"Content-Type":"application/octet-stream"})
            with self.opener.open(request,timeout=180) as response:
                need(response.status in (200,201,202,204),"registration_upload_refused")
                need(len(response.read(MAX_RECEIPT+1))<=MAX_RECEIPT,"registration_response_bound")
            after=os.fstat(incoming.fileno())
            need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
                 ==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
                 "registration_blob_differs")

    def verify(self,action,row):
        request=action_request(action,self.token,method="POST",data=canonical({"oid":row["sha256"],"size":row["bytes"]}),
                               extra={"Content-Type":"application/vnd.git-lfs+json"})
        with self.opener.open(request,timeout=30) as response:
            need(response.status in (200,201,202,204),"registration_verify_refused")
            need(len(response.read(MAX_RECEIPT+1))<=MAX_RECEIPT,"registration_response_bound")

    def readback(self,action,row):
        request=action_request(action,self.token,extra={"Accept-Encoding":"identity"})
        with self.opener.open(request,timeout=180) as response:
            return consume(response,row)


def archive_directory(path, expected_count):
    with path.open("rb") as stream:
        size=os.fstat(stream.fileno()).st_size
        width=min(size,22+65535);stream.seek(size-width);tail=stream.read(width)
        at=tail.rfind(b"PK\x05\x06")
        need(at>=0 and at+22<=len(tail),"registration_archive_invalid")
        _,disk,start,local_count,count,directory_bytes,offset,comment=struct.unpack_from("<4s4H2LH",tail,at)
        need(disk==start==0 and count==local_count==expected_count
             and at+22+comment==len(tail) and expected_count*46<=directory_bytes<=64*1024
             and offset+directory_bytes==size-width+at,"registration_archive_invalid")


def proof_archive(path,args):
    archive_directory(path,len(PROOF_FILES))
    with ZipFile(path) as archive:
        infos=archive.infolist()
        need(len(infos)==len(PROOF_FILES) and {info.filename for info in infos}==PROOF_FILES
             and sum(info.file_size for info in infos)<=MAX_META,"registration_archive_invalid")
        for info in infos:
            need(info.filename==info.orig_filename and not info.is_dir() and not info.flag_bits&1
                 and stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG)
                 and info.compress_type in (ZIP_STORED,ZIP_DEFLATED)
                 and 0<info.file_size<=512*1024,"registration_archive_invalid")
        raw=archive.read("latest-server-data.report.json")
        need(hashlib.sha256(raw).hexdigest()==args.report_sha256,"registration_report_differs")
        report=decode(raw);readback=decode(archive.read("latest-server-data.readback.json"))
        semantic=decode(archive.read("latest-semantic-controls.json"))
        octo_raw=archive.read("latest-octo-proof.json");octo=decode(octo_raw)
    verifier=helper()
    try:
        verifier._proof(report,verifier._source_hashes(),report["output"])
    except Exception:
        raise RegistrationError("registration_source_components_differ") from None
    row={"bytes":args.blob_bytes,"sha256":args.blob_sha256}
    need({key:report["output"][key] for key in row}==row
         and report["source_blob"]=={"path":verifier.OVERLAY_PATH,**row},"registration_report_differs")
    output={key:report["output"][key] for key in
            ("bytes","sha256","payload_manifest_sha256","member_inventory_sha256","entries","master_json_tables")}
    expected={"schema":1,"status":"PASS","operation":verifier.POLICY,"report_sha256":args.report_sha256,
              "output":output,"source_blob":report["source_blob"],
              "component_sources_sha256":report["component_sources_sha256"]}
    need(canonical(readback)==canonical(expected),"registration_readback_differs")
    need(canonical(semantic)==canonical(report.get("semantic_controls")),"registration_readback_differs")
    need(type(octo) is dict and type(octo.get("schema")) is int and octo["schema"]==1
         and octo.get("status")=="PASS" and type(octo.get("platforms")) is dict
         and set(octo["platforms"])=={"android","ios"}
         and all(type(item) is dict and type(item.get("models")) is list for item in octo["platforms"].values())
         and type(octo.get("card_images")) is list and "adv_identity" in octo
         and octo.get("cdn_asset_bytes_downloaded") is False and octo.get("unity_playback_verified") is False
         and octo_raw==canonical(octo)+b"\n","registration_readback_differs")
    compact={"schema":1,"proof_sha256":hashlib.sha256(octo_raw).hexdigest(),
        "platforms":{key:{name:value for name,value in item.items() if name!="models"}
                     for key,item in octo["platforms"].items()},
        "required_card_images":len(octo["card_images"]),
        "card_images_sha256":hashlib.sha256(canonical(octo["card_images"])).hexdigest(),
        "adv_identity_sha256":hashlib.sha256(canonical(octo["adv_identity"])).hexdigest(),
        "cdn_asset_bytes_downloaded":False,"unity_playback_verified":False}
    need(canonical(compact)==canonical(report["semantic_controls"]["features"]["octo"]["receipt"]),
         "registration_readback_differs")
    return report


def source_archive(path,target,args):
    archive_directory(path,1)
    with ZipFile(path) as archive:
        infos=archive.infolist()
        need(len(infos)==1,"registration_archive_invalid")
        info=infos[0]
        need(info.filename==info.orig_filename=="latest-server-overlay.zip" and not info.is_dir()
             and not info.flag_bits&1 and stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG)
             and info.compress_type in (ZIP_STORED,ZIP_DEFLATED) and info.file_size==args.blob_bytes,
             "registration_archive_invalid")
        value,count=hashlib.sha256(),0
        with archive.open(info) as incoming,target.open("xb") as outgoing:
            while block:=incoming.read(CHUNK):
                count+=len(block);need(count<=args.blob_bytes,"registration_blob_differs")
                value.update(block);outgoing.write(block)
            outgoing.flush();os.fsync(outgoing.fileno())
        need(count==args.blob_bytes and value.hexdigest()==args.blob_sha256,"registration_blob_differs")
    return target


def register(args,*,service=None):
    global STAGE
    authorized();validate_inputs(args);STAGE="preparation_metadata"
    work=Path(args.work)
    need(not work.exists() and not work.is_symlink(),"registration_work_required")
    temporary=os.environ.get("RUNNER_TEMP","")
    need(temporary and Path(temporary).is_absolute()
         and work.parent.resolve(strict=True).is_relative_to(Path(temporary).resolve(strict=True)),
         "registration_work_required")
    need(subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True,timeout=10).strip()==args.prep_source,
         "registration_source_differs")
    work.mkdir(mode=0o700)
    service=service or Service(os.environ.get("GH_TOKEN",""))
    run=service.api("/actions/runs/"+str(args.prep_run))
    need(type(run) is dict and run.get("id")==args.prep_run and run.get("head_sha")==args.prep_source
         and run.get("status")=="completed" and run.get("conclusion")=="success"
         and run.get("path")==WORKFLOW and run.get("event") in ("push","workflow_dispatch")
         and run.get("repository",{}).get("full_name")==REPO,"registration_run_differs")
    bindings={}
    for role in ("proof","source"):
        value=service.api("/actions/artifacts/"+str(getattr(args,role+"_artifact_id")))
        bindings[role]=validate_artifact(value,args,role)
    STAGE="preparation_proof"
    proof_path=work/"proof.zip";service.download_artifact(bindings["proof"],proof_path)
    report=proof_archive(proof_path,args)
    STAGE="compiled_source"
    source_path=work/"source.zip";service.download_artifact(bindings["source"],source_path)
    blob=source_archive(source_path,work/"compiled-source.zip",args)
    row={"bytes":args.blob_bytes,"sha256":args.blob_sha256}
    STAGE="lfs_object_upload"
    actions=service.batch("upload",row)
    if "upload" in actions:service.upload(actions["upload"],blob,row)
    if "verify" in actions:service.verify(actions["verify"],row)
    STAGE="whole_lfs_readback"
    downloaded=service.batch("download",row)
    need(set(downloaded)=={"download"},"registration_lfs_object_differs")
    need(service.readback(downloaded["download"],row)==row["bytes"],"registration_readback_differs")
    result={"schema":1,"status":"PASS_OBJECT_ONLY","repository":REPO,
        "preparation":{"source_commit":args.prep_source,"run_id":args.prep_run,
            "report_sha256":args.report_sha256,"artifacts":bindings},
        "registration_run_id":int(os.environ["GITHUB_RUN_ID"]),"source_blob":report["source_blob"],
        "whole_LFS_readback_sha256_verified":True,"git_references_changed":False,
        "release_created":False,"download_branch_created":False,
        "upload_performed":"upload" in actions}
    need(len(canonical(result))<=MAX_RECEIPT,"registration_receipt_bound")
    (work/"registration-receipt.json").write_bytes(canonical(result)+b"\n")
    return result


def main(argv=None):
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prep-source",required=True)
    for name in ("prep-run","source-artifact-id","proof-artifact-id","blob-bytes"):
        parser.add_argument("--"+name,type=int,required=True)
    for name in ("source-artifact-sha256","proof-artifact-sha256","report-sha256","blob-sha256"):
        parser.add_argument("--"+name,required=True)
    parser.add_argument("--work",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        result=register(args)
    except Exception as error:
        code=error.code if isinstance(error,RegistrationError) else "registration_failed"
        # No exceptions, headers, signed URLs, file contents, or environment dumps.
        print(json.dumps({"status":"FAIL_OBJECT_ONLY","stage":STAGE,"error_code":code}))
        return 1
    print(json.dumps({"status":result["status"],"source_blob":result["source_blob"],
                      "whole_LFS_readback_sha256_verified":True}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
