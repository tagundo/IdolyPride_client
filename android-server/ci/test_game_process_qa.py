"""The observed native crash must end observation without fabricating UI results."""
from qa_game_boot import game_process_gone


def test_three_missing_pids_after_the_observed_native_crash_end_capture():
    records = [{"game_pid": "5060"}] * 59
    for missing in range(1, 4):
        assert game_process_gone(records + [{"game_pid": ""}] * missing) is (missing == 3)


def test_a_restarted_process_is_alive_and_resets_the_missing_window():
    assert not game_process_gone([{"game_pid": ""}, {"game_pid": ""}, {"game_pid": "9735"}])


def test_adb_capture_failure_is_not_classified_as_a_game_exit():
    assert not game_process_gone([{"game_pid": "", "png_error": "device offline"}] * 3)
    assert not game_process_gone([{"game_pid": ""}, {"game_pid": ""}, {"xml_error": "offline"}])
