"""Portable trust-boundary checks; no download, game, native build or publication."""
from copy import deepcopy
import hashlib
import json
import importlib.util
from pathlib import Path
import stat
from zipfile import ZipInfo, ZIP_STORED, ZIP_LZMA

import pytest

SPEC = importlib.util.spec_from_file_location("ios_unified_delivery", Path(__file__).resolve().parents[1]/"ios-unified/delivery.py")
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)
SOURCE, RUN, ARTIFACT, DIGEST = "a"*40, 123, 456, "b"*64


def metadata():
    return {"artifact":{"id":ARTIFACT,"name":"ios-unified-prototype-"+SOURCE,"expired":False,
        "workflow_run":{"id":RUN,"head_sha":SOURCE},"digest":"sha256:"+DIGEST,"size_in_bytes":128},
        "run":{"id":RUN,"head_sha":SOURCE,"event":"workflow_dispatch","repository":{"full_name":delivery.REPO}},
        "jobs":{"jobs":[{"name":"ios-unified","conclusion":"success"}]}}


def bind_api(monkeypatch, values):
    def fake(path, token):
        assert token == "test-token"
        if "/artifacts/" in path:return deepcopy(values["artifact"])
        if "/jobs?" in path:return deepcopy(values["jobs"])
        return deepcopy(values["run"])
    monkeypatch.setattr(delivery,"api",fake)


def test_exact_successful_build_artifact_metadata(monkeypatch):
    bind_api(monkeypatch,metadata())
    result = delivery.artifact_metadata(SOURCE,RUN,ARTIFACT,DIGEST,"test-token")
    assert result == {"source_commit":SOURCE,"run_id":RUN,"artifact_id":ARTIFACT,"archive_bytes":128,"archive_sha256":DIGEST}


@pytest.mark.parametrize("section,path,value",[
    ("run",("head_sha",),"c"*40),
    ("run",("event",),"pull_request"),
    ("run",("repository","full_name"),"another/repository"),
    ("artifact",("workflow_run","head_sha"),"c"*40),
    ("artifact",("workflow_run","id"),RUN+1),
    ("artifact",("id",),ARTIFACT+1),
    ("artifact",("name",),"unrelated-artifact"),
    ("artifact",("expired",),True),
    ("artifact",("digest",),None),
    ("artifact",("digest",),"sha256:"+"c"*64),
    ("artifact",("size_in_bytes",),delivery.MAX_ARCHIVE+1),
    ("artifact",("size_in_bytes",),True),
    ("jobs",("jobs",),[{"name":"ios-unified","conclusion":"failure"}]),
    ("jobs",("jobs",),[{"name":"ios-unified","conclusion":"success"}]*2),
    ("jobs",("jobs",),[]),
])
def test_artifact_provenance_mismatch_is_rejected(monkeypatch,section,path,value):
    values = metadata()
    node = values[section]
    for key in path[:-1]:node = node[key]
    node[path[-1]] = value
    bind_api(monkeypatch,values)
    with pytest.raises(delivery.DeliveryError):
        delivery.artifact_metadata(SOURCE,RUN,ARTIFACT,DIGEST,"test-token")


class Inventory:
    def __init__(self,items):self.items = items
    def infolist(self):return self.items


def entry(name,size=1):
    item = ZipInfo(name)
    item.file_size = size
    item.compress_type = ZIP_STORED
    item.external_attr = stat.S_IFREG << 16
    return item


def required_entries():
    names = (delivery.IPA,delivery.PACKAGE_REPORT,"SHA256SUMS","README.txt","simulator-smoke.json",
             "keyboard-lifecycle-native-test.json","local-http-native-test.json","octo-budget-native-test.json",
             "unity-host-native-test.json","probe-build.json","server-data-upgrade.json")
    return [entry(name) for name in names]


def test_valid_required_inventory_is_accepted():
    items = required_entries()
    assert set(delivery.selected_members(Inventory(items))) == {item.filename for item in items}


