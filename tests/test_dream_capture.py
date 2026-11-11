"""Pinned private Dream archives replay information without repeating grants."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from idoly_local import event_capture
from idoly_local.dream import Dream, MASTER_VERSION, _CONDITIONS, _HOME
from idoly_local.dream_capture import (DreamCaptureError, HOME, MASTER, MATERIAL,
    QUEST, TOP, USER, build_dream_catalog, read_capture_directory)
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State

CAPTURED, NOW = 1794300000000, 1794350000000
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Original 6.1.1 schema unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def captured(schema, tmp_path, monkeypatch):
    monkeypatch.setattr(event_capture, "_now", lambda: datetime.fromtimestamp(CAPTURED / 1000, timezone.utc))
    state = State(tmp_path / "state.db")
    identity = state.ensure_profile("local")
    snapshot = schema.response_type(USER)()
    snapshot.user.name = "PRIVATE MANAGER"
    snapshot.userPublic.serverUserId = identity["server_id"]
    snapshot.userPublic.publicUserId = identity["public_id"]
    snapshot.profile.favoritePhotoId = "owned-preview"
    snapshot.areas.add(areaId="area-main-016", clearQuestCount=2, lastClearedTime=CAPTURED - 100)
    snapshot.photos.add(photoId="owned-base", rarity=4, level=30, name="PRIVATE BASE LABEL", isDreamBase=True)
    snapshot.photos.add(photoId="owned-preview", rarity=5, level=40, photoRecipeId="recipe")
    snapshot.photos.add(photoId="owned-material", rarity=4, level=20)
    snapshot.items.add(itemId=_HOME["generateAreaItemId"], amount=2)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("local", snapshot.SerializeToString(), schema.fingerprint)
    state.save_snapshot("other", b"unrelated", schema.fingerprint)
    token, _ = state.login("local")
    master = tmp_path / "master-json"
    master.mkdir()
    (master / "!version.txt").write_text(MASTER_VERSION)
    tables = {
        "Condition": [{"id": key, "settings": value} for key, value in _CONDITIONS.items()],
        "Area": [{"id": "area-main-016", "questIds": ["unlock-1", "unlock-2"]}],
        "Quest": [{"id": f"unlock-{number}", "areaId": "area-main-016"} for number in (1, 2)],
        "Item": [{"id": _HOME["generateAreaItemId"]}],
        "PhotoAbility": [{"id": "ability"}],
        "Stage": [{"id": "stage"}], "Music": [{"id": "music"}],
        "MusicChartPattern": [{"id": "chart"}], "QuestPressure": [{"id": "pressure"}],
        "QuestAudienceAdvantage": [{"id": "audience"}],
    }
    for name, values in tables.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    responses = {method: schema.response_type(method)() for method in (MASTER, HOME, TOP, QUEST, MATERIAL)}
    responses[MASTER].masterTag.version = MASTER_VERSION
    responses[HOME].eventInfo.dreamInfo.name = "Actual captured title"
    for key, value in _HOME.items():
        setattr(responses[HOME].eventInfo.dreamInfo, key, value)
    responses[HOME].eventInfo.dreamInfo.isUnlocked = True
    responses[HOME].eventInfo.dreamInfo.isReceivableLoginReward = True
    top = responses[TOP]
    top.seasonInfo.id, top.seasonInfo.name = "captured-season", "Captured Dream season"
    for key in ("startTime", "endTime", "assetId", "generateAreaItemId"):
        setattr(top.seasonInfo, key, _HOME[key])
    top.seasonInfo.eventMissionInfo.id = _HOME["eventMissionId"]
    top.seasonInfo.eventMissionInfo.userMissions.add()
    row = top.dreamUserPhotos.add(photoId="owned-base", generatedTime=CAPTURED - 1000,
        lastChallengedTime=CAPTURED - 100, maxQuestNumber=2, clearQuestNumber=1,
        currentGrowthPermil=10, maxGrowthPermil=100)
    row.abilities.add(photoAbilityId="ability", maxEffectValue=100, totalEnhancedEffectValue=10)
    top.dreamUserPhotos.add(photoId="owned-preview")
    top.dreamUserPhotos.add(photoId="owned-material")
    top.loginRewardResults.add()
    top.dokanInfos.add()
    for response in responses.values():
        if "commonResponse" in response.DESCRIPTOR.fields_by_name:
            response.commonResponse.updatedData.items.add(itemId="DO_NOT_GRANT", amount=99)
            response.commonResponse.deletedData.photos.add(photoId="DO_NOT_DELETE")
        response.MergeFromString(UNKNOWN)
    quests = responses[QUEST]
    quests.maxQuestNumber, quests.clearQuestNumber = 2, 1
    for number in (1, 2):
        quests.questInfos.add(questNumber=number, stageId="stage", musicId="music", musicChartPatternId="chart",
            questPressureId="pressure", questAudienceAdvantageId="audience", maxCapacity=100,
            mentalThreshold=20, clearScore=1000, cleared=number == 1, isPlayable=True, isSkipAvailable=True)
    responses[MATERIAL].userMaterialPhotos.add(photoId="owned-material", maxQuestNumber=2,
        generateAreaItemConsumptionAmount=1, maxGrowthPermil=100)
    directory = tmp_path / "archive"
    archive = event_capture._Archive(schema, directory, "existing-official-session", True)
    archive.record(MASTER, b"", responses[MASTER].SerializeToString())
    initial = type(snapshot)()
    initial.CopyFrom(snapshot)
    initial.user.managerExp = 1
    archive.record(USER, b"", initial.SerializeToString(), purpose="initial-account-snapshot")
    archive.record(HOME, schema.request_type(HOME)(skipUpdate=True).SerializeToString(), responses[HOME].SerializeToString())
    archive.record(TOP, b"", top.SerializeToString(), purpose="normal-menu-visit")
    archive.record(QUEST, schema.request_type(QUEST)(basePhotoId="owned-base").SerializeToString(), quests.SerializeToString())
    archive.record(MATERIAL, schema.request_type(MATERIAL)(basePhotoId="owned-preview").SerializeToString(),
        responses[MATERIAL].SerializeToString())
    final = archive.record(USER, b"", snapshot.SerializeToString(), purpose="final-account-snapshot")
    archive.manifest["consistent_snapshot_record"] = final
    # An unrelated PvP limitation must not discard complete preserved Dream data.
    archive.manifest["limitations"] = ["pvp_season_missing"]
    archive.flush()
    path = tmp_path / "dream-private-catalog.json"
    data = build_dream_catalog(schema, directory, path)
    return SimpleNamespace(schema=schema, state=state, snapshot=snapshot, master=master,
        directory=directory, path=path, data=data, responses=responses, token=token,
        provider=Dream(schema, state, "local", master, clock=lambda: NOW))


def sql(value):
    with value.state.connect() as db:
        return tuple(db.iterdump())


def response(value, method, **request):
    raw = value.provider.handle(method, value.schema.request_type(method)(**request).SerializeToString())
    return value.schema.response_type(method).FromString(raw)


def update(value, callback):
    def mutate(raw):
        snapshot = value.schema.response_type(USER).FromString(raw)
        callback(snapshot)
        return snapshot.SerializeToString()
    value.state.mutate_snapshot("local", value.schema.fingerprint, mutate)


def replace_manifest(value, callback):
    path = value.directory / "manifest.json"
    data = json.loads(path.read_text())
    callback(data)
    path.write_text(json.dumps(data))


def test_converter_retains_final_owned_snapshot_and_private_permissions_without_source_writes(captured):
    before = {p.name: p.read_bytes() for p in captured.directory.iterdir()}
    source = read_capture_directory(captured.schema, captured.directory)
    assert source.final_snapshot.SerializeToString() == captured.snapshot.SerializeToString()
    assert source.owner == (captured.snapshot.userPublic.serverUserId, captured.snapshot.userPublic.publicUserId)
    assert source.master_version == MASTER_VERSION and source.captured_at_ms == CAPTURED
    assert len([row for row in captured.data["responses"] if row["method"] == USER]) == 1
    assert stat.S_IMODE(captured.path.stat().st_mode) == 0o600
    assert {p.name: p.read_bytes() for p in captured.directory.iterdir()} == before
    assert source.records[0].as_catalog_record() == captured.data["responses"][0]


def test_generated_area_and_material_reads_keep_progress_without_transactions_or_gifts(captured):
    before = sql(captured)
    top = response(captured, TOP)
    quests = response(captured, QUEST, basePhotoId="owned-base")
    material = response(captured, MATERIAL, basePhotoId="owned-preview")
    home = captured.provider.home_info()
    assert top.seasonInfo.id == "captured-season" and top.seasonInfo.name == "Captured Dream season"
    assert (top.dreamUserPhotos[0].clearQuestNumber, top.dreamUserPhotos[0].maxQuestNumber) == (1, 2)
    assert top.dreamUserPhotos[0].abilities[0].totalEnhancedEffectValue == 10
    assert all(row.isDisableGenerateArea for row in top.dreamUserPhotos)
    assert [(row.questNumber, row.cleared) for row in quests.questInfos] == [(1, True), (2, False)]
    assert all(not row.isPlayable and not row.isSkipAvailable for row in quests.questInfos)
    assert [row.photoId for row in material.userMaterialPhotos] == ["owned-material"]
    assert home.isUnlocked and not home.isReceivableLoginReward
    assert home.name == "Captured Dream season" and home.endTime == _HOME["endTime"]
    assert not top.loginRewardResults and not top.dokanInfos and not top.seasonInfo.HasField("eventMissionInfo")
    for result in (top, quests, material):
        assert result.HasField("commonResponse") and result.commonResponse.SerializeToString() == b""
        assert UNKNOWN not in result.SerializeToString() and "DO_NOT_GRANT" not in str(result)
    assert sql(captured) == before and captured.state.authenticated(captured.token, "local")
    assert UNKNOWN in captured.state.snapshot("local")[0]


@pytest.mark.parametrize("change", ["owner", "level", "lock", "favorite", "new", "deleted", "unknown"])
def test_private_reads_fail_when_owner_or_any_photo_eligibility_changed(captured, change):
    def edit(snapshot):
        if change == "owner": snapshot.userPublic.serverUserId = "FOREIGN_OWNER"
        elif change == "level": snapshot.photos[-1].level += 1
        elif change == "lock": snapshot.photos[-1].locked = True
        elif change == "favorite": snapshot.profile.favoritePhotoId = "owned-material"
        elif change == "new": snapshot.photos.add(photoId="new-owned", rarity=4)
        elif change == "deleted": del snapshot.photos[-1]
        else: snapshot.photos[-1].MergeFromString(UNKNOWN)
    update(captured, edit)
    before = sql(captured)
    with pytest.raises(RpcFailure) as error:
        response(captured, TOP)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and sql(captured) == before
    assert all(secret not in str(error.value) for secret in ("FOREIGN_OWNER", "PRIVATE BASE LABEL"))


def test_changed_unrelated_resources_do_not_replay_old_account_state(captured):
    update(captured, lambda value: setattr(value.items[0], "amount", 0))
    before = sql(captured)
    assert response(captured, TOP).seasonInfo.id == "captured-season"
    assert sql(captured) == before and captured.state.snapshot("local")[0] != captured.snapshot.SerializeToString()


@pytest.mark.parametrize("change", ["hash", "traversal", "symlink", "missing-final", "foreign-final"])
def test_archive_source_pins_binding_and_paths_are_required(captured, change):
    if change == "hash":
        (captured.directory / "0004.response.pb").write_bytes(b"other")
    elif change == "traversal":
        replace_manifest(captured, lambda value: value["records"][0]["response"].update(file="../secret.pb"))
    elif change == "symlink":
        path = captured.directory / "0004.response.pb"
        raw = path.read_bytes()
        path.unlink()
        external = captured.directory.parent / "external.pb"
        external.write_bytes(raw)
        path.symlink_to(external)
    elif change == "missing-final":
        replace_manifest(captured, lambda value: value.update(consistent_snapshot_record=None))
    else:
        snapshot = type(captured.snapshot)()
        snapshot.CopyFrom(captured.snapshot)
        snapshot.userPublic.publicUserId = "FOREIGN_PRIVATE_ID"
        raw = snapshot.SerializeToString()
        (captured.directory / "0007.response.pb").write_bytes(raw)
        replace_manifest(captured, lambda value: value["records"][-1]["response"].update(
            bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    with pytest.raises(DreamCaptureError) as error:
        build_dream_catalog(captured.schema, captured.directory)
    assert "FOREIGN_PRIVATE_ID" not in str(error.value)


@pytest.mark.parametrize("change", ["schema", "master", "photo-request", "progress", "quest-gap", "foreign-material"])
def test_catalog_rejects_changed_contracts_and_unbound_progress(captured, change):
    data = json.loads(captured.path.read_text())
    if change == "schema": data["schema_sha256"] = "other"
    elif change == "master": data["master_version"] = "other"
    else:
        import base64
        record = next(row for row in data["responses"] if row["method"] == (MATERIAL if change == "foreign-material" else QUEST))
        kind = "request" if change == "photo-request" else "response"
        message = (captured.schema.request_type(record["method"]) if kind == "request"
            else captured.schema.response_type(record["method"])).FromString(base64.b64decode(record[kind + "_b64"]))
        if change == "photo-request": message.basePhotoId = "not-owned"
        elif change == "progress": message.clearQuestNumber = 0
        elif change == "quest-gap": message.questInfos[1].questNumber = 3
        else: message.userMaterialPhotos[0].photoId = "foreign-photo"
        raw = message.SerializeToString()
        record[kind + "_b64"], record[kind + "_sha256"] = base64.b64encode(raw).decode(), hashlib.sha256(raw).hexdigest()
    captured.path.write_text(json.dumps(data))
    before = sql(captured)
    with pytest.raises(RpcFailure) as error:
        response(captured, TOP)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and sql(captured) == before


def test_missing_photo_read_unknown_master_and_mutations_are_not_fabricated(captured):
    before = sql(captured)
    with pytest.raises(RpcFailure): response(captured, MATERIAL, basePhotoId="owned-base")
    for method in ("/api.Dream/GenerateArea", "/api.Dream/StartQuest", "/api.Dream/SkipQuest", "/api.Dream/ResetArea"):
        assert captured.provider.handle(method, b"") is None
    (captured.master / "Music.json").write_text("[]")
    captured.provider = Dream(captured.schema, captured.state, "local", captured.master, clock=lambda: NOW)
    with pytest.raises(RpcFailure): response(captured, QUEST, basePhotoId="owned-base")
    assert sql(captured) == before


def test_archive_expiry_preserves_observed_period_without_clock_shift_or_monthly_reset(captured):
    before = sql(captured)
    captured.provider.clock = lambda: _HOME["endTime"] + 100000
    assert response(captured, TOP).seasonInfo.endTime == _HOME["endTime"]
    assert sql(captured) == before


def test_grouped_chart_and_advantage_master_rows_share_ids_without_rejection(captured):
    for table, identity in (("MusicChartPattern", "chart"), ("QuestAudienceAdvantage", "audience")):
        (captured.master / (table + ".json")).write_text(json.dumps([
            {"id": identity, "position": 1}, {"id": identity, "position": 2}]))
    captured.provider = Dream(captured.schema, captured.state, "local", captured.master, clock=lambda: NOW)
    before = sql(captured)
    assert len(response(captured, QUEST, basePhotoId="owned-base").questInfos) == 2
    assert sql(captured) == before


def change_response(value, method, callback):
    import base64
    data = json.loads(value.path.read_text())
    record = next(row for row in data["responses"] if row["method"] == method)
    message = value.schema.response_type(method).FromString(base64.b64decode(record["response_b64"]))
    callback(message)
    raw = message.SerializeToString()
    record["response_b64"], record["response_sha256"] = base64.b64encode(raw).decode(), hashlib.sha256(raw).hexdigest()
    value.path.write_text(json.dumps(data))


@pytest.mark.parametrize("method", [QUEST, MATERIAL])
def test_dynamic_quest_and_material_ability_references_need_actual_master(captured, method):
    def edit(message):
        if method == QUEST:
            message.questInfos[0].userPhotoAbilityUpInfos.add(photoAbilityId="unknown-ability", upEffectValue=1)
        else:
            message.userMaterialPhotos[0].enhancePlanAbilities.add(photoAbilityId="unknown-ability", maxEffectValue=10)
    change_response(captured, method, edit)
    before = sql(captured)
    with pytest.raises(RpcFailure) as error:
        response(captured, TOP)
    assert error.value.code == RpcCode.FAILED_PRECONDITION and sql(captured) == before


def test_untrusted_large_quest_count_is_rejected_without_allocating_by_count(captured):
    change_response(captured, TOP, lambda top: setattr(top.dreamUserPhotos[0], "maxQuestNumber", 2147483647))
    change_response(captured, QUEST, lambda quests: setattr(quests, "maxQuestNumber", 2147483647))
    before = sql(captured)
    with pytest.raises(RpcFailure): response(captured, TOP)
    assert sql(captured) == before


def test_malformed_json_field_types_use_fixed_errors(captured):
    replace_manifest(captured, lambda value: value.update(mode=[]))
    with pytest.raises(DreamCaptureError) as error:
        read_capture_directory(captured.schema, captured.directory)
    assert error.value.code == "manifest_invalid"
    data = json.loads(captured.path.read_text())
    data["responses"][0]["method"] = []
    captured.path.write_text(json.dumps(data))
    with pytest.raises(RpcFailure) as error: response(captured, TOP)
    assert error.value.code == RpcCode.FAILED_PRECONDITION


@pytest.mark.parametrize("kind", ["actual-field", "duplicate-group", "invented-id", "wrong-group-with-id"])
def test_captured_live_bonus_uses_original_master_group_id_without_state_change(captured, kind):
    import base64
    from google.protobuf import message_factory
    from google.protobuf.json_format import MessageToDict
    evidence = json.loads((Path(__file__).parent / "fixtures/event-read-master-data.v1.json").read_text())
    cls = message_factory.GetMessageClass(captured.schema.pool.FindMessageTypeByName("master.LiveBonusGroup"))
    original = cls.FromString(base64.b64decode(evidence["live_bonus_group_sample"]["protobuf_b64"]))
    change_response(captured, QUEST, lambda value: setattr(value.questInfos[0], "liveBonusGroupId", original.groupId))
    rows = [MessageToDict(original, preserving_proto_field_name=True)]
    if kind == "duplicate-group":
        rows.append({"groupId": original.groupId, "liveBonusIds": ["synthetic-second-effect"]})
    elif kind == "invented-id":
        rows = [{"id": original.groupId}]
    elif kind == "wrong-group-with-id":
        rows = [{"id": original.groupId, "groupId": "different-group"}]
    (captured.master / "LiveBonusGroup.json").write_text(json.dumps(rows))
    before = sql(captured)
    if kind in ("invented-id", "wrong-group-with-id"):
        with pytest.raises(RpcFailure) as failure:
            response(captured, TOP)
        assert failure.value.code == RpcCode.FAILED_PRECONDITION
    else:
        actual = response(captured, QUEST, basePhotoId="owned-base")
        assert actual.questInfos[0].liveBonusGroupId == original.groupId
        assert not actual.commonResponse.ListFields()
    assert sql(captured) == before and captured.state.authenticated(captured.token, "local")


def test_bad_private_bonus_reference_does_not_fall_back_to_available_public_home(captured):
    public = captured.master.parent / "dream-catalog.json"
    public.write_bytes((Path(__file__).parent / "fixtures/dream-public-2026-10.v1.json").read_bytes())
    (captured.master / "Setting.json").write_text(json.dumps([{
        "id": "setting", "dreamAreaName": "イメージトレーニング",
        "dreamGenerateAreaBasePhotoRequiredRarity": 4}]))
    (captured.master / "EventMission.json").write_text(json.dumps([{
        "id": _HOME["eventMissionId"], "viewConditionId": "cd-time-dream-26-10",
        "unlockConditionId": _HOME["unlockConditionId"], "assetId": _HOME["bannerAssetId"]}]))
    area = json.loads((captured.master / "Area.json").read_text())
    area[0]["type"] = 1
    (captured.master / "Area.json").write_text(json.dumps(area))
    public_only = Dream(captured.schema, captured.state, "local", captured.master,
        capture_catalog_path=captured.master.parent / "missing-private.json", clock=lambda: NOW)
    assert public_only.home_info().name == "イメージトレーニング"
    change_response(captured, QUEST, lambda value: setattr(value.questInfos[0], "liveBonusGroupId", "private-group"))
    (captured.master / "LiveBonusGroup.json").write_text(json.dumps([{"id": "private-group"}]))
    before = sql(captured)
    with pytest.raises(RpcFailure) as failure:
        captured.provider.home_info()
    assert failure.value.code == RpcCode.FAILED_PRECONDITION and sql(captured) == before
