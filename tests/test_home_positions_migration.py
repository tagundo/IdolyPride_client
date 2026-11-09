"""Only the known repeated fixed starter layout may receive new home IDs."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from idoly_local import gameplay
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_starter_roster import (PHOTO, UNKNOWN, legacy_profile, parse,
                                 roster_master, roster_schema, snapshot_tables)


def old_starter(state, schema, master, *, alter=None):
    """Construct the old five-character layout, then apply only roster repair."""
    token = legacy_profile(state, schema, master, version=1)
    assert gameplay.repair_starter_roster(state, schema, "sandbox", master)
    assert state.starter_version("sandbox") == 2
    if alter is not None:
        def change(payload):
            user = schema.response_type("/api.User/Get").FromString(payload)
            alter(user)
            return user.SerializeToString()
        state.mutate_snapshot("sandbox", schema.fingerprint, change)
    return token


def positions(user):
    return {row.homePositionType: row.characterId for row in user.homePositions}


def test_new_seed_uses_distinct_owned_characters_in_real_home_enum_order(tmp_path, roster_schema, roster_master):
    state = State(tmp_path / "state.db")
    raw = gameplay.seed_starter_profile(state, roster_schema, "sandbox", roster_master)
    user = roster_schema.response_type("/api.User/Get").FromString(raw)
    assert positions(user) == dict(zip((1, 2, 3, 4), PHOTO))
    assert len(set(positions(user).values())) == 4
    assert set(positions(user).values()) <= {row.characterId for row in user.characters}
    assert all(not row.isCharacterRandom and not row.isCostumeRandom for row in user.homePositions)
    assert state.starter_version("sandbox") == 3
    before = snapshot_tables(state)
    assert not gameplay.repair_starter_home_positions(state, roster_schema, "sandbox", roster_master)
    assert snapshot_tables(state) == before


def test_repair_changes_only_three_page_ids_and_origin_preserving_complete_state(tmp_path, roster_schema, roster_master):
    state = State(tmp_path / "state.db")

    def with_existing_progress(user):
        user.user.name = "Existing manager"
        user.tutorials[0].step = 100
        user.totalCount.loginCount = 19
        # Both response-level and nested row unknown fields must survive.
        user.homePositions[2].MergeFromString(UNKNOWN)

    token = old_starter(state, roster_schema, roster_master, alter=with_existing_progress)
    before = parse(state, roster_schema)
    tables = snapshot_tables(state)
    assert positions(before) == {1: PHOTO[0], 2: PHOTO[0], 3: PHOTO[0], 4: PHOTO[0]}
    assert gameplay.repair_starter_home_positions(state, roster_schema, "sandbox", roster_master)
    after = parse(state, roster_schema)
    assert positions(after) == dict(zip((1, 2, 3, 4), PHOTO))
    assert after.homePositions[0].SerializeToString() == before.homePositions[0].SerializeToString()
    # Restore only the expected changed fields to compare every other field,
    # including unknown data and repeated collection order, in one assertion.
    expected_original = roster_schema.response_type("/api.User/Get").FromString(after.SerializeToString())
    for row in expected_original.homePositions:
        row.characterId = PHOTO[0]
    assert expected_original.SerializeToString() == before.SerializeToString()
    assert state.snapshot("sandbox")[0].endswith(UNKNOWN)
    assert after.homePositions[2].SerializeToString().endswith(UNKNOWN)
    changed = snapshot_tables(state)
    for table in ("profiles", "sessions", "profile_settings"):
        assert changed[table] == tables[table]
    assert state.authenticated(token, "sandbox")
    assert state.starter_version("sandbox") == 3
    assert not gameplay.repair_starter_home_positions(state, roster_schema, "sandbox", roster_master)
    assert snapshot_tables(state) == changed


@pytest.mark.parametrize("origin", [0, None, 1, 3, 4])
def test_imports_unmarked_and_other_versions_are_not_reclassified(tmp_path, roster_schema, roster_master, origin):
    state = State(tmp_path / "state.db")
    old_starter(state, roster_schema, roster_master)
    raw, fingerprint = state.snapshot("sandbox")
    if origin is None:
        with state.connect() as db:
            db.execute("DELETE FROM starter_profiles WHERE profile='sandbox'")
    else:
        state.save_snapshot("sandbox", raw, fingerprint, starter_version=origin)
    token, _ = state.login("sandbox")
    before = snapshot_tables(state)
    assert not gameplay.repair_starter_home_positions(state, roster_schema, "sandbox", roster_master)
    assert snapshot_tables(state) == before
    assert state.authenticated(token, "sandbox")


@pytest.mark.parametrize("alter", [
    lambda user: setattr(user.homePositions[0], "characterId", PHOTO[1]),
    lambda user: setattr(user.homePositions[3], "characterId", PHOTO[1]),
    lambda user: setattr(user.homePositions[1], "isCharacterRandom", True),
    lambda user: setattr(user.homePositions[2], "isCostumeRandom", True),
    lambda user: setattr(user.homePositions[3], "homePositionType", 1),
    lambda user: user.homePositions.pop(),
    lambda user: user.homePositions.add(homePositionType=0, characterId=PHOTO[0]),
    lambda user: user.characters.remove(next(row for row in user.characters if row.characterId == PHOTO[3])),
])
def test_custom_random_missing_or_duplicate_position_layouts_are_untouched(tmp_path, roster_schema, roster_master, alter):
    state = State(tmp_path / "state.db")
    token = old_starter(state, roster_schema, roster_master, alter=alter)
    before = snapshot_tables(state)
    assert not gameplay.repair_starter_home_positions(state, roster_schema, "sandbox", roster_master)
    assert snapshot_tables(state) == before
    assert state.authenticated(token, "sandbox")
    assert state.starter_version("sandbox") == 2


@pytest.mark.parametrize("origin", [None, 1])
def test_legacy_roster_then_home_repair_preserves_old_shape_until_explicit_second_step(tmp_path, roster_schema, roster_master, origin):
    state = State(tmp_path / "state.db")
    token = legacy_profile(state, roster_schema, roster_master, version=origin)
    assert gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master)
    assert positions(parse(state, roster_schema)) == {kind: PHOTO[0] for kind in (1, 2, 3, 4)}
    assert state.starter_version("sandbox") == 2
    assert gameplay.repair_starter_home_positions(state, roster_schema, "sandbox", roster_master)
    assert state.starter_version("sandbox") == 3
    assert state.authenticated(token, "sandbox")


def test_marker_write_failure_rolls_back_all_page_changes(tmp_path, roster_schema, roster_master):
    state = State(tmp_path / "state.db")
    token = old_starter(state, roster_schema, roster_master)
    with state.connect() as db:
        db.execute("CREATE TRIGGER fail_home_marker BEFORE UPDATE ON starter_profiles "
                   "BEGIN SELECT RAISE(ABORT, 'synthetic marker failure'); END")
    before = snapshot_tables(state)
    with pytest.raises(sqlite3.IntegrityError):
        gameplay.repair_starter_home_positions(state, roster_schema, "sandbox", roster_master)
    assert snapshot_tables(state) == before
    assert state.authenticated(token, "sandbox")


def test_concurrent_repair_applies_once(tmp_path, roster_schema, roster_master):
    state = State(tmp_path / "state.db")
    old_starter(state, roster_schema, roster_master)
    with ThreadPoolExecutor(max_workers=4) as pool:
        changes = list(pool.map(lambda _: gameplay.repair_starter_home_positions(
            State(state.path), roster_schema, "sandbox", roster_master), range(8)))
    assert changes.count(True) == 1
    assert changes.count(False) == 7
    assert state.starter_version("sandbox") == 3


def test_too_few_distinct_master_characters_fails_before_profile_creation(tmp_path, roster_schema, roster_master):
    selected = list(PHOTO[:3])
    for table, key in (("Character", "id"), ("Costume", "characterId"), ("Hair", "characterId")):
        source = roster_master / (table + ".json")
        rows = [row for row in json.loads(source.read_text()) if row[key] in selected]
        source.write_text(json.dumps(rows))
    (roster_master / "Setting.json").write_text(json.dumps([
        {"id": 1, "tutorialPhotoShootingCharacterIds": selected}]))
    state = State(tmp_path / "state.db")
    with pytest.raises(RpcFailure) as error:
        gameplay.seed_starter_profile(state, roster_schema, "sandbox", roster_master)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert state.profile("sandbox") is None
    assert state.snapshot("sandbox") is None
