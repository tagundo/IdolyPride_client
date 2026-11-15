"""Owned profile/card presentation preferences for the recovered 6.1.1 API.

Only the selected user/profile/card preference changes. Inventory, progression,
missions, rewards and imported unknown fields are retained. Card image choices
are checked against the exact (cardId, displayType) master definition as well as
the saved rarity/evolution state; owning an evolved card does not invent an image.
"""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_BUDDY = "/api.Profile/UpdateBuddyCard"
_DECORATION = "/api.Profile/UpdateDecoration"
_BACKGROUND = "/api.Profile/UpdateBackground"
_DISPLAY = "/api.Card/UpdateDisplayType"
_PATHS = frozenset((_BUDDY, _DECORATION, _BACKGROUND, _DISPLAY))
_BACKGROUND_FIELDS = ("backgroundType", "favoriteCardId", "favoritePhotoId",
                      "favoriteCardDisplayType")


PREFERENCE_MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"


def preference_master_rows(catalog, table):
    source = catalog.directory / (table + ".json") if catalog.directory else None
    # A present but empty, malformed or broken table is an error. The
    # supplement only fills the two tables absent from the pinned payload.
    if source is None or source.exists() or source.is_symlink():
        return catalog.rows(table, required=True)
    expected = PREFERENCE_MASTER_VERSION
    try:
        version = catalog.version()
    except (OSError, UnicodeError):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Unreadable local master version") from None
    if version != expected:
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Missing local master table: " + table)
    if table not in ("CardImage", "Decoration"):
        raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Unsupported master supplement")
    if table not in catalog.loaded:
        try:
            import json
            from .preference_master_data import MASTER_VERSION, ROWS_JSON
            if MASTER_VERSION != expected:
                raise ValueError("Incompatible supplement version")
            rows = json.loads(ROWS_JSON[table])
            if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Invalid supplement rows")
        except (ImportError, KeyError, TypeError, ValueError):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Unavailable verified master supplement: " + table) from None
        catalog.loaded[table] = rows
    return catalog.loaded[table]


