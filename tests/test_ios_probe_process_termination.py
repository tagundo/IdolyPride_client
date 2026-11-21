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
