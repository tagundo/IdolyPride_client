"""Persist the local profile introduction through Profile.UpdateMessage.

The original SolisInputField applies a sixty UTF-16-code-unit limit, converts
whitespace-only input to empty and removes tabs. This local server rejects
empty/blank, over-limit and tab-containing direct requests rather than silently
rewriting them. It preserves all other accepted text, including CR/LF: the
original field's prefab line type is not yet established, and its input utility
conditionally preserves newlines. This is an explicit local input policy,
not a claim that protobuf's max_len annotation counts UTF-16 units.

Only UserProfile.message changes. Official moderation, mission progress and
rewards are outside this local action's scope.
"""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .profile_names import _blank
from .rpc import RpcCode, RpcFailure


_PATH = "/api.Profile/UpdateMessage"
_USER = "/api.User/Get"


class ProfileMessages:
    def __init__(self, schema, state, profile):
        self.schema, self.state, self.profile = schema, state, profile

    def handle(self, path, plain):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed profile message request") from None
        message = request.message
        if _blank(message) or "\t" in message or len(message.encode("utf-16-le")) // 2 > 60:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT,
                             "Profile message must contain 1 to 60 UTF-16 code units without tabs")
        result = self.schema.response_type(path)()

        def update(payload):
            try:
                snapshot = self.schema.response_type(_USER).FromString(payload)
            except (DecodeError, UnicodeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
            # Master-backed starters already contain UserProfile. Do not create
            # one over an incomplete/imported snapshot and invent its settings.
            if not snapshot.HasField("profile"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no profile state")
            changed = snapshot.profile.message != message
            if changed:
                snapshot.profile.message = message
            result.commonResponse.updatedData.profile.CopyFrom(snapshot.profile)
            # Keep the current profile ACK for resynchronization while
            # preserving original wire bytes on an identical retry.
            return snapshot.SerializeToString() if changed else payload

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Local profile cannot be updated with this schema") from None
        return result.SerializeToString()
