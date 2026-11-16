"""Finite synthetic compatibility evidence and exact legacy account-byte preservation."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from idoly_local import love_catalog as catalog
from idoly_local import love_compatibility_pins as pins
from idoly_local.account_manager import AccountManager
from idoly_local.love import Love
from idoly_local.rpc import RpcFailure
from test_love import game, schema, settings, invoke, register, finish_first, progress, EV, RULES, UNKNOWN
from test_love_catalog import _synthetic_record


def digest(raw): return hashlib.sha256(raw).hexdigest()


def body(record):
    record.pop("ruleset_sha256", None)
    record["ruleset_sha256"] = digest(catalog._canonical(record))
    return catalog._canonical(record) + b"\n"


def sample():
    story = {"id":"story-one","name":"Original","description":"Original story",
             "advAssetIds":["love_original"],"rewardId":""}
    event = {"loveId":EV,"unlockConditionId":"cd-unlock","storyReadItemId":"pt",
        "presentItemId":"present","promoteItemId":"boost","eventMissionIds":["mission-one"],
        "limitedEventMissionIds":[],"mainCharacters":[{"characterId":"char-one","costumeId":"cos-one",
             "assetId":"img_chr_one","color":"ffffff"}],
        "episodes":{"ep-one":{"storyId":"story-one","story":story,"storyAssetId":"love_original",
                                  "consumptionItemAmount":2}},
        "routes":{"ep-one":{"groups":[{"index":1,"count":2,"best":1}],
                              "outcomes":[{"all":[],"ending":"end-one"}]}},
        "levels":[{"level":1,"requiredExp":"0","lessonStepRewardExp":"14"}],
        "endings":[{"id":"end-one","name":"Original ending","favorability":0}],
        "endingConditions":{"cd-end":"end-one"},"homeActions":[{"id":"action-one","text":"Original"}]}
    tables = {name:[] for name in catalog.SOURCE_TABLES}
    tables.update({"Story":[story,{"id":"unrelated-story","advAssetIds":["other"]}],
        "Item":[{"id":"pt","type":9001,"value":"0"},{"id":"present","type":9002,"value":"7"},
                {"id":"boost","type":9003,"value":"120"},{"id":"unrelated-item","value":"1"}],
        "Character":[{"id":"char-one","assetId":"one","costumeIds":["cos-one"]},
                     {"id":"unrelated-character","assetId":"other"}],
        "Costume":[{"id":"cos-one","characterId":"char-one","bodyAssetId":"one-school"},
                   {"id":"unrelated-costume","characterId":"unrelated-character"}],
        "Area":[{"id":"area-one","questIds":["quest-one"]}],
        "Condition":[{"id":"cd-unlock","setting":[{"clearArea":{"areaId":"area-one"}}]},
                     {"id":"cd-end","setting":[{"conditionIds":["cd-child"]}]},
                     {"id":"cd-child","setting":[{"conditionIds":["cd-end"],"threshold":1}]},
                     {"id":"cd-mission","setting":[{"clearArea":{"areaId":"area-one"}}]},
                     {"id":"cd-unrelated","setting":[]}],
        "EventMission":[{"id":"mission-one","conditionId":"cd-mission","missionIds":["ms-one"]}],
        "Setting":[{"loveSaveSlotNum":5,"secondsPerLoveLessonStep":10,"loveTitleAssetId":"title-original",
                    "unrelatedFlag":False}]})
    return {"schema":1,"schema_sha256":catalog.SCHEMA_SHA256,"events":{EV:event},
            "policy":{"score_bonus_grants":False,"finish_stone_grant":False}},tables


def test_semantic_projection_includes_recursive_conditions_but_ignores_unrelated_new_inventory():
    record,tables = sample()
    original = catalog._semantic_rules(record,tables)
    changed,latest = deepcopy((record,tables))
    latest["Character"][0]["costumeIds"].append("new-unrelated-costume")
    latest["Character"][0]["profile"] = "Changed character biography"
    latest["Condition"].append({"id":"cd-new-unrelated","setting":[]})
    latest["Story"].append({"id":"new-card-story","advAssetIds":["new-card-adv"]})
    latest["Item"].append({"id":"new-card-item","type":1,"value":"1"})
    latest["Costume"].append({"id":"new-outfit","characterId":"char-one"})
    latest["Setting"][0]["unrelatedFlag"] = True
    assert catalog._semantic_rules(changed,latest) == original
    assert {row["id"] for row in original["external"]["Condition"]} == {"cd-unlock","cd-end","cd-child","cd-mission"}
    assert original["external"]["Area"][0]["questIds"] == ["quest-one"]


@pytest.mark.parametrize("change", ["episode-cost","choice-count","ending","present-value","boost-type",
    "nested-condition","area-quests","costume-model","character-model","story-asset","story-text","lesson-step"])
def test_any_actual_story_cost_choice_ending_or_dependency_change_is_not_compatible(change):
    original,tables = sample()
    changed,latest = deepcopy((original,tables))
    event = changed["events"][EV]
    if change == "episode-cost": event["episodes"]["ep-one"]["consumptionItemAmount"] += 1
    elif change == "choice-count": event["routes"]["ep-one"]["groups"][0]["count"] += 1
    elif change == "ending": event["endings"][0]["id"] = "other-ending"
    elif change == "present-value": latest["Item"][1]["value"] = "8"
    elif change == "boost-type": latest["Item"][2]["type"] = 1
    elif change == "nested-condition": latest["Condition"][2]["setting"][0]["threshold"] = 2
    elif change == "area-quests": latest["Area"][0]["questIds"].append("quest-two")
    elif change == "costume-model": latest["Costume"][0]["bodyAssetId"] = "different-model"
    elif change == "character-model": latest["Character"][0]["assetId"] = "different-model"
    elif change == "story-asset": latest["Story"][0]["advAssetIds"] = ["different-adv"]
    elif change == "story-text": latest["Story"][0]["description"] = "Different original text"
    else: latest["Setting"][0]["secondsPerLoveLessonStep"] = 20
    assert catalog._semantic_rules(changed,latest) != catalog._semantic_rules(original,tables)


def test_missing_condition_or_selected_costume_link_fails_closed():
    record,tables = sample()
    tables["Condition"] = [row for row in tables["Condition"] if row["id"] != "cd-child"]
    with pytest.raises(catalog.LoveCatalogError): catalog._semantic_rules(record,tables)
    record,tables = sample();tables["Costume"][0]["characterId"] = "wrong-character"
    with pytest.raises(catalog.LoveCatalogError): catalog._semantic_rules(record,tables)


def adv_report():
    proof = json.loads((Path(__file__).resolve().parents[1] / "data/love-adv-proof.json").read_bytes())
    names = sorted("adv_" + asset + ".txt" for asset in proof["assets"])
    return {"schema":1,"platforms":{platform:{"baseline_manifest_sha256":"a"*64,
        "candidate_manifest_sha256":"b"*64,"records":[{"name":name,
            "baseline":{"md5":"1"*32,"size":10,"generation":1,"objectName":"original-"+str(index)},
            "candidate":{"md5":"1"*32,"size":10,"generation":1,"objectName":"original-"+str(index)}}
            for index,name in enumerate(names)]} for platform in ("android","ios")}}


def prepared(tmp_path, monkeypatch, *, different=False):
    old,tables = sample()
    new,latest = deepcopy((old,tables))
    if different: latest["Item"][1]["value"] = "8"
    else: latest["Character"][0]["costumeIds"].append("new-outfit")
    paths = []
    for name,record,rows,version in (("legacy",old,tables,catalog.MASTER_VERSION),
                                   ("public",new,latest,catalog.LATEST_MASTER_VERSION)):
        directory = tmp_path / name / "master-json";directory.mkdir(parents=True)
        record["master_version"] = version
        record["source_files"] = {}
        for table in catalog.SOURCE_TABLES:
            raw = catalog._canonical(rows[table]) + b"\n"
            (directory / (table + ".json")).write_bytes(raw)
            record["source_files"][table + ".json"] = digest(raw)
        (directory / "!version.txt").write_text(version)
        raw = body(record)
        if name == "legacy": (directory / "LoveCatalog.json").write_bytes(raw)
        paths.append(directory)
    monkeypatch.setattr(catalog,"LEGACY_RULESET_SHA256",old["ruleset_sha256"])
    monkeypatch.setattr(catalog,"load_love_catalog",lambda *args,**kwargs:deepcopy(old))
    monkeypatch.setattr(catalog,"build_love_catalog",lambda *args,**kwargs:deepcopy(new))
    arguments = {"latest_pack_proofs":{},"legacy_master_dir":paths[0],
        "legacy_catalog_path":paths[0]/"LoveCatalog.json","output_path":paths[1]/"LoveCatalog.json",
        "compatibility_path":paths[1].parent/"love-compatibility.json",
        "legacy_rules_path":paths[1].parent/"love-legacy-rules.json","adv_identity_proof":adv_report()}
    return old,new,paths,arguments


@pytest.mark.parametrize("different", [False, True])
def test_remote_preparer_preserves_exact_old_rules_and_publishes_only_proven_alias(tmp_path, monkeypatch, different):
    old,new,paths,args = prepared(tmp_path,monkeypatch,different=different)
    before = {p:p.read_bytes() for p in paths[0].iterdir()}
    report = catalog.prepare_latest_love_catalog(SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256),paths[1],**args)
    candidate = json.loads(args["output_path"].read_bytes())
    proof = json.loads(args["compatibility_path"].read_bytes())
    archived = json.loads(args["legacy_rules_path"].read_bytes())
    assert report["equivalent"] is proof["equivalent"] is (not different)
    assert candidate["master_version"] == catalog.LATEST_MASTER_VERSION
    assert candidate["progress_ruleset_aliases"] == ([] if different else [old["ruleset_sha256"]])
    assert candidate["ruleset_sha256"] != old["ruleset_sha256"]
    assert base64.b64decode(archived["catalog_raw_base64"]) == before[args["legacy_catalog_path"]]
    assert before == {p:p.read_bytes() for p in paths[0].iterdir()}
    for key,path in (("catalog",args["output_path"]),("compatibility",args["compatibility_path"]),
                     ("legacy_rules",args["legacy_rules_path"])):
        raw = path.read_bytes();assert report["files"][key] == {"bytes":len(raw),"sha256":digest(raw)}
    assert not list(tmp_path.rglob("*.db"))


def test_preparer_rejects_changed_old_source_and_removes_only_its_new_partial_outputs(tmp_path, monkeypatch):
    old,new,paths,args = prepared(tmp_path,monkeypatch)
    item = paths[0] / "Item.json";raw = item.read_bytes();item.write_bytes(raw + b" ")
    with pytest.raises(catalog.LoveCatalogError):
        catalog.prepare_latest_love_catalog(SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256),paths[1],**args)
    assert not args["output_path"].exists() and not args["compatibility_path"].exists()
    item.write_bytes(raw)
    args["compatibility_path"].write_bytes(b"existing-not-owned")
    with pytest.raises(FileExistsError):
        catalog.prepare_latest_love_catalog(SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256),paths[1],**args)
    assert not args["output_path"].exists() and args["compatibility_path"].read_bytes() == b"existing-not-owned"


def runtime_candidate(tmp_path, monkeypatch):
    directory = tmp_path / "master-json"
    record = _synthetic_record(directory)
    record["master_version"] = catalog.LATEST_MASTER_VERSION
    record["progress_ruleset_aliases"] = [catalog.LEGACY_RULESET_SHA256]
    (directory / "!version.txt").write_text(catalog.LATEST_MASTER_VERSION)
    raw = body(record);(directory / "LoveCatalog.json").write_bytes(raw)
    archive_raw = b'{"synthetic_legacy_archive":true}\n'
    archive = tmp_path / "love-legacy-rules.json";archive.write_bytes(archive_raw)
    source = record["source_files"]
    proof = {"schema":1,"policy":"love-progress-compatibility-v1","schema_sha256":catalog.SCHEMA_SHA256,
        "reference_sha256":catalog.REFERENCE_SHA256,"adv_proof_sha256":catalog.ADV_PROOF_SHA256,
        "equivalent":True,"reason_code":None,"adv_identity_proof":adv_report(),
        "legacy":{"master_version":catalog.MASTER_VERSION,"ruleset_sha256":catalog.LEGACY_RULESET_SHA256,
            "catalog_sha256":"1"*64,"semantic_sha256":"2"*64,"source_files":source},
        "candidate":{"master_version":catalog.LATEST_MASTER_VERSION,"ruleset_sha256":record["ruleset_sha256"],
            "catalog_sha256":digest(raw),"semantic_sha256":"2"*64,"source_files":source},
        "legacy_rules":{"name":"love-legacy-rules.json","bytes":len(archive_raw),"sha256":digest(archive_raw)}}
    path = tmp_path / "love-compatibility.json"
    def pin():
        encoded = catalog._canonical(proof) + b"\n";path.write_bytes(encoded)
        monkeypatch.setattr(pins,"COMPATIBILITY_SHA256",digest(encoded))
        catalog._CACHE.clear()
    pin()
    return directory,record,proof,path,archive,pin


def test_runtime_accepts_only_exact_pinned_cohort_proof_and_keeps_full_integrity(tmp_path, monkeypatch):
    directory,record,proof,path,archive,pin = runtime_candidate(tmp_path,monkeypatch)
    schema = SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256)
    assert catalog.load_love_catalog(schema,directory) == record
    (directory / "Item.json").write_bytes(b"[{}]")
    with pytest.raises(catalog.LoveCatalogError): catalog.load_love_catalog(schema,directory)


@pytest.mark.parametrize("damage", ["unverified","proof-bytes","archive-bytes","missing-archive",
                                     "unknown-alias","false-equivalence","invalid-semantic-hash","changed-adv"])
def test_latest_legacy_alias_is_fail_closed_when_any_finite_evidence_differs(tmp_path, monkeypatch, damage):
    directory,record,proof,path,archive,pin = runtime_candidate(tmp_path,monkeypatch)
    if damage == "unverified": monkeypatch.setattr(pins,"COMPATIBILITY_SHA256",None)
    elif damage == "proof-bytes": path.write_bytes(path.read_bytes()+b" ")
    elif damage == "archive-bytes": archive.write_bytes(archive.read_bytes()+b" ")
    elif damage == "missing-archive": archive.unlink()
    elif damage == "unknown-alias":
        record["progress_ruleset_aliases"] = ["f"*64]
        raw = body(record);(directory / "LoveCatalog.json").write_bytes(raw)
        proof["candidate"].update(catalog_sha256=digest(raw),ruleset_sha256=record["ruleset_sha256"]);pin()
    elif damage == "false-equivalence": proof["equivalent"]=False;proof["candidate"]["semantic_sha256"]="3"*64;pin()
    elif damage == "changed-adv":
        proof["adv_identity_proof"]["platforms"]["ios"]["records"][0]["candidate"]["generation"] += 1;pin()
    else: proof["candidate"]["semantic_sha256"] = proof["legacy"]["semantic_sha256"] = None;pin()
    with pytest.raises(catalog.LoveCatalogError):
        catalog.load_love_catalog(SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256),directory)


@pytest.mark.parametrize("mode", ["normal","media"])
def test_existing_progress_snapshot_archive_and_storage_pin_survive_compatible_upgrade_exactly(game,tmp_path,mode):
    manager = AccountManager(tmp_path / "accounts",schema=game.schema)
    state = manager._state(mode)
    seed = game.state.account_snapshot("player")[0]
    state.replace_account("player",seed)
    old_normal = game.state.account_snapshot("player")
    viewer = Love(game.schema,state,"player",game.master,event_settings=settings(),
                  media_mode=mode=="media",clock=lambda:game.clock[0])
    viewer._prepared = deepcopy(game.plan)
    target = SimpleNamespace(**{**vars(game),"state":state,"love":viewer})
    register(target);finish_first(target,bad=True)
    invoke(target,"Save",loveId=EV,slotNumber=1)
    def uncommon_wire(snapshot,raw):
        data=json.loads(raw)
        return UNKNOWN+snapshot,json.dumps(data,indent=2,ensure_ascii=False).encode()
    state.mutate_love_snapshot("player",game.schema.fingerprint,EV,RULES,uncommon_wire)
    before = state.account_snapshot("player")
    saved = state.love_progress("player",EV)
    exported = manager.command("accounts_export",{"mode":mode,"profile":"player","expected_revision":before[1]})
    with ZipFile(exported["path"]) as archive:backup = archive.read("account.json")
    latest = deepcopy(game.plan)
    latest["master_version"] = catalog.LATEST_MASTER_VERSION
    latest["ruleset_sha256"] = "f"*64
    latest["progress_ruleset_aliases"] = [RULES]
    target.love = Love(game.schema,state,"player",game.master,event_settings=settings(),
                       media_mode=mode=="media",clock=lambda:game.clock[0])
    target.love._prepared = latest
    assert state.account_snapshot("player") == before
    invoke(target,"Title");invoke(target,"Top",loveId=EV)
    assert state.account_snapshot("player") == before and state.love_progress("player",EV) == saved
    again = manager.command("accounts_export",{"mode":mode,"profile":"player","expected_revision":before[1]})
    with ZipFile(again["path"]) as archive:assert archive.read("account.json") == backup
    preview = manager.command("accounts_preview",{"path":exported["path"]})
    manager.command("accounts_import",{"token":preview["token"],"mode":mode,"profile":"restored",
                    "replace":False,"expected_revision":None})
    assert state.love_progress("restored",EV) == saved
    invoke(target,"UpdateName",loveId=EV,name="Changed")
    assert progress(target)["player_name"] == "Changed" and state.love_progress("player",EV)[2] == RULES
    state.save_snapshot("fresh",seed["tables"]["snapshots"][0]["response"],game.schema.fingerprint)
    target.love = Love(game.schema,state,"fresh",game.master,event_settings=settings(),
                       media_mode=mode=="media",clock=lambda:game.clock[0]);target.love._prepared=latest
    invoke(target,"Register",loveId=EV,name="Fresh")
    assert state.love_progress("fresh",EV)[2] == latest["ruleset_sha256"]
    assert game.state.account_snapshot("player") == old_normal


def test_unproven_new_rules_refuse_existing_progress_without_resetting_or_granting(game):
    register(game);before=game.state.account_snapshot("player")
    latest=deepcopy(game.plan);latest["ruleset_sha256"]="f"*64
    game.love._prepared=latest
    with pytest.raises(RpcFailure):invoke(game,"Top",loveId=EV)
    assert game.state.account_snapshot("player") == before


@pytest.mark.parametrize("platform", ["android","ios"])
@pytest.mark.parametrize("field", ["md5","size","generation","objectName"])
def test_changed_latest_adv_identity_blocks_preparation_before_any_outputs(tmp_path,monkeypatch,platform,field):
    old,new,paths,args = prepared(tmp_path,monkeypatch)
    identity = args["adv_identity_proof"]["platforms"][platform]["records"][0]["candidate"]
    identity[field] = identity[field] + 1 if type(identity[field]) is int else identity[field] + "different"
    original = args["legacy_catalog_path"].read_bytes()
    with pytest.raises(catalog.LoveCatalogError,match="love_compatibility_adv_changed"):
        catalog.prepare_latest_love_catalog(SimpleNamespace(fingerprint=catalog.SCHEMA_SHA256),paths[1],**args)
    assert args["legacy_catalog_path"].read_bytes() == original
    assert not args["output_path"].exists() and not args["compatibility_path"].exists()
