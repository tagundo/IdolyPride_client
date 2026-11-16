"""First-three-live controls are typed, additive-only and read-only."""
from copy import deepcopy
import json
from pathlib import Path

from google.protobuf import message_factory
from google.protobuf.json_format import ParseDict, MessageToDict
import pytest

from idoly_local import live_input as module
from idoly_local import public_cohort_support
from idoly_local.master_build import _normalized_row
from idoly_local.schema import Schema
from idoly_local.rpc import RpcFailure
from test_live_input import game


@pytest.fixture(scope="module")
def schema():
    path=Path(__file__).resolve().parents[1]/"data/protocol/idolypride-6.1.1.pb"
    assert path.is_file(),"The original descriptor must be prepared before units"
    return Schema.from_descriptor_set(path)


def candidate(game,tmp_path):
    schema,legacy,rows,snapshot=game
    rows=deepcopy(rows)
    rows["Reward"]=[{"id":definition.reward_id} for definition in module.MAIN_QUEST_DEFINITIONS]
    rows.setdefault("Accessory",[{"id":"ac-1-vocal-02"},{"id":"ac-1-visual-02"}])
    if not any(row["id"]=="item-photo_shooting-01" for row in rows["Item"]):rows["Item"].append({"id":"item-photo_shooting-01"})
    for row in rows["Character"]:
        key=row["id"].removeprefix("char-")
        # Character has costumeIds. Hair membership is represented by the
        # Hair.characterId and Costume.defaultHairId masters, not a hairIds field.
        row["costumeIds"]=["cos-"+key]
    for row in rows["Music"]:row["is3DAvailable"]=True
    for row in rows["Quest"]:
        if "QuestAudienceAdvantageId" in row:row["questAudienceAdvantageId"]=row.pop("QuestAudienceAdvantageId")
        if "QuestCharacterAdvantageId" in row:row["questCharacterAdvantageId"]=row.pop("QuestCharacterAdvantageId")
    latest=tmp_path/"latest"/"master-json";latest.mkdir(parents=True)
    for table,values in rows.items():
        (legacy/(table+".json")).write_text(json.dumps(values))
        descriptor=schema.pool.FindMessageTypeByName("master."+table)
        cls=message_factory.GetMessageClass(descriptor)
        encoded=[MessageToDict(ParseDict(_normalized_row(table,row,descriptor)[0],cls()),
                 preserving_proto_field_name=True,use_integers_for_enums=True,
                 always_print_fields_with_no_presence=True) for row in values]
        (latest/(table+".json")).write_text(json.dumps(encoded))
    (latest/"!version.txt").write_text(module._LATEST_MASTER_VERSION)
    return latest


def test_typed_main_receipt_preserves_snapshot_and_does_not_consume_runtime_authority(game,tmp_path,monkeypatch):
    schema,legacy,rows,snapshot=game;latest=candidate(game,tmp_path);before=snapshot.SerializeToString()
    monkeypatch.setattr(public_cohort_support,"require_master_cohort",lambda *args:(_ for _ in ()).throw(AssertionError("Runtime authority must not be consumed")))
    receipt=module.audit_latest_main_live_semantics(schema,legacy,latest)
    assert receipt["status"]=="PASS" and receipt["scope"]=="main_live"
    assert receipt["checks"]["ruleset"]=="live-v5" and receipt["checks"]["first_quests"]==3
    assert not receipt["runtime_authority_consumed"] and not receipt["state_changed"]
    assert snapshot.SerializeToString()==before


def test_new_card_costume_and_hair_are_additive_without_replacing_old_membership(game,tmp_path):
    schema,legacy,rows,snapshot=game;latest=candidate(game,tmp_path)
    for table,key,identity in (("Card","card-a","card-new"),("Costume","cos-a","cos-new"),("Hair","hair-a","hair-new")):
        path=latest/(table+".json");values=json.loads(path.read_bytes())
        row=deepcopy(next(row for row in values if row["id"]==key));row["id"]=identity;values.append(row)
        path.write_text(json.dumps(values))
    path=latest/"Character.json";values=json.loads(path.read_bytes());owner=next(row for row in values if row["id"]=="char-a")
    owner["costumeIds"].append("cos-new");path.write_text(json.dumps(values))
    receipt=module.audit_latest_main_live_semantics(schema,legacy,latest)
    assert receipt["checks"]["new_cards"]==receipt["checks"]["new_costumes"]==receipt["checks"]["new_hairs"]==1