@pytest.mark.parametrize("name",["../escape.json","/absolute.json","dir/../../escape.json","dir\\escape.json","a/./b.json","truncated\0.json"])
def test_unsafe_zip_paths_are_rejected(name):
    with pytest.raises(delivery.DeliveryError):
        delivery.selected_members(Inventory(required_entries()+[entry(name)]))


@pytest.mark.parametrize("items",[
    [entry("duplicate.json"),entry("duplicate.json")],
    [entry("a/repeated.json"),entry("b/repeated.json")],
    [entry("large.json",delivery.MAX_SMALL+1)],
    [entry("f%d.json"%i,delivery.MAX_SMALL) for i in range(5)],
    [entry("unexpected.bin")],
])
def test_duplicate_oversize_and_unexpected_members_are_rejected(items):
    with pytest.raises(delivery.DeliveryError):
        delivery.selected_members(Inventory(required_entries()+items))


def test_oversize_ipa_is_rejected():
    items = required_entries()
    items[0].file_size = delivery.MAX_IPA+1
    with pytest.raises(delivery.DeliveryError):delivery.selected_members(Inventory(items))


@pytest.mark.parametrize("kind",["symlink","encrypted","compression"])
def test_unsafe_zip_member_attributes_are_rejected(kind):
    item = entry("bad.json")
    if kind == "symlink":item.external_attr = stat.S_IFLNK << 16
    elif kind == "encrypted":item.flag_bits = 1
    else:item.compress_type = ZIP_LZMA
    with pytest.raises(delivery.DeliveryError):delivery.selected_members(Inventory(required_entries()+[item]))


def test_missing_new_host_report_is_rejected():
    items = [item for item in required_entries() if item.filename != "unity-host-native-test.json"]
    with pytest.raises(delivery.DeliveryError):delivery.selected_members(Inventory(items))


def test_proof_inventory_cannot_contain_an_ipa():
    with pytest.raises(delivery.DeliveryError):delivery.selected_proof_members(Inventory([entry(delivery.IPA)]))


def test_proof_aggregate_size_is_bounded():
    items = [entry("p%d.json"%i,delivery.MAX_PROOF) for i in range(2)]
    with pytest.raises(delivery.DeliveryError):delivery.selected_proof_members(Inventory(items))


@pytest.mark.parametrize("bad_digest,bad_size",[(False,False),(True,False),(False,True)])
def test_archive_api_sha_is_required_before_extraction(monkeypatch,tmp_path,bad_digest,bad_size):
    import hashlib
    import io
    body = b"bounded artifact data"
    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Encoding":"identity"}
    class Guard:
        calls = 0
        def check(self):self.calls += 1
    def open_response(request,timeout):
        assert request.get_header("Authorization") is None
        assert timeout == 60
        return Response(body)
    monkeypatch.setattr(delivery.OPENER,"open",open_response)
    expected = "0"*64 if bad_digest else hashlib.sha256(body).hexdigest()
    metadata = {"archive_bytes":len(body)-(1 if bad_size else 0),"archive_sha256":expected}
    guard = Guard()
    destination = tmp_path/"archive.zip"
    if bad_digest or bad_size:
        with pytest.raises(delivery.DeliveryError):
            delivery.download_verified_url(metadata,"https://objects.githubusercontent.com/signed",destination,guard)
    else:
        delivery.download_verified_url(metadata,"https://objects.githubusercontent.com/signed",destination,guard)
        assert destination.read_bytes() == body and guard.calls >= 2


def test_unapproved_archive_host_is_rejected_before_network(monkeypatch,tmp_path):
    def forbidden(*args,**kwargs):raise AssertionError("network must not start")
    monkeypatch.setattr(delivery.OPENER,"open",forbidden)
    with pytest.raises(delivery.DeliveryError,match="unapproved_archive_origin"):
        delivery.download_verified_url({"archive_bytes":1,"archive_sha256":DIGEST},
            "https://untrusted.example/archive",tmp_path/"archive.zip",None)


