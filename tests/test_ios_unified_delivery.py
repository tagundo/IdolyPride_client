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
             "unity-host-native-test.json","probe-build.json","server-data-upgrade.json","startupTranslations.json")
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


# Exact bounded proof records from Actions 43953232317. Unchanged sprites are
# placeholders here; the 23 actual object hashes and every changed layout are real.
KOREAN_REFRESH_PROOF = json.loads(r'''{"common_files":44,"korean_resources_refreshed":true,"language_members":3,"proofs":{"korean_resources":{"all_other_objects_byte_identical":true,"declared_object_differences":[{"after_sha256":"ab3ce9b383db93c1dfc8c1a63cfac0ca3b5dff99084841342c67142865c1b4c5","before_sha256":"7ffd5267aa86522069f31d417ce044b535ebfbb7f2d6e494dd0efe5496ed21d6","changed":true,"class_id":213,"path_id":542},{"after_sha256":"c5047a7e349e021716a688d378fc50964bfbc6ae1d497dea29ce98a9420952f4","before_sha256":"16be9241077f25dc115e3abfaa80bbaf1a2417e4bfab004bb9fd63716821903e","changed":true,"class_id":213,"path_id":819},{"after_sha256":"64a96e12e334bae3749d9a7b1b8ef4af813dc2080d9ec150dd2df38fc5d7106f","before_sha256":"0daa3069aa20b281eb6fe7ba1271fff16b2075df8181990b4c5affa74525a9b6","changed":true,"class_id":213,"path_id":875},{"after_sha256":"31c16bcc7f437d8d227b79b4d71fc55f539b5e05437dcb28295948c103bbca1e","before_sha256":"80bbe5c96e857790e572193dfaed0734acb37a463b9b04f288bf7b76d7011ee7","changed":true,"class_id":213,"path_id":1007},{"after_sha256":"d8622057839d16f5cd0abef33d2597be1533fa652b56b0da538cd94b4458abbc","before_sha256":"fb054adfcb0364f8a0812ab063e91ffcfbe7abef795f3d5106569cca99ac1e28","changed":true,"class_id":213,"path_id":1029},{"after_sha256":"8bc768fc415c99a87e5adc844d44c8d6497cf64919d39863fef438903e7cdbff","before_sha256":"41eb393aab16d113480a46a76d4d63cf8f0842b0bcc8054fae1fda36f64991dd","changed":true,"class_id":213,"path_id":1076},{"after_sha256":"7144d7ccdf206d5d67541c77dfb3ee197a340c31bab38bcbed7ae9b195f1c4dc","before_sha256":"5f2612fddc07a34df72eba836329df1a71c1909d008b102caefa2f7dc1fe0c58","changed":true,"class_id":213,"path_id":1161},{"after_sha256":"08ae50fce5579c83084a1893f52aeafe8b7aa7bf8a081d66971ecc23d9427b74","before_sha256":"8cea3133a023bc03131384e57b2b08c08ce9b60bf9d6cb5c648ff31ce62300c9","changed":true,"class_id":213,"path_id":1342},{"after_sha256":"61f9e70fcc84c3ab26dde31b915c5975870f36afcec4a6c1937a70c6c76f8160","before_sha256":"6ad94e40cacb3535518ccfbeb9d554ae7222d33dbed050a0bfa6bcd5d760abfa","changed":true,"class_id":213,"path_id":1344},{"after_sha256":"ad88fb382f989318b3ccc919b84afdf81340467b597da8063f0fff460ed58905","before_sha256":"9682d8bf26b8f67b1ffc6110454c78de7c5679e68d1030c1327085826534ee19","changed":true,"class_id":213,"path_id":1576},{"after_sha256":"5cfb93c9c4b74dc7f5baa2d9ad617b5fff182ed13746da12e8f354f24a9bb50e","before_sha256":"08479eb31ff6e4c083ec658646706dd6fe2ca15ca9f33fd8676ca213f668d50f","changed":true,"class_id":224,"path_id":231861},{"after_sha256":"805a243bd7de534379ab050fb640acdf19ef40f5962b1df6e3aabca1f70a4dfe","before_sha256":"27181f442ff15fce8493d10564b115e75bb16e0afc2dbdc14748c53128ffe4c5","changed":true,"class_id":224,"path_id":251370},{"after_sha256":"de3190d9440761254cfc18d344b2382d442f2bad53abd2d76b814a3d9a7035b1","before_sha256":"405a65bd45c8fc6b9def4cc5bd50d7950d5b1f63d93b860b363d09b6f0ce7c9f","changed":true,"class_id":224,"path_id":253735},{"after_sha256":"7bd65663257fe23eaad847fc3e80078701516151151eb33583578cd723965c8c","before_sha256":"e28531bba225b519aa09d16dbab2547b4fd8f94016d3f08cdf5604e89b9e47f7","changed":true,"class_id":28,"path_id":418897},{"after_sha256":"a811fcfc5ecb666df17991549f1c1b439d260b734ff82ba2887f3ae7f1858f0a","before_sha256":"3d2a0aa78443049f328c1cb41a736ec7285cc1ee294010738258cf8769201066","changed":true,"class_id":28,"path_id":418898},{"after_sha256":"e73171bc77ac8e1e72aac247ce94d4d3d7532e8b34a855d713f97641fda71ed5","before_sha256":"a769993e4acfd82f3ecd42fd7269b1f5984386186b552a38b9b0811a36c20c09","changed":true,"class_id":28,"path_id":418899},{"after_sha256":"7135392bdaf21c294e55ebb2cf72b60d882bf23eb2cece04456464ea7dca5426","before_sha256":"d62d90c381bc4532ba0c44ff898cb398fb2a229f381e8dead1a2c874305e1403","changed":true,"class_id":28,"path_id":418900},{"after_sha256":"2a14a8a0214e635266fffc8c4dff9adfff86fc0d0b296901584565a04172d7e6","before_sha256":"a2529b03306de5e8b89be29d9e1dd1e04b9b26d2c553b800d0e010ccd20b4a7b","changed":true,"class_id":28,"path_id":418901},{"after_sha256":"08dc7285b6fde9d65eb56de43922a099608cfa909ababcc061978e57f43942c2","before_sha256":"395351cf2a4da7b388dad6418d845589732ad605eeb89738f075a44916cd3711","changed":true,"class_id":28,"path_id":418902},{"after_sha256":"42c4181dca2c86c075aff98a59a6c3be13776a2f320f4c32a6160d46ae0fad72","before_sha256":"5af53466ee72eab64a3dae13476844828f1f9c6e4a642249cc6b70a87e8b764e","changed":true,"class_id":28,"path_id":418903},{"after_sha256":"bab356fe0dd58e661f1fdff01ad06fe051b2114a6b7b3a60fe184728be6ef4fb","before_sha256":"5b030f23a30d6a9ad546d66c78d0cf1e1b6d826c401918cad6198396f09c88a2","changed":true,"class_id":28,"path_id":418904},{"after_sha256":"57114eeecce57925ba2c603bfa4a17b9e89fd9a376698837e81759007b32d591","before_sha256":"3229c84dd0494e435a50b143edb58255a018391f65e05174271f01d8e090c8a8","changed":true,"class_id":28,"path_id":418906},{"after_sha256":"8dbbd4e8965bfc9b9876c79f36f33cd61c4341a14633fd632e74e6eb12546c34","before_sha256":"f9ba49ce4b1a0811306b78f72171f26ab9714d5e63dfc10ce03bc6b497873a1f","changed":true,"class_id":28,"path_id":418911}],"original_stock_rebuilt":true,"output":{"bytes":80641216,"sha256":"9b3f5bb680670f91d6c3e41c5968acf49d8b9484431d5dc4d9837c786f982020"},"static_images":{"atlas_pixels_modified":false,"fixed_text_layout_policy":"original-rect-love-text-v1","fixed_text_sprites":10,"language":"ko","layout_policy":"preserved-v1-layout, Localify PNG rectangle, or fixed Love text aspect","logo_layout":{"all_other_object_bytes_identical":true,"content_size":[94.5,24.0],"full_translated_glyphs_preserved":true,"members":[],"original_frame":[96.0,32.0],"platform":"ios","policy":"love-logo-whole-label-uniform-v1","runtime_gameplay_tested":false,"transforms":[{"class_id":224,"full_png_size":[31,32],"input_sha256":"405a65bd45c8fc6b9def4cc5bd50d7950d5b1f63d93b860b363d09b6f0ce7c9f","name":"love_label_mo","object_bytes":108,"only_position_and_size_changed":true,"original_position":[-32.0,0.0],"original_size":[32.0,32.0],"output_sha256":"de3190d9440761254cfc18d344b2382d442f2bad53abd2d76b814a3d9a7035b1","path_id":253735,"position":[-35.625,0.0],"size":[23.25,24.0],"uniform_scale":0.75},{"class_id":224,"full_png_size":[32,32],"input_sha256":"08479eb31ff6e4c083ec658646706dd6fe2ca15ca9f33fd8676ca213f668d50f","name":"love_label_shi","object_bytes":108,"only_position_and_size_changed":true,"original_position":[0.0,0.0],"original_size":[32.0,32.0],"output_sha256":"5cfb93c9c4b74dc7f5baa2d9ad617b5fff182ed13746da12e8f354f24a9bb50e","path_id":231861,"position":[-12.0,0.0],"size":[24.0,24.0],"uniform_scale":0.75},{"class_id":224,"full_png_size":[63,32],"input_sha256":"27181f442ff15fce8493d10564b115e75bb16e0afc2dbdc14748c53128ffe4c5","name":"love_label_koi","object_bytes":108,"only_position_and_size_changed":true,"original_position":[32.0,0.0],"original_size":[32.0,32.0],"output_sha256":"805a243bd7de534379ab050fb640acdf19ef40f5962b1df6e3aabca1f70a4dfe","path_id":251370,"position":[23.625,0.0],"size":[47.25,24.0],"uniform_scale":0.75}],"uniform_scale":0.75},"lossy_recompression":false,"original_layout_preserved":false,"original_pivots_borders_pixels_per_unit_preserved":true,"original_sprite_IDs_preserved":true,"platform":"ios","policy":"korean-static-sprites-v2","private_sprite_render_data_keys":true,"runtime_image_hooks":false,"schema":2,"sprites":[{"PNG_resampled":false,"content_size":[250,40],"input_sha256":"d989d01c45ea559db49c94d0bacec8937b9c31985d979bcc7bbb044bad76a598","layout_policy":"original-rect-love-text-v1","layout_size":[280,40],"name":"love_btn_achievement","original_layout_size":[280.0,40.0],"output_bytes":1552,"output_sha256":"61f9e70fcc84c3ab26dde31b915c5975870f36afcec4a6c1937a70c6c76f8160","png_sha256":"1c225e517ab7c7ccb41793ef5bea65201a4890b014ebff408c0007119189c6fe","png_size":[250,40],"private_texture_path_id":418897,"readback_pixel_exact":true,"sprite_path_id":1344,"texture_bytes":44952,"texture_sha256":"7bd65663257fe23eaad847fc3e80078701516151151eb33583578cd723965c8c","transparent_padding_offset":[15,0]},{"PNG_resampled":false,"content_size":[147,40],"input_sha256":"90afc5a10e79f544d23a88572c64076e331337a6b1aad462bacbb239dfbdc467","layout_policy":"original-rect-love-text-v1","layout_size":[159,40],"name":"love_btn_fin","original_layout_size":[159.0,40.0],"output_bytes":896,"output_sha256":"08ae50fce5579c83084a1893f52aeafe8b7aa7bf8a081d66971ecc23d9427b74","png_sha256":"e88f419e01512c3ddb21a823938b78e29d69400e142d4b264cfcab219acef526","png_size":[147,40],"private_texture_path_id":418898,"readback_pixel_exact":true,"sprite_path_id":1342,"texture_bytes":25584,"texture_sha256":"a811fcfc5ecb666df17991549f1c1b439d260b734ff82ba2887f3ae7f1858f0a","transparent_padding_offset":[6,0]},{"PNG_resampled":true,"content_size":[72,27],"input_sha256":"3c8b2c8d64aa551f89787e7b0fd3f5c35ef11978a8414a36be7548190230fa33","layout_policy":"original-rect-love-text-v1","layout_size":[72,28],"name":"love_btn_max","original_layout_size":[72.0,28.0],"output_bytes":568,"output_sha256":"7144d7ccdf206d5d67541c77dfb3ee197a340c31bab38bcbed7ae9b195f1c4dc","png_sha256":"260d3c1a901c253c06058e0a39fc0cb98fe03c3041b1c31ca7a250874687da13","png_size":[74,28],"private_texture_path_id":418899,"readback_pixel_exact":true,"sprite_path_id":1161,"texture_bytes":8208,"texture_sha256":"e73171bc77ac8e1e72aac247ce94d4d3d7532e8b34a855d713f97641fda71ed5","transparent_padding_offset":[0,0]},{"PNG_resampled":false,"content_size":[78,37],"input_sha256":"e7cbf50d55f6e611f3a4122bacf1a653c911462ce2eeae00615db4ecaa622ec4","layout_policy":"original-rect-love-text-v1","layout_size":[80,40],"name":"love_btn_mission","original_layout_size":[80.0,40.0],"output_bytes":616,"output_sha256":"d8622057839d16f5cd0abef33d2597be1533fa652b56b0da538cd94b4458abbc","png_sha256":"397c9b6ca09ac4d5a2c8252ada8106cdbc4d687472f1614d32f0bddf24e30d67","png_size":[78,37],"private_texture_path_id":418900,"readback_pixel_exact":true,"sprite_path_id":1029,"texture_bytes":12948,"texture_sha256":"7135392bdaf21c294e55ebb2cf72b60d882bf23eb2cece04456464ea7dca5426","transparent_padding_offset":[1,1]},{"PNG_resampled":false,"content_size":[96,48],"input_sha256":"30c5b587c2fb5edb083e5b5d2f517b4bedaab75cfb22c6616861dcb9ce36a6f3","layout_policy":"original-rect-love-text-v1","layout_size":[240,48],"name":"love_btn_playing","original_layout_size":[240.0,48.0],"output_bytes":1180,"output_sha256":"c5047a7e349e021716a688d378fc50964bfbc6ae1d497dea29ce98a9420952f4","png_sha256":"59ec50bd4243fbde660b06851fe1be8716ca72cac36417a0937cadcd7bdaa69a","png_size":[96,48],"private_texture_path_id":418901,"readback_pixel_exact":true,"sprite_path_id":819,"texture_bytes":46228,"texture_sha256":"2a14a8a0214e635266fffc8c4dff9adfff86fc0d0b296901584565a04172d7e6","transparent_padding_offset":[72,0]},{"PNG_resampled":false,"content_size":[72,40],"input_sha256":"7705b5606c35bc9fe429976b85d90f04506d2cca252549696b86dedcfd97a413","layout_policy":"original-rect-love-text-v1","layout_size":[194,40],"name":"love_btn_present","original_layout_size":[194.0,40.0],"output_bytes":928,"output_sha256":"31c16bcc7f437d8d227b79b4d71fc55f539b5e05437dcb28295948c103bbca1e","png_sha256":"e17fe8648b4ecb9882f3f4cd33fd908aafc91a13a3218db44d0daef3d6242140","png_size":[72,40],"private_texture_path_id":418902,"readback_pixel_exact":true,"sprite_path_id":1007,"texture_bytes":31188,"texture_sha256":"08dc7285b6fde9d65eb56de43922a099608cfa909ababcc061978e57f43942c2","transparent_padding_offset":[61,0]},{"PNG_resampled":false,"content_size":[75,40],"input_sha256":"94877bb1b0429fe795fb79297ea532c20e736b755d4c1c10dd6968094f08b74b","layout_policy":"original-rect-love-text-v1","layout_size":[80,40],"name":"love_btn_setting","original_layout_size":[80.0,40.0],"output_bytes":644,"output_sha256":"8bc768fc415c99a87e5adc844d44c8d6497cf64919d39863fef438903e7cdbff","png_sha256":"5a86b66900da43d8674e05c9388a9dca659db299c6fff240fcdf27fd63f5de68","png_size":[75,40],"private_texture_path_id":418903,"readback_pixel_exact":true,"sprite_path_id":1076,"texture_bytes":12948,"texture_sha256":"42c4181dca2c86c075aff98a59a6c3be13776a2f320f4c32a6160d46ae0fad72","transparent_padding_offset":[2,0]},{"PNG_resampled":false,"content_size":[185,37],"input_sha256":"b354e4bf0bbf5e1957dfce6d19c3353e459f95504a4312ee483a24879e9e8624","layout_policy":"original-rect-love-text-v1","layout_size":[192,40],"name":"love_btn_status","original_layout_size":[192.0,40.0],"output_bytes":940,"output_sha256":"64a96e12e334bae3749d9a7b1b8ef4af813dc2080d9ec150dd2df38fc5d7106f","png_sha256":"1a35c8d1735721cde72701ff2febb69535f9ebb19844b5c9b241c487844b2473","png_size":[185,37],"private_texture_path_id":418904,"readback_pixel_exact":true,"sprite_path_id":875,"texture_bytes":30864,"texture_sha256":"bab356fe0dd58e661f1fdff01ad06fe051b2114a6b7b3a60fe184728be6ef4fb","transparent_padding_offset":[3,1]},{"PNG_resampled":false,"content_size":[184,48],"input_sha256":"8c5771c8836a71a9944424d18b6c7fac5c011dcb06fd426d7afe0e0b24aa24ab","layout_policy":"original-rect-love-text-v1","layout_size":[192,48],"name":"love_button_start","original_layout_size":[192.0,48.0],"output_bytes":1292,"output_sha256":"ab3ce9b383db93c1dfc8c1a63cfac0ca3b5dff99084841342c67142865c1b4c5","png_sha256":"9cd53381f154c4ccce414fce9ee816ea6d7b4fdb0612e06ce6a821bbd1ee824f","png_size":[184,48],"private_texture_path_id":418906,"readback_pixel_exact":true,"sprite_path_id":542,"texture_bytes":37012,"texture_sha256":"57114eeecce57925ba2c603bfa4a17b9e89fd9a376698837e81759007b32d591","transparent_padding_offset":[4,0]},{"PNG_resampled":false,"content_size":[96,28],"input_sha256":"f5404b603e61255ca89fcaeeae714e42f66bda6fa73c23a3c75a24f82268e50f","layout_policy":"original-rect-love-text-v1","layout_size":[96,32],"name":"love_header_level_label","original_layout_size":[96.0,32.0],"output_bytes":440,"output_sha256":"ad88fb382f989318b3ccc919b84afdf81340467b597da8063f0fff460ed58905","png_sha256":"5b4c6479eb59d8bb382e0850a80bc07c7b992440f28d4356ee624743431df821","png_size":[96,28],"private_texture_path_id":418911,"readback_pixel_exact":true,"sprite_path_id":1576,"texture_bytes":12440,"texture_sha256":"8dbbd4e8965bfc9b9876c79f36f33cd61c4341a14633fd632e74e6eb12546c34","transparent_padding_offset":[0,2]}],"texture_format":"RGBA32","translated_sprites":139},"type_graph_and_external_references_unchanged":true,"unchanged_object_count":418937}}}''')


