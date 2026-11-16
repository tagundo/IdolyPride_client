"""Pure local schedule persistence; no official network or account mutation."""
from copy import deepcopy
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from idoly_local import event_settings as subject

IDS = ("love-23-0514", "love-extra-25-0426")


def catalog(*, available=True):
    return {"schema": 1, "available": available, "ruleset_sha256": "a"*64 if available else None,
        "events": [{"id": identity, "title": "もしも君と恋をしたら " + identity, "supported": True,
            "source_grade": "original_master_and_reference_capture_claim",
            "inference_status": "reference_routes_inferred", "original_start_time_ms": 1700000000000,
            "original_end_time_ms": None, "original_duration_ms": None} for identity in IDS] if available else []}


def entry(identity=IDS[0], start=1700000000000, duration=30*86400000):
    return {"event_id": identity, "start_time_ms": start, "end_time_ms": start+duration}


def settings(*rows, revision=0):
    return {"schema": 1, "revision": revision, "love_events": list(rows)}


@pytest.fixture
def producer(monkeypatch):
    value = catalog()
    monkeypatch.setitem(sys.modules, "idoly_local.love_catalog", SimpleNamespace(event_catalog=lambda root: deepcopy(value)))
    return value


def test_empty_unavailable_status_is_read_only_and_can_freeze_disabled(tmp_path, producer):
    producer.update(catalog(available=False))
    root = tmp_path/"missing"
    observed = subject.event_settings_status(root)
    assert observed == {"schema": 1, "saved": settings(), "effective": None, "restart_required": False,
        "catalog": {"schema": 1, "available": False, "events": [], "ruleset_sha256": None,
            "reason_code": "event_catalog_unavailable"}, "invalid_settings_file": False}
    assert subject.freeze_event_settings(root) == settings() and not root.exists()
    with pytest.raises(subject.EventSettingsError, match="event_settings_catalog_unavailable"):
        subject.event_settings_command(root, "events_save", {"settings": settings(entry()), "expected_revision": 0})
    assert not root.exists()


def test_multiple_overlapping_entries_are_canonical_cas_and_noop_is_stable(tmp_path):
    state = subject.EventSettingsState(tmp_path, catalog=catalog())
    saved = state.save(settings(entry(IDS[1]), entry(IDS[0])), expected_revision=0)
    assert [row["event_id"] for row in saved["love_events"]] == sorted(IDS) and saved["revision"] > 0
    raw = (tmp_path/subject.FILENAME).read_bytes()
    assert state.save(deepcopy(saved), expected_revision=saved["revision"]) == saved
    assert (tmp_path/subject.FILENAME).read_bytes() == raw
    other = subject.EventSettingsState(tmp_path, catalog=catalog())
    with pytest.raises(subject.EventSettingsError, match="event_settings_revision_conflict"):
        other.save(settings(), expected_revision=0)
    assert other.settings() == saved


def test_effective_freeze_is_immutable_disable_preserves_progress_and_global_clock(tmp_path, producer):
    account = tmp_path/"state.db"; account.write_bytes(b"ACCOUNT-PROGRESS-MUST-NOT-BE-OPENED")
    original = account.read_bytes()
    state = subject.EventSettingsState(tmp_path, catalog=catalog())
    saved = state.save(settings(entry()), expected_revision=0)
    frozen = subject.freeze_event_settings(tmp_path)
    assert frozen == saved
    disabled = subject.event_settings_command(tmp_path, "events_save", {
        "settings": settings(revision=saved["revision"]), "expected_revision": saved["revision"]}, effective=frozen)
    assert disabled["saved"]["love_events"] == [] and disabled["effective"] == saved
    assert disabled["restart_required"] is True and account.read_bytes() == original
    assert frozen == saved and subject.freeze_event_settings(tmp_path)["love_events"] == []
    assert subject.event_settings_status(tmp_path)["restart_required"] is False
    disabled["effective"]["love_events"].clear()
    assert frozen == saved  # No alias through returned status.


@pytest.mark.parametrize("row", [entry(start=-1), entry(duration=0), entry(duration=subject.MAX_WINDOW_MS+1),
    {**entry(), "start_time_ms": True}, {**entry(), "end_time_ms": 1.5},
    {**entry(), "end_time_ms": subject.MAX_SAFE_INTEGER+1}, {**entry(), "extra": 1},
    {**entry(), "event_id": "../outside"}])
def test_invalid_periods_and_shapes_are_rejected_without_writing(tmp_path,row):
    state = subject.EventSettingsState(tmp_path, catalog=catalog())
    with pytest.raises(subject.EventSettingsError, match="event_settings_invalid"):
        state.save(settings(row), expected_revision=0)
    assert not (tmp_path/subject.FILENAME).exists()


def test_duplicate_ids_unknown_ids_and_boolean_revisions_are_not_accepted(tmp_path):
    state = subject.EventSettingsState(tmp_path, catalog=catalog())
    for value in (settings(entry(),entry()), {**settings(),"revision":True}, {**settings(),"extra":1}):
        with pytest.raises(subject.EventSettingsError, match="event_settings_invalid"):
            state.save(value, expected_revision=0)
    with pytest.raises(subject.EventSettingsError, match="event_settings_unsupported"):
        state.save(settings(entry("love-unverified")), expected_revision=0)
    with pytest.raises(subject.EventSettingsError):
        state.save(settings(), expected_revision=True)