@pytest.mark.parametrize("name",["manifest.json","nested/manifest.json","delivery-proof.json","publication.json","proof-fetch.json","Manifest.json"])
def test_artifact_cannot_overwrite_generated_proof_records(name):
    with pytest.raises(delivery.DeliveryError,match="reserved_proof_member"):
        delivery.selected_members(Inventory(required_entries()+[entry(name)]))


def test_proof_budget_reserves_generated_records_before_publication():
    delivery.check_proof_budget(delivery.MAX_PROOF-delivery.PROOF_GENERATED_RESERVE-17,17)
    with pytest.raises(delivery.DeliveryError,match="publication_proof_preflight_bound"):
        delivery.check_proof_budget(delivery.MAX_PROOF-delivery.PROOF_GENERATED_RESERVE-16,17)


@pytest.mark.parametrize("changed",[False,True])
def test_delivery_code_bytes_must_match_frozen_git_commit(monkeypatch,tmp_path,changed):
    import hashlib
    committed = b"reviewed delivery code"
    (tmp_path/"delivery.py").write_bytes(b"changed delivery code" if changed else committed)
    monkeypatch.setattr(delivery,"ROOT",tmp_path)
    monkeypatch.setattr(delivery,"DELIVERY_SOURCES",("delivery.py",))
    monkeypatch.setattr(delivery,"_delivery_source_paths",lambda:delivery.DELIVERY_SOURCES)
    def git(arguments,**kwargs):
        assert arguments[-1] == SOURCE+":delivery.py"
        return str(len(committed)).encode() if arguments[1] == "cat-file" else committed
    monkeypatch.setattr(delivery.subprocess,"check_output",git)
    if changed:
        with pytest.raises(delivery.DeliveryError):delivery.delivery_source_pins(SOURCE)
    else:
        assert delivery.delivery_source_pins(SOURCE) == {"delivery.py":hashlib.sha256(committed).hexdigest()}


def test_oversize_proof_stops_before_publish_or_ipa_retirement(monkeypatch,tmp_path):
    import hashlib
    import json
    monkeypatch.setenv("GITHUB_ACTIONS","true")
    monkeypatch.setenv("GITHUB_REPOSITORY",delivery.REPO)
    monkeypatch.setenv("GITHUB_SHA",SOURCE)
    monkeypatch.setenv("GITHUB_RUN_ID",str(RUN))
    monkeypatch.setenv("RUNNER_TEMP",str(tmp_path))
    monkeypatch.setenv("GH_TOKEN","test-token")
    work = tmp_path/"owned"
    monkeypatch.setattr(delivery.sys,"argv",["delivery.py","--source-commit",SOURCE,"--run-id",str(RUN),
        "--artifact-id",str(ARTIFACT),"--artifact-sha256",DIGEST,"--work",str(work),"--publish"])
    monkeypatch.setattr(delivery.subprocess,"check_output",lambda *args,**kwargs:SOURCE)
    monkeypatch.setattr(delivery,"delivery_source_pins",lambda source:{})
    class Guard:
        def check(self):pass
        def report(self):return {}
    monkeypatch.setattr(delivery,"Guard",Guard)
    monkeypatch.setattr(delivery,"artifact_metadata",lambda *args:{})
    monkeypatch.setattr(delivery,"fetch_archive",lambda metadata,token,path,guard:path.write_bytes(b"zip"))
    def extract(archive,members,metadata,guard):
        (members/delivery.IPA).write_bytes(b"ipa")
        with (members/"large.json").open("wb") as output:output.truncate(delivery.MAX_PROOF)
        return {}
    monkeypatch.setattr(delivery,"extract_archive",extract)
    def verify(members,proof,source,run,artifact,guard):
        ipa = members/delivery.IPA
        manifest = {"source_commit":source,"artifacts":[{"path":str(ipa),"name":ipa.name,"bytes":3,"sha256":hashlib.sha256(b"ipa").hexdigest()}]}
        (proof/"manifest.json").write_text(json.dumps(manifest))
        (proof/"README.md").write_text("reviewed")
        return manifest,delivery.file_identity(ipa.lstat())
    monkeypatch.setattr(delivery,"verify_members",verify)
    published = []
    monkeypatch.setattr(delivery,"publish",lambda *args:published.append(True))
    with pytest.raises(SystemExit,match="Delivery stopped"):
        delivery.main()
    assert published == [] and (work/"members"/delivery.IPA).read_bytes() == b"ipa"
    assert json.loads((work/"proof/delivery-proof.json").read_text())["error_code"] == "publication_proof_preflight_bound"


