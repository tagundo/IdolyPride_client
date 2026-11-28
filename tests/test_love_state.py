"""Atomic event progress, schema-v2 portability and mode/profile isolation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from idoly_local.state import State, _ACCOUNT_TABLES, _ACCOUNT_TABLES_V1

FP = hashlib.sha256(b"love-state-schema").hexdigest()
RULES = hashlib.sha256(b"love-state-rules").hexdigest()
LOVE = "love-23-0514"
OTHER_LOVE = "love-23-1114"


def progress(n=0,love=LOVE):
    value = {"schema":1,"love_id":love,"player_name":"Love QA","registered_ms":1,"exp":n,
        "lesson_anchor_ms":1,"last_play_ms":2,"path":["love-event-story-"+love+"-001"],
        "choices":{},"past_choices":{},"current":None,"saves":[],"promotion_day":"2026-11-16","promotion_used":0}
    return json.dumps(value,sort_keys=True,indent=1).encode()+b"\n"


def seeded(root,name="state.db"):
    value = State(root/name)
    value.save_snapshot("player",b"0",FP,starter_version=7)
    value.save_snapshot("other",b"unchanged",FP,starter_version=7)
    return value


def test_atomic_mutation_retains_sessions_other_events_profiles_and_media_database(tmp_path):
    state = seeded(tmp_path); media = seeded(tmp_path,"media-state.db")
    token,_ = state.login("player"); other_token,_ = state.login("other")
    before_other = state.account_snapshot("other"); before_media = media.account_snapshot("player")
    assert not state.has_love_progress("player") and state.love_progress("player",LOVE) is None
    assert state.mutate_love_snapshot("player",FP,LOVE,RULES,lambda raw,old:(raw,progress())) == (b"0",progress())
    state.mutate_love_snapshot("player",FP,OTHER_LOVE,RULES,lambda raw,old:(raw,progress(love=OTHER_LOVE)))
    other_event = state.love_progress("player",OTHER_LOVE)
    previous = state.account_snapshot("player")[1]
    def mutate(raw,old):
        assert raw == b"0" and old == progress()
        return b"1",progress(1)
    state.mutate_love_snapshot("player",FP,LOVE,RULES,mutate)
    assert state.snapshot("player") == (b"1",FP) and state.love_progress("player",LOVE) == (progress(1),FP,RULES)
    assert state.account_snapshot("player")[1] != previous and state.has_love_progress("player")
    assert state.love_progress("player",OTHER_LOVE) == other_event
    assert state.account_snapshot("other") == before_other and media.account_snapshot("player") == before_media
    assert state.authenticated(token,"player") and state.authenticated(other_token,"other")


@pytest.mark.parametrize("fault", ["callback","sql","schema","ruleset","oversize"])
def test_mutation_failures_never_partially_write_snapshot_progress_or_sessions(tmp_path,fault):
    state = seeded(tmp_path)
    state.mutate_love_snapshot("player",FP,LOVE,RULES,lambda raw,old:(raw,progress()))
    before = state.account_snapshot("player"); token,_ = state.login("player"); called=[]
    if fault == "sql":
        with state.connect() as db:
            db.execute("CREATE TRIGGER reject_love BEFORE UPDATE ON profile_love_progress "
                       "BEGIN SELECT RAISE(ABORT,'reject Love test update'); END")
    def mutate(raw,old):
        called.append(True)
        if fault == "callback": raise RuntimeError("test callback failed")
        return b"changed", b"x"*(128*1024+1) if fault == "oversize" else progress(1)
    with pytest.raises((RuntimeError,ValueError,sqlite3.IntegrityError)):
        state.mutate_love_snapshot("player","0"*64 if fault == "schema" else FP,LOVE,
            "0"*64 if fault == "ruleset" else RULES,mutate)
    assert state.account_snapshot("player") == before and state.authenticated(token,"player")
    assert bool(called) is (fault not in ("schema","ruleset"))


def test_snapshot_capture_cannot_mix_in_progress_reward_and_user_bytes(tmp_path):
    state = seeded(tmp_path)
    state.mutate_love_snapshot("player",FP,LOVE,RULES,lambda raw,old:(raw,progress()))
    def writer():
        for n in range(1,35):
            state.mutate_love_snapshot("player",FP,LOVE,RULES,lambda raw,old:(str(n).encode(),progress(n)))
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(writer)
        for _ in range(35):
            bundle,revision = state.account_snapshot("player")
            assert bundle["schema"] == 2 and len(bundle["tables"]) == 8
            raw = bundle["tables"]["snapshots"][0]["response"]
            record = bundle["tables"]["profile_love_progress"][0]
            assert int(raw) == json.loads(record["response"])["exp"]
            assert revision == State.account_revision(bundle)
        pending.result()


def test_snapshot_replacement_clears_only_target_event_progress(tmp_path):
    state = seeded(tmp_path)
    for profile in ("player","other"):
        state.mutate_love_snapshot(profile,FP,LOVE,RULES,lambda raw,old:(raw,progress()))
    other = state.account_snapshot("other"); token,_ = state.login("player")
    state.save_snapshot("player",b"new exact snapshot",FP)
    assert state.love_progress("player",LOVE) is None and not state.has_love_progress("player")
    assert state.account_snapshot("other") == other and not state.authenticated(token,"player")


def test_v1_bundle_shape_stays_strict_and_upgrade_never_invents_love(tmp_path):
    state = seeded(tmp_path)
    current,revision = state.account_snapshot("player")
    legacy = {"schema":1,"profile":"player","tables":{name:deepcopy(current["tables"][name])
        for name,_columns,_keys in _ACCOUNT_TABLES_V1}}
    old_revision = State.account_revision(legacy)
    upgraded = State.upgrade_account(legacy)
    assert old_revision != revision and upgraded == current and legacy["schema"] == 1
    assert len(legacy["tables"]) == 7 and upgraded["tables"]["profile_love_progress"] == []
    state.replace_account("from-old",legacy)
    assert state.account_snapshot("from-old")[0]["schema"] == 2
    invalid = deepcopy(current);invalid["schema"] = 1
    with pytest.raises(ValueError,match="bundle_schema_invalid"): State.upgrade_account(invalid)
    invalid = deepcopy(legacy);invalid["schema"] = 2
    with pytest.raises(ValueError,match="bundle_schema_invalid"): State.upgrade_account(invalid)


def test_old_database_migration_retains_every_original_table_and_session(tmp_path):
    state = seeded(tmp_path); token,_ = state.login("player")
    before,revision = state.account_snapshot("player")
    with state.connect() as db: db.execute("DROP TABLE profile_love_progress")
    reopened = State(tmp_path/"state.db")
    assert reopened.account_snapshot("player") == (before,revision)
    assert reopened.authenticated(token,"player") and reopened.love_progress("player",LOVE) is None


@pytest.mark.parametrize("field,value", [("love_id","../escape"),("ruleset_sha256","f"*63),("response",b"x"*(128*1024+1))])
def test_opaque_row_bounds_and_fingerprints_are_checked_before_portability(tmp_path,field,value):
    state = seeded(tmp_path)
    state.mutate_love_snapshot("player",FP,LOVE,RULES,lambda raw,old:(raw,progress()))
    with state.connect() as db: db.execute("UPDATE profile_love_progress SET "+field+"=? WHERE profile='player'",(value,))
    with pytest.raises(ValueError): state.account_snapshot("player")
    if field == "response":
        with pytest.raises(ValueError,match="progress_bound"): state.love_progress("player",LOVE)
