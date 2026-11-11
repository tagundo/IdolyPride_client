"""Rename an owned photo using the original 6.1.1 Photo.Update contract.

The native detail screen validates nonblank text with a twelve UTF-16-unit
limit and its IsSurrogateText character filter before submitting. This local
preference changes no recipe, rarity, ability, resource, lock or Dream state.
Official text moderation and normalization are not reproduced.
"""
from __future__ import annotations

import unicodedata

from google.protobuf.message import DecodeError

from .profile_names import _blank
from .rpc import RpcCode, RpcFailure


_PATH = "/api.Photo/Update"
_USER = "/api.User/Get"


class PhotoNames:
    def __init__(self, schema, state, profile):
        self.schema, self.state, self.profile = schema, state, profile

    def handle(self, path, plain):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed photo name request") from None
        name = request.name
        # InputUtility.ValidateText at 0x46a6b64 counts String.Length.
        # Its IsSurrogateText at 0x46a6d94/0x46a6e58 rejects surrogate
        # characters, Unicode categories 5/6/7/16/28, and regex [☀-⛿].
        # The name of that helper also covers combining marks and symbols.
        # Reject CR/LF/tab direct requests consistently with local name input;
        # preserve accepted spaces and characters without trimming them.
        if (not request.photoId or _blank(name) or any(char in name for char in "\r\n\t")
                or any(ord(char) > 0xFFFF or 0xD800 <= ord(char) <= 0xDFFF for char in name)
                or any(unicodedata.category(char) in {"Mn", "Mc", "Me", "Cs", "So"}
                       or 0x2600 <= ord(char) <= 0x26FF for char in name)
                or len(name.encode("utf-16-le")) // 2 > 12):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT,
                             "Photo name requires an owned photo and 1 to 12 UTF-16 units with native permitted characters")
        result = self.schema.response_type(path)()

        def update(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except (DecodeError, UnicodeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local photo snapshot is malformed") from None
            if not snapshot.HasField("user"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local photo profile has no user state")
            owned = {}
            for row in snapshot.photos:
                if not row.photoId or row.photoId in owned:
                    raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                                     "Local photo inventory has empty or duplicate identities")
                owned[row.photoId] = row
            photo = owned.get(request.photoId)
            if photo is None:
                raise RpcFailure(RpcCode.PERMISSION_DENIED, "The requested photo is not owned")
            changed = photo.name != name
            if changed:
                photo.name = name
            result.commonResponse.updatedData.photos.add().CopyFrom(photo)
            # A retry returns the current full photo without rewriting its
            # original protobuf wire ordering or dropping unknown fields.
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Local photo profile cannot be updated with this schema") from None
        return result.SerializeToString()