@pytest.mark.parametrize("table,change",[("Card","card"),("Setting","numeric"),("Skill","skill"),
    ("Character","model"),("Character","membership"),("MusicChartPattern","chart"),("Card","unknown")])
def test_main_changed_old_controls_or_unknown_fields_fail_closed(game,tmp_path,table,change):
    schema,legacy,rows,snapshot=game;latest=candidate(game,tmp_path);before=snapshot.SerializeToString()
    path=latest/(table+".json");values=json.loads(path.read_bytes())
    if change=="card":values[0]["vocalRatioPermil"]+=1
    elif change=="numeric":values[0]["liveMinimumGuaranteedAudienceAmount"]+=1
    elif change=="skill":values[0]["levels"][0]["stamina"]+=1
    elif change=="model":values[0]["characterGroupId"]="different"
    elif change=="membership":values[0]["costumeIds"]=[]
    elif change=="chart":values[0]["number"]+=1000
    else:values[0]["unknownMustNotBeIgnored"]=True
    path.write_text(json.dumps(values))
    with pytest.raises(module.LatestSemanticsError) as stopped:
        module.audit_latest_main_live_semantics(schema,legacy,latest)
    assert stopped.value.receipt["status"]=="FAIL" and stopped.value.code=="latest_main_live_semantics_changed"
    assert snapshot.SerializeToString()==before


def test_latest_runtime_gate_precedes_input_preparation_and_reports_real_version(game,tmp_path,monkeypatch):
    schema,legacy,rows,snapshot=game
    baseline=module.prepare_main_live(schema,legacy,snapshot,module.MAIN_QUEST_ID,1,1)
    latest=candidate(game,tmp_path);before=snapshot.SerializeToString();calls=[]
    def denied(*args):calls.append(args);raise ValueError("unapproved")
    monkeypatch.setattr(public_cohort_support,"require_master_cohort",denied)
    with pytest.raises(RpcFailure):module.prepare_main_live(schema,latest,snapshot,module.MAIN_QUEST_ID,1,1)
    assert calls==[(latest,"main_live")]
    monkeypatch.setattr(public_cohort_support,"require_master_cohort",lambda *args:None)
    prepared=module.prepare_main_live(schema,latest,snapshot,module.MAIN_QUEST_ID,1,1)
    assert prepared["master_version"]==module._LATEST_MASTER_VERSION and snapshot.SerializeToString()==before
    assert prepared["proto"]==baseline["proto"] and prepared["cards"]==baseline["cards"]


@pytest.mark.parametrize("table",["Card","Character","Costume","Hair"])
def test_additive_inventory_never_allows_unknown_fields_to_be_ignored(game,tmp_path,table):
    schema,legacy,rows,snapshot=game;latest=candidate(game,tmp_path)
    path=latest/(table+".json");values=json.loads(path.read_bytes())
    extra=deepcopy(values[0]);extra["id"]="new-additive-record";extra["unknownMustNotBeIgnored"]=True
    values.append(extra);path.write_text(json.dumps(values))
    with pytest.raises(module.LatestSemanticsError) as stopped:
        module.audit_latest_main_live_semantics(schema,legacy,latest)
    assert stopped.value.receipt["status"]=="FAIL" and stopped.value.receipt["reason_code"]=="input_invalid"


def test_hair_allowlist_change_cannot_make_an_old_costume_unwearable(game,tmp_path):
    schema,legacy,rows,snapshot=game;latest=candidate(game,tmp_path)
    path=latest/"Hair.json";values=json.loads(path.read_bytes())
    hair=next(row for row in values if row["id"]=="hair-a")
    hair["wearableCostumeIds"]=["new-only-costume"]
    hair["notWearableCostumeIds"]=[];path.write_text(json.dumps(values))
    with pytest.raises(module.LatestSemanticsError) as stopped:
        module.audit_latest_main_live_semantics(schema,legacy,latest)
    assert stopped.value.receipt["reason_code"]=="main_membership_changed"
