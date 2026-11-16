"""Official-import native bridge contracts. All service operations are fake; no login/network."""
from pathlib import Path
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine


USER_ID = "Case_ID-1"
PASSWORD = "Correct P@ssWord"
JOB = "a"*32


def wait_for(check):
    end = time.monotonic()+4
    while time.monotonic() < end:
        if check(): return
        time.sleep(.01)
    raise AssertionError("Fake official worker did not finish")


class FakeOfficialManager:
    def __init__(self):
        self.calls = []; self.closed = False
        self.job = {"schema":1,"state":"idle","job_id":None,"busy":False,"progress":"preparing",
            "error_code":None,"counts":{"cards":2,"items":3,"photos":4},"expires_in_seconds":600,
            "preview":{"manager_name":"Imported manager","public_id":"PUBLIC-1","server_id":"SERVER-1",
                "manager_level":30,"inventory":{"cards":2,"items":3,"photos":4},"password":PASSWORD},
            "password":PASSWORD,"user_id":USER_ID,"ticket":"DO-NOT-EXPORT"}
    def status(self, *, public=True):
        # Deliberately bad fake projection tests the native host's own boundary.
        return dict(self.job)
    def command(self, action, payload):
        self.calls.append((action,dict(payload)))
        if action == "official_inspect": self.job.update(state="verified",job_id=JOB,progress="verified")
        elif action == "official_fetch": self.job.update(state="ready",progress="ready")
        elif action == "official_cancel": self.job.update(state="cancelled",progress="cancelled")
        elif action == "official_apply": self.job.update(state="completed",progress="completed")
        result={"action":action,"job":dict(self.job),"password":PASSWORD}
        if action == "official_apply":
            result.update(account={"mode":"normal","profile":payload["profile"],"revision":"b"*64},
                status={"accounts":[],"selected":{"normal":"sandbox","media":"sandbox"},"selection_revision":"c"*64})
        return result
    def close(self): self.closed = True


@pytest.fixture
def official(tmp_path,monkeypatch):
    folder=tmp_path/"protocol";folder.mkdir()
    (folder/"idolypride-6.1.1.pb").write_bytes(b"fake protocol; never used for network")
    events=[];manager=FakeOfficialManager()
    monkeypatch.setitem(sys.modules,"idoly_local.official_import",SimpleNamespace(
        OfficialImportManager=lambda root: manager,ERROR_CODES=frozenset(("official_expired",))))
    value=engine.Controller(tmp_path,tmp_path/"ServerData.zip",emit_event=lambda name,**data:events.append((name,data)))
    return value,manager,events


def invoke(value,action,payload,identifier=1):
    command={"action":action,"request_id":identifier,**payload}
    value.official(action,command)
    wait_for(lambda:value.official_worker is None)
    return command


def test_credentials_are_case_exact_memory_only_and_public_status_is_sanitized(official):
    value,manager,events=official
    command=invoke(value,"official_inspect",{"user_id":USER_ID,"password":PASSWORD,"platform":"ios"})
    assert "user_id" not in command and "password" not in command
    assert manager.calls == [("official_inspect",{"user_id":USER_ID,"password":PASSWORD,"platform":"ios"})]
    explicit=next(data["result"] for name,data in events if name=="official_result")
    assert explicit["job"]["preview"]["public_id"]=="PUBLIC-1"
    assert "preview" not in value.status()["official_import"]
    assert all(secret not in json.dumps(events) for secret in (USER_ID,PASSWORD,"DO-NOT-EXPORT"))
    assert manager.calls[0][1]["password"] == PASSWORD


def test_inspection_and_status_never_implicitly_fetch_login_or_apply(official):
    value,manager,events=official
    invoke(value,"official_inspect",{"user_id":USER_ID,"password":PASSWORD,"platform":"android"})
    for identifier in range(2,5): invoke(value,"official_status",{},identifier)
    assert [action for action,payload in manager.calls]==["official_inspect",*(["official_status"]*3)]
    invoke(value,"official_fetch",{"job_id":JOB},5)
    invoke(value,"official_cancel",{"job_id":JOB},6)
    assert [action for action,payload in manager.calls][-2:]==["official_fetch","official_cancel"]
    assert manager.job["state"]=="cancelled"


@pytest.mark.parametrize("payload",[
    {"user_id":"bad id","password":PASSWORD,"platform":"ios"},
    {"user_id":USER_ID,"password":" leading","platform":"ios"},
    {"user_id":USER_ID,"password":"trailing ","platform":"ios"},
    {"user_id":USER_ID,"password":"line\nbreak","platform":"ios"},
    {"user_id":USER_ID,"password":"é","platform":"ios"},
    {"user_id":USER_ID,"password":PASSWORD,"platform":"other"},
    {"user_id":USER_ID,"password":PASSWORD,"platform":"ios","retry":True},
])
def test_invalid_credentials_or_extra_options_never_reach_service(official,payload):
    value,manager,events=official
    command=invoke(value,"official_inspect",payload)
    assert manager.calls==[]
    assert events[-1]==("official_error",{"request_id":1,"action":"official_inspect","code":"official_request_invalid"})
    assert "password" not in command and "user_id" not in command


