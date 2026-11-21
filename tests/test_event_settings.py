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
            "reason_code": "event_catalog_unavailable"}, "invalid_settings_file": False,
        "media_mode": False, "media_default_all": False, "media_all_supported": False}
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


def permanent(identity=IDS[0]):
    return {"event_id": identity, "start_time_ms": 0, "end_time_ms": 0}


def test_media_missing_preferences_enable_all_supported_without_creating_or_changing_files(tmp_path, producer):
    unsupported = deepcopy(producer["events"][0])
    unsupported.update(id="unsupported", supported=False)
    producer["events"].append(unsupported)
    normal = subject.EventSettingsState(tmp_path, catalog=producer)
    saved = normal.save(settings(entry()), expected_revision=0)
    before = (tmp_path / subject.FILENAME).read_bytes()
    state = subject.EventSettingsState(tmp_path, media_mode=True)
    observed = state.status()
    assert observed["saved"] == settings(*(permanent(identity) for identity in sorted(IDS)))
    assert observed["media_mode"] and observed["media_default_all"] and observed["media_all_supported"]
    assert subject.freeze_event_settings(tmp_path, media_mode=True) == observed["saved"]
    assert not (tmp_path / subject.MEDIA_FILENAME).exists()
    assert (tmp_path / subject.FILENAME).read_bytes() == before and normal.settings() == saved


def test_media_choices_have_independent_cas_and_reenable_without_an_expiry_or_progress_writes(tmp_path, producer):
    normal = subject.EventSettingsState(tmp_path, catalog=producer)
    normal_saved = normal.save(settings(entry()), expected_revision=0)
    normal_before = (tmp_path / subject.FILENAME).read_bytes()
    for name in ("state.db", "media-state.db"):
        (tmp_path / name).write_bytes(b"OPAQUE-ACCOUNT-PROGRESS-AND-SESSIONS")
    media = subject.event_settings_command(tmp_path, "events_status", {"mode": "media"})
    selected = subject.event_settings_command(tmp_path, "events_save", {"mode": "media",
        "settings": settings(permanent(IDS[1])), "expected_revision": 0}, effective=media["saved"])
    assert selected["restart_required"] and not selected["media_default_all"] and not selected["media_all_supported"]
    assert selected["saved"]["love_events"] == [permanent(IDS[1])]
    # A stale rapid second click cannot overwrite another committed selection.
    with pytest.raises(subject.EventSettingsError, match="event_settings_revision_conflict"):
        subject.event_settings_command(tmp_path, "events_save", {"mode": "media",
            "settings": settings(), "expected_revision": 0})
    revision = selected["saved"]["revision"]
    enabled = subject.event_settings_command(tmp_path, "events_save", {"mode": "media",
        "settings": settings(*(permanent(identity) for identity in IDS), revision=revision),
        "expected_revision": revision})
    assert enabled["media_all_supported"] and subject.freeze_event_settings(tmp_path, media_mode=True) == enabled["saved"]
    revision = enabled["saved"]["revision"]
    disabled = subject.event_settings_command(tmp_path, "events_save", {"mode": "media",
        "settings": settings(revision=revision), "expected_revision": revision})
    assert disabled["saved"]["love_events"] == [] and not disabled["media_default_all"]
    assert subject.freeze_event_settings(tmp_path, media_mode=True)["love_events"] == []
    assert subject.freeze_event_settings(tmp_path) == normal_saved
    assert (tmp_path / subject.FILENAME).read_bytes() == normal_before
    assert all((tmp_path / name).read_bytes() == b"OPAQUE-ACCOUNT-PROGRESS-AND-SESSIONS"
               for name in ("state.db", "media-state.db"))


@pytest.mark.parametrize("media_mode,row", [(False, permanent()), (True, entry()),
    (True, {**permanent(), "end_time_ms": 1}), (True, {**permanent(), "start_time_ms": True})])
def test_media_permanent_and_normal_finite_period_shapes_cannot_be_mixed(tmp_path, media_mode, row):
    state = subject.EventSettingsState(tmp_path, catalog=catalog(), media_mode=media_mode)
    with pytest.raises(subject.EventSettingsError, match="event_settings_invalid"):
        state.save(settings(row), expected_revision=0)
    assert not (tmp_path / subject.FILENAME).exists() and not (tmp_path / subject.MEDIA_FILENAME).exists()


