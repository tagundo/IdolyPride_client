"""Synthetic 360 LIVE lists/checks never create photos or alter an account."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from idoly_local.media_panorama import MediaPanorama, prepare_media_panorama
from idoly_local.panorama_rules import MASTER_PANORAMA_RULES, MASTER_VERSION, PANORAMA_RULES, UNLOCK_CONDITION
from idoly_local.rpc import RpcCode, RpcFailure
from idoly_local.schema import Schema
from idoly_local.state import State


USER = "/api.User/Get"
LIST = "/api.PhotoPanorama/List"
CHECK = "/api.PhotoPanorama/CheckShooting"
CREATE = "/api.PhotoPanorama/CreateShootings"
UNKNOWN = b"\x80\x4b\x7b"


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[1] / "data/protocol/idolypride-6.1.1.pb"
    if not path.is_file():
        pytest.skip("Recovered 6.1.1 descriptor is unavailable")
    return Schema.from_descriptor_set(path)


@pytest.fixture
def game(schema, tmp_path):
    master = tmp_path / "master"
    master.mkdir()
    # Values are synthetic: only the public catalog identities are fixed.
    rows = {
        "Music": [{"id": rule.music_id, "assetId": "asset-" + rule.music_id,
                   "is360LiveExist": True, "displayCharacterAmount": 3 + index % 4}
                  for index, rule in enumerate(PANORAMA_RULES)],
        "Stage": [{"id": identity, "assetId": "asset-" + identity,
                   "cameraPositions": [{"name": "front", "index": 0}]}
                  for identity in sorted({rule.stage_id for rule in PANORAMA_RULES})],
        "Character": [{"id": "char-" + str(index)} for index in range(6)],
        "Costume": [{"id": "costume-" + str(index), "characterId": "char-" + str(index)}
                    for index in range(6)],
        "Hair": [{"id": "hair-" + str(index), "characterId": "char-" + str(index),
                  "wearableCostumeIds": [], "notWearableCostumeIds": []} for index in range(6)],
    }
    rows["Music"].append({"id": "music-hsm-017", "assetId": "asset-music-hsm-017",
        "is360LiveExist": True, "displayCharacterAmount": 5,
        "selectableStageIds": ["stage-live-dome-03-00"], "releaseTime": "1788145200000"})
    rows["Music"].append({"id": "unmapped-panorama", "assetId": "unmapped-real-definition",
                          "is360LiveExist": True, "displayCharacterAmount": 5})
    rows["Costume"].append({"id": "unowned-costume", "characterId": "char-0"})
    rows["Hair"].append({"id": "unowned-hair", "characterId": "char-0"})
    for name, values in rows.items():
        (master / (name + ".json")).write_text(json.dumps(values))
    (master / "!version.txt").write_text(MASTER_VERSION)
    state = State(tmp_path / "media-state.db")
    state.ensure_profile("media")
    snapshot = schema.response_type(USER)()
    snapshot.user.name = "Synthetic media manager"
    snapshot.user.nextPhotoImageIds.append("keep-reservation")
    for index in range(6):
        snapshot.characters.add(characterId="char-" + str(index))
        snapshot.costumes.add(costumeId="costume-" + str(index))
        snapshot.hairs.add(hairId="hair-" + str(index))
    snapshot.items.add(itemId="keep-film", amount=1)
    snapshot.photos.add(photoId="keep-photo", assetId="keep-image", locked=True)
    snapshot.quests.add(questId="keep-progress", lastClearedTime=123)
    snapshot.user.MergeFromString(UNKNOWN)
    snapshot.MergeFromString(UNKNOWN)
    state.save_snapshot("media", snapshot.SerializeToString(), schema.fingerprint)
    state.login("media")
    return MediaPanorama(schema, state, "media", master), state, master, rows


def dump(state):
    with state.connect() as connection:
        return tuple(connection.iterdump())


def call(game, path, **values):
    provider = game[0]
    raw = provider.handle(path, provider.schema.request_type(path)(**values).SerializeToString())
    assert raw is not None
    return provider.schema.response_type(path).FromString(raw)


def cast(game, index=0):
    count = game[3]["Music"][index]["displayCharacterAmount"]
    return {"photoMusicId": (*PANORAMA_RULES, *MASTER_PANORAMA_RULES)[index].music_id,
            "characterIds": ["char-" + str(value) for value in range(count)],
            "costumeIds": ["costume-" + str(value) for value in range(count)],
            "hairIds": ["hair-" + str(value) for value in range(count)]}


def rewrite(game, table, change):
    values = deepcopy(game[3][table])
    change(values)
    (game[2] / (table + ".json")).write_text(json.dumps(values))


def test_list_returns_fifteen_scenes_with_required_unlock_description_and_unrestricted_view_term(game):
    before = dump(game[1])
    result = call(game, LIST)
    assert not (game[2] / "PhotoQuestMusic.json").exists()
    assert len(result.musics) == 15
    assert [(row.musicId, row.stageId, row.order) for row in result.musics] == [
        (rule.music_id, rule.stage_id, rule.order) for rule in (*PANORAMA_RULES, *MASTER_PANORAMA_RULES)]
    for row, rule in zip(result.musics, (*PANORAMA_RULES, *MASTER_PANORAMA_RULES)):
        assert row.isUnlocked and row.assetId == "asset-" + rule.music_id
        assert row.unlockConditionId == UNLOCK_CONDITION
        assert not row.viewConditionId
    assert result.musics[-1].musicId == "music-hsm-017"
    assert "unmapped-panorama" not in {row.musicId for row in result.musics}
    assert not result.dokanInfos
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.SerializeToString() == b""
    assert call(game, LIST) == result
    assert dump(game[1]) == before


@pytest.mark.parametrize("index", [0, 1, 2, 3, 14])
def test_check_uses_exact_music_id_and_master_cast_count_without_music_grants(game, index):
    before = dump(game[1])
    snapshot = game[0].schema.response_type(USER).FromString(game[1].snapshot("media")[0])
    assert not snapshot.musics
    result = call(game, CHECK, **cast(game, index))
    assert result.HasField("commonResponse")
    assert not result.commonResponse.HasField("updatedData")
    assert not result.commonResponse.HasField("deletedData")
    assert result.commonResponse.SerializeToString() == b""
    assert call(game, CHECK, **cast(game, index)) == result
    assert dump(game[1]) == before


@pytest.mark.parametrize("change,code", [
    ({"photoMusicId": "unknown"}, RpcCode.INVALID_ARGUMENT),
    ({"photoMusicId": "unmapped-panorama"}, RpcCode.FAILED_PRECONDITION),
    ({"photoMusicId": ""}, RpcCode.INVALID_ARGUMENT),
    ({"characterIds": []}, RpcCode.INVALID_ARGUMENT),
    ({"characterIds": ["char-0", "char-0", "char-2"]}, RpcCode.INVALID_ARGUMENT),
    ({"hairIds": []}, RpcCode.INVALID_ARGUMENT),
    ({"costumeIds": ["", "costume-1", "costume-2"]}, RpcCode.INVALID_ARGUMENT),
    ({"costumeIds": ["unknown", "costume-1", "costume-2"]}, RpcCode.INVALID_ARGUMENT),
    ({"costumeIds": ["unowned-costume", "costume-1", "costume-2"]}, RpcCode.PERMISSION_DENIED),
    ({"hairIds": ["unowned-hair", "hair-1", "hair-2"]}, RpcCode.PERMISSION_DENIED),
    ({"costumeIds": ["costume-1", "costume-1", "costume-2"]}, RpcCode.INVALID_ARGUMENT),
    ({"hairIds": ["hair-1", "hair-1", "hair-2"]}, RpcCode.INVALID_ARGUMENT),
])
def test_invalid_or_unverified_scene_and_cast_is_rejected_without_state_changes(game, change, code):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        call(game, CHECK, **(cast(game) | change))
    assert error.value.code == code
    assert dump(game[1]) == before


def test_hair_compatibility_is_enforced_without_touching_snapshot(game):
    rewrite(game, "Hair", lambda rows: rows[0].update(notWearableCostumeIds=["costume-0"]))
    before = dump(game[1])
    with pytest.raises(RpcFailure, match="cannot be worn"):
        call(game, CHECK, **cast(game))
    assert dump(game[1]) == before


@pytest.mark.parametrize("table,change", [
    ("Music", lambda rows: rows[0].update(is360LiveExist=False)),
    ("Music", lambda rows: rows[0].update(is360LiveExist=1)),
    ("Music", lambda rows: rows[0].update(assetId="")),
    ("Music", lambda rows: rows[0].update(displayCharacterAmount=True)),
    ("Music", lambda rows: rows[0].update(displayCharacterAmount=0)),
    ("Stage", lambda rows: rows[0].update(cameraPositions=[])),
    ("Stage", lambda rows: rows[0].update(cameraPositions=[None])),
    ("Stage", lambda rows: rows[0].update(cameraPositions=[{}])),
    ("Stage", lambda rows: rows[0].update(cameraPositions=[{"name": "front", "index": True}])),
    ("Stage", lambda rows: rows[0].update(cameraPositions=[{"name": "front", "index": -1}])),
    ("Stage", lambda rows: rows[0].update(cameraPositions=[{"name": "front", "index": 0},
                                                         {"name": "back", "index": 0}])),
    ("Stage", lambda rows: rows[0].update(assetId="")),
])
def test_malformed_public_scene_data_fails_before_db_creation_or_writes(game, table, change):
    before = dump(game[1])
    rewrite(game, table, change)
    with pytest.raises(RpcFailure) as error:
        prepare_media_panorama(game[2])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


@pytest.mark.parametrize("change", [
    {"selectableStageIds": []},
    {"selectableStageIds": ["stage-live-dome-01-00"]},
    {"selectableStageIds": ["stage-live-dome-03-00", "stage-live-dome-01-00"]},
    {"releaseTime": "0"}, {"releaseTime": True},
    {"is360LiveExist": False},
])
def test_master_backed_melodies_requires_its_exact_single_stage_and_original_definition(game, change):
    before = dump(game[1])
    rewrite(game, "Music", lambda rows: next(row for row in rows
        if row["id"] == "music-hsm-017").update(change))
    with pytest.raises(RpcFailure) as error:
        prepare_media_panorama(game[2])
    assert error.value.code == RpcCode.FAILED_PRECONDITION
    assert dump(game[1]) == before


def test_actual_melodies_stage_cast_and_camera_are_master_backed_without_added_photo_masters():
    master = Path(__file__).resolve().parents[1] / "data/master-json"
    if not (master / "Music.json").is_file():
        pytest.skip("Original public master catalog is unavailable")
    scenes = prepare_media_panorama(master)
    assert len(scenes) == 15
    melodies = scenes["music-hsm-017"]
    assert melodies.stage_id == "stage-live-dome-03-00"
    assert melodies.asset_id == "hsm-017" and melodies.cast_count == 5
    assert melodies.order == 15 and not melodies.view_condition_id
    assert len(PANORAMA_RULES) == 14


def test_unlock_reference_has_an_actual_nonempty_condition_description_in_original_master(schema):
    # SetView reads UnlockCondition.Description before checking isUnlocked.
    # A blank (or invented) ID can fail despite the scene being unlocked.
    sqlcipher = pytest.importorskip("sqlcipher3.dbapi2")
    from google.protobuf import message_factory

    archive = Path(__file__).resolve().parents[1] / "data/original-master"
    if not (archive / "master-tag.json").is_file():
        pytest.skip("Original public master archive is unavailable")
    tag = json.loads((archive / "master-tag.json").read_text())
    pack = next(row for row in tag["masterTagPacks"] if row["type"] == "ConditionDescription")
    source = archive / "assets/master" / pack["fileName"]
    if not source.is_file():
        pytest.skip("Original ConditionDescription pack is unavailable")
    connection = sqlcipher.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute('PRAGMA key="x\'' + pack["cryptoKey"] + '\'"')
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute("SELECT data FROM ConditionDescription WHERE Id=?",
                                  (UNLOCK_CONDITION,)).fetchall()
    finally:
        connection.close()
    assert UNLOCK_CONDITION == "cd-tutorial-finish-photo-create-shooting"
    assert len(rows) == 1
    message = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName("master.ConditionDescription"))
    entry = message.FromString(bytes(rows[0][0]))
    assert entry.id == UNLOCK_CONDITION and entry.description == "フォト撮影チュートリアル突破"


def test_master_version_is_pinned_and_constructor_does_not_eagerly_read_it(game):
    (game[2] / "!version.txt").write_text("different-master")
    provider = MediaPanorama(game[0].schema, None, "no-profile", game[2])
    assert provider.handle(CREATE, b"invalid") is None
    assert provider.handle("/unrelated/Method", b"invalid") is None
    with pytest.raises(RpcFailure, match="pinned original"):
        prepare_media_panorama(game[2])


def test_missing_or_invalid_snapshot_and_duplicate_ownership_do_not_mutate_it(game):
    before = dump(game[1])
    missing = MediaPanorama(game[0].schema, game[1], "absent", game[2])
    with pytest.raises(RpcFailure, match="no snapshot"):
        missing.handle(LIST, b"")
    assert dump(game[1]) == before
    snapshot = game[0].schema.response_type(USER).FromString(game[1].snapshot("media")[0])
    snapshot.characters.add().CopyFrom(snapshot.characters[0])
    game[1].save_snapshot("media", snapshot.SerializeToString(), game[0].schema.fingerprint)
    before = dump(game[1])
    with pytest.raises(RpcFailure, match="duplicate"):
        call(game, CHECK, **cast(game))
    assert dump(game[1]) == before


def test_malformed_requests_and_create_never_grant_or_consume_anything(game):
    before = dump(game[1])
    with pytest.raises(RpcFailure) as error:
        game[0].handle(CHECK, b"\x80")
    assert error.value.code == RpcCode.INVALID_ARGUMENT
    assert game[0].handle(CREATE, b"") is None
    assert dump(game[1]) == before
