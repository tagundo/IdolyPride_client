"""Captured VENUS reads keep private source/account/state boundaries intact."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idoly_local import pvp as module
from idoly_local.live_assets import project_saved_deck_assets
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State
from test_live_assets import game as asset_game

NOW = 1794355200000
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Recovered 6.1.1 schema is not installed")
    return Schema.from_descriptor_set(path)


def record(path, request, response):
    a = request.SerializeToString()
    b = response.SerializeToString()
    return {"method": path, "request_b64": base64.b64encode(a).decode(),
            "request_sha256": hashlib.sha256(a).hexdigest(),
            "response_b64": base64.b64encode(b).decode(),
            "response_sha256": hashlib.sha256(b).hexdigest()}


@pytest.fixture
def game(asset_game, monkeypatch):
    old, state, master, rows, token = asset_game
    schema = old.schema
    monkeypatch.setattr(module, "_now_ms", lambda: NOW)
    rows["Area"].append({"id": "area-main-011", "type": 1, "questIds": ["gate-quest"]})
    rows["Quest"].append({"id": "gate-quest", "areaId": "area-main-011"})
    rows.update({"Stage": [{"id": "battle-stage"}], "Music": [{"id": "battle-music"}],
                 "MusicChartPattern": [{"id": "battle-chart", "number": 1}, {"id": "battle-chart", "number": 2}],
                 "QuestPressure": [{"id": "battle-pressure"}],
                 "QuestAudienceAdvantage": [{"id": "battle-audience", "audienceAmount": 0},
                                              {"id": "battle-audience", "audienceAmount": 10}],
                 "Reward": [{"id": "ranking-reward"}, {"id": "challenge-reward"}]})
    for table, values in rows.items():
        (master / (table + ".json")).write_text(json.dumps(values))
    (master / "!version.txt").write_text("synthetic-pvp-master")
    snapshot = schema.response_type(module._USER).FromString(state.snapshot("player")[0])
    snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId = "owner-server", "owner-public"
    snapshot.user.managerLevel = 42
    snapshot.areas.add(areaId="area-main-011", clearQuestCount=1, lastClearedTime=1)
    snapshot.quests.add(questId="gate-quest", lastClearedTime=1)
    state.save_snapshot("player", snapshot.SerializeToString(), schema.fingerprint,
                        server_id="owner-server", public_id="owner-public")
    state.save_snapshot("other", b"unrelated-private-snapshot", schema.fingerprint)
    state.mutate_snapshot("player", schema.fingerprint, lambda raw: raw, setting_info=b"private-settings")
    state.mutate_lesson_snapshot("player", schema.fingerprint, lambda raw, _: (raw, b"private-clock"))
    # Importing a snapshot deliberately invalidates the old fixture session.
    token, _ = state.login("player")
    top = schema.response_type(module._TOP)()
    result = top.topResult
    season = result.pvpSeason
    season.id, season.name = "synthetic-season", "Synthetic season"
    season.startTime, season.endTime = NOW - 10000, NOW + 10000
    season.aggregateEndTime, season.nextStartTime, season.challengeCount = NOW + 20000, NOW + 30000, 3
    quest = result.pvpQuest
    quest.id, quest.stageId, quest.musicId = "dynamic-battle-not-in-master-quest", "battle-stage", "battle-music"
    quest.musicChartPatternId, quest.questPressureId = "battle-chart", "battle-pressure"
    quest.QuestAudienceAdvantageId, quest.maxCapacity, quest.mentalThreshold = "battle-audience", 10000, 100
    result.userPvpSeason.point, result.userPvpSeason.challengeCount = 234, 1
    result.rank, result.pvpTicketAvailableAmount = 56, 2
    result.pvpRewards.add(rankFrom=1, rankingRewardId="ranking-reward", challengeRewardId="challenge-reward")
    opponent = top.opponentInfos.add(opponentId="synthetic-opponent", name="Private rival label", managerLevel=30, point=345, rank=65)
    for i, name in enumerate("abcde", 1):
        opponent.cardInfos.add(position=i, cardId="card-" + name, level=10, rarity=3)
    top.commonResponse.updatedData.balance.freeBalance = 999999
    top.MergeFromString(UNKNOWN)
    header = schema.response_type(module._QUEST)()
    header.pvpInfo.latestPvpSeason.CopyFrom(season)
    header.pvpInfo.rank, header.pvpInfo.remainingChallengeCount = 55, 2
    tag = schema.response_type(module._MASTER)()
    tag.masterTag.version = "synthetic-pvp-master"
    tag.masterTag.masterTagPacks.add(type="Card", fileName="synthetic.enc", fileSize=1,
        cryptoKey="synthetic-not-a-real-key", downloadUrl="https://climaster.game-idolypride.jp/Card/synthetic.enc")
    assets = schema.response_type(module._ASSET)()
    for name in "abcde":
        for target in (assets.characterAssets, assets.opponentCharacterAssets):
            target.add(characterId="char-" + name, costumeId="cos-" + name + "-default", hairId="hair-" + name + "-default")
    assets.commonResponse.updatedData.user.name = "Stale official update"
    query = schema.request_type(module._ASSET)(pvpSeasonId=season.id, opponentId=opponent.opponentId, deckNumber=1)
    records = [record(module._USER, schema.request_type(module._USER)(), snapshot),
               record(module._MASTER, schema.request_type(module._MASTER)(), tag),
               record(module._QUEST, schema.request_type(module._QUEST)(), header),
               record(module._TOP, schema.request_type(module._TOP)(), top),
               record(module._ASSET, query, assets)]
    data = {"schema": 1, "schema_sha256": schema.fingerprint, "master_version": "synthetic-pvp-master",
            "captured_at_ms": NOW - 1000,
            "owner": {"server_user_id": "owner-server", "public_user_id": "owner-public"}, "responses": records}
    path = master.parent / "pvp-catalog.json"
    path.write_text(json.dumps(data))
    provider = module.Pvp(schema, state, "player", master)
    return SimpleNamespace(provider=provider, schema=schema, state=state, master=master, rows=rows,
                           data=data, path=path, top=top, header=header, assets=assets, token=token)


def write(game):
    game.path.write_text(json.dumps(game.data))


def source_change(game, path, change):
    for i, item in enumerate(game.data["responses"]):
        if item["method"] == path:
            request = game.schema.request_type(path).FromString(base64.b64decode(item["request_b64"]))
            response = game.schema.response_type(path).FromString(base64.b64decode(item["response_b64"]))
            change(request, response)
            game.data["responses"][i] = record(path, request, response)
            write(game)
            return
    raise AssertionError("Synthetic source is absent")


def mutate(game, callback):
    def apply(raw):
        snapshot = game.schema.response_type(module._USER).FromString(raw)
        callback(snapshot)
        return snapshot.SerializeToString()
    game.state.mutate_snapshot("player", game.schema.fingerprint, apply)


def dump(game):
    with game.state.connect() as db:
        return tuple(db.iterdump())


def invoke(game, path=module._TOP, **values):
    request = game.schema.request_type(path)(**values)
    raw = game.provider.handle(path, request.SerializeToString())
    return game.schema.response_type(path).FromString(raw)


def test_top_opponents_and_dynamic_assets_are_private_owned_read_only_projections(game):
    before = dump(game)
    top = invoke(game)
    assert top.topResult == game.top.topResult and top.opponentInfos == game.top.opponentInfos
    assert UNKNOWN in top.SerializeToString() and not top.commonResponse.ListFields()
    opponents = invoke(game, module._OPPONENTS, pvpSeasonId="synthetic-season")
    assert opponents.opponentInfos == game.top.opponentInfos and not opponents.commonResponse.ListFields()
    assets = invoke(game, module._ASSET, pvpSeasonId="synthetic-season", opponentId="synthetic-opponent", deckNumber=1)
    assert all(row.costumeId.endswith("-selected") for row in assets.characterAssets)
    assert assets.opponentCharacterAssets == game.assets.opponentCharacterAssets
    assert not assets.commonResponse.ListFields()
    # Dynamic PvP quest is not forged into Master.Quest merely for projection.
    assert game.top.topResult.pvpQuest.id not in {row["id"] for row in game.rows["Quest"]}
    assert game.provider.quest_top_info(game.schema.response_type(module._USER).FromString(game.state.snapshot("player")[0])) == game.header.pvpInfo
    for _ in range(2):
        assert invoke(game).SerializeToString() == top.SerializeToString()
    restarted = module.Pvp(game.schema, State(game.state.path), "player", game.master)
    assert restarted.handle(module._TOP, b"") == top.SerializeToString()
    assert dump(game) == before and game.state.authenticated(game.token, "player")


def test_top_only_capture_reads_menu_and_list_but_missing_selected_appearance_is_fixed_failure(game):
    game.data["responses"] = [row for row in game.data["responses"] if row["method"] != module._ASSET]
    write(game)
    assert len(game.data["responses"]) == 4
    before = dump(game)
    snapshot_before = game.state.snapshot("player")
    top = invoke(game)
    assert top.topResult == game.top.topResult and top.opponentInfos == game.top.opponentInfos
    assert UNKNOWN in top.SerializeToString() and not top.commonResponse.ListFields()
    opponents = invoke(game, module._OPPONENTS, pvpSeasonId="synthetic-season")
    assert opponents.opponentInfos == game.top.opponentInfos and not opponents.commonResponse.ListFields()
    snapshot = game.schema.response_type(module._USER).FromString(game.state.snapshot("player")[0])
    assert game.provider.quest_top_info(snapshot) == game.header.pvpInfo
    restarted = module.Pvp(game.schema, State(game.state.path), "player", game.master)
    assert restarted.handle(module._TOP, b"") == top.SerializeToString()
    with pytest.raises(RpcFailure) as missing:
        invoke(game, module._ASSET, pvpSeasonId="synthetic-season",
               opponentId="synthetic-opponent", deckNumber=1)
    assert missing.value.code == RpcCode.FAILED_PRECONDITION
    assert missing.value.details == "VENUS capture unavailable: opponent_appearance_missing"
    assert "synthetic-opponent" not in missing.value.details and str(game.path) not in missing.value.details
    with pytest.raises(RpcFailure) as unknown:
        invoke(game, module._ASSET, pvpSeasonId="synthetic-season",
               opponentId="unknown-private-opponent", deckNumber=1)
    assert unknown.value.code == RpcCode.INVALID_ARGUMENT
    assert "unknown-private-opponent" not in unknown.value.details
    assert game.state.snapshot("player") == snapshot_before
    assert dump(game) == before and game.state.authenticated(game.token, "player")


def test_partial_appearance_never_copies_another_opponents_model(game):
    def add_opponent(_request, response):
        added = response.opponentInfos.add()
        added.CopyFrom(response.opponentInfos[0])
        added.opponentId, added.name = "synthetic-second-opponent", "Second private rival"
    source_change(game, module._TOP, add_opponent)
    before = dump(game)
    assert len(invoke(game).opponentInfos) == 2
    assert len(invoke(game, module._OPPONENTS, pvpSeasonId="synthetic-season").opponentInfos) == 2
    first = invoke(game, module._ASSET, pvpSeasonId="synthetic-season",
                   opponentId="synthetic-opponent", deckNumber=1)
    assert first.opponentCharacterAssets == game.assets.opponentCharacterAssets
    with pytest.raises(RpcFailure) as missing:
        invoke(game, module._ASSET, pvpSeasonId="synthetic-season",
               opponentId="synthetic-second-opponent", deckNumber=1)
    assert missing.value.code == RpcCode.FAILED_PRECONDITION
    assert missing.value.details == "VENUS capture unavailable: opponent_appearance_missing"
    assert dump(game) == before


def test_optional_captured_opponent_list_is_available_without_any_appearance(game):
    game.data["responses"] = [row for row in game.data["responses"] if row["method"] != module._ASSET]
    captured = game.schema.response_type(module._OPPONENTS)()
    captured.opponentInfos.extend(game.top.opponentInfos)
    captured.opponentInfos[0].opponentId = "synthetic-list-only-opponent"
    captured.MergeFromString(UNKNOWN)
    captured.commonResponse.updatedData.balance.freeBalance = 999999
    request = game.schema.request_type(module._OPPONENTS)(pvpSeasonId="synthetic-season")
    game.data["responses"].append(record(module._OPPONENTS, request, captured))
    write(game)
    before = dump(game)
    actual = invoke(game, module._OPPONENTS, pvpSeasonId="synthetic-season")
    assert actual.opponentInfos == captured.opponentInfos and UNKNOWN in actual.SerializeToString()
    assert invoke(game).opponentInfos == game.top.opponentInfos
    with pytest.raises(RpcFailure) as missing:
        invoke(game, module._ASSET, pvpSeasonId="synthetic-season",
               opponentId="synthetic-list-only-opponent", deckNumber=1)
    assert missing.value.code == RpcCode.FAILED_PRECONDITION
    assert missing.value.details == "VENUS capture unavailable: opponent_appearance_missing"
    assert not actual.commonResponse.ListFields() and dump(game) == before


@pytest.mark.parametrize("gate", ["owner", "master", "expired", "main11"])
def test_top_only_capture_keeps_account_master_time_and_unlock_gates(game, monkeypatch, gate):
    game.data["responses"] = [row for row in game.data["responses"] if row["method"] != module._ASSET]
    if gate == "owner":
        game.data["owner"]["public_user_id"] = "foreign-private-owner"
    elif gate == "master":
        game.data["master_version"] = "different-master"
    elif gate == "expired":
        monkeypatch.setattr(module, "_now_ms", lambda: NOW + 10001)
    else:
        mutate(game, lambda snapshot: snapshot.quests.clear())
    write(game)
    before = dump(game)
    for path, values in ((module._TOP, {}), (module._OPPONENTS, {"pvpSeasonId": "synthetic-season"})):
        with pytest.raises(RpcFailure) as denied:
            invoke(game, path, **values)
        assert denied.value.code == RpcCode.FAILED_PRECONDITION
        assert "foreign-private-owner" not in denied.value.details
    snapshot = game.schema.response_type(module._USER).FromString(game.state.snapshot("player")[0])
    assert game.provider.quest_top_info(snapshot) is None and dump(game) == before


@pytest.mark.parametrize("kind", ["short", "unknown-opponent", "wrong-season", "bad-deck", "bad-pin"])
def test_any_malformed_captured_appearance_blocks_all_reads_even_for_another_selection(game, kind):
    def add_opponent(_request, response):
        for identity in ("synthetic-second-opponent", "synthetic-missing-appearance"):
            added = response.opponentInfos.add()
            added.CopyFrom(response.opponentInfos[0])
            added.opponentId = identity
    source_change(game, module._TOP, add_opponent)
    request = game.schema.request_type(module._ASSET)(pvpSeasonId="synthetic-season",
        opponentId="synthetic-second-opponent", deckNumber=1)
    response = game.schema.response_type(module._ASSET)()
    response.CopyFrom(game.assets)
    if kind == "short":
        response.opponentCharacterAssets.pop()
    elif kind == "unknown-opponent":
        request.opponentId = "uncaptured-private-opponent"
    elif kind == "wrong-season":
        request.pvpSeasonId = "different-season"
    elif kind == "bad-deck":
        request.deckNumber = 0
    captured = record(module._ASSET, request, response)
    if kind == "bad-pin":
        captured["response_sha256"] = "0" * 64
    game.data["responses"].append(captured)
    write(game)
    before = dump(game)
    for path, values in ((module._TOP, {}),
                         (module._OPPONENTS, {"pvpSeasonId": "synthetic-season"}),
                         (module._ASSET, {"pvpSeasonId": "synthetic-season",
                                         "opponentId": "synthetic-opponent", "deckNumber": 1})):
        with pytest.raises(RpcFailure) as denied:
            invoke(game, path, **values)
        assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game) == before


def test_selected_owned_deck_changes_projection_without_changing_private_opponent(game):
    mutate(game, lambda s: setattr(s.deckPositions[0], "costumeId", "cos-e-live"))
    # Slot5 is e because the shared synthetic input is deliberately unsorted.
    response = invoke(game, module._ASSET, pvpSeasonId="synthetic-season", opponentId="synthetic-opponent", deckNumber=1)
    assert response.characterAssets[4].costumeId == "cos-e-live"
    assert response.opponentCharacterAssets == game.assets.opponentCharacterAssets


@pytest.mark.parametrize("change", [
    lambda g: g.path.unlink(),
    lambda g: g.data.update(schema=2),
    lambda g: g.data.update(schema_sha256="0" * 64),
    lambda g: g.data.update(master_version="other-master"),
    lambda g: g.data["owner"].update(public_user_id="other-account-secret"),
    lambda g: g.data.update(captured_at_ms=NOW + 1),
    lambda g: g.data.update(captured_at_ms=True),
    lambda g: g.data["responses"][0].update(response_sha256="0" * 64),
    lambda g: g.data["responses"][0].update(request_b64="secret-invalid-base64"),
    lambda g: g.data["responses"].append(deepcopy(g.data["responses"][0])),
    lambda g: g.data["responses"].pop(1),
])
def test_missing_future_mismatched_partial_or_unpinned_catalog_fails_without_state_or_identifier_logs(game, change):
    before = dump(game)
    change(game)
    if game.path.exists():
        write(game)
    with pytest.raises(RpcFailure) as error:
        invoke(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert "other-account-secret" not in error.value.details and str(game.path) not in error.value.details
    snapshot = game.schema.response_type(module._USER).FromString(game.state.snapshot("player")[0])
    assert game.provider.quest_top_info(snapshot) is None and dump(game) == before


@pytest.mark.parametrize("part", ["user-owner", "master", "header", "header-name", "no-opponent",
                                  "bad-opponent", "duplicate-card", "appearance", "appearance-order", "expired"])
def test_internally_pinned_but_wrong_source_definitions_are_rejected(game, part, monkeypatch):
    if part == "user-owner":
        source_change(game, module._USER, lambda q, r: setattr(r.userPublic, "serverUserId", "foreign-private-owner"))
    elif part == "master":
        source_change(game, module._MASTER, lambda q, r: r.masterTag.ClearField("masterTagPacks"))
    elif part == "header":
        source_change(game, module._QUEST, lambda q, r: setattr(r.pvpInfo.latestPvpSeason, "id", "different-season"))
    elif part == "header-name":
        source_change(game, module._QUEST, lambda q, r: setattr(r.pvpInfo.latestPvpSeason, "name", "Different season"))
    elif part == "no-opponent":
        source_change(game, module._TOP, lambda q, r: r.ClearField("opponentInfos"))
    elif part == "bad-opponent":
        source_change(game, module._TOP, lambda q, r: setattr(r.opponentInfos[0].cardInfos[0], "cardId", "missing-card"))
    elif part == "duplicate-card":
        source_change(game, module._TOP, lambda q, r: setattr(r.opponentInfos[0].cardInfos[0], "cardId", "card-b"))
    elif part == "appearance":
        source_change(game, module._ASSET, lambda q, r: setattr(r.opponentCharacterAssets[0], "costumeId", "unknown-costume"))
    elif part == "appearance-order":
        def reverse(_query, response):
            assets = list(response.opponentCharacterAssets)
            del response.opponentCharacterAssets[:]
            response.opponentCharacterAssets.extend(reversed(assets))
        source_change(game, module._ASSET, reverse)
    else:
        monkeypatch.setattr(module, "_now_ms", lambda: NOW + 10001)
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        invoke(game)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before
    assert "foreign-private-owner" not in error.value.details


@pytest.mark.parametrize("change", [lambda s: s.areas.clear(), lambda s: s.quests.clear(),
    lambda s: s.ClearField("user"),
    lambda s: setattr(s.areas[0], "clearQuestCount", 0),
    lambda s: setattr(s.userPublic, "publicUserId", "different-local-owner")])
def test_locked_or_partial_current_account_is_not_unlocked_from_other_source(game, change):
    mutate(game, change)
    before = dump(game)
    with pytest.raises(RpcFailure) as failure:
        invoke(game)
    assert failure.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


@pytest.mark.parametrize("path,values", [(module._OPPONENTS, {"pvpSeasonId": "other"}),
    (module._ASSET, {"pvpSeasonId": "synthetic-season", "opponentId": "other-private-id", "deckNumber": 1}),
    (module._ASSET, {"pvpSeasonId": "synthetic-season", "opponentId": "synthetic-opponent", "deckNumber": 0})])
def test_bad_read_selection_is_rejected_without_echoing_account_identifiers(game, path, values):
    before = dump(game)
    with pytest.raises(RpcFailure) as error:
        invoke(game, path, **values)
    assert error.value.code == RpcCode.INVALID_ARGUMENT and dump(game) == before
    assert "other-private-id" not in error.value.details


def test_capture_list_opponent_projection_preserves_unknowns_without_stale_deltas(game):
    response = game.schema.response_type(module._OPPONENTS)()
    response.opponentInfos.extend(game.top.opponentInfos)
    response.MergeFromString(UNKNOWN)
    response.commonResponse.updatedData.balance.freeBalance = 999999
    request = game.schema.request_type(module._OPPONENTS)(pvpSeasonId="synthetic-season")
    game.data["responses"].append(record(module._OPPONENTS, request, response))
    write(game)
    actual = invoke(game, module._OPPONENTS, pvpSeasonId="synthetic-season")
    assert UNKNOWN in actual.SerializeToString() and not actual.commonResponse.ListFields()


def test_write_ranking_ticket_and_future_routes_remain_unhandled(game):
    before = dump(game)
    for path in ("/api.Pvp/Start", "/api.Pvp/ListRanking", "/api.Future/Top"):
        assert game.provider.handle(path, b"") is None
    with pytest.raises(RpcFailure) as bad:
        game.provider.handle(module._TOP, b"\x0a\x80")
    assert bad.value.code == RpcCode.INVALID_ARGUMENT and dump(game) == before


def test_stored_local_identity_must_match_snapshot_and_capture(game):
    with game.state.connect() as db:
        db.execute("UPDATE profiles SET public_id=? WHERE name=?", ("different-private-id", "player"))
    before = dump(game)
    with pytest.raises(RpcFailure) as caught:
        invoke(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION
    assert "different-private-id" not in caught.value.details and dump(game) == before


@pytest.mark.parametrize("content", [b"{", b"[]", b"\xff", b"[" * 2000 + b"]" * 2000,
                                     b" " * (module._MAX_CATALOG + 1)])
def test_malformed_or_oversized_catalog_is_fixed_failure_without_changes(game, content):
    game.path.write_bytes(content)
    before = dump(game)
    with pytest.raises(RpcFailure) as caught:
        invoke(game)
    assert caught.value.code == RpcCode.FAILED_PRECONDITION and dump(game) == before


@pytest.mark.parametrize("kind", ["actual-field", "duplicate-group", "invented-id", "wrong-group-with-id"])
def test_venus_quest_live_bonus_uses_original_master_group_id_read_only(game, kind):
    from google.protobuf import message_factory
    from google.protobuf.json_format import MessageToDict
    evidence = json.loads((Path(__file__).parent / "fixtures/event-read-master-data.v1.json").read_text())
    cls = message_factory.GetMessageClass(game.schema.pool.FindMessageTypeByName("master.LiveBonusGroup"))
    original = cls.FromString(base64.b64decode(evidence["live_bonus_group_sample"]["protobuf_b64"]))
    source_change(game, module._TOP, lambda request, top: setattr(top.topResult.pvpQuest, "liveBonusGroupId", original.groupId))
    rows = [MessageToDict(original, preserving_proto_field_name=True)]
    if kind == "duplicate-group":
        rows.append({"groupId": original.groupId, "liveBonusIds": ["synthetic-second-effect"]})
    elif kind == "invented-id":
        rows = [{"id": original.groupId}]
    elif kind == "wrong-group-with-id":
        rows = [{"id": original.groupId, "groupId": "different-group"}]
    (game.master / "LiveBonusGroup.json").write_text(json.dumps(rows))
    before = dump(game)
    if kind in ("invented-id", "wrong-group-with-id"):
        with pytest.raises(RpcFailure) as failure:
            invoke(game)
        assert failure.value.code == RpcCode.FAILED_PRECONDITION
    else:
        actual = invoke(game)
        assert actual.topResult.pvpQuest.liveBonusGroupId == original.groupId
        assert not actual.commonResponse.ListFields()
    assert dump(game) == before and game.state.authenticated(game.token, "player")