@pytest.fixture
def refreshed_korean_report():
    report = deepcopy(KOREAN_REFRESH_PROOF)
    sprites = report["proofs"]["korean_resources"]["static_images"]["sprites"]
    sprites.extend({"name": "unchanged-sprite-" + str(i)} for i in range(129))
    language = delivery.read(delivery.HERE / "delivery-pins/client-languages-real-v3.manifest.json")
    return report, language


def test_refreshed_korean_resources_bind_actual_23_object_graph_and_all_other_bytes(refreshed_korean_report):
    report, language = refreshed_korean_report
    assert delivery.validate_refreshed_korean_resources(report, language) is None
    delivery.validate_language_manifest(language)
    assert len(language["common"]) == 44
    assert {key: len(language["common"]) + len(value)
            for key, value in language["languages"].items()} == {"ja": 46, "ko": 46, "en": 46}
    assert sum(row["source"] == "archive" for value in language["languages"].values()
               for row in value.values()) == 3


@pytest.mark.parametrize("damage", ["not-refreshed", "legacy-members", "bool-members", "output-sha",
    "source-base", "other-objects", "unchanged-count", "bool-unchanged-count", "missing-change", "extra-change",
    "changed-sha", "duplicate-id", "wrong-class", "false-change", "text-count", "text-layout", "text-padding",
    "text-texture", "missing-fixed-text", "duplicate-sprite-name", "logo-scale", "logo-position", "logo-source",
    "logo-output", "logo-object-bytes", "logo-other-fields", "duplicate-transform", "missing-logo"])
