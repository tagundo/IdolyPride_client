"""Preserved Dream controls admit latest only with frozen runtime authority."""
from copy import deepcopy
import json
from pathlib import Path

from google.protobuf import message_factory
from google.protobuf.json_format import ParseDict, MessageToDict
import pytest

from idoly_local import dream as module
from idoly_local import public_cohort_support
from idoly_local.live_input import _LATEST_MASTER_VERSION, LatestSemanticsError
from idoly_local.rpc import RpcFailure
from test_dream import game, schema, sql, TOP


def candidate(game,tmp_path):
    latest=tmp_path/"latest"/"master-json";latest.mkdir(parents=True)
    rows=deepcopy(game.rows)
    for table,values in rows.items():
        cls=message_factory.GetMessageClass(game.schema.pool.FindMessageTypeByName("master."+table))
        encoded=[MessageToDict(ParseDict(row,cls()),preserving_proto_field_name=True,
                 use_integers_for_enums=True,always_print_fields_with_no_presence=True) for row in values]
        (latest/(table+".json")).write_text(json.dumps(encoded))
    (latest/"!version.txt").write_text(_LATEST_MASTER_VERSION)
    return latest


def test_pure_dream_receipt_checks_typed_controls_without_authority_or_state_change(game,tmp_path,monkeypatch):
    latest=candidate(game,tmp_path);before=sql(game)
    monkeypatch.setattr(public_cohort_support,"require_master_cohort",lambda *args:(_ for _ in ()).throw(AssertionError("Runtime authority must not be consumed")))
    receipt=module.audit_latest_dream_semantics(game.schema,game.master,latest)
    assert receipt["status"]=="PASS" and receipt["scope"]=="dream"
    assert receipt["projection_equal"] and receipt["external_controls_equal"]
    assert receipt["checks"]["optional_capture_created"] is False
    assert receipt["checks"]["area_16_quests"]==2 and not receipt["state_changed"]
    assert not receipt["runtime_authority_consumed"] and sql(game)==before
    assert not (latest.parent/"dream-catalog.json").exists()


@pytest.mark.parametrize("table,change",[("Setting","setting"),("Condition","condition"),("Item","manual"),
    ("EventMission","mission"),("Area","area"),("Quest","quest")])
def test_dream_changed_dependencies_return_finite_failure_receipt(game,tmp_path,table,change):
    latest=candidate(game,tmp_path);before=sql(game)
    path=latest/(table+".json");rows=json.loads(path.read_bytes())
    if change=="setting":rows[0]["dreamGenerateAreaBasePhotoRequiredRarity"]=3
    elif change=="condition":rows[0]["settings"]=[]
    elif change=="manual":rows[0]["value"]=2
    elif change=="mission":rows[0]["assetId"]="different"
    elif change=="area":rows[0]["questIds"].append("missing")
    else:rows[0]["areaId"]="different"
    path.write_text(json.dumps(rows))
    with pytest.raises(LatestSemanticsError) as stopped:
        module.audit_latest_dream_semantics(game.schema,game.master,latest)
    assert stopped.value.code=="latest_dream_semantics_changed"
    assert stopped.value.receipt["status"]=="FAIL" and len(json.dumps(stopped.value.receipt))<256
    assert sql(game)==before


def test_optional_absence_stays_absent_but_existing_latest_capture_requires_gate(game,tmp_path,monkeypatch):
    latest=candidate(game,tmp_path);before=sql(game);calls=[]
    def denied(*args):calls.append(args);raise ValueError("not pinned")
    monkeypatch.setattr(public_cohort_support,"require_master_cohort",denied)
    provider=module.Dream(game.schema,game.state,"player",latest,clock=game.provider.clock)
    assert provider.home_info() is None and not calls
    saved=json.loads(game.catalog.read_bytes());saved["master_version"]=_LATEST_MASTER_VERSION
    (latest.parent/"dream-catalog.json").write_text(json.dumps(saved))
    with pytest.raises(RpcFailure):provider.handle(TOP,b"")
    assert calls[-1]==(latest,"dream") and sql(game)==before
    monkeypatch.setattr(public_cohort_support,"require_master_cohort",lambda *args:None)
    result=game.schema.response_type(TOP).FromString(provider.handle(TOP,b""))
    assert result.seasonInfo.startTime==module._HOME["startTime"]
    assert result.seasonInfo.endTime==module._HOME["endTime"] and sql(game)==before
