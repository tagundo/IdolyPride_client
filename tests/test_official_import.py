"""Offline official-to-local staging: explicit steps, exact bytes, identity and rollback."""
from dataclasses import dataclass
import errno
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from zipfile import ZipFile

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import pytest

from idoly_local.account_manager import AccountManager, selected_profile
from idoly_local.application import Application
from idoly_local.official_account import OfficialAccountError
from idoly_local.official_import import OfficialImportManager, OfficialImportError, ERROR_CODES, STAGES
from idoly_local.rpc import RpcCode
from idoly_local.state import State

UNKNOWN = b"\x80\x4b\x7b"
PASSWORD = "private password canary"
PUBLIC = "private-official-public"
SERVER = "private-official-server"
NAME = "PrivateMgr"
MASTER = "official-master-v1"


@pytest.fixture
def schema():
    file = descriptor_pb2.FileDescriptorProto(name="official-import-test.proto", package="api", syntax="proto3")
    def message(name, fields):
        value = file.message_type.add(name=name)
        for name, number, kind, repeated, typename in fields:
            field = value.field.add(name=name, number=number, label=3 if repeated else 1, type=kind)
            if typename: field.type_name = ".api."+typename
        return value
    message("User", [("name",1,9,False,None),("managerLevel",100,5,False,None)])
    message("UserPublic", [("serverUserId",1,9,False,None),("publicUserId",2,9,False,None)])
    for name, key in (("OwnedCard","cardId"),("OwnedItem","itemId"),("OwnedPhoto","photoId")):
        message(name, [(key,1,9,False,None)])
    message("UserGetResponse", [("user",1,11,False,"User"),("cards",3,11,True,"OwnedCard"),
        ("items",4,11,True,"OwnedItem"),("photos",5,11,True,"OwnedPhoto"),("userPublic",999,11,False,"UserPublic")])
    message("MasterTag", [("version",1,9,False,None)])
    message("MasterResponse", [("masterTag",1,11,False,"MasterTag")])
    message("SettingInfo", [("value",1,5,False,None)])
    message("LessonProgress", [("value",1,5,False,None)])
    message("HomeLoginRequest", [("settingInfo",1,11,False,"SettingInfo")])
    message("LessonResponse", [("progress",1,11,False,"LessonProgress")])
    message("Receipt", [("value",1,5,False,None)])
    pool = descriptor_pool.DescriptorPool(); pool.Add(file)
    names = ("UserGetResponse","MasterResponse","HomeLoginRequest","LessonResponse","Receipt")
    classes = {name: message_factory.GetMessageClass(pool.FindMessageTypeByName("api."+name)) for name in names}
    def response_type(path):
        return classes[{"/api.User/Get":"UserGetResponse", "/api.Master/Get":"MasterResponse",
            "/api.Activity/ReceiveLessonReward":"LessonResponse"}.get(path,"Receipt")]
    return SimpleNamespace(response_type=response_type, request_type=lambda _: classes["HomeLoginRequest"],
        fingerprint=hashlib.sha256(b"official-import-schema").hexdigest(),
        methods={"/api.User/Get":SimpleNamespace(client_streaming=False,server_streaming=False)})


def snapshot(schema, *, server=SERVER, public=PUBLIC, name=NAME, card="card-a"):
    value = schema.response_type("/api.User/Get")()
    value.user.name = name; value.user.managerLevel = 31
    value.userPublic.serverUserId = server; value.userPublic.publicUserId = public
    value.cards.add(cardId=card); value.items.add(itemId="item-a"); value.photos.add(photoId="photo-instance")
    return value.SerializeToString()+UNKNOWN


class Timer:
    instances = []
    def __init__(self, interval, callback, args=()):
        self.interval, self.callback, self.args = interval, callback, args
        self.cancelled, self.started, self.daemon = False, False, False
        self.instances.append(self)
    def start(self): self.started = True
    def cancel(self): self.cancelled = True
    def fire(self): self.callback(*self.args)


