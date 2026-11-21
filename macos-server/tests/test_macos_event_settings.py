"""Mac native-only compact transport; common settings always use object rows."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine
from idoly_local import event_settings

IDS=("love-23-0514","love-23-1114","love-24-0517","love-24-1114","love-26-0313","love-extra-25-0426")


def wire(rows=None,revision=0):
    rows=rows if rows is not None else [[identity,1700000000000,1702592000000] for identity in IDS]
    return {"action":"events_save","request_id":2**31-1,"settings":{"schema":1,"revision":revision,
        "love_events":rows},"expected_revision":revision}


def wait_for_worker(value):
    end=time.monotonic()+4
    while value.events_worker is not None:
        assert time.monotonic()<end,"Mac event settings worker did not finish"
        time.sleep(.01)


@pytest.fixture
def controller(tmp_path,monkeypatch):
    rows=[{"id":identity,"title":identity,"supported":True,
        "source_grade":"original_master_and_reference_capture_claim","inference_status":"reference_routes_inferred",
        "original_start_time_ms":1700000000000,"original_end_time_ms":None,"original_duration_ms":None} for identity in IDS]
    catalog={"schema":1,"available":True,"ruleset_sha256":"a"*64,"events":rows}
    monkeypatch.setitem(sys.modules,"idoly_local.love_catalog",SimpleNamespace(event_catalog=lambda root:deepcopy(catalog)))
    events=[]
    value=engine.Controller(tmp_path,tmp_path/"ServerData.zip",emit_event=lambda name,**data:events.append((name,data)))
    return value,events,tmp_path


@pytest.mark.parametrize("media_mode",[False,True])
def test_six_events_fit_atomic_wire_expand_exactly_and_only_save_next_settings(controller,media_mode):
    value,events,root=controller
    command=wire()
    assert len(json.dumps(command,separators=(",",":"),ensure_ascii=True).encode())+1<=512
    active={"schema":1,"revision":0,"love_events":[]}
    def forbidden():raise AssertionError("Event autosave must never stop or reset the runtime")
    runtime=SimpleNamespace(status=lambda:{"running":True,"profile":"sandbox","media_mode":media_mode,
        "event_settings":{"effective":deepcopy(active)}},stop=forbidden)
    value.runtime=runtime
    value.events("events_save",command);wait_for_worker(value)
    result=next(data["result"] for name,data in events if name=="events_result")
    assert result["effective"]==active and result["restart_required"] is True
    assert value.runtime is runtime and result["saved"]["revision"]>0
    expected=[{"event_id":identity,"start_time_ms":1700000000000,"end_time_ms":1702592000000} for identity in sorted(IDS)]
    assert result["saved"]["love_events"]==expected
    disk=json.loads((root/event_settings.FILENAME).read_text())
    assert disk==result["saved"] and all(type(row) is dict for row in disk["love_events"])
    assert not (root/"state.db").exists() and not (root/"media-state.db").exists()


def test_six_max_safe_time_rows_still_fit_and_expand_without_float_or_bool_conversion():
    end=2**53-1;rows=[[identity,end-86400000,end] for identity in IDS]
    command=wire(rows,revision=2**53-1)
    assert len(json.dumps(command,separators=(",",":"),ensure_ascii=True).encode())+1<=512
    payload={key:value for key,value in command.items() if key not in ("action","request_id")}
    expanded=engine._event_payload("events_save",payload)
    assert [row["event_id"] for row in expanded["settings"]["love_events"]]==list(IDS)
    assert all(type(row["start_time_ms"]) is int and row["end_time_ms"]==end for row in expanded["settings"]["love_events"])


@pytest.mark.parametrize("rows",[[[IDS[0],1]],[[IDS[0],1,2,3]],[[IDS[0],True,2]],[[IDS[0],1.5,2]],
    [[IDS[0],"1",2]],[[IDS[0],1,2],[IDS[0],2,3]],[{"event_id":IDS[0],"start_time_ms":1,"end_time_ms":2}],
    [["../PRIVATE-WIRE",1,2]]])
def test_bad_compact_shapes_are_rejected_before_common_command(controller,rows):
    value,events,root=controller
    value.events("events_save",wire(rows));wait_for_worker(value)
    assert events[-1]==("events_error",{"request_id":2**31-1,"action":"events_save","code":"event_settings_command_invalid"})
    assert not (root/event_settings.FILENAME).exists() and "PRIVATE-WIRE" not in json.dumps(events)


def test_oversize_command_is_rejected_without_starting_a_writer(controller):
    value,events,root=controller
    command=wire([["love-"+str(index),1,2] for index in range(64)])
    assert len(json.dumps(command,separators=(",",":")).encode())+1>512
    value.events("events_save",command)
    assert value.events_worker is None
    assert events[-1][1]["code"]=="event_settings_command_invalid"
    assert not (root/event_settings.FILENAME).exists()


def test_compact_still_uses_common_period_and_revision_guards(controller):
    value,events,root=controller
    value.events("events_save",wire([[IDS[0],1,1]]));wait_for_worker(value)
    assert any(name=="events_error" and data["code"]=="event_settings_invalid" for name,data in events)
    events.clear();value.events("events_save",wire());wait_for_worker(value)
    assert any(name=="events_result" for name,data in events)
    before=(root/event_settings.FILENAME).read_bytes();events.clear()
    value.events("events_save",wire([]));wait_for_worker(value)
    assert any(name=="events_error" and data["code"]=="event_settings_revision_conflict" for name,data in events)
    assert (root/event_settings.FILENAME).read_bytes()==before


def test_swift_preserves_atomic_writer_limit_and_supports_both_modes_with_local_periods():
    source=(Path(__file__).resolve().parents[1]/"App.swift").read_text()
    sender=source.split('    private func sendEvent(',1)[1].split('    private func consumeEvents(',1)[0]
    assert 'compact.append([id, start, end])' in sender and 'settings["love_events"] = compact' in sender
    assert sender.index('guard bytes.count <= 512')<sender.index('Self.nonblockingWrite(bytes')
    view=source.split('struct LocalLoveEventControls: View',1)[1].split('struct OfficialImportControls: View',1)[0]
    assert 'model.mediaMode' not in view and 'Local start' in view and 'Local end' in view
    assert '366 days' in view and 'not verified official dates' in view
    assert 'model.eventEnabledBinding(row.id)' in view and 'model.refreshEvents()' in view
    assert 'identifier == pendingOfficialID' in source  # Existing official correlation stays intact.
