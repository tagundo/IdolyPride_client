"""Pinned story-read scope audited against the 6.1.1 public baseline.

All listed IDs are in the public 55-event/3-extra-part catalog and have no
ReadStory dependency in the pinned master Message/Telephone condition closure.
See docs/story-read-support.md for evidence and explicit limitations.
"""

SCHEMA_SHA256 = "0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3"
MASTER_VERSION = "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60"
LATEST_MASTER_VERSION = "6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11"
BASELINE_ID = "fresh-official-2026-10-25"
SOURCE_COMMIT = "c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02"

NO_REWARD_STORIES = frozenset((
    'st-birthday-branch-ai-24-0209',
    'st-birthday-branch-ai-25-0209',
    'st-birthday-branch-ai-26-0209',
    'st-birthday-branch-aoi-24-0619',
    'st-birthday-branch-aoi-25-0619',
    'st-birthday-branch-aoi-26-0619',
    'st-birthday-branch-chs-23-1122',
    'st-birthday-branch-chs-24-1122',
    'st-birthday-branch-chs-25-1122',
    'st-birthday-branch-hrk-24-0103',
    'st-birthday-branch-hrk-25-0103',
    'st-birthday-branch-hrk-26-0103',
    'st-birthday-branch-kan-24-0410',
    'st-birthday-branch-kan-25-0410',
    'st-birthday-branch-kan-26-0410',
    'st-birthday-branch-kkr-23-1206',
    'st-birthday-branch-kkr-24-1206',
    'st-birthday-branch-kkr-25-1206',
    'st-birthday-branch-kor-24-0611',
    'st-birthday-branch-kor-25-0611',
    'st-birthday-branch-kor-26-0611',
    'st-birthday-branch-ktn-23-1225',
    'st-birthday-branch-ktn-24-1225',
    'st-birthday-branch-ktn-25-1225',
    'st-birthday-branch-mei-23-0707',
    'st-birthday-branch-mei-24-0707',
    'st-birthday-branch-mei-25-0707',
    'st-birthday-branch-mei-26-0707',
    'st-birthday-branch-mhk-24-0125',
    'st-birthday-branch-mhk-25-0125',
    'st-birthday-branch-mhk-26-0125',
    'st-birthday-branch-mna-24-1009',
    'st-birthday-branch-mna-25-1009',
    'st-birthday-branch-mna-26-1009',
    'st-birthday-branch-ngs-23-0803',
    'st-birthday-branch-ngs-24-0803',
    'st-birthday-branch-ngs-25-0803',
    'st-birthday-branch-ngs-26-0803',
    'st-birthday-branch-rei-24-0308',
    'st-birthday-branch-rei-25-0308',
    'st-birthday-branch-rei-26-0308',
    'st-birthday-branch-rio-23-0828',
    'st-birthday-branch-rio-24-0828',
    'st-birthday-branch-rio-25-0828',
    'st-birthday-branch-rio-26-0828',
    'st-birthday-branch-rui-23-1111',
    'st-birthday-branch-rui-24-1111',
    'st-birthday-branch-rui-25-1111',
    'st-birthday-branch-ski-23-0926',
    'st-birthday-branch-ski-24-0926',
    'st-birthday-branch-ski-25-0926',
    'st-birthday-branch-ski-26-0926',
    'st-birthday-branch-skr-24-0403',
    'st-birthday-branch-skr-25-0403',
    'st-birthday-branch-skr-26-0403',
    'st-birthday-branch-smr-24-0505',
    'st-birthday-branch-smr-25-0505',
    'st-birthday-branch-smr-26-0505',
    'st-birthday-branch-suz-23-0913',
    'st-birthday-branch-suz-24-0913',
    'st-birthday-branch-suz-25-0913',
    'st-birthday-branch-suz-26-0913',
    'st-birthday-branch-szk-23-1015',
    'st-birthday-branch-szk-24-1015',
    'st-birthday-branch-szk-25-1015',
    'st-birthday-branch-szk-26-1015',
    'st-birthday-branch-yu-24-0227',
    'st-birthday-branch-yu-25-0227',
    'st-birthday-branch-yu-26-0227',
    'st-ex-story-part-birthday-01-ai-01',
    'st-ex-story-part-birthday-01-ai-02',
    'st-ex-story-part-birthday-01-aoi-01',
    'st-ex-story-part-birthday-01-aoi-02',
    'st-ex-story-part-birthday-01-chs-01',
    'st-ex-story-part-birthday-01-chs-02',
    'st-ex-story-part-birthday-01-hrk-01',
    'st-ex-story-part-birthday-01-hrk-02',
    'st-ex-story-part-birthday-01-kan-01',
    'st-ex-story-part-birthday-01-kkr-01',
    'st-ex-story-part-birthday-01-kkr-02',
    'st-ex-story-part-birthday-01-kor-01',
    'st-ex-story-part-birthday-01-ktn-01',
    'st-ex-story-part-birthday-01-ktn-02',
    'st-ex-story-part-birthday-01-mei-01',
    'st-ex-story-part-birthday-01-mei-02',
    'st-ex-story-part-birthday-01-mhk-01',
    'st-ex-story-part-birthday-01-ngs-01',
    'st-ex-story-part-birthday-01-ngs-02',
    'st-ex-story-part-birthday-01-rei-01',
    'st-ex-story-part-birthday-01-rei-02',
    'st-ex-story-part-birthday-01-rio-01',
    'st-ex-story-part-birthday-01-rio-02',
    'st-ex-story-part-birthday-01-rui-01',
    'st-ex-story-part-birthday-01-rui-02',
    'st-ex-story-part-birthday-01-ski-01',
    'st-ex-story-part-birthday-01-ski-02',
    'st-ex-story-part-birthday-01-skr-01',
    'st-ex-story-part-birthday-01-skr-02',
    'st-ex-story-part-birthday-01-smr-01',
    'st-ex-story-part-birthday-01-smr-02',
    'st-ex-story-part-birthday-01-suz-01',
    'st-ex-story-part-birthday-01-suz-02',
    'st-ex-story-part-birthday-01-szk-01',
    'st-ex-story-part-birthday-01-szk-02',
    'st-ex-story-part-birthday-01-yu-01',
    'st-ex-story-part-birthday-01-yu-02',
    'st-ex-story-part-special-01-21-1224-half-aniv',
    'st-ex-story-part-special-01-22-0103-newyear-01',
    'st-ex-story-part-special-01-22-0401-april-01',
    'st-ex-story-part-special-01-22-0401-april-02',
    'st-ex-story-part-special-01-22-0624-aniv-01',
    'st-ex-story-part-special-01-22-0624-aniv-02',
    'st-ex-story-part-special-01-23-0101-newyear-01',
    'st-ex-story-part-special-01-23-0401-april-01',
    'st-ex-story-part-special-01-23-0401-april-02',
    'st-ex-story-part-special-01-23-0401-april-03',
    'st-ex-story-part-special-01-24-0103-newyear-01',
    'st-ex-story-part-special-01-24-0401-april-01',
    'st-ex-story-part-special-01-24-0401-april-02',
    'st-ex-story-part-special-01-24-0401-april-03',
    'st-ex-story-part-special-01-24-0401-april-04',
    'st-ex-story-part-special-01-24-0401-april-05',
    'st-ex-story-part-special-01-25-0104-newyear-01',
    'st-ex-story-part-special-01-25-0624-aniv-01',
    'st-ex-story-part-special-01-26-0104-newyear-01',
    'st-ex-story-part-special-01-26-0401-april-01',
    'st-ex-story-part-special-01-26-0401-april-02',
    'st-ex-story-part-special-01-26-0401-april-03',
    'st-ex-story-part-special-01-26-0401-april-04',
    'st-ex-story-part-special-01-26-0401-april-05',
    'st-ex-story-part-special-01-26-0401-april-06',
    'st-ex-story-part-special-01-26-0624-aniv-01',
    'st-ex-story-part-special-01-birthday-trip-2024-01',
    'st-ex-story-part-special-01-birthday-trip-2024-02',
    'st-ex-story-part-special-01-birthday-trip-2024-03',
    'st-ex-story-part-special-01-birthday-trip-2024-04',
    'st-shelf-25-0401-001-001',
    'st-shelf-25-0401-001-002',
    'st-shelf-25-0401-001-003',
    'st-shelf-25-0401-001-004',
    'st-shelf-25-0401-001-005',
    'st-shelf-25-0401-001-006',
    'st-shelf-25-0401-001-007',
))

