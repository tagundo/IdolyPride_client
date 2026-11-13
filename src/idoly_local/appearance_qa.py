"""Opt-in owned-appearance QA over the native engines' encrypted RPCs.

This flow acknowledges equipment the disposable QA profile already owns and
selects compatible public defaults. It never creates inventory or clears prior
flags. Starter defaults may already match; the receipt reports actual changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


_USER = "/api.User/Get"
_COSTUME = "/api.Costume/CheckCostume"
_HAIR = "/api.Hair/CheckHair"
_BULK = "/api.Costume/CheckBulk"
_SET = "/api.Costume/SetCostume"
_LIVE = "/api.Costume/SetLiveCostume"


def _require(condition, message):
    if not condition:
        raise RuntimeError("Appearance QA: " + message)


def _bytes(value):
    return value.SerializeToString(deterministic=True)


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _indexed(rows, field):
    result = {getattr(row, field): row for row in rows}
    _require(len(result) == len(rows) and all(result), "owned appearance identities are empty or duplicated")
    return result


def _masters(directory):
    result = {}
    for name in ("Character", "Costume", "Hair"):
        rows = json.loads((Path(directory) / (name + ".json")).read_text(encoding="utf-8"))
        _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
                 "invalid public " + name + " table")
        indexed = {row.get("id"): row for row in rows}
        _require(len(indexed) == len(rows) and all(isinstance(key, str) and key for key in indexed),
                 "ambiguous public " + name + " identities")
        result[name] = indexed
    return result


def _selection(snapshot, master_dir):
    _require(snapshot.HasField("user"), "the dedicated QA profile has no user snapshot")
    masters = _masters(master_dir)
    characters = _indexed(snapshot.characters, "characterId")
    costumes = _indexed(snapshot.costumes, "costumeId")
    hairs = _indexed(snapshot.hairs, "hairId")

    def pair(identity, owner):
        costume = masters["Costume"].get(identity)
        _require(costume is not None and costume.get("characterId") == owner,
                 "public default costume does not belong to its character")
        hair_id = costume.get("defaultHairId")
        hair = masters["Hair"].get(hair_id)
        _require(hair is not None and hair.get("characterId") == owner,
                 "public default hair does not belong to its costume character")
        allowed, denied = hair.get("wearableCostumeIds", []), hair.get("notWearableCostumeIds", [])
        _require(isinstance(allowed, list) and isinstance(denied, list)
                 and all(isinstance(key, str) and key for key in allowed + denied),
                 "public default hair compatibility lists are malformed")
        # Use the unambiguous explicit whitelist subset for native QA. This
        # deliberately does not reimplement the provider's broader rule engine.
        _require(identity in allowed and identity not in denied,
                 "public default pair is not explicitly known compatible")
        return (identity, hair_id) if identity in costumes and hair_id in hairs else None

    candidates = []
    for owner in sorted(characters):
        definition = masters["Character"].get(owner)
        _require(definition is not None, "owned character is absent from the public master")
        favorite = pair(definition.get("defaultCostumeId"), owner)
        live = pair(definition.get("defaultLiveCostumeId") or definition.get("defaultCostumeId"), owner)
        if favorite is not None and live is not None:
            candidates.append((owner, favorite, live))
            if len(candidates) == 2:
                break
    _require(len(candidates) == 2, "requires two owned characters with compatible owned public defaults")
    first, second = candidates
    costume_ids, hair_ids = (first[1][0], second[1][0]), (first[1][1], second[1][1])
    _require(len(set(costume_ids)) == len(set(hair_ids)) == 2,
             "single and bulk acknowledgements must target different owned rows")
    selection = {"costumes": costume_ids, "hairs": hair_ids, "owner": first[0],
                 "favorite": first[1], "live": first[2]}
    return selection


def _selection_digest(selection):
    return hashlib.sha256(json.dumps(selection, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _operations(selection):
    return (
        (_COSTUME, {"costumeId": selection["costumes"][0]}),
        (_HAIR, {"hairId": selection["hairs"][0]}),
        (_BULK, {"costumeIds": [selection["costumes"][1]], "hairIds": [selection["hairs"][1]]}),
        (_SET, {"costumeId": selection["favorite"][0], "hairId": selection["favorite"][1]}),
        (_LIVE, {"costumeId": selection["live"][0], "hairId": selection["live"][1]}),
    )


def _project(schema, expected, path, fields, selection):
    response = schema.response_type(path)()
    updated = response.commonResponse.updatedData
    updated.SetInParent()
    response.commonResponse.deletedData.SetInParent()
    if path in (_SET, _LIVE):
        character = _indexed(expected.characters, "characterId")[selection["owner"]]
        prefix = "favorite" if path == _SET else "live"
        setattr(character, prefix + "CostumeId", fields["costumeId"])
        setattr(character, prefix + "HairId", fields["hairId"])
        updated.characters.add().CopyFrom(character)
    else:
        for name, identity_field, identities in (
                ("costumes", "costumeId", fields.get("costumeIds", [fields["costumeId"]] if "costumeId" in fields else [])),
                ("hairs", "hairId", fields.get("hairIds", [fields["hairId"]] if "hairId" in fields else []))):
            owned = _indexed(getattr(expected, name), identity_field)
            for identity in identities:
                row = owned[identity]
                row.checked = True
                getattr(updated, name).add().CopyFrom(row)
    return response


def _rpc(schema, invoke, path, fields=None):
    return invoke(path, schema.request_type(path)(**(fields or {})))


def _exercise(schema, invoke, expected, selection, *, retries):
    for path, fields in _operations(selection):
        before = _bytes(expected)
        response = _project(schema, expected, path, fields, selection)
        if retries:
            _require(_bytes(expected) == before, "retry selection would change the completed snapshot")
        actual = _rpc(schema, invoke, path, fields)
        _require(_bytes(actual) == _bytes(response),
                 "appearance RPC differs from the exact current-row and empty-deleted Common projection")
        _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(expected),
                 "appearance RPC changed unrelated snapshot fields or failed its selected update")


def _empty_bulk(schema, invoke, expected):
    response = schema.response_type(_BULK)()
    response.commonResponse.SetInParent()
    _require(_bytes(_rpc(schema, invoke, _BULK)) == _bytes(response),
             "empty bulk check must preserve Common without constructing either delta")
    _require(_bytes(_rpc(schema, invoke, _USER)) == _bytes(expected),
             "empty bulk check changed the snapshot")


def assert_appearance_snapshot(schema, payload, receipt):
    snapshot = (schema.response_type(_USER).FromString(bytes(payload))
                if isinstance(payload, (bytes, bytearray, memoryview)) else payload)
    _require(_digest(snapshot) == receipt["snapshot_sha256"], "restart or retry changed the appearance snapshot")
    _require(tuple(len(getattr(snapshot, name)) for name in ("costumes", "hairs", "characters"))
             == tuple(receipt[key] for key in ("costume_rows", "hair_rows", "character_rows")),
             "restart changed owned appearance row counts")


def assert_appearance_retries(schema, invoke, master_dir, receipt):
    """Verify the new receipt before retrying all five APIs after restart."""
    expected = _rpc(schema, invoke, _USER)
    assert_appearance_snapshot(schema, expected, receipt)
    selection = _selection(expected, master_dir)
    _require(_selection_digest(selection) == receipt["selection_sha256"],
             "public/default ownership selection changed after the first receipt")
    _exercise(schema, invoke, expected, selection, retries=True)
    _empty_bulk(schema, invoke, expected)
    assert_appearance_snapshot(schema, _rpc(schema, invoke, _USER), receipt)


def run_appearance_checks(schema, invoke, master_dir, label="native"):
    """Check existing ownership and apply only checked/favorite/live fields."""
    before = _rpc(schema, invoke, _USER)
    selection = _selection(before, master_dir)
    expected = type(before)()
    expected.CopyFrom(before)
    old_costumes, old_hairs = _indexed(before.costumes, "costumeId"), _indexed(before.hairs, "hairId")
    old_character = _indexed(before.characters, "characterId")[selection["owner"]]
    checked_costumes = sum(not old_costumes[key].checked for key in selection["costumes"])
    checked_hairs = sum(not old_hairs[key].checked for key in selection["hairs"])
    favorite_changed = sum(getattr(old_character, "favorite" + suffix) != identity
                           for suffix, identity in zip(("CostumeId", "HairId"), selection["favorite"]))
    live_changed = sum(getattr(old_character, "live" + suffix) != identity
                       for suffix, identity in zip(("CostumeId", "HairId"), selection["live"]))
    _exercise(schema, invoke, expected, selection, retries=False)
    _exercise(schema, invoke, expected, selection, retries=True)
    _empty_bulk(schema, invoke, expected)
    return {"platform": label, "rpc_count": 5, "checked_costume_count": 2, "checked_hair_count": 2,
            "preference_field_count": 4, "costume_checked_changed_count": checked_costumes,
            "hair_checked_changed_count": checked_hairs, "favorite_changed_field_count": favorite_changed,
            "live_changed_field_count": live_changed, "preference_changed_field_count": favorite_changed + live_changed,
            "single_costume_check": True, "single_hair_check": True, "bulk_check": True,
            "favorite_set": True, "live_set": True, "exact_common": True,
            "exact_snapshot_projection": True, "retries_no_change": True, "master_compatible_owned": True,
            "empty_bulk_no_change": True,
            "snapshot_sha256": _digest(expected), "selection_sha256": _selection_digest(selection),
            "costume_rows": len(expected.costumes), "hair_rows": len(expected.hairs),
            "character_rows": len(expected.characters)}
