"""Safe Quest.Start rejection logs through the real application and HTTP/2."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import grpc
import pytest

from idoly_local import codec, h2_server
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.live_rejection_diagnostics import (
    QuestStartFacts, format_quest_start_rejection, quest_start_facts,
)
from idoly_local.rpc import RpcCode, RpcFailure

from test_main_live import QUEST, START, USER, current, dump, game, schema


CANARY = "PRIVATE-token-user-card-name-seed-987654321\nunsafe=1"
MODE = "Experimental main live: only the first main area with one ordinary saved-deck play is supported"


@pytest.fixture
def request_schema():
    """Independent wire types keep the privacy tests free of game assets."""
    file = descriptor_pb2.FileDescriptorProto(name="safe-live-test.proto", package="safe", syntax="proto3")
    buddy = file.message_type.add(name="Buddy")
    buddy.field.add(name="buddyUserId", number=1, type=9)
    request = file.message_type.add(name="Request")
    for number, (name, kind) in enumerate((('questId', 9), ('playCount', 5), ('isAuto', 8),
            ('isSkip', 8), ('useDailyTicket', 8), ('buddyDeckName', 9)), 1):
        request.field.add(name=name, number=number, type=kind)
    request.field.add(name="userBuddyDeckPositions", number=7, type=11, label=3, type_name=".safe.Buddy")
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("safe.Request"))
    return SimpleNamespace(request_type=lambda path: cls)


@pytest.mark.parametrize('detail,reason,label', [
    ("No local handler or response fixture for /api.Quest/Start", "no_handler_or_disabled", "처리기 없음 또는 꺼짐"),
    (MODE, "request_mode_unsupported", "모드 조건 미지원"),
    ("Experimental main live: only the first main quest with one ordinary saved-deck play is supported",
     "request_mode_unsupported", "첫 메인 영역"),
    ("Experimental main live: borrowed deck names are not supported", "deck_name_unsupported", "이름 불일치"),
    ("Local live input: this main quest is not supported", "quest_unsupported", "범위 밖의 퀘스트"),
    ("Local live input: quest conditions or live bonuses are not supported", "quest_bonus_unsupported", "보너스 미지원"),
    ("Local live input: live photo and accessory bonuses are not supported", "equipment_unsupported", "장비 미지원"),
    ("Local live input: live photos and Part2 accessories are not supported", "photo_or_part2_unsupported", "포토·Part2"),
    ("Local live input: this live accessory is not supported", "accessory_unsupported", "초기 두 종류 외"),
    ("Local live input: live accessories require unlearned owned live abilities", "accessory_ability_unsupported", "보유 라이브 능력"),
    ("Borrowed live decks are not available locally", "buddy_unsupported", "대여 버디 미지원"),
    ("Card enhancement: initial ability release is unsupported", "card_initial_ability_unsupported", "초기 능력"),
    ("Card enhancement: initial skill upgrade is unsupported", "card_initial_skill_unsupported", "초기 스킬"),
    ("Card enhancement: support, rank and evolution are not supported", "card_growth_unsupported", "진화 상태"),
    ("Card enhancement: changed card rarity is not supported", "card_rarity_unsupported", "레어리티"),
    ("Card enhancement: the next card release or skill upgrade is not supported", "card_release_unsupported", "강화 경계"),
    ("Card enhancement: current card has an unsupported parameter projection", "card_parameters_unsupported", "능력치"),
    ("Card enhancement: trained skills are not supported", "card_skill_training_unsupported", "스킬 훈련"),
    ("Card enhancement: learned abilities are not supported", "card_abilities_unsupported", "습득한 카드 능력"),
    ("Native live engine: " + CANARY, "native_unsupported", "네이티브 계산기"),
])
def test_fixed_symbols_and_korean_labels_never_copy_error_detail(detail, reason, label):
    result = format_quest_start_rejection(START, RpcCode.UNIMPLEMENTED, detail)
    assert result.startswith("live_rejection=" + reason + " · ") and label in result
    assert CANARY not in result and "987654321" not in result and "\n" not in result
    assert len("RPC " + START + " -> UNIMPLEMENTED [" + result + "]") < 400


@pytest.mark.parametrize('detail', [CANARY, "Native live engineX: " + CANARY, None, 123])
def test_unclassified_future_or_malformed_detail_is_fixed(detail):
    assert format_quest_start_rejection(START, RpcCode.UNIMPLEMENTED, detail) == (
        "live_rejection=unclassified · 알려진 거절 사유에 해당하지 않음")


@pytest.mark.parametrize('path,code', [('/api.Deck/Save', RpcCode.UNIMPLEMENTED),
    (START + '/' + CANARY, RpcCode.UNIMPLEMENTED), (START, RpcCode.INVALID_ARGUMENT),
    (START, RpcCode.UNAUTHENTICATED), (START, RpcCode.INTERNAL)])
def test_other_paths_and_status_logs_are_unchanged(path, code):
    assert format_quest_start_rejection(path, code, MODE) is None
    assert quest_start_facts(path, code, MODE, object(), b'') is None


@pytest.mark.parametrize('first,once', [(True, True), (False, False)])
def test_only_public_literal_categories_and_boolean_request_facts_are_retained(request_schema, first, once):
    request = request_schema.request_type(START)(questId=QUEST if first else CANARY,
        playCount=1 if once else 987654321, isAuto=True, isSkip=True, useDailyTicket=True,
        buddyDeckName=CANARY)
    request.userBuddyDeckPositions.add(buddyUserId=CANARY)
    raw = codec.encode(request.SerializeToString())
    before = request.SerializeToString()
    facts = quest_start_facts(START, RpcCode.UNIMPLEMENTED, MODE, request_schema, raw)
    assert facts == QuestStartFacts(first, once, True, True, True, True)
    assert request.SerializeToString() == before
    result = format_quest_start_rejection(START, RpcCode.UNIMPLEMENTED, MODE, facts)
    assert "quest=" + ("first_area" if first else "other") in result
    assert "play=" + ("one" if once else "other") in result
    assert "auto=1 skip=1 daily_ticket=1 buddy_positions=1" in result
    assert CANARY not in result and "987654321" not in result and "\n" not in result
    assert len(result) < 300


@pytest.mark.parametrize('quest_id,first_area', [
    ('qt-main-1-001-01', True), ('qt-main-1-001-02', True), ('qt-main-1-001-03', True),
    ('qt-main-1-002-01', False), ('qt-main-1-001-04', False), (CANARY, False),
])
def test_first_area_message_keeps_finite_safe_request_facts(request_schema, quest_id, first_area):
    detail = 'Experimental main live: only the first main area with one ordinary saved-deck play is supported'
    request = request_schema.request_type(START)(questId=quest_id, playCount=1, isAuto=True, buddyDeckName=CANARY)
    facts = quest_start_facts(START, RpcCode.UNIMPLEMENTED, detail, request_schema, codec.encode(request.SerializeToString()))
    assert facts == QuestStartFacts(first_area, True, True, False, False, False)
    text = format_quest_start_rejection(START, RpcCode.UNIMPLEMENTED, detail, facts)
    assert 'live_rejection=request_mode_unsupported' in text and 'auto=1' in text and CANARY not in text
    assert ('quest=first_area' if first_area else 'quest=other') in text
    assert quest_id not in text


def test_facts_are_not_parsed_for_native_unclassified_or_other_rejections():
    def forbidden(path):
        pytest.fail("diagnostics parsed a request outside the exact request-mode branch")
    schema = SimpleNamespace(request_type=forbidden)
    for detail in ("Native live engine: " + CANARY, CANARY,
            "Local live input: live photo and accessory bonuses are not supported"):
        assert quest_start_facts(START, RpcCode.UNIMPLEMENTED, detail, schema, b'') is None


@pytest.mark.parametrize('raw', [b'bad-encrypted-' + CANARY.encode(), codec.encode(b'\x0a\x80'),
    b'x' * (16 * 1024 * 1024 + 1), CANARY])
def test_malformed_or_oversized_input_only_produces_unavailable_facts(request_schema, raw):
    facts = quest_start_facts(START, RpcCode.UNIMPLEMENTED, MODE, request_schema, raw)
    assert facts is None
    assert format_quest_start_rejection(START, RpcCode.UNIMPLEMENTED, MODE, facts).endswith("facts=unavailable")


def test_empty_protobuf_is_a_valid_default_request_not_a_parse_error(request_schema):
    assert quest_start_facts(START, RpcCode.UNIMPLEMENTED, MODE, request_schema, b'') == (
        QuestStartFacts(False, False, False, False, False, False))


@pytest.mark.parametrize('facts', [CANARY, {'first_area': CANARY},
    QuestStartFacts(CANARY, True, False, False, False, False),
    QuestStartFacts(True, True, 1, False, False, False)])
def test_invalid_context_facts_cannot_inject_text(facts):
    result = format_quest_start_rejection(START, RpcCode.UNIMPLEMENTED, MODE, facts)
    assert result.endswith("facts=unavailable") and CANARY not in result


@contextmanager
def connected(game, directory, *, enabled=True, callback=None):
    application = Application(game.schema, game.state, FixtureStore(directory, game.schema),
        profile='player', master_dir=game.master, experimental_main_live=enabled, live_engine=game.engine)
    server = h2_server.create_server(application, port=0, log_callback=callback).start()
    try:
        with grpc.insecure_channel(f'127.0.0.1:{server.port}') as channel:
            grpc.channel_ready_future(channel).result(timeout=3)
            def invoke(path=START, **values):
                args = dict(questId=QUEST, deckNumber=1, playCount=1, buddyDeckName='Saved unit')
                args.update(values)
                raw = game.schema.request_type(path)(**args).SerializeToString() if path == START else b''
                call = channel.unary_unary(path, request_serializer=codec.encode, response_deserializer=codec.decode)
                return call(raw, metadata=(('x-auth-token', game.token), ('x-app-request-id', '1'),
                    ('safe-canary', 'PRIVATE-metadata-token')), timeout=5)
            yield invoke
    finally:
        server.stop()


@pytest.mark.parametrize('enabled,values,detail,reason', [
    (False, {}, "No local handler or response fixture for /api.Quest/Start", "no_handler_or_disabled"),
    (True, {'isAuto': True, 'isSkip': True}, MODE, "request_mode_unsupported"),
    (True, {'questId': 'qt-main-1-001-02', 'isAuto': True}, MODE, "request_mode_unsupported"),
    (True, {'questId': 'qt-main-1-001-03', 'useDailyTicket': True}, MODE, "request_mode_unsupported"),
    (True, {'questId': CANARY}, MODE, "request_mode_unsupported"),
    (True, {'buddyDeckName': CANARY}, "Experimental main live: borrowed deck names are not supported", "deck_name_unsupported"),
])
def test_actual_application_h2_preserves_wire_error_and_complete_state(game, tmp_path, enabled, values, detail, reason):
    logs, before = [], dump(game)
    snapshot = current(game)
    private_values = [CANARY, game.token, snapshot.userPublic.serverUserId, snapshot.userPublic.publicUserId,
        snapshot.user.name, *[card.cardId for card in snapshot.cards], 'PRIVATE-metadata-token']
    with connected(game, tmp_path / 'fixtures', enabled=enabled, callback=logs.append) as invoke:
        with pytest.raises(grpc.RpcError) as error:
            invoke(**values)
        assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED and error.value.details() == detail
        assert dump(game) == before and not game.engine.calls
    line = next(line for line in logs if line.startswith('RPC ' + START))
    assert 'live_rejection=' + reason in line and len(line) < 400
    assert not any(value in line for value in private_values)
    if values.get('isAuto'):
        assert ('auto=1 skip=' + str(int(bool(values.get('isSkip'))))
                + ' daily_ticket=0 buddy_positions=0') in line
    if values.get('useDailyTicket'):
        assert 'daily_ticket=1' in line
    if values.get('questId') in ('qt-main-1-001-02', 'qt-main-1-001-03'):
        assert 'quest=first_area' in line and values['questId'] not in line
    elif 'questId' in values:
        assert 'quest=other' in line


def test_native_detail_callback_failure_and_other_rpc_logs_remain_safe(game, tmp_path, monkeypatch):
    def reject(prepared):
        raise RpcFailure(RpcCode.UNIMPLEMENTED, 'Native live engine: ' + CANARY)
    monkeypatch.setattr(game.engine, 'simulate', reject)
    logs, before = [], dump(game)
    def failing_callback(line):
        logs.append(line)
        raise RuntimeError(CANARY)
    with connected(game, tmp_path / 'fixtures', callback=failing_callback) as invoke:
        with pytest.raises(grpc.RpcError) as error:
            invoke()
        assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED
        assert error.value.details() == 'Native live engine: ' + CANARY
        with pytest.raises(grpc.RpcError) as other:
            invoke('/api.Gacha/List')
        assert other.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert dump(game) == before
    assert any('live_rejection=native_unsupported' in line for line in logs)
    assert 'RPC /api.Gacha/List -> UNIMPLEMENTED' in logs
    assert all(CANARY not in line and 'PRIVATE-metadata-token' not in line for line in logs)


def test_concurrent_request_facts_are_isolated_and_do_not_change_state(game, tmp_path):
    logs, before = [], dump(game)
    with connected(game, tmp_path / 'fixtures', callback=logs.append) as invoke:
        def reject(number):
            with pytest.raises(grpc.RpcError) as error:
                invoke(isAuto=True, isSkip=bool(number % 2))
            assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED and error.value.details() == MODE
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(reject, range(12)))
    lines = [line for line in logs if line.startswith('RPC ' + START)]
    assert len(lines) == 12
    assert sum('auto=1 skip=1 ' in line for line in lines) == 6
    assert sum('auto=1 skip=0 ' in line for line in lines) == 6
    assert dump(game) == before and not game.engine.calls


@pytest.mark.parametrize('hook', ['quest_start_facts', 'format_quest_start_rejection'])
def test_diagnostic_hook_failures_cannot_replace_original_rpc_or_write_state(game, tmp_path, monkeypatch, hook):
    def broken(*args, **kwargs):
        raise RuntimeError(CANARY)
    monkeypatch.setattr(h2_server, hook, broken)
    logs, before = [], dump(game)
    with connected(game, tmp_path / 'fixtures', callback=logs.append) as invoke:
        with pytest.raises(grpc.RpcError) as error:
            invoke(isAuto=True)
        assert error.value.code() == grpc.StatusCode.UNIMPLEMENTED and error.value.details() == MODE
    assert dump(game) == before and not game.engine.calls
    assert all(CANARY not in line for line in logs)
    if hook == 'quest_start_facts':
        assert any('facts=unavailable' in line for line in logs)
    else:
        assert 'RPC /api.Quest/Start -> UNIMPLEMENTED' in logs
