"""Optional public-master contract checks; no account, engine or VM inputs."""
from pathlib import Path

import pytest

from idoly_local.gameplay import _Catalog
from idoly_local.live_input import MASTER_VERSION, _chart, main_quest_definition
from idoly_local.main_live import MainLives


@pytest.fixture(scope='module')
def public_master():
    master = Path(__file__).resolve().parents[1] / 'data/master-json'
    required = ('Quest', 'Area', 'Music', 'Stage', 'Reward', 'Item', 'Accessory', 'Setting', 'MusicChartPattern')
    if not all((master / (table + '.json')).is_file() for table in required):
        pytest.skip('Optional audited public master JSON is unavailable')
    catalog = _Catalog(master)
    assert catalog.version() == MASTER_VERSION
    return master, catalog


@pytest.mark.parametrize('quest_id,song,goal,manager_exp,card_exp,reward_id,rewards', [
    ('qt-main-1-001-01', 'hsm-006', 3000, 50, 40, 'rd-main-quest-001-01',
     ((1, 'item-card_enhance', 290), (8, '', 500), (15, '', 50), (3, 'ac-1-visual-02', 1))),
    ('qt-main-1-001-02', 'sun-001', 5400, 65, 57, 'rd-main-quest-001-02',
     ((1, 'item-card_enhance', 590), (8, '', 500), (15, '', 50), (3, 'ac-1-vocal-02', 1))),
    ('qt-main-1-001-03', 'moon-004', 10000, 85, 74, 'rd-main-quest-001-03',
     ((1, 'item-card_enhance', 890), (8, '', 500), (15, '', 50), (1, 'item-photo_shooting-01', 1))),
])
def test_three_definitions_match_original_public_master_and_same_song_charts(
        public_master, quest_id, song, goal, manager_exp, card_exp, reward_id, rewards):
    master, catalog = public_master
    definition = main_quest_definition(quest_id)
    assert (definition.music_id, definition.chart_id, definition.reference_chart_id) == (
        'music-' + song, 'chart-' + song + '-002', 'chart-' + song + '-001')
    assert (definition.clear_score, definition.manager_exp, definition.card_exp,
            definition.reward_id, definition.rewards) == (goal, manager_exp, card_exp, reward_id, rewards)
    quest, area, _setting, validated = MainLives(None, None, 'unused', master)._definition(quest_id)
    assert validated == definition
    assert area['questIds'] == ['qt-main-1-001-01', 'qt-main-1-001-02', 'qt-main-1-001-03']
    assert quest['stageId'] == 'stage-live-house-00-00' and quest['liveSkipType'] == 2
    for identity in (definition.chart_id, definition.reference_chart_id):
        chart = _chart(catalog, identity)
        assert chart and {row['id'] for row in chart} == {identity}