class Verification:
    def __init__(self, clock, platform):
        self.public_id, self.server_id = PUBLIC, None
        self.manager_name, self.manager_level, self.platform = NAME, 31, platform
        self.created_at, self.expires_at = int(clock[0]), int(clock[0])+600
        self.closed, self.consumed = False, False
        self.private_ticket = "private-ticket-canary"
    def close(self): self.closed, self.private_ticket = True, None


@dataclass(repr=False)
class Collected:
    user_get: bytes
    master_get: bytes
    master_version: str = MASTER
    server_id: str = SERVER
    public_id: str = PUBLIC
    platform: str = "ios"
    closed: bool = False
    def close(self): self.user_get, self.master_get, self.closed = b"", b"", True


class Client:
    def __init__(self, env, platform):
        self.env, self.platform, self.closed = env, platform, False
        self.verification, self.collected = None, None
    def inspect(self, user_id, password, *, cancel, progress):
        self.env.calls.append("inspect")
        self.env.credentials_ok = user_id == "transfer-id" and password == PASSWORD
        self.env.inspect_started.set()
        if self.env.inspect_gate is not None:
            assert self.env.inspect_gate.wait(3), "offline inspect release timed out"
        if self.env.inspect_error is not None: raise self.env.inspect_error
        progress("verified")
        self.verification = Verification(self.env.clock, self.platform)
        return self.verification
    def fetch(self, verification, *, cancel, progress):
        assert verification is self.verification and not verification.closed
        self.env.calls.append("fetch")
        verification.consumed = True
        self.env.fetch_started.set()
        if self.env.fetch_gate is not None:
            assert self.env.fetch_gate.wait(3), "offline fetch release timed out"
        if self.env.fetch_error is not None: raise self.env.fetch_error
        progress("account")
        master = self.env.schema.response_type("/api.Master/Get")()
        master.masterTag.version = self.env.remote_version
        self.collected = Collected(self.env.raw, master.SerializeToString()+UNKNOWN,
            master_version=self.env.remote_version, platform=self.platform)
        return self.collected
    def close(self):
        self.closed = True
        if self.verification is not None: self.verification.close()


@pytest.fixture
def env(tmp_path, schema):
    (tmp_path/"original-master").mkdir()
    (tmp_path/"master-json").mkdir()
    (tmp_path/"original-master/master-tag.json").write_text(json.dumps({"version":MASTER}))
    (tmp_path/"master-json/!version.txt").write_text(MASTER)
    for table, identity in (("Card","card-a"),("Item","item-a")):
        (tmp_path/("master-json/"+table+".json")).write_text(json.dumps([{"id":identity}]))
    accounts = AccountManager(tmp_path, schema=schema)
    value = SimpleNamespace(root=tmp_path,schema=schema,accounts=accounts,clock=[1800000000.0],calls=[],clients=[],
        raw=snapshot(schema),remote_version=MASTER,inspect_gate=None,fetch_gate=None,
        inspect_error=None,fetch_error=None,credentials_ok=False,
        inspect_started=threading.Event(),fetch_started=threading.Event())
    def factory(protocol, *, platform):
        assert protocol is value.accounts._schema()
        client = Client(value,platform); value.clients.append(client); return client
    value.manager = OfficialImportManager(tmp_path, accounts=accounts, client_factory=factory,
        now=lambda: value.clock[0], timer_factory=Timer)
    yield value
    if value.inspect_gate is not None: value.inspect_gate.set()
    if value.fetch_gate is not None: value.fetch_gate.set()
    value.manager.close()
    if value.manager._thread is not None: value.manager._thread.join(timeout=3)


def finish(env, expected):
    env.manager._thread.join(timeout=3)
    assert not env.manager._thread.is_alive()
    assert env.manager.status()["state"] == expected
    return env.manager.status(public=False)


def inspect(env, platform="ios"):
    payload = {"user_id":"transfer-id", "password":PASSWORD, "platform":platform}
    result = env.manager.command("official_inspect",payload)
    # Native hosts clear their credential dictionary as soon as command returns.
    payload.clear()
    return result["job"]["job_id"]


def ready(env):
    job_id = inspect(env); finish(env,"verified")
    env.manager.command("official_fetch",{"job_id":job_id}); finish(env,"ready")
    return job_id


