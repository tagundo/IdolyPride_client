"""Read the local profile header without inventing rankings or remote friends."""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure


_PATH = "/api.Profile/Top"
_USER = "/api.User/Get"


class ProfileTop:
    def __init__(self, schema, state, profile, catalog):
        self.schema, self.state, self.profile, self.catalog = schema, state, profile, catalog

    def handle(self, path, plain):
        if path != _PATH or path not in self.schema.methods:
            return None
        try:
            self.schema.request_type(path).FromString(plain)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed profile top request") from None
        saved = self.state.snapshot(self.profile)
        if saved is None:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no snapshot")
        raw, fingerprint = saved
        if fingerprint != self.schema.fingerprint:
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot uses a different schema")
        try:
            snapshot = self.schema.response_type(_USER).FromString(raw)
        except (DecodeError, UnicodeError):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile snapshot is malformed") from None
        if not snapshot.HasField("user"):
            raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Local profile has no user state")
        result = self.schema.response_type(path)()
        # Use the same master-validated, point-based grade as Home and Quest.
        # Rank zero does not claim a global ranking; the local social graph is
        # empty, so friendProfiles remains an actual empty repeated collection.
        result.hierarchyCurrentDetailGradeId = self.catalog.hierarchy_grade(
            snapshot.hierarchy.currentFixedPoint + snapshot.hierarchy.currentVariablePoint,
            snapshot.hierarchy.bestDetailGradeId)
        result.hierarchyCurrentRank = 0
        result.commonResponse.SetInParent()
        return result.SerializeToString()
