"""Resolve owned local-deck appearances for the 6.1.1 Quest.ListAsset API.

Native MainLive request construction at 0x647b038 sends the saved deck number
and its name in buddyDeckName even without rentals. DeckCard.ViewCostume and
ViewHair (0x51f2b38/0x51f2bd4), UserCharacter.ActualLiveCostume/GetHair
(0x47a3888/0x47a38d4), and ActorCostume (0x503eddc) establish the appearance
fallbacks below. This enumerates model references; it does not start a battle,
check its outcome, change inventory, or provide resource URLs.
"""
from __future__ import annotations

from collections import Counter

from .rpc import RpcCode, RpcFailure


def _bad(detail):
    raise RpcFailure(RpcCode.FAILED_PRECONDITION, "Invalid local live deck: " + detail)


def _index(rows, identity):
    result = {}
    for row in rows:
        key = getattr(row, identity)
        if not key or key in result:
            _bad("duplicate or empty " + identity)
        result[key] = row
    return result


def _wearable(hair, costume_id):
    allowed = hair.get("wearableCostumeIds", [])
    denied = hair.get("notWearableCostumeIds", [])
    if (not isinstance(allowed, list) or not isinstance(denied, list)
            or any(not isinstance(key, str) or not key for key in [*allowed, *denied])):
        _bad("invalid master hair compatibility")
    # Hair.IsWearableCostume(0x4e47994): unrestricted if both lists are empty;
    # otherwise a whitelist match or a nonempty blacklist non-match permits it.
    return not allowed and not denied or costume_id in allowed or bool(denied) and costume_id not in denied


def project_live_assets(schema, snapshot, request, catalog):
    """Return real appearance IDs in saved slot order, with no snapshot writes."""
    if request.userBuddyDeckPositions:
        raise RpcFailure(RpcCode.UNIMPLEMENTED, "Borrowed live decks are not available locally")
    if not request.questId or request.deckNumber <= 0:
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "A quest and positive saved deck number are required")
    quests = catalog.ids("Quest", required=True)
    areas = catalog.ids("Area", required=True)
    quest = quests.get(request.questId)
    if quest is None:
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown local quest")
    if not isinstance(quest.get("areaId"), str) or quest["areaId"] not in areas:
        _bad("quest has an unknown master area")
    decks = _index(snapshot.decks, "number")
    if request.deckNumber not in decks:
        raise RpcFailure(RpcCode.INVALID_ARGUMENT, "Unknown local saved deck")
    positions = sorted((row for row in snapshot.deckPositions if row.number == request.deckNumber),
                       key=lambda row: row.position)
    if [row.position for row in positions] != [1, 2, 3, 4, 5]:
        _bad("five distinct saved slots are required")
    owned_cards = _index(snapshot.cards, "cardId")
    owned_characters = _index(snapshot.characters, "characterId")
    owned_costumes = _index(snapshot.costumes, "costumeId")
    owned_hairs = _index(snapshot.hairs, "hairId")
    owned_photos = _index(snapshot.photos, "photoId")
    owned_accessories = _index(snapshot.accessories, "accessoryId")
    cards = catalog.ids("Card", required=True)
    characters = catalog.ids("Character", required=True)
    costumes = catalog.ids("Costume", required=True)
    hairs = catalog.ids("Hair", required=True)
    accessories = catalog.ids("Accessory", required=any(
        row.part1AccessoryId or row.part2AccessoryId for row in positions))

    def costume(identity, owner, *, explicit=False):
        row = costumes.get(identity) if isinstance(identity, str) else None
        if row is None or row.get("characterId") != owner or explicit and identity not in owned_costumes:
            _bad("costume must resolve for the owned card character")
        return identity

    def hair(identity, owner, *, explicit=False):
        row = hairs.get(identity) if isinstance(identity, str) else None
        if row is None or row.get("characterId") != owner or explicit and identity not in owned_hairs:
            _bad("hair must resolve for the owned card character")
        return identity

    def default_hair(costume_id, owner):
        identity = hair(costumes[costume_id].get("defaultHairId"), owner)
        if not _wearable(hairs[identity], costume_id):
            _bad("costume default hair is incompatible")
        return identity

    result = schema.response_type("/api.Quest/ListAsset")()
    result.commonResponse.SetInParent()
    used_cards, used_photos, used_accessories = set(), set(), Counter()
    for position in positions:
        owned = owned_cards.get(position.cardId)
        master = cards.get(position.cardId)
        if owned is None or master is None or position.cardId in used_cards:
            _bad("cards must be distinct owned master references")
        used_cards.add(position.cardId)
        owner = master.get("characterId")
        character = characters.get(owner) if isinstance(owner, str) else None
        user_character = owned_characters.get(owner) if isinstance(owner, str) else None
        if character is None or user_character is None:
            _bad("card character must be owned and exist in the master")
        if (len(set(position.photoIds)) != len(position.photoIds)
                or len(position.photoIds) > owned.photoEquipableCount
                or any(key not in owned_photos or key in used_photos for key in position.photoIds)):
            _bad("photo references must be owned, distinct and within the card limit")
        used_photos.update(position.photoIds)
        for key in (position.part1AccessoryId, position.part2AccessoryId):
            if not key:
                continue
            used_accessories[key] += 1
            item = owned_accessories.get(key)
            if key not in accessories or item is None or used_accessories[key] > item.amount:
                _bad("accessory references exceed owned quantities")

        def actual_live_costume():
            # Preferences are valid-lookup fallbacks, not mandatory global
            # references. Explicit deck overrides above have stricter checks.
            for identity, require_owned in ((user_character.liveCostumeId, True),
                                             (character.get("defaultLiveCostumeId"), False),
                                             (user_character.favoriteCostumeId, True),
                                             (character.get("defaultCostumeId"), False)):
                candidate = costumes.get(identity) if isinstance(identity, str) else None
                if (candidate is not None and candidate.get("characterId") == owner
                        and (not require_owned or identity in owned_costumes)):
                    return identity
            _bad("owned character has no valid default live costume")

        selected_costume = costume(position.costumeId, owner, explicit=True) if position.costumeId else actual_live_costume()
        if position.hairId:
            selected_hair = hair(position.hairId, owner, explicit=True)
        else:
            live_costume = actual_live_costume()
            preferred = hairs.get(user_character.liveHairId)
            if (preferred is not None and preferred.get("characterId") == owner
                    and user_character.liveHairId in owned_hairs
                    and _wearable(preferred, live_costume)):
                selected_hair = user_character.liveHairId
            else:
                selected_hair = default_hair(live_costume, owner)
        # ViewHair uses ActualLiveCostume even when a deck costume override is
        # present. ActorCostume then applies this final effective-costume check.
        if not _wearable(hairs[selected_hair], selected_costume):
            selected_hair = default_hair(selected_costume, owner)
        result.characterAssets.add(characterId=owner, costumeId=selected_costume, hairId=selected_hair)
    return result