def test_refreshed_korean_resources_reject_partial_stale_or_unbounded_proofs(refreshed_korean_report, damage):
    report, language = refreshed_korean_report
    proof = report["proofs"]["korean_resources"]
    differences = proof["declared_object_differences"]
    images = proof["static_images"]
    fixed = images["sprites"][0]
    logo = images["logo_layout"]
    if damage == "not-refreshed": report["korean_resources_refreshed"] = False
    elif damage == "legacy-members": report["language_members"] = 2
    elif damage == "bool-members": report["language_members"] = True
    elif damage == "output-sha": proof["output"]["sha256"] = "f" * 64
    elif damage == "source-base": language["languages"]["ko"]["Data/resources.assets"]["source"] = "base"
    elif damage == "other-objects": proof["all_other_objects_byte_identical"] = 1
    elif damage == "unchanged-count": proof["unchanged_object_count"] = 418938
    elif damage == "bool-unchanged-count": proof["unchanged_object_count"] = True
    elif damage == "missing-change": differences.pop()
    elif damage == "extra-change": differences.append(deepcopy(differences[-1]))
    elif damage == "changed-sha": differences[0]["after_sha256"] = "e" * 64
    elif damage == "duplicate-id": differences[0]["path_id"] = differences[1]["path_id"]
    elif damage == "wrong-class": differences[0]["class_id"] = 28
    elif damage == "false-change": differences[0]["changed"] = False
    elif damage == "text-count": images["fixed_text_sprites"] = 9
    elif damage == "text-layout": fixed["layout_size"][0] += 1
    elif damage == "text-padding": fixed["transparent_padding_offset"][0] += 1
    elif damage == "text-texture": fixed["texture_sha256"] = "e" * 64
    elif damage == "missing-fixed-text": fixed["layout_policy"] = "preserved-v1-layout"
    elif damage == "duplicate-sprite-name": images["sprites"][-1]["name"] = fixed["name"]
    elif damage == "logo-scale": logo["uniform_scale"] = .7
    elif damage == "logo-position": logo["transforms"][0]["position"][0] += 1
    elif damage == "logo-source": logo["transforms"][0]["input_sha256"] = "e" * 64
    elif damage == "logo-output": logo["transforms"][0]["output_sha256"] = "e" * 64
    elif damage == "logo-object-bytes": logo["transforms"][0]["object_bytes"] = 109
    elif damage == "logo-other-fields": logo["transforms"][0]["only_position_and_size_changed"] = 1
    elif damage == "duplicate-transform": logo["transforms"][0] = deepcopy(logo["transforms"][1])
    elif damage == "missing-logo": del images["logo_layout"]
    with pytest.raises(delivery.DeliveryError):
        delivery.validate_refreshed_korean_resources(report, language)


