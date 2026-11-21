"""Mocked exact-owned PID death and privacy; no Simulator execution claimed."""
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("owned_termination_probe",ROOT/"ios-unified/probe/smoke_probe.py")
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


@pytest.mark.parametrize("value",["2026-11-21 03:07:08.0098 +0000",
    "2026-11-21 03:07:08.0098    +0000","2026-11-21T03:07:08.0098Z",
    "2026-11-21T03:07:08.0098+00:00","2026-11-21 12:07:08.0098 +0900"])
def test_diagnostic_time_accepts_actual_apple_ips_and_explicit_iso_zones(value):
    expected=datetime(2026,11,21,3,7,8,9800,tzinfo=timezone.utc).timestamp()
    assert probe._diagnostic_time(value)==expected


@pytest.mark.parametrize("value",["2026-11-21 03:07:08.0098","2026-11-21 03:07:08.0098 UTC",
    "2026-11-21 03:07:08.0098\n+0000","2026-11-21 03:07:08.0098\t+0000",
    "2026-11-21T03:07:08+2500","2026-13-21T03:07:08Z","not a date",None,True])
def test_diagnostic_time_rejects_missing_zone_invalid_dates_and_unapproved_whitespace(value):
    assert probe._diagnostic_time(value) is None


@pytest.fixture
def owned(tmp_path,monkeypatch):
    udid="11111111-1111-4111-8111-111111111111"
    device=tmp_path/"Devices"/udid
    container=device/"data/Containers/Data/Application/22222222-2222-4222-8222-222222222222"
    container.mkdir(parents=True)
    executable=device/"data/Containers/Bundle/Application/33333333-3333-4333-8333-333333333333/Probe.app"/probe.PROBE_EXECUTABLE
    executable.parent.mkdir(parents=True);executable.write_bytes(b"pinned owned test image")
    sampler=probe.OwnedProbeProcessSampler(udid,executable.parent,container)
    sampler.executable=executable;sampler.executable_pin=probe._sample_executable_identity(executable);sampler.prepare_error="none"
    sampler.clear_launch();sampler.note_launch((probe.BUNDLE_ID+": 123\n").encode())
    clock=[0.0];monkeypatch.setattr(probe.time,"monotonic",lambda:clock[0]);monkeypatch.setattr(probe.sys,"platform","darwin")
    starts=[]
    monkeypatch.setattr(sampler,"_process_identity",lambda path:starts.append(path) or "verified launch start")
    monkeypatch.setattr(probe,"select",SimpleNamespace())  # Portable mocked tests never query a real host PID.
    return SimpleNamespace(sampler=sampler,clock=clock,starts=starts,container=container,device=device,executable=executable)


def test_alive_slow_process_never_fails_and_attestation_and_file_read_run_once(owned,monkeypatch):
    calls=[];reads=[]
    monkeypatch.setattr(probe.os,"kill",lambda pid,sig:calls.append((pid,sig)))
    def checkpoint():reads.append(1);return {"process_id":123}
    for tick in range(40):
        owned.clock[0]=tick;owned.sampler.poll_liveness(checkpoint)
    assert calls==[(123,0)]*40 and len(owned.starts)==len(reads)==1
    assert owned.sampler.termination is None


def test_only_two_separated_esrch_after_attestation_fail_without_adopting_another_pid(owned,monkeypatch):
    queried=[]
    def absent(pid,sig):queried.append((pid,sig));raise ProcessLookupError()
    monkeypatch.setattr(probe.os,"kill",absent)
    owned.sampler.poll_liveness({"process_id":123})
    owned.clock[0]=0.5;owned.sampler.poll_liveness({"process_id":123})
    owned.clock[0]=1.0
    with pytest.raises(probe.ProbeError,match="^owned_probe_process_exited$") as caught:
        owned.sampler.poll_liveness({"process_id":123})
    assert queried==[(123,0),(123,0)]
    assert caught.value.process_termination["confirmed_absence_observations"]==2
    assert owned.sampler.pid==123


