"""Seed one evidenced achievement without replacing existing account state."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import gameplay
from idoly_local.card_level_missions import MISSION_ID
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_starter_roster import NOW, UNKNOWN, roster_master, roster_schema, write_rows


USER = "/api.User/Get"
TABLES = ("profiles", "sessions", "snapshots", "profile_settings", "starter_profiles",
          "profile_lesson_progress", "main_live_attempts")


@pytest.fixture
def mission_schema(roster_schema, tmp_path):
    if "missions" in roster_schema.response_type(USER).DESCRIPTOR.fields_by_name:
        return roster_schema
    # Extend the independent roster contract; the recovered descriptor remains
    # entirely unmodified and runs the same behavioral cases.
    path = tmp_path / "mission-roster.pb"
    roster_schema.export(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    file = descriptors.file[0]
    mission = file.message_type.add(name="StarterMission")
    for number, (name, kind) in enumerate((("missionId", 9), ("currentThreshold", 3),
            ("progress", 3), ("statusType", 5), ("lastUpdateTime", 3)), 1):
        mission.field.add(name=name, number=number, label=1, type=kind)
    for name in ("UserGetResponse", "UpdatedData"):
        next(row for row in file.message_type if row.name == name).field.add(
            name="missions", number=100, label=3, type=11, type_name=".api.StarterMission")
    manager = next(row for row in file.message_type if row.name == "Manager")
    manager.field.add(name="cardSupportLevel", number=100, label=1, type=5)
    path.write_bytes(descriptors.SerializeToString())
    return Schema.from_descriptor_set(path)


@pytest.fixture
def mission_master(roster_master):
    evidence = json.loads((Path(__file__).parent / "fixtures" /
                           "official-card-level-mission.v1.json").read_text())
    write_rows(roster_master, "Mission", [evidence["mission_master"]["card_level_achievement"]])
    write_rows(roster_master, "CardLevel", [
        {"level": level, "requiredExp": str(level - 1)} for level in (1, 2, 5, 10, 20, 41, 42, 50)])
    return roster_master


def dump(state):
    with state.connect() as db:
        return {name: [tuple(row) for row in db.execute("SELECT * FROM " + name + " ORDER BY 1")]
                for name in TABLES}


def master_bytes(master):
    return {path.name: path.read_bytes() for path in master.iterdir() if path.is_file()}


def parsed(state, schema):
    return schema.response_type(USER).FromString(state.snapshot("sandbox")[0])


@pytest.fixture
def old_starter(tmp_path, mission_schema, mission_master):
    state = State(tmp_path / "mission.sqlite")
    raw = gameplay.seed_starter_profile(state, mission_schema, "sandbox", mission_master)
    snapshot = mission_schema.response_type(USER).FromString(raw)
    del snapshot.missions[:]
    snapshot.user.name = "Keep this manager"
    snapshot.user.lastLoginTime += 17
    snapshot.user.cardSupportLevel = 99  # This is not an owned card level.
    snapshot.user.MergeFromString(UNKNOWN)
    snapshot.cards[0].level = snapshot.cards[0].baseLevel = 2
    snapshot.cards[0].MergeFromString(UNKNOWN)
    snapshot.totalCount.loginCount = 7
    snapshot.missions.add(missionId="unrelated-saved-mission", currentThreshold=42,
                          progress=17, statusType=1, lastUpdateTime=NOW - 5).MergeFromString(UNKNOWN)
    state.save_snapshot("sandbox", snapshot.SerializeToString() + UNKNOWN,
                        mission_schema.fingerprint, starter_version=4)
    settings = mission_schema.request_type("/api.Home/Login")().settingInfo
    settings.soundBgm, settings.frameRate = 37, 60
    state.mutate_snapshot("sandbox", mission_schema.fingerprint, lambda raw: raw,
                          setting_info=settings.SerializeToString())
    # The mission migration has no authority to interpret or reset this clock.
    state.mutate_lesson_snapshot("sandbox", mission_schema.fingerprint,
                                lambda raw, _lesson: (raw, b"\x08\x07"))
    token, _ = state.login("sandbox")
    state.save_snapshot("other", b"opaque other snapshot", "other-schema")
    other_token, _ = state.login("other")
    return state, mission_schema, mission_master, token, other_token


def test_fresh_seed_adds_only_the_first_supported_achievement(tmp_path, mission_schema, mission_master, monkeypatch):
    monkeypatch.setattr(gameplay, "_now_ms", lambda: NOW)
    source = master_bytes(mission_master)
    state = State(tmp_path / "new.sqlite")
    raw = gameplay.seed_starter_profile(state, mission_schema, "sandbox", mission_master)
    user = mission_schema.response_type(USER).FromString(raw)
    assert state.starter_version("sandbox") == 5
    assert len(user.missions) == 1
    row = user.missions[0]
    assert (row.missionId, row.currentThreshold, row.progress, row.statusType, row.lastUpdateTime) == (
        MISSION_ID, 5, 1, 1, NOW)
    assert max(card.level for card in user.cards) == 1
    assert master_bytes(mission_master) == source

    # Compare the entire freshly seeded account against the older payload's
    # behavior. The new mission and marker are the only additions.
    mission_file = mission_master / "Mission.json"
    mission_file.unlink()
    legacy = State(tmp_path / "legacy.sqlite")
    old = mission_schema.response_type(USER).FromString(
        gameplay.seed_starter_profile(legacy, mission_schema, "sandbox", mission_master))
    assert legacy.starter_version("sandbox") == 4 and not old.missions
    assert state.profile("sandbox")["server_id"] == user.userPublic.serverUserId
    assert state.profile("sandbox")["public_id"] == user.userPublic.publicUserId
    old.userPublic.CopyFrom(user.userPublic)  # Independently generated local identities.
    del user.missions[:]
    assert user.SerializeToString() == old.SerializeToString()


def test_version4_migration_changes_only_the_mission_and_marker(old_starter, monkeypatch):
    state, schema, master, token, other_token = old_starter
    monkeypatch.setattr(gameplay, "_now_ms", lambda: NOW)
    before = parsed(state, schema)
    tables, source = dump(state), master_bytes(master)
    assert gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    after = parsed(state, schema)
    added = [row for row in after.missions if row.missionId == MISSION_ID]
    assert len(added) == 1
    row = added[0]
    assert (row.currentThreshold, row.progress, row.statusType, row.lastUpdateTime) == (5, 2, 1, NOW)
    assert state.starter_version("sandbox") == 5
    kept = [row for row in after.missions if row.missionId != MISSION_ID]
    del after.missions[:]
    after.missions.extend(kept)
    assert after.SerializeToString() == before.SerializeToString()
    assert UNKNOWN in state.snapshot("sandbox")[0]
    for name in TABLES:
        if name not in ("snapshots", "starter_profiles"):
            assert dump(state)[name] == tables[name]
    assert state.snapshot("other") == (b"opaque other snapshot", "other-schema")
    assert state.starter_version("other") == 0
    assert state.authenticated(token, "sandbox") and state.authenticated(other_token, "other")
    assert master_bytes(master) == source

    migrated = dump(state)
    assert not gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    reopened = State(state.path)
    assert not gameplay.repair_starter_card_level_mission(reopened, schema, "sandbox", master)
    assert dump(reopened) == migrated


@pytest.mark.parametrize("origin", (None, 0, 1, 3, 5, 6))
def test_other_origins_are_not_seeded_or_relabelled(old_starter, origin):
    state, schema, master, token, _ = old_starter
    with state.connect() as db:
        if origin is None:
            db.execute("DELETE FROM starter_profiles WHERE profile='sandbox'")
        else:
            db.execute("UPDATE starter_profiles SET version=? WHERE profile='sandbox'", (origin,))
    before = dump(state)
    assert not gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert dump(state) == before
    assert state.authenticated(token, "sandbox")


@pytest.mark.parametrize("status,threshold,progress", ((1, 50, 41), (2, 20, 41), (3, 20, 41), (4, 20, 41)))
def test_existing_advanced_or_received_row_is_preserved_verbatim(old_starter, status, threshold, progress):
    state, schema, master = old_starter[:3]
    def prepare(raw):
        user = schema.response_type(USER).FromString(raw)
        user.missions.add(missionId=MISSION_ID, currentThreshold=threshold, progress=progress,
                          statusType=status, lastUpdateTime=NOW + 999).MergeFromString(UNKNOWN)
        return user.SerializeToString()
    state.mutate_snapshot("sandbox", schema.fingerprint, prepare)
    before, tables = state.snapshot("sandbox"), dump(state)
    assert gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert state.snapshot("sandbox") == before
    assert state.starter_version("sandbox") == 5
    after = dump(state)
    for name in TABLES:
        if name != "starter_profiles":
            assert after[name] == tables[name]


def test_simultaneous_startup_migrates_once(old_starter):
    state, schema, master = old_starter[:3]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: gameplay.repair_starter_card_level_mission(
            state, schema, "sandbox", master), range(3)))
    assert sorted(results) == [False, False, True]
    assert state.starter_version("sandbox") == 5
    assert sum(row.missionId == MISSION_ID for row in parsed(state, schema).missions) == 1


def test_missing_master_preserves_version4_and_all_existing_state(old_starter):
    state, schema, master = old_starter[:3]
    (master / "Mission.json").unlink()
    before = dump(state)
    assert not gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert dump(state) == before


def test_master_disappearing_during_migration_preserves_origin_and_snapshot(old_starter, monkeypatch):
    from idoly_local import card_level_missions

    state, schema, master = old_starter[:3]
    original = card_level_missions.initialize_mission
    def remove_before_initialization(snapshot, catalog, now):
        (master / "Mission.json").unlink()
        return original(snapshot, catalog, now)
    monkeypatch.setattr(card_level_missions, "initialize_mission", remove_before_initialization)
    before = dump(state)
    assert not gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert state.starter_version("sandbox") == 4
    assert dump(state) == before


def corrupt_master(master, case):
    path = master / "Mission.json"
    if case == "malformed":
        path.write_text("[")
        return
    rows = json.loads(path.read_text())
    if case == "absent-target":
        rows[0]["id"] = "different-mission"
    elif case == "duplicate-target":
        rows.append(rows[0].copy())
    elif case == "conditional":
        rows[0]["viewConditionId"] = "unsupported-condition"
    elif case == "threshold":
        rows[0]["progresses"][0]["threshold"] = "-1"
    else:
        raise AssertionError(case)
    write_rows(master, "Mission", rows)


@pytest.mark.parametrize("case", ("malformed", "absent-target", "duplicate-target", "conditional", "threshold"))
def test_invalid_master_rolls_back_migration_and_creates_no_seed_identity(old_starter, case):
    state, schema, master, token, _ = old_starter
    corrupt_master(master, case)
    before, source = dump(state), master_bytes(master)
    for profile, operation in (("sandbox", gameplay.repair_starter_card_level_mission),
                               ("never-created", gameplay.seed_starter_profile)):
        with pytest.raises(RpcFailure) as error:
            operation(state, schema, profile, master)
        assert error.value.code == RpcCode.FAILED_PRECONDITION
        assert dump(state) == before
    assert state.profile("never-created") is None and state.snapshot("never-created") is None
    assert state.authenticated(token, "sandbox")
    assert master_bytes(master) == source


@pytest.mark.parametrize("case", ("duplicate-mission", "invalid-threshold", "malformed", "no-user"))
def test_invalid_saved_state_never_partially_upgrades(old_starter, case):
    state, schema, master = old_starter[:3]
    def prepare(raw):
        if case == "malformed":
            return b"\xff"
        user = schema.response_type(USER).FromString(raw)
        if case == "no-user":
            user.ClearField("user")
        else:
            target = user.missions.add(missionId=MISSION_ID,
                                      currentThreshold=5 if case == "duplicate-mission" else 6,
                                      progress=2, statusType=1, lastUpdateTime=NOW)
            if case == "duplicate-mission":
                user.missions.add().CopyFrom(target)
        return user.SerializeToString()
    state.mutate_snapshot("sandbox", schema.fingerprint, prepare)
    before = dump(state)
    with pytest.raises(RpcFailure) as error:
        gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(state) == before


def test_marker_write_failure_rolls_back_prepared_mission(old_starter):
    state, schema, master = old_starter[:3]
    with state.connect() as db:
        db.execute("CREATE TRIGGER fail_mission_marker BEFORE UPDATE ON starter_profiles "
                   "WHEN OLD.profile='sandbox' BEGIN SELECT RAISE(ABORT, 'synthetic marker failure'); END")
    before = dump(state)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic marker failure"):
        gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert dump(state) == before


def test_schema_mismatch_or_absent_snapshot_is_untouched(old_starter):
    state, schema, master = old_starter[:3]
    with state.connect() as db:
        db.execute("UPDATE snapshots SET schema_sha256='different-schema' WHERE profile='sandbox'")
    before = dump(state)
    assert not gameplay.repair_starter_card_level_mission(state, schema, "sandbox", master)
    assert not gameplay.repair_starter_card_level_mission(state, schema, "absent", master)
    assert dump(state) == before and state.profile("absent") is None
