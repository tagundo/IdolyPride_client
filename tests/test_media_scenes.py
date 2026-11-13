"""Explicit media mode derives scene access from real master references only."""
import json

import pytest

from idoly_local.media_scenes import (prepare_media_scenes, unlock_media_musics,
    prepare_media_photo_poses, apply_media_photo_poses)
from idoly_local.rpc import RpcCode, RpcFailure
from test_photo_shooting import schema, UNKNOWN, USER


@pytest.fixture
def master(tmp_path):
    root = tmp_path / "media-master"
    root.mkdir()
    rows = {
        "Music": [
            {"id": "three-d", "is3dAvailable": True, "assetId": "music-three-d", "mvAssetId": "",
             "selectableStageIds": ["stage-live"]},
            {"id": "movie", "is3dAvailable": False, "assetId": "music-movie", "mvAssetId": "movie-asset",
             "selectableStageIds": []},
            {"id": "unavailable", "is3dAvailable": False, "assetId": "", "mvAssetId": "",
             "selectableStageIds": []},
            {"id": "not-in-photo-list", "is3dAvailable": True, "assetId": "outside", "mvAssetId": ""},
        ],
        "Stage": [{"id": "stage-live", "assetId": "live-stage"},
                  {"id": "stage-photo", "assetId": "photo-stage"}],
        "PhotoQuestMusic": [{"id": identity} for identity in ("three-d", "movie", "unavailable")],
        "PhotoQuestStage": [{"id": "stage-live", "assetId": "live-stage"}],
        "PhotoActivity": [{"id": "activity", "type": 1, "stageId": "stage-photo"}],
        "PhotoExpression": [{"id": "expression", "stageId": "stage-photo"}],
    }
    for table, values in rows.items():
        (root / (table + ".json")).write_text(json.dumps(values))
    (root / "!version.txt").write_text("synthetic-media-master")
    return root, rows


def write(master, table):
    (master[0] / (table + ".json")).write_text(json.dumps(master[1][table]))


def test_only_playable_real_scenes_are_unlocked_without_master_or_state_writes(master):
    root, _ = master
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    access = prepare_media_scenes(root)
    assert access.activities == {"activity": True}
    assert access.expressions == {"expression": True}
    assert access.stages == {"stage-live": True}
    assert access.musics == {"movie": True, "three-d": True}
    assert "not-in-photo-list" not in access.musics and "unavailable" not in access.musics
    with pytest.raises(TypeError):
        access.musics["invented"] = True
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_music_ownership_adds_only_photo_list_3d_rows_and_preserves_unknown_fields(schema, master):
    value = schema.response_type(USER)()
    value.user.name = "Media viewer"
    value.photos.add(photoId="kept-photo", rarity=4, locked=True)
    value.balance.freeBalance = 123
    existing = value.musics.add(musicId="movie")
    existing.MergeFromString(UNKNOWN)
    value.MergeFromString(UNKNOWN)
    before = value.SerializeToString()
    expected = schema.response_type(USER).FromString(before)
    expected.musics.add(musicId="three-d")
    assert unlock_media_musics(value, master[0]) == 1
    assert value.SerializeToString() == expected.SerializeToString()
    assert UNKNOWN in value.musics[0].SerializeToString()
    assert unlock_media_musics(value, master[0]) == 0
    assert value.SerializeToString() == expected.SerializeToString()


@pytest.mark.parametrize("kind", ("no-user", "duplicate", "unknown", "empty"))
def test_invalid_media_snapshot_fails_before_any_music_is_added(schema, master, kind):
    value = schema.response_type(USER)()
    if kind != "no-user":
        value.user.name = "Media viewer"
    if kind == "duplicate":
        value.musics.add(musicId="movie")
        value.musics.add(musicId="movie")
    elif kind == "unknown":
        value.musics.add(musicId="unknown-private-music")
    elif kind == "empty":
        value.musics.add()
    before = value.SerializeToString()
    with pytest.raises(RpcFailure) as denied:
        unlock_media_musics(value, master[0])
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert "unknown-private-music" not in denied.value.details
    assert value.SerializeToString() == before


@pytest.mark.parametrize("table,field,value", (
    ("PhotoActivity", "stageId", "unknown-stage"),
    ("PhotoActivity", "type", 3),
    ("PhotoExpression", "stageId", "unknown-stage"),
    ("PhotoQuestStage", "assetId", ""),
    ("Music", "selectableStageIds", ["unknown-stage"]),
    ("Music", "is3dAvailable", 1),
))
def test_bad_scene_references_are_not_replaced_with_invented_definitions(master, table, field, value):
    master[1][table][0][field] = value
    write(master, table)
    before = {p.name: p.read_bytes() for p in master[0].iterdir()}
    with pytest.raises(RpcFailure) as denied:
        prepare_media_scenes(master[0])
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert {p.name: p.read_bytes() for p in master[0].iterdir()} == before


def test_unknown_photo_music_reference_fails_instead_of_manufacturing_a_music(master):
    master[1]["PhotoQuestMusic"].append({"id": "absent-from-music-master"})
    write(master, "PhotoQuestMusic")
    with pytest.raises(RpcFailure):
        prepare_media_scenes(master[0])