@pytest.mark.parametrize("identifier",[None,True,0,-1,2**31,"1"])
def test_official_request_ids_must_be_bounded_integers(official,identifier):
    value,manager,events=official
    invoke(value,"official_status",{},identifier)
    assert manager.calls==[] and events[-1][1]["code"]=="official_request_invalid"


@pytest.mark.parametrize("replace",[False,True])
def test_all_official_apply_operations_require_fully_stopped_runtime_and_preserve_cas(official,replace):
    value,manager,events=official
    payload={"job_id":JOB,"profile":"imported","replace":replace,"expected_revision":"b"*64 if replace else None}
    runtime=SimpleNamespace(status=lambda:{"running":True,"profile":"sandbox"})
    value.runtime=runtime
    invoke(value,"official_apply",payload)
    assert manager.calls==[] and events[-1][1]["code"]=="official_server_running"
    value.runtime=None
    invoke(value,"official_apply",payload,2)
    assert manager.calls==[("official_apply",payload)]
    result=next(data["result"] for name,data in events if name=="official_result")
    assert result["account"]=={"mode":"normal","profile":"imported","revision":"b"*64}
    assert result["status"]["selected"]["normal"]=="sandbox" and value.profile=="sandbox"
    assert "mode" not in manager.calls[0][1]


def test_busy_command_keeps_status_responsive_blocks_start_and_drops_late_results(official):
    value,manager,events=official
    entered,release=threading.Event(),threading.Event()
    def command(action,payload):
        entered.set();assert release.wait(3)
        return {"action":action,"job":manager.job}
    manager.command=command
    value.official("official_status",{"request_id":1})
    assert entered.wait(2)
    assert value.status()["running"] is False
    assert value.start() is not None and value.worker is None
    value.official("official_status",{"request_id":2})
    assert events[-1][1]["code"]=="official_operation_busy"
    value.closed=True;release.set();wait_for(lambda:value.official_worker is None)
    assert not any(name=="official_result" for name,data in events)


def test_service_errors_never_echo_credentials_and_close_cancels_manager(official):
    value,manager,events=official
    def fail(action,payload): raise RuntimeError(PASSWORD+USER_ID)
    manager.command=fail
    invoke(value,"official_inspect",{"user_id":USER_ID,"password":PASSWORD,"platform":"ios"})
    assert any(name=="official_error" and data["code"]=="official_operation_failed" for name,data in events)
    assert PASSWORD not in json.dumps(events) and USER_ID not in json.dumps(events)
    value.close();assert manager.closed is True


def test_official_job_projection_rejects_unbounded_or_private_content():
    job={"state":"ready","job_id":JOB,"progress":[],"busy":True,"error_code":"DO-NOT-EXPORT",
         "counts":{"cards":True,"items":-1,"photos":2**31},"expires_in_seconds":99999,
         "preview":{"public_id":"PUBLIC-1","manager_name":"name","password":PASSWORD},"password":PASSWORD}
    public=engine._official_job(job)
    assert public["counts"]=={} and public["expires_in_seconds"]==0 and public["error_code"] is None
    assert "preview" not in public and PASSWORD not in json.dumps(public)
    assert engine._official_job({"state":[]})["state"]=="failed"


def test_official_committing_phase_is_public_busy_metadata_without_private_summary():
    public=engine._official_job({"state":"ready","progress":"applying","job_id":JOB,"busy":True,
        "expires_in_seconds":20,"preview":{"public_id":"PRIVATE-PREVIEW"}})
    assert public["state"]=="ready" and public["progress"]=="applying" and public["busy"] is True
    assert "preview" not in public


def test_native_official_ui_uses_secure_ram_fields_explicit_stages_and_context_bound_selection():
    source=(Path(__file__).resolve().parents[1]/"App.swift").read_text()
    panel=source.split("struct OfficialImportControls: View",1)[1].split("struct ServerView: View",1)[0]
    assert '@State private var transferID = ""' in panel
    assert '@State private var transferPassword = ""' in panel and 'SecureField(' in panel
    assert 'model.inspectOfficial(userID: transferID, password: transferPassword)' in panel
    assert 'transferID = ""; transferPassword = ""' in panel
    assert 'official_fetch' in source and 'official_apply' in source and 'official_cancel' in source
    assert 'privateSummary: false' in source and 'privateSummary: true' in source
    assert 'identifier == pendingOfficialID' in source and 'event["action"] as? String == pendingOfficialAction' in source
    assert 'if action == "accounts_select", let profile = activationProfile' in source
    assert 'mediaMode = false; accountMode = "normal"' in source
    assert 'bytes.resetBytes(in: 0..<bytes.count)' in source
    assert 'UserDefaults' not in panel and 'appendLog' not in panel
    assert 'text("2. 공식 인계 로그인·내려받기", "2. Official transfer login and download", "2. 公式引き継ぎログイン・取得")' in panel
    assert '.onDisappear { transferID = ""; transferPassword = "" }' in panel
