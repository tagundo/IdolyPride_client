"""Persist a local manager name using the original 6.1.1 profile contract.

ProfileTopScreenPresenter sends Profile.UpdateName and refreshes from User.Name.
The original name input uses ten System.String (UTF-16) code units. This local
action changes only that name; official moderation and mission progress are
outside its scope.
"""
from __future__ import annotations

import unicodedata

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure


_PATH = "/api.Profile/UpdateName"
_USER = "/api.User/Get"


def _blank(name):
    # .NET Char.IsWhiteSpace, used by the original InputUtility. Python's
    # str.isspace/strip additionally treats U+001C..U+001F as whitespace.
    return not name or all(char in "\t\n\v\f\r\u0085"
                           or unicodedata.category(char) in ("Zs", "Zl", "Zp") for char in name)


class ProfileNames:
    def __init__(self, schema, state, profile):
        self.schema, self.state, self.profile = schema, state, profile

    def handle(self, path, plain):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed profile name request") from None
        name = request.name
        # Python len() counts Unicode code points, unlike the original C# UI.
        # Preserve accepted text exactly; do not strip or normalize names.
        # The original input removes line breaks and tabs before submission.
        # Reject such out-of-contract requests instead of silently rewriting.
        if _blank(name) or any(char in name for char in "\r\n\t") or len(name.encode("utf-16-le")) // 2 > 10:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Manager name must contain 1 to 10 UTF-16 code units")
        result = self.schema.response_type(path)()

        def update(payload):
            try:
                snapshot = self.schema.response_type(_USER).FromString(payload)
            except (DecodeError, UnicodeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
            if not snapshot.HasField("user"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no user state")
            snapshot.user.name = name
            result.commonResponse.updatedData.user.CopyFrom(snapshot.user)
            return snapshot.SerializeToString()

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile cannot be updated with this schema") from None
        return result.SerializeToString()
