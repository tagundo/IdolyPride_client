"""The known pre-live empty starter receives its initial inventory once."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from idoly_local import gameplay
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.state import State
from test_starter_roster import (BASELINE, UNKNOWN, roster_master, roster_schema,
                                snapshot_tables)


@pytest.fixture
def old_starter(tmp_path, roster_schema, roster_master):
    state = State(tmp_path / "old.sqlite")
    raw = gameplay.seed_starter_profile(state, roster_schema, "sandbox", roster_master)
    snapshot = roster_schema.response_type("/api.User/Get").FromString(raw)
    # Reconstruct exactly the earlier release's empty initial inventory. The
    # expected post-upgrade fields below are checked separately, never erased
    # from a whole-snapshot comparison without verifying them first.
    del snapshot.cards[:]
    del snapshot.items[:]
    del snapshot.deckPositions[:]
    snapshot.tutorials[0].step = 10
    snapshot.user.name = "Keep this manager"
    snapshot.user.lastLoginTime += 42
    snapshot.totalCount.loginCount = 3
    state.save_snapshot("sandbox", snapshot.SerializeToString() + UNKNOWN,
                        roster_schema.fingerprint, starter_version=3)
    state.login("sandbox")
    settings = roster_schema.request_type("/api.Home/Login")().settingInfo
    settings.frameRate = 60
    state.mutate_snapshot("sandbox", roster_schema.fingerprint, lambda raw: raw,
                          setting_info=settings.SerializeToString())
    return state, roster_schema, roster_master


def parsed(state, schema):
    return schema.response_type("/api.User/Get").FromString(state.snapshot("sandbox")[0])


def test_empty_version3_upgrade_is_complete_atomic_and_idempotent(old_starter):
    state, schema, master = old_starter
    before = parsed(state, schema)
    before_tables = snapshot_tables(state)
    assert gameplay.repair_starter_inventory(state, schema, "sandbox", master)
    after = parsed(state, schema)
    assert state.starter_version("sandbox") == 4
    assert len(after.cards) == len(BASELINE)
    assert all(c.level == c.baseLevel == 1 and c.rarity == 3 and c.skillId1
               and c.skillId1 == c.baseSkillId1 and not c.skillId2
               and not c.baseSkillId2 and c.photoEquipableCount == 2 for c in after.cards)
    assert len(after.items) == 2
    assert len(after.deckPositions) == 5
    assert {p.position for p in after.deckPositions} == set(range(1, 6))
    assert all(p.number == 1 and p.cardId in {c.cardId for c in after.cards}
               for p in after.deckPositions)
    assert len({p.cardId for p in after.deckPositions}) == 5
    del after.cards[:]
    del after.items[:]
    del after.deckPositions[:]
    assert after.SerializeToString() == before.SerializeToString()
    assert UNKNOWN in state.snapshot("sandbox")[0]
    after_tables = snapshot_tables(state)
    for name in ("profiles", "sessions", "profile_settings"):
        assert after_tables[name] == before_tables[name]
    assert not gameplay.repair_starter_inventory(state, schema, "sandbox", master)
    assert snapshot_tables(state) == after_tables
    assert State(state.path).snapshot("sandbox") == state.snapshot("sandbox")


@pytest.mark.parametrize("origin", [None, 0, 1, 2, 4, 5])
def test_other_origins_are_not_granted_inventory(old_starter, origin):
    state, schema, master = old_starter
    state.save_snapshot("sandbox", state.snapshot("sandbox")[0], schema.fingerprint,
                        starter_version=origin)
    before = snapshot_tables(state)
    assert not gameplay.repair_starter_inventory(state, schema, "sandbox", master)
    assert snapshot_tables(state) == before


@pytest.mark.parametrize("change", [
    lambda s: setattr(s.user, "managerLevel", 2),
    lambda s: setattr(s.user, "tutorialClearedTime", 123),
    lambda s: setattr(s.tutorials[0], "step", 100),
    lambda s: setattr(s.tutorials[0], "step", 110),
    lambda s: s.tutorials.add(tutorialType=1, step=10),
    lambda s: setattr(s.decks[0], "name", "Custom unit"),
    lambda s: s.decks.add(number=2, name="Other unit"),
    lambda s: s.cards.add(cardId="custom-card"),
    lambda s: s.items.add(itemId="custom-item", amount=1),
    lambda s: s.deckPositions.add(number=1, position=1, cardId="custom-card"),
    lambda s: s.photos.add(photoId="custom-photo"),
    lambda s: s.accessories.add(accessoryId="custom-accessory", amount=1),
    lambda s: s.balance.MergeFromString(b"\x80\x4b\x01"),
    lambda s: setattr(s.areas[0], "clearQuestCount", 1),
    lambda s: s.quests.add(questId="historical-quest"),
])
def test_custom_inventory_and_progress_are_preserved(old_starter, change):
    state, schema, master = old_starter
    snapshot = parsed(state, schema)
    change(snapshot)
    state.save_snapshot("sandbox", snapshot.SerializeToString(), schema.fingerprint,
                        starter_version=3)
    before = snapshot_tables(state)
    assert not gameplay.repair_starter_inventory(state, schema, "sandbox", master)
    assert snapshot_tables(state) == before


def test_invalid_initial_inventory_leaves_entire_existing_database_unchanged(old_starter):
    state, schema, master = old_starter
    path = master / "Reward.json"
    rows = json.loads(path.read_text())
    reward = next(row for row in rows if row["id"] == "initial_user_reward")
    resource = next(row for row in reward["resources"] if row["resourceType"] == 2)
    resource["resourceId"] = "missing-card"
    path.write_text(json.dumps(rows))
    before = snapshot_tables(state)
    with pytest.raises(RpcFailure) as error:
        gameplay.repair_starter_inventory(state, schema, "sandbox", master)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert snapshot_tables(state) == before


def test_failure_after_preparing_cards_rolls_back_inventory_and_origin(old_starter):
    state, schema, master = old_starter
    path = master / "Setting.json"
    rows = json.loads(path.read_text())
    rows[0]["tutorialPhotoShootingCharacterIds"] = rows[0]["tutorialPhotoShootingCharacterIds"][:4]
    path.write_text(json.dumps(rows))
    before = snapshot_tables(state)
    with pytest.raises(RpcFailure, match="five idols"):
        gameplay.repair_starter_inventory(state, schema, "sandbox", master)
    assert snapshot_tables(state) == before


def test_schema_mismatch_does_not_touch_the_profile(old_starter):
    state, schema, master = old_starter
    state.save_snapshot("sandbox", state.snapshot("sandbox")[0], "other-schema", starter_version=3)
    before = snapshot_tables(state)
    assert not gameplay.repair_starter_inventory(state, schema, "sandbox", master)
    assert snapshot_tables(state) == before


def test_simultaneous_startup_grants_initial_inventory_once(old_starter):
    state, schema, master = old_starter
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: gameplay.repair_starter_inventory(
            state, schema, "sandbox", master), range(2)))
    assert sorted(results) == [False, True]
    user = parsed(state, schema)
    assert len(user.cards) == len({card.cardId for card in user.cards}) == len(BASELINE)
    assert len(user.items) == 2 and len(user.deckPositions) == 5
    assert state.starter_version("sandbox") == 4