def test_missing_canary_build_report_is_rejected():
    items = [item for item in required_entries() if item.filename != "probe-build.json"]
    with pytest.raises(delivery.DeliveryError):delivery.selected_members(Inventory(items))


@pytest.mark.parametrize("changed",[False,True])
def test_generated_canary_digest_binds_every_language(monkeypatch,tmp_path,changed):
    import json
    digest = "d"*64
    report = {"source_sha256":{name:"e"*64 for name in
        ("IdolyUnityHost.h","IdolyUnityHost.m","UnityHostPolicy.h","UnityHostProfile.h","IdolyClientData.h","IdolyClientData.m")}}
    (tmp_path/"unity-host-native-test.json").write_text(json.dumps(report))
    descriptor = {"sha256":"c"*64}
    monkeypatch.setattr(delivery,"_packaged_server_data_pin",lambda:{"bytes":12,"sha256":"a"*64})
    monkeypatch.setattr(delivery,"_packaged_payload_pin_bytes",lambda:b"fixed-generated-payload-pin")
    (tmp_path/"probe-build.json").write_text(json.dumps({"generated_language_canaries_sha256":digest,
        "copied_input_sha256":{"LocalServer/client-languages.zip":descriptor["sha256"],
        "LocalServer/ServerData.zip":"a"*64,
        "LocalServer/payload-pin.json":hashlib.sha256(b"fixed-generated-payload-pin").hexdigest()}}))
    monkeypatch.setattr(delivery,"validate_probe_build_sources",lambda built:None)
    paths = ("Data/resources.assets","Data/Managed/Metadata/global-metadata.dat")
    language = {"languages":{code:{path:{"sha256":"e"*64,"bytes":17} for path in paths} for code in ("ko","en","ja")}}
    class Host:
        @staticmethod
        def validate_report(value,native_dir):assert value == report
    class Probe:
        @staticmethod
        def validate_language_matrix_report(value):assert len(value["reports"]) == 5
    monkeypatch.setattr(delivery,"load_module",lambda *args:Host)
    smoke = {"native_probe":{"server_status":{"unity_host":{"unity_window_bound":True,"sigpipe_ignored_before_server":True}},
             "unity_host_probe":{"canary_source_sha256":digest}},
             "language_matrix":{"reports":[{"unity_host":{"sigpipe_ignored_before_server":True},"unity_host_probe":{"canary_source_sha256":digest}} for _ in range(5)]}}
    for code,row in zip(("ko","en","ja","en","ko"),smoke["language_matrix"]["reports"]):row["language"] = code
    for host in [smoke["native_probe"]["unity_host_probe"],*(row["unity_host_probe"] for row in smoke["language_matrix"]["reports"])]:
        host["canaries"] = {path:{"expected_sha256":"e"*64,"actual_sha256":"e"*64,"expected_bytes":17,"actual_bytes":17} for path in paths}
    if changed:smoke["language_matrix"]["reports"][1]["unity_host_probe"]["canary_source_sha256"] = "f"*64
    if changed:
        with pytest.raises(delivery.DeliveryError,match="generated_canary_source_differs"):
            delivery.verify_language_proofs(smoke,tmp_path,report,Probe,language,descriptor)
    else:delivery.verify_language_proofs(smoke,tmp_path,report,Probe,language,descriptor)


def test_generated_json_bound_is_checked_before_loading(tmp_path):
    path = tmp_path/"record.json"
    path.write_bytes(b"{"+b" "*10000+b"}")
    with pytest.raises(delivery.DeliveryError,match="json_file_bound"):
        delivery.small_json(path,128)