def apply(env, job_id, profile="imported", *, replace=False, revision=None):
    return env.manager.command("official_apply", {"job_id":job_id,"profile":profile,
        "replace":replace,"expected_revision":revision})


def populate(env, profile, mode="normal"):
    state = env.accounts._state(mode)
    identity = state.ensure_profile(profile)
    raw = snapshot(env.schema,server=identity["server_id"],public=identity["public_id"],name="OldMgr")
    state.save_snapshot(profile,raw,env.schema.fingerprint,starter_version=7)
    with state.connect() as db:
        db.execute("INSERT INTO profile_settings VALUES (?,?,?)",(profile,b"\x08\x01"+UNKNOWN,env.schema.fingerprint))
        db.execute("INSERT INTO profile_lesson_progress VALUES (?,?,?)",(profile,b"\x08\x02"+UNKNOWN,env.schema.fingerprint))
        db.execute("INSERT INTO preference_receipts VALUES (?,?,?,?,?,?)",(profile,"/api.Photograph/ToggleLock",
            "5","a"*64,env.schema.fingerprint,b"\x08\x03"+UNKNOWN))
        db.execute("INSERT INTO main_live_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",(profile,"9","b"*64,"/api.Quest/Start",
            env.schema.fingerprint,"master","rules","42",1800000000000,b"\x08\x04"+UNKNOWN))
    return state


def test_inspect_is_separate_from_fetch_and_keeps_credentials_out_of_status_and_disk(env):
    env.inspect_gate = threading.Event()
    job_id = inspect(env)
    assert env.inspect_started.wait(3)
    assert env.manager.status()["state"] == "checking"
    assert env.manager.status()["busy"] is True
    env.inspect_gate.set(); full = finish(env,"verified")
    assert env.credentials_ok and env.calls == ["inspect"]
    public = env.manager.status()
    assert set(public) == {"schema","state","job_id","progress","error_code","counts","busy","expires_in_seconds"}
    assert full["preview"]["public_id"] == PUBLIC and full["preview"]["server_id"] is None
    assert full["preview"]["manager_name"] == NAME
    rendered = json.dumps(public)
    assert all(value not in rendered for value in (PASSWORD,PUBLIC,SERVER,NAME,"private-ticket-canary"))
    assert all(value not in repr(env.manager) for value in (PASSWORD,PUBLIC,SERVER,NAME,"private-ticket-canary"))
    assert not (env.root/"state.db").exists() and not (env.root/"media-state.db").exists()
    assert not list((env.accounts.base).rglob("*.zip"))
    assert env.manager.command("official_status",{})["job"]["job_id"] == job_id


def test_fetch_stages_only_exact_user_data_and_apply_creates_normal_slot_without_selecting(env):
    original = env.raw
    job_id = ready(env)
    assert env.calls == ["inspect","fetch"]
    assert all(client.closed and client.verification.closed and client.collected.closed for client in env.clients)
    assert not (env.root/"state.db").exists() and not (env.root/"media-state.db").exists()
    assert env.manager.status()["counts"] == {"cards":1,"items":1,"photos":1}
    staged = list((env.accounts.base/"imports").glob("*.zip"))
    assert len(staged) == 1
    with ZipFile(staged[0]) as archive:
        assert set(archive.namelist()) == {"manifest.json","account.json"}
        content = archive.read("account.json")
        assert PASSWORD.encode() not in content and b"private-ticket-canary" not in content
    result = apply(env,job_id)
    state = env.accounts._state("normal")
    assert state.snapshot("imported") == (original,env.schema.fingerprint)
    bundle, revision = state.account_snapshot("imported")
    assert set(bundle["tables"]) == {"profiles","snapshots","starter_profiles","profile_settings",
        "profile_lesson_progress","preference_receipts","main_live_attempts"}
    assert bundle["tables"]["starter_profiles"] == [{"profile":"imported","version":0}]
    assert all(not bundle["tables"][key] for key in ("profile_settings","profile_lesson_progress","preference_receipts","main_live_attempts"))
    assert state.profile("imported")["server_id"] == SERVER
    assert state.profile("imported")["public_id"] == PUBLIC
    assert result["account"]["mode"] == "normal" and result["account"]["profile"] == "imported"
    assert result["account"]["revision"] == revision and result["job"]["state"] == "completed"
    assert selected_profile(env.root,False) == "sandbox" and selected_profile(env.root,True) == "sandbox"
    assert not (env.root/"media-state.db").exists()
    assert not list((env.accounts.base/"imports").glob("*.zip"))
    assert not list((env.accounts.base/"imports").glob("*.json"))


