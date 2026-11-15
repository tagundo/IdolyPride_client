"""Photo scene checks and image reservations without fabricated photographs.

The 6.1.1 protocol separates scene unlocks, reserved upload IDs and UserPhoto
records.  A master scene is not proof of normal-profile ownership and an upload
ID is not an image. Callers provide scene access from preserved ownership or
an explicit separate media-mode policy, and finalized image URLs.
Creation remains blocked until the local upload/generation flow is available;
this module never consumes film or creates a placeholder PhotoImageType.User.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import re
from types import SimpleNamespace
from uuid import uuid4

from google.protobuf.message import DecodeError

from .appearance import _owned
from .gameplay import _Catalog
from .live_assets import _wearable
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_LIST = "/api.Photo/ListShooting"
_CHECK = "/api.Photo/CheckShooting"
_EXPRESSION_CHECK = "/api.Photo/CheckExpressionShooting"
_CREATE = "/api.Photo/CreateShootings"
_URL = "/api.Photo/GetImageURL"
_ROUTES = frozenset((_LIST, _CHECK, _EXPRESSION_CHECK, _CREATE, _URL))
_SAFE_IMAGE_ID = re.compile(r"[A-Za-z0-9_.~-]{1,251}\Z")
_SAFE_MASTER_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_DIAGNOSTIC_REQUEST_BYTES = 64 * 1024
_DIAGNOSTIC_MASTER_BYTES = 1024 * 1024
_EXPRESSION_REJECTION_REASONS = {
    (RpcCode.INVALID_ARGUMENT, "A photo expression ID is required"): "expression_missing",
    (RpcCode.INVALID_ARGUMENT, "Unknown local photo expression"): "expression_unknown",
    (RpcCode.INVALID_ARGUMENT, "Conflicting photo expression style selections"): "legacy_conflict",
    (RpcCode.INVALID_ARGUMENT, "The selected cast count exceeds this photo expression's capacity"): "cast_capacity",
    (RpcCode.INVALID_ARGUMENT, "The photo expression roster must contain one to five characters"): "cast_capacity",
    (RpcCode.INVALID_ARGUMENT, "Matching nonempty photo character/style lists are required"): "style_shape",
    (RpcCode.INVALID_ARGUMENT, "Unknown photo character or outfit"): "style_unknown",
    (RpcCode.INVALID_ARGUMENT, "Photo character and outfit do not match"): "style_owner",
    (RpcCode.INVALID_ARGUMENT, "The photo hair cannot be worn with this costume"): "hair_incompatible",
    (RpcCode.INVALID_ARGUMENT, "The photo activity does not allow this character or costume"): "scene_restricted",
    (RpcCode.PERMISSION_DENIED, "The photo expression is not owned and unlocked"): "expression_locked",
    (RpcCode.PERMISSION_DENIED, "The photo character or outfit is not owned"): "style_unowned",
    (RpcCode.FAILED_PRECONDITION, "The photo expression stage or cast definition is malformed"): "expression_master_invalid",
    (RpcCode.FAILED_PRECONDITION, "Photo activity style restrictions are malformed"): "style_restrictions_invalid",
    (RpcCode.INVALID_ARGUMENT, "Malformed photo request"): "request_malformed",
    (RpcCode.INVALID_ARGUMENT, "Malformed encrypted protobuf request"): "request_malformed",
}
RESERVED_IMAGE_COUNT = 20
MAX_EXPRESSION_ROSTER = 5
_MV_SCENE = object()


def _fail(message, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, message)


def valid_image_id(value):
    return isinstance(value, str) and value not in (".", "..") and bool(_SAFE_IMAGE_ID.fullmatch(value))


def reserve_photo_image_ids(user, *, id_factory=lambda: str(uuid4())):
    """Fill the native client's upload reservations, preserving all existing IDs.

    This operates on a protobuf User only.  Persist it in the caller's existing
    snapshot transaction and return updatedData.user if it changed.  Reservation
    creates no image, photo, film or scene unlock.  The deprecated single ID and
    imported arrays longer than twenty are deliberately retained.
    """
    current = list(user.nextPhotoImageIds)
    if any(not valid_image_id(value) for value in current) or len(set(current)) != len(current):
        _fail("Photo image reservations are malformed")
    if len(current) >= RESERVED_IMAGE_COUNT:
        return False
    seen = set(current)
    # UUID collisions should be exceptional. A bounded loop also makes a broken
    # injected generator fail before touching the caller's User.
    additions = []
    for _ in range(RESERVED_IMAGE_COUNT * 4):
        candidate = id_factory()
        if not valid_image_id(candidate):
            _fail("Photo reservation generator returned an invalid image ID")
        if candidate not in seen:
            seen.add(candidate)
            additions.append(candidate)
            if len(current) + len(additions) == RESERVED_IMAGE_COUNT:
                user.nextPhotoImageIds.extend(additions)
                return True
    _fail("Photo reservation generator could not produce unique image IDs")


@dataclass(frozen=True)
class PhotoSceneAccess:
    """Explicit per-profile scene access, including locked rows.

    IDs use the native API names: activities and expressions use their photo
    IDs, musics use musicId, and stages use stageId. This value object infers
    nothing. Normal profiles use preserved access; a separately enabled media
    profile may supply an explicit all-unlocked public-master policy.
    """
    activities: Mapping[str, bool] = field(default_factory=dict)
    musics: Mapping[str, bool] = field(default_factory=dict)
    stages: Mapping[str, bool] = field(default_factory=dict)
    expressions: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class PhotoExpressionRejectionFacts:
    """Finite counts and public master IDs retained for one failed request."""

    counts: tuple[int, int, int]
    legacy: tuple[bool, bool, bool]
    expression: str
    characters: tuple[str, ...]
    costumes: tuple[str, ...]
    hairs: tuple[str, ...]


class PhotoShootings:
    """Read/check photo endpoints; unsupported creation fails before any writes.

    ``scene_access`` may be a PhotoSceneAccess or a callback accepting the local
    profile name and returning one.  ``image_urls(profile, asset_id)`` must return
    (original_url, thumbnail_url) for a finalized image owned by that profile,
    or None.  A missing original image must not be replaced with a stock asset.
    """

    def __init__(self, schema, state, profile, master_dir=None, *, scene_access=None, image_urls=None,
                 media_mode=False, media_settings=None):
        if type(media_mode) is not bool:
            raise ValueError("Media mode must be an explicit boolean")
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self.scene_access = scene_access
        self.image_urls = image_urls
        self.media_mode = media_mode
        self.media_settings = media_settings

    def _snapshot(self):
        stored = self.state.snapshot(self.profile)
        if stored is None or stored[1] != self.schema.fingerprint:
            _fail("Local photo profile has no snapshot for this schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(stored[0])
        except DecodeError:
            _fail("Local photo snapshot is malformed")
        if not snapshot.HasField("user"):
            _fail("Local photo profile has no user state")
        return snapshot

    def _access(self):
        access = self.scene_access(self.profile) if callable(self.scene_access) else self.scene_access
        if not isinstance(access, PhotoSceneAccess):
            _fail("Preserved photo scene unlocks are unavailable locally")
        for name in ("activities", "musics", "stages", "expressions"):
            entries = getattr(access, name)
            if (not isinstance(entries, Mapping)
                    or any(not isinstance(key, str) or not key or type(value) is not bool
                           for key, value in entries.items())):
                _fail("Preserved photo scene unlocks are malformed")
        return access

    def _diagnostic_master_ids(self, table, values):
        """Resolve a few IDs without retaining arbitrary request strings.

        Only the fixed public tables used below reach here. Missing/corrupt
        tables and unsafe identities produce a fixed marker. Diagnostics may
        inspect a bounded table without populating the gameplay catalog cache.
        """
        unknown = tuple("unknown" for _ in values)
        try:
            rows = self.catalog.loaded.get(table)
            if rows is None:
                if self.catalog.directory is None:
                    return unknown
                with (self.catalog.directory / (table + ".json")).open("rb") as stream:
                    raw = stream.read(_DIAGNOSTIC_MASTER_BYTES + 1)
                if len(raw) > _DIAGNOSTIC_MASTER_BYTES:
                    return unknown
                rows = json.loads(raw)
            if not isinstance(rows, list) or len(rows) > 4096:
                return unknown
            identities = set()
            for row in rows:
                identity = row.get("id") if isinstance(row, dict) else None
                if (not isinstance(identity, str) or not _SAFE_MASTER_ID.fullmatch(identity)
                        or identity in identities):
                    return unknown
                identities.add(identity)
            return tuple(value if value in identities else "unknown" for value in values)
        except (OSError, ValueError, TypeError):
            return unknown

    def expression_rejection_facts(self, path, code, plain):
        """Return bounded catalog-only facts for an expression-check failure.

        Call with the already decoded protobuf in Application's failure catch,
        before aborting with the original code/details. The return value keeps
        no request bytes, inventory, user IDs or image reservations. It is safe
        to attach to that request's transport context for its diagnostic log.
        """
        if path != _EXPRESSION_CHECK or code not in (
                RpcCode.INVALID_ARGUMENT, RpcCode.PERMISSION_DENIED, RpcCode.FAILED_PRECONDITION):
            return None
        if type(plain) is not bytes or len(plain) > _DIAGNOSTIC_REQUEST_BYTES:
            return None
        try:
            request = self.schema.request_type(_EXPRESSION_CHECK).FromString(plain)
            arrays = (request.characterIds, request.costumeIds, request.hairIds)
            counts = tuple(min(len(values), 33) for values in arrays)
            legacy = tuple(bool(value) for value in (request.characterId, request.costumeId, request.hairId))
            expression = self._diagnostic_master_ids("PhotoExpression", (request.photoExpressionId,))[0]
            selected = [self._diagnostic_master_ids(table, tuple(values[:3]))
                        for table, values in zip(("Character", "Costume", "Hair"), arrays)]
            return PhotoExpressionRejectionFacts(counts, legacy, expression, *selected)
        except Exception:
            # A failed diagnostic must never replace the original RPC failure.
            return None

    @staticmethod
    def _common(result):
        # Only successful read/check paths reach this helper. Preserve the
        # Common parent without creating either unused user-data delta.
        result.commonResponse.SetInParent()

    def _list(self, result, access):
        hidden = set()
        if self.media_settings is not None:
            from .media_settings import validate_settings
            try:
                settings = self.media_settings() if callable(self.media_settings) else self.media_settings
                settings = validate_settings(settings)
            except (OSError, ValueError):
                _fail("Local media menu settings are unavailable or malformed")
            if settings["hide_video_mv"]:
                musics = self.catalog.ids("Music", required=True)
                for identity in access.musics:
                    music = musics.get(identity)
                    if music is None:
                        _fail("The photo music has no original music definition")
                    is_3d, asset = music.get("is3dAvailable", False), music.get("mvAssetId", "")
                    if type(is_3d) is not bool or not isinstance(asset, str):
                        _fail("The original music playback type is malformed")
                    if asset and not is_3d:
                        hidden.add(identity)
        for table, source, target, identity in (
            ("PhotoActivity", access.activities, result.activities, "photoActivityId"),
            ("PhotoQuestMusic", access.musics, result.musics, "musicId"),
            ("PhotoQuestStage", access.stages, result.stages, "stageId"),
            ("PhotoExpression", access.expressions, result.expressions, "photoExpressionId"),
        ):
            if not source:
                continue
            masters = self.catalog.ids(table, required=True)
            if any(key not in masters for key in source):
                _fail("Preserved photo scene has an unknown master reference")
            for key in sorted(source):
                if table == "PhotoQuestMusic" and key in hidden:
                    continue
                row = target.add(isUnlocked=source[key])
                setattr(row, identity, key)
        result.DokanInfo.SetInParent()
        self._common(result)

    def fill_home(self, result):
        """Supply the gallery's scene access to the original Home cache.

        The original Pose tab validates its cast against the unlocked
        ``HomeEnterResponse.photoExpressions`` cached by UserDataManager,
        before CheckExpressionShooting or ListShooting can be called. Pose
        ownership alone therefore leaves every character marked Shooting NG
        when this collection is empty. Keep all four Home scene collections
        identical to the corresponding Photo.ListShooting projection.

        Ordinary account Home responses and captured permissions are outside
        this explicit gallery policy. Validate the whole new projection
        before replacing any Home field; unrelated/unknown fields stay intact.
        """
        if not self.media_mode:
            return
        if not isinstance(result, self.schema.response_type("/api.Home/Enter")):
            _fail("The media photo home response has a different schema")
        listing = self.schema.response_type(_LIST)()
        self._list(listing, self._access())
        for source, target in (("activities", "photoActivities"), ("musics", "photoMusics"),
                               ("stages", "photoStages"), ("expressions", "photoExpressions")):
            result.ClearField(target)
            getattr(result, target).extend(getattr(listing, source))

    def _scene(self, request, access):
        if request.actionType in (1, 2):
            key = request.photoActivityId
            if not key:
                _fail("A photo activity ID is required", RpcCode.INVALID_ARGUMENT)
            activity = self.catalog.ids("PhotoActivity", required=True).get(key)
            if activity is None or activity.get("type") != request.actionType:
                _fail("Unknown photo activity or mismatched action type", RpcCode.INVALID_ARGUMENT)
            if access.activities.get(key) is not True:
                _fail("The photo activity is not owned and unlocked")
            return activity
        if request.actionType == 3:
            if not request.photoMusicId:
                _fail("A photo music ID is required", RpcCode.INVALID_ARGUMENT)
            if request.photoMusicId not in self.catalog.ids("PhotoQuestMusic", required=True):
                _fail("Unknown local photo music or stage", RpcCode.INVALID_ARGUMENT)
            if access.musics.get(request.photoMusicId) is not True:
                _fail("The photo music or stage is not owned and unlocked")
            if not request.photoStageId:
                # Original LivePhotography.OnExecuteConfirmSheetAsync chooses
                # an empty stage for MV songs before Photo.CheckShootingAsync
                # (0x59b8660..0x59b902c). Music.IsMvMusic (0x4e7af24) uses
                # the real master mvAssetId, not a music-ID prefix.
                music = self.catalog.ids("Music", required=True).get(request.photoMusicId)
                if music is not None and isinstance(music.get("mvAssetId"), str) and music["mvAssetId"]:
                    return _MV_SCENE
                _fail("A photo stage ID is required for a 3D live", RpcCode.INVALID_ARGUMENT)
            if request.photoStageId not in self.catalog.ids("PhotoQuestStage", required=True):
                _fail("Unknown local photo music or stage", RpcCode.INVALID_ARGUMENT)
            if access.stages.get(request.photoStageId) is not True:
                _fail("The photo music or stage is not owned and unlocked")
            return None
        _fail("Unsupported photo shooting action type", RpcCode.INVALID_ARGUMENT)

    def _styles(self, request, snapshot, activity, *, active_count=None):
        characters, costumes, hairs = list(request.characterIds), list(request.costumeIds), list(request.hairIds)
        # A movie creates no 3D actors. The native caller constructs these
        # arrays from its current selection before branching to the empty MV
        # stage. Accept an entirely empty selection without inventing actors;
        # any supplied cast still passes every ordinary ownership/style check.
        if activity is _MV_SCENE and not characters and not costumes and not hairs:
            return (), (), ()
        if (not characters or len(costumes) != len(characters)
                or len(hairs) != len(characters)
                or any(not value for value in [*characters, *costumes, *hairs])):
            _fail("Matching nonempty photo character/style lists are required", RpcCode.INVALID_ARGUMENT)
        if active_count is None:
            active_count = len(characters)
        if type(active_count) is not int or not 0 < active_count <= len(characters):
            _fail("The active photo character projection is malformed")
        character_master = self.catalog.ids("Character", required=True)
        costume_master = self.catalog.ids("Costume", required=True)
        hair_master = self.catalog.ids("Hair", required=True)
        owned_characters = _owned(snapshot.characters, "characterId")
        owned_costumes = _owned(snapshot.costumes, "costumeId")
        owned_hairs = _owned(snapshot.hairs, "hairId")
        for index, (character, costume, hair) in enumerate(zip(characters, costumes, hairs)):
            definition, hair_definition = costume_master.get(costume), hair_master.get(hair)
            if character not in character_master or definition is None or hair_definition is None:
                _fail("Unknown photo character or outfit", RpcCode.INVALID_ARGUMENT)
            if character not in owned_characters or costume not in owned_costumes or hair not in owned_hairs:
                _fail("The photo character or outfit is not owned", RpcCode.PERMISSION_DENIED)
            if definition.get("characterId") != character or hair_definition.get("characterId") != character:
                _fail("Photo character and outfit do not match", RpcCode.INVALID_ARGUMENT)
            if not _wearable(hair_definition, costume):
                _fail("The photo hair cannot be worn with this costume", RpcCode.INVALID_ARGUMENT)
            if index < active_count and activity is not None and activity is not _MV_SCENE:
                denied = activity.get("impossibleShootingCharacterIds", [])
                allowed = activity.get("costumeTypeIds", [])
                if not isinstance(denied, list) or not isinstance(allowed, list):
                    _fail("Photo activity style restrictions are malformed")
                # The separate gallery permits all owned compatible outfits
                # for a job, while retaining character/motion exclusions.
                # The client selector also needs its media master override;
                # this check alone cannot expand that original UI list.
                if (character in denied
                        or not self.media_mode and allowed and definition.get("costumeTypeId") not in allowed):
                    _fail("The photo activity does not allow this character or costume", RpcCode.INVALID_ARGUMENT)
        return tuple(tuple(values[:active_count]) for values in (characters, costumes, hairs))

    def _expression(self, request, snapshot, access):
        if not request.photoExpressionId:
            _fail("A photo expression ID is required", RpcCode.INVALID_ARGUMENT)
        expression = self.catalog.ids("PhotoExpression", required=True).get(request.photoExpressionId)
        if expression is None:
            _fail("Unknown local photo expression", RpcCode.INVALID_ARGUMENT)
        if access.expressions.get(request.photoExpressionId) is not True:
            _fail("The photo expression is not owned and unlocked", RpcCode.PERMISSION_DENIED)
        stage = self.catalog.ids("Stage", required=True).get(expression.get("stageId"))
        amounts = expression.get("characterAmountArray")
        if (stage is None or not isinstance(stage.get("assetId"), str) or not stage["assetId"]
                or not isinstance(amounts, list) or not amounts
                or any(type(value) is not int or value <= 0 for value in amounts)
                or len(amounts) != len(set(amounts))):
            _fail("The photo expression stage or cast definition is malformed")
        characters, costumes, hairs = (list(request.characterIds), list(request.costumeIds),
                                       list(request.hairIds))
        legacy = (request.characterId, request.costumeId, request.hairId)
        if not characters and not costumes and not hairs:
            characters, costumes, hairs = ([legacy[0]], [legacy[1]], [legacy[2]])
        elif any(legacy) and legacy != tuple(values[0] if values else ""
                                             for values in (characters, costumes, hairs)):
            _fail("Conflicting photo expression style selections", RpcCode.INVALID_ARGUMENT)
        # The current client sends its retained roster, including greyed
        # standby characters. Request Take(display capacity) is not a scene's
        # active-cast count: a one-place scene can still send three styles.
        # Validate every roster style, then apply scene restrictions only to
        # the ordered prefix that this original layout can actively display.
        if not 0 < len(characters) <= MAX_EXPRESSION_ROSTER:
            _fail("The photo expression roster must contain one to five characters", RpcCode.INVALID_ARGUMENT)
        return self._styles(SimpleNamespace(characterIds=characters, costumeIds=costumes, hairIds=hairs),
                            snapshot, expression, active_count=min(len(characters), max(amounts)))

    def _urls(self, request, result, snapshot):
        if request.type not in (1, 2, 3):
            _fail("Unsupported photo image request type", RpcCode.INVALID_ARGUMENT)
        assets = list(request.assetIds)
        if any(not valid_image_id(value) for value in assets):
            _fail("Invalid photo image asset IDs", RpcCode.INVALID_ARGUMENT)
        photos = {}
        for photo in snapshot.photos:
            if photo.assetId in assets and photo.imageType == 2:
                photos[photo.assetId] = photo
        for asset in assets:
            if asset not in photos:
                _fail("The requested user photo image is not owned", RpcCode.PERMISSION_DENIED)
            urls = self.image_urls(self.profile, asset) if self.image_urls is not None else None
            if (not isinstance(urls, tuple) or len(urls) != 2 or not isinstance(urls[0], str)
                    or not urls[0] or not isinstance(urls[1], str)):
                _fail("The original photo image has not been preserved locally", RpcCode.NOT_FOUND)
            entry = result.urlList.add(assetId=asset)
            if request.type in (1, 3):
                entry.origUrl = urls[0]
            if request.type in (2, 3):
                entry.tmbUrl = urls[1] or urls[0]

    def handle(self, path, plain):
        if path not in _ROUTES or path not in self.schema.methods or self.catalog.directory is None:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("Malformed photo request", RpcCode.INVALID_ARGUMENT)
        result = self.schema.response_type(path)()
        snapshot = self._snapshot()
        if path == _URL:
            self._urls(request, result, snapshot)
        elif path == _LIST:
            self._list(result, self._access())
        elif path == _EXPRESSION_CHECK:
            self._expression(request, snapshot, self._access())
            self._common(result)
        else:
            activity = self._scene(request, self._access())
            self._styles(request, snapshot, activity)
            if path == _CREATE:
                _fail("Local photo creation requires finalized image upload and verified film generation rules")
            self._common(result)
        return result.SerializeToString()


def format_photo_expression_rejection(path, code, details, facts=None, provider=None):
    """Format only validated facts, with room for the transport's RPC prefix.

    Context attributes are untrusted at this boundary. Validate their complete
    shape and recheck every ID against the provider's bounded public tables.
    Never render exception text or a partial/truncated identity.
    """
    if path != _EXPRESSION_CHECK or code not in (
            RpcCode.INVALID_ARGUMENT, RpcCode.PERMISSION_DENIED, RpcCode.FAILED_PRECONDITION):
        return None
    reason = (_EXPRESSION_REJECTION_REASONS.get((code, details), "unclassified")
              if type(details) is str else "unclassified")
    prefix = "photo_expression_rejection=" + reason
    unavailable = prefix + " facts=unavailable"
    try:
        if type(facts) is not PhotoExpressionRejectionFacts or type(provider) is not PhotoShootings:
            return unavailable
        if (type(facts.counts) is not tuple or len(facts.counts) != 3
                or any(type(value) is not int or not 0 <= value <= 33 for value in facts.counts)
                or type(facts.legacy) is not tuple or len(facts.legacy) != 3
                or any(type(value) is not bool for value in facts.legacy)):
            return unavailable
        arrays = (facts.characters, facts.costumes, facts.hairs)
        if (type(facts.expression) is not str or not _SAFE_MASTER_ID.fullmatch(facts.expression)
                or any(type(values) is not tuple or len(values) != min(count, 3)
                       or any(type(value) is not str or not _SAFE_MASTER_ID.fullmatch(value) for value in values)
                       for values, count in zip(arrays, facts.counts))):
            return unavailable
        if provider._diagnostic_master_ids("PhotoExpression", (facts.expression,)) != (facts.expression,):
            return unavailable
        if any(provider._diagnostic_master_ids(table, values) != values
               for table, values in zip(("Character", "Costume", "Hair"), arrays)):
            return unavailable
        result = (prefix + " counts=" + "/".join(str(value) if value <= 32 else "32+" for value in facts.counts)
                  + " legacy=" + "".join("1" if value else "0" for value in facts.legacy)
                  + " expr=" + facts.expression)
        fields = [(name, "[" + ",".join(values) + "]") for name, values in
                  zip(("char", "costume", "hair"), arrays)]
        for index, (name, value) in enumerate(fields):
            # Reserve fixed markers for later arrays, and omit whole arrays
            # when necessary. A transport log line remains below 400 chars.
            reserve = sum(len(" " + later + "=[omitted]") for later, _ in fields[index + 1:])
            field = " " + name + "=" + value
            result += field if len(result) + len(field) + reserve <= 320 else " " + name + "=[omitted]"
        return result if len(result) <= 320 else unavailable
    except Exception:
        return unavailable
