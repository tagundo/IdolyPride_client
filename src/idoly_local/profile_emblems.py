"""Persist an owned profile emblem without granting unlocks or mission progress.

The recovered 6.1.1 profile UI selects possession emblems and refreshes User's
emblem thumbnail after Profile.UpdateEmblem. Only a nonempty, owned, master-valid
selection is supported here: the original empty-clear UI contract is unproved.
Only User.emblemId changes; the ACK contains the complete updated User.
"""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .rpc import RpcCode, RpcFailure


_PATH = "/api.Profile/UpdateEmblem"
_USER = "/api.User/Get"


class ProfileEmblems:
    def __init__(self, schema, state, profile, master_dir=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)

    def handle(self, path, plain):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed profile emblem request") from None
        selected = request.emblemId
        if not selected:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A nonempty owned emblem identity is required")
        result = self.schema.response_type(path)()

        def update(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except (DecodeError, UnicodeError):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
            if not snapshot.HasField("user"):
                raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no user state")
            masters = self.catalog.ids("Emblem", required=True)
            owned = set()
            for row in snapshot.emblems:
                if not row.emblemId or row.emblemId in owned:
                    raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                                     "Local emblem inventory has empty or duplicate identities")
                owned.add(row.emblemId)
            if selected not in masters:
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown profile emblem identity")
            if selected not in owned:
                raise RpcFailure(RpcCode.PERMISSION_DENIED, "The profile emblem is not owned")
            changed = snapshot.user.emblemId != selected
            if changed:
                snapshot.user.emblemId = selected
            result.commonResponse.updatedData.user.CopyFrom(snapshot.user)
            # Return the full User ACK even after a lost reply, but leave the
            # imported wire ordering and unknown fields intact on an exact retry.
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION,
                             "Local profile cannot be updated with this schema") from None
        return result.SerializeToString()