@pytest.mark.parametrize("mode", [True, None, 1, "gallery", "", [], {}])
def test_command_mode_is_a_finite_string_and_never_changes_either_file(tmp_path, mode):
    with pytest.raises(subject.EventSettingsError, match="event_settings_command_invalid"):
        subject.event_settings_command(tmp_path, "events_status", {"mode": mode})
    assert not tmp_path.joinpath(subject.FILENAME).exists() and not tmp_path.joinpath(subject.MEDIA_FILENAME).exists()


def test_media_catalog_unavailable_keeps_disabled_lazy_default_and_corrupt_choices_fail_closed(tmp_path, producer):
    producer.update(catalog(available=False))
    assert subject.freeze_event_settings(tmp_path, media_mode=True) == settings()
    assert not (tmp_path / subject.MEDIA_FILENAME).exists()
    path = tmp_path / subject.MEDIA_FILENAME
    path.write_text('{"schema":1,"revision":0,"love_events":[{"event_id":"bad","start_time_ms":1,"end_time_ms":2}]}')
    before = path.read_bytes()
    with pytest.raises(subject.EventSettingsError): subject.freeze_event_settings(tmp_path, media_mode=True)
    assert path.read_bytes() == before


def test_event_catalog_adds_three_bounded_ui_labels_without_replacing_original_titles(tmp_path, producer):
    observed = subject.event_settings_status(tmp_path)
    for row in observed["catalog"]["events"]:
        assert set(row["titles"]) == {"ko", "ja", "en"}
        assert row["titles"]["ja"] == row["title"]
        assert not any(character in row["titles"]["ko"] for character in "もし恋君編")
        assert all(type(value) is str and value.isprintable() and 0 < len(value.encode("utf-8")) <= 1024
                   for value in row["titles"].values())
    assert observed["catalog"]["events"][0]["titles"]["ko"] != observed["catalog"]["events"][0]["title"]


def test_extra_event_label_keeps_the_recognizable_title(tmp_path, producer):
    original = "サキュ×まほ ~KISS AND MAGIC!~"
    producer["events"][1]["title"] = original
    extra = next(row for row in subject.event_settings_status(tmp_path)["catalog"]["events"]
                 if row["id"] == "love-extra-25-0426")
    assert extra["title"] == original and extra["titles"]["ja"] == original
    assert extra["titles"]["ko"] == "사큐×마호 ~KISS AND MAGIC!~"
    assert "KISS AND MAGIC!" in extra["titles"]["en"]


@pytest.mark.parametrize("media_mode,no_op", [(False, False), (True, False), (True, True)])
def test_successful_acknowledgement_keeps_own_snapshot_if_another_writer_commits_before_status(
        tmp_path, producer, monkeypatch, media_mode, no_op):
    original_status = subject.EventSettingsState.status
    observed = {}
    mode = "media" if media_mode else "normal"
    rows = [permanent(identity) if media_mode else entry(identity) for identity in IDS]
    ours = settings(*rows) if no_op else settings(rows[0])
    def interleaved_status(state, **options):
        committed = options.get("_saved")
        if committed is not None:
            observed["ours"] = deepcopy(committed)
            writer = subject.EventSettingsState(tmp_path, catalog=producer, media_mode=media_mode)
            external_rows = [rows[1]] if no_op else rows
            external = settings(*external_rows, revision=committed["revision"])
            observed["newer"] = writer.save(external, expected_revision=committed["revision"])
        return original_status(state, **options)
    monkeypatch.setattr(subject.EventSettingsState, "status", interleaved_status)
    response = subject.event_settings_command(tmp_path, "events_save", {
        "mode": mode, "settings": ours, "expected_revision": 0})
    assert response["saved"] == observed["ours"]
    assert response["saved"]["love_events"] == ours["love_events"]
    assert response["media_default_all"] is (media_mode and no_op)
    assert response["media_all_supported"] is (media_mode and no_op)
    assert observed["newer"]["revision"] > response["saved"]["revision"]
    stored = subject.EventSettingsState(tmp_path, catalog=producer, media_mode=media_mode).settings()
    assert stored == observed["newer"] and stored != response["saved"]
