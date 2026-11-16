"""Offline object-only registration boundary tests; no network or credentials."""
import hashlib,importlib.util,io,json,sys
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("latest_registration_tests",ROOT/"tools/register_latest_server_data_lfs.py")
tool=importlib.util.module_from_spec(spec);sys.modules[spec.name]=tool;spec.loader.exec_module(tool)
TOKEN="repository-token-stays-in-github"
SECRET="https://github-cloud.s3.amazonaws.com/private?signature=never-print"
SOURCE="b"*40
def canon(x):return json.dumps(x,sort_keys=True,separators=(",",":")).encode()
def sha(x):return hashlib.sha256(x).hexdigest()
def zip_(path,files):
    with ZipFile(path,"w") as z:
        for name,raw in files.items():z.writestr(name,raw)
    return path.read_bytes()

@pytest.fixture
def env(tmp_path,monkeypatch):
    for k,v in {"GITHUB_ACTIONS":"true","GITHUB_REPOSITORY":tool.REPO,
        "GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_RUN_ID":"999",
        "IDOLY_LFS_OBJECT_WRITE":"reviewed-object-only","RUNNER_TEMP":str(tmp_path)}.items():monkeypatch.setenv(k,v)
    monkeypatch.setattr(tool.subprocess,"check_output",lambda *a,**k:SOURCE+"\n")
    body=b"frozen-public-source"*40
    output={"bytes":len(body),"sha256":sha(body),"payload_manifest_sha256":"a"*64,
        "member_inventory_sha256":"c"*64,"entries":700,"master_json_tables":64}
    octo={"schema":1,"status":"PASS","platforms":{
        key:{"models":[{"name":"model"}],"missing_model_roots":0} for key in ("android","ios")},
        "card_images":[{"id":"card","present":True}],"adv_identity":{"preserved":True},
        "cdn_asset_bytes_downloaded":False,"unity_playback_verified":False}
    compact={"schema":1,"proof_sha256":sha(canon(octo)+b"\n"),
        "platforms":{key:{name:value for name,value in item.items() if name!="models"}
                     for key,item in octo["platforms"].items()},
        "required_card_images":len(octo["card_images"]),"card_images_sha256":sha(canon(octo["card_images"])),
        "adv_identity_sha256":sha(canon(octo["adv_identity"])),"cdn_asset_bytes_downloaded":False,
        "unity_playback_verified":False}
    controls={"schema":1,"master_version":"6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11",
              "features":{"octo":{"receipt":compact}}}
    report={"output":output,"source_blob":{"path":"data/latest-server-overlay.zip","bytes":len(body),"sha256":sha(body)},
        "component_sources_sha256":"d"*64,"semantic_controls":controls}
    raw=canon(report)+b"\n"
    readback={"schema":1,"status":"PASS","operation":"latest-cohort-overlay-v1","report_sha256":sha(raw),
        "output":output,"source_blob":report["source_blob"],"component_sources_sha256":"d"*64}
    proof_raw=zip_(tmp_path/"proof.zip",{"latest-server-data.report.json":raw,
        "latest-server-data.readback.json":canon(readback)+b"\n","latest-semantic-controls.json":canon(controls)+b"\n",
        "latest-octo-proof.json":canon(octo)+b"\n"})
    source_raw=zip_(tmp_path/"source.zip",{"latest-server-overlay.zip":body})
    args=SimpleNamespace(prep_source=SOURCE,prep_run=42,source_artifact_id=100,proof_artifact_id=101,
        source_artifact_sha256=sha(source_raw),proof_artifact_sha256=sha(proof_raw),
        report_sha256=sha(raw),blob_sha256=sha(body),blob_bytes=len(body),work=tmp_path/"registration")
    verified=[]
    def verify(value,sources,out):
        assert value==report and sources=={"component":"e"*64} and out==output
        verified.append(True)
    fake_helper=SimpleNamespace(_proof=verify,_source_hashes=lambda:{"component":"e"*64},
        POLICY="latest-cohort-overlay-v1",OVERLAY_PATH="data/latest-server-overlay.zip")
    monkeypatch.setattr(tool,"helper",lambda:fake_helper)
    result=SimpleNamespace(args=args,body=body,report=report,proof_raw=proof_raw,source_raw=source_raw,
                           verified=verified,helper=fake_helper,tmp=tmp_path,octo=octo)
    class Fake:
        def __init__(self):self.calls=[];self.already=False;self.fail=False
        def api(self,path):
            self.calls.append(("api",path))
            if "/runs/" in path:return {"id":42,"head_sha":SOURCE,"status":"completed","conclusion":"success",
                "path":tool.WORKFLOW,"event":"workflow_dispatch","repository":{"full_name":tool.REPO}}
            role="source" if path.endswith("/100") else "proof"
            return {"id":getattr(args,role+"_artifact_id"),"name":"latest-server-data-"+role+"-"+SOURCE,
                "expired":False,"size_in_bytes":len(source_raw if role=="source" else proof_raw),
                "digest":"sha256:"+getattr(args,role+"_artifact_sha256"),
                "workflow_run":{"id":42,"head_sha":SOURCE}}
        def download_artifact(self,row,path):
            role="source" if row["artifact_id"]==100 else "proof"
            self.calls.append(("artifact",role));path.write_bytes(result.source_raw if role=="source" else result.proof_raw)
        def batch(self,operation,row):
            self.calls.append(("batch",operation));assert verified and row=={"bytes":len(body),"sha256":sha(body)}
            if operation=="download":return {"download":{"href":"https://lfs.github.com/object"}}
            return {} if self.already else {"upload":{"href":"https://lfs.github.com/upload"},"verify":{"href":"https://lfs.github.com/verify"}}
        def upload(self,action,path,row):
            self.calls.append(("upload",));assert path.read_bytes()==body and sha(path.read_bytes())==row["sha256"]
        def verify(self,action,row):self.calls.append(("verify",))
        def readback(self,action,row):
            self.calls.append(("readback",))
            if self.fail:raise tool.RegistrationError("registration_readback_differs")
            return row["bytes"]
    result.service=Fake()
    return result