def test_current_v3_pin_is_exact_and_legacy_v2_is_immutable():
    pins = delivery.HERE / "delivery-pins"
    current = pins / "client-languages-real-v3.manifest.json"
    legacy = pins / "client-languages-real-v2.manifest.json"
    assert current.stat().st_size == 8674
    assert delivery.sha(current) == delivery.LANGUAGE_MANIFEST_SHA256
    assert delivery.sha(legacy) == "21ab66246fb6647a9959f8001234dab44c6c9290685cc6f0c1bd4138d2bcbc1c"
    assert "ios-unified/delivery-pins/client-languages-real-v3.manifest.json" in delivery.DELIVERY_SOURCES
    assert "ios-unified/delivery-pins/client-languages-real-v2.manifest.json" not in delivery.DELIVERY_SOURCES
    with pytest.raises(delivery.DeliveryError, match="language_manifest_pin_differs"):
        delivery.validate_language_manifest(delivery.read(legacy))


def test_public_startup_receipt_producer_sources_are_frozen_for_delivery():
    assert {"tools/build_startup_translation_receipt.py", "src/idoly_local/startup_receipt.py"} <= set(delivery.DELIVERY_SOURCES)


@pytest.mark.parametrize("damage", [None, "missing-public", "schema-bool", "size-bool", "oversize-pin",
    "uppercase-sha", "platform", "extra-key", "duplicate-pin-key", "report", "report-schema-bool", "ipa-pin", "member-sha",
    "zip-sha", "envelope", "layer-source", "layer-extra", "symlink", "duplicate-member", "oversized-member"])
