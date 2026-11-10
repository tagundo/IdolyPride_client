"""Owned outfit preferences and acknowledgement flags, without inventory grants."""
from __future__ import annotations

from google.protobuf.message import DecodeError

from .gameplay import _Catalog
from .live_assets import _wearable
from .rpc import RpcCode, RpcFailure


_USER = "/api.User/Get"
_SET = "/api.Costume/SetCostume"
_LIVE = "/api.Costume/SetLiveCostume"
_COSTUME = "/api.Costume/CheckCostume"
_HAIR = "/api.Hair/CheckHair"
_BULK = "/api.Costume/CheckBulk"
_ROUTES = frozenset((_SET, _LIVE, _COSTUME, _HAIR, _BULK))


def _fail(message, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, message)


def _ids(values, description):
    if any(not isinstance(value, str) or not value for value in values):
        _fail("A nonempty " + description + " is required", RpcCode.INVALID_ARGUMENT)
    return tuple(dict.fromkeys(values))


def _owned(rows, field):
    result = {}
    for row in rows:
        identity = getattr(row, field)
        if not identity or identity in result:
            _fail("Local appearance inventory has duplicate or empty " + field)
        result[identity] = row
    return result


class Appearance:
    """Handle five local acknowledgement/preference APIs atomically."""

    def __init__(self, schema, state, profile, master_dir=None):
        self.schema, self.state, self.profile = schema, state, profile
        self.catalog = _Catalog(master_dir)

    def _equipment(self, snapshot, table, owned_field, identity_field, identities):
        masters = self.catalog.ids(table, required=True)
        characters = self.catalog.ids("Character", required=True)
        owned = _owned(getattr(snapshot, owned_field), identity_field)
        selected = []
        for identity in identities:
            definition = masters.get(identity)
            if definition is None:
                _fail("Unknown local " + table + " identity", RpcCode.INVALID_ARGUMENT)
            owner = definition.get("characterId")
            if not isinstance(owner, str) or not owner or owner not in characters:
                _fail("Local " + table + " has no character reference")
            row = owned.get(identity)
            if row is None:
                _fail("The requested " + table + " is not owned", RpcCode.PERMISSION_DENIED)
            selected.append((row, definition))
        return selected

    def handle(self, path, plain):
        if path not in _ROUTES or path not in self.schema.methods or self.catalog.directory is None:
            return None
        try:
            request = self.schema.request_type(path).FromString(plain)
        except DecodeError:
            _fail("Malformed appearance request", RpcCode.INVALID_ARGUMENT)
        costume_ids, hair_ids = (), ()
        if path in (_SET, _LIVE):
            costume_ids = _ids((request.costumeId,), "costumeId")
            hair_ids = _ids((request.hairId,), "hairId")
        elif path == _COSTUME:
            costume_ids = _ids((request.costumeId,), "costumeId")
        elif path == _HAIR:
            hair_ids = _ids((request.hairId,), "hairId")
        else:
            costume_ids = _ids(request.costumeIds, "costumeId")
            hair_ids = _ids(request.hairIds, "hairId")
        result = self.schema.response_type(path)()
        result.commonResponse.updatedData.SetInParent()
        result.commonResponse.deletedData.SetInParent()
        if path == _BULK and not costume_ids and not hair_ids:
            # The native caller sends filtered ID arrays without a nonempty
            # guard. Acknowledging an empty batch needs no snapshot mutation.
            return result.SerializeToString()

        def update(raw):
            try:
                snapshot = self.schema.response_type(_USER).FromString(raw)
            except DecodeError:
                _fail("Local appearance snapshot is malformed")
            if not snapshot.HasField("user"):
                _fail("Local appearance profile has no user state")
            costumes = (self._equipment(snapshot, "Costume", "costumes", "costumeId", costume_ids)
                        if costume_ids else [])
            hairs = (self._equipment(snapshot, "Hair", "hairs", "hairId", hair_ids)
                     if hair_ids else [])
            changed = False
            updated = result.commonResponse.updatedData
            if path in (_SET, _LIVE):
                costume, definition = costumes[0]
                hair, hair_definition = hairs[0]
                owner = definition["characterId"]
                if owner != hair_definition["characterId"]:
                    _fail("Costume and hair belong to different characters", RpcCode.INVALID_ARGUMENT)
                if owner not in self.catalog.ids("Character", required=True):
                    _fail("Local costume character is missing from the master")
                character = _owned(snapshot.characters, "characterId").get(owner)
                if character is None:
                    _fail("The outfit character is not owned", RpcCode.PERMISSION_DENIED)
                if not _wearable(hair_definition, costume.costumeId):
                    _fail("The hair cannot be worn with this costume", RpcCode.INVALID_ARGUMENT)
                prefix = "live" if path == _LIVE else "favorite"
                for field, identity in ((prefix + "CostumeId", costume.costumeId),
                                        (prefix + "HairId", hair.hairId)):
                    if getattr(character, field) != identity:
                        setattr(character, field, identity)
                        changed = True
                updated.characters.add().CopyFrom(character)
            else:
                # Validate the complete batch before changing any selected row.
                for entries, target in ((costumes, updated.costumes), (hairs, updated.hairs)):
                    for row, _definition in entries:
                        if not row.checked:
                            row.checked = True
                            changed = True
                        target.add().CopyFrom(row)
            return snapshot.SerializeToString() if changed else raw

        try:
            self.state.mutate_snapshot(self.profile, self.schema.fingerprint, update)
        except ValueError:
            _fail("Local appearance profile cannot be updated with this schema")
        return result.SerializeToString()