def test_replace_requires_current_revision_and_creates_complete_restore_point(env):
    state = populate(env,"target"); populate(env,"other"); media = populate(env,"gallery","media")
    old, old_revision = state.account_snapshot("target")
    other, media_before = state.account_snapshot("other"), media.account_snapshot("gallery")
    target_token,_ = state.login("target"); other_token,_ = state.login("other")
    job_id = ready(env)
    with pytest.raises(OfficialImportError) as error:
        apply(env,job_id,"target",replace=True,revision="0"*64)
    assert error.value.code == "account_revision_conflict"
    assert env.manager.status()["state"] == "ready"
    assert state.account_snapshot("target") == (old,old_revision)
    assert state.authenticated(target_token,"target")
    assert env.accounts.status()["restore_points"] == []
    result = apply(env,job_id,"target",replace=True,revision=old_revision)
    assert not state.authenticated(target_token,"target") and state.authenticated(other_token,"other")
    assert state.snapshot("target")[0] == env.raw
    assert state.account_snapshot("other") == other and media.account_snapshot("gallery") == media_before
    points = result["status"]["restore_points"]
    assert len(points) == 1 and points[0]["revision"] == old_revision
    current = result["account"]["revision"]
    env.accounts.command("accounts_restore",{"mode":"normal","profile":"target","id":points[0]["id"],"expected_revision":current})
    assert state.account_snapshot("target") == (old,old_revision)
    assert state.account_snapshot("other") == other and media.account_snapshot("gallery") == media_before


@pytest.mark.parametrize("change,code", [("version","official_master_mismatch"),("reference","official_catalog_reference_missing"),
    ("catalog_missing","official_catalog_unavailable"),("identity","official_snapshot_invalid")])
def test_fetch_compatibility_failures_never_create_a_slot_or_keep_a_stage(env,change,code):
    if change == "version": env.remote_version = "different-master"
    elif change == "reference": env.raw = snapshot(env.schema,card="missing-card")
    elif change == "catalog_missing": (env.root/"master-json/Item.json").unlink()
    else: env.raw = snapshot(env.schema,server="different-server")
    job_id = inspect(env); finish(env,"verified")
    env.manager.command("official_fetch",{"job_id":job_id})
    result = finish(env,"failed")
    assert result["error_code"] == code and "preview" not in result
    assert env.calls == ["inspect","fetch"] and all(c.closed for c in env.clients)
    assert not (env.root/"state.db").exists()
    assert not list(env.accounts.base.rglob("*.zip"))


@pytest.mark.parametrize("change,code", [("catalog","official_catalog_changed"),("schema","official_protocol_changed")])
def test_apply_rechecks_compatibility_after_preview_without_mutating_target(env,change,code):
    state = populate(env,"target"); before = state.account_snapshot("target"); token,_ = state.login("target")
    job_id = ready(env)
    if change == "catalog":
        with (env.root/"master-json/Card.json").open("a") as stream: stream.write(" ")
    else:
        env.accounts._schema_override = SimpleNamespace(**{**vars(env.schema),"fingerprint":"f"*64})
    with pytest.raises(OfficialImportError) as error: apply(env,job_id,"target",replace=True,revision=before[1])
    assert error.value.code == code and env.manager.status()["state"] == "failed"
    assert state.account_snapshot("target") == before and state.authenticated(token,"target")
    assert not list((env.accounts.base/"imports").glob("*.zip"))


