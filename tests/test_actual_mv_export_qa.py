"""Reject false positives in the actual Unity MV runtime verdict."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("actual_mv_qa", ROOT / "tools/run_actual_mv_export_qa.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


def test_activity_start_requires_the_actual_menu_activity():
    qa.verified_activity_start("Starting: Intent\nStatus: ok\nActivity: " + qa.MAIN + "\nComplete\n")


@pytest.mark.parametrize('value',[None,False,1,'true'])
def test_actual_runtime_requires_compiled_factory_preservation_receipt(value):
    evidence={'compiled_manifest_structure_preserved':True,'manifest_factory_and_activities_preserved':value}
    with pytest.raises(qa.Rejected,match='manifest_component_preservation'):
        qa.verified_observer_manifest(evidence)
    qa.verified_observer_manifest({'compiled_manifest_structure_preserved':True,'manifest_factory_and_activities_preserved':True})


def logrow(pid,tag,message,second=0):
    return f"11-22 00:49:{second:02d}.000 {pid:5d} {pid:5d} E {tag}: {message}"


def test_launch_history_keeps_failed_process_before_surviving_provider_restart():
    raw='\n'.join([
        logrow(580,'ActivityTaskManager','START u0 {cmp='+qa.MAIN+'} from uid 0',0),
        logrow(580,'ActivityManager','Start proc 4100:'+qa.PACKAGE+'/u0a210 for top-activity',1),
        logrow(4100,'TransactionExecutor','Failed to execute the transaction: ClientTransaction{',2),
        logrow(4100,'AndroidRuntime','FATAL EXCEPTION: main',2),
        logrow(4100,'AndroidRuntime','java.lang.NoClassDefFoundError: missing launch class',2),
        logrow(4100,'AndroidRuntime','    at android.app.ActivityThread.performLaunchActivity(ActivityThread.java:4000)',2),
        logrow(580,'am_crash','[0,4100,'+qa.PACKAGE+',538984005,java.lang.NoClassDefFoundError,missing]',2),
        logrow(580,'am_proc_died','[0,4100,'+qa.PACKAGE+',0]',3),
        logrow(580,'ActivityTaskManager','Force finishing activity '+qa.MAIN,3),
        *[logrow(700,'Unrelated','noise',4)for _ in range(200)],
        logrow(580,'am_proc_start','[0,4156,10210,'+qa.PACKAGE+',service,SDKProvider]',5),
        logrow(4156,'Provider','provider remains running',6),
    ])
    evidence=qa.launch_log_evidence(raw)
    assert evidence['observed_process_ids']==[4100,4156]
    assert [(event['kind'],event.get('pid'))for event in evidence['events']]==[
        ('activity_start_requested',None),('process_start',4100),('launch_transaction_failed',4100),('fatal_exception',4100),
        ('crash',4100),('process_died',4100),('activity_force_finished',None),('process_start',4156)]
    assert evidence['events'][0]['caller_uid']==0
    assert 'NoClassDefFoundError'in evidence['context']and'performLaunchActivity'in evidence['context']
    assert 'provider remains running'in evidence['context']


def test_launch_context_keeps_package_free_system_transaction_stack():
    raw='\n'.join([
        logrow(580,'ActivityManager','Start proc 4100:'+qa.PACKAGE+'/u0a210 for top-activity'),
        logrow(580,'ActivityTaskManager','Failed to launch activity: android.os.TransactionTooLargeException'),
        logrow(580,'ActivityTaskManager','    at android.app.servertransaction.ClientTransaction.schedule(ClientTransaction.java:1)'),
        logrow(580,'ActivityTaskManager','Force finishing activity '+qa.MAIN),
    ])
    context=qa.launch_log_evidence(raw)['context']
    assert 'TransactionTooLargeException'in context and'ClientTransaction.schedule'in context


def test_launch_context_redacts_account_fields_and_keeps_exception_type():
    raw='\n'.join([
        logrow(580,'ActivityManager','Start proc 4100:'+qa.PACKAGE+'/u0a210 for top-activity'),
        logrow(4100,'AndroidRuntime','java.lang.IllegalStateException: password=private-value account_id=9999'),
        logrow(4100,'Debug','Authorization: Bearer should-never-appear'),
        logrow(4100,'Debug','device_id=unique-device-value'),
    ])
    evidence=qa.launch_log_evidence(raw)
    assert evidence['redacted_records']==3
    for secret in('private-value','9999','should-never-appear','unique-device-value'):
        assert secret not in evidence['context']
    assert 'java.lang.IllegalStateException'in evidence['context']


def test_launch_context_requires_exact_package_and_bounded_input():
    evidence=qa.launch_log_evidence(logrow(580,'ActivityManager','Start proc 4100:'+qa.PACKAGE+'.other/u0a210'))
    assert not evidence['events']and not evidence['context']
    with pytest.raises(qa.Rejected,match='oversized'):
        qa.launch_log_evidence('x'*(4*1024*1024+1))


@pytest.mark.parametrize("raw,code", [
    ("Error type 3\nError: Activity class does not exist", "activity_start_rejected"),
    ("Starting: Intent\nStatus: timeout\n", "activity_start_rejected"),
    ("Status: ok\nActivity: org.idolypride.environmentprobe/.MainActivity\n", "activity_identity_mismatch"),
    ("Status: ok\n", "activity_identity_mismatch"),
    ("Status: ok\nActivity: " + qa.MAIN + "\nActivity: " + qa.MAIN + "\n", "activity_identity_mismatch"),
])
def test_adb_process_success_does_not_prove_activity_launch(raw, code):
    with pytest.raises(qa.Rejected, match=code):
        qa.verified_activity_start(raw)


def snapshot(frame=100, *, complete=False):
    return {"ok": True, "qa_only": True, "read_only": True, "native": {
        "schema": 1, "ready": True, "phase": "completed" if complete else "idle", "error_code": "none",
        "export_id": "e" * 32, "width": 256, "height": 144, "source_width": 256, "source_height": 144,
        "fps_num": 30, "fps_den": 1, "frames": 60 if complete else 0, "total_frames": 60,
        "capture_acks": 70 if complete else 10, "audio_frames": 96000, "total_audio_frames": 96000,
        "observation": {"schema": 1, "pipeline": "owned_native_clock", "source_valid": True, "source_kind": "photography_3d",
            "source_identity": "photography:opaque17", "source_time": 1.25, "source_paused": True,
            "playerloop_frame": frame, "coordinator_active": False, "native_clock_owned": False,
            "render_width": 256, "render_height": 144,
            "rendered_simulation_ticks": 119 if complete else 0,
            "restored_source_valid": complete, "restored_source_identity": "photography:opaque17",
            "restored_source_time": 1.25, "restored_source_paused": True,
            "native_clock_held": False, "simulation_tick": 118 if complete else None,
            "accepted_frames": 60 if complete else 0, "source_restored": complete,
            "clock_settings_restored": complete, "camera_audio_restored": complete,
            "dependent_state_restored": complete, "world_admission": "verified" if complete else "unverified"}}}


def probe():
    return {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 256, "height": 144,
        "avg_frame_rate": "30/1", "nb_read_frames": "60", "time_base": "1/15360"},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000", "duration": "2.0"}],
        "packets": [{"codec_type": "video", "pts": i * 512} for i in range(60)]}


def test_paused_game_source_requires_advancing_playerloop_then_full_restore():
    qa.validate_paused_source(snapshot(100), snapshot(102))
    state = qa.validate_completed(snapshot(100), snapshot(600, complete=True), 256, 144, 30)
    assert qa.validate_probe(probe(), state)["frames"] == 60


@pytest.mark.parametrize("field,value,error", [
    ("playerloop_frame", 100, "playerloop_suspended"),
    ("source_paused", False, "source_not_paused"),
    ("source_time", 1.26, "paused_timeline_advanced"),
    ("source_identity", "photography:different", "source_not_paused"),
    ("native_clock_owned", True, "baseline_already_owned"),
    ("pipeline", "screen_recording", "owned_native_pipeline"),
    ("source_kind", "synthetic_codec_probe", "normal_3d_source"),
    ("source_valid", False, "normal_3d_source"),
    ("source_identity", "0000000000000000", "normal_3d_source"),
    ("schema", True, "owned_native_pipeline"),
    ("source_time", float("nan"), "source_observation_invalid"),
])
def test_rejects_activity_suspend_synthetic_source_or_mutating_baseline(field, value, error):
    second = snapshot(102)
    second["native"]["observation"][field] = value
    with pytest.raises(qa.Rejected, match=error):
        qa.validate_paused_source(snapshot(100), second)


@pytest.mark.parametrize("field", ["source_restored", "clock_settings_restored", "camera_audio_restored", "dependent_state_restored"])
def test_cleanup_only_or_unverified_restore_is_not_a_pass(field):
    final = snapshot(600, complete=True)
    final["native"]["observation"][field] = False
    with pytest.raises(qa.Rejected, match=field):
        qa.validate_completed(snapshot(), final, 256, 144, 30)


@pytest.mark.parametrize("scope,field,value,error", [
    ("observation", "source_time", 1.5, "source_pause_position_not_restored"),
    ("observation", "source_identity", "photography:other", "source_pause_position_not_restored"),
    ("observation", "native_clock_owned", True, "native_scope_not_released"),
    ("observation", "accepted_frames", 59, "native_frame_count_differs"),
    ("observation", "simulation_tick", 119, "simulation_schedule_differs"),
    ("observation", "rendered_simulation_ticks", 118, "actual_simulation_draw_count"),
    ("native", "capture_acks", 69, "real_capture_ack_count_differs"),
    ("observation", "render_width", 1920, "actual_render_geometry"),
    ("native", "fps_den", True, "actual_render_geometry"),
    ("native", "audio_frames", 95999, "native_audio_not_complete"),
    ("native", "phase", "failed", "native_export_not_completed"),
])
def test_completed_native_counts_geometry_clock_and_state_are_independent_gates(scope, field, value, error):
    final = snapshot(600, complete=True)
    target = final["native"] if scope == "native" else final["native"]["observation"]
    target[field] = value
    with pytest.raises(qa.Rejected, match=error):
        qa.validate_completed(snapshot(), final, 256, 144, 30)


def test_restored_live_geometry_does_not_replace_the_captured_render_geometry():
    final = snapshot(600, complete=True)
    final["native"].update(source_width=1920, source_height=1080)
    qa.validate_completed(snapshot(), final, 256, 144, 30)
    del final["native"]["observation"]["render_width"]
    with pytest.raises(qa.Rejected, match="actual_render_geometry"):
        qa.validate_completed(snapshot(), final, 256, 144, 30)


def test_playing_source_may_continue_after_its_exact_native_restoration_checkpoint():
    before, final = snapshot(), snapshot(600, complete=True)
    before["native"]["observation"]["source_paused"] = False
    final["native"]["observation"].update(source_paused=False, source_time=1.7, restored_source_paused=False)
    qa.validate_completed(before, final, 256, 144, 30)
    final["native"]["observation"]["restored_source_time"] = 1.7
    with pytest.raises(qa.Rejected, match="native_source_restoration_checkpoint"):
        qa.validate_completed(before, final, 256, 144, 30)


def test_running_scope_needs_fresh_admission_and_monotonic_simulation_clock():
    current = snapshot()
    obs = current["native"]["observation"]
    obs.update(coordinator_active=True, native_clock_owned=True, world_admission="verified", simulation_tick=8)
    assert qa.validate_running(current, 6) == 8
    obs["world_admission"] = "cached"
    with pytest.raises(qa.Rejected, match="render_admission"):
        qa.validate_running(current, 6)
    obs["world_admission"] = "verified"
    with pytest.raises(qa.Rejected, match="rewound"):
        qa.validate_running(current, 10)


def test_native_clock_hold_requires_advancing_loop_without_timeline_progress():
    first, second = snapshot(100), snapshot(102)
    for payload in (first, second):
        payload["native"]["observation"].update(coordinator_active=True, native_clock_owned=True,
            native_clock_held=True, world_admission="verified", simulation_tick=8, accepted_frames=4)
    qa.validate_clock_hold(first, second)
    for key, value, code in (("source_time", 1.5, "timeline_advanced"),
                             ("playerloop_frame", 100, "playerloop_not_advancing"),
                             ("simulation_tick", 10, "frame_scope_changed"),
                             ("rendered_simulation_ticks", 1, "frame_scope_changed"),
                             ("native_clock_held", False, "hold_not_observed")):
        changed = deepcopy(second)
        changed["native"]["observation"][key] = value
        with pytest.raises(qa.Rejected, match=code):
            qa.validate_clock_hold(first, changed)


def test_native_overlay_pause_requires_acknowledgement_and_live_loop():
    first, second = snapshot(100), snapshot(102)
    for payload in (first, second):
        payload["native"].update(phase="paused", paused=True, pause_requested=True)
        payload["native"]["observation"].update(coordinator_active=True, native_clock_owned=True,
            native_clock_held=True, world_admission="verified", simulation_tick=8, accepted_frames=4)
    qa.validate_export_pause(first, second)
    second["native"]["phase"] = "pausing"
    with pytest.raises(qa.Rejected, match="not_acknowledged"):
        qa.validate_export_pause(first, second)


def test_queue_replay_restores_its_native_acquired_source_not_previous_init_sequence():
    before = snapshot(complete=True)
    replay = snapshot(200)
    replay["native"].update(phase="rendering", export_id="f" * 32)
    replay["native"]["observation"].update(acquired_source_valid=True, acquired_source_identity="1234567890abcdef",
        acquired_source_time=0.0, acquired_source_paused=False)
    baseline = qa.replay_acquisition_baseline(before, replay)
    assert baseline["native"]["observation"]["source_identity"] == "1234567890abcdef"
    assert baseline["native"]["observation"]["source_paused"] is False
    assert baseline["native"]["capture_acks"] == before["native"]["capture_acks"]
    assert before["native"]["observation"]["source_identity"] == "photography:opaque17"
    del replay["native"]["observation"]["acquired_source_time"]
    with pytest.raises(qa.Rejected, match="acquisition_baseline_unavailable"):
        qa.replay_acquisition_baseline(before, replay)


def test_encoded_packet_pts_must_match_rational_frame_schedule_even_with_decode_order_reordering():
    state = snapshot(complete=True)["native"]
    data = probe()
    data["packets"][0:2] = reversed(data["packets"][0:2])
    qa.validate_probe(data, state)
    data["packets"][3]["pts"] += 20
    with pytest.raises(qa.Rejected, match="rational_frame_steps"):
        qa.validate_probe(data, state)


@pytest.mark.parametrize("change,error", [
    (lambda p: p["streams"][0].update(width=1920), "encoded_geometry"),
    (lambda p: p["streams"][0].update(nb_read_frames="59"), "decoded_rate_or_count"),
    (lambda p: p["streams"][0].update(avg_frame_rate="30000/1001"), "decoded_rate_or_count"),
    (lambda p: p["streams"][1].update(channels=1), "encoded_audio_format"),
    (lambda p: p["streams"][1].update(duration="1.0"), "encoded_audio_duration"),
    (lambda p: p["packets"].pop(), "video_packet_count"),
])
def test_ffprobe_output_is_not_accepted_merely_because_mp4_is_decodable(change, error):
    data = probe()
    change(data)
    with pytest.raises(qa.Rejected, match=error):
        qa.validate_probe(data, snapshot(complete=True)["native"])


def test_all_runtime_labels_exist_in_current_android_resources():
    for name in ("launch_diagnostic_client", "mp4_fps", "mp4_codec", "mp4_bitrate", "mp4_bitrate_mbps", "mp4_output_resolution", "mp4_custom",
                 "mp4_width_pixels", "mp4_height_pixels", "mp4_queue_add", "mp4_queue_run", "mp4_save", "mp4_pause", "mp4_resume"):
        assert qa.labels(name)