def test_slow_initial_attestation_cannot_backdate_the_first_absence(owned,monkeypatch):
    def slow(_):owned.clock[0]=2.0;return "verified launch start"
    monkeypatch.setattr(owned.sampler,"_process_identity",slow)
    calls=[]
    def absent(pid,sig):calls.append(owned.clock[0]);raise ProcessLookupError()
    monkeypatch.setattr(probe.os,"kill",absent)
    owned.sampler.poll_liveness({"process_id":123})
    owned.clock[0]=2.1;owned.sampler.poll_liveness({"process_id":123})
    assert calls==[2.0] and owned.sampler.absent_since==2.0
    owned.clock[0]=3.0
    with pytest.raises(probe.ProbeError,match="owned_probe_process_exited"):
        owned.sampler.poll_liveness({"process_id":123})
    assert calls==[2.0,3.0]


@pytest.mark.parametrize("failure",["permission","query","wrong-pid","no-ack","changed-image"])
def test_uncertain_or_unowned_queries_cannot_establish_exit(owned,monkeypatch,failure):
    checkpoint={"process_id":123}
    if failure=="query":monkeypatch.setattr(owned.sampler,"_process_identity",lambda _:(_ for _ in ()).throw(probe.ProbeError("process_query_timeout")))
    elif failure=="wrong-pid":checkpoint["process_id"]=999
    elif failure=="no-ack":owned.sampler.pid=None
    elif failure=="changed-image":owned.executable.write_bytes(b"changed")
    calls=[]
    def denied(pid,sig):calls.append((pid,sig));raise PermissionError()
    monkeypatch.setattr(probe.os,"kill",denied)
    for tick in range(3):owned.clock[0]=tick;owned.sampler.poll_liveness(checkpoint)
    assert owned.sampler.termination is None
    assert bool(calls)==(failure=="permission")


def test_transient_absence_followed_by_live_or_permission_observation_resets_confirmation(owned,monkeypatch):
    outcomes=iter([ProcessLookupError(),None,ProcessLookupError(),PermissionError(),ProcessLookupError()])
    def query(pid,sig):
        outcome=next(outcomes)
        if outcome is not None:raise outcome
    monkeypatch.setattr(probe.os,"kill",query)
    for tick in range(5):owned.clock[0]=tick;owned.sampler.poll_liveness({"process_id":123})
    assert owned.sampler.termination is None
    owned.sampler.clear_launch()
    assert owned.sampler.process_start_identity is owned.sampler.absent_since is None


def crash(owned,**changes):
    stamp=lambda value:datetime.fromtimestamp(value,timezone.utc).isoformat()
    result={"procName":probe.PROBE_EXECUTABLE,"pid":123,"procPath":str(owned.executable),
        "procLaunch":stamp(owned.sampler.launch_started),"captureTime":stamp(owned.sampler.launch_ack),
        "exception":{"type":"EXC_CRASH","signal":"SIGABRT","reason":"DO-NOT-EXPORT"},
        "termination":{"namespace":"SIGNAL","code":6,"indicator":"DO-NOT-EXPORT"},
        "faultingThread":0,"usedImages":[{"name":"Foundation","path":"DO-NOT-EXPORT"}],
        "threads":[{"frames":[{"imageIndex":0,"symbol":"-[NSObject doesNotRecognizeSelector:]"}]}],
        "account":"DO-NOT-EXPORT"}
    result.update(changes);return result


def parsed(owned,value,**kwargs):
    return probe._owned_termination_record(json.dumps(value).encode(),pid=123,executable=owned.executable,
        launch_started=owned.sampler.launch_started,launch_ack=owned.sampler.launch_ack,ended=owned.sampler.launch_ack+2,**kwargs)


def test_matching_crash_keeps_scalar_cause_and_known_frames_without_raw_reason_or_paths(owned):
    clean=parsed(owned,crash(owned))
    assert clean["termination_code"]==6 and clean["exception_signal"]=="SIGABRT"
    assert clean["frames"][0]["module"]=="Foundation"
    assert "DO-NOT-EXPORT" not in json.dumps(clean) and str(owned.executable) not in json.dumps(clean)