def test_delivery_requires_actual_signed_app_startup_receipt(tmp_path, damage):
    import io
    from types import SimpleNamespace
    from zipfile import ZipFile, ZipInfo
    layer = {"original_sha256": "a" * 64, "legacy_sha256": None,
             "source_sha256": ["b" * 64, "c" * 64, "d" * 64, None]}
    index = {"schema": 1, "platform": "ios", "layers": {"ko": deepcopy(layer), "en": deepcopy(layer)}}
    if damage == "envelope": index["platform"] = "android"
    if damage == "layer-source": index["layers"]["ko"]["source_sha256"][0] = True
    if damage == "layer-extra": index["layers"]["en"]["private_account"] = "forbidden"
    inner = io.BytesIO()
    with ZipFile(inner, "w") as receipt:
        receipt.writestr("index.json", json.dumps(index))
        for language in ("ko", "en"):
            for name in ("metadata.json", "base.pb", "rebased.pb"):
                receipt.writestr(language + "/" + name, b"public fixture")
    raw = inner.getvalue()
    pin = {"schema": 1, "platform": "ios", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if damage == "schema-bool": pin["schema"] = True
    elif damage == "size-bool": pin["bytes"] = True
    elif damage == "oversize-pin": pin["bytes"] = 16 * delivery.MIB + 1
    elif damage == "uppercase-sha": pin["sha256"] = "A" * 64
    elif damage == "platform": pin["platform"] = "android"
    elif damage == "extra-key": pin["path"] = "/private/account"
    elif damage == "zip-sha": pin["sha256"] = "f" * 64
    public = (json.dumps(pin, sort_keys=True) + "\n").encode()
    if damage == "duplicate-pin-key": public = public[:-2] + b',"schema":1}\n'
    if damage != "missing-public": (tmp_path / "startupTranslations.json").write_bytes(public)
    embedded = public if damage != "ipa-pin" else public + b" "
    report = {"startup_translations": deepcopy(pin), "member_sha256": {}}
    if damage == "report": report["startup_translations"]["bytes"] = len(raw) + 1
    if damage == "report-schema-bool": report["startup_translations"]["schema"] = True
    prefix = "Payload/Game.app/"
    path = tmp_path / "tiny.ipa"
    with ZipFile(path, "w") as ipa:
        for name, value in (("startupTranslations.json", embedded), ("startupTranslations.zip", raw)):
            member = prefix + "LocalServer/" + name
            if damage == "symlink" and name.endswith(".zip"):
                info = ZipInfo(member); info.create_system = 3; info.external_attr = 0o120777 << 16
                ipa.writestr(info, value)
            else: ipa.writestr(member, value)
            report["member_sha256"][member] = hashlib.sha256(value).hexdigest()
        if damage == "duplicate-member":
            with pytest.warns(UserWarning, match="Duplicate name"):
                ipa.writestr(prefix + "LocalServer/startupTranslations.zip", raw)
    if damage == "member-sha": report["member_sha256"][prefix + "LocalServer/startupTranslations.zip"] = "e" * 64
    with ZipFile(path) as ipa:
        if damage == "oversized-member":
            ipa.getinfo(prefix + "LocalServer/startupTranslations.zip").file_size = 16 * delivery.MIB + 1
        if damage is None:
            checks = []
            delivery.verify_bundled_startup_receipt(ipa, prefix, report, tmp_path,
                                                  SimpleNamespace(check=lambda: checks.append(True)))
            assert checks
        else:
            with pytest.raises(delivery.DeliveryError):
                delivery.verify_bundled_startup_receipt(ipa, prefix, report, tmp_path,
                                                      SimpleNamespace(check=lambda: None))


def test_current_delivery_artifact_requires_public_startup_receipt_pin():
    items = [item for item in required_entries() if item.filename != "startupTranslations.json"]
    with pytest.raises(delivery.DeliveryError, match="required_artifact_members_missing"):
        delivery.selected_members(Inventory(items))