def test_missing_catalog_keeps_saved_revision_visible_but_blocks_activation(tmp_path,producer):
    state=subject.EventSettingsState(tmp_path,catalog=catalog())
    saved=state.save(settings(entry()),expected_revision=0)
    producer.update(catalog(available=False))
    observed=subject.event_settings_status(tmp_path)
    assert observed["saved"]==saved and observed["catalog"]["available"] is False
    with pytest.raises(subject.EventSettingsError,match="event_settings_catalog_unavailable"):
        subject.freeze_event_settings(tmp_path)
    result=subject.event_settings_command(tmp_path,"events_save",{
        "settings":settings(revision=saved["revision"]),"expected_revision":saved["revision"]})
    assert result["saved"]["love_events"]==[] and subject.freeze_event_settings(tmp_path)["love_events"]==[]


def test_malformed_file_keeps_last_valid_copy_and_never_silently_overwrites(tmp_path,producer):
    state=subject.EventSettingsState(tmp_path,catalog=catalog())
    saved=state.save(settings(entry()),expected_revision=0)
    path=tmp_path/subject.FILENAME;bad=b'{"schema":1,"schema":1,"revision":0,"love_events":[]}'
    path.write_bytes(bad)
    assert state.settings()==saved and state.status()["invalid_settings_file"] is True
    with pytest.raises(subject.EventSettingsError):subject.freeze_event_settings(tmp_path)
    with pytest.raises(subject.EventSettingsError):state.save(settings(revision=saved["revision"]),expected_revision=saved["revision"])
    assert path.read_bytes()==bad


def test_symlink_settings_never_changes_external_file(tmp_path):
    outside=tmp_path/"outside";outside.write_bytes(b"EXTERNAL-MUST-NOT-CHANGE")
    root=tmp_path/"root";root.mkdir();(root/subject.FILENAME).symlink_to(outside)
    state=subject.EventSettingsState(root,catalog=catalog())
    assert state.status()["invalid_settings_file"] is True
    with pytest.raises(subject.EventSettingsError):state.save(settings(entry()),expected_revision=0)
    assert outside.read_bytes()==b"EXTERNAL-MUST-NOT-CHANGE"


def test_failed_atomic_replace_preserves_previous_file_and_cleans_temporary(tmp_path,monkeypatch):
    state=subject.EventSettingsState(tmp_path,catalog=catalog())
    saved=state.save(settings(entry()),expected_revision=0);path=tmp_path/subject.FILENAME;before=path.read_bytes()
    def denied(*args):raise PermissionError("PRIVATE-STORAGE-DETAIL")
    monkeypatch.setattr(subject.os,"replace",denied)
    with pytest.raises(subject.EventSettingsError) as error:
        state.save(settings(revision=saved["revision"]),expected_revision=saved["revision"])
    assert error.value.code=="event_settings_storage_unavailable" and "PRIVATE" not in str(error.value)
    assert path.read_bytes()==before and not list(tmp_path.glob(".server-events-*.tmp"))


@pytest.mark.parametrize("release",["commit","close"])
def test_mutex_release_cannot_report_failure_after_file_commit(tmp_path,monkeypatch,release):
    original=subject.sqlite3.connect
    class Connection:
        def __init__(self,wrapped):self.wrapped=wrapped
        def execute(self,*args):return self.wrapped.execute(*args)
        def commit(self):
            self.wrapped.commit()
            if release=="commit":raise subject.sqlite3.OperationalError("PRIVATE-MUTEX")
        def close(self):
            self.wrapped.close()
            if release=="close":raise OSError("PRIVATE-MUTEX")
    monkeypatch.setattr(subject.sqlite3,"connect",lambda *args,**kwargs:Connection(original(*args,**kwargs)))
    state=subject.EventSettingsState(tmp_path,catalog=catalog())
    saved=state.save(settings(entry()),expected_revision=0)
    assert saved["love_events"]==[entry()] and state.settings()==saved


def test_concurrent_writers_have_one_cas_winner(tmp_path):
    barrier=threading.Barrier(2);results=[]
    def worker(identity):
        state=subject.EventSettingsState(tmp_path,catalog=catalog());barrier.wait()
        try:results.append(("ok",state.save(settings(entry(identity)),expected_revision=0)))
        except subject.EventSettingsError as error:results.append((error.code,None))
    threads=[threading.Thread(target=worker,args=(identity,)) for identity in IDS]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=5);assert not thread.is_alive()
    assert sorted(code for code,value in results)==["event_settings_revision_conflict","ok"]
    assert len(subject.EventSettingsState(tmp_path,catalog=catalog()).settings()["love_events"])==1


def test_command_allowlist_and_catalog_projection_are_bounded(tmp_path,producer):
    for action,payload in (("events_status",{"retry":True}),("events_save",{}),("events_reset",{})):
        with pytest.raises(subject.EventSettingsError,match="event_settings_command_invalid"):
            subject.event_settings_command(tmp_path,action,payload)
    producer["password"]="PRIVATE-CATALOG";producer["events"][0]["token"]="PRIVATE-CATALOG"
    value=subject.event_settings_command(tmp_path,"events_status",{})
    assert "PRIVATE-CATALOG" not in json.dumps(value) and len(json.dumps(value))<16384
    assert value["catalog"]["events"][0]["original_duration_ms"] is None