def test_cancel_during_inspect_drops_late_result_and_does_not_allow_parallel_login(env):
    env.inspect_gate = threading.Event(); job_id = inspect(env)
    assert env.inspect_started.wait(3)
    env.manager.command("official_cancel",{"job_id":job_id})
    assert env.manager.status()["state"] == "cancelled" and env.manager.status()["busy"]
    with pytest.raises(OfficialImportError,match="official_job_busy"): inspect(env)
    env.inspect_gate.set(); finish(env,"cancelled")
    assert not env.manager.status()["busy"] and all(c.closed and c.verification.closed for c in env.clients)
    assert env.calls == ["inspect"] and not (env.root/"state.db").exists()


def test_cancel_during_fetch_discards_late_collected_bytes_and_zip(env):
    job_id = inspect(env); finish(env,"verified")
    env.fetch_gate = threading.Event()
    env.manager.command("official_fetch",{"job_id":job_id}); assert env.fetch_started.wait(3)
    env.manager.command("official_cancel",{"job_id":job_id})
    env.fetch_gate.set(); finish(env,"cancelled")
    assert all(c.closed and c.collected.closed for c in env.clients)
    assert not list(env.accounts.base.rglob("*.zip")) and not (env.root/"state.db").exists()


@pytest.mark.parametrize("stage", ["verified","ready"])
def test_expiry_timer_closes_ticket_and_removes_private_staging_without_status_poll(env,stage):
    if stage == "ready": ready(env)
    else: inspect(env); finish(env,"verified")
    job = env.manager._job; timer = job.timer
    assert timer.started and timer.daemon and timer.interval <= 600
    # Timer is monotonic in production; it must expire even after a wallclock setback.
    env.clock[0] -= 1000
    timer.fire()
    assert job.state == "failed" and job.error_code == "official_session_expired"
    assert job.preview is None and job.client is None and job.verification is None and job.stage_token is None
    assert timer.cancelled and all(client.closed for client in env.clients)
    assert not list(env.accounts.base.rglob("*.zip")) and not (env.root/"state.db").exists()


def test_replaced_expiry_timer_cannot_cancel_newer_verified_ticket(env):
    inspect(env); initial = env.manager._job.timer
    finish(env,"verified"); current = env.manager._job.timer
    assert initial is not current and initial.cancelled
    initial.fire()
    assert env.manager.status()["state"] == "verified" and not current.cancelled


def test_atomic_apply_is_not_interrupted_by_cancel_or_expiry(env,monkeypatch):
    job_id = ready(env); job = env.manager._job; original = env.accounts.command
    def command(action,payload):
        assert env.manager.status()["state"] == "ready"
        assert env.manager.status()["progress"] == "applying" and env.manager.status()["busy"]
        with pytest.raises(OfficialImportError,match="official_apply_in_progress"):
            env.manager.command("official_cancel",{"job_id":job_id})
        env.clock[0] += 1000; job.timer.fire()
        assert env.manager.status()["state"] == "ready"
        return original(action,payload)
    monkeypatch.setattr(env.accounts,"command",command)
    result = apply(env,job_id)
    assert result["job"]["state"] == "completed" and not result["job"]["busy"]
    assert env.accounts._state("normal").snapshot("imported")[0] == env.raw


def test_close_cancels_ready_job_and_only_its_expendable_files(env):
    state = populate(env,"sandbox"); before = state.account_snapshot("sandbox")
    ready(env); timer = env.manager._job.timer
    env.manager.close()
    assert env.manager.status()["state"] == "cancelled" and timer.cancelled
    assert not list((env.accounts.base/"imports").glob("*.zip"))
    assert state.account_snapshot("sandbox") == before
    with pytest.raises(OfficialImportError,match="official_closed"): inspect(env)


@pytest.mark.parametrize("error,code", [(OfficialAccountError("tls_failed"),"tls_failed"),
    (ValueError(PASSWORD),"official_operation_failed"),(RuntimeError(PASSWORD),"official_operation_failed"),
    (PermissionError(errno.EACCES,PASSWORD),"account_permission_denied"),
    (OSError(errno.ENOSPC,PASSWORD),"account_insufficient_space")])
def test_fixed_errors_preserve_useful_codes_without_remote_or_credential_text(env,error,code):
    env.inspect_error = error
    inspect(env); result = finish(env,"failed")
    assert result["error_code"] == code and code in ERROR_CODES
    assert PASSWORD not in json.dumps(result) and "preview" not in result
    assert all(client.closed for client in env.clients)


