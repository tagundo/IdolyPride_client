"""Owned, bounded native-stack evidence; all host commands are mocked here."""
import importlib.util
import json
from pathlib import Path
import plistlib
import signal
import sys
import time
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def probe():
    spec=importlib.util.spec_from_file_location("owned_sample_probe",ROOT/"ios-unified/probe/smoke_probe.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


RAW_SAMPLE=b"""Analysis of sampling IdolyEmbeddedProbe (pid 123)
Path: /private/DO-NOT-EXPORT/Probe.app/IdolyEmbeddedProbe
Arguments: password=DO-NOT-EXPORT
Call graph:
    100 Thread_55   DispatchQueue_1: com.apple.main-thread  (serial)
    + 100 semaphore_wait_trap  (in libsystem_kernel.dylib) + 8 [0x123456]
    +   100 -[NSXPCConnection _sendInvocation:orArguments:count:methodSignature:selector:withProxy:]  (in Foundation) + 12 [0x23456]
    +     100 -[UIDocumentPickerViewController initWithDocumentTypes:inMode:]  (in UIKitCore) + 25 [0x34567]
    +       100 ProbeZIPImportBegin  (in IdolyEmbeddedProbe) + 12 [0x45678]
    +         100 -[IDSettingsController pickResourceArchive]  (in IdolyEmbeddedServer) + 12 [0x45679]
    +       100 DO-NOT-EXPORT  (in IdolyEmbeddedProbe) + 12 [0x45678]
    +       100 ProbeDO-NOT-EXPORT  (in /private/DO-NOT-EXPORT) + 12 [0x45678]
    100 Thread_66   DispatchQueue_7: worker  (serial)
    + 100 PyEval_SaveThread  (in Python) + 1 [0x77889]
Binary Images:
/private/DO-NOT-EXPORT/secret.dylib
"""


def test_parser_keeps_main_wait_and_picker_frames_and_drops_every_header_path(probe):
    observed=probe.parse_process_sample(RAW_SAMPLE)
    assert observed["main_thread_found"] is True
    assert observed["thread_count"]==2 and observed["frame_count"]==5
    assert [row["module"] for row in observed["frames"]]==["libsystem_kernel.dylib","Foundation","UIKitCore","IdolyEmbeddedProbe","IdolyEmbeddedServer"]
    assert observed["frames"][0]["symbol"]=="semaphore_wait_trap"
    assert "DO-NOT-EXPORT" not in json.dumps(observed)
    assert "PyEval_SaveThread" not in json.dumps(observed)


@pytest.mark.parametrize("header", ["DispatchQueue_1: com.apple.main-thread-DO-NOT-EXPORT  (serial)",
    "DispatchQueue_1: DO-NOT-EXPORT-com.apple.main-thread  (serial)","DispatchQueue_1: com.apple.main-thread  (serial) extra"])
def test_main_queue_marker_is_exact_not_a_substring(probe,header):
    raw=("    1 Thread_1   "+header+"\n    + 1 semaphore_wait_trap  (in libsystem_kernel.dylib) + 8 [0x1]\n").encode()
    assert probe.parse_process_sample(raw)["main_thread_found"] is False
    assert probe.parse_process_sample(raw)["frames"]==[]


def test_any_later_thread_header_ends_main_capture_and_frames_are_capped(probe):
    prefix=b"    1 Thread_1   DispatchQueue_1: com.apple.main-thread  (serial)\n"
    row=b"    + 1 semaphore_wait_trap  (in libsystem_kernel.dylib) + 8 [0x1]\n"
    observed=probe.parse_process_sample(prefix+row*100+b"    1 Thread_unknown other\n"+row*100,truncated=True)
    assert observed["frame_count"]==probe.PROCESS_SAMPLE_MAX_FRAMES and observed["truncated"] is True
    observed=probe.parse_process_sample(prefix+row+b"    1 Thread_unknown other\n"+row)
    assert observed["frame_count"]==1


def test_projection_and_stdout_summary_cannot_add_raw_sample_content(probe):
    dirty={"schema":1,"available":True,"attempted":True,"error_code":"none","frames":[
        {"module":"UIKitCore","symbol":"-[UIDocumentPickerViewController init]","samples":1,
         "arguments":"DO-NOT-EXPORT"}],"raw":"DO-NOT-EXPORT","path":"DO-NOT-EXPORT",
        "sample_output_bytes":True,"frame_count":1000000,"elapsed":float("nan")}
    clean=probe.process_sample_observation(dirty)
    assert clean["frame_count"]==1 and "DO-NOT-EXPORT" not in json.dumps(clean)
    summary=probe.safe_failure_summary({"error":"settings_zip_import_picker_failed","process_sample":dirty})
    assert summary["process_sample"]["frame_count"]==1
    assert "frames" not in summary["process_sample"] and "UIKitCore" not in json.dumps(summary)
    assert "DO-NOT-EXPORT" not in json.dumps(summary)


@pytest.fixture(scope="module")
def builder():
    # Use the real producer's plist/command rather than a separately invented
    # executable name in this identity fixture.
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT/"ios-unified"))
        spec=importlib.util.spec_from_file_location("owned_sample_builder",ROOT/"ios-unified/build_probe.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_owned_sampler_matches_actual_probe_producer_identity_and_fixed_image_names(probe,builder):
    assert builder.EXECUTABLE==probe.PROBE_EXECUTABLE=="IdolyEmbeddedProbe"
    info=builder.info_plist()
    assert info["CFBundleIdentifier"]==probe.BUNDLE_ID
    assert info["CFBundleExecutable"]==probe.PROBE_EXECUTABLE
    assert info["CFBundleSupportedPlatforms"]==["iPhoneSimulator"]
    command=builder.clang_command("/owned/clang","/owned/sdk",Path("/owned/Probe.app"),"arm64")
    assert command[-2:]==["-o",str(Path("/owned/Probe.app")/probe.PROBE_EXECUTABLE)]
    native_image=command[command.index("-framework")+1]
    assert native_image=="IdolyEmbeddedServer"
    assert {builder.EXECUTABLE,native_image}<=probe.PROCESS_SAMPLE_MODULES
    assert "Probe" not in probe.PROCESS_SAMPLE_MODULES and "IdolyServer" not in probe.PROCESS_SAMPLE_MODULES


@pytest.fixture
def owned(tmp_path,monkeypatch,probe,builder):
    udid="11111111-1111-4111-8111-111111111111"
    data=tmp_path/"Devices"/udid/"data/Containers/Data/Application/22222222-2222-4222-8222-222222222222"
    bundle=tmp_path/"Devices"/udid/"data/Containers/Bundle/Application/33333333-3333-4333-8333-333333333333/Probe.app"
    source=tmp_path/"input/Probe.app"
    for path in (data,bundle,source):path.mkdir(parents=True)
    info=builder.info_plist()
    (bundle/"Info.plist").write_bytes(plistlib.dumps(info))
    for root in (source,bundle):(root/builder.EXECUTABLE).write_bytes(b"owned immutable fake Mach-O fixture")
    monkeypatch.setattr(probe.sys,"platform","darwin")
    monkeypatch.setattr(probe,"_simctl",lambda arguments,timeout:(str(bundle)+"\n").encode())
    sampler=probe.OwnedProbeProcessSampler(udid,source,data)
    assert sampler.prepare() is True
    sampler.clear_launch();sampler.note_launch((probe.BUNDLE_ID+": 123\n").encode())
    ps_calls=[]
    def ps(arguments,**kwargs):
        assert arguments[0]=="/bin/ps" and arguments[-1]=="-ww"
        ps_calls.append(arguments)
        started=time.strftime("%a %b %d %H:%M:%S %Y",time.localtime(sampler.launch_started))
        return SimpleNamespace(returncode=0,stdout=("123 "+started+" "+str(bundle/builder.EXECUTABLE)+"\n").encode())
    monkeypatch.setattr(probe.subprocess,"run",ps)
    return SimpleNamespace(sampler=sampler,bundle=bundle,source=source,data=data,ps=ps,ps_calls=ps_calls,executable=builder.EXECUTABLE)


def install_sample(monkeypatch,probe,raw=RAW_SAMPLE,returncode=0):
    calls=[]
    class Child:
        pid=99999
        def __init__(self,arguments,**kwargs):
            assert arguments[:4]==[sys.executable,"-I","-S","-c"]
            assert "RLIMIT_FSIZE" in arguments[4] and "'/usr/bin/sample'" in arguments[4]
            assert arguments[-2]=="123" and kwargs["start_new_session"] is True
            self.path=Path(arguments[-1]);self.path.write_bytes(raw);self.returncode=returncode;calls.append(self)
        def poll(self):return self.returncode
        def wait(self,timeout):return self.returncode
    monkeypatch.setattr(probe.subprocess,"Popen",Child)
    return calls


def test_only_verified_launched_image_can_be_sampled_once_and_raw_is_deleted(owned,monkeypatch,probe):
    calls=install_sample(monkeypatch,probe)
    # Sampling no longer depends on Simulator services being responsive.
    monkeypatch.setattr(probe,"_simctl",lambda *args:pytest.fail("No simctl call allowed during failure capture"))
    observed=owned.sampler.capture({"process_id":123})
    assert observed["available"] is True and observed["identity_stable"] is True
    assert observed["launch_pid_matched"] is True and observed["executable_verified"] is True
    assert observed["error_code"]=="none" and len(owned.ps_calls)==2 and len(calls)==1
    assert not calls[0].path.exists() and not calls[0].path.parent.exists()
    assert owned.sampler.capture({"process_id":123}) is None
    assert "DO-NOT-EXPORT" not in json.dumps(observed)


@pytest.mark.parametrize("damage",["no-ack","wrong-checkpoint","same-image-reused-pid","changed-executable","symlink-executable","other-comm"])
def test_unverified_or_reused_process_never_reaches_sample(owned,monkeypatch,probe,damage):
    monkeypatch.setattr(probe.subprocess,"Popen",lambda *args,**kwargs:pytest.fail("Unverified PID must not be sampled"))
    checkpoint={"process_id":123}
    if damage=="no-ack":owned.sampler.note_launch(b"unknown bundle: 123\n")
    elif damage=="wrong-checkpoint":checkpoint["process_id"]=999
    elif damage=="same-image-reused-pid":owned.sampler.launch_ack=owned.sampler.launch_started-10
    elif damage=="changed-executable":(owned.bundle/owned.executable).write_bytes(b"changed")
    elif damage=="symlink-executable":
        (owned.bundle/owned.executable).unlink();(owned.bundle/owned.executable).symlink_to(owned.source/owned.executable)
    elif damage=="other-comm":
        monkeypatch.setattr(probe.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(returncode=0,
            stdout=b"123 Tue Nov 17 00:00:00 2026 /private/other.app/IdolyEmbeddedProbe\n"))
    observed=owned.sampler.capture(checkpoint)
    assert observed["available"] is False and observed["error_code"]!="none"


@pytest.mark.parametrize("damage",["wrong-device","wrong-bundle","wrong-executable","malformed-plist","different-source-bytes"])
def test_preparation_rejects_unowned_container_and_bad_image_without_sampling(owned,monkeypatch,probe,damage):
    sampler=probe.OwnedProbeProcessSampler(owned.sampler.udid,owned.source,owned.data)
    if damage=="wrong-device":sampler.udid="44444444-4444-4444-8444-444444444444"
    elif damage=="wrong-bundle":
        info=plistlib.loads((owned.bundle/"Info.plist").read_bytes());info["CFBundleIdentifier"]="other.app"
        (owned.bundle/"Info.plist").write_bytes(plistlib.dumps(info))
    elif damage=="wrong-executable":
        info=plistlib.loads((owned.bundle/"Info.plist").read_bytes());info["CFBundleExecutable"]="Probe"
        (owned.bundle/"Info.plist").write_bytes(plistlib.dumps(info))
    elif damage=="malformed-plist":(owned.bundle/"Info.plist").write_bytes(plistlib.dumps(["DO-NOT-EXPORT"]))
    elif damage=="different-source-bytes":(owned.source/owned.executable).write_bytes(b"not installed")
    assert sampler.prepare() is False
    sampler.clear_launch();sampler.note_launch((probe.BUNDLE_ID+": 123\n").encode())
    monkeypatch.setattr(probe.subprocess,"Popen",lambda *args,**kwargs:pytest.fail("Do not sample bad image"))
    observed=sampler.capture({"process_id":123})
    assert observed["available"] is False and "DO-NOT-EXPORT" not in json.dumps(observed)


@pytest.mark.parametrize("exit_code",[1,65,-signal.SIGTERM])
def test_nonzero_sample_exit_is_not_mislabelled_as_collected(owned,monkeypatch,probe,exit_code):
    calls=install_sample(monkeypatch,probe,returncode=exit_code)
    observed=owned.sampler.capture({"process_id":123})
    assert observed["available"] is False and observed["error_code"]=="sample_failed"
    assert not calls[0].path.parent.exists()


def test_size_capped_sample_keeps_useful_main_prefix_with_truncation(owned,monkeypatch,probe):
    raw=RAW_SAMPLE+b"x"*(probe.PROCESS_SAMPLE_MAX_BYTES-len(RAW_SAMPLE))
    calls=install_sample(monkeypatch,probe,raw=raw,returncode=-signal.SIGXFSZ)
    observed=owned.sampler.capture({"process_id":123})
    assert observed["available"] is True and observed["truncated"] is True and observed["frame_count"]==5
    assert observed["sample_output_bytes"]==probe.PROCESS_SAMPLE_MAX_BYTES
    assert not calls[0].path.parent.exists()


def test_post_sample_identity_change_discards_stack_and_deletes_raw(owned,monkeypatch,probe):
    calls=install_sample(monkeypatch,probe)
    count=0
    def changed(arguments,**kwargs):
        nonlocal count
        count+=1
        if count==1:return owned.ps(arguments,**kwargs)
        return SimpleNamespace(returncode=1,stdout=b"")
    monkeypatch.setattr(probe.subprocess,"run",changed)
    observed=owned.sampler.capture({"process_id":123})
    assert observed["available"] is False and observed["frames"]==[] and not calls[0].path.parent.exists()


def test_timeout_kills_only_new_sample_group_and_retains_fixed_partial_stack(owned,monkeypatch,probe):
    calls=install_sample(monkeypatch,probe)
    original=probe.subprocess.Popen
    class Pending(original):
        def poll(self):return None if not getattr(self,"stopped",False) else -signal.SIGKILL
        def wait(self,timeout):return -signal.SIGKILL
    monkeypatch.setattr(probe.subprocess,"Popen",Pending)
    clock=iter((0,9));monkeypatch.setattr(probe.time,"monotonic",lambda:next(clock))
    groups=[]
    def killed(pid,sig):
        groups.append((pid,sig));calls[0].stopped=True
    monkeypatch.setattr(probe.os,"killpg",killed)
    observed=owned.sampler.capture({"process_id":123})
    assert observed["timed_out"] is True and observed["error_code"]=="sample_timed_out"
    assert groups==[(99999,signal.SIGKILL)] and groups[0][0]!=owned.sampler.pid
    assert observed["available"] is True and not calls[0].path.parent.exists()


def test_fixed_picker_phase_markers_bracket_calls_without_deadline_changes(probe):
    source=(ROOT/"ios-unified/probe/main.m").read_text()
    block=source.split("static void ProbeZIPPickerCheckpoint(",1)[1].split("// Fixed scalars only:",1)[0]
    assert 'seen.count >= 64' in block and 'pass > 2' in block
    assert '12*NSEC_PER_SEC' in block
    assert block.index('@"settings_zip_import_before_script"',block.index('static void ProbeZIPImportBegin'))<block.index('[web evaluateJavaScript:ProbeSettingsScript(script,')
    assert '@"settings_zip_import_script_submitted"' in block and '@"settings_zip_import_script_completed"' in block
    for phase in ("before_presenter","after_presenter","before_cancel","after_cancel","before_dismiss","after_dismiss"):
        assert 'settings_zip_import_'+phase in block
        assert 'settings_zip_import_'+phase in probe.NATIVE_CHECKPOINT_STAGES
    run=(ROOT/"ios-unified/probe/smoke_probe.py").read_text().split('def run_probe(',1)[1]
    assert run.index('owned_sampler.capture(')<run.index('for action in ("shutdown", "delete")')
    assert run.index('owned_sampler.prepare()')<run.index('stage = "app_launch"')
    assert '0 <' not in probe.PROCESS_SAMPLE_CHILD
    assert "'1','10'" in probe.PROCESS_SAMPLE_CHILD



def test_optional_diagnostic_keeps_top_wait_and_bottom_caller_under_existing_audit_cap(probe):
    frames=[{"module":"Probe","symbol":"ProbeFrame"+str(i),"samples":1} for i in range(48)]
    sample=probe.process_sample_observation({"schema":1,"available":True,"frames":frames})
    report={"schema":1,"status":"FAIL","original_error":"unchanged","padding":"x"*(probe.MAX_JSON-800),"process_sample":sample}
    probe.fit_process_sample_audit(report)
    assert report["original_error"]=="unchanged"
    assert len(json.dumps(report,separators=(",",":"),sort_keys=True).encode())+1<=probe.MAX_JSON
    kept=report["process_sample"]["frames"]
    assert kept[0]["symbol"]=="ProbeFrame0" and kept[-1]["symbol"]=="ProbeFrame47"
    assert report["process_sample"]["truncated"] is True


def test_poll_failure_cannot_escape_diagnostic_boundary_or_leave_raw_file(owned,monkeypatch,probe):
    calls=install_sample(monkeypatch,probe)
    original=probe.subprocess.Popen
    class Broken(original):
        def poll(self):raise RuntimeError("DO-NOT-EXPORT")
    monkeypatch.setattr(probe.subprocess,"Popen",Broken)
    killed=[];monkeypatch.setattr(probe.os,"killpg",lambda pid,sig:killed.append((pid,sig)))
    observed=owned.sampler.capture({"process_id":123})
    assert observed["available"] is False and observed["error_code"]=="sample_failed"
    assert not calls[0].path.parent.exists() and killed==[(99999,signal.SIGKILL)]
    assert "DO-NOT-EXPORT" not in json.dumps(observed)



@pytest.mark.parametrize("module,symbol",[("DocumentManager","-[DOCServiceConnection connection]"),
    ("DocumentManagerUICore","DOCViewControllerCreate"),("FileProvider","-[FPItemManager fetchItem:]"),
    ("FileProviderUI","FPUIManagerWaitForReply")])
def test_known_document_and_file_provider_callers_survive_without_paths_or_arguments(probe,module,symbol):
    row={"module":module,"symbol":symbol,"samples":5,"arguments":"DO-NOT-EXPORT"}
    clean=probe.process_sample_observation({"schema":1,"frames":[row]})
    assert clean["frames"]==[{"module":module,"symbol":symbol,"samples":5}]
    rejected=probe.process_sample_observation({"schema":1,"frames":[{**row,"symbol":symbol+" /private/DO-NOT-EXPORT"}]})
    assert rejected["frames"]==[] and "DO-NOT-EXPORT" not in json.dumps(clean)+json.dumps(rejected)


def presenter_checkpoint(probe,container,language="ko",run_index=0,**changes):
    # Match recordCheckpoint: language/run identity belongs to the host proof,
    # while the selected current-run filename is supplied by language_paths.
    value={"schema":1,"stage":"settings_zip_import_after_presenter","process_id":123,
        "main_thread_checkpoint":True,"checkpoint_count":9,"main_elapsed_seconds":25.0,
        "main_heartbeat_count":42,"unity_host_probe":{"expected_language":language,"run_index":run_index}}
    value.update(changes)
    path=container/"Documents"/probe.language_paths(language,run_index)[2]
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    return path


def test_presenter_watchdog_uses_thirty_unchanged_monotonic_seconds_and_is_per_wait(tmp_path,monkeypatch,probe):
    presenter_checkpoint(probe,tmp_path)
    clock=[100.0];monkeypatch.setattr(probe.time,"monotonic",lambda:clock[0])
    watchdog=probe.ZIPPresenterStallWatchdog(tmp_path,"ko",0)
    watchdog.poll();clock[0]=129.999;watchdog.poll()
    clock[0]=130
    with pytest.raises(probe.ProbeError,match="^settings_zip_import_picker_failed$"):watchdog.poll()
    # A new language wait does not inherit an earlier wait's host clock.
    probe.ZIPPresenterStallWatchdog(tmp_path,"ko",0).poll()


@pytest.mark.parametrize("change",["count","pid","other-stage","missing","malformed","not-main","symlink"])
def test_presenter_watchdog_resets_on_progress_or_unusable_checkpoint(tmp_path,monkeypatch,probe,change):
    path=presenter_checkpoint(probe,tmp_path)
    clock=[0.0];monkeypatch.setattr(probe.time,"monotonic",lambda:clock[0])
    watchdog=probe.ZIPPresenterStallWatchdog(tmp_path,"ko",0);watchdog.poll()
    clock[0]=29
    if change=="count":presenter_checkpoint(probe,tmp_path,checkpoint_count=10)
    elif change=="pid":presenter_checkpoint(probe,tmp_path,process_id=124)
    elif change=="other-stage":presenter_checkpoint(probe,tmp_path,stage="settings_zip_import_picker_attached")
    elif change=="not-main":presenter_checkpoint(probe,tmp_path,main_thread_checkpoint=False)
    elif change=="missing":path.unlink()
    elif change=="malformed":path.write_text("not-json")
    else:
        foreign=tmp_path/"foreign-checkpoint.json";foreign.write_text(path.read_text())
        path.unlink();path.symlink_to(foreign)
    watchdog.poll()
    if path.is_symlink():path.unlink()
    presenter_checkpoint(probe,tmp_path)
    clock[0]=30;watchdog.poll()
    clock[0]=59.999;watchdog.poll()
    clock[0]=60
    with pytest.raises(probe.ProbeError,match="^settings_zip_import_picker_failed$"):watchdog.poll()


@pytest.mark.parametrize("changes",[{"schema":True},{"process_id":True},{"process_id":0},
    {"process_id":2**31},{"checkpoint_count":True},{"checkpoint_count":0},{"checkpoint_count":100001},
    {"stage":"settings_zip_import_after_presenter extra"},{"main_thread_checkpoint":1}])
def test_presenter_watchdog_never_arms_for_untyped_or_other_stage_values(tmp_path,monkeypatch,probe,changes):
    presenter_checkpoint(probe,tmp_path,**changes)
    clock=[0.0];monkeypatch.setattr(probe.time,"monotonic",lambda:clock[0])
    watchdog=probe.ZIPPresenterStallWatchdog(tmp_path,"ko",0);watchdog.poll()
    clock[0]=100;watchdog.poll()


def test_presenter_watchdog_reads_only_current_language_and_return_run_filename(tmp_path,monkeypatch,probe):
    presenter_checkpoint(probe,tmp_path,"ko",0)
    presenter_checkpoint(probe,tmp_path,"en",1)
    clock=[0.0];monkeypatch.setattr(probe.time,"monotonic",lambda:clock[0])
    watchdog=probe.ZIPPresenterStallWatchdog(tmp_path,"en",3);watchdog.poll()
    clock[0]=100;watchdog.poll()
    presenter_checkpoint(probe,tmp_path,"en",3);watchdog.poll()
    clock[0]=129.999;watchdog.poll()
    clock[0]=130
    with pytest.raises(probe.ProbeError,match="^settings_zip_import_picker_failed$"):watchdog.poll()


def test_wait_report_stalled_presenter_fails_into_owned_checkpoint_sampling_before_global_budget(owned,monkeypatch,probe):
    presenter_checkpoint(probe,owned.data)
    clock=[0.0];monkeypatch.setattr(probe.time,"monotonic",lambda:clock[0])
    delays=[]
    def advance(delay):
        assert 0<delay<=0.25
        delays.append(delay);clock[0]+=15
    monkeypatch.setattr(probe.time,"sleep",advance)
    calls=install_sample(monkeypatch,probe)
    with pytest.raises(probe.ProbeError,match="^settings_zip_import_picker_failed$"):
        probe.wait_report(owned.data,lambda:900)
    assert clock[0]==30 and len(delays)==2
    checkpoint=probe.failure_checkpoint(owned.data,"ko",0)
    assert checkpoint["stage"]=="settings_zip_import_after_presenter" and checkpoint["process_id"]==123
    observed=owned.sampler.capture(checkpoint)
    assert observed["available"] is True and observed["executable_verified"] is True
    assert observed["identity_stable"] is True and len(calls)==1
    assert not calls[0].path.parent.exists()


@pytest.mark.parametrize("valid",[True,False])
def test_final_report_precedes_watchdog_and_still_requires_full_native_validation(tmp_path,monkeypatch,probe,valid):
    from test_ios_unified_probe_smoke import native_report
    presenter_checkpoint(probe,tmp_path)
    value=native_report()
    if not valid:value["original_called"]=0
    final=tmp_path/"Documents"/probe.language_paths("ko",0)[0]
    final.write_text(json.dumps(value))
    checked=[];validate=probe.validate_report
    def full_validation(observed):
        checked.append(True)
        return validate(observed)
    monkeypatch.setattr(probe,"validate_report",full_validation)
    monkeypatch.setattr(probe.ZIPPresenterStallWatchdog,"poll",lambda self:pytest.fail("Final report takes priority"))
    if valid:
        observed=probe.wait_report(tmp_path,lambda:900)
        assert observed["original_called"]==1 and observed["unity_host_probe"]["run_index"]==0
    else:
        with pytest.raises(probe.ProbeError,match="^unity_original_gate_failed$"):
            probe.wait_report(tmp_path,lambda:900)
    assert checked==[True]