@pytest.mark.parametrize("already",[False,True])
def test_exact_preparation_registers_only_one_object_and_requires_full_readback(env,already):
    env.service.already=already
    result=tool.register(env.args,service=env.service)
    assert result["status"]=="PASS_OBJECT_ONLY" and result["whole_LFS_readback_sha256_verified"]
    assert result["git_references_changed"] is False and result["release_created"] is False
    assert result["upload_performed"] is not already
    assert env.service.calls[-1]==("readback",) and len(env.verified)==1
    raw=(env.args.work/"registration-receipt.json").read_bytes()
    assert len(raw)<=65536 and TOKEN.encode() not in raw and b"https://" not in raw

@pytest.mark.parametrize("damage",["run","artifact","report","blob","components","authorization"])
def test_failures_stop_before_any_lfs_write(env,monkeypatch,damage):
    original=env.service.api
    if damage=="run":
        def bad(path):
            value=original(path)
            if "/runs/" in path:value["head_sha"]="0"*40
            return value
        env.service.api=bad
    elif damage=="artifact":
        def bad(path):
            value=original(path)
            if "/artifacts/" in path:value["digest"]="sha256:"+"0"*64
            return value
        env.service.api=bad
    elif damage=="report":env.args.report_sha256="0"*64
    elif damage=="blob":env.args.blob_sha256="0"*64
    elif damage=="components":
        env.helper._proof=lambda *a:(_ for _ in ()).throw(ValueError(SECRET))
    else:monkeypatch.delenv("IDOLY_LFS_OBJECT_WRITE")
    with pytest.raises(tool.RegistrationError):tool.register(env.args,service=env.service)
    assert not any(call[0]=="batch" for call in env.service.calls)
    assert not (env.args.work/"registration-receipt.json").exists()

def test_existing_object_still_needs_verified_download(env):
    env.service.fail=True
    with pytest.raises(tool.RegistrationError):tool.register(env.args,service=env.service)
    assert env.service.calls[-1]==("readback",)
    assert not (env.args.work/"registration-receipt.json").exists()

@pytest.mark.parametrize("target",["http://lfs.github.com/object","https://user:pass@lfs.github.com/object",
    "https://evil.amazonaws.com/object","https://github-cloud.s3.amazonaws.com.evil.invalid/object",
    "https://lfs.github.com/object#fragment"])
def test_lfs_storage_origin_is_fixed_and_redirect_free(target):
    with pytest.raises(tool.RegistrationError):tool.action_request({"href":target},TOKEN)

@pytest.mark.parametrize("headers",[{"Host":"evil"},{"Cookie":"value"},{"X-Auth":TOKEN},
    {"Authorization":"Basic "+__import__("base64").b64encode(("x-access-token:"+TOKEN).encode()).decode()},
    {"X-Auth":"line\nbreak"}])
def test_repository_credentials_and_unsafe_headers_cannot_leave_github_batch(headers):
    with pytest.raises(tool.RegistrationError):tool.action_request({"href":"https://lfs.github.com/object","header":headers},TOKEN)

class Response(io.BytesIO):
    status=200
    def __init__(self,raw):super().__init__(raw);self.headers={"Content-Length":str(len(raw))}