@pytest.mark.parametrize("tamper",["none","digest","missing","extra"])
def test_probe_build_source_set_and_bytes_are_pinned(monkeypatch,tmp_path,tamper):
    import hashlib
    monkeypatch.setattr(delivery,"HERE",tmp_path)
    monkeypatch.setattr(delivery,"PROBE_SOURCES",("build_probe.py","probe/main.m"))
    (tmp_path/"probe").mkdir()
    pins = {}
    for name in delivery.PROBE_SOURCES:
        raw = name.encode()
        (tmp_path/name).write_bytes(raw)
        pins[name] = hashlib.sha256(raw).hexdigest()
    if tamper == "digest":pins["probe/main.m"] = "f"*64
    elif tamper == "missing":pins.pop("build_probe.py")
    elif tamper == "extra":pins["unreviewed.m"] = "f"*64
    if tamper == "none":delivery.validate_probe_build_sources({"source_sha256":pins})
    else:
        with pytest.raises(delivery.DeliveryError):delivery.validate_probe_build_sources({"source_sha256":pins})


@pytest.mark.parametrize("allowed",[False,True])
def test_fileservice_proof_handoff_is_explicit_and_never_sends_auth(monkeypatch,tmp_path,allowed):
    import hashlib
    import io
    body = b"API-SHA-bound small proof"
    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Encoding":"identity"}
    class Guard:
        def check(self):pass
    calls = []
    def open_response(request,timeout):
        calls.append(request.full_url)
        assert request.get_header("Authorization") is None
        assert set(name.lower() for name,_ in request.header_items()) <= {"accept-encoding","user-agent"}
        return Response(body)
    monkeypatch.setattr(delivery.OPENER,"open",open_response)
    metadata = {"archive_bytes":len(body),"archive_sha256":hashlib.sha256(body).hexdigest()}
    target = "https://sdmntprkoreacentral.oaiusercontent.com/files/file_test-123/raw?temporary=opaque"
    if allowed:
        delivery.download_verified_url(metadata,target,tmp_path/"proof.zip",Guard(),allow_file_reference=True)
        assert (tmp_path/"proof.zip").read_bytes() == body and len(calls) == 1
    else:
        with pytest.raises(delivery.DeliveryError,match="unapproved_archive_origin"):
            delivery.download_verified_url(metadata,target,tmp_path/"proof.zip",Guard())
        assert calls == []


@pytest.mark.parametrize("target",[
    "http://sdmntprkoreacentral.oaiusercontent.com/files/file_test/raw",
    "https://sdmntprkoreacentral.oaiusercontent.com/wrong/file_test/raw",
    "https://sdmntprkoreacentral.oaiusercontent.com/files/file_test/other",
    "https://user@sdmntprkoreacentral.oaiusercontent.com/files/file_test/raw",
    "https://sdmntprkoreacentral.oaiusercontent.com.evil.example/files/file_test/raw",
])
def test_file_reference_handoff_rejects_wrong_origin_path_or_auth(monkeypatch,tmp_path,target):
    def forbidden(*args,**kwargs):raise AssertionError("network must not start")
    monkeypatch.setattr(delivery.OPENER,"open",forbidden)
    with pytest.raises(delivery.DeliveryError,match="unapproved_archive_origin"):
        delivery.download_verified_url({"archive_bytes":1,"archive_sha256":DIGEST},target,
            tmp_path/"proof.zip",None,allow_file_reference=True)


def test_file_reference_mode_cannot_download_a_large_artifact(monkeypatch,tmp_path):
    def forbidden(*args,**kwargs):raise AssertionError("network must not start")
    monkeypatch.setattr(delivery.OPENER,"open",forbidden)
    with pytest.raises(delivery.DeliveryError,match="file_reference_proof_bound"):
        delivery.download_verified_url({"archive_bytes":delivery.MAX_PROOF+delivery.MIB+1,"archive_sha256":DIGEST},
            "https://sdmntprkoreacentral.oaiusercontent.com/files/file_test/raw",tmp_path/"proof.zip",None,
            allow_file_reference=True)


