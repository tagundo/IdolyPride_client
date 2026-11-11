"""Image-training reads preserve actual owned state and the observed period."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local.dream import Dream, MASTER_VERSION, SCHEMA_SHA256, _CONDITIONS
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State

USER, TOP = "/api.User/Get", "/api.Dream/Top"
UNKNOWN = b"\x80\x4b\x7b"
NOW = 1794350000000


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.exists():
        pytest.skip("Recovered 6.1.1 schema is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    master = tmp_path / "master-json"
    master.mkdir()
    (master / "!version.txt").write_text(MASTER_VERSION)
    rows = {
        "Setting": [{"id": "setting", "dreamAreaName": "イメージトレーニング",
                     "dreamGenerateAreaBasePhotoRequiredRarity": 4}],
        "Item": [{"id": "item-dream-generate-dream-25-0320"}],
        "Condition": [{"id": key, "settings": value} for key, value in _CONDITIONS.items()],
        "EventMission": [{"id": "event-dream-26-10", "viewConditionId": "cd-time-dream-26-10",
                          "unlockConditionId": "cd-dream-25-0320-play",
                          "assetId": "img_banner_l_event-dream-defalut"}],
        "Area": [{"id": "area-main-016", "type": 1, "questIds": ["quest-a", "quest-b"]}],
        "Quest": [{"id": key, "areaId": "area-main-016"} for key in ("quest-a", "quest-b")],
    }
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    catalog = tmp_path / "dream-catalog.json"
    catalog.write_bytes((Path(__file__).parent / "fixtures/dream-public-2026-10.v1.json").read_bytes())
    state = State(tmp_path / "state.db")
    identity = state.ensure_profile("player")
    snapshot = schema.response_type(USER)()
    snapshot.user.name = "Actual local manager"
    snapshot.userPublic.publicUserId = identity["public_id"]
    snapshot.areas.add(areaId="area-main-016", clearQuestCount=2, lastClearedTime=NOW - 100)
    snapshot.photos.add(photoId="owned-low", rarity=3, level=10)
    snapshot.photos.add(photoId="owned-four", rarity=4, level=30, name="PRIVATE PHOTO LABEL")
    snapshot.photos.add(photoId="owned-five", rarity=5, level=40, locked=True)
    snapshot.items.add(itemId="item-dream-generate-dream-25-0320", amount=2)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("player", snapshot.SerializeToString(), schema.fingerprint)
    state.save_snapshot("other", b"unrelated-state", schema.fingerprint)
    token, _ = state.login("player")
    state.mutate_snapshot("player", schema.fingerprint, lambda raw: raw, setting_info=b"private-settings")
    return SimpleNamespace(schema=schema, state=state, master=master, catalog=catalog, rows=rows,
        token=token, provider=Dream(schema, state, "player", master, clock=lambda: NOW))


def sql(game):
    with game.state.connect() as db:
        return tuple(db.iterdump())


def mutate(game, callback):
    def update(raw):
        value = game.schema.response_type(USER).FromString(raw)
        callback(value)
        return value.SerializeToString()
    game.state.mutate_snapshot("player", game.schema.fingerprint, update)


def response(game):
    return game.schema.response_type(TOP).FromString(game.provider.handle(TOP, b""))


def test_top_and_home_show_only_owned_photos_without_private_labels_or_any_state_change(game):
    before = sql(game)
    top = response(game)
    home = game.provider.home_info()
    assert home.name == top.seasonInfo.name == "イメージトレーニング"
    assert home.isUnlocked and not home.isReceivableLoginReward
    assert top.seasonInfo.startTime == home.startTime == 1792033200000
    assert top.seasonInfo.endTime == home.endTime == 1794711599000
    assert home.eventMissionId == "event-dream-26-10"
    assert [(row.photoId, row.isDisableGenerateArea) for row in top.dreamUserPhotos] == [
        ("owned-four", True), ("owned-five", True)]
    assert all(not row.generatedTime and not row.clearQuestNumber and not row.maxQuestNumber
               and not row.abilities for row in top.dreamUserPhotos)
    assert not top.seasonInfo.id and not top.seasonInfo.rankInfos
    assert not top.seasonInfo.HasField("noticeInfo") and not top.seasonInfo.HasField("eventMissionInfo")
    assert not top.loginRewardResults and not top.dokanInfos
    assert "PRIVATE PHOTO LABEL" not in str(top) and "Actual local manager" not in str(top)
    assert sql(game) == before and game.state.authenticated(game.token, "player")
    assert UNKNOWN in game.state.snapshot("player")[0]


def test_locked_account_retains_locked_home_and_cannot_read_top(game):
    mutate(game, lambda value: setattr(value.areas[0], "clearQuestCount", 1))
    before = sql(game)
    assert not game.provider.home_info().isUnlocked
    with pytest.raises(RpcFailure) as failure:
        response(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION and sql(game) == before


def test_expired_catalog_keeps_original_dates_without_november_fallback_or_monthly_grant(game):
    game.provider.clock = lambda: 1796000000000
    before = sql(game)
    top = response(game)
    assert top.seasonInfo.endTime == 1794711599000 and not top.loginRewardResults
    assert not top.seasonInfo.HasField("eventMissionInfo") and sql(game) == before


def test_older_payload_without_catalog_keeps_existing_home_boot_and_no_new_handler(game):
    game.catalog.unlink()
    before = sql(game)
    assert game.provider.home_info() is None and game.provider.handle(TOP, b"") is None
    assert sql(game) == before


@pytest.mark.parametrize("change", ["schema", "master", "source", "dates", "extra-private-field"])
def test_tampered_catalog_is_rejected_without_mutation(game, change):
    data = json.loads(game.catalog.read_text())
    if change == "schema": data["schema_sha256"] = "other"
    elif change == "master": (game.master / "!version.txt").write_text("other")
    elif change == "source": data["source"]["sha256"] = "0" * 64
    elif change == "dates": data["home"]["endTime"] += 1
    else: data["home"]["serverUserId"] = "private"
    game.catalog.write_text(json.dumps(data))
    before = sql(game)
    with pytest.raises(RpcFailure) as failure: response(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION and sql(game) == before


@pytest.mark.parametrize("change", ["generated", "duplicate", "negative"])
def test_unregistered_or_invalid_owned_photo_state_is_not_replaced_with_fake_progress(game, change):
    def update(value):
        if change == "generated": value.photos[1].isDreamBase = True
        elif change == "duplicate": value.photos.add().CopyFrom(value.photos[1])
        else: value.photos[1].level = -1
    mutate(game, update)
    before = sql(game)
    with pytest.raises(RpcFailure) as failure: response(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION and sql(game) == before


def test_bad_condition_and_missing_master_references_fail_closed(game):
    game.rows["Condition"][0]["settings"] = []
    (game.master / "Condition.json").write_text(json.dumps(game.rows["Condition"]))
    before = sql(game)
    with pytest.raises(RpcFailure) as failure: response(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION and sql(game) == before


def test_unsupported_mutations_and_malformed_top_never_write(game):
    before = sql(game)
    for path in ("/api.Dream/GenerateArea", "/api.Dream/StartQuest", "/api.Dream/ResetArea"):
        assert game.provider.handle(path, b"") is None
    with pytest.raises(RpcFailure) as failure: game.provider.handle(TOP, b"\x0a\x80")
    assert failure.value.code == RpcCode.INVALID_ARGUMENT and sql(game) == before