def test_matching_crash_accepts_apple_capture_time_and_process_launch_fields(owned):
    apple=lambda value:datetime.fromtimestamp(value,timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f %z")
    clean=parsed(owned,crash(owned,procLaunch=apple(owned.sampler.launch_started),captureTime=apple(owned.sampler.launch_ack)))
    assert clean["launch_interval_matched"] is clean["capture_interval_matched"] is True


@pytest.mark.parametrize("changes",[{"pid":124},{"pid":True},{"procName":"AnotherApp"},
    {"procPath":"/private/unrelated/IdolyEmbeddedProbe"},{"captureTime":"2000-01-01T00:00:00+00:00"},
    {"procLaunch":"2000-01-01T00:00:00+00:00"},{"captureTime":"not a date"}])
def test_wrong_pid_image_or_time_crash_is_never_retained(owned,changes):
    assert parsed(owned,crash(owned,**changes)) is None


def test_host_jetsam_is_rejected_and_owned_simulator_projection_drops_other_processes(owned):
    value={"date":datetime.fromtimestamp(owned.sampler.launch_ack,timezone.utc).isoformat(),
        "processes":[{"pid":999,"name":"DO-NOT-EXPORT","reason":"DO-NOT-EXPORT"},
            {"pid":123,"name":probe.PROBE_EXECUTABLE,"reason":"per-process-limit","secret":"DO-NOT-EXPORT"}]}
    assert parsed(owned,value) is None
    clean=parsed(owned,value,owned_device=True)
    assert clean["kind"]=="jetsam" and clean["reason"]=="per-process-limit"
    assert "DO-NOT-EXPORT" not in json.dumps(clean)


def test_collector_reads_only_bounded_fresh_probe_ips_under_owned_roots(owned,tmp_path,monkeypatch):
    monkeypatch.setattr(probe.Path,"home",lambda:tmp_path/"home")
    host=tmp_path/"home/Library/Logs/DiagnosticReports";host.mkdir(parents=True)
    ips=host/(probe.PROBE_EXECUTABLE+"-test.ips");ips.write_text(json.dumps({"timestamp":"unused"})+"\n"+json.dumps(crash(owned)))
    (host/"Unrelated.ips").write_text("DO-NOT-READ")
    (host/(probe.PROBE_EXECUTABLE+"-link.ips")).symlink_to(ips)
    owned.sampler.termination={"schema":1,"scope":"owned-disposable-simulator-process","reason":"confirmed_esrch",
        "pid":123,"launch_ack_matched":True,"executable_verified_before_exit":True,"start_identity_verified_before_exit":True,
        "confirmed_absence_observations":2,"ended":owned.sampler.launch_ack+2}
    result=owned.sampler.termination_evidence()
    assert result["matching_record_count"]==1 and result["raw_logs_retained"] is False
    assert "DO-NOT" not in json.dumps(result)
    summary=probe.safe_failure_summary({"error":"owned_probe_process_exited","process_termination":result})
    assert summary["error_code"]=="owned_probe_process_exited" and "records" not in summary["process_termination"]


@pytest.mark.parametrize("damage",[None,"pid","time","run"])
def test_new_minimal_heartbeat_and_account_progress_are_fresh_launch_bound(owned,damage):
    docs=owned.container/"Documents";docs.mkdir()
    value={"schema":1,"process_id":123,"run_index":0,"main_thread_checkpoint":True,"main_thread_heartbeat":True,
        "stage":"settings_account_status_requested","main_heartbeat_count":7,"main_elapsed_seconds":10,
        "footprint_bytes":100,"account_management_progress":{"schema":1,"phase":"status_requested","last_action":"accounts_status",
            "observations":1,"secret":"DO-NOT-EXPORT"}}
    if damage=="pid":value["process_id"]=999
    if damage=="run":value["run_index"]=1
    for suffix in ("heartbeat","account-progress"):
        path=docs/("embedded-probe-"+suffix+".json");path.write_text(json.dumps(value))
        if damage=="time":os.utime(path,(owned.sampler.launch_started-10,)*2)
    result=probe.failure_checkpoint(owned.container,run_index=0,expected_pid=123,launch_started=owned.sampler.launch_started)
    assert ("independent_heartbeat" in result)==(damage is None)
    assert ("account_management_progress" in result)==(damage is None)
    assert "DO-NOT-EXPORT" not in json.dumps(result)


@pytest.fixture
def exit_queue(owned,monkeypatch):
    class Queue:
        def __init__(self): self.calls=[];self.events=[];self.closed=0;self.registration_error=None;self.read_error=None
        def control(self,changes,maximum,timeout):
            self.calls.append((changes,maximum,timeout))
            error=self.registration_error if changes is not None else self.read_error
            if error:raise error
            return [] if changes is not None else self.events[:maximum]
        def close(self): self.closed+=1
    queue=Queue();created=[]
    def create():created.append(1);return queue
    api=SimpleNamespace(kqueue=create,kevent=lambda pid,**fields:SimpleNamespace(ident=pid,**fields),
        KQ_FILTER_PROC=-5,KQ_EV_ADD=1,KQ_EV_ENABLE=4,KQ_EV_ONESHOT=16,KQ_EV_ERROR=0x4000,KQ_NOTE_EXIT=0x80000000)
    monkeypatch.setattr(probe,"select",api)
    monkeypatch.setattr(owned.sampler,"_kernel_birth_identity",lambda:(123456,123456))
    monkeypatch.setattr(probe.os,"kill",lambda pid,sig:None)
    return SimpleNamespace(queue=queue,created=created,api=api)


def test_exit_observer_is_registered_once_only_after_owned_image_start_attestation(owned,exit_queue):
    owned.sampler.poll_liveness({"process_id":999})
    assert exit_queue.created==[]
    owned.clock[0]=1;owned.sampler.poll_liveness({"process_id":123})
    for tick in range(2,5):owned.clock[0]=tick;owned.sampler.poll_liveness({"process_id":123})
    assert len(exit_queue.created)==1 and len(owned.starts)==2
    registration,maximum,timeout=exit_queue.queue.calls[0]
    assert len(registration)==1 and registration[0].ident==123
    assert registration[0].fflags==0x84000000 and maximum==timeout==0
    assert all(call[1:]==(1,0) for call in exit_queue.queue.calls[1:])
    owned.sampler.close();owned.sampler.close()
    assert exit_queue.queue.closed==1


def test_exit_observer_signal_is_bounded_private_and_does_not_replace_two_esrch_gate(owned,exit_queue,monkeypatch):
    owned.sampler.poll_liveness({"process_id":123})
    exit_queue.queue.events=[SimpleNamespace(ident=123,filter=-5,flags=0,fflags=0x84000000,data=13)]
    owned.clock[0]=1;owned.sampler.poll_liveness({"process_id":123})
    assert owned.sampler.termination is None and exit_queue.queue.closed==1
    assert owned.sampler._exit_observation["signal"]==13
    monkeypatch.setattr(probe.os,"kill",lambda pid,sig:(_ for _ in ()).throw(ProcessLookupError()))
    owned.clock[0]=2;owned.sampler.poll_liveness({"process_id":123})
    owned.clock[0]=3
    with pytest.raises(probe.ProbeError,match="^owned_probe_process_exited$") as caught:
        owned.sampler.poll_liveness({"process_id":123})
    clean=probe.process_termination_summary(caught.value.process_termination)
    assert clean["confirmed_absence_observations"]==2 and clean["exit_observer"]["signal"]==13
    assert "records" not in clean and "path" not in json.dumps(clean)
    owned.sampler.clear_launch()
    assert owned.sampler._exit_observation=={} and exit_queue.queue.closed==1


@pytest.mark.parametrize("damage",["wrong-pid","changed-start","registration","read","missing-status","invalid-status"])
def test_exit_observer_uncertain_registration_or_event_closes_fd_without_failing_probe(owned,exit_queue,monkeypatch,damage):
    if damage=="registration":exit_queue.queue.registration_error=PermissionError()
    if damage=="changed-start":
        identities=iter(["first","second"])
        monkeypatch.setattr(owned.sampler,"_process_identity",lambda _:next(identities))
    owned.sampler.poll_liveness({"process_id":123})
    if damage not in ("registration","changed-start"):
        event=SimpleNamespace(ident=999 if damage=="wrong-pid" else 123,filter=-5,flags=0,
            fflags=0x80000000 if damage=="missing-status" else 0x84000000,data=65536 if damage=="invalid-status" else 23<<8)
        exit_queue.queue.events=[event]
        if damage=="read":exit_queue.queue.read_error=OSError()
        owned.clock[0]=1;owned.sampler.poll_liveness({"process_id":123})
    assert exit_queue.queue.closed==1 and owned.sampler._exit_queue is None
    assert owned.sampler.termination is None and owned.sampler._exit_observation["state"]=="unavailable"
    owned.clock[0]=2;owned.sampler.poll_liveness({"process_id":123})
    assert len(exit_queue.created)==1


def test_exit_observer_launch_reset_and_reused_identity_never_adopt_another_process(owned,exit_queue):
    owned.sampler.poll_liveness({"process_id":123})
    owned.sampler.pid=124
    owned.sampler._poll_exit_observer()
    assert owned.sampler._exit_observation["error_code"]=="identity_changed" and exit_queue.queue.closed==1
    assert owned.sampler.termination is None
    owned.sampler.clear_launch()
    assert owned.sampler._exit_attempted is False and owned.sampler.pid is None


@pytest.mark.parametrize("status,expected",[(23<<8,{"exit_code":23}),(0,{"exit_code":0}),(9,{"signal":9}),(139,{"signal":11})])
def test_exit_status_projection_uses_kernel_wait_status_and_drops_extra_fields(status,expected):
    clean=probe.process_exit_observation({"schema":1,"state":"exited","error_code":"none","wait_status":status,
        "signal":999,"exit_code":999,"path":"DO-NOT-EXPORT","reason":"DO-NOT-EXPORT"})
    for key,value in expected.items():assert clean[key]==value
    assert "DO-NOT-EXPORT" not in json.dumps(clean)


def test_zip_restore_policy_requires_callback_detachment_and_both_idle_transitions(tmp_path):
    import shutil,subprocess,itertools
    compiler=shutil.which("cc")
    if not compiler:pytest.skip("C compiler unavailable")
    source=(ROOT/"ios-unified/probe/main.m").read_text()
    body=source.split("static BOOL ProbeZIPPickerRestoreAllowed(",1)[1].split("static BOOL ProbeZIPPickerTransitionBusy",1)[0]
    harness="#include <stdbool.h>\n#include <assert.h>\ntypedef bool BOOL;\nstatic BOOL ProbeZIPPickerRestoreAllowed("+body
    harness+="int main(void) {\n"
    for flags in itertools.product((False,True),repeat=5):
        args=",".join("true" if flag else "false" for flag in flags)
        expected=flags==(True,False,False,False,False)
        harness+=f"assert(ProbeZIPPickerRestoreAllowed({args}) == {'true' if expected else 'false'});\n"
    harness+="return 0;}\n"
    path=tmp_path/"picker.c";path.write_text(harness);binary=tmp_path/"picker"
    result=subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror",str(path),"-o",str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    subprocess.run([str(binary)],check=True)
    picker=source.split("static void ProbeZIPImportObserve(",1)[1].split("static void ProbeZIPImportBegin(",1)[0]
    assert "completion:nil" not in picker
    assert 'pass[@"dismissal_completion_observed"]=@YES' in picker
    assert "ProbeZIPPickerRestoreAllowed(" in picker and 'state[@"dismissal_completed"]' in picker
    for flag in ("dismissal_completion_observed","transition_idle_before_restore"):
        assert flag in probe.ZIP_IMPORT_PASS_BOOL_FIELDS


def test_probe_finally_closes_observer_before_simulator_cleanup():
    run=(ROOT/"ios-unified/probe/smoke_probe.py").read_text().split("def run_probe(",1)[1]
    cleanup=run.split("    finally:\n",1)[1]
    assert cleanup.index("owned_sampler.close()")<cleanup.index('for action in ("shutdown", "delete")')


@pytest.mark.skipif(__import__("sys").platform!="darwin",reason="Actual public Darwin kqueue test requires macOS")
@pytest.mark.parametrize("ending",["exit","signal"])
def test_actual_darwin_kqueue_owned_disposable_child_exit_status_and_fd_close(tmp_path,ending):
    import subprocess,sys,time,signal,select
    sampler=probe.OwnedProbeProcessSampler("unused",tmp_path,tmp_path)
    sampler.clear_launch()
    code="import os,sys,signal;print('ready',flush=True);sys.stdin.buffer.read(1);"+("os._exit(23)" if ending=="exit" else "os.kill(os.getpid(),signal.SIGTERM)")
    child=subprocess.Popen([sys.executable,"-I","-S","-c",code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        assert select.select([child.stdout],[],[],5)[0],"Disposable child readiness deadline"
        assert child.stdout.readline(64)==b"ready\n"
        sampler.pid=child.pid;sampler.launch_ack=time.time();sampler.executable=Path(sys.executable).resolve(strict=True)
        birth=sampler._kernel_birth_identity()
        sampler.process_start_identity=sampler._process_identity(sampler.executable)
        assert sampler._kernel_birth_identity()==birth
        sampler._exit_birth_identity=birth
        sampler._arm_exit_observer()
        assert sampler._exit_observation["state"]=="armed",sampler._exit_observation
        queue=sampler._exit_queue
        child.stdin.write(b"x");child.stdin.flush()
        deadline=time.monotonic()+5
        while sampler._exit_observation["state"]=="armed" and time.monotonic()<deadline:
            sampler._poll_exit_observer();time.sleep(0.01)
        expected={"exit_code":23} if ending=="exit" else {"signal":signal.SIGTERM}
        assert sampler._exit_observation["state"]=="exited",sampler._exit_observation
        for key,value in expected.items():assert sampler._exit_observation[key]==value
        with pytest.raises(ValueError):queue.fileno()
        assert child.wait(timeout=2)==(23 if ending=="exit" else -signal.SIGTERM)
    finally:
        sampler.close()
        if child.poll() is None:child.kill()
        child.wait(timeout=2);child.stdin.close();child.stdout.close()


@pytest.mark.parametrize("moment",["before-register","after-register"])
def test_same_second_pid_reuse_with_identical_ps_identity_is_rejected_by_microsecond_birth(owned,exit_queue,monkeypatch,moment):
    original=(123456,100);reused=(123456,101)
    births=iter([original,original,reused] if moment=="before-register" else [original,original,original,reused])
    monkeypatch.setattr(owned.sampler,"_kernel_birth_identity",lambda:next(births))
    owned.sampler.poll_liveness({"process_id":123})
    assert owned.sampler._exit_observation["error_code"]=="identity_changed"
    assert owned.sampler._exit_queue is None and owned.sampler.termination is None
    assert len(exit_queue.created)==(0 if moment=="before-register" else 1)
    assert exit_queue.queue.closed==(0 if moment=="before-register" else 1)


def test_reset_closes_one_live_observer_fd_before_relaunch(owned,exit_queue):
    owned.sampler.poll_liveness({"process_id":123})
    assert exit_queue.queue.closed==0
    owned.sampler.clear_launch()
    assert exit_queue.queue.closed==1 and owned.sampler._exit_queue is None
    assert owned.sampler._exit_birth_identity is None and owned.sampler._exit_bound_identity is None


@pytest.mark.parametrize("value",[{"schema":True,"state":"exited","error_code":"none","wait_status":0},
    {"schema":1,"state":"exited","error_code":"none","wait_status":True},
    {"schema":1,"state":"exited","error_code":"none","wait_status":127},
    {"schema":1,"state":"exited","error_code":"none","wait_status":-1}])
def test_exit_status_projection_rejects_non_scalar_or_nonterminal_wait_status(value):
    assert probe.process_exit_observation(value)=={}
