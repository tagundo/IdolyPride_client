"""Pure, bounded preparation of the two original first-area accessories.

Original 6.1.1 Accessory.TryGetParam1Bonus (0x4dad5d4) and
DeckCard.SetAccessoriesParameterBonuses (0x51f4700) keep flat addition separate
from permil multiplication. Only the two pinned +64 Part1 items are supported.
"""
from collections import Counter

from .rpc import RpcCode, RpcFailure


_STARTER = {"ac-1-vocal-02": ("vocal", 2), "ac-1-visual-02": ("visual", 3)}
_PLAIN = {"categoryType": 1, "param1Value": 64, "param1Permil": 0,
          "param2Type": 0, "param2Value": 0, "param2Permil": 0,
          "limitBreakPhase": 0, "limitBreakConsumptionId": "",
          "characterId": "", "characterGroupId": ""}


def _fail(detail, code=RpcCode.FAILED_PRECONDITION):
    raise RpcFailure(code, "Local live input: " + detail)


def prepare_starter_accessories(snapshot, positions, catalog):
    """Return slot-to-attribute names without changing inventory or card stats.

    ``positions`` belongs only to the selected deck; its normal five-slot/card
    validation still runs through project_live_assets before these bonuses are
    applied. Repeated item IDs are legal up to their owned quantity.
    """
    if any(row.photoIds or row.part2AccessoryId for row in positions):
        _fail("live photos and Part2 accessories are not supported", RpcCode.UNIMPLEMENTED)
    equipped = [row for row in positions if row.part1AccessoryId]
    if not equipped:
        return {}
    if any(row.part1AccessoryId not in _STARTER for row in equipped):
        _fail("this live accessory is not supported", RpcCode.UNIMPLEMENTED)
    # A locked ability may legitimately have level1 and an empty ID. All owned
    # cards matter: an off-deck learned ability can boost accessory parameters.
    if any(card.liveAbilityId or card.baseLiveAbilityId
           or card.liveAbilityLevel not in (0, 1) or card.baseLiveAbilityLevel not in (0, 1)
           for card in snapshot.cards):
        _fail("live accessories require unlearned owned live abilities", RpcCode.UNIMPLEMENTED)
    owned = {}
    for row in snapshot.accessories:
        if not row.accessoryId or row.accessoryId in owned or row.amount < 0:
            _fail("invalid owned accessory inventory")
        owned[row.accessoryId] = row.amount
    masters = catalog.ids("Accessory", required=True)
    used, result = Counter(), {}
    for position in equipped:
        identity = position.part1AccessoryId
        attribute, parameter_type = _STARTER[identity]
        master = masters.get(identity)
        expected = {**_PLAIN, "param1Type": parameter_type}
        if master is None or any(type(master.get(key)) is not type(value) or master[key] != value
                                 for key, value in expected.items()):
            _fail("the supported accessory differs from its plain master pin")
        used[identity] += 1
        if used[identity] > owned.get(identity, 0):
            _fail("accessory references exceed owned quantities")
        result[position.position] = attribute
    return result
