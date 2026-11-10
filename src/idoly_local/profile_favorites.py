"""Persist the ordered profile favorites without changing ownership or missions.

The recovered 6.1.1 caller submits the selected character ID list and consumes
the common user-data delta. This local policy accepts distinct, owned,
master-valid characters, naturally bounded by the profile's inventory; an empty
selection clears the list. No unevidenced fixed-count cap is applied: the
existing local starter already stores five favorites.
It does not infer official eligibility, moderation or profile mission triggers.
"""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_PATH = "/api.Profile/UpdateFavoriteCharacters"
_USER = "/api.User/Get"


class ProfileFavorites:
    def __init__(self, schema, state, profile, master_dir=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)

    def handle(self, path, plain):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed profile favorite request") from None
        selected = tuple(request.favoriteCharacterIds)
        if any(not identity for identity in selected) or len(set(selected)) != len(selected):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT,
                             "Local profile favorites require distinct nonempty character IDs")
        result = self.schema.response_type(path)()

        def update(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except (DecodeError, UnicodeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
            if not snapshot.HasField("user") or not snapshot.HasField("profile"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no user or profile state")
            # Clearing needs no inventory or master lookup. In particular, it
            # can remove stale imported favorites without inventing ownership.
            if selected:
                masters = self.catalog.ids("Character", required=True)
                owned = set()
                for row in snapshot.characters:
                    if not row.characterId or row.characterId in owned:
                        raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                                         "Local character inventory has empty or duplicate identities")
                    owned.add(row.characterId)
                if any(identity not in masters for identity in selected):
                    raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown favorite character identity")
                if any(identity not in owned for identity in selected):
                    raise RpcFailure(RpcCode.PERMISSION_DENIED, "A favorite character is not owned")
            changed = tuple(snapshot.profile.favoriteCharacterIds) != selected
            if changed:
                del snapshot.profile.favoriteCharacterIds[:]
                snapshot.profile.favoriteCharacterIds.extend(selected)
            result.commonResponse.updatedData.profile.CopyFrom(snapshot.profile)
            # Preserve the original wire bytes on identical retry, including
            # unknown fields and any original wire ordering.
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Local profile cannot be updated with this schema") from None
        return result.SerializeToString()