FREE_STONE_STORIES = frozenset((
    'st-eve-2107-tour-001',
    'st-eve-2107-tour-002',
    'st-eve-2107-tour-003',
    'st-eve-2107-tour-004',
    'st-eve-2107-tour-005',
    'st-eve-2108-tour-001',
    'st-eve-2108-tour-002',
    'st-eve-2108-tour-003',
    'st-eve-2108-tour-004',
    'st-eve-2108-tour-005',
    'st-eve-2109-backside-001',
    'st-eve-2109-backside-002',
    'st-eve-2109-backside-003',
    'st-eve-2109-backside-004',
    'st-eve-2109-backside-005',
    'st-eve-2110-marathon-001',
    'st-eve-2110-marathon-002',
    'st-eve-2110-marathon-003',
    'st-eve-2110-marathon-004',
    'st-eve-2110-marathon-005',
    'st-eve-2110-marathon-006',
    'st-eve-2111-backside-001',
    'st-eve-2111-backside-002',
    'st-eve-2111-backside-003',
    'st-eve-2111-backside-004',
    'st-eve-2111-backside-005',
    'st-eve-2112-marathon-001',
    'st-eve-2112-marathon-002',
    'st-eve-2112-marathon-003',
    'st-eve-2112-marathon-004',
    'st-eve-2112-marathon-005',
    'st-eve-2201-contest-001',
    'st-eve-2201-contest-002',
    'st-eve-2201-contest-003',
    'st-eve-2201-contest-004',
    'st-eve-2201-contest-005',
    'st-eve-2202-marathon-001',
    'st-eve-2202-marathon-002',
    'st-eve-2202-marathon-003',
    'st-eve-2202-marathon-004',
    'st-eve-2202-marathon-005',
    'st-eve-2203-race-001',
    'st-eve-2203-race-002',
    'st-eve-2203-race-003',
    'st-eve-2203-race-004',
    'st-eve-2203-race-005',
    'st-eve-2203-race-006',
    'st-eve-2204-contest-001',
    'st-eve-2204-contest-002',
    'st-eve-2204-contest-003',
    'st-eve-2204-contest-004',
    'st-eve-2204-contest-005',
    'st-eve-2204-contest-006',
    'st-eve-2205-race-001',
    'st-eve-2205-race-002',
    'st-eve-2205-race-003',
    'st-eve-2205-race-004',
    'st-eve-2205-race-005',
    'st-eve-2206-marathon-001',
    'st-eve-2206-marathon-002',
    'st-eve-2206-marathon-003',
    'st-eve-2206-marathon-004',
    'st-eve-2206-marathon-005',
    'st-eve-2207-contest-001',
    'st-eve-2207-contest-002',
    'st-eve-2207-contest-003',
    'st-eve-2207-contest-004',
    'st-eve-2207-contest-005',
    'st-eve-2208-backside-001',
    'st-eve-2208-backside-002',
    'st-eve-2208-backside-003',
    'st-eve-2208-backside-004',
    'st-eve-2208-backside-005',
    'st-eve-2209-contest-001',
    'st-eve-2209-contest-002',
    'st-eve-2209-contest-003',
    'st-eve-2209-contest-004',
    'st-eve-2209-contest-005',
    'st-eve-2210-race-001',
    'st-eve-2210-race-002',
    'st-eve-2210-race-003',
    'st-eve-2210-race-004',
    'st-eve-2210-race-005',
    'st-eve-2211-marathon-raid-001',
    'st-eve-2211-marathon-raid-002',
    'st-eve-2211-marathon-raid-003',
    'st-eve-2211-marathon-raid-004',
    'st-eve-2211-marathon-raid-005',
    'st-eve-2212-race-001',
    'st-eve-2212-race-002',
    'st-eve-2212-race-003',
    'st-eve-2212-race-004',
    'st-eve-2212-race-005',
    'st-eve-2301-contest-001',
    'st-eve-2301-contest-002',
    'st-eve-2301-contest-003',
    'st-eve-2301-contest-004',
    'st-eve-2301-contest-005',
    'st-eve-2302-marathon-raid-001',
    'st-eve-2302-marathon-raid-002',
    'st-eve-2302-marathon-raid-003',
    'st-eve-2302-marathon-raid-004',
    'st-eve-2302-marathon-raid-005',
    'st-eve-2303-race-001',
    'st-eve-2303-race-002',
    'st-eve-2303-race-003',
    'st-eve-2303-race-004',
    'st-eve-2303-race-005',
    'st-eve-2304-marathon-raid-001',
    'st-eve-2304-marathon-raid-002',
    'st-eve-2304-marathon-raid-003',
    'st-eve-2304-marathon-raid-004',
    'st-eve-2304-marathon-raid-005',
    'st-eve-2305-race-001',
    'st-eve-2305-race-002',
    'st-eve-2305-race-003',
    'st-eve-2306-contest-001',
    'st-eve-2306-contest-002',
    'st-eve-2306-contest-003',
    'st-eve-2306-contest-004',
    'st-eve-2306-contest-005',
    'st-eve-2307-race-001',
    'st-eve-2307-race-002',
    'st-eve-2307-race-003',
    'st-eve-2307-race-004',
    'st-eve-2307-race-005',
    'st-eve-2308-marathon-raid-001',
    'st-eve-2308-marathon-raid-002',
    'st-eve-2308-marathon-raid-003',
    'st-eve-2308-marathon-raid-004',
    'st-eve-2308-marathon-raid-005',
    'st-eve-2309-backside-001',
    'st-eve-2309-backside-002',
    'st-eve-2309-backside-003',
    'st-eve-2309-backside-004',
    'st-eve-2309-backside-005',
    'st-eve-2310-race-001',
    'st-eve-2310-race-002',
    'st-eve-2310-race-003',
    'st-eve-2310-race-004',
    'st-eve-2310-race-005',
    'st-eve-2311-marathon-raid-001',
    'st-eve-2311-marathon-raid-002',
    'st-eve-2311-marathon-raid-003',
    'st-eve-2311-marathon-raid-004',
    'st-eve-2311-marathon-raid-005',
    'st-eve-2401-race-001',
    'st-eve-2401-race-002',
    'st-eve-2401-race-003',
    'st-eve-2401-race-004',
    'st-eve-2401-race-005',
    'st-eve-2402-contest-001',
    'st-eve-2402-contest-002',
    'st-eve-2402-contest-003',
    'st-eve-2402-contest-004',
    'st-eve-2402-contest-005',
    'st-eve-2403-race-001',
    'st-eve-2403-race-002',
    'st-eve-2403-race-003',
    'st-eve-2403-race-004',
    'st-eve-2403-race-005',
    'st-eve-2404-dice-001',
    'st-eve-2404-dice-002',
    'st-eve-2404-dice-003',
    'st-eve-2404-dice-004',
    'st-eve-2404-dice-005',
    'st-eve-2405-race-001',
    'st-eve-2405-race-002',
    'st-eve-2405-race-003',
    'st-eve-2405-race-004',
    'st-eve-2405-race-005',
    'st-eve-2406-contest-001',
    'st-eve-2406-contest-002',
    'st-eve-2406-contest-003',
    'st-eve-2406-contest-004',
    'st-eve-2406-contest-005',
    'st-eve-2407-dice-001',
    'st-eve-2407-dice-002',
    'st-eve-2407-dice-003',
    'st-eve-2407-dice-004',
    'st-eve-2407-dice-005',
    'st-eve-2408-race-001',
    'st-eve-2408-race-002',
    'st-eve-2408-race-003',
    'st-eve-2408-race-004',
    'st-eve-2408-race-005',
    'st-eve-2409-marathon-raid-001',
    'st-eve-2409-marathon-raid-002',
    'st-eve-2409-marathon-raid-003',
    'st-eve-2409-marathon-raid-004',
    'st-eve-2409-marathon-raid-005',
    'st-eve-2410-dice-001',
    'st-eve-2410-dice-002',
    'st-eve-2410-dice-003',
    'st-eve-2410-dice-004',
    'st-eve-2410-dice-005',
    'st-eve-2411-race-001',
    'st-eve-2411-race-002',
    'st-eve-2411-race-003',
    'st-eve-2411-race-004',
    'st-eve-2411-race-005',
    'st-eve-2501-race-001',
    'st-eve-2501-race-002',
    'st-eve-2501-race-003',
    'st-eve-2501-race-004',
    'st-eve-2501-race-005',
    'st-eve-2502-marathon-raid-001',
    'st-eve-2502-marathon-raid-002',
    'st-eve-2502-marathon-raid-003',
    'st-eve-2502-marathon-raid-004',
    'st-eve-2502-marathon-raid-005',
    'st-eve-2504-marathon-raid-001',
    'st-eve-2504-marathon-raid-002',
    'st-eve-2504-marathon-raid-003',
    'st-eve-2504-marathon-raid-004',
    'st-eve-2504-marathon-raid-005',
    'st-eve-2507-free-001',
    'st-eve-2507-free-002',
    'st-eve-2507-free-003',
    'st-eve-2507-free-004',
    'st-eve-2507-free-005',
    'st-eve-2507-race-001',
    'st-eve-2507-race-002',
    'st-eve-2507-race-003',
    'st-eve-2507-race-004',
    'st-eve-2507-race-005',
    'st-eve-2508-free-001',
    'st-eve-2508-free-002',
    'st-eve-2508-free-003',
    'st-eve-2508-free-004',
    'st-eve-2508-free-005',
    'st-eve-2509-contest-001',
    'st-eve-2509-contest-002',
    'st-eve-2509-contest-003',
    'st-eve-2509-contest-004',
    'st-eve-2509-contest-005',
    'st-eve-2510-marathon-raid-001',
    'st-eve-2510-marathon-raid-002',
    'st-eve-2510-marathon-raid-003',
    'st-eve-2510-marathon-raid-004',
    'st-eve-2510-marathon-raid-005',
    'st-eve-2511-race-001',
    'st-eve-2511-race-002',
    'st-eve-2511-race-003',
    'st-eve-2511-race-004',
    'st-eve-2511-race-005',
    'st-eve-2512-dice-001',
    'st-eve-2512-dice-002',
    'st-eve-2512-dice-003',
    'st-eve-2601-race-001',
    'st-eve-2601-race-002',
    'st-eve-2601-race-003',
    'st-eve-2601-race-004',
    'st-eve-2601-race-005',
    'st-eve-2602-dice-001',
    'st-eve-2602-dice-002',
    'st-eve-2602-dice-003',
    'st-eve-2602-dice-004',
    'st-eve-2602-dice-005',
    'st-eve-2603-race-001',
    'st-eve-2603-race-002',
    'st-eve-2603-race-003',
    'st-eve-2603-race-004',
    'st-eve-2603-race-005',
    'st-eve-2604-dice-001',
    'st-eve-2604-dice-002',
    'st-eve-2604-dice-003',
    'st-eve-2604-dice-004',
    'st-eve-2604-dice-005',
    'st-eve-2605-marathon-raid-001',
    'st-eve-2605-marathon-raid-002',
    'st-eve-2605-marathon-raid-003',
    'st-eve-2606-dice-001',
    'st-eve-2606-dice-002',
    'st-eve-2606-dice-003',
    'st-eve-2606-dice-004',
    'st-eve-2606-dice-005',
    'st-eve-2607-marathon-raid-001',
    'st-eve-2607-marathon-raid-002',
    'st-eve-2607-marathon-raid-003',
    'st-eve-2607-marathon-raid-004',
    'st-eve-2607-marathon-raid-005',
))



