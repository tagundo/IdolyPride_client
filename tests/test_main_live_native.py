"""Optional real native settlement smoke; no captured account or forced outcome.

IDOLY_LIVE_LIBRARY and IDOLY_LIVE_MASTER_DIR select locally built C ABI v1
and the audited canonical master bundle. Ordinary unit tests need neither.
"""
import os
import base64
import copy
from pathlib import Path
from unittest.mock import patch

from google.protobuf import message_factory
import pytest

from idoly_local.gameplay import seed_starter_profile
from idoly_local.live_engine import NativeLiveEngine
from idoly_local.main_live import MainLives
from idoly_local.schema import Schema
from idoly_local.state import State


def test_actual_native_first_live_and_transactional_retry(tmp_path):
    library, master = os.environ.get('IDOLY_LIVE_LIBRARY'), os.environ.get('IDOLY_LIVE_MASTER_DIR')
    if not library or not master:
        pytest.skip('Optional native live library and audited 39-table master are not configured')
    schema = Schema.from_descriptor_set(Path(__file__).resolve().parents[1] / 'data/protocol/idolypride-6.1.1.pb')
    state = State(tmp_path / 'state.db')
    seed_starter_profile(state, schema, 'player', Path(master))
    provider = MainLives(schema, state, 'player', Path(master), NativeLiveEngine(Path(library)), True)
    request = schema.request_type('/api.Quest/Start')(questId='qt-main-1-001-01', deckNumber=1,
        playCount=1, buddyDeckName='Local deck').SerializeToString()
    with patch('idoly_local.main_live.secrets.randbits', return_value=123456):
        first = provider.handle('/api.Quest/Start', request, '1')
    response = schema.response_type('/api.Quest/Start').FromString(first)
    # This is the previously independently checked stock live-v5 calculation,
    # not a score substituted by the Python provider.
    assert response.result.cleared and response.result.userInfos[0].userResult.score == 4781
    assert len(response.result.charts) == 183 and len(response.reward.clearRewards) == 4
    assert [r.exp for r in response.reward.rewardCards] == [40] * 5
    assert provider.handle('/api.Quest/Start', request, '1') == first
    with patch('idoly_local.main_live.secrets.randbits', return_value=123456):
        replay = schema.response_type('/api.Quest/Start').FromString(provider.handle('/api.Quest/Start', request, '2'))
    assert replay.result.cleared and not replay.reward.clearRewards and not replay.reward.rewardCards
    snapshot = schema.response_type('/api.User/Get').FromString(state.snapshot('player')[0])
    assert snapshot.user.managerExp == 50 and snapshot.user.managerLevel == 2
    assert snapshot.areas[0].clearQuestCount == 1
    assert len([row for row in snapshot.cards if row.totalExp == 40]) == 5
    restarted = MainLives(schema, State(state.path), 'player', Path(master), enabled=True)
    assert restarted.handle('/api.Quest/Start', request, '1') == first

    # A test-only negative control changes the *prepared calculator input*,
    # never inventory or production behavior, to prove Go-computed failure is
    # not converted into a successful Python settlement.
    state2 = State(tmp_path / 'failure.db')
    seed_starter_profile(state2, schema, 'failure', Path(master))
    actual = NativeLiveEngine(Path(library))
    class ZeroAttributes:
        def simulate(self, prepared):
            prepared = copy.deepcopy(prepared)
            cls = message_factory.GetMessageClass(schema.pool.FindMessageTypeByName('api.LiveUserInfo'))
            user = cls.FromString(base64.b64decode(prepared['proto']['UserInfo'][0]))
            for card in user.userDeck.cards:
                card.vocal = card.dance = card.visual = 0
            prepared['proto']['UserInfo'][0] = base64.b64encode(user.SerializeToString()).decode('ascii')
            return actual.simulate(prepared)
    failing = MainLives(schema, state2, 'failure', Path(master), ZeroAttributes(), True)
    before = state2.snapshot('failure')
    with patch('idoly_local.main_live.secrets.randbits', return_value=123456):
        failed_raw = failing.handle('/api.Quest/Start', request, '1')
    failed = schema.response_type('/api.Quest/Start').FromString(failed_raw)
    assert not failed.result.cleared and failed.result.userInfos[0].userResult.score == 0
    assert not failed.reward.clearRewards and not failed.reward.rewardCards
    assert state2.snapshot('failure') == before
