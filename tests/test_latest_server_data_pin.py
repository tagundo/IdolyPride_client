"""Offline contract tests for exact latest-source pins and complete payloads."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo, ZIP_STORED

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("latest_pin_tests", ROOT/"tools/latest_server_data_pin.py")
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)


def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def row(path, raw):
    return {"path": path, "bytes": len(raw), "sha256": digest(raw)}


def archive(path, files, *, symlink=None):
    with ZipFile(path, "w", compression=ZIP_STORED) as value:
        for name in sorted(files):
            info = ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.external_attr = ((stat.S_IFLNK if name == symlink else stat.S_IFREG)|0o644) << 16
            value.writestr(info, files[name])


def write_pin(env):
    proof = env.proof
    pin = {"schema": 1, "policy": subject.POLICY, "base_payload": subject.base_pin(),
           "component_sources": env.sources, "output": proof["output"], "source_blob": proof["source_blob"],
           "preparation": {"source_commit": "a"*40, "run_id": 321,
               "report_sha256": digest(canon(proof)+b"\n")}, "upgrade_proof": proof}
    env.pin_path.write_bytes(canon(pin)+b"\n")
    pointer = ("version https://git-lfs.github.com/spec/v1\noid sha256:"+proof["output"]["sha256"]
               +"\nsize "+str(proof["output"]["bytes"])+"\n").encode()
    env.pointer.write_bytes(pointer)
    return pin


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path/"repo"; root.mkdir()
    sources = {}
    for name in subject.SOURCE_FILES:
        path = root/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("source:"+name).encode())
        sources[name] = digest(path.read_bytes())
    monkeypatch.setattr(subject, "ROOT", root)
    pin_path = root/"data/latest-server-data-pin.json"
    monkeypatch.setattr(subject, "PIN_PATH", pin_path)
    descriptor = b"offline descriptor exact byte input"
    monkeypatch.setattr(subject, "DESCRIPTOR_SHA256", digest(descriptor))
    files = {"data/protocol/idolypride-6.1.1.pb": descriptor,
             "data/master-json/!version.txt": (subject.MASTER_VERSION+"\n").encode(),
             "data/love-compatibility.json": b'{"schema":1}',
             "data/love-legacy-rules.json": b'{"schema":1,"legacy":true}'}
    packs, tag_packs = [], []
    for i in range(202):
        identity, name = "Pack%03d"%i, "original-%03d"%i
        raw = ("encrypted-public:"+identity).encode()
        files["data/original-master/assets/master/"+name] = raw
        packs.append({"type": identity, "file_name": name, "bytes": len(raw), "sha256": digest(raw)})
        tag_packs.append({"type": identity, "fileName": name, "fileSize": len(raw), "cryptoKey": "a"*32,
                          "downloadUrl": "http://127.0.0.1:8080/master/"+name})
        if i < 63:
            files["data/master-json/"+identity+".json"] = b"[]\n"
    catalog = {"schema":1,"master_version":subject.MASTER_VERSION,"schema_sha256":subject.SCHEMA_SHA256,
        "events":{"love-%d"%i:{"episodes":{"episode-%d-%d"%(i,j):{} for j in range(12)}} for i in range(6)}}
    ruleset = digest(canon(catalog)); catalog["ruleset_sha256"] = ruleset
    files["data/master-json/LoveCatalog.json"] = canon(catalog)+b"\n"
    original = {"complete": True, "master_version": subject.MASTER_VERSION,
                "expected_packs": 202, "completed_packs": 202,
                "packs": {p["type"]: {"file_name":p["file_name"],"size":p["bytes"],"sha256":p["sha256"]}
                          for p in packs}}
    files["data/original-master/archive-report.json"] = canon(original)+b"\n"
    locales = {}
    for language in ("ja","ko","en"):
        modes = locales[language] = {}
        prefix = "data/original-master/" + ("" if language == "ja" else "languages/"+language+"/")
        for mode in ("normal","media"):
            stem = "" if mode == "normal" else "media-"
            version = subject.MASTER_VERSION if (language,mode) == ("ja","normal") else "local-"+language+"-"+mode
            tag = canon({"version":version,"masterTagPacks":tag_packs})+b"\n"
            sort = canon({"schema":1,"language":language,"source":mode})+b"\n"
            files[prefix+stem+"master-tag.json"] = tag
            files[prefix+stem+"master-sort.json"] = sort
            modes[mode] = {"tag_version":version,"tag_sha256":digest(tag),"pack_count":202,
                          "table_names":[p["type"] for p in packs],"sort_manifest_sha256":digest(sort)}
    overlay = {"schema":1,"operation":subject.POLICY,"derivation":"complete-public-member-replacement",
               "base_bytes":subject.BASE_BYTES,"base_sha256":subject.BASE_SHA256,
               "master_version":subject.MASTER_VERSION,"component_sources":sources,
               "component_sources_sha256":digest(canon(sources))}
    controls = {}
    for name in ("story_reads", "media_access", "panorama", "dream", "main_live", "octo"):
        receipt = {"checked": 1}
        controls[name] = {"status":"PASS","scope":name,"master_version":subject.MASTER_VERSION,
            "schema_sha256":subject.SCHEMA_SHA256,"receipt":receipt,"receipt_sha256":digest(canon(receipt))}
    controls = {"schema":1,"master_version":subject.MASTER_VERSION,"features":controls}
    files["data/latest-semantic-controls.json"] = canon(controls)+b"\n"
    rows = [row(name,files[name]) for name in sorted(files)]
    tables = sorted(name[len("data/master-json/"):-5] for name in files
                    if name.startswith("data/master-json/") and name.endswith(".json"))
    manifest = {"schema":1,"master_version":subject.MASTER_VERSION,"files":rows,
                "tables":{name:0 for name in tables if name!="LoveCatalog"},
                "source_overlay":overlay,"semantic_controls":controls}
    files[subject.MANIFEST] = canon(manifest)+b"\n"
    payload = tmp_path/"compiled.zip"; archive(payload,files)
    output = {"bytes":payload.stat().st_size,"sha256":digest(payload.read_bytes()),
              "entries":len(files),"master_json_tables":64,
              "payload_manifest_sha256":digest(files[subject.MANIFEST]),
              "member_inventory_sha256":digest(canon(rows)),"member_names":sorted(files),
              "master_json_table_names":tables,"members":rows}
    old_names = set(files)-{"data/love-compatibility.json","data/love-legacy-rules.json"}
    for i in range(555-len(old_names)):
        old_names.add("data/original-master/assets/master/obsolete-%03d"%i)
    monkeypatch.setattr(subject, "_base_names", lambda:set(old_names))
    new_names = set(files)
    preservation = {"unchanged_paths":sorted((old_names&new_names)-{subject.MANIFEST}),
        "replaced_paths":[subject.MANIFEST],"removed_paths":sorted(old_names-new_names),
        "added_paths":sorted(new_names-old_names)}
    proof = {"schema":1,"status":"PASS","operation":subject.POLICY,
        "base":{**subject.base_pin(),"entries":555,"master_json_tables":55},
        "component_sources":sources,"component_sources_sha256":digest(canon(sources)),
        "source_blob":{"path":subject.OVERLAY_PATH,"bytes":output["bytes"],"sha256":output["sha256"]},
        "output":output,"original_master":{"version":subject.MASTER_VERSION,
          "schema_sha256":subject.SCHEMA_SHA256,"descriptor_sha256":subject.DESCRIPTOR_SHA256,
          "tag_sha256":locales["ja"]["normal"]["tag_sha256"],
          "archive_report_sha256":digest(files["data/original-master/archive-report.json"]),
          "pack_count":202,"packs":packs},
        "love":{"master_version":subject.MASTER_VERSION,"schema_sha256":subject.SCHEMA_SHA256,
          "ruleset_sha256":ruleset,"events":6,"episodes":72,
          "compatibility":{"path":"data/love-compatibility.json","sha256":digest(files["data/love-compatibility.json"]),
            "legacy_ruleset_sha256":"b"*64,"legacy_rules_path":"data/love-legacy-rules.json",
            "legacy_rules_sha256":digest(files["data/love-legacy-rules.json"])}},
        "locales":locales,"preservation":preservation,"derivation":deepcopy(subject._DERIVATION),
        "semantic_controls":controls}
    env = SimpleNamespace(root=root,pin_path=pin_path,pointer=root/subject.OVERLAY_PATH,
                          sources=sources,proof=proof,payload=payload,files=files)
    write_pin(env)
    return env


def test_complete_compiled_blob_payload_pin_and_sidecar_have_exact_roles(frozen):
    pin = subject.load_pin()
    assert subject.verify_source_pointer() == subject.output_pin() == subject.overlay_pin()
    assert subject.verify_payload(frozen.payload) == frozen.proof["output"]
    assert subject.verify_overlay(frozen.payload) == frozen.proof["output"]
    assert subject.verify_upgrade_proof(frozen.proof) == frozen.proof
    assert subject.payload_pin() == {"schema":1,"policy":subject.POLICY,
        "bytes":pin["output"]["bytes"],"sha256":pin["output"]["sha256"],
        "manifest_sha256":pin["output"]["payload_manifest_sha256"],"master_version":subject.MASTER_VERSION}
    pin["upgrade_proof"]["love"]["events"] = 0
    assert subject.load_pin()["upgrade_proof"]["love"]["events"] == 6


@pytest.mark.parametrize("change", ["source","pointer","missing","blob-role","base","receipt"])
def test_pin_requires_current_sources_canonical_pointer_and_immutable_roles(frozen, change):
    if change == "source": (frozen.root/subject.SOURCE_FILES[0]).write_bytes(b"changed")
    elif change == "pointer": frozen.pointer.write_bytes(frozen.pointer.read_bytes()+b"\n")
    elif change == "missing": frozen.pin_path.unlink()
    else:
        pin = json.loads(frozen.pin_path.read_bytes())
        if change == "blob-role": pin["source_blob"]["sha256"] = "0"*64
        elif change == "base": pin["base_payload"]["sha256"] = "0"*64
        else: pin["preparation"]["report_sha256"] = "0"*64
        frozen.pin_path.write_bytes(canon(pin))
    with pytest.raises(subject.LatestServerDataPinError): subject.load_pin()


@pytest.mark.parametrize("change", ["pack-count","pack-sha","tables","locale","compatibility","preservation","boolean","derivation"])
def test_proof_rejects_incoherent_catalog_and_exact_member_projection(frozen, change):
    proof = frozen.proof
    if change == "pack-count": proof["original_master"]["pack_count"] = 201
    elif change == "pack-sha": proof["original_master"]["packs"][0]["sha256"] = "0"*64
    elif change == "tables": proof["output"]["master_json_tables"] = 63
    elif change == "locale": proof["locales"]["en"]["media"]["pack_count"] = 201
    elif change == "compatibility": proof["love"]["compatibility"]["sha256"] = "0"*64
    elif change == "preservation": proof["preservation"]["unchanged_paths"].pop()
    elif change == "boolean": proof["schema"] = True
    else: proof["derivation"]["raw_compile_repeat_byte_identity_claim"] = True
    write_pin(frozen)
    with pytest.raises(subject.LatestServerDataPinError): subject.load_pin()


def test_untrusted_fresh_receipt_cannot_rewrite_preparation(frozen):
    changed = deepcopy(frozen.proof); changed["original_master"]["version"] = "0"*64
    with pytest.raises(subject.LatestServerDataPinError): subject.verify_upgrade_proof(changed)
    with pytest.raises(subject.LatestServerDataPinError): subject.verify_upgrade_proof({"value":float("nan")})


@pytest.mark.parametrize("kind", ["changed","symlink","fifo","zip-link"])
def test_complete_payload_verification_rejects_changed_or_nonregular_inputs(frozen, kind, tmp_path):
    target = tmp_path/"input.zip"
    if kind == "changed":
        target.write_bytes(frozen.payload.read_bytes()[:-1]+b"x")
    elif kind == "symlink": target.symlink_to(frozen.payload)
    elif kind == "fifo": os.mkfifo(target)
    else:
        archive(target,frozen.files,symlink="data/protocol/idolypride-6.1.1.pb")
        frozen.proof["output"]["bytes"] = target.stat().st_size
        frozen.proof["output"]["sha256"] = digest(target.read_bytes())
        frozen.proof["source_blob"].update(bytes=target.stat().st_size,sha256=digest(target.read_bytes()))
        write_pin(frozen)
    with pytest.raises(subject.LatestServerDataPinError): subject.verify_payload(target)


def test_ci_fetch_is_explicit_readonly_fresh_owned_and_hash_verified(frozen, tmp_path, monkeypatch):
    destination = tmp_path/"fresh.zip"
    calls = []
    monkeypatch.delenv("GITHUB_ACTIONS",raising=False)
    monkeypatch.setattr(subject,"_download_overlay",lambda *args:calls.append(args))
    with pytest.raises(subject.LatestServerDataPinError):subject.fetch_overlay(destination)
    assert not calls and not destination.exists()
    monkeypatch.setenv("GITHUB_ACTIONS","true");monkeypatch.setenv("GITHUB_RUN_ID","42")
    monkeypatch.setenv("RUNNER_TEMP",str(tmp_path))
    def download(pin,path):
        assert pin == subject.output_pin()
        path.write_bytes(frozen.payload.read_bytes()); calls.append(dict(pin))
    monkeypatch.setattr(subject,"_download_overlay",download)
    assert subject.fetch_overlay(destination) == frozen.proof["output"]
    assert digest(destination.read_bytes()) == frozen.proof["output"]["sha256"] and len(calls)==1
    with pytest.raises(subject.LatestServerDataPinError):subject.fetch_overlay(destination)
    assert len(calls)==1 and not list(tmp_path.glob(".latest-cohort-*"))


def test_fetch_bad_full_bytes_never_installs_destination(frozen,tmp_path,monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS","true");monkeypatch.setenv("GITHUB_RUN_ID","42")
    monkeypatch.setenv("RUNNER_TEMP",str(tmp_path))
    monkeypatch.setattr(subject,"_download_overlay",lambda pin,path:path.write_bytes(b"wrong"))
    target = tmp_path/"new.zip"
    with pytest.raises(subject.LatestServerDataPinError):subject.fetch_overlay(target)
    assert not target.exists() and not list(tmp_path.glob(".latest-cohort-*"))


@pytest.mark.parametrize("path", ["data/state.sqlite","data/server-events.json","data/accounts/a.zip",
    "data/original-master/assets/master/../../state.sqlite","data/licenses/unrelated.txt",
    "data/public-fixtures/responses/api.Auth-Login-"+"a"*64+".pb"])
def test_only_finite_public_names_are_admitted(path):
    assert not subject._public_name(path)


def test_legacy_pin_is_historical_data_and_helper_has_no_duplicate_functions():
    import ast
    tree = ast.parse((ROOT/"tools/latest_server_data_pin.py").read_text())
    names = [node.name for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))]
    assert len(names)==len(set(names))
    assert len(subject._base_names()) == 555
    assert subject.BASE_BYTES == 191343014 and subject.BASE_SHA256.startswith("37dbf0fb")


@pytest.mark.parametrize("name", [
    "../data/master-json/Card.json", "data/../settings.json", "data/account-management/registry.json",
    "data/state.sqlite3", "data/settings.json", "data/server-events.json", "data/licenses/account.zip",
    "data/original-master/private-user.json", "data/public-fixtures/responses/api.User-Get-"+"a"*64+".pb",
    "data/master-json/Card.json/", "data\\master-json\\Card.json", "/data/master-json/Card.json"])
def test_public_namespace_never_admits_accounts_settings_or_path_aliases(name):
    assert not subject._public_name(name)


@pytest.mark.parametrize("change", ["tables", "table-type", "pack-count", "duplicate-pack",
                                    "blob-path", "locale-count", "preservation", "derivation"])
def test_structural_proof_invariants_remain_strict(frozen, change):
    proof = frozen.proof
    if change == "tables": proof["output"]["master_json_tables"] = 63
    elif change == "table-type": proof["output"]["master_json_tables"] = True
    elif change == "pack-count": proof["original_master"]["pack_count"] = 201
    elif change == "duplicate-pack": proof["original_master"]["packs"][-1] = deepcopy(proof["original_master"]["packs"][0])
    elif change == "blob-path": proof["source_blob"]["path"] = "data/other.zip"
    elif change == "locale-count": proof["locales"]["en"]["media"]["pack_count"] = 201
    elif change == "preservation": proof["preservation"]["removed_paths"].pop()
    else: proof["derivation"]["raw_compile_repeat_byte_identity_claim"] = True
    write_pin(frozen)
    with pytest.raises(subject.LatestServerDataPinError):
        subject.load_pin()


def test_historical_base_namespace_is_read_as_immutable_data_not_current_generators(monkeypatch, tmp_path):
    original_root = ROOT
    monkeypatch.setattr(subject, "ROOT", original_root)
    names = subject._base_names()
    assert len(names) == 555 and subject.MANIFEST in names
    assert "data/master-json/LoveCatalog.json" not in names
    location = tmp_path/"data"; location.mkdir()
    raw = (original_root/"data/love-server-data-pin.json").read_bytes()
    (location/"love-server-data-pin.json").write_bytes(raw+b" ")
    monkeypatch.setattr(subject, "ROOT", tmp_path)
    with pytest.raises(subject.LatestServerDataPinError, match="historical_pin"):
        subject._base_names()


def test_source_has_one_api_definition_and_one_64_table_validation_path():
    import ast
    tree = ast.parse((ROOT/"tools/latest_server_data_pin.py").read_text())
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert len(functions) == len(set(functions))
    output = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_output")
    table_checks = [node for node in ast.walk(output) if isinstance(node, ast.Constant) and node.value == "latest_data_tables_differ"]
    assert len(table_checks) == 1


def test_outer_blob_pin_cannot_diverge_even_with_a_canonical_matching_pointer(frozen):
    pin = json.loads(frozen.pin_path.read_bytes())
    pin["source_blob"]["sha256"] = "0"*64
    frozen.pin_path.write_bytes(canon(pin))
    frozen.pointer.write_bytes(("version https://git-lfs.github.com/spec/v1\\noid sha256:"
        +"0"*64+"\\nsize "+str(pin["source_blob"]["bytes"])+"\\n").encode())
    with pytest.raises(subject.LatestServerDataPinError, match="blob_differs"):
        subject.load_pin()

@pytest.mark.parametrize("field", ["base_payload","base","blob"])
def test_json_numeric_equality_cannot_admit_float_byte_counts(frozen, field):
    pin = json.loads(frozen.pin_path.read_bytes())
    if field == "base_payload":
        pin["base_payload"]["bytes"] = float(pin["base_payload"]["bytes"])
        frozen.pin_path.write_bytes(canon(pin))
    else:
        row = frozen.proof["base"] if field == "base" else frozen.proof["source_blob"]
        row["bytes"] = float(row["bytes"])
        write_pin(frozen)
    with pytest.raises(subject.LatestServerDataPinError):
        subject.load_pin()


@pytest.mark.parametrize("damage", ["scope", "receipt", "feature"])
def test_semantic_envelope_is_finite_and_bound_to_typed_receipt_hash(frozen, damage):
    controls = frozen.proof["semantic_controls"]["features"]
    if damage == "scope": controls["story_reads"]["scope"] = "other"
    elif damage == "receipt": controls["story_reads"]["receipt"]["checked"] = 0
    else: controls["other"] = controls["story_reads"]
    write_pin(frozen)
    with pytest.raises(subject.LatestServerDataPinError, match="semantic_controls"):
        subject.load_pin()