def audit_story_semantics(stories, conditions, messages, telephones, items):
    """Audit only the fixed 425-story scope against a complete decoded cohort.

    Telephone is mandatory even when a payload omits its raw JSON. A compiler
    must decode that table for this audit; absence never means no dependencies.
    This function reads public definitions only and never changes game state.
    """
    import hashlib
    import json

    def need(value, code):
        if not value:
            raise ValueError(code)

    def identity(value):
        return (type(value) is str and 0 < len(value.encode("utf-8")) <= 512
                and all(ord(character) >= 32 for character in value))

    def index(rows):
        need(type(rows) is list and 0 < len(rows) <= 100000, "story_semantic_table_missing")
        result = {}
        for row in rows:
            need(type(row) is dict and identity(row.get("id"))
                 and row["id"] not in result, "story_semantic_identity_invalid")
            result[row["id"]] = row
        return result

    def fingerprint(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

    story_rows, condition_rows, item_rows = index(stories), index(conditions), index(items)
    message_rows, telephone_rows = index(messages), index(telephones)
    scope = NO_REWARD_STORIES | FREE_STONE_STORIES
    need(len(NO_REWARD_STORIES) == 143 and len(FREE_STONE_STORIES) == 282
         and len(scope) == 425 and not NO_REWARD_STORIES & FREE_STONE_STORIES,
         "story_semantic_rule_overlap")
    rewards = []
    for name in sorted(scope):
        expected = "" if name in NO_REWARD_STORIES else "rd_auto;stone;;30"
        need(name in story_rows and story_rows[name].get("rewardId", "") == expected,
             "story_semantic_reward_changed")
        rewards.append([name, expected])
    graph = {}
    for name, row in condition_rows.items():
        settings = row.get("settings")
        need(type(settings) is list and all(type(value) is dict for value in settings),
             "story_semantic_condition_invalid")
        dependencies, read_stories, item_ids = set(), set(), set()
        pending, nodes = list(settings), 0
        while pending:
            node = pending.pop()
            nodes += 1
            need(nodes <= 10000, "story_semantic_condition_bound")
            if type(node) is dict:
                if "readStory" in node:
                    entry = node["readStory"]
                    need(type(entry) is dict and identity(entry.get("storyId")),
                         "story_semantic_story_reference_invalid")
                    read_stories.add(entry["storyId"])
                for key, value in node.items():
                    if key in ("conditionId", "itemId"):
                        need(identity(value), "story_semantic_reference_invalid")
                        (dependencies if key == "conditionId" else item_ids).add(value)
                    elif type(value) in (dict, list):
                        pending.append(value)
            elif type(node) is list:
                pending.extend(node)
        graph[name] = (dependencies, read_stories, item_ids)
    roots = []
    for table, rows in (("Message", message_rows), ("Telephone", telephone_rows)):
        for name, row in sorted(rows.items()):
            condition = row.get("unlockConditionId", "")
            need(type(condition) is str and (not condition or identity(condition)),
                 "story_semantic_unlock_invalid")
            roots.append([table, name, condition])
    state, referenced_stories, referenced_items = {}, set(), set()
    for _, _, root in roots:
        if not root:
            continue
        pending = [(root, False)]
        while pending:
            name, exiting = pending.pop()
            if exiting:
                state[name] = 2
                continue
            if state.get(name) == 2:
                continue
            need(state.get(name) != 1, "story_semantic_condition_cycle")
            need(name in graph, "story_semantic_condition_missing")
            dependencies, read_stories, item_ids = graph[name]
            need(read_stories <= story_rows.keys(), "story_semantic_story_missing")
            need(item_ids <= item_rows.keys(), "story_semantic_item_missing")
            referenced_stories.update(read_stories)
            referenced_items.update(item_ids)
            state[name] = 1
            pending.append((name, True))
            pending.extend((value, False) for value in sorted(dependencies, reverse=True))
    need(not scope & referenced_stories, "story_semantic_narrative_dependency_changed")
    closure = [[name, sorted(graph[name][0]), sorted(graph[name][1]), sorted(graph[name][2])]
               for name in sorted(state)]
    return {"schema": 1, "scope_stories": len(scope), "no_reward_stories": len(NO_REWARD_STORIES),
            "free_stone_stories": len(FREE_STONE_STORIES), "message_rows": len(message_rows),
            "telephone_rows": len(telephone_rows), "condition_rows": len(condition_rows),
            "reachable_conditions": len(state), "read_story_references": len(referenced_stories),
            "supported_story_dependencies": 0, "item_references": len(referenced_items),
            "story_rewards_sha256": fingerprint(rewards),
            "condition_closure_sha256": fingerprint({"roots": roots, "closure": closure}),
            "item_references_sha256": fingerprint([item_rows[name] for name in sorted(referenced_items)])}