@pytest.mark.parametrize("ignored",[False,None,1,"true"])
def test_startup_sigpipe_policy_requires_actual_boolean_true(tmp_path,ignored):
    smoke = {"native_probe":{"server_status":{"unity_host":{"unity_window_bound":True,
        "sigpipe_ignored_before_server":ignored}}}}
    with pytest.raises(delivery.DeliveryError,match="sigpipe_not_ignored_before_server"):
        delivery.verify_language_proofs(smoke,tmp_path,None,None,None,None)


def test_delivery_requires_upgraded_server_data_receipt_and_static_exact_pin(monkeypatch,tmp_path):
    import json
    from types import SimpleNamespace
    proof={"schema":1,"recipe":"source-bound"};(tmp_path/"server-data-upgrade.json").write_text(json.dumps(proof))
    monkeypatch.setattr(delivery,"_packaged_server_data_pin",lambda:{"bytes":1,"sha256":"b"*64})
    seen=[]
    def verify(value):assert value==proof;seen.append(value);return value
    monkeypatch.setattr(delivery,"_packaged_server_data_verifier",lambda:SimpleNamespace(verify_upgrade_proof=verify))
    delivery.verify_server_data_provenance(tmp_path,{"server_data_provenance":proof})
    assert seen==[proof]
    with pytest.raises(delivery.DeliveryError,match="server_data_upgrade_proof_differs"):
        delivery.verify_server_data_provenance(tmp_path,{"server_data_provenance":{"schema":1,"recipe":"old-base"}})


def test_delivery_cannot_substitute_missing_payload_pin_with_old_digest(monkeypatch,tmp_path):
    import json
    from types import SimpleNamespace
    base={"bytes":191343014,"sha256":"37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"}
    (tmp_path/"runtime_inputs.json").write_text(json.dumps({"inputs":{"server_data":base},"packaged_server_data":delivery.PACKAGED_SERVER_DATA}))
    def missing():raise ValueError("latest_server_data_pin_missing")
    monkeypatch.setattr(delivery,"HERE",tmp_path)
    monkeypatch.setattr(delivery,"_packaged_server_data_verifier",lambda:SimpleNamespace(base_pin=lambda:base,output_pin=missing))
    with pytest.raises(delivery.DeliveryError,match="packaged_server_data_pin_unavailable"):
        delivery._packaged_server_data_pin()


def test_delivery_uses_latest_source_pointer_and_fixed_payload_pin_without_large_body(tmp_path,monkeypatch):
    from types import SimpleNamespace
    base={"bytes":191343014,"sha256":"37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223"}
    wanted={"bytes":300*delivery.MIB,"sha256":"b"*64}
    (tmp_path/"runtime_inputs.json").write_text(json.dumps({"inputs":{"server_data":base},"packaged_server_data":delivery.PACKAGED_SERVER_DATA}))
    calls=[]
    verifier=SimpleNamespace(base_pin=lambda:base,output_pin=lambda:wanted,
        verify_source_pointer=lambda:calls.append("pointer"))
    monkeypatch.setattr(delivery,"HERE",tmp_path)
    monkeypatch.setattr(delivery,"_packaged_server_data_verifier",lambda:verifier)
    assert delivery._packaged_server_data_pin()==wanted and calls==["pointer"]
    assert not (tmp_path/"latest-server-overlay.zip").exists()
    assert {"tools/latest_server_data_pin.py","tools/prepare_latest_server_data.py",
        "data/latest-server-data-pin.json","data/latest-server-overlay.zip",
        "src/idoly_local/master_build.py","src/idoly_local/media_master_build.py",
        "src/idoly_local/master_translation_build.py","src/idoly_local/master_sort_build.py"}<=set(delivery.DELIVERY_SOURCES)


