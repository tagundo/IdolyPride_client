"""Toggle owned photo locks with an atomic receipt for the original request.

The original 6.1.1 wrapper at 0x474073c builds only repeated photoIds; there
is no desired-lock flag. Its cache-enabled context at 0x4740984 follows the
same x-app-request-id metadata path as other cached mutations. A repeated
request must replay its exact response instead of toggling the photos again.
"""
from __future__ import annotations

import hashlib

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure
from .state import AttemptConflict, State


_PATH = "/api.Photo/SwitchLock"
_USER = "/api.User/Get"


def _fail(reason, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, "Local photo lock: " + reason)


class PhotoPreferences:
    def __init__(self, schema, state, profile):
        self.schema, self.state, self.profile = schema, state, profile

    def handle(self, path, plain, request_id=None):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            State.live_request_id(request_id)
        except ValueError:
            _fail("one canonical positive uint64 x-app-request-id is required",
                  RpcCode.INVALID_ARGUMENT)
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            _fail("malformed request", RpcCode.INVALID_ARGUMENT)
        identities = tuple(request.photoIds)
        if (not identities or any(not identity for identity in identities)
                or len(set(identities)) != len(identities)):
            _fail("nonempty unique photo identities are required", RpcCode.INVALID_ARGUMENT)

        def toggle(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except (DecodeError, UnicodeError):
                _fail("profile snapshot is malformed")
            if not snapshot.HasField("user"):
                _fail("profile has no user state")
            owned = {}
            for row in snapshot.photos:
                if not row.photoId or row.photoId in owned:
                    _fail("photo inventory has empty or duplicate identities")
                owned[row.photoId] = row
            selected = []
            for identity in identities:
                photo = owned.get(identity)
                if photo is None:
                    _fail("a requested photo is not owned", RpcCode.PERMISSION_DENIED)
                selected.append(photo)
            # Validate the complete batch before changing even an in-memory row.
            result = self.schema.response_type(path)()
            for photo in selected:
                photo.locked = not photo.locked
                result.commonResponse.updatedData.photos.add().CopyFrom(photo)
            return snapshot.SerializeToString(), result.SerializeToString()

        try:
            return self.state.mutate_preference_snapshot(
                self.profile, self.schema.fingerprint, request_id,
                hashlib.sha256(plain).hexdigest(), path, toggle)
        except AttemptConflict:
            _fail("request identity was already used for different input",
                  RpcCode.INVALID_ARGUMENT)
        except ValueError:
            _fail("profile or cached preference uses an incompatible schema")