@pytest.mark.parametrize("table", ("PhotoActivity", "PhotoQuestMusic", "PhotoQuestStage", "PhotoExpression",
                                  "Music", "Stage"))
def test_incomplete_payload_requires_its_real_scene_tables(master, table):
    (master[0] / (table + ".json")).unlink()
    with pytest.raises(RpcFailure) as denied:
        prepare_media_scenes(master[0])
    assert denied.value.code == RpcCode.FAILED_PRECONDITION


@pytest.fixture
def pose_master(master):
    root, rows = master
    rows.update({
        "Character": [{"id": "char-a"}, {"id": "char-b"}],
        "PhotoPose": [{"id": "pose-a", "poseType": 1, "poseMotionType": 2},
                      {"id": "pose-b", "poseType": 2, "poseMotionType": 2}],
        "PhotoPoseMotion": [
            {"photoPoseId": "pose-a", "characterId": "char-a", "motionAssetId": "motion-a",
             "propAssetIds": []},
            {"photoPoseId": "pose-b", "characterId": "char-b", "motionAssetId": "motion-b",
             "propAssetIds": ["prop-b"]},
        ],
    })
    for table in ("Character", "PhotoPose", "PhotoPoseMotion"):
        write(master, table)
    return master


def test_media_pose_plan_grants_only_real_ids_and_preserves_existing_rows_and_unknown_fields(schema, pose_master):
    before_files = {p.name: p.read_bytes() for p in pose_master[0].iterdir()}
    plan = prepare_media_photo_poses(schema, pose_master[0])
    assert plan.pose_ids == ("pose-a", "pose-b")
    value = schema.response_type(USER)()
    value.user.name = "Media"
    value.balance.freeBalance = 321
    value.photoPoses.add(photoPoseId="pose-a").MergeFromString(UNKNOWN)
    value.photos.add(photoId="kept-photo", locked=True)
    value.MergeFromString(UNKNOWN)
    expected = type(value).FromString(value.SerializeToString())
    expected.photoPoses.add(photoPoseId="pose-b")
    assert apply_media_photo_poses(value, plan)
    assert value.SerializeToString() == expected.SerializeToString()
    assert UNKNOWN in value.photoPoses[0].SerializeToString()
    assert not apply_media_photo_poses(value, plan)
    assert value.SerializeToString() == expected.SerializeToString()
    assert {p.name: p.read_bytes() for p in pose_master[0].iterdir()} == before_files


@pytest.mark.parametrize("kind", ("no-user", "duplicate", "empty", "unknown"))
def test_invalid_existing_pose_inventory_is_rejected_before_any_append(schema, pose_master, kind):
    plan = prepare_media_photo_poses(schema, pose_master[0])
    value = schema.response_type(USER)()
    if kind != "no-user":
        value.user.name = "Media"
    if kind == "duplicate":
        value.photoPoses.add(photoPoseId="pose-a")
        value.photoPoses.add(photoPoseId="pose-a")
    elif kind == "empty":
        value.photoPoses.add()
    elif kind == "unknown":
        value.photoPoses.add(photoPoseId="private-unknown-pose")
    before = value.SerializeToString()
    with pytest.raises(RpcFailure) as denied:
        apply_media_photo_poses(value, plan)
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert "private-unknown-pose" not in denied.value.details
    assert value.SerializeToString() == before


@pytest.mark.parametrize("change", ("missing-pose-table", "missing-motion-table", "duplicate-pose",
    "unknown-pose", "unknown-character", "missing-motion-asset", "duplicate-motion",
    "uncovered-pose", "bad-pose-type", "bad-motion-type", "bad-props"))
def test_pose_plan_rejects_invalid_original_motion_joins(schema, pose_master, change):
    root, rows = pose_master
    if change.startswith("missing-"):
        (root / ("PhotoPose.json" if change == "missing-pose-table" else "PhotoPoseMotion.json")).unlink()
    else:
        if change == "duplicate-pose": rows["PhotoPose"].append(dict(rows["PhotoPose"][0]))
        elif change == "unknown-pose": rows["PhotoPoseMotion"][0]["photoPoseId"] = "unknown"
        elif change == "unknown-character": rows["PhotoPoseMotion"][0]["characterId"] = "unknown"
        elif change == "missing-motion-asset": rows["PhotoPoseMotion"][0]["motionAssetId"] = ""
        elif change == "duplicate-motion": rows["PhotoPoseMotion"].append(dict(rows["PhotoPoseMotion"][0]))
        elif change == "uncovered-pose": rows["PhotoPoseMotion"].pop()
        elif change == "bad-pose-type": rows["PhotoPose"][0]["poseType"] = True
        elif change == "bad-motion-type": rows["PhotoPose"][0]["poseMotionType"] = 999
        elif change == "bad-props": rows["PhotoPoseMotion"][0]["propAssetIds"] = [""]
        write(pose_master, "PhotoPose")
        write(pose_master, "PhotoPoseMotion")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(RpcFailure) as denied:
        prepare_media_photo_poses(schema, root)
    assert denied.value.code == RpcCode.FAILED_PRECONDITION
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