@pytest.mark.parametrize("mutated",[False,True])
def test_delivery_checks_actual_embedded_generated_payload_pin_bytes_and_report_hash(tmp_path,monkeypatch,mutated):
    from types import SimpleNamespace
    from zipfile import ZipFile
    pin={"schema":1,"policy":"latest-cohort-overlay-v1","bytes":123,"sha256":"a"*64,
        "manifest_sha256":"b"*64,"master_version":"c"*64}
    monkeypatch.setattr(delivery,"_packaged_server_data_verifier",lambda:SimpleNamespace(payload_pin=lambda:pin))
    prefix="Payload/Game.app/";name=prefix+"LocalServer/payload-pin.json"
    expected=(json.dumps(pin,indent=2)+"\n").encode()
    actual=(json.dumps({**pin,"bytes":124},indent=2)+"\n").encode() if mutated else expected
    path=tmp_path/"tiny.ipa"
    with ZipFile(path,"w") as archive:archive.writestr(name,actual)
    report={"member_sha256":{name:hashlib.sha256(actual).hexdigest()}}
    with ZipFile(path) as archive:
        if mutated:
            with pytest.raises(delivery.DeliveryError,match="bundled_payload_pin_differs"):
                delivery.verify_bundled_payload_pin(archive,prefix,report)
        else:
            delivery.verify_bundled_payload_pin(archive,prefix,report)
            with pytest.raises(delivery.DeliveryError,match="bundled_payload_pin_differs"):
                delivery.verify_bundled_payload_pin(archive,prefix,{"member_sha256":{name:"f"*64}})


@pytest.mark.parametrize("kind",["missing","oversized","symlink"])
def test_delivery_rejects_missing_oversized_or_symlink_payload_identity(tmp_path,monkeypatch,kind):
    from zipfile import ZipFile,ZipInfo
    prefix="Payload/Game.app/";name=prefix+"LocalServer/payload-pin.json";path=tmp_path/"tiny.ipa"
    with ZipFile(path,"w") as archive:
        if kind=="oversized":archive.writestr(name,b"x"*4097)
        if kind=="symlink":
            entry=ZipInfo(name);entry.create_system=3;entry.external_attr=(0o120777)<<16
            archive.writestr(entry,b"/private/other.json")
    with ZipFile(path) as archive:
        with pytest.raises(delivery.DeliveryError,match="bundled_payload_pin_invalid"):
            delivery.verify_bundled_payload_pin(archive,prefix,{})


def test_delivery_source_inventory_includes_complete_finite_producer_closure(monkeypatch):
    from types import SimpleNamespace
    components=("src/idoly_local/deep_dependency.py","uv.lock")
    monkeypatch.setattr(delivery,"_packaged_server_data_verifier",lambda:SimpleNamespace(SOURCE_COMPONENTS=components))
    paths=delivery._delivery_source_paths()
    assert paths==tuple(sorted(set(delivery.DELIVERY_SOURCES)|set(components)))
    assert {"src/idoly_local/latest_cohort_pins.py","src/idoly_local/love_compatibility_pins.py",
        "src/idoly_local/public_cohort_support.py"}<=set(paths)


@pytest.mark.parametrize("components",[(),["uv.lock"],("../private",),("/private",),("src//bad.py",),
    ("src/./bad.py",),("src/../bad.py",),("src\\bad.py",),("bad\0name",),(42,)])
def test_delivery_component_inventory_cannot_introduce_arbitrary_paths(monkeypatch,components):
    from types import SimpleNamespace
    monkeypatch.setattr(delivery,"_packaged_server_data_verifier",lambda:SimpleNamespace(SOURCE_COMPONENTS=components))
    with pytest.raises(delivery.DeliveryError,match="delivery_source_components_invalid"):
        delivery._delivery_source_paths()


@pytest.fixture
def language_producer_tree(tmp_path, monkeypatch):
    pins = {}
    for name in delivery.LANGUAGE_PRODUCER_SOURCES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = ("reviewed language producer: " + name).encode()
        path.write_bytes(raw)
        pins[name] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(delivery, "ROOT", tmp_path)
    return tmp_path, {"source_commit": SOURCE, "source_component_sha256": pins}


