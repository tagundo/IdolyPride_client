"""Local public-profile lookup and initial birthday registration.

These are explicit local-account contracts, not a remote social directory or
an implementation of official birthday rewards/campaign timing. A saved
birthday cannot be overwritten: only an unset date and exact retries are
accepted. Birthday ADV/reminder messages are never invented.
"""
from __future__ import annotations

from datetime import date

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_FIND = "/api.Profile/FindUser"
_BIRTHDAY = "/api.Profile/UpdateBirthday"
_PATHS = frozenset((_FIND, _BIRTHDAY))


def _valid_birthday(month, day, *, allow_unset=False):
    if allow_unset and (month, day) == (0, 0):
        return True
    try:
        # The protocol stores no birth year. A leap year admits February 29.
        date(2000, month, day)
    except (ValueError, OverflowError):
        return False
    return True


class ProfileDirectory:
    def __init__(self, schema, state, profile, catalog, preferences):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog, self.preferences = catalog, preferences

    def _snapshot(self, raw):
        try:
            snapshot = self.schema.response_type(_USER).FromString(raw)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
        if not snapshot.HasField("user") or not snapshot.HasField("profile"):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local user/profile state is missing")
        if not _valid_birthday(snapshot.profile.birthMonth, snapshot.profile.birthDay, allow_unset=True):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile birthday is invalid")
        return snapshot

    def handle(self, path, plain):
        if path not in _PATHS or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed local profile request") from None
        if path == _BIRTHDAY:
            return self._register_birthday(request)
        return self._find(request)

    def _register_birthday(self, request):
        month, day = request.month, request.day
        if not _valid_birthday(month, day):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Birthday must be a valid calendar month and day")
        result = self.schema.response_type(_BIRTHDAY)()

        def update(raw):
            snapshot = self._snapshot(raw)
            current = snapshot.profile.birthMonth, snapshot.profile.birthDay
            if current not in ((0, 0), (month, day)):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                                 "An existing birthday cannot be replaced by local registration")
            changed = current != (month, day)
            if changed:
                snapshot.profile.birthMonth, snapshot.profile.birthDay = month, day
            result.commonResponse.updatedData.profile.CopyFrom(snapshot.profile)
            # Exact retries return the current full profile ACK without
            # rewriting its original wire representation or unrelated fields.
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile cannot be updated with this schema") from None
        return result.SerializeToString()

    def _find(self, request):
        if not request.userId or len(request.userId) > 128:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A local user identity is required")
        saved = self.state.snapshot(self.profile)
        if saved is None or saved[1] != self.schema.fingerprint:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is unavailable for this schema")
        snapshot = self._snapshot(saved[0])
        if (not snapshot.HasField("userPublic") or not snapshot.userPublic.serverUserId
                or not snapshot.userPublic.publicUserId):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local public identity is missing")
        identity = snapshot.userPublic
        # Accept the selected account's two real IDs, without searching other
        # local accounts or fabricating remote users. The response uses its
        # authoritative server ID; the public ID is the search alias.
        if request.userId not in (identity.serverUserId, identity.publicUserId):
            raise RpcFailure(RpcCode.NOT_FOUND, "The user is not the selected local account")
        user, profile = snapshot.user, snapshot.profile
        if not user.name or user.managerExp < 0 or user.managerLevel < 1:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local manager state is invalid")
        result = self.schema.response_type(_FIND)()
        result.userId = identity.serverUserId
        for field in ("name", "managerExp", "managerLevel", "divisionId", "guildId", "emblemId"):
            setattr(result, field, getattr(user, field))
        for field in ("message", "birthMonth", "birthDay", "backgroundType", "layoutType",
                      "decorationId", "informationType", "colorType"):
            setattr(result, field, getattr(profile, field))
        result.favoriteCharacterIds.extend(profile.favoriteCharacterIds)
        if profile.favoriteCardId:
            try:
                card, master = self.preferences._owned_card(snapshot, profile.favoriteCardId)
                self.preferences._available_image(card, master, profile.favoriteCardDisplayType, allow_auto=True)
            except RpcFailure:
                raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                                 "The saved favorite card image is unavailable") from None
            result.favoriteCard.cardId = card.cardId
            result.favoriteCard.rarity = card.rarity
            result.favoriteCard.evolutionLevel = card.evolutionLevel
            result.favoriteCard.displayType = profile.favoriteCardDisplayType
        if profile.favoritePhotoId:
            photos = [photo for photo in snapshot.photos if photo.photoId == profile.favoritePhotoId]
            if len(photos) != 1 or not photos[0].assetId or photos[0].imageType not in (1, 2, 3):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "The saved favorite photo is unavailable")
            photo = photos[0]
            result.favoritePhoto.photoId = photo.photoId
            result.favoritePhoto.assetId = photo.assetId
            result.favoritePhoto.imageType = photo.imageType
        result.hierarchyCurrentDetailGradeId = self.catalog.hierarchy_grade(
            snapshot.hierarchy.currentFixedPoint + snapshot.hierarchy.currentVariablePoint,
            snapshot.hierarchy.bestDetailGradeId)
        result.hierarchyCurrentRank = 0
        result.commonResponse.SetInParent()
        return result.SerializeToString()
