"""Read-only lists for this server's empty local inbox and social graph.

These six 6.1.1 RPCs describe local collections only. They do not import an
official inbox, discover remote players, grant gifts or change relationships.
Story catalogs are deliberately separate because even a fresh official user
has nonempty archived event stories.
"""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .rpc import RpcCode, RpcFailure


_GIFT_LIST = "/api.Gift/List"
_ROUTES = frozenset((
    _GIFT_LIST, "/api.Gift/ListHistory", "/api.Friend/List",
    "/api.Friend/ListApplying", "/api.Friend/ListApplied", "/api.Friend/Search",
))


def _validate_enums(message):
    """Proto3 accepts unknown enum numbers; this API supports defined values.

    Defined zero values remain valid. In particular, GiftSortType zero has a
    posted-time fallback in the reference service; rejecting it is unjustified.
    """
    for field, value in message.ListFields():
        values = value if field.is_repeated else (value,)
        if field.enum_type is not None:
            if any(number not in field.enum_type.values_by_number for number in values):
                raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown local list enum value: " + field.name)
        elif field.message_type is not None:
            for nested in values:
                _validate_enums(nested)


class SocialInbox:
    """Project explicit empty local collections without any persistence access."""

    def __init__(self, schema):
        self.schema = schema

    def handle(self, path, plain):
        if path not in _ROUTES or path not in self.schema.methods:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Malformed local list request") from None
        _validate_enums(request)
        if path == _GIFT_LIST and request.offset < 0:
            raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Gift offset must not be negative")
        result = self.schema.response_type(path)()
        # Repeated fields are real empty collections. Gift count=0 and
        # hasNext=false are their protobuf defaults for every valid offset.
        # Explicit nested common containers match the captured empty inbox.
        result.commonResponse.updatedData.SetInParent()
        result.commonResponse.deletedData.SetInParent()
        return result.SerializeToString()
