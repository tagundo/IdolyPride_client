"""Public scene selections for an explicitly separate, all-unlocked media profile.

These helpers are opt-in policy, not official acquisition-condition evaluation.
They do not write State, create photographs, start a live, or provide resource
bytes. The caller owns keeping the media profile separate from normal play.
"""
from __future__ import annotations

from types import MappingProxyType

from .gameplay import _Catalog
from .photo_shooting import PhotoSceneAccess
from .rpc import RpcCode, RpcFailure


def _need(ok):
    if not ok:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "The media scene master references are unavailable or malformed")


def _text(value):
    return isinstance(value, str) and bool(value)


def _music_rows(catalog):
    """Resolve real photo-list music rows; exclude definitions with no playback."""
    definitions = catalog.ids("Music", required=True)
    photo_musics = catalog.ids("PhotoQuestMusic", required=True)
    available, three_dimensional = {}, set()
    for identity in photo_musics:
        music = definitions.get(identity)
        _need(music is not None)
        is_3d, asset, mv_asset = (music.get("is3dAvailable", False), music.get("assetId", ""),
                                   music.get("mvAssetId", ""))
        _need(type(is_3d) is bool and isinstance(asset, str) and isinstance(mv_asset, str))
        # Original Music.IsMvMusic uses a nonempty mvAssetId; it does not
        # require Is3dAvailable to be false or infer an ID prefix.
        if mv_asset or is_3d and asset:
            available[identity] = music
            if is_3d and asset:
                three_dimensional.add(identity)
    return available, three_dimensional


def prepare_media_scenes(master_dir):
    """Return validated public scene IDs as unlocked in the media profile only.

    Original LivePhotography list models read Photo.ListShooting music unlocks.
    UserMusic alone does not unlock that menu. All IDs below come from real
    master rows; this does not assert that their CDN files are already cached.
    """
    catalog = _Catalog(master_dir)
    _need(bool(catalog.version()))
    stages = catalog.ids("Stage", required=True)

    def stage_exists(identity):
        return _text(identity) and identity in stages and _text(stages[identity].get("assetId"))

    available_music, _ = _music_rows(catalog)
    for music in available_music.values():
        selected = music.get("selectableStageIds", [])
        _need(isinstance(selected, list) and all(stage_exists(identity) for identity in selected))
    activities = catalog.ids("PhotoActivity", required=True)
    expressions = catalog.ids("PhotoExpression", required=True)
    photo_stages = catalog.ids("PhotoQuestStage", required=True)
    for row in [*activities.values(), *expressions.values()]:
        _need(stage_exists(row.get("stageId")))
    for identity, row in photo_stages.items():
        _need(stage_exists(identity) and _text(row.get("assetId")))
    _need(all(type(row.get("type")) is int and row["type"] in (1, 2)
              for row in activities.values()))

    def unlocked(identities):
        return MappingProxyType({identity: True for identity in sorted(identities)})

    return PhotoSceneAccess(activities=unlocked(activities), musics=unlocked(available_music),
                            stages=unlocked(photo_stages), expressions=unlocked(expressions))


def unlock_media_musics(snapshot, master_dir):
    """Append only real, playable 3D photo-list UserMusic IDs and return their count.

    This mutates a supplied User.Get protobuf, not the database. Existing valid
    music rows and all their unknown fields are retained. MV movie rows are
    unlocked through PhotoSceneAccess rather than invented UserMusic records.
    """
    catalog = _Catalog(master_dir)
    _need(bool(catalog.version()) and snapshot.HasField("user"))
    definitions = catalog.ids("Music", required=True)
    _, three_dimensional = _music_rows(catalog)
    owned = set()
    for row in snapshot.musics:
        _need(bool(row.musicId) and row.musicId in definitions and row.musicId not in owned)
        owned.add(row.musicId)
    additions = sorted(three_dimensional - owned)
    for identity in additions:
        snapshot.musics.add(musicId=identity)
    return len(additions)
