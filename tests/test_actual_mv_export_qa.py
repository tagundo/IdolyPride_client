"""Reject false positives in the actual Unity MV runtime verdict."""
from copy import deepcopy
import importlib.util
from pathlib import Path
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


def main_ui():
    tree = ET.Element("hierarchy")
    ET.SubElement(tree, "node", {"package": qa.PACKAGE, "class": "android.widget.Button", "enabled": "true",
                               "clickable": "true", "text": sorted(qa.labels("launch_diagnostic_client"))[0],
                               "bounds": "[20,400][500,460]"})
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
        "unified_launcher_start_accepted"]
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
