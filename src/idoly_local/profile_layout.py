"""Persist the three native profile appearance preferences.

The 6.1.1 UpdateLayout contract has four defined choices for each preference.
This local action changes only an existing UserProfile and returns its full
post-image. It does not create a profile or infer rewards or mission progress.
"""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure


_PATH = "/api.Profile/UpdateLayout"
_USER = "/api.User/Get"
_FIELDS = ("layoutType", "informationType", "colorType")
_CHOICES = frozenset((1, 2, 3, 4))


class ProfileLayout:
    def __init__(self, schema, state, profile):
        self.schema, self.state, self.profile = schema, state, profile

    def handle(self, path, plain):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed profile layout request") from None
        selected = tuple(getattr(request, name) for name in _FIELDS)
        if any(value not in _CHOICES for value in selected):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Profile appearance choices must be defined values 1 to 4")
        result = self.schema.response_type(path)()

        def update(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except (DecodeError, UnicodeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
            if not snapshot.HasField("user") or not snapshot.HasField("profile"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no user or profile state")
            changed = tuple(getattr(snapshot.profile, name) for name in _FIELDS) != selected
            if changed:
                for name, value in zip(_FIELDS, selected):
                    setattr(snapshot.profile, name, value)
            result.commonResponse.updatedData.profile.CopyFrom(snapshot.profile)
            # An identical retry retains the imported wire order and unknown
            # fields byte for byte instead of normalizing its serialization.
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Local profile cannot be updated with this schema") from None
        return result.SerializeToString()
