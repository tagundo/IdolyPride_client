"""Reject false positives in the actual Unity MV runtime verdict."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

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



def test_launch_budget_prioritizes_failed_activity_stack_over_earlier_settings_flood():
    raw="\n".join([
        *[logrow(580,'PackageManager','index '+qa.PACKAGE+' '+('SettingsNoise '*70),0) for _ in range(1200)],
        logrow(580,'ActivityManager','Start proc 4100:'+qa.PACKAGE+'/u0a210 for top-activity',1),
        logrow(4100,'TransactionExecutor','Failed to execute the transaction: ClientTransaction{',2),
        logrow(4100,'AndroidRuntime','FATAL EXCEPTION: main',2),
        logrow(4100,'AndroidRuntime','java.lang.NoClassDefFoundError: MainActivity linkage',2),
        logrow(4100,'AndroidRuntime','    at android.app.ActivityThread.performLaunchActivity(ActivityThread.java:4000)',2),
        logrow(580,'am_crash','[0,4100,'+qa.PACKAGE+',538984005,java.lang.NoClassDefFoundError,missing]',3),
        logrow(580,'ActivityTaskManager','Force finishing activity '+qa.MAIN,3),
        *[logrow(4156,'Provider','restart noise '+('x'*256),4) for _ in range(1000)],
        logrow(580,'am_proc_start','[0,4156,10210,'+qa.PACKAGE+',service,SDKProvider]',5),
    ])
    evidence=qa.launch_log_evidence(raw)
    assert evidence['observed_process_ids']==[4100,4156]
    assert evidence['omitted_context_records']>0
    context=evidence['context']
    assert len(context.encode('utf-8'))<=128*1024
    for fragment in ('FATAL EXCEPTION: main','NoClassDefFoundError: MainActivity linkage',
                     'performLaunchActivity','Failed to execute the transaction','Force finishing activity'):
        assert fragment in context
    assert context.index('Start proc 4100')<context.index('FATAL EXCEPTION')<context.index('Force finishing')

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


PERMISSION_COMPONENT = "com.google.android.permissioncontroller/" + qa.PERMISSION_ACTIVITY


def permission_start(component=PERMISSION_COMPONENT):
    # Android 13+ am -W reports the system interruption instead of MAIN.
    return ("Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp="
            + qa.MAIN + " }\nStatus: ok\nLaunchState: COLD\nActivity: " + component + "\nComplete\n")


def activity_context(component=PERMISSION_COMPONENT, caller=qa.PACKAGE, token="f298d76", hist_gap="  "):
    return (f"  topResumedActivity=ActivityRecord{{{token} u0 {component} t9}}\n"
            f"    * Hist{hist_gap}#1: ActivityRecord{{{token} u0 {component} t9}}\n"
            f"      launchedFromUid=10210 launchedFromPackage={caller} userId=0\n"
            "      Intent { act=android.content.pm.action.REQUEST_PERMISSIONS (has extras) }\n"
            f"    * Hist{hist_gap}#0: ActivityRecord{{485ba61 u0 {qa.MAIN} t9}}\n"
            "      launchedFromUid=0 launchedFromPackage=null userId=0\n")


def permission_ui(message="Allow 아이프라 로컬 to send you notifications?"):
    tree = ET.Element("hierarchy")
    package = PERMISSION_COMPONENT.split("/")[0]
    ET.SubElement(tree, "node", {"package": package, "resource-id": "com.android.permissioncontroller:id/permission_message",
                               "text": message, "class": "android.widget.TextView"})
    ET.SubElement(tree, "node", {"package": package, "resource-id": "com.android.permissioncontroller:id/permission_allow_button",
                               "text": "Allow", "class": "android.widget.Button", "enabled": "true", "clickable": "true",
                               "bounds": "[120,240][280,320]"})
    return tree


def main_ui(server="status_running"):
    tree = ET.Element("hierarchy")
    ET.SubElement(tree, "node", {"package": qa.PACKAGE, "class": "android.widget.Button", "enabled": "true",
                               "clickable": "true", "text": sorted(qa.labels("launch_diagnostic_client"))[0],
                               "bounds": "[20,400][500,460]"})
    # The real Main UI always shows the embedded server status and its Start control.
    ET.SubElement(tree, "node", {"package": qa.PACKAGE, "class": "android.widget.TextView", "enabled": "true",
                               "clickable": "false", "text": sorted(qa.labels(server))[0], "bounds": "[20,100][500,160]"})
    ET.SubElement(tree, "node", {"package": qa.PACKAGE, "class": "android.widget.Button",
                               "enabled": "false" if server == "status_running" else "true", "clickable": "true",
                               "text": sorted(qa.labels("start_server"))[0], "bounds": "[20,170][260,240]"})
    return tree


def main_lifecycle(*states):
    return "observer_registered\n" + "".join(
        f"{46346 + index} server {state} finishing=false destroyed=false\n" for index, state in enumerate(states))


def test_notification_activity_result_only_defers_the_actual_main_verdict():
    raw = permission_start()
    with pytest.raises(qa.Rejected, match="activity_identity_mismatch"):
        qa.verified_activity_start(raw)
    assert qa.verified_activity_start(raw, notification_interruption=True) is True
    assert qa.verified_activity_start("Status: ok\nActivity: " + qa.MAIN + "\n",
                                      notification_interruption=True) is False
    # System foreground and a lookalike Main button are not Main readiness.
    assert qa.launcher_main_control(main_ui(), activity_context(), main_lifecycle("created", "started", "resumed")) is None


@pytest.mark.parametrize("change", [
    lambda raw: raw.replace("cmp=" + qa.MAIN, "cmp=org.other/.MainActivity"),
    lambda raw: raw.replace("act=android.intent.action.MAIN", "act=android.intent.action.VIEW"),
    lambda raw: raw.replace("cat=[android.intent.category.LAUNCHER]", "cat=[android.intent.category.DEFAULT]"),
    lambda raw: raw.replace("Starting: Intent", "Intent"),
    lambda raw: raw + "Starting: Intent { cmp=" + qa.MAIN + " }\n",
])
def test_notification_interruption_still_requires_the_exact_requested_main_intent(change):
    with pytest.raises(qa.Rejected, match="requested_main_unverified"):
        qa.verified_activity_start(change(permission_start()), notification_interruption=True)


@pytest.mark.parametrize("component", [
    "org.other/" + qa.PERMISSION_ACTIVITY,
    "com.google.android.permissioncontroller/.OtherActivity",
    "com.android.settings/.Settings",
])
def test_unrelated_reported_activity_cannot_use_the_permission_exception(component):
    with pytest.raises(qa.Rejected, match="activity_identity_mismatch"):
        qa.verified_activity_start(permission_start(component), notification_interruption=True)


def test_duplicate_activity_start_status_is_not_success():
    with pytest.raises(qa.Rejected, match="activity_start_rejected"):
        qa.verified_activity_start(permission_start() + "Status: timeout\n", notification_interruption=True)


def test_notification_permission_uses_observed_system_control_with_independent_target_identity():
    tree = permission_ui("Allow \u2068아이프라 로컬\u2069 to send you notifications?")
    assert qa.notification_permission_control(tree, activity_context()) is tree[1]
    # App labels can collide; the system caller package must be the exact target.
    with pytest.raises(qa.Rejected, match="permission_target_unverified"):
        qa.notification_permission_control(tree, activity_context(caller=qa.PACKAGE + ".other"))


@pytest.mark.parametrize("gap", [" ", "  ", "\t", " \t "])
def test_notification_target_hist_record_accepts_actual_horizontal_spacing(gap):
    tree = permission_ui()
    assert qa.notification_permission_control(tree, activity_context(hist_gap=gap)) is tree[1]


def test_notification_hist_record_cannot_cross_lines_to_borrow_another_target():
    with pytest.raises(qa.Rejected, match="permission_target_unverified"):
        qa.notification_permission_control(permission_ui(), activity_context(hist_gap="\n  "))


@pytest.mark.parametrize("message", [
    "Allow 아이프라 로컬 to take pictures and record video?", "Allow 아이프라 로컬 to record audio?",
    "Allow 아이프라 로컬 to access this device's location?", "Allow", "알림을 허용하시겠습니까?",
])
def test_generic_allow_and_other_runtime_groups_are_not_notification_consent(message):
    with pytest.raises(qa.Rejected, match="permission_kind_unverified"):
        qa.notification_permission_control(permission_ui(message), activity_context())


@pytest.mark.parametrize("mutation,error", [
    (lambda tree: tree.append(deepcopy(tree[1])), "permission_control_ambiguous"),
    (lambda tree: tree.append(deepcopy(tree[0])), "permission_kind_unverified"),
    (lambda tree: tree[1].set("enabled", "false"), "permission_control_ambiguous"),
    (lambda tree: tree[1].set("resource-id", "org.other:id/permission_allow_button"), "permission_control_ambiguous"),
    (lambda tree: tree[0].set("resource-id", "org.other:id/permission_message"), "permission_kind_unverified"),
])
def test_permission_ui_must_have_one_real_enabled_system_control(mutation, error):
    tree = permission_ui()
    mutation(tree)
    with pytest.raises(qa.Rejected, match=error):
        qa.notification_permission_control(tree, activity_context())


def test_unrelated_system_overlay_is_neither_dismissed_nor_main_readiness():
    tree = ET.fromstring('<hierarchy><node package="android" text="Pixel Launcher isn\'t responding"/>'
                         '<node package="android" text="Close app" resource-id="android:id/aerr_close"/></hierarchy>')
    assert qa.notification_permission_control(tree, activity_context()) is None
    assert qa.launcher_main_control(tree, activity_context(), main_lifecycle("created", "started", "resumed", "paused")) is None
    wrong_token = activity_context().replace("* Hist  #1: ActivityRecord{f298d76", "* Hist  #1: ActivityRecord{other")
    with pytest.raises(qa.Rejected, match="permission_target_unverified"):
        qa.notification_permission_control(permission_ui(), wrong_token)


@pytest.mark.parametrize("states", [
    ("created", "started", "resumed", "paused"), ("resumed",), ("started", "created", "resumed"),
    ("created", "started", "resumed", "destroyed", "precreated", "created", "started"),
])
def test_main_readiness_needs_the_current_incarnation_resumed_with_real_ui(states):
    assert qa.launcher_main_control(main_ui(), activity_context(qa.MAIN), main_lifecycle(*states)) is None


def test_main_lifecycle_and_observed_ui_are_both_required_after_permission():
    tree = main_ui()
    current = main_lifecycle("precreated", "created", "started", "resumed", "paused", "resumed")
    assert qa.launcher_main_control(tree, activity_context(qa.MAIN), current) is tree[0]
    assert qa.launcher_main_control(tree, activity_context(qa.MAIN), current.replace("destroyed=false", "destroyed=true")) is None
    tree[0].set("package", qa.PACKAGE + ".other")
    assert qa.launcher_main_control(tree, activity_context(qa.MAIN), current) is None
    tree[0].set("package", qa.PACKAGE)
    tree.append(deepcopy(tree[0]))
    with pytest.raises(qa.Rejected, match="launch_control_ambiguous"):
        qa.launcher_main_control(tree, activity_context(qa.MAIN), current)


@pytest.mark.parametrize("wrong_permission", [False, True])
def test_normal_launcher_handles_only_notification_ui_then_reverifies_resumed_main(tmp_path, wrong_permission):
    permission = permission_ui("Allow 아이프라 로컬 to record audio?" if wrong_permission else
                               "Allow 아이프라 로컬 to send you notifications?")
    launcher = main_ui()

    class ObservedDevice:
        phase = 0

        def __init__(self):
            self.commands, self.touches = [], []

        def identity(self):
            return {"serial": "emulator-fixture"}

        def adb(self, *args, **kwargs):
            self.commands.append(args)
            if args[:5] == ("shell", "am", "start", "-W", "-a"):
                return permission_start()
            if args == ("shell", "dumpsys", "activity", "activities"):
                return activity_context() if self.phase == 0 else activity_context(qa.MAIN)
            if args[:4] == ("shell", "run-as", qa.PACKAGE, "cat"):
                return main_lifecycle("precreated", "created", "started", "resumed", "paused", "resumed")
            return ""

        def android(self):
            return permission if self.phase == 0 else launcher

        def touch(self, node):
            assert node is (permission[1] if self.phase == 0 else launcher[0])
            self.touches.append(node)
            self.phase += 1

    run = qa.ActualRun.__new__(qa.ActualRun)
    run.args = SimpleNamespace(apk=tmp_path / "actual.apk", startup_timeout=10)
    run.proof, run.report, run.journal = tmp_path, {}, []
    run.device = ObservedDevice()
    run.capture_launch_evidence = lambda stage: ""
    run.handle_dialog = lambda snapshot: False
    run.ui = SimpleNamespace(UiExplorer=lambda device: SimpleNamespace(_snapshot=lambda: {"ok": True}),
                             _home_role=lambda snapshot, role: True)

    def wait(action, timeout, code):
        for _ in range(3):
            result = action()
            if result is not None and result is not False:
                return result
        raise qa.Rejected(code)
    run.wait = wait
    if wrong_permission:
        with pytest.raises(qa.Rejected, match="permission_kind_unverified"):
            run.launch()
        assert not run.device.touches and not run.report.get("launcher_main_verified")
        return
    run.launch()
    assert run.device.touches == [permission[1], launcher[0]]
    assert run.report["launcher_main_verified"] and run.report["game_boot_verified"]
    assert [event["phase"] for event in run.journal] == ["unified_launcher_start_requested",
        "unified_launcher_notification_interruption_reported", "fresh_qa_notification_permission_allowed",
        "embedded_server_already_running", "unified_launcher_start_accepted"]
    assert (tmp_path / "notification-permission-ui.xml").read_text() == ET.tostring(permission, encoding="unicode")
    assert (tmp_path / "launcher-main-lifecycle.txt").is_file()
    assert ("shell", "am", "start", "-W", "-a", "android.intent.action.MAIN", "-c",
            "android.intent.category.LAUNCHER", "-n", qa.MAIN) in run.device.commands
    assert not any("grant" in command or "appops" in command or "settings" in command
                   for command in run.device.commands)


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


def playing_snapshot(frame=100, seconds=1.25):
    value = snapshot(frame)
    value["native"]["observation"].update(source_identity="1234567890abcdef",
        source_time=seconds, source_paused=False)
    return value


def test_normal_mv_playback_does_not_depend_on_an_in_game_pause_control_or_export_readiness():
    first, second = playing_snapshot(), playing_snapshot(102, 1.5)
    first["native"]["ready"] = second["native"]["ready"] = False
    assert qa.validate_playing_source(first, second)["source_time"] == 1.5


@pytest.mark.parametrize("field,value,error", [
    ("source_paused", True, "source_not_playing"),
    ("source_identity", "different", "source_not_playing"),
    ("playerloop_frame", 100, "playing_source_playerloop"),
    ("source_time", 1.25, "playing_source_timeline"),
    ("source_time", 1.0, "playing_source_timeline"),
    ("native_clock_owned", True, "baseline_already_owned"),
    ("coordinator_active", True, "baseline_already_owned"),
])
def test_playing_source_observation_rejects_a_suspended_loop_or_held_export(field, value, error):
    second = playing_snapshot(102, 1.5)
    second["native"]["observation"][field] = value
    with pytest.raises(qa.Rejected, match=error):
        qa.validate_playing_source(playing_snapshot(), second)


def test_open_mv_uses_the_real_view_route_without_searching_for_a_pause_button(tmp_path):
    run = qa.ActualRun.__new__(qa.ActualRun)
    run.args = SimpleNamespace(song_label="Bittersweet Echo")
    run.proof, run.report, run.journal = tmp_path, {}, []
    run.explorer = SimpleNamespace(_snapshot=lambda: {"ok": True}, _tap=lambda snap, node, role, index: True)
    run.ui = SimpleNamespace(_home_role=lambda snap, role: {"name": "Idols"}, notice_close_target=lambda s: None,
                             manager_level_close_target=lambda s: None, lesson_reward_close_target=lambda s: None,
                             download_confirmation=lambda s: None)
    routes, shots = [], []
    run.unity_touch = lambda *args: None
    run.route = lambda pattern, *args, **kwargs: routes.append(pattern)
    run.device = SimpleNamespace(screenshot=shots.append)
    first, second = playing_snapshot(), playing_snapshot(102, 1.5)
    first["native"]["ready"] = second["native"]["ready"] = False
    payloads = iter((first, second))
    run.mp4 = lambda: next(payloads)
    run.wait = lambda action, timeout, code: action()
    assert run.open_mv() is second
    assert routes and not any("Pause" in route or "一時停止" in route or "정지" in route for route in routes)
    assert shots == ["real-mv-playing"]
    assert run.report["actual_mv_verified"] is True
    assert run.journal[-1]["phase"] == "real_mv_playing"


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
    baseline = qa.export_acquisition_baseline(before, replay, replay=True)
    assert baseline["native"]["observation"]["source_identity"] == "1234567890abcdef"
    assert baseline["native"]["observation"]["source_paused"] is False
    assert baseline["native"]["capture_acks"] == before["native"]["capture_acks"]
    assert before["native"]["observation"]["source_identity"] == "photography:opaque17"
    del replay["native"]["observation"]["acquired_source_time"]
    with pytest.raises(qa.Rejected, match="acquisition_baseline_unavailable"):
        qa.export_acquisition_baseline(before, replay, replay=True)


def test_direct_export_restores_its_actual_acquisition_after_time_spent_in_server_settings():
    before = playing_snapshot(seconds=1.25)
    current = playing_snapshot(150, 30.75)
    current["native"].update(phase="rendering", export_id="f" * 32)
    current["native"]["observation"].update(acquired_source_valid=True,
        acquired_source_identity="1234567890abcdef", acquired_source_time=30.75,
        acquired_source_paused=False)
    acquired = qa.export_acquisition_baseline(before, current)
    assert before["native"]["observation"]["source_time"] == 1.25
    assert acquired["native"]["observation"]["source_time"] == 30.75
    final = snapshot(600, complete=True)
    final["native"]["observation"].update(source_identity="1234567890abcdef", source_time=31.0,
        source_paused=False, restored_source_identity="1234567890abcdef",
        restored_source_time=30.75, restored_source_paused=False)
    qa.validate_restored(acquired, final)
    with pytest.raises(qa.Rejected, match="restoration_checkpoint"):
        qa.validate_restored(before, final)
    current["native"]["observation"]["acquired_source_identity"] = "fedcba0987654321"
    with pytest.raises(qa.Rejected, match="direct_export_source_identity_changed"):
        qa.export_acquisition_baseline(before, current)


def test_direct_export_returns_the_acquired_checkpoint_to_the_later_save_and_replay_checks(tmp_path, monkeypatch):
    before = playing_snapshot(seconds=1.25)
    rendering = playing_snapshot(150, 30.75)
    rendering["native"].update(phase="rendering", export_id="f" * 32)
    rendering["native"]["observation"].update(coordinator_active=True, native_clock_owned=True,
        world_admission="verified", simulation_tick=2, accepted_frames=2, rendered_simulation_ticks=3,
        acquired_source_valid=True, acquired_source_identity="1234567890abcdef",
        acquired_source_time=30.75, acquired_source_paused=False)
    final = snapshot(600, complete=True)
    final["native"]["export_id"] = "f" * 32
    final["native"]["observation"].update(source_identity="1234567890abcdef", source_time=31.0,
        source_paused=False, restored_source_identity="1234567890abcdef",
        restored_source_time=30.75, restored_source_paused=False)
    run = qa.ActualRun.__new__(qa.ActualRun)
    run.args = SimpleNamespace(width=256, height=144, fps=30)
    run.proof, run.report, run.journal = tmp_path, {}, []
    run.export_deadline = qa.time.monotonic() + 10
    run.device = SimpleNamespace(adb=lambda *args, **kwargs: "4000")
    payloads = iter((rendering, final))
    run.mp4 = lambda: next(payloads)
    run.exercise_export_pause = lambda: run.report.update(native_overlay_pause_resume_verified=True,
        native_clock_hold_with_advancing_playerloop_verified=True)
    monkeypatch.setattr(qa.time, "sleep", lambda _: None)
    actual, acquired = run.await_export(before)
    assert actual is final and acquired["native"]["observation"]["source_time"] == 30.75
    assert run.journal[0]["phase"] == "native_direct_acquisition_baseline"
    qa.validate_restored(acquired, actual)


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


# --- redroid (native ARM64 container) guest: explicit option, default unchanged ---

def test_default_guest_keeps_the_exact_emulator_serial_contract(tmp_path):
    assert qa.Device("adb", "emulator-5554", tmp_path).guest == qa.TRANSLATED_GUEST
    for serial in ("127.0.0.1:15555", "localhost:15555", "emulator-", "emulator-5554 ", "R58M12345"):
        with pytest.raises(qa.Rejected, match="disposable_emulator_serial_required"):
            qa.Device("adb", serial, tmp_path)


@pytest.mark.parametrize("serial", ["127.0.0.1:15555", "localhost:15555", "127.0.0.1:5555"])
def test_redroid_guest_accepts_only_its_loopback_adb_transport(tmp_path, serial):
    device = qa.Device("adb", serial, tmp_path, qa.REDROID_GUEST)
    assert device.base == ["adb", "-s", serial] and device.guest == qa.REDROID_GUEST


@pytest.mark.parametrize("serial", ["emulator-5554", "192.168.1.20:5555", "10.0.2.2:5555", "127.0.0.2:15555",
                                    "127.0.0.1", "127.0.0.1:1", "R58M12345", "localhost:15555\n"])
def test_redroid_guest_rejects_emulator_lan_and_physical_serials(tmp_path, serial):
    with pytest.raises(qa.Rejected, match="disposable_redroid_loopback_serial_required"):
        qa.Device("adb", serial, tmp_path, qa.REDROID_GUEST)


def test_unknown_guest_kind_is_rejected(tmp_path):
    with pytest.raises(qa.Rejected, match="qa_guest_kind_invalid"):
        qa.Device("adb", "emulator-5554", tmp_path, "cuttlefish")


def redroid_properties(**changes):
    values = {"ro.hardware": "redroid", "ro.boot.hardware": "redroid", "ro.product.device": "redroid_arm64_only",
              "ro.product.cpu.abi": "arm64-v8a", "ro.product.cpu.abilist": "arm64-v8a",
              "ro.dalvik.vm.native.bridge": "0", "ro.kernel.qemu": "", "ro.hardware.egl": "angle",
              "ro.hardware.vulkan": "pastel", "ro.hardware.gralloc": "redroid", "debug.stagefright.ccodec": "4",
              "uname_machine": "aarch64"}
    values.update(changes)
    return values


class PropertyDevice(qa.Device):
    def __init__(self, tmp_path, guest, values):
        super().__init__("adb", "127.0.0.1:15555" if guest == qa.REDROID_GUEST else "emulator-5554", tmp_path, guest)
        self.values, self.commands = values, []

    def adb(self, *args, **kwargs):
        self.commands.append(args)
        if args[:2] == ("shell", "getprop"):
            return self.values.get(args[2], "") + "\n"
        if args == ("shell", "uname", "-m"):
            return self.values.get("uname_machine", "") + "\n"
        if args[:2] == ("shell", "sha256sum"):
            if "libndk_translation" not in self.values:
                raise qa.Rejected("adb_operation_failed_shell")
            return "a" * 64 + "  /system/lib64/libndk_translation.so\n"
        return ""


def test_redroid_identity_records_native_gpu_codec_stack_without_a_translator_hash(tmp_path):
    device = PropertyDevice(tmp_path, qa.REDROID_GUEST, redroid_properties())
    identity = device.identity()
    assert identity["guest"] == "redroid" and identity["ro.hardware.egl"] == "angle"
    assert identity["debug.stagefright.ccodec"] == "4" and identity["uname_machine"] == "aarch64"
    assert "native_bridge_sha256" not in identity
    assert not any(command[:2] == ("shell", "sha256sum") for command in device.commands)


@pytest.mark.parametrize("change", [
    {"ro.hardware": "ranchu"}, {"ro.boot.hardware": ""}, {"ro.boot.hardware": "cutf_cvm"},
    {"ro.product.device": "redroid_x86_64"}, {"ro.product.device": "redroid_x86_64_only"},
    {"ro.product.cpu.abi": "x86_64"}, {"ro.product.cpu.abilist": "x86_64,arm64-v8a"},
    {"ro.dalvik.vm.native.bridge": "libndk_translation.so"}, {"ro.dalvik.vm.native.bridge": "libhoudini.so"},
    {"uname_machine": "x86_64"},
])
def test_redroid_identity_rejects_translated_x86_or_other_guests(tmp_path, change):
    assert not qa.redroid_guest_verified(redroid_properties(**change))
    with pytest.raises(qa.Rejected, match="redroid_native_arm64_guest_unavailable"):
        PropertyDevice(tmp_path, qa.REDROID_GUEST, redroid_properties(**change)).identity()


def test_translated_identity_still_requires_qemu_bridge_and_translator_hash(tmp_path):
    values = {"ro.kernel.qemu": "1", "ro.product.cpu.abilist": "x86_64,arm64-v8a",
              "ro.dalvik.vm.native.bridge": "libndk_translation.so", "libndk_translation": "present"}
    identity = PropertyDevice(tmp_path, qa.TRANSLATED_GUEST, values).identity()
    assert identity["native_bridge_sha256"] == "a" * 64 and "guest" not in identity
    with pytest.raises(qa.Rejected, match="official_translated_guest_unavailable"):
        PropertyDevice(tmp_path, qa.TRANSLATED_GUEST, redroid_properties()).identity()


ANR_WINDOWS = ("  Window #5 Window{4b1e2a7 u0 Application Not Responding: com.android.systemui}:\n"
               "  mCurrentFocus=Window{4b1e2a7 u0 Application Not Responding: com.android.systemui}\n")


def anr_ui(title="System UI isn't responding", wait_enabled="true", extra=None):
    tree = ET.Element("hierarchy")
    ET.SubElement(tree, "node", {"package": "android", "resource-id": "android:id/alertTitle", "text": title})
    ET.SubElement(tree, "node", {"package": "android", "resource-id": "android:id/aerr_close", "text": "Close app",
                               "class": "android.widget.Button", "enabled": "true", "clickable": "true",
                               "bounds": "[40,500][500,560]"})
    ET.SubElement(tree, "node", {"package": "android", "resource-id": "android:id/aerr_wait", "text": "Wait",
                               "class": "android.widget.Button", "enabled": wait_enabled, "clickable": "true",
                               "bounds": "[40,580][500,640]"})
    for attributes in extra or ():
        ET.SubElement(tree, "node", attributes)
    return tree


def test_system_anr_dialog_identifies_only_android_wait_control():
    assert qa.system_anr_windows(ANR_WINDOWS) == ["com.android.systemui"]
    assert qa.system_anr_windows("mCurrentFocus=Window{1 u0 com.android.launcher3/.Launcher}") == []
    title, node = qa.system_anr_wait_control(anr_ui())
    assert title == "System UI isn't responding" and node.get("resource-id") == "android:id/aerr_wait"
    assert qa.system_anr_wait_control(anr_ui("Idoly Pride is not responding"))[1].get("text") == "Wait"


@pytest.mark.parametrize("tree", [
    anr_ui(wait_enabled="false"), anr_ui(title="Unfortunately, System UI has stopped"),
    anr_ui(extra=[{"package": "android", "resource-id": "android:id/aerr_wait", "enabled": "true", "clickable": "true"}]),
    anr_ui(extra=[{"package": "android", "text": "Launcher isn't responding"}]),
    ET.fromstring('<hierarchy><node package="com.example" text="Game isn\'t responding"/>'
                  '<node package="com.example" resource-id="android:id/aerr_wait" enabled="true" clickable="true"/></hierarchy>'),
])
def test_ambiguous_or_foreign_anr_dialogs_are_left_alone(tree):
    assert qa.system_anr_wait_control(tree) is None


class AnrDevice:
    def __init__(self, tree, windows=ANR_WINDOWS):
        self.tree, self.windows, self.commands, self.touches, self.shots = tree, windows, [], [], []

    def adb(self, *args, **kwargs):
        self.commands.append(args)
        return self.windows if args == ("shell", "dumpsys", "window", "windows") else ""

    def android(self):
        return self.tree

    def screenshot(self, name):
        self.shots.append(name)

    def touch(self, node):
        self.touches.append(node)


def bare_run(tmp_path, guest=None, **arguments):
    run = qa.ActualRun.__new__(qa.ActualRun)
    if guest:
        arguments["guest"] = guest
    run.args = SimpleNamespace(**arguments)
    run.proof, run.report, run.journal, run.explorer = tmp_path, {}, [], None
    return run


def test_redroid_answers_system_anr_with_wait_and_records_it(tmp_path):
    run = bare_run(tmp_path, qa.REDROID_GUEST)
    run.device = AnrDevice(anr_ui())
    assert run.relieve_system_anr(force=True) is True
    assert [node.get("resource-id") for node in run.device.touches] == ["android:id/aerr_wait"]
    entry = run.report["system_anr_wait_selected"][0]
    assert entry["choice"] == "wait" and entry["windows"] == ["com.android.systemui"]
    assert run.journal[-1]["phase"] == "redroid_system_anr_wait_selected" and run.device.shots == ["system-anr-01"]
    # Throttled between checks; a capped number of answers per run.
    assert run.relieve_system_anr() is False and len(run.device.touches) == 1


def test_translated_guest_never_answers_a_system_dialog(tmp_path):
    for run in (bare_run(tmp_path, qa.TRANSLATED_GUEST), bare_run(tmp_path)):
        run.device = AnrDevice(anr_ui())
        assert run.relieve_system_anr(force=True) is False
        assert not run.device.commands and not run.device.touches and "system_anr_wait_selected" not in run.report


def test_redroid_without_anr_window_does_not_dump_or_touch(tmp_path):
    run = bare_run(tmp_path, qa.REDROID_GUEST)
    run.device = AnrDevice(anr_ui(), windows="mCurrentFocus=Window{1 u0 com.android.launcher3/.Launcher}")
    assert run.relieve_system_anr(force=True) is False and not run.device.touches


def test_redroid_pregrants_only_notification_permission_then_launches_main_without_dialog(tmp_path):
    launcher = main_ui()

    class RedroidDevice:
        def __init__(self):
            self.commands, self.touches = [], []

        def identity(self):
            return {"guest": "redroid"}

        def adb(self, *args, **kwargs):
            self.commands.append((args, kwargs))
            if args[:5] == ("shell", "am", "start", "-W", "-a"):
                return "Starting: Intent\nStatus: ok\nActivity: " + qa.MAIN + "\nComplete\n"
            if args == ("shell", "dumpsys", "package", qa.PACKAGE):
                return "    runtime permissions:\n      android.permission.POST_NOTIFICATIONS: granted=true, flags=[ USER_SET ]\n"
            if args == ("shell", "dumpsys", "activity", "activities"):
                return activity_context(qa.MAIN)
            if args[:4] == ("shell", "run-as", qa.PACKAGE, "cat"):
                return main_lifecycle("precreated", "created", "started", "resumed")
            return ""

        def android(self):
            return launcher

        def touch(self, node):
            self.touches.append(node)

    run = bare_run(tmp_path, qa.REDROID_GUEST, apk=tmp_path / "actual.apk", startup_timeout=10)
    run.device = RedroidDevice()
    run.capture_launch_evidence = lambda stage: ""
    run.handle_dialog = lambda snapshot: False
    run.ui = SimpleNamespace(UiExplorer=lambda device: SimpleNamespace(_snapshot=lambda: {"ok": True}),
                             _home_role=lambda snapshot, role: True)
    run.wait = lambda action, timeout, code: action()
    run.launch()
    commands = [args for args, _ in run.device.commands]
    install = [kwargs for args, kwargs in run.device.commands if args[0] == "install"]
    assert install == [{"timeout": 600}]
    grant = ("shell", "pm", "grant", qa.PACKAGE, "android.permission.POST_NOTIFICATIONS")
    assert grant in commands and commands.index(grant) < next(i for i, c in enumerate(commands) if c[:3] == ("shell", "am", "start"))
    assert [c for c in commands if "grant" in c] == [grant] and not any("appops" in c for c in commands)
    assert run.report["notification_permission_pregranted_via_adb"] is True
    assert [event["phase"] for event in run.journal] == ["redroid_notification_permission_pregranted",
        "unified_launcher_start_requested", "unified_launcher_start_reported", "embedded_server_already_running",
        "unified_launcher_start_accepted"]
    assert run.device.touches == [launcher[0]]


def test_stopped_embedded_server_is_started_through_its_ui_before_launch(tmp_path):
    stopped, running = main_ui("status_stopped"), main_ui()
    storage = ET.Element("hierarchy")
    ET.SubElement(storage, "node", {"package": qa.PACKAGE, "class": "android.widget.Button", "enabled": "true",
                                    "clickable": "true", "text": sorted(qa.labels("resource_storage_use_private"))[0],
                                    "bounds": "[20,600][500,660]"})
    screens = [stopped, storage, running]

    class Device:
        def __init__(self):
            self.touches, self.shots = [], []

        def android(self):
            return screens[0]

        def touch(self, node):
            self.touches.append(node.get("text"))
            screens.pop(0)

        def screenshot(self, name):
            self.shots.append(name)

    run = bare_run(tmp_path, qa.REDROID_GUEST)
    run.device = Device()

    def wait(action, timeout, code):
        for _ in range(5):
            result = action()
            if result is not None and result is not False:
                return result
        raise qa.Rejected(code)
    run.wait = wait
    assert run.start_embedded_server() is True
    assert run.device.touches == [sorted(qa.labels("start_server"))[0], sorted(qa.labels("resource_storage_use_private"))[0]]
    assert [event["phase"] for event in run.journal] == ["embedded_server_start_requested",
        "embedded_server_private_storage_selected", "embedded_server_running"]
    assert run.device.shots == ["embedded-server-running"]
    # Already running: nothing is touched.
    run.journal.clear(); run.device.touches.clear(); screens[:] = [main_ui()]
    assert run.start_embedded_server() is False and not run.device.touches
    # A failed start is a named stop, never a silent wait.
    failed = main_ui("status_failed"); screens[:] = [main_ui("status_stopped"), failed]
    with pytest.raises(qa.Rejected, match="embedded_server_start_failed"):
        run.start_embedded_server()


def test_unverified_redroid_pregrant_keeps_the_observed_dialog_path(tmp_path):
    run = bare_run(tmp_path, qa.REDROID_GUEST)
    run.device = SimpleNamespace(adb=lambda *args, **kwargs: "Exception occurred while executing 'grant'")
    assert run.grant_redroid_notification_permission() is False
    assert run.journal[-1]["phase"] == "redroid_notification_permission_pregrant_unverified"


class SaveDevice:
    def __init__(self, installed):
        self.installed, self.commands = installed, []

    def adb(self, *args, **kwargs):
        self.commands.append(args)
        if args[:3] == ("shell", "pm", "path"):
            return "package:/system/priv-app/DocumentsUI/DocumentsUI.apk\n" if args[3] in self.installed else ""
        return ""


@pytest.mark.parametrize("guest,installed,expected", [
    (qa.REDROID_GUEST, (), False), (qa.REDROID_GUEST, ("com.android.documentsui",), True),
    (qa.TRANSLATED_GUEST, (), True), (None, (), True)])
def test_missing_documentsui_is_a_distinct_redroid_save_block_not_a_crash(tmp_path, guest, installed, expected):
    run = bare_run(tmp_path, guest)
    run.device = SaveDevice(installed)
    calls = []
    run.save_cancel = lambda path, digest: calls.append("cancel")
    run.save_completed = lambda path, digest, identifier: calls.append("save")
    assert run.save_steps("files/x.mp4", "d" * 64, "e" * 32) is expected
    if expected:
        assert calls == ["cancel", "save"] and run.report["save_verdict"] == {"status": "VERIFIED"}
    else:
        assert calls == [] and run.report["save_verdict"]["code"] == qa.SAVE_BLOCKED_DOCUMENTSUI
        assert run.journal[-1]["phase"] == qa.SAVE_BLOCKED_DOCUMENTSUI
    if guest != qa.REDROID_GUEST:
        assert not run.device.commands


def diagnostics_payload(stage="fresh_warm", code="fresh_warm_draw_wait", sequence=7, last_error="none"):
    return {"ok": True, "schema": 1, "qa_only": True, "read_only": True, "native_initialized": True,
            "native_status": {"phase": "preparing", "error_code": "none", "readiness_error": "none",
                              "scene_diagnostics": {"actor": {"result": 0, "error": "none"}}},
            "native_diagnostics": {"pipeline_mode": "fresh_original_scene", "export_trace": {
                "schema": 1, "current_stage": stage, "last_error": last_error,
                "events": [{"sequence": sequence, "stage": stage, "code": code, "frame": 0, "tick": 0}],
                "modules": {"native_scene_control": True, "scene_parts": False}},
                "session_progress": {"job_stage": "scene_acquire", "boundary_entries": 3}},
            "app_diagnostics": {"job_stage": "scene_acquire", "last_failed_export_trace": {"last_error": "output_geometry_x"}}}


def test_export_trace_summary_names_where_the_export_stopped():
    summary = qa.export_trace_summary(diagnostics_payload())
    assert summary["export_trace"]["current_stage"] == "fresh_warm"
    assert summary["export_trace"]["events"][-1]["code"] == "fresh_warm_draw_wait"
    assert summary["export_trace"]["unbound_modules"] == ["scene_parts"]
    assert summary["session_progress"]["job_stage"] == "scene_acquire" and summary["phase"] == "preparing"
    assert summary["last_failed_export_trace"] == {"last_error": "output_geometry_x"}
    assert summary["scene_diagnostics"]["actor"]["result"] == 0
    assert qa.export_trace_summary(None) == {} and qa.export_trace_summary({"native_diagnostics": []}) == {}


def test_diagnostics_capture_writes_distinct_trace_snapshots_and_never_raises(tmp_path):
    run = bare_run(tmp_path)
    run.explorer = SimpleNamespace(port=1)
    payloads = [diagnostics_payload(), diagnostics_payload(), diagnostics_payload("fresh_wait", "fresh_wait_actor", 8)]
    run.observer_get = lambda path, limit, code: payloads.pop(0)
    for reason in ("export_progress", "export_progress", "failure"):
        run.capture_mp4_diagnostics(reason, force=True)
    files = sorted(path.name for path in tmp_path.glob("mp4-diagnostics-*.json"))
    assert files == ["mp4-diagnostics-001-export_progress.json", "mp4-diagnostics-002-failure.json"]
    assert run.report["mp4_diagnostics"]["trace"]["export_trace"]["current_stage"] == "fresh_wait"
    assert (tmp_path / "latest-mp4-diagnostics.json").is_file()
    def unavailable(path, limit, code):
        raise qa.Rejected("qa_observer_token_unavailable")
    run.observer_get = unavailable
    assert run.capture_mp4_diagnostics("final", force=True) is None
    assert run.report["mp4_diagnostics"]["errors"] == {"qa_observer_token_unavailable": 1}
    run.observer_get = lambda path, limit, code: 1 / 0
    assert run.capture_mp4_diagnostics("final", force=True) is None
    assert run.report["mp4_diagnostics_collection_errors"] == ["ZeroDivisionError"]
    assert qa.ActualRun.__new__(qa.ActualRun).capture_mp4_diagnostics("x") is None


def test_persisted_trace_keeps_only_the_apps_own_export_diagnostics():
    trace = '{"export_trace":{"current_stage":"output_geometry","last_error":"output_geometry_odd"}}'
    raw = ("<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n"
           '    <string name="last_failed_native_trace">' + trace.replace('"', "&quot;") + "</string>\n"
           '    <string name="last_save_failure_stage">none</string>\n'
           '    <string name="mp4_title_catalog">private-looking value</string>\n'
           '    <int name="mp4_fps" value="30" />\n</map>\n')
    document = qa.persisted_mp4_diagnostics(raw)
    assert document["last_failed_native_trace"]["export_trace"]["last_error"] == "output_geometry_odd"
    assert document["last_save_failure_stage"] == "none" and "mp4_title_catalog" not in document
    assert qa.persisted_mp4_diagnostics("run-as: package not debuggable") == {"available": False}


def run_with_stubbed_flow(tmp_path, monkeypatch, guest, *, documentsui=True, export_error=None):
    monkeypatch.setattr(qa.subprocess, "check_output", lambda *args, **kwargs: "a" * 40 + "\n")
    apk = tmp_path / "observer.apk"
    apk.write_bytes(b"apk")
    evidence = tmp_path / "observer.evidence.json"
    evidence.write_text(qa.json.dumps({"compiled_manifest_structure_preserved": True,
        "manifest_factory_and_activities_preserved": True, "input_profile": "unified-current", "qa_only": True,
        "software_aes_and_no_store_input": False, "all_existing_members_preserved_except_manifest_and_signatures": True,
        "qa_ui": {"source_commit": "a" * 40}, "output_apk_sha256": qa.sha(apk)}))
    proof = tmp_path / "runtime"
    proof.mkdir()
    run = qa.ActualRun.__new__(qa.ActualRun)
    run.args = SimpleNamespace(source_commit="a" * 40, qa_evidence=evidence, apk=apk, export_timeout=60,
                               queue_replay=False, guest=guest)
    run.proof, run.journal, run.explorer = proof, [], SimpleNamespace(port=1, _snapshot=lambda: {"ok": True})
    run.report = {"scope": qa.GUESTS[guest]["scope"], "guest": guest}
    run.device = SimpleNamespace(adb=lambda *args, **kwargs: "package:/x.apk\n" if documentsui and args[:3] == ("shell", "pm", "path") else "",
                                 android=lambda: ET.Element("hierarchy"), screenshot=lambda name: None)
    final = snapshot(600, complete=True)
    run.launch = run.server_menu = run.configure_and_start = lambda: None
    run.open_mv = lambda: snapshot()
    def await_export(baseline):
        if export_error:
            raise qa.Rejected(export_error)
        return final, baseline
    run.await_export = await_export
    run.retrieve_and_decode = lambda payload, label: ("files/.idoly-mp4-library/exports/x.mp4", "d" * 64)
    run.save_cancel = lambda path, digest: None
    run.save_completed = lambda path, digest, identifier: None
    reasons = []
    run.observer_get = lambda path, limit, code: reasons.append(path) or diagnostics_payload(sequence=len(reasons))
    return run, proof, reasons


def test_redroid_pass_has_its_own_scope_and_status_and_keeps_the_trace(tmp_path, monkeypatch):
    run, proof, reasons = run_with_stubbed_flow(tmp_path, monkeypatch, qa.REDROID_GUEST)
    assert run.run() is True
    report = qa.json.loads((proof / "runtime-report.json").read_text())
    assert report["status"] == "PASS_ACTUAL_MV_EXPORT_REDROID_ARM64_ONLY" and report["guest"] == "redroid"
    assert report["scope"] == "actual_game_in_redroid_native_arm64_container"
    assert report["save_verdict"] == {"status": "VERIFIED"} and reasons == ["/mp4-diagnostics"]
    assert report["mp4_diagnostics"]["last_reason"] == "final" and (proof / "persisted-mp4-diagnostics.json").is_file()


def test_redroid_save_block_keeps_export_verdict_but_never_passes(tmp_path, monkeypatch):
    run, proof, _ = run_with_stubbed_flow(tmp_path, monkeypatch, qa.REDROID_GUEST, documentsui=False)
    assert run.run() is False
    report = qa.json.loads((proof / "runtime-report.json").read_text())
    assert report["status"] == "EXPORT_VERIFIED_SAVE_BLOCKED"
    assert report["failure_code"] == "save_blocked_documentsui_unavailable" and report["failure_stage"] == "save"
    assert report["direct_playing_source_export_and_restore_verified"] is True
    assert report["save_verdict"]["status"] == "BLOCKED"


def test_export_failure_records_the_native_trace_on_failure_and_final(tmp_path, monkeypatch):
    run, proof, reasons = run_with_stubbed_flow(tmp_path, monkeypatch, qa.REDROID_GUEST,
                                                export_error="native_export_failed_fresh_actor_collect_timeout")
    assert run.run() is False
    report = qa.json.loads((proof / "runtime-report.json").read_text())
    assert report["status"] == "FAILED_OR_ENVIRONMENT_BLOCKED"
    assert report["failure_code"] == "native_export_failed_fresh_actor_collect_timeout"
    assert reasons == ["/mp4-diagnostics", "/mp4-diagnostics"]
    assert report["mp4_diagnostics"]["trace"]["export_trace"]["current_stage"] == "fresh_warm"
    assert sorted(p.name for p in proof.glob("mp4-diagnostics-*")) == [
        "mp4-diagnostics-001-failure.json", "mp4-diagnostics-002-final.json"]


def test_translated_guest_pass_status_is_unchanged(tmp_path, monkeypatch):
    run, proof, _ = run_with_stubbed_flow(tmp_path, monkeypatch, qa.TRANSLATED_GUEST, documentsui=False)
    assert run.run() is True
    report = qa.json.loads((proof / "runtime-report.json").read_text())
    assert report["status"] == "PASS_ACTUAL_MV_EXPORT_TRANSLATED_GUEST_ONLY"


def test_cli_guest_option_defaults_to_the_translated_emulator(monkeypatch, tmp_path):
    seen = []

    class Recorder:
        def __init__(self, args):
            seen.append(args)

        def run(self):
            return True
    monkeypatch.setattr(qa, "ActualRun", Recorder)
    base = ["driver", "--apk", "a.apk", "--qa-evidence", "e.json", "--source-commit", "a" * 40,
            "--output-directory", str(tmp_path / "out")]
    for extra, guest, serial in (([], "translated-emulator", "emulator-5554"),
                                 (["--guest", "redroid", "--serial", "127.0.0.1:15555"], "redroid", "127.0.0.1:15555")):
        monkeypatch.setattr(sys, "argv", base + extra)
        with pytest.raises(SystemExit) as exit_code:
            qa.main()
        assert exit_code.value.code == 0 and seen[-1].guest == guest and seen[-1].serial == serial
    monkeypatch.setattr(sys, "argv", base + ["--guest", "cuttlefish"])
    with pytest.raises(SystemExit) as exit_code:
        qa.main()
    assert exit_code.value.code == 2


def java_array(source, name):
    body = re.search(r"\b" + name + r"\s*=\s*\{(.*?)\};", source, re.S)
    assert body, name
    return set(re.findall(r'"([a-z_]+)"', re.sub(r"//[^\n]*", "", body.group(1))))


def test_observer_exposes_every_native_field_the_runtime_gates_read():
    """The QA observer whitelist must carry the observation keys the verdict needs."""
    source = (ROOT / "qa-game-ui/java/game/qualiarts/idolypride/qa/ui/QaMp4Observation.java").read_text()
    status, observation = java_array(source, "STATUS"), java_array(source, "OBSERVATION")
    complete = snapshot(complete=True)["native"]
    needed = set(complete["observation"]) | {"acquired_source_valid", "acquired_source_identity",
                                             "acquired_source_time", "acquired_source_paused"}
    assert needed <= observation, sorted(needed - observation)
    assert set(complete) - {"observation", "source_width", "source_height"} <= status | {"source_width", "source_height"}
    assert {"paused", "pause_requested", "readiness_error", "restoration_error"} <= status
    # Never invent a field: each one is formatted by the native status document.
    runtime = (ROOT / "client-presentation/native/mp4_runtime.hpp").read_text()
    formatted = set(re.findall(r'\\"([a-z_]+)\\":', runtime))
    assert observation <= formatted and status <= formatted, sorted((observation | status) - formatted)
    assert "/mp4-diagnostics" in (ROOT / "qa-game-ui/java/game/qualiarts/idolypride/qa/ui/LoopbackUiServer.java").read_text()


def test_observer_side_diagnostics_errors_keep_their_fixed_code(tmp_path):
    run = bare_run(tmp_path)
    run.explorer = SimpleNamespace(port=1)
    run.observer_get = lambda path, limit, code: {"ok": False, "error": "mp4_diagnostics_oversized"}
    assert run.capture_mp4_diagnostics("final", force=True) is None
    assert run.report["mp4_diagnostics"]["errors"] == {"observer_mp4_diagnostics_oversized": 1}
    assert not list(tmp_path.glob("*.json"))


def test_terms_of_service_sheet_is_agreed_through_its_own_wired_button():
    base = "Title/TitleStartTutorial(Clone)/TermsOfServiceSheet(Clone)/Canvas/Root/UIContentArea/ActionBarContainer/AnchorAdjust/Actions/"
    agree = {"path": base + "Execute/TextButtonNormal", "kind": "button", "active": True,
             "interactable": True, "callback_registered": True}
    cancel = dict(agree, path=base + "Cancel/TextButtonNormal")
    title = {"path": "Canvas/TitleButton", "kind": "button", "active": True, "interactable": True, "callback_registered": True}
    assert qa.terms_agree_target({"nodes": [title, cancel, agree]}) is agree
    assert qa.terms_agree_target({"nodes": [title, cancel]}) is None
    for broken in ({"interactable": False}, {"active": False}, {"callback_registered": None}, {"kind": "tmp_text"}):
        assert qa.terms_agree_target({"nodes": [dict(agree, **broken)]}) is None
    assert qa.terms_agree_target({"nodes": [agree, dict(agree)]}) is None
    assert qa.terms_agree_target({"ok": False}) is None

    run = qa.ActualRun.__new__(qa.ActualRun)
    run.journal, touched = [], []
    run.explorer = SimpleNamespace(_tap=lambda snap, node, role, index: touched.append((node["path"], role)) or True)
    run.ui = SimpleNamespace(notice_close_target=lambda s: None, manager_level_close_target=lambda s: None,
                             lesson_reward_close_target=lambda s: None, download_confirmation=lambda s: None)
    run.record = lambda phase, observation=None: run.journal.append({"phase": phase})
    assert run.handle_dialog({"nodes": [title, cancel, agree]}) is True
    assert touched == [(agree["path"], "observed_terms_agree")] and run.journal[-1]["phase"] == "observed_terms_agree"


# QA-only completed-opening profile fixture (explicit --prepare-completed-opening).
FIXTURE_TOKEN = "local-" + "Q7v" * 14 + "x"  # shaped like the embedded server's session token


class FakeRpcError(Exception):
    def __init__(self, name, details):
        super().__init__(details)
        self.status_name = name

    def code(self):
        return SimpleNamespace(name=self.status_name)


def fixture_result(**changes):
    methods = ("/api.Auth/Login", "/api.Tutorial/Init", "/api.User/Get", "/api.Tutorial/Progress")
    result = {"enabled": True, "qa_only": True, "status": "ready",
              "rpc_calls": [{"method": method, "status": "OK", "origin": "profile_fixture"} for method in methods],
              "completed_tutorial_step": 150, "tutorial_cleared": True, "actual_game_tutorial_played": False,
              "continuation": {"platform": "actual-game fixture setup", "completed_step": 150,
                               "snapshot_sha256": "c" * 64}}
    result.update(changes)
    return result


def fixture_boot(events, *, result=None, error=None, stage=None):
    def fail(name):
        if error is not None and stage == name:
            raise error

    def from_descriptor_set(path):
        events.append(("schema", Path(path).name))
        fail("descriptor_set")
        return "schema"

    def wait_server(schema, port, timeout):
        events.append(("wait_server", port, timeout))
        fail("server_wait")

    def prepare(schema, port, master_dir, *, timeout):
        events.append(("prepare", port, Path(master_dir).name, timeout))
        fail("prepare")
        return fixture_result() if result is None else result
    return SimpleNamespace(Schema=SimpleNamespace(from_descriptor_set=from_descriptor_set), wait_server=wait_server,
                           prepare_completed_opening=prepare, grpc=SimpleNamespace(RpcError=FakeRpcError))


class FixtureDevice:
    """The unified Main UI; its embedded server starts through the Start control."""

    def __init__(self, events, running=False, forward_error=None):
        self.events, self.running, self.forward_error = events, running, forward_error

    def identity(self):
        return {"guest": "redroid"}

    def adb(self, *args, **kwargs):
        if args[:2] == ("forward", "--remove"):
            self.events.append(("forward_removed", args[2]))
        if args[:5] == ("shell", "am", "start", "-W", "-a"):
            return "Starting: Intent\nStatus: ok\nActivity: " + qa.MAIN + "\nComplete\n"
        if args == ("shell", "dumpsys", "activity", "activities"):
            self.events.append(("launcher_read",))
            return activity_context(qa.MAIN)
        if args[:4] == ("shell", "run-as", qa.PACKAGE, "cat"):
            return main_lifecycle("precreated", "created", "started", "resumed")
        return ""

    def forward(self, port):
        self.events.append(("forward", port))
        if self.forward_error is not None:
            raise self.forward_error
        return 41234

    def android(self):
        return main_ui() if self.running else main_ui("status_stopped")

    def touch(self, node):
        if node.get("text") in qa.labels("start_server"):
            self.running = True
            self.events.append(("start_server",))
        else:
            self.events.append(("touch", node.get("text")))

    def screenshot(self, name):
        pass


def fixture_run(tmp_path, events, enabled=True, running=False, forward_error=None):
    arguments = {"apk": tmp_path / "actual.apk", "startup_timeout": 10}
    if enabled:
        arguments.update(prepare_completed_opening=True, descriptor_set=tmp_path / "idolypride-6.1.1.pb",
                         master_dir=tmp_path / "master-json")
    proof = tmp_path / "runtime"
    proof.mkdir()
    run = bare_run(proof, qa.REDROID_GUEST, **arguments)
    run.device = FixtureDevice(events, running, forward_error)
    run.capture_launch_evidence = lambda stage: ""
    run.handle_dialog = lambda snapshot: False
    run.ui = SimpleNamespace(UiExplorer=lambda device: SimpleNamespace(_snapshot=lambda: {"ok": True}),
                             _home_role=lambda snapshot, role: True)

    def wait(action, timeout, code):
        for _ in range(5):
            result = action()
            if result is not None and result is not False:
                return result
        raise qa.Rejected(code)
    run.wait = wait
    original = run.record

    def record(phase, payload=None):
        events.append(("phase", phase))
        original(phase, payload)
    run.record = record
    return run, proof


def written(proof):
    return "".join(path.read_text() for path in proof.iterdir() if path.is_file())


@pytest.mark.parametrize("running", [False, True])
def test_completed_opening_fixture_runs_after_server_running_and_before_launch(tmp_path, monkeypatch, running):
    events = []
    monkeypatch.setattr(qa, "load_fixture_boot", lambda: fixture_boot(events))
    run, proof = fixture_run(tmp_path, events, running=running)
    run.launch()
    launch_label = sorted(qa.labels("launch_diagnostic_client"))[0]
    server = ("phase", "embedded_server_already_running" if running else "embedded_server_running")
    order = [server, ("phase", "profile_fixture_requested"), ("schema", "idolypride-6.1.1.pb"),
             ("forward", qa.FIXTURE_SERVER_PORT), ("wait_server", 41234, qa.FIXTURE_SERVER_TIMEOUT),
             ("prepare", 41234, "master-json", qa.FIXTURE_RPC_TIMEOUT), ("forward_removed", "tcp:41234"),
             ("phase", "profile_fixture_ready"), ("launcher_read",), ("touch", launch_label)]
    positions = [max(i for i, event in enumerate(events) if event == wanted) for wanted in order]
    assert positions == sorted(positions), events
    # The Launch node is read again after the fixture, then touched exactly once.
    assert [event for event in events if event[0] == "touch"] == [("touch", launch_label)]
    assert events.index(("phase", "profile_fixture_ready")) < max(
        i for i, event in enumerate(events) if event == ("launcher_read",))
    document = qa.json.loads((proof / "profile-fixture.json").read_text())
    assert document["status"] == "ready" and document["qa_only"] is True
    assert document["actual_game_tutorial_played"] is False and document["gameplay_evidence"] is False
    assert document["prepared_before_game_launch"] is True and document["completed_tutorial_step"] == 150
    assert all(set(row) == {"method", "status", "origin"} for row in document["rpc_calls"])
    assert run.report["profile_fixture"] == document
    ready = next(event for event in run.journal if event["phase"] == "profile_fixture_ready")["observation"]
    assert ready["actual_game_tutorial_played"] is False and ready["rpc_methods"][:2] == [
        "/api.Auth/Login", "/api.Tutorial/Init"]
    assert "local-" not in written(proof) and run.report["game_boot_verified"] is True


@pytest.mark.parametrize("stage,error,code,check", [
    ("load", ModuleNotFoundError("No module named 'grpc'"), "profile_fixture_failed_load_ModuleNotFoundError", None),
    ("descriptor_set", FileNotFoundError("missing"), "profile_fixture_failed_descriptor_set_FileNotFoundError", None),
    ("forward", qa.Rejected("loopback_forward_failed"), "profile_fixture_failed_forward_loopback_forward_failed", None),
    ("server_wait", RuntimeError("Server did not start before the timeout"),
     "profile_fixture_failed_server_wait_RuntimeError", None),
    ("prepare", FakeRpcError("UNAVAILABLE", "details x-auth-token " + FIXTURE_TOKEN),
     "profile_fixture_failed_prepare_rpc_unavailable", None),
    ("prepare", FakeRpcError("DEADLINE_EXCEEDED", "Deadline Exceeded"),
     "profile_fixture_failed_prepare_rpc_deadline_exceeded", None),
    ("prepare", RuntimeError("Tutorial continuation QA: lesson reward definitions differ"),
     "profile_fixture_failed_prepare_RuntimeError", "lesson_reward_definitions_differ"),
    ("prepare", KeyError(FIXTURE_TOKEN), "profile_fixture_failed_prepare_KeyError", None),
    ("record", None, "profile_fixture_failed_record_profile_fixture_result_invalid", None),
])
def test_completed_opening_fixture_failure_is_a_named_stop_before_launch(tmp_path, monkeypatch, stage, error, code, check):
    events = []
    if stage == "load":
        def unavailable():
            raise error
        monkeypatch.setattr(qa, "load_fixture_boot", unavailable)
    else:
        result = fixture_result(actual_game_tutorial_played=True) if stage == "record" else None
        monkeypatch.setattr(qa, "load_fixture_boot", lambda: fixture_boot(events, result=result, error=error, stage=stage))
    run, proof = fixture_run(tmp_path, events, forward_error=error if stage == "forward" else None)
    with pytest.raises(qa.Rejected) as rejected:
        run.launch()
    assert str(rejected.value) == code
    assert not [event for event in events if event[0] == "touch"]  # Launch is never pressed.
    assert run.journal[-1]["phase"] == code and "game_boot_verified" not in run.report
    assert run.report["profile_fixture"] == dict({"enabled": True, "qa_only": True, "status": "failed",
        "failure_code": code, "actual_game_tutorial_played": False}, **({"failed_check": check} if check else {}))
    assert not (proof / "profile-fixture.json").exists()
    forwarded = stage in ("server_wait", "prepare", "record")
    assert (("forward_removed", "tcp:41234") in events) is forwarded
    # Exception text (RPC details, keys) never reaches the report or journal.
    assert FIXTURE_TOKEN not in written(proof) + qa.json.dumps(run.report)


def test_fixture_result_with_a_token_shaped_value_is_never_written(tmp_path, monkeypatch):
    events = []
    leaked = fixture_result(continuation={"completed_step": 150, "note": FIXTURE_TOKEN})
    monkeypatch.setattr(qa, "load_fixture_boot", lambda: fixture_boot(events, result=leaked))
    run, proof = fixture_run(tmp_path, events)
    with pytest.raises(qa.Rejected, match="^profile_fixture_failed_record_profile_fixture_secret_shaped_value$"):
        run.launch()
    assert not (proof / "profile-fixture.json").exists() and FIXTURE_TOKEN not in written(proof)
    for change in ({"rpc_calls": [{"method": "/api.Auth/Login", "status": "OK", "origin": "profile_fixture",
                                   "token": "x"}] * 3},
                   {"rpc_calls": []}, {"tutorial_cleared": False}, {"status": "preparing"}):
        with pytest.raises(qa.Rejected):
            qa.completed_opening_document(fixture_result(**change))


def test_fixture_failure_stops_the_run_with_its_named_code(tmp_path, monkeypatch):
    run, proof, _ = run_with_stubbed_flow(tmp_path, monkeypatch, qa.REDROID_GUEST)
    events = []
    run.args.descriptor_set, run.args.master_dir = tmp_path / "set.pb", tmp_path / "master-json"
    run.device.forward = lambda port: 41234
    monkeypatch.setattr(qa, "load_fixture_boot", lambda: fixture_boot(
        events, error=RuntimeError("Tutorial continuation QA: requires the dedicated uncompleted synthetic QA profile"),
        stage="prepare"))
    run.launch = run.prepare_completed_opening_fixture
    assert run.run() is False
    report = qa.json.loads((proof / "runtime-report.json").read_text())
    code = "profile_fixture_failed_prepare_RuntimeError"
    assert report["status"] == "FAILED_OR_ENVIRONMENT_BLOCKED"
    assert report["failure_code"] == report["failure_stage"] == code
    assert report["profile_fixture"]["failed_check"] == "requires_the_dedicated_uncompleted_synthetic_qa_profile"
    assert "actual_mv_verified" not in report or report["actual_mv_verified"] is False


def test_without_the_option_no_fixture_forward_or_rpc_happens(tmp_path, monkeypatch):
    events = []

    def forbidden():
        raise AssertionError("fixture loader must not run without the explicit option")
    monkeypatch.setattr(qa, "load_fixture_boot", forbidden)
    run, proof = fixture_run(tmp_path, events, enabled=False)
    run.launch()
    assert not [event for event in events if event[0] in ("forward", "forward_removed")]
    assert [event["phase"] for event in run.journal] == ["redroid_notification_permission_pregrant_unverified",
        "unified_launcher_start_requested", "unified_launcher_start_reported", "embedded_server_start_requested",
        "embedded_server_running", "unified_launcher_start_accepted"]
    assert "profile_fixture" not in run.report and not (proof / "profile-fixture.json").exists()


def test_fixture_failure_codes_never_carry_exception_text():
    boot = SimpleNamespace(grpc=SimpleNamespace(RpcError=FakeRpcError))
    assert qa.fixture_failure_code("prepare", FakeRpcError("UNAUTHENTICATED", FIXTURE_TOKEN), boot) == \
        "profile_fixture_failed_prepare_rpc_unauthenticated"

    class Statusless(FakeRpcError):
        def code(self):
            raise AttributeError("no status")
    assert qa.fixture_failure_code("prepare", Statusless("X", FIXTURE_TOKEN), boot) == "profile_fixture_failed_prepare_rpc_error"
    # Without the loaded grpc module a .code() method is not trusted.
    assert qa.fixture_failure_code("prepare", FakeRpcError("UNAVAILABLE", "x")) == "profile_fixture_failed_prepare_FakeRpcError"
    assert qa.fixture_failed_check(RuntimeError("Tutorial continuation QA: message has no local identity/time")) == \
        "message_has_no_local_identity_time"
    for other in (RuntimeError("Server did not start " + FIXTURE_TOKEN), ValueError("Tutorial continuation QA: x"),
                  RuntimeError("Tutorial continuation QA: " + "\n" + FIXTURE_TOKEN)):
        assert qa.fixture_failed_check(other) is None


def test_cli_fixture_option_is_off_by_default_and_requires_its_inputs(monkeypatch, tmp_path):
    seen = []

    class Recorder:
        def __init__(self, args):
            seen.append(args)

        def run(self):
            return True
    monkeypatch.setattr(qa, "ActualRun", Recorder)
    base = ["driver", "--apk", "a.apk", "--qa-evidence", "e.json", "--source-commit", "a" * 40,
            "--output-directory", str(tmp_path / "out"), "--guest", "redroid", "--serial", "127.0.0.1:15555"]

    def main(*extra):
        monkeypatch.setattr(sys, "argv", base + list(extra))
        with pytest.raises(SystemExit) as exit_code:
            qa.main()
        return exit_code.value.code
    assert main() == 0 and seen[-1].prepare_completed_opening is False
    assert seen[-1].descriptor_set is None and seen[-1].master_dir is None
    descriptor, master = tmp_path / "idolypride-6.1.1.pb", tmp_path / "master-json"
    descriptor.write_bytes(b"descriptor")
    master.mkdir()
    for name in qa.FIXTURE_TABLES[:-1]:
        (master / name).write_text("[]")
    for extra in ([], ["--descriptor-set", str(descriptor)], ["--descriptor-set", str(descriptor), "--master-dir", str(master)],
                  ["--descriptor-set", str(tmp_path / "missing.pb"), "--master-dir", str(master)]):
        with pytest.raises(qa.Rejected, match="^profile_fixture_inputs_required$"):
            main("--prepare-completed-opening", *extra)
    (master / qa.FIXTURE_TABLES[-1]).write_text("[]")  # Mission.json backs the continuation's mission check.
    assert main("--prepare-completed-opening", "--descriptor-set", str(descriptor), "--master-dir", str(master)) == 0
    assert seen[-1].prepare_completed_opening is True and seen[-1].master_dir == master
    with pytest.raises(qa.Rejected, match="^profile_fixture_inputs_without_option$"):
        main("--descriptor-set", str(descriptor), "--master-dir", str(master))


def test_driver_reuses_qa_game_boot_fixture_and_keeps_the_session_token_out_of_files(tmp_path, monkeypatch):
    pytest.importorskip("grpc")
    pytest.importorskip("google.protobuf")
    boot = qa.load_fixture_boot()
    assert boot is sys.modules["qa_game_boot"] and boot.prepare_completed_opening.__module__ == "qa_game_boot"
    from idoly_local import tutorial_qa
    sent = []

    class Channel:
        def __init__(self, target):
            self.target = target

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def unary_unary(self, path, request_serializer=None, response_deserializer=None):
            def call(raw, metadata=(), timeout=None):
                sent.append((self.target, path, dict(metadata), timeout))
                return b""
            return call

    class Request(SimpleNamespace):
        def SerializeToString(self):
            return b"request"
    login = SimpleNamespace(gameAuthToken=FIXTURE_TOKEN)
    schema = SimpleNamespace(request_type=lambda path: Request, response_type=lambda path: SimpleNamespace(
        FromString=lambda raw: login if path == "/api.Auth/Login" else SimpleNamespace()))
    waited = []

    def continuation(schema, invoke, master_dir, *, label):
        invoke("/api.User/Get", schema.request_type("/api.User/Get")())
        invoke("/api.Tutorial/Progress", schema.request_type("/api.Tutorial/Progress")(type=1, step=150))
        return {"platform": label, "completed_step": 150, "snapshot_sha256": "d" * 64}
    monkeypatch.setattr(boot.grpc, "insecure_channel", Channel)
    monkeypatch.setattr(boot, "Schema", SimpleNamespace(from_descriptor_set=lambda path: schema))
    monkeypatch.setattr(boot, "wait_server", lambda schema, port, timeout: waited.append((port, timeout)))
    monkeypatch.setattr(tutorial_qa, "run_tutorial_continuation", continuation)
    removed = []
    run = bare_run(tmp_path, qa.REDROID_GUEST, descriptor_set=tmp_path / "set.pb", master_dir=tmp_path / "master-json")
    run.device = SimpleNamespace(forward=lambda port: 41234 if port == qa.FIXTURE_SERVER_PORT else 0,
                                 adb=lambda *args, **kwargs: removed.append(args) or "")
    document = run.prepare_completed_opening_fixture()
    assert waited == [(41234, qa.FIXTURE_SERVER_TIMEOUT)] and removed == [("forward", "--remove", "tcp:41234")]
    assert [path for _, path, _, _ in sent] == ["/api.Auth/Login", "/api.Tutorial/Init", "/api.User/Get",
                                                "/api.Tutorial/Progress"]
    assert {target for target, _, _, _ in sent} == {"127.0.0.1:41234"}
    assert {timeout for _, _, _, timeout in sent} == {qa.FIXTURE_RPC_TIMEOUT}
    # The token authenticates the setup RPCs only as metadata; it is never written.
    assert sent[0][2] == {} and all(metadata == {"x-auth-token": FIXTURE_TOKEN} for _, _, metadata, _ in sent[1:])
    assert [row["method"] for row in document["rpc_calls"]] == [path for _, path, _, _ in sent]
    assert document["actual_game_tutorial_played"] is False and document["continuation"]["completed_step"] == 150
    assert FIXTURE_TOKEN not in written(tmp_path) + qa.json.dumps(run.report) + qa.json.dumps(run.journal)


def test_a_dialog_that_closed_before_its_touch_is_re_observed_not_a_failure():
    sheet = {"path": "Title/SimpleActionSheet(Clone)/Canvas/Root/UIContentArea/ActionBarContainer/AnchorAdjust/Actions/Execute/TextButtonNormal",
             "kind": "button", "active": True}
    run = qa.ActualRun.__new__(qa.ActualRun)
    run.journal = []
    run.explorer = SimpleNamespace(_tap=lambda snap, node, role, index: False)
    run.ui = SimpleNamespace(notice_close_target=lambda s: None, manager_level_close_target=lambda s: None,
                             lesson_reward_close_target=lambda s: None, download_confirmation=lambda s: sheet)
    run.record = lambda phase, observation=None: run.journal.append({"phase": phase})
    assert run.handle_dialog({"nodes": [sheet]}) is True
    assert run.journal[-1]["phase"] == "observed_resource_download_confirmation_input_skipped"


def test_home_counts_only_after_loading_releases_input():
    assert qa.home_input_blocked({"startup_observation": {"content_blocking": True, "input_releasing": False}})
    assert qa.home_input_blocked({"startup_observation": {"content_blocking": False, "input_releasing": True}})
    assert not qa.home_input_blocked({"startup_observation": {"content_blocking": False, "input_releasing": False}})
    assert not qa.home_input_blocked({"ok": True})


def test_idols_route_waits_for_released_home_and_retries_a_refused_touch():
    states = [{"ok": True, "startup_observation": {"content_blocking": True}},
              {"ok": True, "startup_observation": {"content_blocking": False}},
              {"ok": True, "startup_observation": {"content_blocking": False}}]
    taps = []
    run = qa.ActualRun.__new__(qa.ActualRun)
    run.journal = []
    run.explorer = SimpleNamespace(_snapshot=lambda: states.pop(0),
                                   _tap=lambda snap, node, role, index: taps.append(role) or len(taps) > 1)
    run.ui = SimpleNamespace(_home_role=lambda snap, role: {"path": "idols"}, notice_close_target=lambda s: None,
                             manager_level_close_target=lambda s: None, lesson_reward_close_target=lambda s: None,
                             download_confirmation=lambda s: None)
    run.record = lambda phase, observation=None: run.journal.append({"phase": phase})

    def wait(action, timeout, code):
        for _ in range(5):
            result = action()
            if result is not None and result is not False:
                return result
        raise qa.Rejected(code)
    run.wait = wait
    run.route = lambda *a, **k: (_ for _ in ()).throw(StopIteration)
    with pytest.raises(StopIteration):
        run.open_mv()
    assert taps == ["route_idols", "route_idols"] and [e["phase"] for e in run.journal] == ["route_idols"]


def test_viewing_mode_is_checked_through_the_server_tab_before_start(tmp_path):
    def tree(checked):
        root = ET.Element("hierarchy")
        ET.SubElement(root, "node", {"package": qa.PACKAGE, "class": "android.widget.Button", "enabled": "true",
                                     "clickable": "true", "content-desc": "idoly.nav.server", "text": "Server",
                                     "bounds": "[0,0][100,50]"})
        ET.SubElement(root, "node", {"package": qa.PACKAGE, "class": "android.widget.CheckBox", "enabled": "true",
                                     "clickable": "true", "content-desc": "idoly.options.media-mode",
                                     "checked": checked, "bounds": "[0,100][300,150]"})
        return root
    state = {"checked": "false"}

    class Device:
        def __init__(self):
            self.touches, self.shots = [], []

        def android(self):
            return tree(state["checked"])

        def android_control(self, values, *, cls=None, scroll=True, packages=(qa.PACKAGE,)):
            return next((n for n in self.android().iter("node") if n.get("content-desc") in values), None)

        def touch(self, node):
            self.touches.append(node.get("content-desc"))
            if node.get("content-desc") == "idoly.options.media-mode":
                state["checked"] = "true"

        def screenshot(self, name):
            self.shots.append(name)

    run = bare_run(tmp_path, qa.REDROID_GUEST)
    run.device = Device()
    run.wait = lambda action, timeout, code: action() or (_ for _ in ()).throw(qa.Rejected(code))
    run.enable_viewing_mode()
    assert run.device.touches == ["idoly.nav.server", "idoly.options.media-mode"]
    assert run.journal[-1]["phase"] == "viewing_mode_enabled" and run.device.shots == ["viewing-mode-enabled"]
    # Already checked: only the tab is touched.
    run.device.touches.clear()
    run.enable_viewing_mode()
    assert run.device.touches == ["idoly.nav.server"]