class ProfilePreferences:
    def __init__(self, schema, state, profile, master_dir=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)
        self._images = None

    @staticmethod
    def _inventory(rows, field, label):
        result = {}
        for row in rows:
            identity = getattr(row, field)
            if not identity or identity in result:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                                 "Local " + label + " inventory has invalid identities")
            result[identity] = row
        return result

    def _rows(self, table):
        return preference_master_rows(self.catalog, table)

    def _decoration_ids(self):
        result = {}
        for row in self._rows("Decoration"):
            identity = row.get("id")
            if not isinstance(identity, str) or not identity or identity in result:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid decoration master identities")
            result[identity] = row
        return result

    def _owned_card(self, snapshot, identity):
        masters = self.catalog.ids("Card", required=True)
        owned = self._inventory(snapshot.cards, "cardId", "card")
        if identity not in masters:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown card identity")
        if identity not in owned:
            raise RpcFailure(RpcCode.PERMISSION_DENIED, "The card is not owned")
        return owned[identity], masters[identity]

    def _available_image(self, card, master, display_type, *, allow_auto=False):
        if display_type not in (0, 1, 2, 3) or (display_type == 0 and not allow_auto):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Undefined card image choice")
        initial = master.get("initialRarity")
        if type(initial) is not int or initial < 1:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid card rarity definition")
        if card.rarity < initial or card.evolutionLevel < 0:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local card image eligibility")
        # CalcIllustrationStage's auto value derives the actual illustration
        # stage from evolution, then current rarity. Keep 0 only in a profile
        # background request; Card's confirmation sheet sends an explicit 1..3.
        effective = display_type
        if effective == 0:
            effective = 3 if card.evolutionLevel > 0 else (2 if card.rarity > 4 else 1)
        if effective == 2 and initial <= 4 and card.rarity <= 4:
            raise RpcFailure(RpcCode.PERMISSION_DENIED, "The card image is not released")
        if effective == 3 and card.evolutionLevel <= 0:
            raise RpcFailure(RpcCode.PERMISSION_DENIED, "The evolved card image is not released")
        if self._images is None:
            images = {}
            for row in self._rows("CardImage"):
                identity, choice, kind = row.get("cardId"), row.get("displayType"), row.get("imageType")
                if (not isinstance(identity, str) or not identity or
                        type(choice) is not int or choice not in (1, 2, 3) or
                        type(kind) is not int or kind not in (1, 2, 3) or
                        (identity, choice) in images):
                    raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                                     "Invalid card image master definition")
                images[(identity, choice)] = row
            self._images = images
        if (card.cardId, effective) not in self._images:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "The card has no such image definition")

    def handle(self, path, plain):
        if path not in _PATHS or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed presentation preference request") from None
        if path in (_BUDDY, _DISPLAY) and not request.cardId:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A nonempty owned card identity is required")
        if path == _DECORATION and not request.decorationId:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A nonempty owned decoration identity is required")
        if path == _DISPLAY and request.displayType not in (1, 2, 3):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Card image choice must be defined value 1 to 3")
        if path == _BACKGROUND:
            if request.backgroundType not in (1, 2, 3):
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Undefined profile background choice")
            if request.backgroundType == 2 and not request.favoriteCardId:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A card background requires an owned card")
            if request.backgroundType == 3 and not request.favoritePhotoId:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A photo background requires an owned photo")
            if not request.favoriteCardId and request.favoriteCardDisplayType != 0:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "An image choice requires a card identity")
        result = self.schema.response_type(path)()

        def update(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except (DecodeError, UnicodeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
            if not snapshot.HasField("user"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no user state")
            if path in (_BACKGROUND, _DECORATION) and not snapshot.HasField("profile"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no profile state")
            if path == _BUDDY:
                self._owned_card(snapshot, request.cardId)
                changed = snapshot.user.buddyCardId != request.cardId
                if changed:
                    snapshot.user.buddyCardId = request.cardId
                result.commonResponse.updatedData.user.CopyFrom(snapshot.user)
            elif path == _DECORATION:
                masters = self._decoration_ids()
                owned = self._inventory(snapshot.decorations, "decorationId", "decoration")
                if request.decorationId not in masters:
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown decoration identity")
                if request.decorationId not in owned:
                    raise RpcFailure(RpcCode.PERMISSION_DENIED, "The decoration is not owned")
                changed = snapshot.profile.decorationId != request.decorationId
                if changed:
                    snapshot.profile.decorationId = request.decorationId
                result.commonResponse.updatedData.profile.CopyFrom(snapshot.profile)
            elif path == _DISPLAY:
                card, master = self._owned_card(snapshot, request.cardId)
                self._available_image(card, master, request.displayType)
                changed = card.displayType != request.displayType
                if changed:
                    card.displayType = request.displayType
                result.commonResponse.updatedData.cards.add().CopyFrom(card)
            else:
                # Validate both supplied favorite references, including the
                # inactive preference, before committing the complete request.
                if request.favoriteCardId:
                    card, master = self._owned_card(snapshot, request.favoriteCardId)
                    self._available_image(card, master, request.favoriteCardDisplayType, allow_auto=True)
                if request.favoritePhotoId:
                    owned = self._inventory(snapshot.photos, "photoId", "photo")
                    if request.favoritePhotoId not in owned:
                        raise RpcFailure(RpcCode.PERMISSION_DENIED, "The photo is not owned")
                selected = tuple(getattr(request, name) for name in _BACKGROUND_FIELDS)
                changed = tuple(getattr(snapshot.profile, name) for name in _BACKGROUND_FIELDS) != selected
                if changed:
                    for name, value in zip(_BACKGROUND_FIELDS, selected):
                        setattr(snapshot.profile, name, value)
                result.commonResponse.updatedData.profile.CopyFrom(snapshot.profile)
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Local profile cannot be updated with this schema") from None
        return result.SerializeToString()