@pytest.mark.parametrize("extra", [{"mode":"media"},{"path":"/tmp/account.zip"},{"password":PASSWORD}])
def test_apply_never_accepts_mode_credentials_or_filesystem_paths(env,extra):
    job_id = ready(env)
    payload = {"job_id":job_id,"profile":"target","replace":False,"expected_revision":None,**extra}
    with pytest.raises(OfficialImportError,match="official_command_invalid"):
        env.manager.command("official_apply",payload)
    assert not (env.root/"state.db").exists() and env.manager.status()["state"] == "ready"


class Aborted(Exception):
    def __init__(self, code): self.code = code


class Context:
    def __init__(self,token): self.token = token
    def invocation_metadata(self): return (("x-auth-token",self.token),) if self.token else ()
    def abort(self,code,details): raise Aborted(code)


def application(env,state,captured):
    # Exercise the real dispatch/authentication/fixture ordering without unrelated
    # gameplay constructors. The User.Get request is an empty protobuf.
    app = Application.__new__(Application)
    app.schema,app.state,app.profile = env.schema,state,"target"
    app.master_response,app.media_master_version,app.media_stories = None,None,None
    app.media_mode = False
    app.fixtures = SimpleNamespace(get=lambda path,plain:captured)
    return app


def test_explicit_imported_user_get_outranks_legacy_capture_but_starter_keeps_replay(env):
    state = populate(env,"target"); token,_ = state.login("target")
    original = state.snapshot("target")[0]; captured = b"legacy captured account"
    app = application(env,state,captured)
    assert app.handle("/api.User/Get",b"",Context(token)) == captured
    state.save_snapshot("target",original,env.schema.fingerprint,starter_version=0)
    token,_ = state.login("target")
    assert app.handle("/api.User/Get",b"",Context(token)) == original
    with pytest.raises(Aborted) as error: app.handle("/api.User/Get",b"",Context(None))
    assert error.value.code == RpcCode.UNAUTHENTICATED
    state.save_snapshot("target",original,"0"*64,starter_version=0)
    token,_ = state.login("target")
    with pytest.raises(Aborted) as error: app.handle("/api.User/Get",b"",Context(token))
    assert error.value.code == RpcCode.FAILED_PRECONDITION


def test_public_contract_uses_fixed_states_and_stages(env):
    assert env.manager.status()["state"] == "idle"
    job_id = ready(env)
    assert env.manager.status()["progress"] in STAGES
    with pytest.raises(OfficialImportError,match="official_job_mismatch"):
        env.manager.command("official_fetch",{"job_id":"wrong-job"})
    assert env.calls == ["inspect","fetch"]
    apply(env,job_id)
    with pytest.raises(OfficialImportError,match="official_invalid_state"):
        env.manager.command("official_fetch",{"job_id":job_id})
    assert env.calls == ["inspect","fetch"]


def test_expiry_during_pending_inspect_preserves_expiry_code_when_late_worker_returns(env):
    env.inspect_gate = threading.Event(); inspect(env)
    assert env.inspect_started.wait(3)
    env.manager._job.timer.fire()
    assert env.manager.status()["state"] == "failed" and env.manager.status()["busy"]
    env.inspect_gate.set(); result = finish(env,"failed")
    assert result["error_code"] == "official_session_expired" and not result["busy"]
    assert env.clients[0].closed and env.clients[0].verification.closed
    assert not (env.root/"state.db").exists()


def test_invalid_target_and_revision_have_safe_recoverable_codes(env):
    job_id = ready(env)
    with pytest.raises(OfficialImportError) as error: apply(env,job_id,"../bad")
    assert error.value.code == "account_profile_invalid" and env.manager.status()["state"] == "ready"
    state = populate(env,"target"); before = state.account_snapshot("target")
    with pytest.raises(OfficialImportError) as error: apply(env,job_id,"target",replace=True,revision=None)
    assert error.value.code == "account_revision_required" and state.account_snapshot("target") == before
    assert env.manager.status()["state"] == "ready"
