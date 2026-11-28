"""The builder and runtime use one strict, immutable-in-purpose alias policy."""
from types import SimpleNamespace

import pytest

from idoly_local import schema
from idoly_local import master_build


def descriptor(*,number=27,kind=9):
    return SimpleNamespace(fields_by_name={"QuestAudienceAdvantageId":SimpleNamespace(
        number=number,type=kind,json_name="QuestAudienceAdvantageId")})


def test_builder_compatibility_exports_are_the_single_runtime_safe_normalizer():
    assert master_build._normalized_row is schema.normalize_master_row
    assert master_build._ALIASES is schema._MASTER_FIELD_ALIASES
    original={"id":"quest-test","questAudienceAdvantageId":"audience-test","unknownMustRemain":"reject later"}
    expected={"id":"quest-test","QuestAudienceAdvantageId":"audience-test","unknownMustRemain":"reject later"}
    assert schema.normalize_master_row("Quest",original,descriptor())==(expected,1)
    assert master_build._normalized_row("Quest",original,descriptor())==(expected,1)
    assert original["questAudienceAdvantageId"]=="audience-test" and "QuestAudienceAdvantageId" not in original


@pytest.mark.parametrize("kind",["number","type","conflict"])
def test_shared_alias_rejects_wrong_schema_binding_and_conflicting_spellings(kind):
    actual=descriptor(number=28 if kind=="number" else 27,kind=5 if kind=="type" else 9)
    original={"questAudienceAdvantageId":"old"}
    if kind=="conflict":original["QuestAudienceAdvantageId"]="new"
    with pytest.raises(ValueError):schema.normalize_master_row("Quest",original,actual)
    with pytest.raises(ValueError):master_build._normalized_row("Quest",original,actual)