def test_only_fixed_github_batch_receives_repository_token():
    body=b"source";requests=[]
    def open_(request,timeout):
        requests.append(request)
        if request.full_url==tool.BATCH:
            return Response(canon({"objects":[{"oid":sha(body),"size":len(body),
                "actions":{"download":{"href":"https://lfs.github.com/object","header":{"X-Storage":"scope"}}}}]}))
        return Response(body)
    service=tool.Service(TOKEN,opener=SimpleNamespace(open=open_))
    row={"bytes":len(body),"sha256":sha(body)}
    action=service.batch("download",row)["download"]
    assert service.readback(action,row)==len(body)
    assert requests[0].get_header("Authorization").startswith("Basic ")
    assert "Authorization" not in requests[1].headers and requests[1].get_header("X-storage")=="scope"
    assert all(TOKEN not in str(r.headers) for r in requests[1:])

@pytest.mark.parametrize("damage",["truncated","overlong","different"])
def test_whole_readback_never_accepts_size_or_hash_drift(damage):
    body=b"right"
    wrong=body[:-1] if damage=="truncated" else body+b"x" if damage=="overlong" else b"wrong"
    with pytest.raises(tool.RegistrationError):tool.consume(Response(wrong),{"bytes":len(body),"sha256":sha(body)})

def test_errors_never_print_signed_storage_details(monkeypatch,tmp_path,capsys):
    monkeypatch.setattr(tool,"register",lambda *a,**k:(_ for _ in ()).throw(ValueError(SECRET)))
    argv=["--prep-source",SOURCE,"--prep-run","42","--source-artifact-id","100","--proof-artifact-id","101",
        "--source-artifact-sha256","a"*64,"--proof-artifact-sha256","b"*64,"--report-sha256","c"*64,
        "--blob-sha256","d"*64,"--blob-bytes","100","--work",str(tmp_path/"work")]
    assert tool.main(argv)==1
    output=capsys.readouterr()
    assert SECRET not in output.out+output.err and "registration_failed" in output.out

def test_manual_workflow_only_has_a_minimal_gated_object_write_job():
    source=(ROOT/"tools/register_latest_server_data_lfs.py").read_text()
    workflow=(ROOT/".github/workflows/register-latest-server-data-lfs.yml").read_text()
    assert "workflow_dispatch:" in workflow and "  push:" in workflow
    assert "paths: [.github/workflows/register-latest-server-data-lfs.yml]" in workflow
    source_job = workflow.split("  source-checks:", 1)[1].split("  verify:", 1)[0]
    assert "if: github.event_name == 'push'" in source_job
    assert "GH_TOKEN:" not in source_job and "IDOLY_LFS_OBJECT_WRITE:" not in source_job
    assert "contents: write" not in source_job
    assert workflow.count("if: github.event_name == 'workflow_dispatch' && inputs.confirm_object_only") == 2
    assert "contents: read" in workflow and workflow.count("contents: write")==1
    assert "inputs.confirm_object_only" in workflow and "persist-credentials: false" in workflow
    assert "registration-receipt.json" in workflow and "retention-days: 30" in workflow
    for forbidden in ("git push","gh release","git commit","refs/heads/"):
        assert forbidden not in source+workflow


@pytest.mark.parametrize("damage", ["hash", "compact-summary"])
def test_full_octo_proof_is_hash_bound_and_summary_is_derived_exactly(env, damage):
    with ZipFile(io.BytesIO(env.proof_raw)) as z:
        files = {item.filename:z.read(item) for item in z.infolist()}
    changed = json.loads(files["latest-octo-proof.json"])
    changed["platforms"]["ios"]["missing_model_roots"] = 1
    files["latest-octo-proof.json"] = canon(changed)+b"\n"
    if damage == "compact-summary":
        receipt = env.report["semantic_controls"]["features"]["octo"]["receipt"]
        receipt["proof_sha256"] = sha(files["latest-octo-proof.json"])
        files["latest-semantic-controls.json"] = canon(env.report["semantic_controls"])+b"\n"
        files["latest-server-data.report.json"] = canon(env.report)+b"\n"
        env.args.report_sha256 = sha(files["latest-server-data.report.json"])
        readback = json.loads(files["latest-server-data.readback.json"])
        readback["report_sha256"] = env.args.report_sha256
        files["latest-server-data.readback.json"] = canon(readback)+b"\n"
    path=env.tmp/"changed-proof.zip";zip_(path,files)
    with pytest.raises(tool.RegistrationError,match="readback_differs"):
        tool.proof_archive(path,env.args)
