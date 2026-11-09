"""Regression contract for office actors selected outside the five photo idols."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from idoly_local import gameplay
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_gameplay import initial_inventory_rows, synthetic_schema


ROOT = Path(__file__).resolve().parents[1]
PHOTO = ("char-ktn", "char-ngs", "char-mei", "char-suz", "char-ski")
BASELINE = ("char-ai", "char-aoi", "char-chs", "char-hrk", "char-kkr", *PHOTO,
            "char-rei", "char-rio", "char-rui", "char-skr", "char-smr", "char-szk", "char-yu")
LOCKED = ("char-kan", "char-kor", "char-mhk")
UNKNOWN = b"\x80\x4b\x7b"  # Unknown response field 1200, value 123.
NOW = 1794234000000


@pytest.fixture(params=("synthetic", "client-6.1.1"))
def roster_schema(request, tmp_path):
    if request.param == "synthetic":
        return synthetic_schema(tmp_path / "roster.pb")
    descriptor = ROOT / "data/protocol/idolypride-6.1.1.pb"
    if not descriptor.is_file():
        pytest.skip("Optional recovered 6.1.1 descriptor is unavailable; synthetic contract still runs")
    return Schema.from_descriptor_set(descriptor)


def write_rows(directory, name, rows):
    (directory / (name + ".json")).write_text(json.dumps(rows), encoding="utf-8")


@pytest.fixture
def roster_master(tmp_path):
    directory = tmp_path / "master-json"
    directory.mkdir()
    identities = (*BASELINE, *LOCKED, "char-view-gated", "char-npc")
    rows = {
        "Setting": [{"id": 1, "tutorialPhotoShootingCharacterIds": list(PHOTO),
                     "cardDefaultMental": 100, "cardDefaultTechnique": 100}],
        "Character": [], "Costume": [], "Hair": [],
        "CharacterActivityLevel": [{"level": 1, "maxStamina": 800}],
        "Area": [{"id": "area-main-001", "type": 1, "order": 1, "questIds": ["quest-1"]}],
        "Quest": [{"id": "quest-1", "areaId": "area-main-001"}],
        "HierarchyGrade": [{"id": "hie-007"}],
        "HierarchyDetailGrade": [{"id": "hie-007-003", "hierarchyGradeId": "hie-007",
                                  "requiredHierarchyPoint": "0", "requiredHierarchyRank": 0}],
    }
    rows.update(initial_inventory_rows(BASELINE))
    for key in identities:
        rows["Character"].append({"id": key, "type": 2 if key == "char-npc" else 1,
            "viewConditionId": "view-gate" if key == "char-view-gated" else "",
            "unlockConditionId": "owned-gate" if key in LOCKED else "",
            "defaultCostumeId": "cos-" + key, "defaultLiveCostumeId": "live-" + key})
        for prefix in ("cos-", "live-"):
            costume = prefix + key
            rows["Costume"].append({"id": costume, "characterId": key,
                                    "defaultHairId": "hair-" + costume})
            rows["Hair"].append({"id": "hair-" + costume, "characterId": key,
                                 "wearableCostumeIds": [costume]})
    for name, values in rows.items():
        write_rows(directory, name, values)
    return directory


def parse(state, schema, profile="sandbox"):
    return schema.response_type("/api.User/Get").FromString(state.snapshot(profile)[0])


def snapshot_tables(state):
    """Compare the complete existing database rows, including opaque sessions."""
    with state.connect() as db:
        return {name: [tuple(row) for row in db.execute("SELECT * FROM " + name + " ORDER BY 1")]
                for name in ("profiles", "sessions", "snapshots", "profile_settings", "starter_profiles")}


def legacy_profile(state, schema, master, *, version=None, alter=None):
    """Construct the pre-fix five-idol shape independently of the new seeder."""
    characters = {r["id"]: r for r in json.loads((master / "Character.json").read_text())}
    costumes = {r["id"]: r for r in json.loads((master / "Costume.json").read_text())}
    identity = state.ensure_profile("sandbox")
    user = schema.response_type("/api.User/Get")()
    for field in user.DESCRIPTOR.fields:
        if field.message_type is not None and not field.is_repeated:
            getattr(user, field.name).SetInParent()
    user.user.name = "Preserve this manager"
    user.user.managerLevel = 1
    user.user.gameStartTime = NOW
    user.user.lastLoginTime = NOW + 1
    user.user.deckSequence = 1
    user.totalCount.loginCount = 7
    user.hierarchy.bestDetailGradeId = "hie-007-003"
    user.decks.add(number=1, name="Local deck")
    for key in PHOTO:
        row = characters[key]
        default, live = row["defaultCostumeId"], row["defaultLiveCostumeId"]
        hair, live_hair = costumes[default]["defaultHairId"], costumes[live]["defaultHairId"]
        user.characters.add(characterId=key, favoriteCostumeId=default, liveCostumeId=live,
                            favoriteHairId=hair, liveHairId=live_hair, activityLevel=1,
                            activityStamina=800, staminaUpdatedTime=NOW)
        for costume in dict.fromkeys((default, live)):
            user.costumes.add(costumeId=costume, checked=True, obtainedTime=NOW)
        for hair_id in dict.fromkeys((hair, live_hair)):
            user.hairs.add(hairId=hair_id, checked=True)
    for number in (1, 2, 3, 4):
        user.homePositions.add(homePositionType=number, characterId=PHOTO[0])
    user.areas.add(areaId="area-main-001")
    user.tutorials.add(tutorialType=1, step=10)
    user.profile.favoriteCharacterIds.extend(PHOTO)
    user.userPublic.serverUserId = identity["server_id"]
    user.userPublic.publicUserId = identity["public_id"]
    if alter:
        alter(user)
    state.save_snapshot("sandbox", user.SerializeToString() + UNKNOWN, schema.fingerprint, starter_version=1)
    if version is None:
        with state.connect() as db:
            db.execute("DELETE FROM starter_profiles WHERE profile=?", ("sandbox",))
    elif version != 1:
        with state.connect() as db:
            db.execute("UPDATE starter_profiles SET version=? WHERE profile=?", (version, "sandbox"))
    settings = schema.request_type("/api.Home/Login")().settingInfo
    settings.soundBgm = 37
    settings.frameRate = 30
    state.mutate_snapshot("sandbox", schema.fingerprint, lambda payload: payload,
                          setting_info=settings.SerializeToString())
    token, _ = state.login("sandbox")
    return token


def assert_roster(user, master, *, initial_inventory=False):
    assert {row.characterId for row in user.characters} == set(BASELINE)
    assert not (set(LOCKED) & {row.characterId for row in user.characters})
    if initial_inventory:
        reward = next(row for row in json.loads((master / "Reward.json").read_text())
                      if row["id"] == "initial_user_reward")
        expected_cards = [row["resourceId"] for row in reward["resources"] if row["resourceType"] == 2]
        expected_items = {row["resourceId"]: int(row["amount"]) for row in reward["resources"]
                          if row["resourceType"] == 1}
        assert [row.cardId for row in user.cards] == expected_cards
        assert {row.itemId: row.amount for row in user.items} == expected_items
        cards = {row["id"]: row for row in json.loads((master / "Card.json").read_text())}
        assert len(user.deckPositions) == 5
        assert [(row.number, row.position, cards[row.cardId]["characterId"]) for row in user.deckPositions] == [
            (1, number, character) for number, character in enumerate(PHOTO, 1)]
        assert all(row.level == row.baseLevel == row.skillLevel1 == row.baseSkillLevel1 == 1
                   for row in user.cards)
        assert all(row.photoEquipableCount == row.basePhotoEquipableCount == 2 for row in user.cards)
    else:
        assert not user.cards and not user.items and not user.deckPositions
    assert not user.balance.ListFields()
    costumes = {r["id"]: r for r in json.loads((master / "Costume.json").read_text())}
    hairs = {r["id"]: r for r in json.loads((master / "Hair.json").read_text())}
    for row in user.characters:
        for costume_id, hair_id in ((row.favoriteCostumeId, row.favoriteHairId), (row.liveCostumeId, row.liveHairId)):
            assert costumes[costume_id]["characterId"] == row.characterId
            assert hairs[hair_id]["characterId"] == row.characterId
            assert costume_id in {owned.costumeId for owned in user.costumes}
            assert hair_id in {owned.hairId for owned in user.hairs}


def test_fresh_seed_covers_office_roster_and_canonical_inventory_without_currency(tmp_path, roster_schema, roster_master):
    state = State(tmp_path / "state.db")
    payload = gameplay.seed_starter_profile(state, roster_schema, "sandbox", roster_master)
    user = roster_schema.response_type("/api.User/Get").FromString(payload)
    assert_roster(user, roster_master, initial_inventory=True)
    assert set(PHOTO) <= {row.characterId for row in user.characters}
    assert list(user.profile.favoriteCharacterIds) == list(PHOTO)
    assert state.starter_version("sandbox") == 4
    assert gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master) is False


def test_photo_tutorial_identities_must_be_a_subset_of_the_ungated_roster(tmp_path, roster_schema, roster_master):
    write_rows(roster_master, "Setting", [{"id": 1,
        "tutorialPhotoShootingCharacterIds": [LOCKED[0], *PHOTO[1:]]}])
    state = State(tmp_path / "state.db")
    with pytest.raises(RpcFailure) as error:
        gameplay.seed_starter_profile(state, roster_schema, "sandbox", roster_master)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert state.snapshot("sandbox") is None
    assert state.profile("sandbox") is None


@pytest.mark.parametrize("version", [None, 1])
def test_legacy_repair_is_atomic_idempotent_and_preserves_existing_data(tmp_path, roster_schema, roster_master, version):
    state = State(tmp_path / "state.db")
    token = legacy_profile(state, roster_schema, roster_master, version=version)
    before = parse(state, roster_schema)
    old_characters = {row.characterId: row.SerializeToString() for row in before.characters}
    tables = snapshot_tables(state)
    assert gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master) is True
    user = parse(state, roster_schema)
    assert_roster(user, roster_master)
    assert state.starter_version("sandbox") == 2
    for key, payload in old_characters.items():
        assert next(row for row in user.characters if row.characterId == key).SerializeToString() == payload
    for field in ("user", "userPublic", "totalCount", "profile", "hierarchy"):
        assert getattr(user, field).SerializeToString() == getattr(before, field).SerializeToString()
    for field in ("decks", "homePositions", "tutorials", "areas"):
        assert [row.SerializeToString() for row in getattr(user, field)] == [row.SerializeToString() for row in getattr(before, field)]
    assert state.snapshot("sandbox")[0].endswith(UNKNOWN)
    after = snapshot_tables(state)
    for name in ("profiles", "sessions", "profile_settings"):
        assert after[name] == tables[name]
    assert state.authenticated(token, "sandbox")
    assert gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master) is False
    assert snapshot_tables(state) == after


def test_explicit_import_marker_prevents_even_an_identical_legacy_shape_from_being_repaired(tmp_path, roster_schema, roster_master):
    state = State(tmp_path / "state.db")
    legacy_profile(state, roster_schema, roster_master)
    payload, fingerprint = state.snapshot("sandbox")
    state.save_snapshot("sandbox", payload, fingerprint)  # Explicit import, origin/version 0.
    token, _ = state.login("sandbox")
    before = snapshot_tables(state)
    assert state.starter_version("sandbox") == 0
    assert gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master) is False
    assert snapshot_tables(state) == before
    assert state.authenticated(token, "sandbox")


@pytest.mark.parametrize("alter", [
    lambda user: user.cards.add(cardId="imported-card"),
    lambda user: user.decks.add(number=2, name="Existing deck"),
    lambda user: user.profile.favoriteCharacterIds.append("char-ai"),
    lambda user: setattr(user.homePositions[0], "isCharacterRandom", True),
    lambda user: setattr(user.characters[0], "favoriteCostumeId", "unknown-favorite"),
])
def test_untagged_nonstarter_shape_is_never_repaired(tmp_path, roster_schema, roster_master, alter):
    state = State(tmp_path / "state.db")
    legacy_profile(state, roster_schema, roster_master, alter=alter)
    before = snapshot_tables(state)
    assert gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master) is False
    assert snapshot_tables(state) == before


@pytest.mark.parametrize("extra", ["photos", "balance"])
def test_untagged_legacy_with_inventory_or_currency_is_not_a_local_starter(tmp_path, roster_schema, roster_master, extra):
    def with_nonstarter_data(user):
        if extra == "photos":
            user.photos.add(photoId="existing-photo")
        else:
            # Field 1 is freeBalance in 6.1.1; the small synthetic contract
            # preserves it as unknown data, which must also prevent guessing.
            user.balance.MergeFromString(b"\x08\x01")

    state = State(tmp_path / "state.db")
    token = legacy_profile(state, roster_schema, roster_master, alter=with_nonstarter_data)
    before = snapshot_tables(state)
    assert state.starter_version("sandbox") is None
    assert gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master) is False
    assert snapshot_tables(state) == before
    assert state.starter_version("sandbox") is None
    assert state.authenticated(token, "sandbox")


@pytest.mark.parametrize("table,missing", [("Costume", True), ("Costume", False), ("Hair", True), ("Hair", False)])
def test_missing_or_invalid_new_baseline_appearance_rolls_back_the_entire_repair(tmp_path, roster_schema, roster_master, table, missing):
    state = State(tmp_path / "state.db")
    token = legacy_profile(state, roster_schema, roster_master)
    source = roster_master / (table + ".json")
    rows = json.loads(source.read_text())
    identity = "cos-char-ai" if table == "Costume" else "hair-cos-char-ai"
    if missing:
        rows = [row for row in rows if row["id"] != identity]
    else:
        next(row for row in rows if row["id"] == identity)["characterId"] = "char-wrong-owner"
    write_rows(roster_master, table, rows)
    before = snapshot_tables(state)
    with pytest.raises(RpcFailure) as error:
        gameplay.repair_starter_roster(state, roster_schema, "sandbox", roster_master)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert snapshot_tables(state) == before
    assert state.authenticated(token, "sandbox")


def test_actual_611_schema_and_master_define_seventeen_ungated_normal_characters(tmp_path):
    descriptor = ROOT / "data/protocol/idolypride-6.1.1.pb"
    master = Path(os.environ.get("IDOLY_TEST_MASTER_DIR", str(ROOT / "data/master-json")))
    if not descriptor.is_file() or not (master / "Character.json").is_file():
        pytest.skip("Optional actual schema/master unavailable; synthetic roster regressions still run")
    schema = Schema.from_descriptor_set(descriptor)
    characters = json.loads((master / "Character.json").read_text())
    baseline = {row["id"] for row in characters if row.get("type") == 1
                and not row.get("viewConditionId") and not row.get("unlockConditionId")}
    assert baseline == set(BASELINE)
    state = State(tmp_path / "state.db")
    payload = gameplay.seed_starter_profile(state, schema, "actual", master)
    user = schema.response_type("/api.User/Get").FromString(payload)
    assert_roster(user, master, initial_inventory=True)
    assert len(user.cards) == 17
    assert state.starter_version("actual") == 4
