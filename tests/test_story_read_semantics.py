"""Read-only cohort audit over complete public Condition/Telephone inputs."""
import copy
import json
import re

import pytest

from idoly_local import story_read_rules as rules


@pytest.fixture
def tables():
    stories = [{"id": name, "rewardId": ""} for name in sorted(rules.NO_REWARD_STORIES)]
    stories += [{"id": name, "rewardId": "rd_auto;stone;;30"} for name in sorted(rules.FREE_STONE_STORIES)]
    stories.append({"id": "outside-supported-scope", "rewardId": "other"})
    conditions = [
        {"id": "message-root", "settings": [{"satisfyConditions": {"conditions": [
            {"conditionId": "story-leaf"}, {"conditionId": "item-leaf"}]}}]},
        {"id": "phone-root", "settings": [{"notSatisfyCondition": {"conditionId": "message-root"}}]},
        {"id": "story-leaf", "settings": [{"readStory": {"storyId": "outside-supported-scope"}}]},
        {"id": "item-leaf", "settings": [{"obtainItem": {"itemId": "known-item"}}]},
    ]
    return [stories, conditions, [{"id": "message", "unlockConditionId": "message-root"}],
            [{"id": "telephone", "unlockConditionId": "phone-root"}],
            [{"id": "known-item", "type": 1, "value": 1}]]


def test_known_story_scope_audit_is_pure_and_pins_semantic_receipt(tables):
    before = json.dumps(tables, ensure_ascii=False, sort_keys=True)
    result = rules.audit_story_semantics(*tables)
    assert json.dumps(tables, ensure_ascii=False, sort_keys=True) == before
    assert result == {**result, "schema": 1, "scope_stories": 425, "no_reward_stories": 143,
        "free_stone_stories": 282, "message_rows": 1, "telephone_rows": 1, "condition_rows": 4,
        "reachable_conditions": 4, "read_story_references": 1, "supported_story_dependencies": 0,
        "item_references": 1}
    for key in ("story_rewards_sha256", "condition_closure_sha256", "item_references_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", result[key])
    reordered = [list(reversed(rows)) for rows in tables]
    assert rules.audit_story_semantics(*reordered) == result


@pytest.mark.parametrize("change", ["reward", "story-missing", "telephone-missing", "condition-missing",
    "condition-cycle", "nested-read-dependency", "read-story-missing", "item-missing", "malformed-setting"])
def test_latest_semantic_delta_or_missing_input_is_rejected(tables, change):
    tables = copy.deepcopy(tables)
    if change == "reward": tables[0][0]["rewardId"] = "rd_auto;stone;;99"
    elif change == "story-missing": tables[0].pop(0)
    elif change == "telephone-missing": tables[3].clear()
    elif change == "condition-missing":
        tables[1][0]["settings"][0]["satisfyConditions"]["conditions"][0]["conditionId"] = "missing"
    elif change == "condition-cycle":
        tables[1][2]["settings"] = [{"notSatisfyConditions": {"conditions": [{"conditionId": "phone-root"}]}}]
    elif change == "nested-read-dependency":
        tables[1][2]["settings"][0]["readStory"]["storyId"] = next(iter(rules.FREE_STONE_STORIES))
    elif change == "read-story-missing":
        tables[1][2]["settings"][0]["readStory"]["storyId"] = "missing"
    elif change == "item-missing": tables[1][3]["settings"][0]["obtainItem"]["itemId"] = "missing"
    else: tables[1][0]["settings"] = [None]
    before = json.dumps(tables, sort_keys=True)
    with pytest.raises(ValueError, match="^story_semantic_"):
        rules.audit_story_semantics(*tables)
    assert json.dumps(tables, sort_keys=True) == before


@pytest.mark.parametrize("table", range(5))
def test_audit_rejects_ambiguous_public_identity_in_any_required_table(tables, table):
    tables[table].append(dict(tables[table][0]))
    with pytest.raises(ValueError, match="story_semantic_identity_invalid"):
        rules.audit_story_semantics(*tables)


def test_new_unrelated_condition_changes_receipt_without_claiming_whole_graph_equivalence(tables):
    before = rules.audit_story_semantics(*tables)
    tables[1].append({"id": "new-condition", "settings": []})
    tables[2].append({"id": "new-message", "unlockConditionId": "new-condition"})
    after = rules.audit_story_semantics(*tables)
    assert before["story_rewards_sha256"] == after["story_rewards_sha256"]
    assert before["condition_closure_sha256"] != after["condition_closure_sha256"]
    assert after["supported_story_dependencies"] == 0