def test_language_producer_report_binds_every_current_writer_and_profile(language_producer_tree):
    root, report = language_producer_tree
    assert delivery.validate_language_producer_report(report, SOURCE) is None
    assert set(report["source_component_sha256"]) <= set(delivery.DELIVERY_SOURCES)
    # Changing one actual writer invalidates an otherwise unchanged successful report.
    path = root / "src/idoly_local/static_ui_images.py"
    path.write_bytes(path.read_bytes() + b"\nchanged font layout")
    with pytest.raises(delivery.DeliveryError, match="language_producer_source_sha256_differs"):
        delivery.validate_language_producer_report(report, SOURCE)


@pytest.mark.parametrize("damage", ["missing-report", "wrong-commit", "missing-commit", "pins-list",
    "missing-writer", "extra-path", "uppercase-sha", "wrong-sha", "non-string-sha"])
def test_language_producer_cannot_relabel_omit_or_extend_its_source_closure(language_producer_tree, damage):
    _, report = language_producer_tree
    if damage == "missing-report": report = None
    elif damage == "wrong-commit": report["source_commit"] = "c" * 40
    elif damage == "missing-commit": del report["source_commit"]
    elif damage == "pins-list": report["source_component_sha256"] = []
    elif damage == "missing-writer": del report["source_component_sha256"]["tools/fetch_korean_ui_images.py"]
    elif damage == "extra-path": report["source_component_sha256"]["../private/credentials.json"] = "d" * 64
    else:
        report["source_component_sha256"]["src/idoly_local/static_ui_images.py"] = {
            "uppercase-sha": "D" * 64, "wrong-sha": "d" * 64, "non-string-sha": True}[damage]
    with pytest.raises(delivery.DeliveryError): delivery.validate_language_producer_report(report, SOURCE)


@pytest.mark.parametrize("damage", ["missing", "empty", "symlink", "writer-oversize", "catalog-oversize"])
def test_language_producer_source_files_stay_finite_and_regular(language_producer_tree, damage):
    root, report = language_producer_tree
    name = "client-presentation/translations/static-ui-v1.json" if damage == "catalog-oversize" else "tools/fetch_korean_ui_images.py"
    path = root / name
    if damage == "missing": path.unlink()
    elif damage == "empty": path.write_bytes(b"")
    elif damage == "symlink":
        original = root / "unowned.py"; path.rename(original); path.symlink_to(original)
    else: path.write_bytes(b"x" * (delivery.SOURCE_FILE_LIMITS.get(name, 256*1024) + 1))
    with pytest.raises(delivery.DeliveryError, match="language_producer_source_file_bound"):
        delivery.validate_language_producer_report(report, SOURCE)


def test_only_static_ui_catalog_gets_the_narrow_768kib_source_allowance(language_producer_tree):
    root, report = language_producer_tree
    name = "client-presentation/translations/static-ui-v1.json"
    path = root / name; path.write_bytes(b"x" * 566808)
    report["source_component_sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert delivery.validate_language_producer_report(report, SOURCE) is None
    assert delivery.SOURCE_FILE_LIMITS[name] == 768*1024
    assert delivery.SOURCE_FILE_LIMITS.get("src/idoly_local/static_ui_images.py", 256*1024) == 256*1024
    assert delivery.SOURCE_FILE_LIMITS.get("arbitrary.json", 256*1024) == 256*1024


def test_committed_language_producer_and_delivery_have_the_same_finite_closure():
    import ast
    tree = ast.parse((delivery.ROOT / "tools/build_ios_client_languages.py").read_text())
    builder = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_build_source_pins")
    assignment = next(node for node in builder.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "names" for target in node.targets))
    actual = ast.literal_eval(assignment.value)
    assert type(actual) is tuple and len(actual) == 11
    assert actual == delivery.LANGUAGE_PRODUCER_SOURCES
