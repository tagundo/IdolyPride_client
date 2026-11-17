"""Portable controller/protocol tests, explicitly not simulator execution proof."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import plistlib
from unittest import mock
from zipfile import ZipFile

from google.protobuf import descriptor_pb2
import pytest

from idoly_local import codec
from idoly_local.h2_server import create_server
from idoly_local.octo_manifest import Database
from idoly_local.octo_runtime import _desktop_aes_backend
from idoly_local.rpc import RpcCode


SOURCE = Path(__file__).resolve().parents[1] / "ios-unified/probe/smoke_probe.py"
spec = importlib.util.spec_from_file_location("ios_unified_smoke_probe", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


REAL_ACCOUNT_FIXTURE_HARNESS = probe.AccountFixtureHarness


def modeled_account_management(run_index=0):
    if run_index != 0:
        return {"performed": False, "reason": "first-cold-run-only"}
    source_rows = {table: 1 for table in probe.ACCOUNT_TABLES}
    target_rows = {**source_rows, "preference_receipts": 2, "main_live_attempts": 2}
    def fixture(phase, rows, digest, revision, request):
        return {"schema":1,"ready":True,"phase":phase,"request_sha256":request*64,
            "bundle_revision":revision*64,"normalized_sha256":digest*64,
            "table_rows":rows,"unknown_tables":list(probe.ACCOUNT_BLOB_TABLES)}
    return {"performed":True,"scope":"stock-simulator","ui_trigger":"dom-click",
        "selection_trigger":"delegate-callback","seed_fixture_used":True,"gameplay_tested":False,
        "timed_out":False,"completed":True,"elapsed_seconds":10.0,
        **{key:True for key in probe.ACCOUNT_NATIVE_FLAGS},
        "ui_flags":{key:True for key in probe.ACCOUNT_UI_FLAGS},"ui_actions":list(probe.ACCOUNT_UI_ACTIONS),
        "archive_bytes":4096,"archive_sha256":"9"*64,"preview_picker_count":2,
        "preview_copies":[{"queued":True,"copied_bytes":4096,"total_bytes":4096} for _ in range(2)],
        "fixture_source":fixture("source",source_rows,"a","c","e"),
        "fixture_target":fixture("target",target_rows,"b","d","f"),
        "state_observation":{"observer":"runner-sqlite-and-archive","seed_fixture_used":True,
            "gameplay_tested":False,"checks":{key:True for key in probe.ACCOUNT_STATE_FLAGS},
            "table_rows":target_rows,"normalized_source_sha256":"a"*64,
            "normalized_restored_sha256":"b"*64,"archive_sha256":"9"*64,"archive_bytes":4096}}


def modeled_ui_test_proof(udid=None):
    pins=probe.official_ui_source_pins()
    return {"schema":1,"status":"PASS","execution":"public_xctest","simulator_udid":udid or CREATED,
        "test_identifier":probe.UI_TEST_IDENTIFIER,"tests":1,"failures":0,"skipped":0,
        "actual_cancel_tap":True,"ready_marker_observed":True,"source_pins":pins,
        "source_sha256":hashlib.sha256(json.dumps(pins,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
        "xctestrun_sha256":"a"*64,"xcresult_summary_sha256":"b"*64,"xcresult_tests_sha256":"c"*64}


class ModeledUIDriver:
    def __init__(self,simulator_udid,*,remaining):
        self.udid=simulator_udid;self.remaining=remaining;self.started=False;self.closed=False
    def start(self):
        assert not self.started;self.started=True
    def poll(self):
        assert self.started and not self.closed
        return {"phase":"running","ready":True}
    def finish(self):
        assert self.started and not self.closed
        return modeled_ui_test_proof(self.udid)
    def close(self):self.closed=True


@pytest.fixture(autouse=True)
def modeled_account_observer_for_mock_simulator_transport(monkeypatch):
    # FakeSimctl writes modeled reports; it never runs UIKit or the real fixture.
    # Real producer/SQLite/ZIP tests below retain the original class explicitly.
    class ModeledFixture:
        def __init__(self, *args, **kwargs): pass
        def process(self): pass
        def verify(self, native):
            return native.get("state_observation", modeled_account_management()["state_observation"])
        def verify_persisted(self):
            return {"schema":1,"observer":"runner-sqlite-after-five-cold-runs","seed_fixture_used":True,
                "gameplay_tested":False,"checks":{key:True for key in (
                    "source_all_tables_persisted","restored_all_tables_persisted","source_session_preserved",
                    "target_session_invalidated","original_selection_preserved","love_progress_bytes_persisted")},
                "normalized_source_sha256":"a"*64,"normalized_restored_sha256":"b"*64}
    monkeypatch.setattr(probe, "AccountFixtureHarness", ModeledFixture)
    monkeypatch.setattr(probe, "ProbePromptCancelDriver", ModeledUIDriver)


CREATED = "00000000-0000-4000-8000-000000000123"
DEVICE = "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"
RUNTIME = "com.apple.CoreSimulator.SimRuntime.iOS-18-5"
MASTER_BYTES = bytes(range(128))
MASTER_MEMBER = "data/original-master/assets/master/fixture.db"
SDK_SETTINGS_MEMBER = "data/public-octo-ios/settings.json"
SDK_MANIFEST_MEMBER = "data/public-octo-ios/manifest.pb"
SDK_PATH = "/v2/pub/a/212/v/105051/list/0"
SDK_KEY = hashlib.sha256(b"portable-public-sdk-fixture").digest()
SDK_OBJECT = b"public translated SDK image fixture"
SDK_OBJECT_PATH = "/octo/101050/assetbundle/Ab12Z9/12346"


def sdk_fixture():
    original = Database(revision=1159,urlFormat="https://original.invalid/{v}/{type}/{o}/{g}")
    original.assetBundleList.add(id=1,name="public-ui-image",size=12,state=1,
        md5=hashlib.md5(b"original-img").hexdigest(),objectName="Or1gA1",generation=12345,uploadVersionId=101050)
    original.resourceList.add(id=1,name="public-resource",size=8,state=1,
        md5=hashlib.md5(b"resource").hexdigest(),objectName="Res001",generation=12345,uploadVersionId=101050)
    raw = original.SerializeToString()
    settings = {"schema":1,"application_id":212,"application_version":105051,"revision":1159,
        "manifest_sha256":hashlib.sha256(raw).hexdigest(),"aes_key_hex":SDK_KEY.hex(),
        "client_key":"public-sdk-fixture-key"}
    wire = Database.FromString(raw)
    wire.revision = 1160
    wire.urlFormat = "http://127.0.0.1:8080/octo/{v}/{type}/{o}/{g}"
    wire.assetBundleList[0].objectName = "Ab12Z9"
    wire.assetBundleList[0].generation = 12346
    wire.assetBundleList[0].md5 = hashlib.md5(SDK_OBJECT).hexdigest()
    wire.assetBundleList[0].size = len(SDK_OBJECT)
    return settings,raw,wire


def encrypted_sdk_manifest(database):
    plain = database.SerializeToString()
    padding = 16-len(plain)%16
    iv = bytes(range(16))
    return iv+_desktop_aes_backend()(True,SDK_KEY,iv,plain+bytes([padding])*padding)


def sdk_resource_report():
    settings,_,wire = sdk_fixture()
    digest = hashlib.md5(SDK_OBJECT).hexdigest()
    return {"schema":1,"transport":"http.client","origin":"http://127.0.0.1:8080",
        "application_id":212,"application_version":105051,"manifest_path":SDK_PATH,
        "manifest_http_status":200,"manifest_encrypted":True,"manifest_decrypted":True,
        "manifest_ciphertext_bytes":len(encrypted_sdk_manifest(wire)),
        "manifest_plaintext_bytes":len(wire.SerializeToString()),
        "original_manifest_sha256":settings["manifest_sha256"],"manifest_rows":2,"active_rows":2,
        "wire_rowset_matches_original":True,"all_active_object_names_six_base62":True,
        "translated_image_count":1,"selection":"smallest-translated-image","selected_kind":"assetbundle",
        "object_path_sha256":hashlib.sha256(SDK_OBJECT_PATH.encode()).hexdigest(),
        "object_http_status":200,"object_mime":"application/octet-stream",
        "object_bytes":len(SDK_OBJECT),"received_bytes":len(SDK_OBJECT),
        "expected_md5":digest,"received_md5":digest,"etag_matches_md5":True,
        "original_revision":1159,"manifest_revision":1160}


def master_file_report():
    digest = hashlib.sha256(MASTER_BYTES[:64]).hexdigest()
    return {"schema":1,"transport":"http.client","origin":"http://127.0.0.1:8080",
            "expected_source":"bundled-master-prefix","path_sha256":hashlib.sha256(b"/master/fixture.db").hexdigest(),
            "file_bytes":128,"head_status":200,"head_content_length":128,
            "range_status":206,"range_content_length":64,"sample_bytes":64,
            "content_range":"bytes 0-63/128","expected_sample_sha256":digest,
            "received_sample_sha256":digest,"sample_matches_bundle":True,
            "auth_rpc":{"path":"/api.Auth/Login","grpc_status":0,
                "request_encrypted":True,"response_encrypted":True},
            "master_rpc":{"path":"/api.Master/Get","grpc_status":0,
                "request_encrypted":True,"response_encrypted":True}}


def language_canaries():
    return {"schema":1,"bundle_id":"local.idoly.client-data",
        "client_archive_sha256":hashlib.sha256(b"public-fixture-archive").hexdigest(),
        "client_manifest_sha256":hashlib.sha256(b"public-fixture-manifest").hexdigest(),
        "descriptor_sha256":hashlib.sha256(public_descriptor()).hexdigest(),
        "languages":{language:{path:{"bytes":len((language+path).encode()),
            "sha256":hashlib.sha256((language+path).encode()).hexdigest()}
            for path in ("Data/resources.assets","Data/Managed/Metadata/global-metadata.dat")}
            for language in ("ko","en","ja")}}


def language_canary_bytes():
    return json.dumps(language_canaries(),sort_keys=True,separators=(",",":")).encode()+b"\n"


def native_report(language="ko", run_index=None):
    if run_index is None: run_index = ("ko","en","ja","en","ko").index(language)
    assert ("ko","en","ja","en","ko")[run_index] == language
    report = {"schema": 1, "original_called": 1, "main_thread": True,
            "application_argument_matches": True, "command_completion_main_thread": True,
            "crypto_completion_main_thread": True,
            "native_crypto": {"ok": True, "nist_encrypt": True, "nist_decrypt": True,
                              "invalid_iv_rejected": True, "worker_main_thread": False},
            "server_status": {"schema": 1, "hook_installed": True, "phase": 4,
                              "captured": 1, "forwarded": 1, "attempts": 1,
                              "python_initialized": True, "error": None,
                              "keyboard_ready": True,
                              "keyboard_lifecycle":{"installed":True,"strategy":"reuse-existing",
                                  "initialize_calls":1,"original_initialize_calls":0,"reused_existing_calls":1},
                              "http_readiness":{"schema":1,"ok":True,"transport":"NSURLSession",
                                  "url":"http://127.0.0.1:8080/client/playback","http_status":200,
                                  "error_code":"none","body_is_json":True,"received_bytes":128,
                                  "worker_main_thread":False,"ns_error_domain":None,"ns_error_code":None},
                              "launch_requested": True, "launch_prepared": True, "launcher_visible": False,
                              "client_data": {"selected": True, "language": "ko", "bundle_identifier": "local.idoly.client-data"}},
            "launcher": {"premature_phase": 1, "premature_original_called": 0,
                "premature_launch_requested": False, "ready_phase": 2, "ready_captured":1, "ready_original_called": 0,
                "ready_launch_requested": False, "ready_launch_prepared": False,
                "ready_observations": 5, "ready_wait_seconds": 5.25,
                "ready_launcher_visible": True, "ready_button_found": True,
                "ready_button_enabled": True, "ready_button_title": "게임 시작",
                "ready_button_kind":"UIButton","button_control_event":"touch-up-inside",
                "button_action_dispatched": True, "button_dispatch_count": 1,
                "duplicate_launch_called": True, "forwarded_after_button": True,
                **{key:True for key in probe.LAUNCH_SETTINGS_FLAGS}},
            "corner_gesture": {"game_window_key": True, "matching_count": 1,
                "recognizer_name": "idoly.server-menu-corner", "one_finger_count": 1, "three_finger_count": 0,
                "minimum_press_seconds": 2.0, "allowable_movement_points": 12.0, "delegate_present": True,
                "delays_touches_began": False, "delays_touches_ended": False, "cancels_touches_in_view": True},
            "ports": {"grpc": 50051, "assets": 8080,
                      "grpc_connect": True, "assets_connect": True},
            "commoncrypto": {"nist_aes128_cbc": True, "nist_aes256_cbc": True},
            "host_status": {"id": 1, "ok": True, "result": {"state": "ready", "running": True,
                "last_error": None, "runtime": {"running": True, "grpc_address": "127.0.0.1:50051",
                                                "asset_url": "http://127.0.0.1:8080"}}}}
    report["server_status"]["octo_budget"] = {"schema":1,"status":"configured","prepared":True,
        "configured":True,"original_seconds":10,"effective_seconds":330,"cache_wait_seconds":300,
        "scope":"unified-loopback","error":None}
    report["octo_budget_probe"] = {"apis_registered":True,"prepared_without_managed_callbacks":True,
        "during_original_seconds":10,"during_original_configured":False,"first_queued_seconds":330,
        "configured_before_first_queued_work":True,"queued_work_on_main_thread":True,
        "class_initialized":True,"initializations":1,"reads":2,"writes":1,
        "last_snapshot":330,"first_queued_snapshot_count":1,"writes_before_initialization":0}
    report["keyboard"] = {
        "before_capture":{"ready":False,"phase":2,"returned_nil":False,
                          "returned_initialized_field":True,"returned_same_field":True,
                          "original_calls":1,"field_creation_count":1,
                          "lifecycle":{"installed":False,"strategy":"reuse-existing","initialize_calls":0,
                              "original_initialize_calls":0,"reused_existing_calls":0}},
        "before_launch":{"ready":False,"phase":2,"returned_nil":False,
                         "returned_initialized_field":True,"returned_same_field":True,
                         "original_calls":2,"field_creation_count":1,
                         "lifecycle":{"installed":False,"strategy":"reuse-existing","initialize_calls":0,
                             "original_initialize_calls":0,"reused_existing_calls":0}},
        "during_init":{"ready":False,"phase":4,"returned_nil":False,
                       "returned_initialized_field":True,"returned_same_field":True,
                       "original_calls":3,"field_creation_count":1,
                       "lifecycle":{"installed":True,"strategy":"reuse-existing","initialize_calls":1,
                           "original_initialize_calls":0,"reused_existing_calls":1}},
        "after_init":{"ready":True,"phase":4,"returned_nil":False,
                      "returned_initialized_field":True,"returned_same_field":True,
                      "original_calls":4,"field_creation_count":1,
                      "lifecycle":{"installed":True,"strategy":"reuse-existing","initialize_calls":1,
                          "original_initialize_calls":0,"reused_existing_calls":1}},
    }
    report["early_status"] = {"id":2718,"ok":True,"state":"starting","running":False,
                              "phase":1,"captured":1,"completion_main_thread":True}
    report["launcher"].update(startup_evidence_version=2,premature_captured=1,server_ready_before_runtime=True,
        cold_original_called=0,cold_attempts=1,host_capture_once=True)
    def header_sample(width, height, fonts):
        return {"header_found":True,"actions_found":True,"title_found":True,"status_found":True,
                "hint_found":True,"nav_bar_hidden":True,"header_inside":True,"controls_inside":True,
                "row_no_overlap":True,"button_titles_fit":True,"button_count":2,
                "root_width":width,"root_height":height,"header_width":width,"header_height":160,
                "actions_width":width-32,"min_button_height":48,"button_min_font":fonts[0],
                "title_font":fonts[1],"status_font":fonts[2],"hint_font":fonts[3]}
    current = header_sample(393,852,(18,24,18,13))
    report["native_header"] = {"restore_succeeded":True,"owned_root_only":True,"current":current,
        "wide":header_sample(1920,1080,(26,34,26,19)),
        "ultrawide":header_sample(3840,2160,(52,68,52,38)),"restored":dict(current)}
    report["menu_lifetime"] = {"opened_via_owned_menu_target":True,"full_screen":True,
        "frame_width_matches":True,"frame_width":393.0,"window_width":393.0,"return_button_found":True,
        "server_control_found":True,"server_control_disabled_while_running":True,
        "return_button_kind":"UIButton","server_button_kind":"UIButton","return_control_event":"touch-up-inside",
        "diagnostics_copy":{"button_found":True,"enabled_before":True,"click_dispatched":True,
            "completed":True,"feedback_success":True,"pasteboard_matches":True,"clipboard_seeded":True,
            "clipboard_cleared":True,"timed_out":False,"text_bytes":1024},
        "zip_import_picker":{"scope":"stock-simulator","cancel_trigger":"delegate-callback",
            "timed_out":False,"observations":8,"elapsed_seconds":0.8,
            "grpc_connected_after_cancel":True,"assets_connected_after_cancel":True,
            "passes":[{**{key:True for key in probe.ZIP_IMPORT_PASS_BOOL_FIELDS},"document_picker_mode":0}
                      for _ in range(2)]},
        "zip_roundtrip":({"performed":True,"scope":"stock-simulator","selection_trigger":"delegate-callback",
            "timed_out":False,"elapsed_seconds":4.0,**{key:True for key in probe.ZIP_ROUNDTRIP_FLAGS},
            "source_bytes":4096,"copied_bytes":4096,"total_bytes":4096,"exported_files":0,"imported_files":0,
            "failed_files":0,"source_sha256":"a"*64,"copied_sha256":"a"*64}
            if run_index == 0 else {"performed":False,"reason":"first-cold-run-only"}),
        "account_management":modeled_account_management(run_index),
        "official_prompt":({"performed":True,"scope":"stock-simulator","ui_trigger":"dom-click",
            "cancel_trigger":"public-xctest-tap","timed_out":False,"credential_submission_performed":False,
            "elapsed_seconds":0.9,**{key:True for key in probe.OFFICIAL_PROMPT_FLAGS},"ui_test":modeled_ui_test_proof()}
            if run_index==0 else {"performed":False,"reason":"first-cold-run-only"}),
        "return_action_dispatched":True,"dismissed":True,"menu_view_detached_after_close":True,"game_window_key_after_close":True,
        "dismiss_observation":{"presented_controller_remaining":False,"settings_controller_still_presented":False,
            "settings_view_attached":False,"settings_is_being_dismissed":False,"game_window_key":True,
            "application_state":0,"observations":4,"wait_seconds":0.303,"timed_out":False},
        "status_completion_main_thread":True,"grpc_connected_after_close":True,"assets_connected_after_close":True,
        "web":{"web_found":True,"evaluation_succeeded":True,"ready":True,"forms_present":True,
               "scale_2_present":True,"buffer_4096_present":True,"no_horizontal_overflow":True,
               "timed_out":False,"viewport_width":393,"content_width":393,"select_count":14,
               "navigation_loading":False,"navigation_file_url":True,"web_attached":True,"navigation_progress":1,
               "evaluation_started":True,"evaluation_completed":True,"data_store_reused":True,
               "launcher_store_nonpersistent":True,"menu_store_nonpersistent":True,"web_view_recreated":True,
               "launcher_document_marker_absent":True},
        "host_status_after_close":{"id":2,"ok":True,"result":{"state":"ready","running":True,
               "last_error":None,"runtime":{"running":True,"grpc_address":"127.0.0.1:50051",
                                              "asset_url":"http://127.0.0.1:8080"}}}}
    report["server_status"]["client_data"]["language"] = language
    report["server_status"]["unity_host"] = {"schema":1,"strategy":"unity-as-library",
        "installed":True,"entry_captured":True,"host_ready":True,"started":True,"unity_window_bound":True,
        "launching":False,"failed":False,"application_main_calls":1,"runtime_start_calls":1,"warmup_calls":1,
        "bundle_match_before":True,"bundle_match_after":True,"first_warmup_bundle_match":True,
        "sigpipe_ignored_before_server":True,
        "consumed_bundle_language":language,"queued_events":0,"delivered_events":0,"lifecycle_forwarded":0,"error":None}
    report["unity_host_probe"] = {"schema":1,"expected_language":language,"run_index":run_index,
        "prelaunch_server_healthy":True,"prelaunch_runtime_cold":True,
        "cache_return":run_index >= 3,"cache_identity_recorded":True,
        "cache_files_same_identity":True if run_index >= 3 else None,
        "sigpipe":{phase:{"schema":1,"sigaction_read":True,"sigpipe_ignored":True,"socketpair_created":True,
            "peer_closed":True,"write_epipe":True,"process_survived":True,"main_thread":phase == "before_server"}
            for phase in ("before_server","before_game_worker")},
        "constructor_installed_before_c_main":True,"host_hooks_registered":True,"application_main_adapter_calls":1,
        "host_delegate_owned":True,"original_run_main_calls":0,"cold_before_game_start":True,
        "runtime_count_before_game_start":0,"warmup_count_before_game_start":0,
        "consumed_bundle_language":language,"canary_source_sha256":hashlib.sha256(language_canary_bytes()).hexdigest(),
        "canaries_match":True,"game_window_distinct":True,"game_window_key":True,
        "host_delegate_window_is_game":True,"placeholder_hidden":True,
        "canaries":{path:{"expected_sha256":row["sha256"],"actual_sha256":row["sha256"],
            "expected_bytes":row["bytes"],"actual_bytes":row["bytes"]}
            for path,row in language_canaries()["languages"][language].items()}}
    report["interface_language_cycle"] = [{"language":item,"ack_id":index+100,
        "acknowledged":True,"dom_language_matches":True,"native_title_matches":True,
        "native_game_button_matches":True,"native_status_label_matches":True,"native_server_button_matches":True,
        "game_select_unchanged":True,"persisted_game_language_unchanged":True}
        for index,item in enumerate(("ja","en","ko"))]
    next_language = ("en","ja","en","ko","ko")[run_index]
    report["language_save"] = {"current_language":language,"next_language":next_language,"ack_id":200,
        "save_trigger":"change-autosave",
        "acknowledged":True,"persisted_language":next_language,"effective_language":language,
        "options_fields_reenabled":True,"message_success":True,"form_feedback_saved":True,
        "request_id":200,"request_action":"save_options","request_language":next_language,
        "request_observed":True,"ack_correlated":True,"feedback_source":"options-save-feedback","feedback_state":"saved",
        "ack_language":next_language,"ack_effective_language":language,"server_status_received":True,
        "server_language_matches":True,"server_effective_matches":True,"timed_out":False}
    return report


@pytest.mark.parametrize("language", ("ko","en","ja"))
def test_unity_library_host_consumes_selected_language_before_first_warmup(language):
    native = native_report(language)
    summary = probe.validate_language_relaunch_report(native,language)
    assert summary["language"] == language
    assert summary["unity_host"]["runtime_start_calls"] == 1
    assert summary["unity_host_probe"]["warmup_count_before_game_start"] == 0
    assert summary["unity_host_probe"]["original_run_main_calls"] == 0
    assert summary["language_save"]["effective_language"] == language
    assert summary["language_save"]["persisted_language"] == {"ko":"en","en":"ja","ja":"en"}[language]
    with pytest.raises(probe.ProbeError):
        probe.validate_language_relaunch_report(native,"en" if language == "ko" else "ko")


@pytest.mark.parametrize("key,value", (("installed",False),("entry_captured",1),("host_ready",False),
    ("started",False),("unity_window_bound",False),("launching",True),("failed",True),
    ("application_main_calls",True),("runtime_start_calls",2),("warmup_calls",0),
    ("bundle_match_before",False),("bundle_match_after",False),("first_warmup_bundle_match",False),
    ("consumed_bundle_language","en"),("queued_events",33),("delivered_events",True),
    ("lifecycle_forwarded",-1),("sigpipe_ignored_before_server",False),("error","must-not-export")))
def test_unity_host_requires_exact_once_entry_runtime_warmup_and_game_window(key, value):
    native = native_report()
    native["server_status"]["unity_host"][key] = value
    with pytest.raises(probe.ProbeError,match="unity_host_failed"):
        probe.validate_report(native)


@pytest.mark.parametrize("key,value", (("schema",True),("constructor_installed_before_c_main",False),
    ("host_hooks_registered",False),("application_main_adapter_calls",0),("host_delegate_owned",False),
    ("original_run_main_calls",1),("cold_before_game_start",False),("runtime_count_before_game_start",1),
    ("warmup_count_before_game_start",True),("consumed_bundle_language","en"),
    ("canary_source_sha256","not-a-sha"),("canaries_match",False),("game_window_distinct",False),
    ("game_window_key",False),("host_delegate_window_is_game",False),("placeholder_hidden",False),
    ("prelaunch_server_healthy",False),("prelaunch_runtime_cold",False)))
def test_unity_host_probe_rejects_late_selection_or_placeholder_runtime(key, value):
    native = native_report()
    native["unity_host_probe"][key] = value
    with pytest.raises(probe.ProbeError,match="unity_host_probe_failed"):
        probe.validate_report(native)


@pytest.mark.parametrize("key,value", (("actual_sha256","0"*64),("expected_sha256","Z"*64),
    ("actual_bytes",0),("actual_bytes",True),("expected_bytes",128*1024*1024+1)))
def test_first_warmup_canary_requires_actual_exact_selected_resource_bytes(key, value):
    native = native_report()
    native["unity_host_probe"]["canaries"]["Data/resources.assets"][key] = value
    with pytest.raises(probe.ProbeError,match="unity_host_probe_failed"):
        probe.validate_report(native)


@pytest.mark.parametrize("key,value", (("language","ko"),("ack_id",True),("ack_id",0),
    ("acknowledged",False),("dom_language_matches",False),("native_title_matches",False),
    ("native_game_button_matches",1),("native_status_label_matches",False),("native_server_button_matches",1),
    ("game_select_unchanged",False),
    ("persisted_game_language_unchanged",False)))
def test_interface_cycle_requires_real_ack_chrome_and_unchanged_game_language(key, value):
    native = native_report()
    native["interface_language_cycle"][0][key] = value
    with pytest.raises(probe.ProbeError,match="language_interface_cycle_failed"):
        probe.validate_report(native)


@pytest.mark.parametrize("key,value", (("current_language","en"),("next_language","ja"),
    ("persisted_language","ko"),("effective_language","en"),("ack_id",False),
    ("acknowledged",False),("options_fields_reenabled",False),("message_success",False)))
def test_game_language_save_requires_persisted_next_but_unchanged_effective_language(key, value):
    native = native_report()
    native["language_save"][key] = value
    with pytest.raises(probe.ProbeError,match="language_save_failed"):
        probe.validate_report(native)


def test_unity_host_error_key_and_canary_path_set_are_explicit_and_closed():
    native = native_report()
    del native["server_status"]["unity_host"]["error"]
    with pytest.raises(probe.ProbeError,match="unity_host_failed"):
        probe.validate_report(native)
    native = native_report()
    native["unity_host_probe"]["canaries"]["private/path"] = {"secret":"must-not-export"}
    with pytest.raises(probe.ProbeError,match="unity_host_probe_failed"):
        probe.validate_report(native)


def test_language_matrix_requires_five_ordered_cold_processes_including_en_and_ko_returns():
    matrix = {"schema":2,"order":["ko","en","ja","en","ko"],"preserved_app_container":True,
        "reports":[probe.validate_language_relaunch_report(native_report(language,index),language,run_index=index)
                   for index,language in enumerate(("ko","en","ja","en","ko"))]}
    checked = probe.validate_language_matrix_report(matrix)
    assert [row["run_index"] for row in checked["reports"]] == [0,1,2,3,4]
    assert [row["language"] for row in checked["reports"]] == ["ko","en","ja","en","ko"]
    for mutation in ("missing_return","wrong_order","reused_ko","reused_first_en","container_reset","old_schema"):
        bad = json.loads(json.dumps(matrix))
        if mutation == "missing_return": bad["reports"].pop()
        elif mutation == "wrong_order": bad["order"] = ["ko","en","ja","ko","en"]
        elif mutation == "reused_ko": bad["reports"][4] = bad["reports"][0]
        elif mutation == "reused_first_en": bad["reports"][3] = bad["reports"][1]
        elif mutation == "container_reset": bad["preserved_app_container"] = False
        else: bad["schema"] = 1
        with pytest.raises(probe.ProbeError): probe.validate_language_matrix_report(bad)


def test_language_canary_file_is_descriptor_bound_and_matches_consumed_bytes(app):
    expected, digest = probe.load_language_canaries(app,hashlib.sha256(public_descriptor()).hexdigest())
    assert digest == hashlib.sha256(language_canary_bytes()).hexdigest()
    summary = probe.validate_language_relaunch_report(native_report("en"),"en")
    probe.compare_language_canaries(summary,"en",expected,digest)
    summary["unity_host_probe"]["canaries"]["Data/resources.assets"]["expected_sha256"] = "0"*64
    with pytest.raises(probe.ProbeError,match="language_canaries_mismatch"):
        probe.compare_language_canaries(summary,"en",expected,digest)
    with pytest.raises(probe.ProbeError,match="language_canaries_invalid"):
        probe.load_language_canaries(app,"0"*64)


@pytest.mark.parametrize("mutation", ("missing_language","extra_path","bool_bytes","oversize","bad_hash"))
def test_derived_language_canary_loader_rejects_unbounded_or_incomplete_records(app, mutation):
    value = language_canaries()
    if mutation == "missing_language": del value["languages"]["ja"]
    elif mutation == "extra_path": value["languages"]["ko"]["private/path"] = {"bytes":1,"sha256":"0"*64}
    elif mutation == "bool_bytes": value["languages"]["ko"]["Data/resources.assets"]["bytes"] = True
    elif mutation == "oversize": value["languages"]["en"]["Data/resources.assets"]["bytes"] = 128*1024*1024+1
    else: value["languages"]["ja"]["Data/resources.assets"]["sha256"] = "z"*64
    (app/"probe-language-canaries.json").write_text(json.dumps(value))
    with pytest.raises(probe.ProbeError,match="language_canaries_invalid"):
        probe.load_language_canaries(app,hashlib.sha256(public_descriptor()).hexdigest())


def test_language_audit_drops_unknown_errors_paths_and_payloads():
    native = native_report()
    native["server_status"]["unity_host"]["private_path"] = "must-not-export"
    native["unity_host_probe"]["canaries"]["Data/resources.assets"]["private_payload"] = "must-not-export"
    native["interface_language_cycle"][0]["private_text"] = "must-not-export"
    native["language_save"]["private_text"] = "must-not-export"
    assert "must-not-export" not in json.dumps(probe.validate_report(native))
    native["server_status"]["unity_host"].update(error="must-not-export",runtime_start_calls=True)
    native["unity_host_probe"]["canaries"]["private/path"] = {"secret":"must-not-export"}
    observed = probe.language_observation(native)
    assert "error" not in observed["unity_host"] and "runtime_start_calls" not in observed["unity_host"]
    assert "must-not-export" not in json.dumps(observed) and "private/path" not in json.dumps(observed)


@pytest.mark.parametrize("source", ("status","checkpoint","report"))
def test_language_failure_projection_reads_only_expected_process_files(tmp_path, source):
    documents = tmp_path/"Documents"; documents.mkdir()
    native = native_report("en")
    native["server_status"]["unity_host"]["error"] = "must-not-export"
    native["unity_host_probe"].update(game_window_key=False,private="must-not-export")
    final,status,checkpoint = probe.language_paths("en")
    if source == "checkpoint":
        value = {"schema":1,"stage":"host_ready","unity_host":native["server_status"]["unity_host"],
            "unity_host_probe":native["unity_host_probe"],"language_save":native["language_save"]}
    else: value = native
    (documents/{"status":status,"checkpoint":checkpoint,"report":final}[source]).write_text(json.dumps(value))
    (documents/"embedded-probe-status.json").write_text("must-not-read-stale-ko")
    checked = probe.failure_checkpoint(tmp_path,"en")
    assert checked["language_observation"]["unity_host_probe"]["game_window_key"] is False
    assert "must-not-export" not in json.dumps(checked)
    if source == "checkpoint": assert checked["stage"] == "host_ready"


def test_language_relaunch_wait_never_accepts_old_ko_report(tmp_path):
    documents = tmp_path/"Documents"; documents.mkdir()
    (documents/"embedded-probe.json").write_text(json.dumps(native_report()))
    remaining = mock.Mock(side_effect=[1,1,probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time,"sleep"),pytest.raises(probe.ProbeError,match="probe_deadline_exceeded"):
        probe.wait_report(tmp_path,remaining,expected_language="en")
    (documents/"embedded-language-en.json").write_text(json.dumps(native_report()))
    with pytest.raises(probe.ProbeError,match="language_relaunch_mismatch"):
        probe.wait_report(tmp_path,lambda:1,expected_language="en")


def test_language_waiting_failure_and_deadline_export_only_public_process_evidence(tmp_path):
    documents = tmp_path/"Documents"; documents.mkdir()
    value = {"server_status":{"phase":2,"error":None,"unity_host":{"started":False,"error":"must-not-export"}},
        "unity_host_probe":{"game_window_key":False,"private":"must-not-export"},
        "probe_error":"unity_window_handoff_failed"}
    (documents/"embedded-language-en-status.json").write_text(json.dumps(value))
    with pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path,lambda:1,expected_language="en")
    assert caught.value.native_language["unity_host"]["started"] is False
    assert "must-not-export" not in json.dumps(caught.value.native_language)
    del value["probe_error"]
    (documents/"embedded-language-en-status.json").write_text(json.dumps(value))
    remaining = mock.Mock(side_effect=[1,1,probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time,"sleep"),pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path,remaining,expected_language="en")
    assert caught.value.native_language["unity_host_probe"]["game_window_key"] is False


def test_five_cold_processes_preserve_container_and_run_external_ko_gates_once(app, tmp_path):
    controller = FakeSimctl(tmp_path/"matrix-container")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]) as rpc, \
            mock.patch.object(probe,"probe_master_file",return_value=master_file_report()) as master, \
            mock.patch.object(probe,"probe_sdk_resource",return_value=sdk_resource_report()) as sdk:
        result = probe.run_probe(app,tmp_path/"matrix.json")
    assert result["status"] == "PASS"
    assert result["language_matrix"]["schema"] == 2
    assert result["language_matrix"]["order"] == ["ko","en","ja","en","ko"]
    assert result["language_matrix"]["preserved_app_container"] is True
    assert [row[3] for row in controller.calls if row[0] == "launch"] == [
        "--idoly-probe-language=ko","--idoly-probe-language=en","--idoly-probe-language=ja",
        "--idoly-probe-language=en","--idoly-probe-language=ko"]
    assert [row[0] for row in controller.calls].count("install") == 1
    assert [row[4] for row in controller.calls if row[0] == "launch"] == [
        "--idoly-probe-run-index="+str(index) for index in range(5)]
    launch_budgets = [budget for row,budget in zip(controller.calls,controller.timeouts) if row[0] == "launch"]
    assert len(launch_budgets) == 5 and all(0 < value <= 30 for value in launch_budgets[1:])
    assert [row for row in controller.calls if row[0] == "terminate"] == [
        ("terminate",CREATED,probe.BUNDLE_ID)]*4
    rpc.assert_called_once();master.assert_called_once();sdk.assert_called_once()
    assert all((controller.container/"Documents"/probe.language_paths(language,index)[0]).exists()
               for index,language in enumerate(("ko","en","ja","en","ko")))


@pytest.mark.parametrize("failure", ("old_ko_report","native_aes_failure","canary_mismatch","preexisting_ja"))
def test_relaunch_cannot_skip_native_crypto_canary_or_fresh_report_contract(app, tmp_path, failure):
    controller = FakeSimctl(tmp_path/"matrix-failure-container")
    def command(arguments,timeout):
        result = controller(arguments,timeout)
        if arguments[0] == "launch" and arguments[3] == "--idoly-probe-language=en":
            path = controller.container/"Documents/embedded-language-en.json"
            value = native_report("en")
            if failure == "old_ko_report": value = native_report()
            elif failure == "native_aes_failure": value["native_crypto"]["nist_decrypt"] = False
            elif failure == "canary_mismatch":
                value["unity_host_probe"]["canaries"]["Data/resources.assets"].update(
                    expected_sha256="0"*64,actual_sha256="0"*64)
            else: (controller.container/"Documents/embedded-language-ja.json").write_text("owned-stale-file")
            path.write_text(json.dumps(value))
        return result
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",command), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]) as rpc, \
            mock.patch.object(probe,"probe_master_file",return_value=master_file_report()), \
            mock.patch.object(probe,"probe_sdk_resource",return_value=sdk_resource_report()):
        result = probe.run_probe(app,tmp_path/"matrix-failure.json")
    assert result["status"] == "FAIL" and result["cleanup"] == {"shutdown":True,"delete":True}
    rpc.assert_called_once()
    assert [row[0] for row in controller.calls].count("launch") == 2
    if failure == "old_ko_report": assert result["error"] == "language_relaunch_mismatch"
    elif failure == "native_aes_failure": assert result["error"] == "python_commoncrypto_bridge_failed"
    elif failure == "canary_mismatch": assert result["error"] == "language_canaries_mismatch"
    else:
        assert result["error"] == "preexisting_language_report_rejected"
        assert (controller.container/"Documents/embedded-language-ja.json").read_text() == "owned-stale-file"


def test_language_relaunches_share_the_overall_nine_hundred_second_deadline(app, tmp_path):
    controller = FakeSimctl(tmp_path/"matrix-deadline-container")
    clock = {"now":0.0}
    def command(arguments,timeout):
        result = controller(arguments,timeout)
        if arguments[0] == "launch" and arguments[3] == "--idoly-probe-language=en":
            clock["now"] = 900.0
        return result
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",command), \
            mock.patch.object(probe.time,"monotonic",side_effect=lambda:clock["now"]), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]) as rpc, \
            mock.patch.object(probe,"probe_master_file",return_value=master_file_report()), \
            mock.patch.object(probe,"probe_sdk_resource",return_value=sdk_resource_report()):
        result = probe.run_probe(app,tmp_path/"matrix-deadline.json",timeout=900)
    assert result["status"] == "FAIL" and result["error"] == "probe_deadline_exceeded"
    assert result["failed_stage"] == "language_report_en"
    assert [row[0] for row in controller.calls].count("launch") == 2
    rpc.assert_called_once()
    assert result["cleanup"] == {"shutdown":True,"delete":True}



def test_five_complete_cold_processes_can_use_the_bounded_budget_beyond_six_hundred_seconds(app, tmp_path):
    controller = FakeSimctl(tmp_path/"five-cold-budget-container")
    clock = {"now":0.0}
    def command(arguments,timeout):
        result = controller(arguments,timeout)
        if arguments[0] == "launch":
            run_index=int(arguments[-1].split("=")[1])
            clock["now"]=(210.0,410.0,610.0,740.0,899.0)[run_index]
        return result
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",command), \
            mock.patch.object(probe.time,"monotonic",side_effect=lambda:clock["now"]), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]) as rpc, \
            mock.patch.object(probe,"probe_master_file",return_value=master_file_report()), \
            mock.patch.object(probe,"probe_sdk_resource",return_value=sdk_resource_report()):
        result=probe.run_probe(app,tmp_path/"five-cold-budget.json")
    assert result["status"] == "PASS" and result["seconds"] == 899.0
    assert result["language_matrix"]["order"] == ["ko","en","ja","en","ko"]
    assert [row["run_index"] for row in result["language_matrix"]["reports"]] == list(range(5))
    assert [row[0] for row in controller.calls].count("launch") == 5
    assert result["cleanup"] == {"shutdown":True,"delete":True}
    rpc.assert_called_once()


def test_probe_rejects_overall_budget_above_nine_hundred_before_simulator_mutation(app, tmp_path):
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl") as simctl:
        result=probe.run_probe(app,tmp_path/"invalid-budget.json",timeout=901)
    assert result["status"] == "FAIL" and result["error"] == "invalid_probe_timeout"
    simctl.assert_not_called()


def test_server_gate_scalar_observation_preserves_native_bool_and_zero_one_integer_types():
    value = {"hook_installed":1,"python_initialized":False,"captured":0,"forwarded":16,"attempts":1,
        "error":None,"private_path":"never-export-gate"}
    result = probe.server_gate_observation(value)
    assert result == {"hook_installed":1,"python_initialized":False,"captured":0,"forwarded":16,
                      "attempts":1,"error":None}
    assert type(result["hook_installed"]) is int and type(result["python_initialized"]) is bool
    assert "never-export-gate" not in json.dumps(result)


def test_server_gate_scalar_observation_drops_bad_types_and_counts_and_redacts_nonnull_errors():
    result = probe.server_gate_observation({"hook_installed":"1","python_initialized":2,
        "captured":True,"forwarded":17,"attempts":-1,"error":{"private":"never-export-gate"}})
    assert result == {"error":"non_null"}
    assert probe.server_gate_observation({}) == {}
    assert probe.server_gate_observation({"error":None}) == {"error":None}
    assert probe.server_gate_observation(None) == {}
    assert "never-export-gate" not in json.dumps(result)


@pytest.mark.parametrize("flag", ("hook_installed","python_initialized"))
def test_integer_native_ready_flag_still_fails_strict_validator_and_retains_actual_type_in_audit(app, tmp_path, flag):
    native = native_report()
    native["server_status"].update({flag:1,"private_path":"never-export-gate"})
    with pytest.raises(probe.ProbeError,match="embedded_server_not_ready"):
        probe.validate_report(native)
    controller = FakeSimctl(tmp_path/"integer-gate-container")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller), \
            mock.patch(__name__+".native_report",return_value=native),mock.patch.object(probe,"probe_rpcs") as rpc:
        result = probe.run_probe(app,tmp_path/"integer-gate-failure.json")
    assert result["error"] == "embedded_server_not_ready"
    assert result["native_server_gate_observed"][flag] == 1
    assert type(result["native_server_gate_observed"][flag]) is int
    assert type(result["native_checkpoint"]["server_gate"][flag]) is int
    assert result["native_server_gate_observed"]["error"] is None
    assert "never-export-gate" not in json.dumps(result)
    rpc.assert_not_called()


@pytest.mark.parametrize("source,filename", (("checkpoint","embedded-probe-checkpoint.json"),
    ("status","embedded-probe-status.json"),("report","embedded-probe.json")))
def test_server_gate_failure_checkpoint_keeps_bounded_actual_types_and_redacts_errors(tmp_path, source, filename):
    documents = tmp_path/"Documents";documents.mkdir()
    native = native_report()
    native["server_status"].update(hook_installed=1,error="never-export-gate",private="never-export-gate")
    value = native if source == "report" else {"schema":1,"stage":"host_ready", "server_status":native["server_status"]}
    (documents/filename).write_text(json.dumps(value))
    result = probe.failure_checkpoint(tmp_path)
    assert result["server_gate"]["hook_installed"] == 1
    assert type(result["server_gate"]["hook_installed"]) is int
    assert result["server_gate"]["error"] == "non_null"
    assert "never-export-gate" not in json.dumps(result)
    if source == "checkpoint": assert result["stage"] == "host_ready"


def test_server_gate_waiting_probe_failure_and_deadline_keep_only_fixed_scalar_observations(tmp_path):
    documents = tmp_path/"Documents";documents.mkdir()
    path = documents/"embedded-probe-status.json"
    value = {"server_status":{"phase":2,"hook_installed":1,"python_initialized":True,
        "captured":1,"forwarded":0,"attempts":1,"error":None,"private":"never-export-gate"},
        "probe_error":"host_cold_start_failed"}
    path.write_text(json.dumps(value))
    with pytest.raises(probe.ProbeError,match="host_cold_start_failed") as caught:
        probe.wait_report(tmp_path,lambda:1)
    assert type(caught.value.native_server_gate["hook_installed"]) is int
    assert caught.value.native_server_gate["python_initialized"] is True
    assert "never-export-gate" not in json.dumps(caught.value.native_server_gate)
    del value["probe_error"]
    path.write_text(json.dumps(value))
    remaining = mock.Mock(side_effect=[1,1,probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time,"sleep"),pytest.raises(probe.ProbeError,match="probe_deadline_exceeded") as caught:
        probe.wait_report(tmp_path,remaining)
    assert caught.value.native_server_gate["forwarded"] == 0
    assert type(caught.value.native_server_gate["hook_installed"]) is int
    assert caught.value.native_server_gate["error"] is None
    assert "never-export-gate" not in json.dumps(caught.value.native_server_gate)


@pytest.mark.parametrize("run_index,language", enumerate(("ko","en","ja","en","ko")))
def test_five_run_cache_proof_distinguishes_first_visit_from_actual_return(run_index, language):
    native = native_report(language,run_index)
    checked = probe.validate_language_relaunch_report(native,language,run_index=run_index)
    observed = checked["unity_host_probe"]
    assert checked["run_index"] == run_index and observed["run_index"] == run_index
    assert observed["cache_return"] is (run_index >= 3)
    assert observed["cache_identity_recorded"] is True
    assert observed["cache_files_same_identity"] is (True if run_index >= 3 else None)
    assert observed["prelaunch_server_healthy"] is True and observed["prelaunch_runtime_cold"] is True
    assert checked["language_save"]["next_language"] == ("en","ja","en","ko","ko")[run_index]


@pytest.mark.parametrize("key,value", (("cache_return",False),("cache_return",1),
    ("cache_identity_recorded",False),("cache_identity_recorded",1),
    ("cache_files_same_identity",False),("cache_files_same_identity",None),("cache_files_same_identity",1)))
def test_return_run_requires_real_existing_cache_identity_comparison(key, value):
    native = native_report("ko",4)
    native["unity_host_probe"][key] = value
    with pytest.raises(probe.ProbeError,match="language_cache_identity_failed"):
        probe.validate_language_relaunch_report(native,"ko",run_index=4)


def test_first_visit_must_not_claim_cache_identity_comparison_before_baseline_exists():
    native = native_report()
    native["unity_host_probe"]["cache_files_same_identity"] = True
    with pytest.raises(probe.ProbeError,match="language_cache_identity_failed"):
        probe.validate_report(native)
    observed = probe.unity_host_probe_observation({"run_index":True,"cache_return":1,
        "cache_identity_recorded":False,"cache_files_same_identity":None,"private_inodes":[1,2,3]})
    assert observed == {"cache_identity_recorded":False,"cache_files_same_identity":None}


def test_run_specific_fixed_paths_preserve_old_reports_and_bind_language_index_pair():
    stems = ("embedded-probe","embedded-language-en","embedded-language-ja",
        "embedded-language-en-return","embedded-language-ko-return")
    all_paths = []
    for run_index,(language,stem) in enumerate(zip(("ko","en","ja","en","ko"),stems)):
        paths = probe.language_paths(language,run_index)
        assert paths == tuple(stem+suffix+".json" for suffix in ("","-status","-checkpoint"))
        all_paths.extend(paths)
    assert len(set(all_paths)) == 15
    assert probe.language_paths("en") == probe.language_paths("en",1)
    for language,index in (("ko",True),("ko",-1),("ko",5),("en",4),("ja",3)):
        with pytest.raises(probe.ProbeError,match="language_relaunch_mismatch"):
            probe.language_paths(language,index)


@pytest.mark.parametrize("failure", ("stale_first_en","cache_identity","warm_runtime","changed_canary"))
def test_actual_return_cannot_reuse_first_en_or_skip_identity_cold_runtime_and_canary_gates(app, tmp_path, failure):
    controller = FakeSimctl(tmp_path/"return-failure-container")
    def command(arguments,timeout):
        result = controller(arguments,timeout)
        if arguments[0] == "launch" and arguments[-1] == "--idoly-probe-run-index=3":
            native = native_report("en",3)
            if failure == "stale_first_en": native = native_report("en",1)
            elif failure == "cache_identity": native["unity_host_probe"]["cache_files_same_identity"] = False
            elif failure == "warm_runtime": native["unity_host_probe"]["prelaunch_runtime_cold"] = False
            else:
                native["unity_host_probe"]["canaries"]["Data/resources.assets"].update(
                    expected_sha256="0"*64,actual_sha256="0"*64)
            (controller.container/"Documents/embedded-language-en-return.json").write_text(json.dumps(native))
        return result
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",command), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]) as rpc, \
            mock.patch.object(probe,"probe_master_file",return_value=master_file_report()), \
            mock.patch.object(probe,"probe_sdk_resource",return_value=sdk_resource_report()):
        result = probe.run_probe(app,tmp_path/"return-failure.json")
    assert result["status"] == "FAIL" and result["failed_run_index"] == 3
    assert result["cleanup"] == {"shutdown":True,"delete":True}
    assert [row[0] for row in controller.calls].count("launch") == 4
    assert (controller.container/"Documents/embedded-language-en.json").exists()
    assert (controller.container/"Documents/embedded-language-ja.json").exists()
    assert result["native_checkpoint"]["report_available"] is True
    rpc.assert_called_once()
    expected = {"stale_first_en":"language_relaunch_mismatch","cache_identity":"language_cache_identity_failed",
        "warm_runtime":"unity_host_probe_failed","changed_canary":"language_canaries_mismatch"}[failure]
    assert result["error"] == expected


def test_private_probe_cache_identity_file_must_be_absent_initially_and_is_never_deleted(app, tmp_path):
    controller = FakeSimctl(tmp_path/"preexisting-cache-identity-container")
    path = controller.container/"Documents/probe-cache-identities.json"
    path.parent.mkdir();path.write_text("owned-existing-private-state")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller):
        result = probe.run_probe(app,tmp_path/"cache-identity-failure.json")
    assert result["error"] == "preexisting_probe_state_rejected"
    assert not any(row[0] == "launch" for row in controller.calls)
    assert path.read_text() == "owned-existing-private-state"


def test_native_boolean_observations_cast_c_logical_results_before_json_boxing():
    source = (Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    # Objective-C C operators yield int. NSNumber(1) is not JSON true, even
    # though isEqual:@YES accepts it; keep the strict Python bool gate.
    for variable,key in (("pass","single_selection"),("pass","delegate_is_settings"),
            ("metrics","picker_import_mode"),("metrics","picker_single_selection"),
            ('state[@"metrics"]',"wk_import_dispatched"),("metrics","backend_success"),
            ("metrics","picker_detached"),("metrics","owned_copy_found"),("metrics","copy_source_distinct"),
            ("metrics","source_preserved"),("metrics","copy_bytes_match"),("metrics","export_accepted"),
            ("self.launcherProbe","game_button_disabled_during_flush")):
        anchor = variable+'[@"'+key+'"]='
        assert source.count(anchor) == 1
        assert source.split(anchor,1)[1].startswith('@((BOOL)('), key


def test_autosave_language_probe_uses_own_feedback_correlated_send_and_independent_readback():
    source = (Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    saving = source.split("static void ProbeAutoSaveLanguage(",1)[1].split("static NSString *ProbeChromeTitle(",1)[0]
    assert "window.__idolyProbeGameAck=null" in saving and "window.__idolyProbeOptionsRequest=null" in saving
    assert "r.action==='save_options'" in saving and "return original.apply(h,arguments)" in saving
    assert "getElementById('options-save-feedback')" in saving and "m.dataset.state==='saved'" in saving
    assert "getElementById('message')" not in saving and "requestSubmit" not in saving
    assert "a.id===r.id" in saving and "IdolyEmbeddedServerCommand(request" in saving
    assert 'options[@"language"]' in saving and 'activeOptions[@"language"]' in saving
    assert "15*NSEC_PER_SEC" in saving
    polling = source.split("static void ProbePollLanguageAttempt(",1)[1].split("static void ProbeAutoSaveLanguage(",1)[0]
    assert 'last[@"ready"]=@NO' in polling and 'last[@"timed_out"]=@YES' in polling
    hook = source.split("static NSString *const ProbeReplyHook",1)[1].split("static void ProbePollLanguageAttempt(",1)[0]
    assert "q.action==='save_options'&&q.id===id" in hook
    relaunch = source.split('- (void)saveNextLanguage:(WKWebView *)web completion:(void (^)(BOOL))completion {',1)[1].split('- (void)probeLauncher:',1)[0]
    assert 'failed[@"attempted_language"]=@"en"; finish(failed)' in relaunch
    assert '@"next_language":attempted' in relaunch


@pytest.mark.parametrize("field,value", [(key,value) for key in probe.LANGUAGE_SAVE_FLAGS for value in (False,1)] + [
    ("feedback_source","message"),("feedback_state","pending"),("feedback_state","failed"),
    ("request_action","status"),("request_language","ko"),("request_id",199),("request_id",True),
    ("ack_language","ko"),("ack_effective_language","en"),("timed_out",True),("timed_out",0)])
def test_language_save_requires_matching_form_feedback_correlated_ack_and_server_readback(field, value):
    observed = native_report()
    observed["language_save"][field] = value
    with pytest.raises(probe.ProbeError, match="^language_save_failed$"):
        probe.validate_report(observed)


def test_language_save_timeout_preserves_only_bounded_last_ack_and_form_scalars():
    raw = {"request_id":22,"request_action":"save_options","request_language":"ja","request_observed":True,
        "ack_id":22,"ack_correlated":True,"acknowledged":True,"ack_language":"ja","ack_effective_language":"en",
        "feedback_source":"options-save-feedback","feedback_state":"pending","form_feedback_saved":False,
        "options_fields_reenabled":True,"server_status_received":False,"timed_out":True,
        "persisted_language":"unknown","effective_language":"unknown","raw_message":"DO-NOT-EXPORT"}
    clean = probe.language_save_observation(raw)
    assert clean["request_id"] == clean["ack_id"] == 22 and clean["ack_language"] == "ja"
    assert clean["feedback_state"] == "pending" and clean["form_feedback_saved"] is False
    assert clean["server_status_received"] is False and clean["persisted_language"] == "unknown" and clean["timed_out"] is True
    assert "DO-NOT-EXPORT" not in json.dumps(clean)


def test_settings_views_share_only_one_nonpersistent_store_and_still_create_new_web_views():
    source = (Path(__file__).resolve().parents[1]/"ios-unified/native/IdolySettings.m").read_text()
    shared = source.split("static WKWebsiteDataStore *IDSettingsWebsiteDataStore(",1)[1].split("static NSInteger resolvedInterfaceLanguage(",1)[0]
    assert "dispatch_once(&once" in shared and "WKWebsiteDataStore.nonPersistentDataStore" in shared
    assert source.count("WKWebsiteDataStore.nonPersistentDataStore") == 1
    assert "configuration.websiteDataStore = IDSettingsWebsiteDataStore();" in source
    assert "[[WKWebView alloc] initWithFrame:self.view.bounds configuration:configuration]" in source
    assert "defaultDataStore" not in source and "WKProcessPool" not in source


@pytest.mark.parametrize("field,value", [(key,value) for key in ("data_store_reused","launcher_store_nonpersistent",
    "menu_store_nonpersistent","web_view_recreated","launcher_document_marker_absent") for value in (False,1)])
def test_settings_context_reuses_nonpersistent_store_without_reusing_document(field, value):
    observed = native_report()
    observed["menu_lifetime"]["web"][field] = value
    with pytest.raises(probe.ProbeError,match="^settings_web_readiness_or_layout_failed$"):
        probe.validate_report(observed)


def test_settings_dom_waits_for_public_navigation_before_evaluation_with_same_deadline():
    source = (Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    attempt = source.split("static void ProbeSettingsDOMAttempt(",1)[1].split("static void ProbeSettingsDOM(",1)[0]
    assert "web.estimatedProgress" in attempt and "web.URL.isFileURL" in attempt
    assert "web.window!=nil" in attempt and "web.isLoading" in attempt
    gate = attempt.index("if (!navigationReady)")
    evaluation = attempt.index("[web evaluateJavaScript:ProbeSettingsDOMScript")
    assert gate < evaluation and "return;" in attempt[gate:evaluation]
    assert "NSEC_PER_SEC/20" in attempt[gate:evaluation]
    deadline = source.split("static void ProbeSettingsDOM(",1)[1].split("static void ProbeDiagnosticsCopyAttempt(",1)[0]
    assert "10 * NSEC_PER_SEC" in deadline


@pytest.mark.parametrize("field,value", [("navigation_loading",True),("navigation_loading",0),
    ("navigation_file_url",False),("web_attached",False),("evaluation_started",False),("evaluation_completed",False),
    ("evaluation_completed",1),("navigation_progress",True),("navigation_progress",0.99),("navigation_progress",float("nan"))])
def test_settings_dom_requires_completed_attached_file_navigation_and_evaluation(field, value):
    observed = native_report()
    observed["menu_lifetime"]["web"][field] = value
    with pytest.raises(probe.ProbeError, match="^settings_web_readiness_or_layout_failed$"):
        probe.validate_report(observed)


def test_settings_dom_timeout_distinguishes_loading_from_unanswered_evaluation_without_urls():
    waiting = probe.settings_web_observation({"navigation_loading":True,"navigation_progress":0.3,
        "navigation_file_url":True,"web_attached":True,"evaluation_started":False,"evaluation_completed":False,
        "observations":201,"timed_out":True,"url":"DO-NOT-EXPORT"})
    assert waiting["navigation_progress"] == 0.3 and waiting["observations"] == 201
    assert waiting["evaluation_started"] is False and waiting["evaluation_completed"] is False
    unresponsive = probe.settings_web_observation({**waiting,"navigation_loading":False,"navigation_progress":1,
        "evaluation_started":True,"evaluation_completed":False})
    assert unresponsive["evaluation_started"] is True and unresponsive["evaluation_completed"] is False
    assert "DO-NOT-EXPORT" not in json.dumps((waiting,unresponsive))
    assert probe.settings_web_observation({"navigation_progress":True,"evaluation_started":1,
        "observations":257,"url":"DO-NOT-EXPORT"}) == {}


def test_settings_web_diagnostic_projection_keeps_only_bounded_scalar_metrics():
    observed = probe.settings_web_observation({"web_found":True,"ready":False,"document_complete":False,
        "options_fields_enabled":True,"presentation_fields_enabled":False,"bridge_reply_present":True,
        "error_is_wk_domain":True,"viewport_width":402,"content_width":403.5,"select_count":14,
        "observations":128,"elapsed_seconds":600,"evaluation_error_code":-100,
        "script":"never-export-web","error_description":"never-export-web"})
    assert observed["ready"] is False and observed["evaluation_error_code"] == -100
    assert observed["observations"] == 128 and "never-export-web" not in json.dumps(observed)
    assert probe.settings_web_observation({"ready":1,"viewport_width":float("nan"),"content_width":16385,
        "select_count":True,"observations":257,"elapsed_seconds":601,"evaluation_error_code":True,
        "timed_out":True,"raw":"never-export-web"}) == {"timed_out":True}
    assert probe.settings_web_from_observation({"menu_lifetime":{"web":{"ready":False,"select_count":0}}}) == {
        "ready":False,"select_count":0}


def test_settings_overflow_diagnostics_are_capped_and_never_export_arbitrary_dom_content():
    safe={"tag":"BUTTON","id":"accounts-select","right":485,"width":400,"scroll_width":400}
    private={**safe,"tag":"DO-NOT-EXPORT","id":"DO-NOT-EXPORT","text":"DO-NOT-EXPORT","value":"DO-NOT-EXPORT"}
    clean=probe.settings_web_observation({"overflow_elements":[private,*([safe]*12)]})
    assert len(clean["overflow_elements"]) == 8
    assert clean["overflow_elements"][0] == {**safe,"tag":"OTHER","id":""}
    assert "DO-NOT-EXPORT" not in json.dumps(clean)
    for bad in (True,float("nan"),float("inf"),16385):
        assert probe.settings_web_observation({"overflow_elements":[{**safe,"width":bad}]}) == {"overflow_elements":[]}


def test_actual_settings_dom_script_collects_safe_overflow_geometry_without_accepting_layout():
    import re
    import subprocess
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    expression=re.search(r"static NSString \*const ProbeSettingsDOMScript =\s*(.*?)\nstatic void ProbeSettingsDOMAttempt",source,re.S)
    pieces=re.findall(r'@?("(?:\\.|[^"\\])*")',expression.group(1))
    script="".join(json.loads(piece) for piece in pieces).rstrip(";")
    program=r"""
const node={tagName:'BUTTON',id:'accounts-select',scrollWidth:400,
  getBoundingClientRect(){return {right:485,left:85,width:400,height:44};}};
const unknown={...node,tagName:'DO-NOT-EXPORT',id:'DO-NOT-EXPORT',textContent:'DO-NOT-EXPORT'};
const fields={disabled:false},presets={options:[{value:'2'},{value:'4096'}]};
const document={documentElement:{clientWidth:402,scrollWidth:485},
  body:{scrollWidth:485,querySelectorAll(){return [...Array(12).fill(node),unknown];}},readyState:'complete',
  getElementById(id){return id.endsWith('-fields')?fields:presets;},querySelectorAll(){return [];}};
const window={idolyServerReply(){}};
"""+"process.stdout.write(JSON.stringify("+script+"));"
    checked=subprocess.run(["node"],input=program,text=True,capture_output=True,timeout=5)
    assert checked.returncode==0,checked.stderr
    observed=json.loads(checked.stdout)
    assert observed["ready"] is True and observed["no_horizontal_overflow"] is False
    assert len(observed["overflow_elements"]) == 8
    assert "DO-NOT-EXPORT" not in checked.stdout
    assert probe.settings_web_observation(observed)["overflow_elements"] == observed["overflow_elements"]


@pytest.mark.parametrize("source,filename", (("checkpoint","embedded-language-en-checkpoint.json"),
    ("status","embedded-language-en-status.json"),("report","embedded-language-en.json")))
def test_settings_web_diagnostics_survive_checkpoint_status_and_final_without_raw_web_payload(tmp_path, source, filename):
    documents = tmp_path/"Documents";documents.mkdir()
    native = native_report("en",1)
    metrics = {"web_found":True,"ready":False,"document_complete":False,"observations":7,
        "elapsed_seconds":10.5,"evaluation_error_code":4,"error_is_wk_domain":True,"raw":"never-export-web"}
    value = native if source == "report" else {"schema":1,"stage":"settings_web_observed"}
    if source == "report":
        value["menu_lifetime"]["web"].update(metrics)
    else: value["settings_web"] = metrics
    (documents/filename).write_text(json.dumps(value))
    observed = probe.failure_checkpoint(tmp_path,"en",1)
    assert observed["settings_web"]["ready"] is False and observed["settings_web"]["observations"] == 7
    assert observed["settings_web"]["evaluation_error_code"] == 4
    if source == "checkpoint": assert observed["stage"] == "settings_web_observed"
    assert "never-export-web" not in json.dumps(observed)


def test_settings_web_final_failure_still_enforces_dom_gate_and_exports_safe_observation(app, tmp_path):
    native = native_report()
    native["menu_lifetime"]["web"].update(ready=False,document_complete=False,observations=3,
        elapsed_seconds=10.25,evaluation_error_code=5,error_is_wk_domain=True,raw="never-export-web")
    controller = FakeSimctl(tmp_path/"settings-web-failure-container")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller), \
            mock.patch(__name__+".native_report",return_value=native),mock.patch.object(probe,"probe_rpcs") as rpc:
        result = probe.run_probe(app,tmp_path/"settings-web-failure.json")
    assert result["error"] == "settings_web_readiness_or_layout_failed"
    assert result["native_settings_web_observed"]["document_complete"] is False
    assert result["native_settings_web_observed"]["evaluation_error_code"] == 5
    assert "never-export-web" not in json.dumps(result)
    rpc.assert_not_called()


def test_settings_web_probe_error_and_deadline_preserve_safe_latest_metrics(tmp_path):
    documents = tmp_path/"Documents";documents.mkdir()
    path = documents/"embedded-language-en-status.json"
    value = {"server_status":{"phase":4,"error":None},"settings_web":{"ready":False,
        "observations":12,"elapsed_seconds":10.1,"evaluation_error_code":4,"raw":"never-export-web"},
        "probe_error":"settings_web_readiness_or_layout_failed"}
    path.write_text(json.dumps(value))
    with pytest.raises(probe.ProbeError) as caught: probe.wait_report(tmp_path,lambda:1,expected_language="en",run_index=1)
    assert caught.value.native_settings_web["observations"] == 12
    assert "never-export-web" not in json.dumps(caught.value.native_settings_web)
    del value["probe_error"];path.write_text(json.dumps(value))
    remaining = mock.Mock(side_effect=[1,1,probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time,"sleep"),pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path,remaining,expected_language="en",run_index=1)
    assert caught.value.native_settings_web["elapsed_seconds"] == 10.1
    assert "never-export-web" not in json.dumps(caught.value.native_settings_web)


@pytest.mark.parametrize("phase,key,value", (
    ("before_server","sigaction_read",False),("before_server","sigpipe_ignored",False),
    ("before_server","write_epipe",False),("before_server","process_survived",False),
    ("before_game_worker","socketpair_created",False),("before_game_worker","peer_closed",False),
    ("before_game_worker","write_epipe",1),("before_server","main_thread",False),
    ("before_game_worker","main_thread",True),("before_server","schema",True)))
def test_sigpipe_proof_requires_actual_survived_epipe_on_main_and_ready_worker(phase, key, value):
    native = native_report()
    native["unity_host_probe"]["sigpipe"][phase][key] = value
    with pytest.raises(probe.ProbeError,match="sigpipe_probe_failed"):
        probe.validate_report(native)


def test_sigpipe_failure_projection_is_partial_bounded_and_never_exports_raw_signal_state():
    native = native_report("ko",4)
    native["unity_host_probe"]["sigpipe"]["before_server"].update(raw_mask="never-export-sigpipe")
    checked = probe.validate_language_relaunch_report(native,"ko",run_index=4)
    assert "never-export-sigpipe" not in json.dumps(checked)
    pipe = checked["unity_host_probe"]["sigpipe"]
    assert pipe["before_server"]["main_thread"] is True
    assert pipe["before_game_worker"]["main_thread"] is False
    assert pipe["before_server"]["write_epipe"] is True
    assert probe.unity_host_observation({"error":"sigpipe_guard_failed","private_signal":"never-export-sigpipe"}) == {
        "error":"sigpipe_guard_failed"}
    assert probe.sigpipe_observation({"before_server":{"schema":True,"sigaction_read":1,
        "process_survived":False,"raw_signal":"never-export-sigpipe"},
        "unknown_phase":{"raw_signal":"never-export-sigpipe"}}) == {"before_server":{"process_survived":False}}
    del native["unity_host_probe"]["sigpipe"]["before_game_worker"]
    with pytest.raises(probe.ProbeError,match="sigpipe_probe_failed"):
        probe.validate_report(native)


@pytest.mark.parametrize("phase,key,value", (
    ("current","header_found",False),("current","actions_found",1),("current","nav_bar_hidden",False),
    ("current","button_count",True),("current","button_count",1),("current","root_width",True),
    ("current","root_height",float("inf")),("current","header_width",394),
    ("current","actions_width",394),("current","header_height",853),("current","min_button_height",43),
    ("current","button_min_font",15),("current","title_font",19),("current","status_font",15),
    ("current","hint_font",11),("current","button_min_font",float("nan")),
    ("wide","root_width",1919),("wide","root_height",1079),("wide","row_no_overlap",False),
    ("wide","button_min_font",19),("wide","title_font",24),
    ("ultrawide","root_width",3839),("ultrawide","root_height",2159),
    ("ultrawide","button_min_font",39),("ultrawide","status_font",39),
    ("ultrawide","hint_font",19),("ultrawide","button_titles_fit",False),
    ("restored","root_width",393.2),("restored","title_font",24.2),
))
def test_native_header_has_visible_usable_scaled_controls_and_restores_owned_root(phase, key, value):
    observed = native_report()
    observed["native_header"][phase][key] = value
    code = "native_header_restore_failed" if phase == "restored" else "native_header_layout_failed"
    with pytest.raises(probe.ProbeError, match="^" + code + "$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("key,value,code", (("owned_root_only",False,"native_header_layout_failed"),
    ("owned_root_only",1,"native_header_layout_failed"),("restore_succeeded",False,"native_header_restore_failed"),
    ("restore_succeeded",1,"native_header_restore_failed")))
def test_native_header_requires_safe_root_scope_and_successful_restore(key, value, code):
    observed = native_report()
    observed["native_header"][key] = value
    with pytest.raises(probe.ProbeError, match=code):
        probe.validate_report(observed)


@pytest.mark.parametrize("group,key,value,code", (
    ("launcher","ready_button_kind","UIBarButtonItem","ready_launch_control_failed"),
    ("launcher","button_control_event","primary-action-triggered","explicit_launch_action_failed"),
    ("menu_lifetime","return_button_kind","UIBarButtonItem","settings_menu_lifetime_failed"),
    ("menu_lifetime","server_button_kind","UIView","settings_menu_lifetime_failed"),
    ("menu_lifetime","return_control_event","unknown","settings_menu_lifetime_failed"),
))
def test_native_actions_require_real_button_controls_and_touch_up_inside(group, key, value, code):
    observed = native_report()
    observed[group][key] = value
    with pytest.raises(probe.ProbeError, match=code):
        probe.validate_report(observed)


@pytest.mark.parametrize("key,value", (("schema",True),("ok",False),("ok",1),("transport","socket"),
    ("url","https://private.example/secret"),("http_status",503),("http_status",200.0),
    ("error_code","unknown private failure"),("body_is_json",False),("body_is_json",1),
    ("received_bytes",0),("received_bytes",16385),("received_bytes",True),
    ("worker_main_thread",True),("worker_main_thread",0),("ns_error_domain","private domain"),
    ("ns_error_domain",""),("ns_error_domain",0),("ns_error_domain",False),("ns_error_domain",{}),
    ("ns_error_code",False),("ns_error_code",1),("ns_error_code",0),("ns_error_code",""),
    ("ns_error_code",0.0),("ns_error_code",[])))
def test_native_preflight_requires_real_loopback_urlsession_json_success(key, value):
    observed = native_report()
    observed["server_status"]["http_readiness"][key] = value
    with pytest.raises(probe.ProbeError, match="^native_http_readiness_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("missing", (("ns_error_domain",), ("ns_error_code",), ("ns_error_domain", "ns_error_code")))
def test_native_preflight_requires_explicit_null_error_fields(missing):
    observed = native_report()
    for key in missing:
        del observed["server_status"]["http_readiness"][key]
    with pytest.raises(probe.ProbeError, match="^native_http_readiness_failed$"):
        probe.validate_report(observed)


def test_validated_native_layout_and_http_discard_unknown_payloads_and_preserve_null_error_fields():
    observed = native_report()
    observed["native_header"]["private_phase"] = {"secret":"never-copy"}
    observed["native_header"]["current"]["private_text"] = "never-copy"
    http = observed["server_status"]["http_readiness"]
    http["private_field"] = "never-copy"
    result = probe.validate_report(observed)
    assert result["native_header"]["ultrawide"]["button_min_font"] > result["native_header"]["wide"]["button_min_font"]
    assert result["server_status"]["http_readiness"]["url"] == "http://127.0.0.1:8080/client/playback"
    assert result["server_status"]["http_readiness"]["ns_error_domain"] is None
    assert result["server_status"]["http_readiness"]["ns_error_code"] is None
    assert "never-copy" not in json.dumps(result)


def test_http_error_projection_retains_only_present_explicit_null_fields():
    assert probe.http_readiness_observation({"ns_error_domain":None,"ns_error_code":None}) == {
        "ns_error_domain":None,"ns_error_code":None}
    assert probe.http_readiness_observation({}) == {}
    assert probe.http_readiness_observation({"ns_error_domain":"","ns_error_code":0}) == {}


def test_native_header_and_http_failure_projections_keep_only_known_bounded_fields():
    header = probe.header_observation({"restore_succeeded":False,"owned_root_only":1,
        "current":{"header_found":False,"actions_found":1,"root_width":True,"root_height":float("nan"),
                   "header_width":-1,"actions_width":0,"button_min_font":20000,"button_count":17,
                   "private_text":"never-copy"},"private_phase":{"secret":"never-copy"}})
    assert header == {"restore_succeeded":False,"current":{"header_found":False,"actions_width":0}}
    http = probe.http_readiness_observation({"schema":True,"ok":False,"transport":"NSURLSession",
        "url":"https://private.example/never-copy","http_status":503,"received_bytes":True,
        "body_is_json":False,"worker_main_thread":False,"error_code":"never-copy",
        "ns_error_domain":"never-copy","ns_error_code":True,"private_field":"never-copy"})
    assert http == {"ok":False,"transport":"NSURLSession","http_status":503,
                    "body_is_json":False,"worker_main_thread":False}
    assert "never-copy" not in json.dumps((header,http))


@pytest.mark.parametrize("source,filename", (("checkpoint","embedded-probe-checkpoint.json"),
    ("status","embedded-probe-status.json"),("report","embedded-probe.json")))
def test_native_header_checkpoints_project_before_cleanup(tmp_path, source, filename):
    documents = tmp_path / "Documents"
    documents.mkdir()
    observed = native_report() if source == "report" else {
        "schema":1,"stage":"native_header_checked","native_header":native_report()["native_header"],
        "server_status":{"phase":2,"http_readiness":native_report()["server_status"]["http_readiness"]}}
    observed["native_header"]["restore_succeeded"] = False
    observed["native_header"]["current"]["private_text"] = "never-copy"
    (documents / filename).write_text(json.dumps(observed))
    result = probe.failure_checkpoint(tmp_path)
    assert result["native_header"]["restore_succeeded"] is False
    if source == "checkpoint": assert result["stage"] == "native_header_checked"
    assert "never-copy" not in json.dumps(result)


def test_final_header_failure_audit_retains_safe_observations_and_rejects_before_rpc(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    observed = native_report()
    observed["native_header"]["wide"]["row_no_overlap"] = False
    observed["native_header"]["private_phase"] = {"secret":"never-copy"}
    with mock.patch.object(probe.sys,"platform","darwin"), mock.patch.object(probe,"_simctl",controller), \
            mock.patch(__name__+".native_report",return_value=observed), mock.patch.object(probe,"probe_rpcs") as rpc:
        result = probe.run_probe(app,tmp_path/"header-failure.json")
    assert result["error"] == "native_header_layout_failed"
    assert result["native_header_observed"]["wide"]["row_no_overlap"] is False
    assert result["native_http_readiness_observed"]["ok"] is True
    assert "never-copy" not in json.dumps(result)
    rpc.assert_not_called()


def test_waiting_header_failure_retains_only_safe_header_and_http_fields(app, tmp_path):
    controller = FakeSimctl(tmp_path/"container")
    def simctl(arguments, timeout):
        result = controller(arguments,timeout)
        if arguments[0] == "launch":
            documents = controller.container/"Documents"
            (documents/"embedded-probe.json").unlink()
            observed = {"server_status":{"phase":2,"error":None,
                            "http_readiness":native_report()["server_status"]["http_readiness"]},
                        "probe_error":"native_header_restore_failed","native_header":native_report()["native_header"]}
            observed["native_header"]["restore_succeeded"] = False
            observed["native_header"]["current"]["private_text"] = "never-copy"
            (documents/"embedded-probe-status.json").write_text(json.dumps(observed))
        return result
    with mock.patch.object(probe.sys,"platform","darwin"), mock.patch.object(probe,"_simctl",simctl):
        result = probe.run_probe(app,tmp_path/"header-wait-failure.json")
    assert result["error"] == "native_header_restore_failed"
    assert result["native_header_observed"]["restore_succeeded"] is False
    assert result["native_http_readiness_observed"]["transport"] == "NSURLSession"
    assert "never-copy" not in json.dumps(result)


def test_http_deadline_snapshot_does_not_retain_stale_success_error_label(tmp_path):
    documents = tmp_path/"Documents"
    documents.mkdir()
    waiting = documents/"embedded-probe-status.json"
    observed = {"server_status":{"phase":2,"error":None,
        "http_readiness":native_report()["server_status"]["http_readiness"]}}
    waiting.write_text(json.dumps(observed))
    def replace_with_failure(_seconds):
        observed["server_status"]["http_readiness"].update(ok=False,http_status=503,error_code="never-copy")
        waiting.write_text(json.dumps(observed))
    remaining = mock.Mock(side_effect=[1,1,1,1,probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time,"sleep",side_effect=replace_with_failure), pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path,remaining)
    assert caught.value.native_http["ok"] is False
    assert caught.value.native_http["http_status"] == 503
    assert "error_code" not in caught.value.native_http
    assert "never-copy" not in json.dumps(caught.value.native_http)


@pytest.mark.parametrize("field,value", [(key, value) for key in (
    "button_found","enabled_before","click_dispatched","completed","feedback_success",
    "pasteboard_matches","clipboard_seeded","clipboard_cleared") for value in (False,1)] + [
    ("timed_out",True),("timed_out",0),("text_bytes",0),("text_bytes",32769),
    ("text_bytes",True),("text_bytes",-1),("text_bytes","1024")])
def test_diagnostics_copy_requires_actual_success_and_owned_clipboard_cleanup(field, value):
    observed = native_report()
    observed["menu_lifetime"]["diagnostics_copy"][field] = value
    with pytest.raises(probe.ProbeError, match="^settings_diagnostics_copy_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("pass_index,field,value", [
    (index,key,value) for index in (0,1) for key in probe.ZIP_IMPORT_PASS_BOOL_FIELDS for value in (False,1)
] + [(index,"document_picker_mode",value) for index in (0,1) for value in (1,True,"0",None)])
def test_zip_import_requires_import_mode_and_each_actual_cancel_recovery_pass(pass_index, field, value):
    observed = native_report()
    observed["menu_lifetime"]["zip_import_picker"]["passes"][pass_index][field] = value
    with pytest.raises(probe.ProbeError, match="^settings_zip_import_picker_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("field,value", [("scope","livecontainer"),("cancel_trigger","user-tap"),
    ("timed_out",True),("timed_out",0),("observations",True),("observations",0),("observations",201),
    ("elapsed_seconds",True),("elapsed_seconds",float("nan")),("elapsed_seconds",61),
    ("passes",[]),("passes",[{}]),("passes",[{}, {}, {}]),("passes",None),
    *[(key,value) for key in probe.ZIP_IMPORT_SERVER_FLAGS for value in (False,1)]])
def test_zip_import_rejects_incomplete_reentry_and_missing_server_survival(field, value):
    observed = native_report()
    observed["menu_lifetime"]["zip_import_picker"][field] = value
    with pytest.raises(probe.ProbeError, match="^settings_zip_import_picker_failed$"):
        probe.validate_report(observed)


def test_zip_import_audit_contains_only_bounded_contract_metrics():
    observed = native_report()
    zipped = observed["menu_lifetime"]["zip_import_picker"]
    zipped.update(filename="DO-NOT-EXPORT",provider="DO-NOT-EXPORT")
    zipped["passes"][0]["url"] = "DO-NOT-EXPORT"
    result = probe.validate_report(observed)
    clean = result["menu_lifetime"]["zip_import_picker"]
    assert clean["scope"] == "stock-simulator" and clean["cancel_trigger"] == "delegate-callback"
    assert len(clean["passes"]) == 2 and clean["passes"][1]["button_restored"] is True
    assert "DO-NOT-EXPORT" not in json.dumps(result)
    assert probe.zip_import_observation({"timed_out":False,"observations":True,
        "elapsed_seconds":float("inf"),"passes":[{"document_picker_mode":True,"button_restored":1}]}) == {
            "timed_out":False,"passes":[{}]}


@pytest.mark.parametrize("source,filename", (("checkpoint","embedded-probe-checkpoint.json"),
    ("status","embedded-probe-status.json"),("report","embedded-probe.json")))
def test_zip_import_checkpoint_preserves_safe_cancel_evidence(tmp_path, source, filename):
    documents = tmp_path/"Documents"
    documents.mkdir()
    observed = native_report()
    zipped = observed["menu_lifetime"]["zip_import_picker"]
    zipped["passes"][1].update(button_restored=False,filename="DO-NOT-EXPORT")
    if source != "report":
        observed = {"schema":1,"stage":"settings_zip_import_cancelled","zip_import_picker":zipped,
                    "probe_error":"settings_zip_import_picker_failed"}
    (documents/filename).write_text(json.dumps(observed))
    clean = probe.failure_checkpoint(tmp_path)
    assert clean["zip_import_picker"]["passes"][1]["button_restored"] is False
    if source == "checkpoint":
        assert clean["stage"] == "settings_zip_import_cancelled"
    assert "DO-NOT-EXPORT" not in json.dumps(clean)


@pytest.mark.parametrize("field,value", [(key,value) for key in probe.ZIP_ROUNDTRIP_FLAGS for value in (False,1)] + [
    ("performed",False),("performed",1),("scope","livecontainer"),("selection_trigger","files-row-tap"),
    ("timed_out",True),("source_bytes",0),("copied_bytes",4095),("total_bytes",4097),("failed_files",1),
    ("imported_files",1),("exported_files",True),("source_sha256","not-a-hash"),("copied_sha256","b"*64),
    ("elapsed_seconds",121),("elapsed_seconds",float("nan")),("elapsed_seconds",True)])
def test_first_cold_run_requires_actual_zip_copy_and_host_roundtrip_evidence(field, value):
    observed = native_report()
    observed["menu_lifetime"]["zip_roundtrip"][field] = value
    with pytest.raises(probe.ProbeError, match="^settings_zip_roundtrip_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("language,run_index", [("en",1),("ja",2),("en",3),("ko",4)])
def test_roundtrip_is_required_once_and_later_runs_require_exact_skip_provenance(language, run_index):
    observed = native_report(language,run_index)
    assert probe.validate_report(observed)["menu_lifetime"]["zip_roundtrip"] == {
        "performed":False,"reason":"first-cold-run-only"}
    observed["menu_lifetime"]["zip_roundtrip"] = native_report()["menu_lifetime"]["zip_roundtrip"]
    with pytest.raises(probe.ProbeError, match="^settings_zip_roundtrip_failed$"):
        probe.validate_report(observed)
    first = native_report()
    first["menu_lifetime"]["zip_roundtrip"] = {"performed":False,"reason":"first-cold-run-only"}
    with pytest.raises(probe.ProbeError, match="^settings_zip_roundtrip_failed$"):
        probe.validate_report(first)


@pytest.mark.parametrize("field,value", [(key,value) for key in probe.LAUNCH_SETTINGS_FLAGS for value in (False,1)])
def test_launch_stays_cold_until_real_settings_flush_releases(field, value):
    observed = native_report()
    observed["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="^launch_settings_barrier_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("trigger", [None,"submit-button","requestSubmit",1])
def test_language_cycle_requires_change_autosave_instead_of_explicit_submit(trigger):
    observed = native_report()
    observed["language_save"]["save_trigger"] = trigger
    with pytest.raises(probe.ProbeError, match="^language_save_failed$"):
        probe.validate_report(observed)


def test_roundtrip_audit_keeps_full_hash_and_byte_evidence_without_paths():
    observed = native_report()
    observed["menu_lifetime"]["zip_roundtrip"].update(source_path="DO-NOT-EXPORT",owned_path="DO-NOT-EXPORT")
    checked = probe.validate_report(observed)["menu_lifetime"]["zip_roundtrip"]
    assert checked["source_bytes"] == checked["copied_bytes"] == checked["total_bytes"] == 4096
    assert checked["source_sha256"] == checked["copied_sha256"] == "a"*64
    assert "DO-NOT-EXPORT" not in json.dumps(checked)
    assert probe.zip_roundtrip_observation({"source_path":"DO-NOT-EXPORT","source_bytes":True,
        "source_sha256":"invalid","performed":True}) == {"performed":True}


def test_diagnostics_copy_audit_discards_all_copied_text_and_keeps_only_flags_and_size():
    observed = native_report()
    observed["menu_lifetime"]["diagnostics_copy"].update(
        clipboard_text="DONT-COPY",diagnostic_text="DONT-COPY",text_bytes=32768)
    result = probe.validate_report(observed)
    copied = result["menu_lifetime"]["diagnostics_copy"]
    assert copied["text_bytes"] == 32768 and copied["pasteboard_matches"] is True
    assert copied["clipboard_seeded"] is True and copied["clipboard_cleared"] is True
    assert "DONT-COPY" not in json.dumps(result)
    assert probe.diagnostics_copy_observation({"completed":1,"timed_out":False,
        "text_bytes":True,"clipboard_text":"DONT-COPY"}) == {"timed_out":False}


@pytest.mark.parametrize("source,filename", (("checkpoint","embedded-probe-checkpoint.json"),
    ("status","embedded-probe-status.json"),("report","embedded-probe.json")))
def test_diagnostics_copy_checkpoint_projection_never_exports_clipboard_contents(tmp_path, source, filename):
    documents = tmp_path/"Documents"
    documents.mkdir()
    copied = native_report()["menu_lifetime"]["diagnostics_copy"]
    copied.update(completed=False,clipboard_text="DONT-COPY")
    observed = native_report() if source == "report" else {
        "schema":1,"stage":"settings_diagnostics_copied","diagnostics_copy":copied,
        "server_status":{"phase":4,"error":None}}
    if source == "report": observed["menu_lifetime"]["diagnostics_copy"] = copied
    (documents/filename).write_text(json.dumps(observed))
    result = probe.failure_checkpoint(tmp_path)
    assert result["diagnostics_copy"]["completed"] is False
    if source == "checkpoint": assert result["stage"] == "settings_diagnostics_copied"
    assert "DONT-COPY" not in json.dumps(result)


def test_diagnostics_copy_final_failure_audit_retains_safe_actual_flow_flags(app, tmp_path):
    controller = FakeSimctl(tmp_path/"container")
    observed = native_report()
    observed["menu_lifetime"]["diagnostics_copy"].update(pasteboard_matches=False,clipboard_text="DONT-COPY")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller), \
            mock.patch(__name__+".native_report",return_value=observed),mock.patch.object(probe,"probe_rpcs") as rpc:
        result = probe.run_probe(app,tmp_path/"copy-failure.json")
    assert result["error"] == "settings_diagnostics_copy_failed"
    assert result["native_diagnostics_copy_observed"]["pasteboard_matches"] is False
    assert result["native_checkpoint"]["diagnostics_copy"]["pasteboard_matches"] is False
    assert "DONT-COPY" not in json.dumps(result)
    rpc.assert_not_called()


def test_diagnostics_copy_waiting_failure_preserves_only_safe_size_and_flags(app, tmp_path):
    controller = FakeSimctl(tmp_path/"container")
    def simctl(arguments,timeout):
        result = controller(arguments,timeout)
        if arguments[0] == "launch":
            documents = controller.container/"Documents"
            (documents/"embedded-probe.json").unlink()
            copied = native_report()["menu_lifetime"]["diagnostics_copy"]
            copied.update(timed_out=True,completed=False,clipboard_text="DONT-COPY")
            observed = {"server_status":{"phase":4,"error":None},
                "probe_error":"settings_diagnostics_copy_failed","diagnostics_copy":copied}
            (documents/"embedded-probe-status.json").write_text(json.dumps(observed))
        return result
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",simctl):
        result = probe.run_probe(app,tmp_path/"copy-wait-failure.json")
    assert result["error"] == "settings_diagnostics_copy_failed"
    assert result["native_diagnostics_copy_observed"]["timed_out"] is True
    assert result["native_diagnostics_copy_observed"]["completed"] is False
    assert "DONT-COPY" not in json.dumps(result)


def test_diagnostics_copy_deadline_snapshot_preserves_only_latest_safe_flags(tmp_path):
    documents = tmp_path/"Documents"
    documents.mkdir()
    waiting = documents/"embedded-probe-status.json"
    copied = native_report()["menu_lifetime"]["diagnostics_copy"]
    observed = {"server_status":{"phase":4,"error":None},"diagnostics_copy":copied}
    waiting.write_text(json.dumps(observed))
    def replace_with_pending(_seconds):
        copied.update(completed=False,clipboard_cleared=False,clipboard_text="DONT-COPY")
        waiting.write_text(json.dumps(observed))
    remaining = mock.Mock(side_effect=[1,1,1,1,probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time,"sleep",side_effect=replace_with_pending), pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path,remaining)
    assert caught.value.native_diagnostics_copy["completed"] is False
    assert caught.value.native_diagnostics_copy["clipboard_cleared"] is False
    assert "DONT-COPY" not in json.dumps(caught.value.native_diagnostics_copy)


@pytest.mark.parametrize("field,value,code", (
    ("apis_registered",False,"octo_budget_registration_failed"),
    ("apis_registered",1,"octo_budget_registration_failed"),
    ("prepared_without_managed_callbacks",False,"octo_budget_preinit_failed"),
    ("prepared_without_managed_callbacks",1,"octo_budget_preinit_failed"),
    ("during_original_seconds",330,"octo_budget_original_failed"),
    ("during_original_seconds",True,"octo_budget_original_failed"),
    ("during_original_configured",True,"octo_budget_original_failed"),
    ("during_original_configured",0,"octo_budget_original_failed"),
    ("first_queued_seconds",10,"octo_budget_queued_work_failed"),
    ("last_snapshot",10,"octo_budget_queued_work_failed"),
    ("first_queued_seconds",float("inf"),"octo_budget_queued_work_failed"),
    ("configured_before_first_queued_work",False,"octo_budget_queued_work_failed"),
    ("queued_work_on_main_thread",False,"octo_budget_queued_work_failed"),
    ("class_initialized",False,"octo_budget_queued_work_failed"),
    ("initializations",2,"octo_budget_queued_work_failed"),
    ("reads",1,"octo_budget_queued_work_failed"),("writes",0,"octo_budget_queued_work_failed"),
    ("writes",True,"octo_budget_queued_work_failed"),
    ("first_queued_snapshot_count",2,"octo_budget_queued_work_failed"),
    ("writes_before_initialization",1,"octo_budget_queued_work_failed"),
    ("writes_before_initialization",False,"octo_budget_queued_work_failed"),
))
def test_octo_budget_requires_prepare_only_original_default_and_configured_first_queued_work(field, value, code):
    report = native_report()
    report["octo_budget_probe"][field] = value
    with pytest.raises(probe.ProbeError,match="^"+code+"$"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("schema",True),("status","prepared"),("prepared",1),
    ("configured",False),("original_seconds",True),("original_seconds",330),
    ("effective_seconds",10),("effective_seconds",float("nan")),
    ("cache_wait_seconds",True),("cache_wait_seconds",299),("scope","global"),("error","never-export")))
def test_octo_budget_native_policy_status_requires_exact_configured_success(field, value):
    report = native_report()
    report["server_status"]["octo_budget"][field] = value
    with pytest.raises(probe.ProbeError,match="^octo_budget_queued_work_failed$"):
        probe.validate_report(report)


def test_octo_budget_requires_explicit_null_error_key_and_preserves_exact_float_seconds():
    report = native_report()
    del report["server_status"]["octo_budget"]["error"]
    with pytest.raises(probe.ProbeError,match="^octo_budget_queued_work_failed$"):
        probe.validate_report(report)
    report["server_status"]["octo_budget"]["error"] = None
    for key in ("original_seconds","effective_seconds","cache_wait_seconds"):
        report["server_status"]["octo_budget"][key] = float(report["server_status"]["octo_budget"][key])
    for key in ("during_original_seconds","first_queued_seconds","last_snapshot"):
        report["octo_budget_probe"][key] = float(report["octo_budget_probe"][key])
    assert probe.validate_report(report)["server_status"]["octo_budget"]["effective_seconds"] == 330.0


def test_octo_budget_projects_only_known_partial_policy_and_probe_scalars():
    report = native_report()
    report["server_status"]["octo_budget"].update(private_data="never-export")
    report["octo_budget_probe"].update(private_data="never-export")
    checked = probe.validate_report(report)
    assert "never-export" not in json.dumps(checked)
    assert probe.octo_budget_observation({"schema":True,"status":"never-export","scope":"never-export",
        "error":"never-export","prepared":1,"configured":False,"original_seconds":True,
        "effective_seconds":3601,"cache_wait_seconds":float("inf")}) == {"configured":False}
    assert probe.octo_budget_probe_observation({"reads":True,"writes":17,"initializations":-1,
        "first_queued_seconds":True,"during_original_seconds":-1,"last_snapshot":float("nan"),
        "class_initialized":False,"private":"never-export"}) == {"class_initialized":False}
    assert probe.octo_budget_observation({"status":"failed","error":"readback_mismatch"}) == {
        "status":"failed","error":"readback_mismatch"}
    assert probe.octo_budget_observation({"status":"idle","error":None}) == {"status":"idle","error":None}


@pytest.mark.parametrize("source,filename,stage", (
    ("checkpoint","embedded-probe-checkpoint.json","octo_budget_original_observed"),
    ("status","embedded-probe-status.json","octo_budget_first_queued_work_observed"),
    ("report","embedded-probe.json","octo_budget_first_queued_work_observed")))
def test_octo_budget_failure_checkpoint_projects_partial_evidence_without_errors(tmp_path, source, filename, stage):
    documents = tmp_path/"Documents"
    documents.mkdir()
    report = native_report()
    budget = report["server_status"]["octo_budget"]
    budget.update(status="prepared",configured=False,effective_seconds=10,error="never-export")
    report["octo_budget_probe"].update(first_queued_seconds=10,private="never-export")
    observed = report if source != "checkpoint" else {"schema":1,"stage":stage,
        "octo_budget":budget,"octo_budget_probe":report["octo_budget_probe"]}
    (documents/filename).write_text(json.dumps(observed))
    result = probe.failure_checkpoint(tmp_path)
    assert result["octo_budget"]["configured"] is False
    assert result["octo_budget_probe"]["first_queued_seconds"] == 10
    assert "error" not in result["octo_budget"]
    if source == "checkpoint":
        assert result["stage"] == stage
    assert "never-export" not in json.dumps(result)


def test_octo_budget_final_failure_audit_keeps_safe_policy_and_snapshot_evidence(app, tmp_path):
    controller = FakeSimctl(tmp_path/"budget-container")
    report = native_report()
    report["octo_budget_probe"].update(first_queued_seconds=10,private="never-export")
    report["server_status"]["octo_budget"].update(error="never-export")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller), \
            mock.patch(__name__+".native_report",return_value=report),mock.patch.object(probe,"probe_rpcs") as rpc:
        result = probe.run_probe(app,tmp_path/"budget-failure.json")
    assert result["error"] == "octo_budget_queued_work_failed"
    assert result["native_octo_budget_probe_observed"]["first_queued_seconds"] == 10
    assert result["native_octo_budget_observed"]["configured"] is True
    assert "error" not in result["native_octo_budget_observed"]
    assert "never-export" not in json.dumps(result)
    rpc.assert_not_called()


def test_octo_budget_waiting_failure_audit_keeps_only_partial_public_scalars(app, tmp_path):
    controller = FakeSimctl(tmp_path/"budget-wait-container")
    def command(arguments,timeout):
        result = controller(arguments,timeout)
        if arguments[0] == "launch":
            documents = controller.container/"Documents"
            (documents/"embedded-probe.json").unlink()
            observed = {"server_status":{"phase":2,"error":None,"octo_budget":{
                "status":"prepared","prepared":True,"configured":False,"error":"never-export"}},
                "octo_budget_probe":{"prepared_without_managed_callbacks":False,"reads":0,"private":"never-export"},
                "probe_error":"octo_budget_preinit_failed"}
            (documents/"embedded-probe-status.json").write_text(json.dumps(observed))
        return result
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",command):
        result = probe.run_probe(app,tmp_path/"budget-wait-failure.json")
    assert result["error"] == "octo_budget_preinit_failed"
    assert result["native_octo_budget_probe_observed"]["reads"] == 0
    assert result["native_octo_budget_observed"]["configured"] is False
    assert "never-export" not in json.dumps(result)


@pytest.mark.parametrize("safe_partial", (True,False))
def test_octo_budget_deadline_retains_only_latest_partial_public_observation(tmp_path, safe_partial):
    documents = tmp_path/"Documents"
    documents.mkdir()
    waiting = documents/"embedded-probe-status.json"
    report = native_report()
    waiting.write_text(json.dumps(report))
    def replace_with_partial(_seconds):
        report["server_status"]["octo_budget"] = {"error":"never-export"}
        report["octo_budget_probe"] = {"private":"never-export"}
        if safe_partial:
            report["server_status"]["octo_budget"]["configured"] = False
            report["octo_budget_probe"]["first_queued_seconds"] = 10
        waiting.write_text(json.dumps(report))
    remaining = mock.Mock(side_effect=[1,1,1,1,probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time,"sleep",side_effect=replace_with_partial),pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path,remaining)
    assert getattr(caught.value,"native_octo_budget",{}) == ({"configured":False} if safe_partial else {})
    assert getattr(caught.value,"native_octo_budget_probe",{}) == ({"first_queued_seconds":10} if safe_partial else {})


@pytest.mark.parametrize("phase,field,replacement", (
    ("before_capture", "ready", True), ("before_capture", "original_calls", 0),
    ("before_capture", "field_creation_count", 2), ("before_capture", "returned_nil", True),
    ("before_launch", "returned_initialized_field", False), ("before_launch", "original_calls", 1),
    ("before_launch", "field_creation_count", 2), ("before_launch", "returned_same_field", False),
    ("during_init", "ready", True), ("during_init", "returned_nil", True),
    ("during_init", "returned_initialized_field", False), ("during_init", "original_calls", 2),
    ("during_init", "field_creation_count", 2), ("during_init", "returned_same_field", False),
    ("after_init", "ready", False), ("after_init", "returned_nil", True),
    ("after_init", "returned_initialized_field", False), ("after_init", "original_calls", 3),
    ("after_init", "original_calls", 5), ("after_init", "field_creation_count", 2),
    ("after_init", "returned_same_field", False),
    ("before_capture", "phase", True), ("before_launch", "original_calls", True),
    ("during_init", "field_creation_count", True), ("after_init", "original_calls", True),
    ("after_init", "field_creation_count", True), ("before_capture", "returned_nil", 0),
    ("during_init", "ready", 0), ("after_init", "ready", 1), ("after_init", "returned_same_field", 1),
))
def test_keyboard_getter_stays_available_and_reuses_one_precreated_field(phase, field, replacement):
    observed = native_report()
    observed["keyboard"][phase][field] = replacement
    with pytest.raises(probe.ProbeError, match="^keyboard_" + phase + "_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("phase,field,replacement", (
    ("before_capture", "installed", True), ("before_capture", "initialize_calls", 1),
    ("before_launch", "installed", True), ("before_launch", "reused_existing_calls", 1),
    ("during_init", "installed", False), ("during_init", "initialize_calls", 0),
    ("during_init", "original_initialize_calls", 1), ("during_init", "reused_existing_calls", 0),
    ("after_init", "installed", False), ("after_init", "original_initialize_calls", 1),
    ("after_init", "initialize_calls", 2), ("after_init", "reused_existing_calls", 2),
    ("after_init", "strategy", "unknown private strategy"), ("after_init", "installed", 1),
    ("after_init", "initialize_calls", True), ("before_capture", "original_initialize_calls", False),
))
def test_warm_keyboard_lifecycle_hooks_only_initialize_and_skips_duplicate_creation(phase, field, replacement):
    observed = native_report()
    observed["keyboard"][phase]["lifecycle"][field] = replacement
    with pytest.raises(probe.ProbeError, match="^keyboard_" + phase + "_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("field,replacement", (("installed",False),("installed",1),
    ("strategy","unrecognized"),("initialize_calls",0),("initialize_calls",True),
    ("original_initialize_calls",1),("reused_existing_calls",0),("reused_existing_calls",True)))
def test_final_native_lifecycle_must_confirm_warm_instance_reuse(field, replacement):
    observed = native_report()
    observed["server_status"]["keyboard_lifecycle"][field] = replacement
    with pytest.raises(probe.ProbeError, match="^keyboard_after_init_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("replacement", (False,1,None))
def test_final_native_keyboard_readiness_is_a_strict_true_boolean(replacement):
    observed = native_report()
    observed["server_status"]["keyboard_ready"] = replacement
    with pytest.raises(probe.ProbeError, match="^keyboard_after_init_failed$"):
        probe.validate_report(observed)


def test_keyboard_phase_evidence_is_required_and_validated_output_drops_unknown_data():
    observed = native_report()
    del observed["keyboard"]["during_init"]
    with pytest.raises(probe.ProbeError, match="^keyboard_during_init_failed$"):
        probe.validate_report(observed)
    observed = native_report()
    observed["keyboard"]["private_phase"] = {"credentials":"must-not-export"}
    observed["keyboard"]["after_init"]["private_field"] = "must-not-export"
    observed["keyboard"]["after_init"]["lifecycle"]["private_field"] = "must-not-export"
    observed["server_status"]["keyboard_lifecycle"]["private_field"] = "must-not-export"
    result = probe.validate_report(observed)
    assert result["keyboard"]["during_init"]["ready"] is False
    assert result["keyboard"]["after_init"]["original_calls"] == 4
    assert result["keyboard"]["after_init"]["returned_same_field"] is True
    assert result["server_status"]["keyboard_lifecycle"]["strategy"] == "reuse-existing"
    assert result["server_status"]["keyboard_ready"] is True
    assert "must-not-export" not in json.dumps(result)


def test_keyboard_diagnostic_projection_keeps_only_strict_bounded_public_scalars():
    observed = probe.keyboard_observation({
        "before_capture":{"ready":False,"phase":True,"returned_nil":"private",
            "returned_initialized_field":True,"returned_same_field":1,"original_calls":17,
            "field_creation_count":-1,"private_field":"never-copy",
            "lifecycle":{"installed":False,"strategy":"reuse-existing","initialize_calls":0,
                "original_initialize_calls":False,"reused_existing_calls":17,"private_field":"never-copy"}},
        "before_launch":["private"],
        "during_init":{"phase":4,"original_calls":16,"field_creation_count":16,"ready":True},
        "after_init":{"phase":5,"original_calls":True,"field_creation_count":{},
                      "lifecycle":{"installed":True,"strategy":"private value","initialize_calls":1}},
        "private_phase":{"token":"never-copy"}})
    assert observed == {
        "before_capture":{"ready":False,"returned_initialized_field":True,
            "lifecycle":{"installed":False,"strategy":"reuse-existing","initialize_calls":0}},
        "during_init":{"phase":4,"original_calls":16,"field_creation_count":16,"ready":True},
        "after_init":{"lifecycle":{"installed":True,"initialize_calls":1}}}
    assert "private" not in json.dumps(observed) and "never-copy" not in json.dumps(observed)


@pytest.mark.parametrize("source,filename,stage", (
    ("checkpoint","embedded-probe-checkpoint.json","keyboard_before_capture_checked"),
    ("status","embedded-probe-status.json","keyboard_before_launch_checked"),
    ("report","embedded-probe.json","keyboard_after_init_checked"),
))
def test_keyboard_failure_checkpoint_is_projected_from_fixed_public_files(tmp_path, source, filename, stage):
    documents = tmp_path / "Documents"
    documents.mkdir()
    lifecycle = {"installed":False,"strategy":"reuse-existing","initialize_calls":0,
                 "original_initialize_calls":0,"reused_existing_calls":0,"private":"never-copy"}
    observed = native_report() if source == "report" else {
        "schema":1,"stage":stage,"keyboard_lifecycle":lifecycle,"keyboard_ready":False,
        "server_status":{"phase":2,"keyboard_lifecycle":lifecycle,"keyboard_ready":False},
        "keyboard":native_report()["keyboard"]}
    observed["keyboard"]["before_capture"]["field_creation_count"] = 2
    observed["keyboard"]["before_capture"]["lifecycle"]["private_field"] = "never-copy"
    observed["keyboard"]["private_phase"] = {"token":"never-copy"}
    (documents / filename).write_text(json.dumps(observed))
    result = probe.failure_checkpoint(tmp_path)
    assert result["keyboard"]["before_capture"]["field_creation_count"] == 2
    if source == "checkpoint":
        assert result["stage"] == stage and result["keyboard_lifecycle"]["installed"] is False
        assert result["keyboard_ready"] is False
    if source == "status":
        assert result["status_keyboard_lifecycle"]["installed"] is False and result["status_keyboard_ready"] is False
    if source == "report":
        assert result["report_valid"] is False
    assert "never-copy" not in json.dumps(result)


def test_final_keyboard_failure_preserves_only_bounded_observation_in_audit(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    observed = native_report()
    observed["keyboard"]["during_init"]["field_creation_count"] = 2
    observed["keyboard"]["during_init"]["lifecycle"]["private_field"] = "never-copy"
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch(__name__ + ".native_report", return_value=observed), \
            mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "keyboard_during_init_failed"
    assert result["native_keyboard_observed"]["during_init"]["field_creation_count"] == 2
    assert result["native_checkpoint"]["keyboard"]["during_init"]["field_creation_count"] == 2
    assert "never-copy" not in json.dumps(result)
    rpc.assert_not_called()


def test_waiting_keyboard_failure_keeps_known_scalars_and_cleans_owned_simulator(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    def simctl(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            documents = controller.container / "Documents"
            (documents / "embedded-probe.json").unlink()
            observed = {"server_status":{"phase":2,"error":None},
                        "probe_error":"keyboard_precreated_instance_not_reused",
                        "keyboard":native_report()["keyboard"]}
            observed["keyboard"]["before_capture"]["field_creation_count"] = 2
            observed["keyboard"]["before_capture"]["lifecycle"]["private_field"] = "never-copy"
            (documents / "embedded-probe-status.json").write_text(json.dumps(observed))
        return result
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", simctl), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "keyboard_precreated_instance_not_reused"
    assert result["native_keyboard_observed"]["before_capture"]["field_creation_count"] == 2
    assert result["cleanup"] == {"shutdown":True,"delete":True}
    assert "never-copy" not in json.dumps(result)
    rpc.assert_not_called()


def test_waiting_deadline_retains_only_previously_valid_keyboard_scalars(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    observed = {"server_status":{"phase":2,"error":None}, "keyboard":native_report()["keyboard"]}
    observed["keyboard"]["after_init"]["lifecycle"]["private_text"] = "never-copy"
    (documents / "embedded-probe-status.json").write_text(json.dumps(observed))
    remaining = mock.Mock(side_effect=[1, 1, probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.time, "sleep"), pytest.raises(probe.ProbeError) as caught:
        probe.wait_report(tmp_path, remaining)
    assert str(caught.value) == "probe_deadline_exceeded"
    assert caught.value.native_keyboard["during_init"]["ready"] is False
    assert "never-copy" not in json.dumps(caught.value.native_keyboard)


@pytest.mark.parametrize("path,replacement,code", [
    (("early_status", "id"), 2719, "early_status_correlation_failed"),
    (("early_status", "captured"), 0, "early_status_correlation_failed"),
    (("launcher", "server_ready_before_runtime"), False, "server_not_ready_before_capture"),
    (("launcher", "cold_attempts"), 2, "server_not_ready_before_capture"),
    (("launcher", "startup_evidence_version"), True, "server_not_ready_before_capture"),
    (("launcher", "premature_captured"), 0, "server_not_ready_before_capture"),
    (("launcher", "ready_captured"), 0, "unity_started_before_launch_button"),
    (("launcher", "ready_captured"), True, "unity_started_before_launch_button"),
    (("menu_lifetime", "dismissed"), False, "settings_menu_lifetime_failed"),
    (("menu_lifetime", "grpc_connected_after_close"), False, "settings_menu_lifetime_failed"),
    (("menu_lifetime", "host_status_after_close", "result", "running"), False, "server_stopped_after_menu_close"),
    (("menu_lifetime", "frame_width"), 250, "settings_menu_width_failed"),
    (("menu_lifetime", "dismiss_observation", "settings_view_attached"), True, "settings_menu_dismissal_evidence_failed"),
    (("menu_lifetime", "dismiss_observation", "game_window_key"), False, "settings_menu_dismissal_evidence_failed"),
    (("menu_lifetime", "dismiss_observation", "timed_out"), True, "settings_menu_dismissal_evidence_failed"),
    (("menu_lifetime", "web", "scale_2_present"), False, "settings_web_readiness_or_layout_failed"),
    (("menu_lifetime", "web", "buffer_4096_present"), False, "settings_web_readiness_or_layout_failed"),
    (("menu_lifetime", "web", "content_width"), 500, "settings_web_metrics_failed"),
])
def test_autostart_before_capture_and_menu_survival_are_required(path, replacement, code):
    observed = native_report()
    target = observed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(probe.ProbeError, match=code):
        probe.validate_report(observed)


def test_new_flow_audit_discards_unrecognized_native_values():
    observed = native_report()
    observed["server_status"]["client_data"]["unrecognized_payload"] = "must-not-export"
    observed["menu_lifetime"]["unrecognized_payload"] = "must-not-export"
    result = probe.validate_report(observed)
    assert result["launcher"]["server_ready_before_runtime"] is True
    assert result["early_status"]["id"] == 2718
    assert result["menu_lifetime"]["host_status_after_close"]["result"]["running"] is True
    assert "must-not-export" not in json.dumps(result)


@pytest.mark.parametrize("stage", ("settings_menu_requested", "settings_return_requested", "settings_return_observed",
                                  "settings_return_timeout", "settings_menu_dismissed"))
def test_owned_menu_checkpoints_are_projected_before_simulator_cleanup(tmp_path, stage):
    documents = tmp_path / "Documents"
    documents.mkdir()
    value = {"schema":1,"stage":stage,"original_called":1,"phase":4,
             "menu_close":{"presented_controller_remaining":True,"game_window_key":False,
                           "wait_seconds":0.6,"observations":7,"unknown":"must-not-export"}}
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps(value))
    observed = probe.failure_checkpoint(tmp_path)
    assert observed["stage"] == stage
    assert "checkpoint_read_error" not in observed
    assert observed["menu_close"] == {"presented_controller_remaining":True,"game_window_key":False,
                                      "wait_seconds":0.6,"observations":7}


def test_menu_dismissal_diagnostics_drop_nonboolean_or_unbounded_values():
    assert probe.menu_close_observation({"game_window_key":1,"settings_view_attached":"private",
        "presented_controller_remaining":True,"application_state":5,"wait_seconds":float("nan"),
        "observations":100000,"unknown":"private"}) == {"presented_controller_remaining":True}


def test_menu_timeout_distinguishes_transition_and_key_window_without_weakening_failure(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    detail = {"presented_controller_remaining":False,"settings_controller_still_presented":False,
              "settings_view_attached":False,"settings_is_being_dismissed":False,"game_window_key":False,
              "application_state":0,"observations":61,"wait_seconds":6.05,"timed_out":True,
              "unknown":"must-not-export"}
    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            documents = controller.container / "Documents"
            (documents / "embedded-probe.json").unlink()
            (documents / "embedded-probe-status.json").write_text(json.dumps({"schema":1,"original_called":1,
                "server_status":{"phase":4,"error":None},"probe_error":"settings_menu_not_dismissed","menu_close":detail}))
        return result
    with mock.patch.object(probe.sys,"platform","darwin"), mock.patch.object(probe,"_simctl",command), \
            mock.patch.object(probe,"probe_rpcs") as rpc:
        observed = probe.run_probe(app,tmp_path / "dismissal-timeout.json")
    assert observed["status"] == "FAIL" and observed["error"] == "settings_menu_not_dismissed"
    assert observed["native_menu_close_observed"]["presented_controller_remaining"] is False
    assert observed["native_menu_close_observed"]["game_window_key"] is False
    assert observed["cleanup"] == {"shutdown":True,"delete":True}
    assert "must-not-export" not in json.dumps(observed)
    rpc.assert_not_called()


def public_descriptor():
    file = descriptor_pb2.FileDescriptorProto(name="ios-probe-test.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    check = file.message_type.add(name="SystemCheckResponse")
    check.field.add(name="keepAliveTimeMilliseconds", number=3, type=5)
    public = file.message_type.add(name="UserPublic")
    public.field.add(name="serverUserId", number=1, type=9)
    public.field.add(name="publicUserId", number=2, type=9)
    login = file.message_type.add(name="LoginResponse")
    login.field.add(name="gameAuthToken", number=1, type=9)
    login.field.add(name="userPublic", number=2, type=11, type_name=".api.UserPublic")
    home = file.message_type.add(name="HomeResponse")
    home.field.add(name="currentMainAreaId", number=1, type=9)
    pack = file.message_type.add(name="MasterTagPack")
    pack.field.add(name="fileName", number=1, type=9)
    pack.field.add(name="fileSize", number=2, type=3)
    pack.field.add(name="downloadUrl", number=3, type=9)
    tag = file.message_type.add(name="MasterTag")
    tag.field.add(name="masterTagPacks", number=1, type=11, label=3, type_name=".api.MasterTagPack")
    tag.field.add(name="version", number=2, type=9)
    master = file.message_type.add(name="MasterResponse")
    master.field.add(name="masterTag", number=1, type=11, type_name=".api.MasterTag")
    for service, method, output in (("System", "Check", "SystemCheckResponse"),
                                    ("Auth", "Login", "LoginResponse"),
                                    ("Home", "Enter", "HomeResponse"),
                                    ("Master", "Get", "MasterResponse")):
        file.service.add(name=service).method.add(name=method, input_type=".api.Empty", output_type=".api." + output)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    return descriptors.SerializeToString()


@pytest.fixture
def app(tmp_path):
    app = tmp_path / "EmbeddedProbe.app"
    (app / "LocalServer").mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": probe.BUNDLE_ID,
                                                   "CFBundleSupportedPlatforms": ["iPhoneSimulator"]}))
    (app/"probe-language-canaries.json").write_bytes(language_canary_bytes())
    with ZipFile(app / "LocalServer/ServerData.zip", "w") as archive:
        # Match the distributed ServerData archive, independently of the
        # probe's lookup constant (installed core paths omit the data/ root).
        archive.writestr("data/protocol/idolypride-6.1.1.pb", public_descriptor())
        archive.writestr(MASTER_MEMBER, MASTER_BYTES)
        settings,original,_ = sdk_fixture()
        archive.writestr(SDK_SETTINGS_MEMBER,json.dumps(settings))
        archive.writestr(SDK_MANIFEST_MEMBER,original)
    return app


class FakeSimctl:
    """No subprocess or simulator access: only command ownership is modeled."""
    def __init__(self, container, *, failed_action=None, startup_failure=False):
        self.container = container
        self.container.mkdir()
        self.calls = []
        self.timeouts = []
        self.failed_action = failed_action
        self.startup_failure = startup_failure

    def __call__(self, arguments, timeout):
        self.calls.append(tuple(arguments))
        self.timeouts.append(timeout)
        assert 0 < timeout <= (180 if arguments[0] in ("install", "launch") else 60)
        action = arguments[0]
        if action == self.failed_action:
            raise probe.ProbeError("simctl_failed")
        if action == "list":
            assert arguments[1] in ("devicetypes", "runtimes")
            if arguments[1] == "devicetypes":
                return json.dumps({"devicetypes": [{"identifier": DEVICE}]}).encode()
            return json.dumps({"runtimes": [{"identifier": RUNTIME, "version": "18.5", "isAvailable": True}]}).encode()
        if action == "create":
            assert arguments[1].startswith("IdolyEmbeddedProbe-")
            return (CREATED + "\n").encode()
        assert arguments[1] == CREATED, "An existing simulator must never be targeted"
        if action == "get_app_container":
            assert arguments[2:] == [probe.BUNDLE_ID, "data"]
            return (str(self.container) + "\n").encode()
        if action == "launch":
            language = arguments[3].split("=",1)[1] if len(arguments) >= 4 else "ko"
            run_index = int(arguments[4].split("=",1)[1]) if len(arguments) >= 5 else None
            assert language in ("ko","en","ja")
            final_name,status_name,_checkpoint_name = probe.language_paths(language,run_index)
            documents = self.container / "Documents"
            documents.mkdir(exist_ok=True)
            if self.startup_failure:
                value = {"server_status": {"phase": 3, "error": "native-startup-fixture"}}
                (documents / status_name).write_text(json.dumps(value))
            else:
                (documents / final_name).write_text(json.dumps(native_report(language,run_index)))
        return b""


def test_linux_refuses_before_any_simulator_action_and_audits(app, tmp_path):
    audit = tmp_path / "nonmac.json"
    with mock.patch.object(probe.sys, "platform", "linux"), mock.patch.object(probe, "_simctl") as simctl:
        result = probe.run_probe(app, audit)
    simctl.assert_not_called()
    assert result["status"] == "FAIL"
    assert result["error"] == "macos_required_no_simulator_execution"
    assert json.loads(audit.read_text()) == result
    assert result["gameplay_tested"] is False


def test_existing_audit_is_preserved_without_touching_simulators(app, tmp_path):
    audit = tmp_path / "existing.json"
    audit.write_bytes(b"retain-existing-audit")
    with mock.patch.object(probe, "_simctl") as simctl, \
            pytest.raises(probe.ProbeError, match="fresh_audit_path_required"):
        probe.run_probe(app, audit)
    simctl.assert_not_called()
    assert audit.read_bytes() == b"retain-existing-audit"


def test_discovery_uses_available_runtime_and_compatible_device_types_only():
    older = "com.apple.CoreSimulator.SimDeviceType.iPhone-15-Pro"
    def command(arguments, _timeout):
        if arguments[1] == "devicetypes":
            return json.dumps({"devicetypes": [
                {"identifier": DEVICE, "minRuntimeVersion": 18 << 16},
                {"identifier": older, "minRuntimeVersion": 17 << 16}]}).encode()
        assert arguments == ["list", "runtimes", "--json"]
        return json.dumps({"runtimes": [
            {"identifier": RUNTIME, "version": "18.5", "isAvailable": False},
            {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-17-5", "version": "17.5", "isAvailable": True}]}).encode()
    with mock.patch.object(probe, "_simctl", command):
        selected = probe.discover(None, None, lambda: 5)
    assert selected == (older, "com.apple.CoreSimulator.SimRuntime.iOS-17-5")


def test_modern_xcode_type_catalog_over_report_bound_still_discovers_device():
    catalog = json.dumps({"devicetypes": [{"identifier": DEVICE, "model_metadata": "x" * 70000}]}).encode()
    assert probe.MAX_JSON < len(catalog) < probe.MAX_COMMAND_OUTPUT
    runtimes = json.dumps({"runtimes": [{"identifier": RUNTIME, "version": "18.5", "isAvailable": True}]}).encode()
    with mock.patch.object(probe, "_simctl", side_effect=[catalog, runtimes]):
        assert probe.discover(None, None, lambda: 5) == (DEVICE, RUNTIME)
    # Native reports retain the smaller, independent bound.
    with pytest.raises(probe.ProbeError, match="json_size_bound"):
        probe.parse_json(catalog)


def test_fresh_simulator_is_only_mutation_target_and_cleanup_runs(app, tmp_path):
    controller = FakeSimctl(tmp_path / "fresh-container")
    audit = tmp_path / "simulated-controller-test.json"
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch.object(probe.socket, "create_connection") as socket_call, \
            mock.patch.object(probe, "probe_rpcs", return_value=[{"path": path} for path in probe.RPC_PATHS]), \
            mock.patch.object(probe, "probe_master_file", return_value=master_file_report()), \
            mock.patch.object(probe, "probe_sdk_resource", return_value=sdk_resource_report()):
        result = probe.run_probe(app, audit)
    assert result["status"] == "PASS"
    assert result["fresh_local_state_before_launch"] is True
    assert result["native_probe"]["launcher"]["ready_original_called"] == 0
    assert result["native_probe"]["launcher"]["button_dispatch_count"] == 1
    assert result["native_probe"]["server_status"]["launcher_visible"] is False
    assert controller.calls[-2:] == [("shutdown", CREATED), ("delete", CREATED)]
    assert [call[0] for call in controller.calls] == ["list", "list", "create", "boot", "bootstatus", "install",
                                                    "get_app_container", "launch", "terminate", "launch", "terminate", "launch",
                                                    "terminate", "launch", "terminate", "launch", "shutdown", "delete"]
    socket_call.assert_called_once()
    assert socket_call.call_args.args[0] == ("127.0.0.1", 8080)
    assert 60 < controller.timeouts[7] <= 180  # Cold UIKit/WK startup has its own bounded budget.
    assert audit.stat().st_size < probe.MAX_JSON
    assert audit.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failed_action", ("boot", "install", "launch"))
def test_stage_failures_clean_up_only_created_uuid(app, tmp_path, failed_action):
    controller = FakeSimctl(tmp_path / "container", failed_action=failed_action)
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", controller):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "FAIL"
    assert controller.calls[-2:] == [("shutdown", CREATED), ("delete", CREATED)]
    assert result["cleanup"] == {"shutdown": True, "delete": True}


def test_launch_budget_remains_clamped_to_original_overall_deadline(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    clock = {"now": 0.0}

    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "install":
            clock["now"] = 50.0
        return result

    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe.time, "monotonic", side_effect=lambda: clock["now"]), \
            mock.patch.object(probe, "_simctl", command), \
            mock.patch.object(probe.socket, "create_connection"), \
            mock.patch.object(probe, "probe_rpcs", return_value=[]), \
            mock.patch.object(probe, "probe_master_file", return_value=master_file_report()), \
            mock.patch.object(probe, "probe_sdk_resource", return_value=sdk_resource_report()):
        result = probe.run_probe(app, tmp_path / "audit.json", timeout=90)
    assert result["status"] == "PASS"
    assert controller.timeouts[5] == 90.0
    assert controller.timeouts[7] == 40.0


@pytest.mark.parametrize("action", ("install", "launch"))
@pytest.mark.parametrize("timed_out", (False, True))
def test_probe_install_launch_failure_keeps_fixed_code_and_bounded_cli_context(action, timed_out):
    arguments = [action, CREATED, "do-not-copy-command-arguments"]
    # Include invalid UTF-8 and escaping-heavy text to bound serialized JSON,
    # rather than assuming a character bound is also an audit-size bound.
    stdout = b"public-probe-output\n" + b"\xff\x00" * 10000
    stderr = b"public-probe-error\n" + "\u2000".encode() * 10000
    if timed_out:
        effect = probe.subprocess.TimeoutExpired("not copied", 180, output=stdout, stderr=stderr)
        command = mock.Mock(side_effect=effect)
    else:
        command = mock.Mock(return_value=probe.subprocess.CompletedProcess([], 1, stdout, stderr))
    with mock.patch.object(probe.subprocess, "run", command), pytest.raises(probe.ProbeError) as raised:
        probe._simctl(arguments, 180)
    assert str(raised.value) == ("simctl_timeout" if timed_out else "simctl_failed")
    detail = raised.value.tool_detail
    assert detail["action"] == action
    assert detail["stdout"].startswith("public-probe-output\n")
    assert detail["stderr"].startswith("public-probe-error\n")
    assert detail["stdout_truncated"] is True and detail["stderr_truncated"] is True
    encoded = json.dumps(detail, ensure_ascii=True).encode()
    assert len(encoded) <= probe.MAX_TOOL_DETAIL
    assert b"do-not-copy-command-arguments" not in encoded


@pytest.mark.parametrize("action", ("list", "create", "boot", "get_app_container", "shutdown", "delete"))
def test_other_simulator_commands_do_not_contribute_host_cli_context(action):
    result = probe.subprocess.CompletedProcess([], 1, b"do not retain", b"private unrelated host text")
    with mock.patch.object(probe.subprocess, "run", return_value=result), \
            pytest.raises(probe.ProbeError, match="^simctl_failed$") as raised:
        probe._simctl([action, CREATED], 30)
    assert not hasattr(raised.value, "tool_detail")


def test_compact_audit_preserves_every_nested_value_under_unchanged_encoded_bound(tmp_path):
    report = {"schema":1,"status":"PASS","reports":[{"run_index":run_index,"checks":[
        {"kind":"bounded-evidence","ok":True,"counter":index} for index in range(200)]} for run_index in range(5)]}
    assert probe.MAX_JSON == 64*1024
    assert len(json.dumps(report,indent=2,sort_keys=True).encode()) > probe.MAX_JSON
    path = tmp_path/"compact-audit.json"
    probe.write_audit(path,report)
    raw = path.read_bytes()
    assert len(raw) <= probe.MAX_JSON
    assert raw == (json.dumps(report,separators=(",", ":"),sort_keys=True,allow_nan=False)+"\n").encode()
    assert json.loads(raw) == report


def test_compact_audit_rejects_actual_oversized_payload_before_creating_output(tmp_path):
    path = tmp_path/"oversized-audit.json"
    with pytest.raises(probe.ProbeError,match="^audit_size_bound$"):
        probe.write_audit(path,{"data":"x"*probe.MAX_JSON})
    assert not path.exists()


def test_launch_ack_timeout_accepts_only_full_native_and_rpc_success_without_relaunch(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")

    def command(arguments, timeout):
        if arguments[0] == "launch":
            controller(arguments, timeout)
            raise probe._simctl_error("simctl_timeout", arguments, b"probe-start-output", b"probe-start-error")
        return controller(arguments, timeout)

    rows = [{"path": path} for path in probe.RPC_PATHS]
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", command), \
            mock.patch.object(probe.socket, "create_connection") as listener, \
            mock.patch.object(probe, "probe_rpcs", return_value=rows) as rpc, \
            mock.patch.object(probe, "probe_master_file", return_value=master_file_report()) as master, \
            mock.patch.object(probe, "probe_sdk_resource", return_value=sdk_resource_report()) as sdk:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "PASS"
    assert result["launch_ack_timeout"] is True
    assert result["launch_ack_diagnostic"] == {"action": "launch", "stdout": "probe-start-output",
        "stderr": "probe-start-error", "stdout_truncated": False, "stderr_truncated": False}
    assert result["launch_ack_checkpoint"]["report_valid"] is True
    assert result["native_probe"]["launcher"]["button_dispatch_count"] == 1
    assert result["rpcs"] == rows
    listener.assert_called_once()
    rpc.assert_called_once()
    master.assert_called_once()
    sdk.assert_called_once()
    assert result["master_file"] == master_file_report()
    assert result["sdk_resource"] == sdk_resource_report()
    assert [call[0] for call in controller.calls].count("launch") == 5
    assert [call[3] for call in controller.calls if call[0] == "launch"] == [
        "--idoly-probe-language=ko","--idoly-probe-language=en","--idoly-probe-language=ja",
        "--idoly-probe-language=en","--idoly-probe-language=ko"]
    assert result["cleanup"] == {"shutdown": True, "delete": True}
    assert controller.calls[-2:] == [("shutdown", CREATED), ("delete", CREATED)]


def test_launch_ack_timeout_without_report_still_expires_under_original_deadline(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    clock = {"now": 0.0}

    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            (controller.container / "Documents/embedded-probe.json").unlink()
            clock["now"] = 90.0
            raise probe._simctl_error("simctl_timeout", arguments)
        return result

    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe.time, "monotonic", side_effect=lambda: clock["now"]), \
            mock.patch.object(probe, "_simctl", command), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json", timeout=90)
    assert result["status"] == "FAIL"
    assert result["error"] == "probe_deadline_exceeded"
    assert result["failed_stage"] == "startup_gate_report"
    assert result["launch_ack_timeout"] is True
    assert result["native_checkpoint"]["report_available"] is False
    assert [call[0] for call in controller.calls].count("launch") == 1
    assert result["cleanup"] == {"shutdown": True, "delete": True}
    rpc.assert_not_called()


def test_launch_os_rejection_is_still_fatal_even_if_a_report_exists(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")

    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch":
            raise probe._simctl_error("simctl_failed", arguments, stderr=b"public install rejection")
        return result

    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", command), \
            mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "FAIL"
    assert result["error"] == "simctl_failed" and result["failed_stage"] == "app_launch"
    assert result["launch_ack_timeout"] is False
    assert result["native_checkpoint"]["report_valid"] is True
    assert result["simctl_failure"]["stderr"] == "public install rejection"
    rpc.assert_not_called()


def test_startup_failure_is_immediate_and_still_deletes_simulator(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container", startup_failure=True)
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "native_startup_failed"
    assert result["native_startup_error"] == "native-startup-fixture"
    assert result["failed_stage"] == "startup_gate_report"
    assert result["native_checkpoint"]["status_phase"] == 3
    assert result["cleanup"]["delete"] is True
    rpc.assert_not_called()


def test_shutdown_failure_does_not_skip_delete_or_claim_success(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container", failed_action="shutdown")
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch.object(probe.socket, "create_connection"), \
            mock.patch.object(probe, "probe_rpcs", return_value=[]), \
            mock.patch.object(probe, "probe_master_file", return_value=master_file_report()), \
            mock.patch.object(probe, "probe_sdk_resource", return_value=sdk_resource_report()):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "FAIL" and result["cleanup_complete"] is False
    assert controller.calls[-1] == ("delete", CREATED)
    assert result["cleanup"]["delete"] is True
    assert result["native_checkpoint"]["report_valid"] is True


def test_existing_database_in_new_container_is_rejected_before_launch(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    state = controller.container / "Library/Application Support/IdolyPrideLocal/media-state.db"
    state.parent.mkdir(parents=True)
    state.write_bytes(b"test-only-preexisting-state")
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", controller):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "preexisting_probe_state_rejected"
    assert "launch" not in [call[0] for call in controller.calls]
    assert state.read_bytes() == b"test-only-preexisting-state"


def test_preexisting_checkpoint_is_rejected_before_launch_or_native_observation(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    checkpoint = controller.container / "Documents/embedded-probe-checkpoint.json"
    checkpoint.parent.mkdir()
    checkpoint.write_text('{"schema":1,"stage":"report_written"}')
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", controller):
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "preexisting_probe_state_rejected"
    assert "launch" not in [call[0] for call in controller.calls]
    assert result["native_checkpoint"] == {"stage": "not_observed", "container_available": False}


def test_failure_checkpoint_projects_only_fixed_native_stages_and_scalar_gate_fields(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps({
        "schema": 1, "stage": "crypto_received", "phase": 4, "original_called": 1,
        "application_state": 0, "launch_requested": True, "launch_prepared": True,
        "launcher_visible": False, "private_text": "must not retain checkpoint payload"}))
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "original_called": 0, "server_status": {"phase": 2, "launch_requested": False,
        "error": "must not retain raw server error"}, "probe_error": "must not retain unknown text"}))
    raw_report = native_report()
    raw_report["unknown_private_text"] = "must not retain report payload"
    (documents / "embedded-probe.json").write_text(json.dumps(raw_report))
    result = probe.failure_checkpoint(tmp_path)
    assert result["stage"] == "crypto_received" and result["phase"] == 4
    assert result["original_called"] == 1 and result["application_state"] == 0
    assert result["status_phase"] == 2 and result["status_original_called"] == 0
    assert result["report_phase"] == 4 and result["report_original_called"] == 1
    assert result["report_valid"] is True
    assert all(type(value) in (str, int, bool, float, type(None))
               for key, value in result.items() if key not in (
                   "keyboard", "report_keyboard_lifecycle", "native_header", "report_http_readiness", "diagnostics_copy",
                   "octo_budget", "octo_budget_probe", "language_observation", "server_gate", "settings_web", "zip_import_picker", "zip_roundtrip", "account_management", "official_prompt"))
    assert result["account_management"] == probe.account_management_observation(raw_report["menu_lifetime"]["account_management"])
    assert result["keyboard"] == raw_report["keyboard"]
    assert result["report_keyboard_lifecycle"] == raw_report["server_status"]["keyboard_lifecycle"]
    assert result["native_header"] == raw_report["native_header"]
    assert result["report_http_readiness"] == raw_report["server_status"]["http_readiness"]
    assert result["diagnostics_copy"] == raw_report["menu_lifetime"]["diagnostics_copy"]
    assert result["zip_import_picker"] == raw_report["menu_lifetime"]["zip_import_picker"]
    assert result["zip_roundtrip"] == raw_report["menu_lifetime"]["zip_roundtrip"]
    assert result["octo_budget"] == raw_report["server_status"]["octo_budget"]
    assert result["octo_budget_probe"] == raw_report["octo_budget_probe"]
    assert "must not retain" not in json.dumps(result)


@pytest.mark.parametrize("stage", ("private arbitrary message", ["status_received"], None))
def test_failure_checkpoint_rejects_unknown_or_nonscalar_stages(tmp_path, stage):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps({
        "schema": 1, "stage": stage, "phase": 4, "private": "discard"}))
    result = probe.failure_checkpoint(tmp_path)
    assert result["stage"] == "not_observed"
    assert result["checkpoint_read_error"] == "invalid_checkpoint_stage"
    assert "phase" not in result
    assert "private" not in json.dumps(result)


def test_failure_checkpoint_drops_bad_scalar_types_and_keeps_read_errors_public(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-checkpoint.json").write_text(json.dumps({
        "schema": 1, "stage": "status_received", "phase": True, "original_called": 9999,
        "application_state": 3, "launch_requested": 1, "launch_prepared": "private text"}))
    (documents / "embedded-probe-status.json").write_text("invalid private JSON text")
    outside = tmp_path / "unrelated-private-report.json"
    outside.write_text('{"private":"never follow"}')
    (documents / "embedded-probe.json").symlink_to(outside)
    result = probe.failure_checkpoint(tmp_path)
    assert result["stage"] == "status_received"
    assert not {"phase", "original_called", "application_state", "launch_requested", "launch_prepared"} & result.keys()
    assert result["status_read_error"] == "invalid_json"
    assert result["report_read_error"] == "invalid_bounded_file"
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("field,value", (("original_called", True), ("original_called", 2),
                                          ("main_thread", False), ("application_argument_matches", False),
                                          ("command_completion_main_thread", False)))
def test_gate_counters_and_main_thread_are_strict(field, value):
    report = native_report()
    report[field] = value
    with pytest.raises(probe.ProbeError, match="unity_original_gate_failed"):
        probe.validate_report(report)


def test_port_crypto_and_native_readiness_are_not_inferred():
    for category, key, bad in (("ports", "grpc", 50052), ("ports", "assets_connect", False),
                               ("commoncrypto", "nist_aes128_cbc", False),
                               ("server_status", "phase", 2), ("server_status", "captured", True)):
        report = native_report()
        report[category][key] = bad
        with pytest.raises(probe.ProbeError):
            probe.validate_report(report)
    report = native_report()
    report["unexpected_private_text"] = "not copied to audit"
    assert "unexpected_private_text" not in probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("launch_requested", False), ("launch_prepared", False),
                                          ("launcher_visible", True), ("launch_requested", 1),
                                          ("launch_prepared", 1), ("launcher_visible", 0)))
def test_explicit_handoff_requires_preparation_and_hidden_launcher(field, value):
    report = native_report()
    report["server_status"][field] = value
    with pytest.raises(probe.ProbeError, match="launcher_handoff_failed"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("premature_phase", 2), ("premature_phase", True),
        ("premature_original_called", 1), ("premature_original_called", False),
        ("premature_launch_requested", True), ("premature_launch_requested", 0)))
def test_launch_before_ready_must_be_ignored(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="premature_launch_not_ignored"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("ready_phase", 4), ("ready_original_called", 1),
        ("ready_launch_requested", True), ("ready_launch_prepared", True),
        ("ready_observations", 1), ("ready_observations", True),
        ("ready_wait_seconds", 0.99), ("ready_wait_seconds", 4.99), ("ready_wait_seconds", True),
        ("ready_wait_seconds", float("nan")), ("ready_wait_seconds", float("inf"))))
def test_ready_must_remain_idle_for_observation_before_explicit_click(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="unity_started_before_launch_button"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("ready_launcher_visible", False),
        ("ready_button_found", False), ("ready_button_enabled", False),
        ("ready_button_found", 1), ("ready_button_title", "Start")))
def test_ready_requires_real_visible_enabled_launch_button(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="ready_launch_control_failed"):
        probe.validate_report(report)


@pytest.mark.parametrize("field,value", (("button_action_dispatched", False),
        ("button_action_dispatched", 1), ("button_dispatch_count", 0),
        ("button_dispatch_count", 2), ("button_dispatch_count", True),
        ("duplicate_launch_called", False), ("forwarded_after_button", False)))
def test_forwarding_requires_exactly_one_real_ui_action_and_duplicate_launch_guard(field, value):
    report = native_report()
    report["launcher"][field] = value
    with pytest.raises(probe.ProbeError, match="explicit_launch_action_failed"):
        probe.validate_report(report)


def test_launcher_evidence_is_required_and_only_checked_fields_are_audited():
    report = native_report()
    del report["launcher"]
    with pytest.raises(probe.ProbeError, match="launcher_evidence_missing"):
        probe.validate_report(report)
    report = native_report()
    report["launcher"]["unexpected_private_text"] = "must not enter audit"
    checked = probe.validate_report(report)
    assert "unexpected_private_text" not in checked["launcher"]
    assert checked["launcher"]["ready_wait_seconds"] >= 5.0


@pytest.mark.parametrize("field,value", (("game_window_key", False), ("one_finger_count", 0),
        ("one_finger_count", 2), ("one_finger_count", True), ("three_finger_count", 1),
        ("three_finger_count", False), ("minimum_press_seconds", 0.6), ("minimum_press_seconds", True),
        ("matching_count", 0), ("matching_count", 2), ("matching_count", True),
        ("recognizer_name", "unrelated-system-hold"), ("recognizer_name", None),
        ("allowable_movement_points", 100), ("delegate_present", False), ("delegate_present", 1),
        ("delays_touches_began", True), ("delays_touches_ended", True), ("cancels_touches_in_view", False)))
def test_actual_game_window_has_one_configured_corner_hold_and_no_three_finger_hold(field, value):
    report = native_report()
    report["corner_gesture"][field] = value
    with pytest.raises(probe.ProbeError, match="corner_gesture_configuration_failed"):
        probe.validate_report(report)


def test_corner_gesture_evidence_is_required_and_drops_unchecked_details():
    report = native_report()
    del report["corner_gesture"]
    with pytest.raises(probe.ProbeError, match="corner_gesture_configuration_failed"):
        probe.validate_report(report)
    report = native_report()
    report["corner_gesture"]["unchecked"] = "not copied"
    assert "unchecked" not in probe.validate_report(report)["corner_gesture"]


def test_corner_failure_audit_preserves_numeric_boolean_mismatch_without_private_fields(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container")
    broken = native_report()
    # C comparison expressions box as int, unlike an explicit Objective-C
    # BOOL. Keep this actual mismatch visible while still rejecting it.
    broken["corner_gesture"]["delegate_present"] = 1
    broken["corner_gesture"]["private_text"] = "must not retain"
    with mock.patch.object(probe.sys, "platform", "darwin"), \
            mock.patch.object(probe, "_simctl", controller), \
            mock.patch(__name__ + ".native_report", return_value=broken), \
            mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["error"] == "corner_gesture_configuration_failed"
    assert type(result["native_corner_observed"]["delegate_present"]) is int
    assert result["native_corner_observed"]["delegate_present"] == 1
    assert result["native_checkpoint"]["corner_delegate_present"] == 1
    assert result["native_corner_observed"]["matching_count"] == 1
    assert "must not retain" not in json.dumps(result)
    rpc.assert_not_called()


def test_corner_diagnostics_keep_only_bounded_scalars_and_redact_unexpected_names():
    observed = probe.corner_observation({"recognizer_name": "private arbitrary gesture name",
        "matching_count": 2, "one_finger_count": 100000, "three_finger_count": [1],
        "minimum_press_seconds": float("nan"), "allowable_movement_points": 12.0,
        "game_window_key": "private", "delegate_present": 1, "unknown": "private"})
    assert observed == {"recognizer_name": "unexpected_name", "matching_count": 2,
        "allowable_movement_points": 12.0, "delegate_present": 1}


def test_control_bridge_must_report_real_python_host_readiness_and_fixed_listeners():
    for field, value in (("state", "starting"), ("running", False), ("last_error", "test failure")):
        report = native_report()
        report["host_status"]["result"][field] = value
        with pytest.raises(probe.ProbeError, match="python_host_not_ready"):
            probe.validate_report(report)
    report = native_report()
    report["host_status"]["result"]["runtime"]["grpc_address"] = "127.0.0.1:50052"
    with pytest.raises(probe.ProbeError, match="python_host_listeners_differ"):
        probe.validate_report(report)
    report = native_report()
    report["host_status"]["ok"] = False
    with pytest.raises(probe.ProbeError, match="native_status_command_failed"):
        probe.validate_report(report)


@pytest.mark.parametrize("field", ("ok", "nist_encrypt", "nist_decrypt", "invalid_iv_rejected", "worker_main_thread"))
def test_actual_python_commoncrypto_bridge_flags_are_all_required(field):
    report = native_report()
    report["native_crypto"][field] = field == "worker_main_thread"
    with pytest.raises(probe.ProbeError, match="python_commoncrypto_bridge_failed"):
        probe.validate_report(report)
    report = native_report()
    report["crypto_completion_main_thread"] = False
    with pytest.raises(probe.ProbeError, match="python_commoncrypto_bridge_failed"):
        probe.validate_report(report)


@pytest.mark.parametrize("number", (0, 1))
def test_native_crypto_numeric_flags_do_not_count_as_json_booleans(number):
    report = native_report()
    report["native_crypto"]["ok"] = number
    with pytest.raises(probe.ProbeError, match="python_commoncrypto_bridge_failed"):
        probe.validate_report(report)


def test_duplicate_json_and_symlink_report_fail_closed(tmp_path):
    with pytest.raises(probe.ProbeError, match="duplicate_json_key"):
        probe.parse_json(b'{"schema":1,"schema":1}')
    target = tmp_path / "real.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(probe.ProbeError, match="invalid_bounded_file"):
        probe.read_bounded(link, probe.MAX_JSON)


def test_polling_has_a_deadline_without_native_report(tmp_path):
    calls = []
    def remaining():
        calls.append(1)
        if len(calls) == 4:
            raise probe.ProbeError("probe_deadline_exceeded")
        return 1
    with mock.patch.object(probe.time, "sleep"), pytest.raises(probe.ProbeError, match="probe_deadline_exceeded"):
        probe.wait_report(tmp_path, remaining)


def test_atomic_status_replacement_between_lstat_and_open_retries_then_accepts_final_report(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    waiting.write_text(json.dumps({"server_status": {"phase": 1, "error": None}}))
    replacement = documents / "atomic-checkpoint.json"
    replacement.write_text(json.dumps({"server_status": {"phase": 2, "error": None}}))
    original_open = probe.os.open
    replacements = []

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting and not replacements:
            replacements.append(True)
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    def after_retry(delay):
        assert 0 < delay <= 0.25
        (documents / "embedded-probe.json").write_text(json.dumps(native_report()))

    with mock.patch.object(probe.os, "open", opening), \
            mock.patch.object(probe.time, "sleep", side_effect=after_retry) as sleep:
        result = probe.wait_report(tmp_path, lambda: 5)
    assert result["original_called"] == 1
    assert replacements == [True]
    sleep.assert_called_once()


def test_final_report_replacement_between_lstat_and_open_still_fails(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    final = documents / "embedded-probe.json"
    final.write_text(json.dumps(native_report()))
    replacement = documents / "replacement-final.json"
    replacement.write_text(json.dumps(native_report()))
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == final:
            replacement.replace(final)
        return original_open(path, flags, *args, **kwargs)

    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^file_changed_while_opening$"):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_not_called()


def test_status_in_place_mutation_between_lstat_and_open_is_not_retried(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    raw = json.dumps({"server_status": {"phase": 2, "error": None}})
    waiting.write_text(raw)
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting:
            waiting.write_text(raw + " ")  # Same inode, changed size/mtime.
        return original_open(path, flags, *args, **kwargs)

    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^file_changed_while_opening$") as raised:
        probe.wait_report(tmp_path, lambda: 5)
    assert not hasattr(raised.value, "regular_replacement")
    sleep.assert_not_called()


def test_status_open_inode_mutation_during_read_is_not_retried(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    raw = json.dumps({"server_status": {"phase": 2, "error": None}})
    waiting.write_text(raw)
    original_fstat = probe.os.fstat
    observations = []

    def inspect(fd):
        observations.append(fd)
        if len(observations) == 2:
            waiting.write_text(raw + " ")
        return original_fstat(fd)

    with mock.patch.object(probe.os, "fstat", inspect), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^file_changed_while_reading$"):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_not_called()


@pytest.mark.parametrize("unsafe", ("oversize", "symlink", "empty"))
def test_status_replacement_must_still_be_regular_nonempty_bounded_and_nofollow(tmp_path, unsafe):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    waiting.write_text(json.dumps({"server_status": {"phase": 2, "error": None}}))
    replacement = documents / "replacement.json"
    if unsafe == "symlink":
        target = documents / "not-a-checkpoint.json"
        target.write_text("{}")
        replacement.symlink_to(target)
    else:
        replacement.write_bytes(b"x" * (probe.MAX_JSON + 1) if unsafe == "oversize" else b"")
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting:
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    expected = OSError if unsafe == "symlink" else probe.ProbeError
    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(expected):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_not_called()


def test_replaced_status_invalid_json_is_fatal_on_next_bounded_read(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    waiting.write_text(json.dumps({"server_status": {"phase": 2, "error": None}}))
    replacement = documents / "replacement.json"
    replacement.write_text("invalid JSON")
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting and replacement.exists():
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^invalid_json$"):
        probe.wait_report(tmp_path, lambda: 5)
    sleep.assert_called_once()


def test_repeated_atomic_checkpoint_replacement_keeps_original_deadline(tmp_path):
    documents = tmp_path / "Documents"
    documents.mkdir()
    waiting = documents / "embedded-probe-status.json"
    raw = json.dumps({"server_status": {"phase": 2, "error": None}})
    waiting.write_text(raw)
    original_open = probe.os.open

    def opening(path, flags, *args, **kwargs):
        if Path(path) == waiting:
            replacement = documents / "next-checkpoint.json"
            replacement.write_text(raw)
            replacement.replace(waiting)
        return original_open(path, flags, *args, **kwargs)

    remaining = mock.Mock(side_effect=[5, 5, 5, probe.ProbeError("probe_deadline_exceeded")])
    with mock.patch.object(probe.os, "open", opening), mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^probe_deadline_exceeded$"):
        probe.wait_report(tmp_path, remaining)
    assert remaining.call_count == 4
    sleep.assert_called_once_with(0.25)


@pytest.mark.parametrize("failure", sorted(probe.LAUNCHER_FAILURE_CODES))
def test_missing_button_or_explicit_action_fails_immediately_instead_of_waiting(tmp_path, failure):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "server_status": {"phase": 2, "error": None}, "probe_error": failure}))
    with mock.patch.object(probe.time, "sleep") as sleep, \
            pytest.raises(probe.ProbeError, match="^" + failure + "$"):
        probe.wait_report(tmp_path, lambda: 1)
    sleep.assert_not_called()


@pytest.mark.parametrize("failure", ("arbitrary private text", 1, False, ["ready_launch_button_missing"]))
def test_waiting_launcher_failure_diagnostic_is_a_fixed_public_code(tmp_path, failure):
    documents = tmp_path / "Documents"
    documents.mkdir()
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "server_status": {"phase": 2, "error": None}, "probe_error": failure}))
    with pytest.raises(probe.ProbeError, match="^invalid_launcher_failure_code$"):
        probe.wait_report(tmp_path, lambda: 1)


class FixtureApplication:
    def __init__(self, schema, *, empty_token=False):
        self.schema, self.empty_token = schema, empty_token
        self.calls = []

    def handle(self, path, encrypted, context):
        assert encrypted and encrypted != probe.PUBLIC_PROBE_FIELD
        plain = codec.decode(encrypted)
        assert plain == probe.PUBLIC_PROBE_FIELD
        self.schema.request_type(path).FromString(plain)
        self.calls.append(path)
        result = self.schema.response_type(path)()
        if path == probe.RPC_PATHS[0]:
            result.keepAliveTimeMilliseconds = 60000
        elif path == probe.RPC_PATHS[1]:
            result.gameAuthToken = "" if self.empty_token else "portable-test-local-token"
            result.userPublic.serverUserId = "fresh-server-id"
            result.userPublic.publicUserId = "fresh-public-id"
        else:
            if dict(context.invocation_metadata()).get("x-auth-token") != "portable-test-local-token":
                context.abort(RpcCode.UNAUTHENTICATED, "fixture token required")
            result.currentMainAreaId = "fixture-main-area"
        return result.SerializeToString()


def test_real_portable_h2_and_aes_rpc_flow_uses_login_token_without_auditing_it(app):
    schema, fingerprint = probe.load_schema(app)
    assert len(fingerprint) == 64
    application = FixtureApplication(schema)
    server = create_server(application, port=0).start()
    try:
        rows = probe.probe_rpcs(schema, port=server.port, timeout=3)
    finally:
        server.stop()
    assert application.calls == list(probe.RPC_PATHS)
    assert all(row["request_encrypted"] and row["response_encrypted"] and row["grpc_status"] == 0 for row in rows)
    assert "portable-test-local-token" not in json.dumps(rows)


def test_login_without_fresh_identity_token_never_reaches_home(app):
    schema, _ = probe.load_schema(app)
    application = FixtureApplication(schema, empty_token=True)
    server = create_server(application, port=0).start()
    try:
        with pytest.raises(probe.ProbeError, match="fresh_local_login_failed"):
            probe.probe_rpcs(schema, port=server.port, timeout=3)
    finally:
        server.stop()
    assert application.calls == list(probe.RPC_PATHS[:2])


class MasterHTTPResponse:
    def __init__(self, status, headers, body=b""):
        self.status, self.headers, self.body = status, headers, body

    def getheader(self, key, default=None):
        return next((value for name,value in self.headers.items() if name.lower() == key.lower()), default)

    def read(self, amount=None):
        content = self.body if amount is None else self.body[:amount]
        self.body = self.body[len(content):]
        return content

    def close(self):
        pass


class MasterHTTPFixture:
    """Controlled HTTP transport: never opens a listener or follows URLs."""
    def __init__(self, *, head_status=200, head_length="128", range_status=206,
                 range_length="64", content_range="bytes 0-63/128", body=MASTER_BYTES[:64],
                 head_type="application/octet-stream", range_type="application/octet-stream"):
        self.options = head_status, head_length, range_status, range_length, content_range, body, head_type, range_type
        self.connections, self.requests = [], []

    def __call__(self, host, port=None, *, timeout=None):
        self.connections.append((host,port,timeout))
        fixture = self
        class Connection:
            def request(self, method, path, body=None, headers=None):
                self.method = method
                fixture.requests.append((method,path,dict(headers or {})))

            def getresponse(self):
                hs, hl, rs, rl, cr, body, ht, rt = fixture.options
                headers = {"Content-Length":hl if self.method == "HEAD" else rl}
                content_type = ht if self.method == "HEAD" else rt
                if content_type is not None:
                    headers["Content-Type"] = content_type
                if self.method != "HEAD":
                    headers["Content-Range"] = cr
                return MasterHTTPResponse(hs if self.method == "HEAD" else rs,headers,
                                          b"" if self.method == "HEAD" else body)

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()
        return Connection()


def master_unary(schema, *, url="http://127.0.0.1:8080/master/fixture.db", size=128, name="fixture.db"):
    def unary(path, request, *, token=None, port=50051, timeout=15):
        assert port == 50051 and 0 < timeout <= 15
        schema.request_type(path).FromString(request)
        result = schema.response_type(path)()
        if path == "/api.Auth/Login":
            assert token is None
            result.gameAuthToken = "never-export-master-token"
            result.userPublic.serverUserId = "public-fixture-server"
            result.userPublic.publicUserId = "public-fixture-user"
        else:
            assert path == "/api.Master/Get" and token == "never-export-master-token"
            result.masterTag.masterTagPacks.add(fileName=name,fileSize=size,downloadUrl=url)
        return result.SerializeToString(), {"path":path,"grpc_status":0,
            "request_encrypted":True,"response_encrypted":True,"private_token":"never-export-master-token"}
    return unary


def test_master_file_gate_authenticates_catalog_and_compares_bundled_prefix_over_loopback(app):
    schema, _ = probe.load_schema(app)
    http = MasterHTTPFixture()
    with mock.patch.object(probe,"unary_h2",side_effect=master_unary(schema)) as unary, \
            mock.patch.object(probe,"HTTPConnection",side_effect=http):
        result = probe.probe_master_file(schema,app,timeout=3)
    assert result == master_file_report()
    assert [call.args[0] for call in unary.call_args_list] == ["/api.Auth/Login","/api.Master/Get"]
    assert len(http.connections) >= 1
    assert all(host == "127.0.0.1" and port == 8080 and 0 < timeout <= 3
               for host,port,timeout in http.connections)
    assert [row[:2] for row in http.requests] == [("HEAD","/master/fixture.db"),("GET","/master/fixture.db")]
    assert {key.lower():value for key,value in http.requests[1][2].items()}["range"] == "bytes=0-63"
    assert "never-export-master-token" not in json.dumps(result)


def test_master_file_uses_real_encrypted_h2_auth_and_authenticated_master_catalog(app):
    schema, _ = probe.load_schema(app)
    class MasterApplication(FixtureApplication):
        def handle(self, path, encrypted, context):
            if path != "/api.Master/Get":
                return super().handle(path,encrypted,context)
            assert codec.decode(encrypted) == probe.PUBLIC_PROBE_FIELD
            if dict(context.invocation_metadata()).get("x-auth-token") != "portable-test-local-token":
                context.abort(RpcCode.UNAUTHENTICATED,"fixture token required")
            self.calls.append(path)
            result = self.schema.response_type(path)()
            result.masterTag.masterTagPacks.add(fileName="fixture.db",fileSize=128,
                downloadUrl="http://127.0.0.1:8080/master/fixture.db")
            return result.SerializeToString()
    application = MasterApplication(schema)
    server = create_server(application,port=0).start()
    try:
        with mock.patch.object(probe,"HTTPConnection",side_effect=MasterHTTPFixture()):
            result = probe.probe_master_file(schema,app,port=server.port,timeout=3)
    finally:
        server.stop()
    assert application.calls == ["/api.Auth/Login","/api.Master/Get"]
    assert result == master_file_report()
    assert "portable-test-local-token" not in json.dumps(result)


@pytest.mark.parametrize("url", (
    "https://127.0.0.1:8080/master/fixture.db","http://example.invalid:8080/master/fixture.db",
    "http://127.0.0.1:8081/master/fixture.db","http://localhost:8080/master/fixture.db",
    "http://user:secret@127.0.0.1:8080/master/fixture.db","http://127.0.0.1:8080/master/fixture.db?x=1",
    "http://127.0.0.1:8080/master/fixture.db#x","http://127.0.0.1:8080/master/../fixture.db",
    "http://127.0.0.1:8080/master/%66ixture.db","http://127.0.0.1:8080/master/한글.db"))
def test_master_file_rejects_noncanonical_or_nonloopback_url_before_http(app, url):
    schema, _ = probe.load_schema(app)
    with mock.patch.object(probe,"unary_h2",side_effect=master_unary(schema,url=url)), \
            mock.patch.object(probe,"HTTPConnection") as http, pytest.raises(probe.ProbeError):
        probe.probe_master_file(schema,app,timeout=3)
    http.assert_not_called()


def test_master_file_missing_bundled_member_is_rejected_before_http(app):
    schema, _ = probe.load_schema(app)
    with ZipFile(app/"LocalServer/ServerData.zip","w") as archive:
        archive.writestr("data/protocol/idolypride-6.1.1.pb",public_descriptor())
    with mock.patch.object(probe,"unary_h2",side_effect=master_unary(schema)), \
            mock.patch.object(probe,"HTTPConnection") as http, pytest.raises(probe.ProbeError):
        probe.probe_master_file(schema,app,timeout=3)
    http.assert_not_called()


@pytest.mark.parametrize("options", (
    {"head_status":302},{"head_length":"127"},{"head_length":"not-a-length"},
    {"range_status":200},{"range_length":"63"},{"content_range":"bytes 1-64/128"},
    {"body":b"wrong"*13},{"body":MASTER_BYTES[:63]},
))
def test_master_file_rejects_redirects_wrong_lengths_ranges_and_content(app, options):
    schema, _ = probe.load_schema(app)
    with mock.patch.object(probe,"unary_h2",side_effect=master_unary(schema)), \
            mock.patch.object(probe,"HTTPConnection",side_effect=MasterHTTPFixture(**options)), \
            pytest.raises(probe.ProbeError):
        probe.probe_master_file(schema,app,timeout=3)


def test_master_file_equal_length_wrong_sample_fails_bundle_hash_comparison(app):
    schema, _ = probe.load_schema(app)
    with mock.patch.object(probe,"unary_h2",side_effect=master_unary(schema)), \
            mock.patch.object(probe,"HTTPConnection",side_effect=MasterHTTPFixture(body=b"x"*64)), \
            pytest.raises(probe.ProbeError,match="^master_file_sample_differs$"):
        probe.probe_master_file(schema,app,timeout=3)


@pytest.mark.parametrize("field,value", (("head_type",None),("head_type","text/plain"),
    ("range_type",None),("range_type","text/html")))
def test_master_file_requires_binary_mime_on_both_head_and_range(app, field, value):
    schema, _ = probe.load_schema(app)
    with mock.patch.object(probe,"unary_h2",side_effect=master_unary(schema)), \
            mock.patch.object(probe,"HTTPConnection",side_effect=MasterHTTPFixture(**{field:value})), \
            pytest.raises(probe.ProbeError):
        probe.probe_master_file(schema,app,timeout=3)


def test_master_file_gate_uses_first_published_pack_without_language_preference(app):
    schema, _ = probe.load_schema(app)
    first = master_unary(schema)
    def catalog(path,request,**kwargs):
        plain,row = first(path,request,**kwargs)
        if path == "/api.Master/Get":
            message = schema.response_type(path).FromString(plain)
            message.masterTag.masterTagPacks.add(fileName="local-language-ko-ExtraStory.db",fileSize=128,
                downloadUrl="https://must-never-request.invalid/master/another.db")
            plain = message.SerializeToString()
        return plain,row
    with mock.patch.object(probe,"unary_h2",side_effect=catalog), \
            mock.patch.object(probe,"HTTPConnection",side_effect=MasterHTTPFixture()):
        assert probe.probe_master_file(schema,app,timeout=3) == master_file_report()


@pytest.mark.parametrize("field,value", (
    ("schema",True),("transport","requests"),("origin","http://localhost:8080"),
    ("expected_source","remote"),("path_sha256","A"*64),("file_bytes",True),
    ("file_bytes",0),("file_bytes",64*1024*1024+1),("head_status",True),
    ("head_status",302),("head_content_length",127),("range_status",200),
    ("range_content_length",63),("sample_bytes",True),("sample_bytes",63),
    ("content_range","bytes 0-63/129"),("expected_sample_sha256","z"*64),
    ("received_sample_sha256","0"*64),("sample_matches_bundle",1),
))
def test_master_file_report_requires_strict_complete_http_and_bundle_evidence(field, value):
    report = master_file_report()
    report[field] = value
    with pytest.raises(probe.ProbeError):
        probe.validate_master_file_report(report)


@pytest.mark.parametrize("kind,field,value", (
    ("auth_rpc","path","/api.Home/Enter"),("master_rpc","path","/api.Home/Enter"),
    ("auth_rpc","grpc_status",False),("master_rpc","grpc_status",1),
    ("auth_rpc","request_encrypted",1),("master_rpc","response_encrypted",False),
))
def test_master_file_report_requires_encrypted_authenticated_catalog_rpc_evidence(kind, field, value):
    report = master_file_report()
    report[kind][field] = value
    with pytest.raises(probe.ProbeError):
        probe.validate_master_file_report(report)


def test_master_file_audit_projects_fixed_metadata_and_drops_urls_tokens_and_body():
    report = master_file_report()
    report.update(downloadUrl="never-export",body="never-export",token="never-export")
    report["auth_rpc"].update(token="never-export",response_body="never-export")
    result = probe.validate_master_file_report(report)
    assert result == master_file_report()
    assert "never-export" not in json.dumps(result)


def test_master_file_failure_cannot_claim_pass_after_native_and_rpc_success(app, tmp_path):
    controller = FakeSimctl(tmp_path/"master-failure-container")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]), \
            mock.patch.object(probe,"probe_master_file",side_effect=probe.ProbeError("master_file_sample_differs")):
        result = probe.run_probe(app,tmp_path/"master-failure.json")
    assert result["status"] == "FAIL" and result["failed_stage"] == "master_file"
    assert result["error"] == "master_file_sample_differs"
    assert result["cleanup"] == {"shutdown":True,"delete":True}


class SDKHTTPFixture:
    """Encrypted public manifest and streamed object through a fake fixed peer."""
    def __init__(self, *, wire=None, manifest=None, body=SDK_OBJECT, object_status=200,
                 object_mime="application/octet-stream", object_length=None, etag=None):
        self.manifest = encrypted_sdk_manifest(sdk_fixture()[2] if wire is None else wire) if manifest is None else manifest
        self.body, self.object_status, self.object_mime = body, object_status, object_mime
        self.object_length = str(len(body)) if object_length is None else object_length
        self.etag = '"'+hashlib.md5(SDK_OBJECT).hexdigest()+'"' if etag is None else etag
        self.connections, self.requests, self.object_reads = [], [], []

    def __call__(self, host, port=None, *, timeout=None):
        self.connections.append((host,port,timeout))
        fixture = self
        class Connection:
            def request(self, method, path, body=None, headers=None):
                self.path = path
                fixture.requests.append((method,path,dict(headers or {})))

            def getresponse(self):
                if self.path == SDK_PATH:
                    return MasterHTTPResponse(200,{"Content-Length":str(len(fixture.manifest)),
                        "Content-Type":"application/x-protobuf"},fixture.manifest)
                response = MasterHTTPResponse(fixture.object_status,{"Content-Length":fixture.object_length,
                    "Content-Type":fixture.object_mime,"ETag":fixture.etag},fixture.body)
                original_read = response.read
                def read(amount=None):
                    fixture.object_reads.append(amount)
                    return original_read(amount)
                response.read = read
                return response

            def close(self):
                pass
        return Connection()


def rewrite_sdk_settings(app, change):
    path = app/"LocalServer/ServerData.zip"
    with ZipFile(path) as archive:
        entries = {item.filename:archive.read(item) for item in archive.infolist()}
    settings = json.loads(entries[SDK_SETTINGS_MEMBER])
    settings.update(change)
    entries[SDK_SETTINGS_MEMBER] = json.dumps(settings).encode()
    with ZipFile(path,"w") as archive:
        for name,content in entries.items():
            archive.writestr(name,content)


@pytest.mark.parametrize("budget", (3,30))
def test_sdk_resource_decrypts_complete_catalog_and_streams_translated_image_from_fixed_peer(app, budget):
    http = SDKHTTPFixture()
    with mock.patch.object(probe,"HTTPConnection",side_effect=http):
        result = probe.probe_sdk_resource(app,timeout=budget)
    assert result == sdk_resource_report()
    assert [row[:2] for row in http.requests] == [("GET",SDK_PATH),("GET",SDK_OBJECT_PATH)]
    headers = {key.lower():value for key,value in http.requests[0][2].items()}
    assert headers["accept"] == "application/x-protobuf,x-octo-app/212"
    assert headers["x-octo-key"] == "public-sdk-fixture-key"
    assert all(host == "127.0.0.1" and port == 8080 and 0 < timeout <= budget
               for host,port,timeout in http.connections)
    assert http.object_reads and all(type(size) is int and 0 < size <= 65536 for size in http.object_reads)
    assert "public-sdk-fixture-key" not in json.dumps(result)
    assert SDK_KEY.hex() not in json.dumps(result)


def test_sdk_resource_rejects_budget_over_thirty_seconds_before_source_or_network(app):
    with mock.patch.object(probe,"_sdk_source") as source,mock.patch.object(probe,"HTTPConnection") as http, \
            pytest.raises(probe.ProbeError,match="^invalid_sdk_probe_timeout$"):
        probe.probe_sdk_resource(app,timeout=31)
    source.assert_not_called()
    http.assert_not_called()


@pytest.mark.parametrize("name", ("v7"+"a"*48,"Ab\0Z91","Ab_2Z9","한글Ab12","../bad"))
def test_sdk_resource_rejects_non_six_base62_active_names_before_object_fetch(app, name):
    wire = sdk_fixture()[2]
    wire.assetBundleList[0].objectName = name
    http = SDKHTTPFixture(wire=wire)
    with mock.patch.object(probe,"HTTPConnection",side_effect=http),pytest.raises(probe.ProbeError):
        probe.probe_sdk_resource(app,timeout=3)
    assert [row[1] for row in http.requests] == [SDK_PATH]


@pytest.mark.parametrize("mutation", ("row_missing","row_added","duplicate_id","foreign_url",
    "same_revision","unchanged_md5","unchanged_generation"))
def test_sdk_resource_rejects_incomplete_or_untranslated_catalog_before_object_fetch(app, mutation):
    _,raw,wire = sdk_fixture()
    original = Database.FromString(raw)
    if mutation == "row_missing":
        del wire.resourceList[:]
    elif mutation == "row_added":
        wire.resourceList.add().CopyFrom(wire.resourceList[0])
        wire.resourceList[-1].id = 2
    elif mutation == "duplicate_id":
        wire.resourceList.add().CopyFrom(wire.resourceList[0])
    elif mutation == "foreign_url":
        wire.urlFormat = "https://must-never-fetch.invalid/{v}/{type}/{o}/{g}"
    elif mutation == "same_revision":
        wire.revision = original.revision
    elif mutation == "unchanged_md5":
        wire.assetBundleList[0].md5 = original.assetBundleList[0].md5
    else:
        wire.assetBundleList[0].generation = original.assetBundleList[0].generation
    http = SDKHTTPFixture(wire=wire)
    with mock.patch.object(probe,"HTTPConnection",side_effect=http),pytest.raises(probe.ProbeError):
        probe.probe_sdk_resource(app,timeout=3)
    assert [row[1] for row in http.requests] == [SDK_PATH]


@pytest.mark.parametrize("options", ({"body":b"x"*len(SDK_OBJECT)},
    {"body":SDK_OBJECT[:-1],"object_length":str(len(SDK_OBJECT))},
    {"object_status":302},{"object_mime":"text/html"},{"etag":'"'+'0'*32+'"'},
    {"manifest":b"truncated-encrypted-manifest"}))
def test_sdk_resource_rejects_wrong_hash_truncation_redirect_mime_etag_or_ciphertext(app, options):
    with mock.patch.object(probe,"HTTPConnection",side_effect=SDKHTTPFixture(**options)), \
            pytest.raises(probe.ProbeError):
        probe.probe_sdk_resource(app,timeout=3)


@pytest.mark.parametrize("change", ({"schema":True},{"application_version":205051},
    {"manifest_sha256":"0"*64},{"aes_key_hex":"not-a-key"},
    {"client_key":"must-not-export\nsecret"}))
def test_sdk_resource_rejects_bad_archive_settings_before_http_without_exposing_keys(app, change):
    rewrite_sdk_settings(app,change)
    with mock.patch.object(probe,"HTTPConnection") as http,pytest.raises(probe.ProbeError) as caught:
        probe.probe_sdk_resource(app,timeout=3)
    http.assert_not_called()
    assert "must-not-export" not in str(caught.value) and SDK_KEY.hex() not in str(caught.value)


@pytest.mark.parametrize("field,value", (
    ("schema",True),("application_id",True),("application_version",205051),
    ("origin","https://private.invalid"),("manifest_path","/list/another"),
    ("manifest_encrypted",1),("manifest_decrypted",False),("manifest_ciphertext_bytes",33),
    ("manifest_rows",True),("active_rows",3),("translated_image_count",0),
    ("all_active_object_names_six_base62",1),("received_bytes",0),
    ("expected_md5","z"*32),("received_md5","0"*32),("etag_matches_md5",1),
    ("manifest_revision",1159),("object_mime","text/plain"),
))
def test_sdk_resource_report_requires_strict_crypto_catalog_and_object_evidence(field, value):
    report = sdk_resource_report()
    report[field] = value
    with pytest.raises(probe.ProbeError):
        probe.validate_sdk_resource_report(report)


def test_sdk_resource_report_drops_secret_keys_raw_names_urls_and_object_body():
    report = sdk_resource_report()
    report.update(aes_key_hex="never-export",client_key="never-export",body="never-export",
        object_name="never-export",download_url="never-export")
    result = probe.validate_sdk_resource_report(report)
    assert result == sdk_resource_report()
    assert "never-export" not in json.dumps(result)


def test_sdk_resource_failure_prevents_pass_after_unchanged_rpc_and_master_gates(app, tmp_path):
    controller = FakeSimctl(tmp_path/"sdk-failure-container")
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",controller), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]), \
            mock.patch.object(probe,"probe_master_file",return_value=master_file_report()), \
            mock.patch.object(probe,"probe_sdk_resource",side_effect=probe.ProbeError("sdk_resource_sample_differs")):
        result = probe.run_probe(app,tmp_path/"sdk-failure.json")
    assert result["status"] == "FAIL" and result["failed_stage"] == "sdk_resource"
    assert result["error"] == "sdk_resource_sample_differs"
    assert result["cleanup"] == {"shutdown":True,"delete":True}


def test_cold_boot_retries_bounded_observer_for_only_the_created_uuid(monkeypatch):
    calls = []

    def simctl(arguments, timeout):
        calls.append((arguments, timeout))
        if arguments[0] == "bootstatus" and len(calls) == 2:
            raise probe.ProbeError("simctl_timeout")
        return b"booted"

    monkeypatch.setattr(probe, "_simctl", simctl)
    probe.boot_created_simulator(CREATED, lambda: 60)
    assert [row[0] for row in calls] == [
        ["boot", CREATED], ["bootstatus", CREATED, "-b"], ["bootstatus", CREATED, "-b"]]
    assert all(timeout == 60 for _, timeout in calls)


def test_cold_boot_keeps_overall_deadline_and_does_not_hide_other_failures(monkeypatch):
    def timed_out(arguments, timeout):
        if arguments[0] == "bootstatus":
            raise probe.ProbeError("simctl_timeout")
        return b""

    remaining = mock.Mock(side_effect=[60, 60, probe.ProbeError("probe_deadline_exceeded")])
    monkeypatch.setattr(probe, "_simctl", timed_out)
    with pytest.raises(probe.ProbeError, match="probe_deadline_exceeded"):
        probe.boot_created_simulator(CREATED, remaining)
    monkeypatch.setattr(probe, "_simctl", mock.Mock(side_effect=probe.ProbeError("simctl_failed")))
    with pytest.raises(probe.ProbeError, match="simctl_failed"):
        probe.boot_created_simulator(CREATED, lambda: 60)


def test_game_data_failure_ends_wait_without_waiting_for_server_timeout(tmp_path):
    documents = tmp_path / "Documents"; documents.mkdir()
    (documents / "embedded-probe-status.json").write_text(json.dumps({
        "schema": 1, "server_status": {"phase": 2, "error": None, "game_error": "public fixture error"}}))
    with pytest.raises(probe.ProbeError, match="native_game_preparation_failed") as caught:
        probe.wait_report(tmp_path, lambda: 1)
    assert caught.value.native_detail == "public fixture error"

@pytest.mark.parametrize("field", probe.ACCOUNT_UI_FLAGS)
@pytest.mark.parametrize("bad", [False, 1])
def test_account_management_requires_each_actual_ui_flag(field, bad):
    observed = native_report()
    observed["menu_lifetime"]["account_management"]["ui_flags"][field] = bad
    with pytest.raises(probe.ProbeError, match="settings_account_management_failed"):
        probe.validate_report(observed)


@pytest.mark.parametrize("field", probe.ACCOUNT_NATIVE_FLAGS)
@pytest.mark.parametrize("bad", [False, 1])
def test_account_management_requires_picker_and_pending_selection_evidence(field, bad):
    observed = native_report()
    observed["menu_lifetime"]["account_management"][field] = bad
    with pytest.raises(probe.ProbeError, match="settings_account_management_failed"):
        probe.validate_report(observed)


@pytest.mark.parametrize("field", probe.ACCOUNT_STATE_FLAGS)
@pytest.mark.parametrize("bad", [False, 1])
def test_account_management_requires_independent_exact_state_observation(field, bad):
    observed = native_report()
    observed["menu_lifetime"]["account_management"]["state_observation"]["checks"][field] = bad
    with pytest.raises(probe.ProbeError, match="settings_account_management_failed"):
        probe.validate_report(observed)


@pytest.mark.parametrize("case", ["first_skip", "later_performed", "actions", "copy_extent", "copy_bool",
    "empty_table", "row_bool", "fixture_hash", "observer", "state_hash", "gameplay", "timeout", "elapsed"])
def test_account_management_rejects_incomplete_or_mixed_proof(case):
    value = modeled_account_management()
    index = 0
    if case == "first_skip": value = {"performed":False,"reason":"first-cold-run-only"}
    elif case == "later_performed": index = 1
    elif case == "actions": value["ui_actions"].pop()
    elif case == "copy_extent": value["preview_copies"][1]["copied_bytes"] -= 1
    elif case == "copy_bool": value["preview_copies"][1]["copied_bytes"] = True
    elif case == "empty_table": value["fixture_source"]["table_rows"]["main_live_attempts"] = 0
    elif case == "row_bool": value["fixture_source"]["table_rows"]["snapshots"] = True
    elif case == "fixture_hash": value["fixture_target"]["normalized_sha256"] = "a"*64
    elif case == "observer": value["state_observation"]["observer"] = "native-ui"
    elif case == "state_hash": value["state_observation"]["normalized_restored_sha256"] = "0"*64
    elif case == "gameplay": value["gameplay_tested"] = True
    elif case == "timeout": value["timed_out"] = True
    else: value["elapsed_seconds"] = float("nan")
    with pytest.raises(probe.ProbeError, match="settings_account_management_failed"):
        probe.validate_account_management(value, index)


def test_account_management_projection_drops_profile_keys_tokens_and_provider_paths():
    value = modeled_account_management()
    value.update(profile="DO-NOT-EXPORT",nonce="DO-NOT-EXPORT",source_path="DO-NOT-EXPORT")
    value["fixture_source"].update(nonce="DO-NOT-EXPORT",profile="DO-NOT-EXPORT")
    value["state_observation"]["token"] = "DO-NOT-EXPORT"
    assert "DO-NOT-EXPORT" not in json.dumps(probe.validate_account_management(value, 0))
    assert probe.validate_account_management({"performed":False,"reason":"first-cold-run-only"}, 4) == {
        "performed":False,"reason":"first-cold-run-only"}


def account_fixture_schema(path):
    from idoly_local.schema import Schema
    file = descriptor_pb2.FileDescriptorProto(name="account-native-observer-test.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    user = file.message_type.add(name="SavedUser")
    user.field.add(name="name",number=1,type=9)
    public = file.message_type.add(name="UserPublic")
    public.field.add(name="serverUserId",number=1,type=9)
    public.field.add(name="publicUserId",number=2,type=9)
    response = file.message_type.add(name="UserGetResponse")
    response.field.add(name="user",number=1,type=11,type_name=".api.SavedUser")
    response.field.add(name="userPublic",number=2,type=11,type_name=".api.UserPublic")
    file.message_type.add(name="SettingInfo")
    file.message_type.add(name="LessonProgress")
    login = file.message_type.add(name="HomeLogin")
    login.field.add(name="settingInfo",number=1,type=11,type_name=".api.SettingInfo")
    lesson = file.message_type.add(name="LessonResponse")
    lesson.field.add(name="progress",number=1,type=11,type_name=".api.LessonProgress")
    file.message_type.add(name="Receipt")
    for service, method, request, response in (
        ("System","Check","Empty","Empty"),
        ("User","Get","Empty","UserGetResponse"),("Home","Login","HomeLogin","Empty"),
        ("Activity","ReceiveLessonReward","Empty","LessonResponse"),
        ("Photo","SwitchLock","Empty","Receipt"),("Quest","Start","Empty","Receipt")):
        entry=file.service.add(name=service)
        entry.method.add(name=method,input_type=".api."+request,output_type=".api."+response)
    # The real package preserves descriptor order and unknown information;
    # Schema uses sorted files for its separate canonical account identity.
    prefix = descriptor_pb2.FileDescriptorProto(name="account-native-observer-prefix.proto", package="probe", syntax="proto3")
    descriptor=descriptor_pb2.FileDescriptorSet(file=[file,prefix]).SerializeToString()+probe.PUBLIC_PROBE_FIELD
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(descriptor)
    return Schema.from_descriptor_set(path)


@pytest.fixture
def real_account_observer(tmp_path):
    from idoly_local.account_manager import AccountManager
    from idoly_local.state import State
    root=tmp_path/"container/Library/Application Support/IdolyPrideLocal"
    root.mkdir(parents=True)
    schema=account_fixture_schema(root/"protocol/idolypride-6.1.1.pb")
    state=State(root/"state.db")
    identity=state.ensure_profile("sandbox")
    response=schema.response_type("/api.User/Get")()
    response.user.name="Sandbox"
    response.userPublic.serverUserId=identity["server_id"]
    response.userPublic.publicUserId=identity["public_id"]
    state.save_snapshot("sandbox",response.SerializeToString()+b"\x80\x4b\x7b",schema.fingerprint,starter_version=7)
    state.login("sandbox")
    observer=REAL_ACCOUNT_FIXTURE_HARNESS(tmp_path/"container",schema,
        descriptor_sha256=hashlib.sha256((root/"protocol/idolypride-6.1.1.pb").read_bytes()).hexdigest(),nonce="1"*32)
    manager=AccountManager(root,schema=schema)
    manager.command("accounts_clone",{"mode":"normal","source_profile":"sandbox","profile":observer.source,
        "expected_revision":state.account_snapshot("sandbox")[1]})
    return observer,manager,state


def account_seed_request(observer, phase="source", **changes):
    request={"schema":1,"run_index":0,"nonce":hashlib.sha256((observer.nonce+":"+phase).encode()).hexdigest()[:32],
        "phase":phase,"mode":"normal","profile":observer.source if phase=="source" else observer.target,
        "active_profile":"sandbox"}
    request.update(changes)
    observer._write(observer.request,request)
    return request


def consume_account_fixture_ack(observer):
    value=json.loads(observer.ack.read_text())
    observer.ack.unlink();observer.request.unlink()
    return value


def complete_account_observer(observer, manager, state):
    import shutil
    account_seed_request(observer);observer.process()
    source_ack=consume_account_fixture_ack(observer)
    exported=manager.command("accounts_export",{"mode":"normal","profile":observer.source,
        "expected_revision":state.account_snapshot(observer.source)[1]})
    shutil.copyfile(exported["path"],observer.archive)
    preview=manager.command("accounts_preview",{"path":str(observer.archive)})
    manager.command("accounts_import",{"token":preview["token"],"mode":"normal","profile":observer.target,
        "replace":False,"expected_revision":None})
    account_seed_request(observer,"target");observer.process()
    target_ack=consume_account_fixture_ack(observer)
    preview=manager.command("accounts_preview",{"path":str(observer.archive)})
    replaced=manager.command("accounts_import",{"token":preview["token"],"mode":"normal","profile":observer.target,
        "replace":True,"expected_revision":state.account_snapshot(observer.target)[1]})
    point=next(row for row in replaced["status"]["restore_points"] if row["profile"]==observer.target
        and row["revision"]==target_ack["bundle_revision"])
    manager.command("accounts_restore",{"id":point["id"],"mode":"normal","profile":observer.target,
        "expected_revision":state.account_snapshot(observer.target)[1]})
    return {"archive_sha256":exported["sha256"],"archive_bytes":exported["bytes"]},source_ack,target_ack


def test_owned_simulator_fixture_uses_real_schema_eight_tables_unknown_blobs_and_full_archive(real_account_observer):
    observer,manager,state=real_account_observer
    assert observer.descriptor_sha256 == hashlib.sha256((observer.root/"protocol/idolypride-6.1.1.pb").read_bytes()).hexdigest()
    assert observer.schema.fingerprint != observer.descriptor_sha256
    native,source_ack,target_ack=complete_account_observer(observer,manager,state)
    proof=observer.verify(native)
    assert all(proof["checks"].values())
    assert set(proof["table_rows"])==set(probe.ACCOUNT_TABLES)
    assert all(count>0 for count in proof["table_rows"].values())
    assert source_ack["request_sha256"] != target_ack["request_sha256"]
    assert source_ack["normalized_sha256"] != target_ack["normalized_sha256"]
    assert probe.PUBLIC_PROBE_FIELD in state.snapshot(observer.source)[0]
    assert (probe.PUBLIC_PROBE_FIELD[:-1]+b"\x02") in state.snapshot(observer.target)[0]
    assert all(observer.verify_persisted()["checks"].values())
    love=state.account_snapshot(observer.source)[0]["tables"]["profile_love_progress"][0]
    assert love["response"].endswith(b"\n") and b'  "player_name": "ProbeA"' in love["response"]
    assert state.account_snapshot(observer.target)[0]["tables"]["profile_love_progress"][0]["response"] != love["response"]
    assert proof["checks"]["love_progress_bytes_exact"] is True


@pytest.mark.parametrize("case",["descriptor_raw","account_schema"])
def test_account_fixture_checks_raw_package_and_canonical_account_schema_independently(real_account_observer,case):
    from idoly_local.schema import Schema
    observer,manager,state=real_account_observer
    if case == "descriptor_raw":
        descriptor=observer.root/"protocol/idolypride-6.1.1.pb"
        descriptor.write_bytes(descriptor.read_bytes()+probe.PUBLIC_PROBE_FIELD)
        # Same canonical schema does not authorize different package bytes.
        assert Schema.from_descriptor_set(descriptor).fingerprint == observer.schema.fingerprint
        assert hashlib.sha256(descriptor.read_bytes()).hexdigest() != observer.descriptor_sha256
    else:
        with state.connect() as db:
            db.execute("UPDATE snapshots SET schema_sha256=? WHERE profile=?",("0"*64,observer.source))
    before=state.account_snapshot(observer.source)
    account_seed_request(observer)
    with pytest.raises(probe.ProbeError,match="settings_account_fixture_failed"):
        observer.process()
    assert state.account_snapshot(observer.source) == before
    assert not observer.ack.exists()


@pytest.mark.parametrize("case",["nonce","active_target","mode","phase","schema_bool","run_bool",
                                "extra","symlink","hardlink","old_mtime","oversize","ack_exists"])
def test_account_fixture_refuses_unbound_or_replayed_requests_before_database_mutation(real_account_observer,case,tmp_path):
    import os
    observer,manager,state=real_account_observer
    before=state.account_snapshot(observer.source)
    changes={}
    if case=="nonce":changes["nonce"]="0"*32
    elif case=="active_target":changes["profile"]="sandbox"
    elif case=="mode":changes["mode"]="unrecognized"
    elif case=="phase":changes["phase"]="target"
    elif case=="schema_bool":changes["schema"]=True
    elif case=="run_bool":changes["run_index"]=False
    elif case=="extra":changes["provider_path"]="DO-NOT-EXPORT"
    account_seed_request(observer,**changes)
    if case=="symlink":
        original=tmp_path/"request-source.json";observer.request.rename(original);observer.request.symlink_to(original)
    elif case=="hardlink":os.link(observer.request,tmp_path/"request-alias.json")
    elif case=="old_mtime":os.utime(observer.request,ns=(observer.created_ns-1,observer.created_ns-1))
    elif case=="oversize":observer.request.write_bytes(b" "*8193)
    elif case=="ack_exists":observer.ack.write_text("{}")
    with pytest.raises(probe.ProbeError):
        observer.process()
    assert state.account_snapshot(observer.source)==before


def test_account_fixture_consumed_ack_is_not_reissued_and_different_replay_is_rejected(real_account_observer):
    observer,manager,state=real_account_observer
    account_seed_request(observer);observer.process()
    consume_account_fixture_ack(observer)
    before=state.account_snapshot(observer.source)
    account_seed_request(observer);observer.process()
    assert not observer.ack.exists() and state.account_snapshot(observer.source)==before
    account_seed_request(observer,nonce="0"*32)
    with pytest.raises(probe.ProbeError):
        observer.process()
    assert state.account_snapshot(observer.source)==before


@pytest.mark.parametrize("case",["archive_hash","restored_blob"])
def test_account_observer_checks_actual_values_instead_of_trusting_native_flags(real_account_observer,case):
    observer,manager,state=real_account_observer
    native,_source,_target=complete_account_observer(observer,manager,state)
    if case=="archive_hash":native["archive_sha256"]="0"*64
    else:state.mutate_snapshot(observer.target,observer.schema.fingerprint,
        lambda raw:raw+probe.PUBLIC_PROBE_FIELD)
    with pytest.raises(probe.ProbeError,match="settings_account_fixture_failed"):
        observer.verify(native)


def test_account_native_scenario_is_valid_javascript_and_preserves_original_probe_gates(tmp_path):
    import re
    import subprocess
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    expression=re.search(r"static NSString \*const ProbeAccountScenario =\s*(.*?)\nstatic NSString \*ProbeAccountJSON",source,re.S)
    assert expression is not None
    pieces=re.findall(r'@?("(?:\\.|[^"\\])*")',expression.group(1))
    script="".join(json.loads(piece) for piece in pieces).rstrip(";")
    assert script.startswith("(function(config)")
    checked=subprocess.run(["node","--check"],input=script,text=True,capture_output=True)
    assert checked.returncode==0,checked.stderr
    for gate in ("ProbeZIPRoundTrip(web","ProbeAccountManagement(web","ProbeDiagnosticsCopy(web",
                 "data_store_reused","ProbeAutoSaveLanguage"):
        assert gate in source


@pytest.mark.parametrize("case",["consumed_preview","pending_fields","wrong_reply_id"])
def test_native_account_click_completion_respects_single_use_import_and_pending_state(case):
    import re
    import subprocess
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    expression=re.search(r"static NSString \*const ProbeAccountScenario =\s*(.*?)\nstatic NSString \*ProbeAccountJSON",source,re.S)
    pieces=re.findall(r'@?("(?:\\.|[^"\\])*")',expression.group(1))
    script="".join(json.loads(piece) for piece in pieces)
    reveal_match=re.search(r"static NSString \*const ProbeSettingsNavigationScript =\s*(.*?);\n\n//",source,re.S)
    assert reveal_match is not None
    reveal="".join(json.loads(piece) for piece in re.findall(r'@?("(?:\\.|[^"\\])*")',reveal_match.group(1)))
    until=script[script.index("  const until="):script.index("  const current=")]
    click=script[script.index("  const click="):script.index("  const seed=")]
    program="const testCase="+json.dumps(case)+r""";
const q={error:null},config={deadline:Date.now()+350},fields={disabled:false};
let clicks=0,unlocked=false;
const button={disabled:false,scrollIntoView(){},click(){
  clicks++;fields.disabled=true;button.disabled=true;
  q.request={id:1,action:'accounts_import'};
  q.reply={id:testCase==='wrong_reply_id'?2:1,ok:true,result:{action:'accounts_import'}};
  if(testCase!=='pending_fields')setTimeout(()=>{unlocked=true;fields.disabled=false;},25);
}};
const navigation=[],page={id:'category-panel-users',hidden:true,parentElement:null,getAttribute(){return null;}};
const panel={tagName:'DETAILS',open:false,parentElement:page,children:[]};
const summary={tagName:'SUMMARY',scrollIntoView(){},getBoundingClientRect(){return {width:page.hidden?0:100,height:44};},click(){navigation.push('panel-accounts');panel.open=!panel.open;}};
panel.children=[summary,button];button.parentElement=panel;button.hidden=false;button.closest=()=>page;
button.getBoundingClientRect=()=>({width:!page.hidden&&panel.open?100:0,height:44});
const nav={id:'category-users',disabled:false,scrollIntoView(){},getAttribute(name){return name==='aria-controls'?page.id:null;},getBoundingClientRect(){return {width:100,height:44};},click(){navigation.push('category-users');page.hidden=false;}};
const document={getElementById(id){return id==='accounts-fields'?fields:id==='accounts-import'?button:id==='category-users'?nav:null;}};
const getComputedStyle=e=>({display:e.hidden?'none':'block',visibility:'visible'});
"""+"const window={__idolyProbeRevealControl:"+reveal+"};\n"+until+click+r"""
(async()=>{
  let result=null,error=null;
  try{result=await click('import');}catch(value){error=value.message;}
  if(navigation.join(',')!=='category-users,panel-accounts')throw Error('native account navigation was bypassed');
  if(testCase==='consumed_preview'){
    if(!result||result.action!=='accounts_import'||error||!unlocked||fields.disabled||!button.disabled||clicks!==1)
      throw Error('single-use import completion lost');
  }else if(error!=='account_ui_timeout'||result!==null||clicks!==1)
    throw Error('pending or uncorrelated completion accepted');
})().catch(error=>{console.error(error.message);process.exitCode=1;});
"""
    checked=subprocess.run(["node"],input=program,text=True,capture_output=True,timeout=5)
    assert checked.returncode==0,checked.stderr


@pytest.mark.parametrize("field", probe.ACCOUNT_PERSIST_FLAGS)
@pytest.mark.parametrize("bad", [False, 1])
def test_after_five_cold_runs_requires_each_actual_boolean_preservation_check(field,bad):
    first=modeled_account_management()
    value={"schema":1,"observer":"runner-sqlite-after-five-cold-runs","seed_fixture_used":True,
        "gameplay_tested":False,"checks":{key:True for key in probe.ACCOUNT_PERSIST_FLAGS},
        "normalized_source_sha256":"a"*64,"normalized_restored_sha256":"b"*64}
    value["checks"][field]=bad
    with pytest.raises(probe.ProbeError,match="settings_account_management_failed"):
        probe.validate_account_management_after_relaunch(value,first)


@pytest.mark.parametrize("case",["missing","scope","schema_bool","source_hash","restore_hash","hash_swap","gameplay","fixture","first_skip"])
def test_after_relaunch_state_must_match_the_first_complete_fixture_proof(case):
    first=modeled_account_management()
    value={"schema":1,"observer":"runner-sqlite-after-five-cold-runs","seed_fixture_used":True,
        "gameplay_tested":False,"checks":{key:True for key in probe.ACCOUNT_PERSIST_FLAGS},
        "normalized_source_sha256":"a"*64,"normalized_restored_sha256":"b"*64}
    if case=="missing":value["checks"].pop("source_all_tables_persisted")
    elif case=="scope":value["observer"]="native-ui"
    elif case=="schema_bool":value["schema"]=True
    elif case=="source_hash":value["normalized_source_sha256"]="0"*64
    elif case=="restore_hash":value["normalized_restored_sha256"]="0"*64
    elif case=="hash_swap":value.update(normalized_source_sha256="b"*64,normalized_restored_sha256="a"*64)
    elif case=="gameplay":value["gameplay_tested"]=True
    elif case=="fixture":value["seed_fixture_used"]=False
    else:first={"performed":False,"reason":"first-cold-run-only"}
    with pytest.raises(probe.ProbeError,match="settings_account_management_failed"):
        probe.validate_account_management_after_relaunch(value,first)


def test_after_relaunch_projection_keeps_only_bound_metrics_and_actual_hashes():
    first=modeled_account_management()
    value={"schema":1,"observer":"runner-sqlite-after-five-cold-runs","seed_fixture_used":True,
        "gameplay_tested":False,"checks":{key:True for key in probe.ACCOUNT_PERSIST_FLAGS},
        "normalized_source_sha256":"a"*64,"normalized_restored_sha256":"b"*64,
        "provider_path":"DO-NOT-EXPORT","token":"DO-NOT-EXPORT"}
    checked=probe.validate_account_management_after_relaunch(value,first)
    assert "DO-NOT-EXPORT" not in json.dumps(checked)
    assert checked["checks"]==value["checks"]


@pytest.mark.parametrize("field",probe.OFFICIAL_PROMPT_FLAGS)
@pytest.mark.parametrize("bad",[False,1])
def test_official_secure_prompt_requires_each_actual_boolean(field,bad):
    observed=native_report();observed["menu_lifetime"]["official_prompt"][field]=bad
    with pytest.raises(probe.ProbeError,match="^settings_official_prompt_failed$"):
        probe.validate_report(observed)


@pytest.mark.parametrize("field,bad",[("credential_submission_performed",True),("credential_submission_performed",0),
    ("timed_out",True),("elapsed_seconds",31),("elapsed_seconds",True),("elapsed_seconds",float("nan")),
    ("ui_trigger","direct-backend"),("cancel_trigger","submit")])
def test_official_prompt_never_accepts_submission_timeout_or_alternate_actions(field,bad):
    observed=native_report();observed["menu_lifetime"]["official_prompt"][field]=bad
    with pytest.raises(probe.ProbeError,match="^settings_official_prompt_failed$"):
        probe.validate_report(observed)


def test_official_prompt_projection_has_no_input_values_and_later_cold_runs_skip_exactly():
    value=native_report()["menu_lifetime"]["official_prompt"]
    value.update(user_id="DO-NOT-EXPORT",password="DO-NOT-EXPORT",raw_input="DO-NOT-EXPORT")
    assert "DO-NOT-EXPORT" not in json.dumps(probe.validate_official_prompt(value,0))
    skipped={"performed":False,"reason":"first-cold-run-only"}
    for index in (1,2,3,4):assert probe.validate_official_prompt(skipped,index)==skipped
    with pytest.raises(probe.ProbeError):probe.validate_official_prompt(skipped,0)
    with pytest.raises(probe.ProbeError):probe.validate_official_prompt(value,1)


def test_actual_official_prompt_dom_hook_only_clicks_and_observes_cancelled_reply():
    import re
    import subprocess
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    expression=re.search(r"static NSString \*const ProbeOfficialPromptScript =\s*(.*?)\nstatic void ProbeOfficialSnapshot",source,re.S)
    script="".join(json.loads(piece) for piece in re.findall(r'@?("(?:\\.|[^"\\])*")',expression.group(1))).rstrip(";")
    program=r"""
let posts=0,replies=0;
const h={postMessage(value){posts++;}},window={webkit:{messageHandlers:{idolyServer:h}},idolyServerReply(){replies++;}};
"""+"const opened="+script+r""";
if(opened!==true)throw Error('hook did not install');
h.postMessage({id:3,action:'official_inspect'});
window.idolyServerReply(3,{id:3,ok:true,result:{action:'official_inspect',cancelled:true}});
const q=window.__idolyOfficialPromptProbe;
if(q.request!==3||q.empty_payload!==true||q.cancelled!==true||q.forbidden!==false||posts!==1||replies!==1)throw Error('cancel correlation failed');
h.postMessage({id:4,action:'official_fetch'});if(q.forbidden!==true)throw Error('submit accepted');
"""
    checked=subprocess.run(["node"],input=program,text=True,capture_output=True,timeout=5)
    assert checked.returncode==0,checked.stderr


def test_official_cancel_probe_publishes_ready_fields_and_requires_real_cancel_ack():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    poll=source.split("static void ProbeOfficialPromptPoll",1)[1].split("static void ProbeOfficialPrompt(",1)[0]
    assert "ProbeOfficialActivateCancel" not in source
    assert "accessibilityActivate" not in poll and "accessibilityPerformEscape" not in poll
    assert "sendActionsForControlEvents" not in poll and "valueForKey" not in poll and "performSelector" not in poll
    assert 'action.style==UIAlertActionStyleCancel' in poll
    assert 'hasPrefix:' not in poll
    for title in ("iOS 계정 확인","iOSアカウントを確認","Check iOS account","Android 계정 확인","Androidアカウントを確認","Check Android account"):
        assert title in poll
    assert 'iosActions==1&&androidActions==1' in poll
    assert poll.index('metrics[@"synthetic_inputs_set"]') < poll.index('accessibilityIdentifier=@"idoly-official-probe-transfer-id"')
    assert 'accessibilityIdentifier=@"idoly-official-probe-transfer-password"' in poll
    assert '[metrics[@"web_reply_cancelled"] isEqual:@YES]' in poll and 'metrics[@"cancel_ack_observed"]=@YES' in poll
    assert 'metrics[@"fields_cleared"]' in poll and 'metrics[@"account_data_unchanged"]' in poll


@pytest.mark.parametrize("field,bad",[("actual_cancel_tap",False),("actual_cancel_tap",1),("ready_marker_observed",False),
    ("tests",True),("tests",0),("tests",2),("failures",1),("skipped",1),("status","FAIL"),
    ("execution","native-handler"),("test_identifier","Other/test"),("source_sha256","a"*64),
    ("xctestrun_sha256","not-a-hash"),("simulator_udid","not-owned")])
def test_official_prompt_requires_strict_external_xctest_result_and_source_binding(field,bad):
    proof=modeled_ui_test_proof();proof[field]=bad
    with pytest.raises(probe.ProbeError,match="^official_ui_test_evidence_failed$"):
        probe.validate_official_ui_proof(proof,expected_simulator=CREATED)


def test_official_ui_proof_rejects_another_simulator_or_changed_source_and_drops_raw_payload():
    proof=modeled_ui_test_proof();proof["raw_input"]="DO-NOT-EXPORT"
    assert "DO-NOT-EXPORT" not in json.dumps(probe.validate_official_ui_proof(proof,expected_simulator=CREATED))
    with pytest.raises(probe.ProbeError):probe.validate_official_ui_proof(proof,expected_simulator="00000000-0000-4000-8000-000000000999")
    proof["source_pins"]["ui-tests/OfficialPromptCancelTests.swift"]="a"*64
    with pytest.raises(probe.ProbeError):probe.validate_official_ui_proof(proof)
    native=native_report();del native["menu_lifetime"]["official_prompt"]["ui_test"]
    with pytest.raises(probe.ProbeError):probe.validate_report(native)


def test_xctest_runner_starts_before_existing_probe_and_closes_before_owned_simulator(app,tmp_path,monkeypatch):
    events=[]
    class Driver(ModeledUIDriver):
        def start(self):events.append("driver-start");super().start()
        def poll(self):events.append("driver-ready");return super().poll()
        def finish(self):events.append("driver-finish");return super().finish()
        def close(self):events.append("driver-close");super().close()
    sim=FakeSimctl(tmp_path/"ui-runner-container")
    def control(args,timeout):
        if args[0] in ("launch","terminate","shutdown","delete"):events.append(args[0])
        return sim(args,timeout)
    monkeypatch.setattr(probe,"ProbePromptCancelDriver",Driver)
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",control), \
            mock.patch.object(probe.socket,"create_connection"),mock.patch.object(probe,"probe_rpcs",return_value=[]), \
            mock.patch.object(probe,"probe_master_file",return_value=master_file_report()), \
            mock.patch.object(probe,"probe_sdk_resource",return_value=sdk_resource_report()):
        result=probe.run_probe(app,tmp_path/"ui-runner.json")
    assert result["status"]=="PASS"
    assert events.index("driver-start") < events.index("driver-ready") < events.index("launch")
    assert events.index("driver-finish") < events.index("terminate")
    assert events.index("driver-close") < events.index("shutdown") < events.index("delete")
    assert events.count("driver-start")==1 and events.count("driver-finish")==1
    assert events.count("launch")==5 and [x[0] for x in sim.calls].count("install")==1
    assert result["official_prompt_ui_test"]["test_identifier"]==probe.UI_TEST_IDENTIFIER


def test_failed_xctest_result_still_cleans_only_owned_driver_and_simulator(app,tmp_path,monkeypatch):
    closed=[]
    class Failed(ModeledUIDriver):
        def finish(self):raise probe.DriverError("ui_driver_test_failed")
        def close(self):closed.append(True);super().close()
    sim=FakeSimctl(tmp_path/"failed-ui-runner")
    monkeypatch.setattr(probe,"ProbePromptCancelDriver",Failed)
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",sim), \
            mock.patch.object(probe,"probe_rpcs") as rpc:
        result=probe.run_probe(app,tmp_path/"failed-ui-runner.json")
    assert result["status"]=="FAIL" and result["error"]=="ui_driver_test_failed"
    assert closed==[True] and result["ui_test_driver_cleanup"] is True
    assert result["cleanup"]=={"shutdown":True,"delete":True}
    assert [x[0] for x in sim.calls].count("launch")==1
    rpc.assert_not_called()


def test_pre_input_xctest_build_failure_has_only_bounded_owned_diagnostic(app,tmp_path,monkeypatch):
    class FailedBuild(ModeledUIDriver):
        def start(self):raise probe.DriverError("ui_driver_build_failed")
        def build_failure_log(self):return b"BUILD-ONLY-"+b"x"*20000
        def build_metadata_diagnostic(self):return {"schema":1,"scope":"pre-input-generated-xctestrun",
            "check":"root_schema","format_version_type":"int","format_version":1,"raw_path":"DO-NOT-EXPORT"}
    sim=FakeSimctl(tmp_path/"failed-ui-build")
    monkeypatch.setattr(probe,"ProbePromptCancelDriver",FailedBuild)
    with mock.patch.object(probe.sys,"platform","darwin"),mock.patch.object(probe,"_simctl",sim):
        result=probe.run_probe(app,tmp_path/"failed-ui-build.json")
    assert result["status"]=="FAIL" and result["error"]=="ui_driver_build_failed"
    assert not any(call[0]=="launch" for call in sim.calls)
    diagnostic=json.loads((tmp_path/"failed-ui-build-xctest-build.json").read_text())
    assert diagnostic["scope"]=="pre-input-xctest-build" and diagnostic["tail_bytes"]==16384
    assert len(diagnostic["text"].encode())==16384
    assert diagnostic["sha256"]==hashlib.sha256(diagnostic["text"].encode()).hexdigest()
    assert result["xctest_build_diagnostic"]=={key:diagnostic[key] for key in ("scope","tail_bytes","sha256")} | {"file_name":"failed-ui-build-xctest-build.json"}
    assert "text" not in result["xctest_build_diagnostic"]
    metadata=(tmp_path/"failed-ui-build-xctest-metadata.json").read_bytes()
    assert b"DO-NOT-EXPORT" not in metadata
    assert json.loads(metadata)=={"schema":1,"scope":"pre-input-generated-xctestrun","check":"root_schema",
        "format_version_type":"int","format_version":1}
    assert result["xctest_build_metadata"]=={"file_name":"failed-ui-build-xctest-metadata.json",
        "scope":"pre-input-generated-xctestrun","bytes":len(metadata),"sha256":hashlib.sha256(metadata).hexdigest()}
    assert result["cleanup"]=={"shutdown":True,"delete":True}


@pytest.mark.parametrize("changed",[
    {"check":"DO-NOT-EXPORT"},{"check":[]},{"candidate_count":True},{"target_count":130},
    {"format_version_type":"DO-NOT-EXPORT"},{"format_version":True},{"plist_sha256":"DO-NOT-EXPORT"},
    {"paths":{"test_host":{"type":"str","token_kind":"DO-NOT-EXPORT","owned":True,"exists":True}}},
    {"paths":{"test_host":{"type":[],"token_kind":"absolute","owned":True,"exists":True}}},
    {"bundles":{"runner":{"bundle_matches":1,"platforms_type":"list","platforms_exact":True}}}])
def test_generated_xctestrun_diagnostic_requires_finite_typed_metadata(changed):
    value={"schema":1,"scope":"pre-input-generated-xctestrun","check":"root_schema",**changed}
    with pytest.raises(probe.ProbeError,match="^official_ui_metadata_invalid$"):
        probe.official_ui_build_metadata(value)


def test_generated_xctestrun_diagnostic_projects_only_known_scalar_fields():
    value={"schema":1,"scope":"pre-input-generated-xctestrun","check":"runner_bundle","plist_bytes":123,
        "plist_sha256":"a"*64,"paths":{"test_host":{"type":"str","token_kind":"testroot","owned":True,
        "exists":True,"raw_path":"DO-NOT-EXPORT"},"unknown":"DO-NOT-EXPORT"},"bundles":{"runner":{
        "bundle_matches":True,"platforms_type":"list","platforms_exact":True,"identifier":"DO-NOT-EXPORT"}},
        "raw_plist":"DO-NOT-EXPORT"}
    projected=probe.official_ui_build_metadata(value)
    assert "DO-NOT-EXPORT" not in json.dumps(projected)
    assert projected["paths"]["test_host"]=={"type":"str","token_kind":"testroot","owned":True,"exists":True}
    assert projected["bundles"]["runner"]=={"bundle_matches":True,"platforms_type":"list","platforms_exact":True}


def test_failure_checkpoint_heartbeat_distinguishes_main_activity_without_exporting_payload(tmp_path):
    documents=tmp_path/"Documents";documents.mkdir()
    (documents/"embedded-probe-checkpoint.json").write_text(json.dumps({"schema":1,"stage":"server_starting","phase":1,
        "process_id":1234,"main_thread_checkpoint":True,"main_heartbeat_count":42,"checkpoint_count":45,
        "main_elapsed_seconds":11.5,"raw_log":"DO-NOT-EXPORT"}))
    observed=probe.failure_checkpoint(tmp_path)
    assert observed["process_id"]==1234 and observed["main_thread_checkpoint"] is True
    assert observed["main_heartbeat_count"]==42 and observed["checkpoint_count"]==45
    assert observed["main_elapsed_seconds"]==11.5 and 0<=observed["checkpoint_age_seconds"]<=60
    assert "DO-NOT-EXPORT" not in json.dumps(observed)


def test_safe_ci_failure_summary_keeps_finite_phase_pid_and_markers_only():
    report={"error":"ui_driver_deadline","native_checkpoint":{"stage":"server_starting","phase":1,
        "process_id":4321,"main_heartbeat_count":80,"checkpoint_count":83,"main_thread_checkpoint":True,
        "checkpoint_age_seconds":0.2,"status_age_seconds":0.3,"main_elapsed_seconds":20,"raw":"DO-NOT-EXPORT"},
        "xctest_failure":{"schema":1,"scope":"owned-public-xctest-failure","phase":"testing","error_code":"ui_driver_deadline",
            "ready_marker_observed":True,"test_spawned":True,"child_pid":1234,"child_exit_code":None,"phase_elapsed_seconds":300,
            "markers":{"foreground_observed":True,"prompt_waiting":True,"cancel_tapped":False,"unknown":"DO-NOT-EXPORT"},"raw":"DO-NOT-EXPORT"}}
    projected=probe.safe_failure_summary(report)
    assert projected["native"]["checkpoint_age_seconds"]==0.2 and projected["native"]["main_heartbeat_count"]==80
    assert projected["xctest"]["child_exit_code"] is None and projected["xctest"]["phase"]=="testing"
    assert projected["xctest"]["markers"]=={"foreground_observed":True,"prompt_waiting":True,"cancel_tapped":False}
    assert "DO-NOT-EXPORT" not in json.dumps(projected)
    report["error"]="DO-NOT-EXPORT";report["native_checkpoint"]["stage"]="DO-NOT-EXPORT"
    assert probe.safe_failure_summary(report)["error_code"]=="probe_failed"


def test_native_probe_heartbeat_is_read_only_and_has_no_new_lifecycle_or_credential_dispatch():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    recorder=source.split('- (void)recordCheckpoint:(NSString *)stage {',1)[1].split('- (BOOL)observeOctoBudgetBeforeOriginal',1)[0]
    assert '@"process_id":@(getpid())' in recorder and '@"main_thread_checkpoint":@((BOOL)NSThread.isMainThread)' in recorder
    assert '@"main_heartbeat_count":@(self.mainHeartbeatCount)' in recorder and '++self.checkpointCount' in recorder
    assert '++self.mainHeartbeatCount' in source and 'credential' not in recorder


@pytest.mark.parametrize("profile_kind",["source","target"])
def test_account_fixture_rejects_lost_love_progress_even_when_seven_old_tables_survive(real_account_observer,profile_kind):
    observer,manager,state=real_account_observer
    native,source_ack,target_ack=complete_account_observer(observer,manager,state)
    profile=getattr(observer,profile_kind)
    with state.connect() as db:
        db.execute("DELETE FROM profile_love_progress WHERE profile=?",(profile,))
    assert all(state.account_snapshot(profile)[0]["tables"][table] for table in probe.ACCOUNT_TABLES if table!="profile_love_progress")
    with pytest.raises(probe.ProbeError,match="settings_account_fixture_failed"):
        observer.verify(native)
    with pytest.raises(probe.ProbeError,match="settings_account_fixture_failed"):
        observer.verify_persisted()


@pytest.mark.parametrize("rotated",[False,True])
def test_actual_language_observer_tracks_each_handler_identity_and_rejects_previous_save_ack(rotated):
    import re
    import subprocess
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    hook_source=source.split('static NSString *const ProbeReplyHook =',1)[1].split('static void ProbePollLanguageAttempt',1)[0]
    saving=source.split('static void ProbeAutoSaveLanguage(',1)[1].split('static NSString *ProbeChromeTitle',1)[0]
    setup_source=saving.split('NSString *setup=[ProbeReplyHook stringByAppendingFormat:',1)[1].split(',next];',1)[0]
    extract=lambda value:"".join(json.loads(item) for item in re.findall(r'@?("(?:\\.|[^"\\])*")',value))
    hook=extract(hook_source);setup=extract(setup_source)
    program="const rotated="+json.dumps(rotated)+";const hook="+json.dumps(hook)+";const setup="+json.dumps(setup)+r""";
const assert=require('node:assert/strict');let serial=0;const sent=[];
function freshHandler(){return {postMessage(value){sent.push(value);}};}
const window={webkit:{messageHandlers:{idolyServer:freshHandler()}},idolyServerReply(){}};
class Event{constructor(type,options){this.type=type;this.bubbles=options.bubbles;}}
const select={value:'ko',dispatchEvent(event){assert.equal(event.type,'change');assert.equal(event.bubbles,true);
 window.webkit.messageHandlers.idolyServer.postMessage({id:++serial,action:'save_options',language:this.value});}};
const form={},document={getElementById(id){return id==='language'?select:id==='options-form'?form:null;}};
function run(language){assert.equal(eval(hook+setup.replace('%@',language)),true);}
function reply(id,language){window.idolyServerReply(id,{id,ok:true,result:{options:{language},effective_options:{language:'ko'}}});}
run('en');assert.equal(sent.length,1);const first=window.__idolyProbeOptionsRequest;assert.equal(first.language,'en');
reply(first.id,'en');assert.equal(window.__idolyProbeGameAck.id,first.id);
if(rotated)window.webkit.messageHandlers.idolyServer=freshHandler();
run('ko');assert.equal(sent.length,2,'each real save forwarded exactly once');const second=window.__idolyProbeOptionsRequest;
assert.equal(second.language,'ko');assert.notEqual(first.id,second.id);assert.equal(window.__idolyProbeGameAck,null);
reply(first.id,'en');assert.equal(window.__idolyProbeGameAck,null,'previous save ACK cannot own the new save');
reply(second.id,'ko');assert.deepEqual(window.__idolyProbeGameAck,{id:second.id,language:'ko',effective:'ko'});
assert.equal(select.value,'ko');assert.equal(window.webkit.messageHandlers.idolyServer.postMessage,window.__idolyProbeTransportObserver);
"""
    checked=subprocess.run(["node"],input=program,text=True,capture_output=True,timeout=5)
    assert checked.returncode==0,checked.stderr


def test_language_observer_identity_diagnostics_are_finite_and_preserve_fifth_run_context():
    observation={"selected_language":"ko","observer_matches_current_handler":False,"request_observed":False,"timed_out":True,
        "raw_handler":"DO-NOT-EXPORT"}
    projected=probe.language_save_observation(observation)
    assert projected["selected_language"]=="ko" and projected["observer_matches_current_handler"] is False
    summary=probe.safe_failure_summary({"error":"language_save_failed","failed_run_index":4,
        "native_checkpoint":{"stage":"settings_official_prompt_checked","language_observation":{"language_save":observation}}})
    assert summary["run_index"]==4 and summary["native"]["language_save"]==projected
    assert "DO-NOT-EXPORT" not in json.dumps(summary)


def startup_failure_fixture():
    return {"schema":1,"scope":"ios-startup-failure","stage":"catalog","error_code":"invalid_input",
            "error_type":"ValueError","frames":[{"file":"public_payload_transaction.py","function":"_need","line":61}]}


def write_startup_failure_fixture(container, value=None):
    data = container / "Library/Application Support/IdolyPrideLocal"
    data.mkdir(parents=True, exist_ok=True)
    path = data / probe.STARTUP_FAILURE_FILE
    path.write_text(json.dumps(value if value is not None else startup_failure_fixture()))
    return path


def test_startup_failure_observation_is_reprojected_before_simulator_cleanup(app, tmp_path):
    controller = FakeSimctl(tmp_path / "container", startup_failure=True)
    def command(arguments, timeout):
        result = controller(arguments, timeout)
        if arguments[0] == "launch": write_startup_failure_fixture(controller.container)
        return result
    with mock.patch.object(probe.sys, "platform", "darwin"), mock.patch.object(probe, "_simctl", command), mock.patch.object(probe, "probe_rpcs") as rpc:
        result = probe.run_probe(app, tmp_path / "failure.json")
    assert result["status"] == "FAIL" and result["error"] == "native_startup_failed"
    assert result["host_startup_failure"] == {**startup_failure_fixture(),"available":True}
    assert result["cleanup"]["delete"] is True
    assert probe.safe_failure_summary(result)["host_startup_failure"] == startup_failure_fixture()
    rpc.assert_not_called()


@pytest.mark.parametrize("damage", ["symlink", "parent-symlink", "hardlink", "oversized", "duplicate", "path", "credential", "unknown-type", "boolean-line", "unhashable", "bad-errno", "boolean-errno"])
def test_startup_failure_reader_rejects_unsafe_or_unbounded_diagnostics(tmp_path, damage):
    container = tmp_path / "container"; container.mkdir()
    value = startup_failure_fixture(); path = write_startup_failure_fixture(container, value)
    outside = tmp_path / "outside"; outside.write_text("provider-password-private")
    if damage == "symlink": path.unlink(); path.symlink_to(outside)
    elif damage == "parent-symlink":
        directory = path.parent; directory.rename(directory.with_name("moved")); directory.symlink_to(directory.with_name("moved"), target_is_directory=True)
    elif damage == "hardlink": probe.os.link(path, path.with_name("extra-link"))
    elif damage == "oversized": path.write_bytes(b"x" * (probe.STARTUP_FAILURE_MAX+1))
    elif damage == "duplicate": path.write_text('{"schema":1,"schema":1}')
    else:
        if damage == "path": value["frames"][0]["file"] = "/private/provider/password.py"
        elif damage == "credential": value["password"] = "never disclose"
        elif damage == "unknown-type": value["error_type"] = "SecretPasswordType"
        elif damage == "boolean-line": value["frames"][0]["line"] = True
        elif damage == "unhashable": value["stage"] = ["password"]
        elif damage == "bad-errno": value["errno"] = 4097
        elif damage == "boolean-errno": value["errno"] = True
        path.write_text(json.dumps(value))
    observed = probe.read_startup_failure(container)
    assert observed == {"schema":1,"scope":"ios-startup-failure","available":False,"read_code":"startup_diagnostic_invalid"}
    assert "password" not in json.dumps(observed).lower() and outside.read_text() == "provider-password-private"


def test_startup_failure_reader_missing_and_safe_contract_parity(tmp_path):
    from idoly_local import ios_host
    assert probe.STARTUP_FAILURE_FILES == ios_host.STARTUP_FAILURE_FILES
    assert probe.STARTUP_FAILURE_TYPES == ios_host.STARTUP_FAILURE_TYPES
    assert probe.STARTUP_FAILURE_CODES == ios_host.STARTUP_FAILURE_CODES
    assert probe.STARTUP_FAILURE_STAGES == ios_host.STARTUP_FAILURE_STAGES
    assert probe.read_startup_failure(tmp_path)["read_code"] == "startup_diagnostic_missing"


def test_startup_failure_reader_preserves_only_integer_errno(tmp_path):
    value = startup_failure_fixture(); value["errno"] = 13
    container = tmp_path / "container"; container.mkdir()
    write_startup_failure_fixture(container, value)
    assert probe.read_startup_failure(container) == {**value, "available": True}
    assert probe.safe_failure_summary({"host_startup_failure": {**value, "available": True}})["host_startup_failure"] == value



def test_public_official_cancel_precedes_independent_zip_and_account_work_without_dropping_gates():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    flow=source.split("- (void)probeMenuAfterLaunch:(NSMutableDictionary *)report {",1)[1].split("- (void)observeMenuDismissal:",1)[0]
    order=("ProbeDiagnosticsCopy(web", "ProbeOfficialPrompt(web", "ProbeZIPImportPicker(web",
           "ProbeZIPRoundTrip(web", "ProbeAccountManagement(web", "[self saveNextLanguage:web")
    assert all(flow.count(call)==1 for call in order)
    assert [flow.index(call) for call in order]==sorted(flow.index(call) for call in order)
    for failure in ("settings_diagnostics_copy_failed", "settings_official_prompt_failed", "settings_zip_import_picker_failed",
                    "settings_zip_roundtrip_failed", "settings_account_management_failed", "language_save_failed"):
        assert f'failProbe:@"{failure}"' in flow
    for key in probe.ZIP_ROUNDTRIP_FLAGS:
        assert f'@"{key}"' in flow
    for key in probe.OFFICIAL_PROMPT_FLAGS:
        assert f'@"{key}"' in flow
    assert 'probeRunIndex==0' in flow and 'credential_submission_performed' in flow


def test_diagnostic_progress_does_not_extend_any_existing_native_or_public_deadline():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    roundtrip=source.split("static void ProbeZIPRoundTrip(WKWebView",1)[1].split("static NSString *const ProbeAccountScenario",1)[0]
    assert '@"deadline":@(started+120)' in roundtrip
    assert '120*NSEC_PER_SEC' in roundtrip
    prompt=source.split("static void ProbeOfficialPrompt(WKWebView",1)[1].split("@interface",1)[0]
    assert '30*NSEC_PER_SEC' in prompt
    assert 'probeRunIndex!=0' in prompt and '@"first-cold-run-only"' in prompt
    swift=(Path(__file__).resolve().parents[1]/"ios-unified/probe/ui-tests/OfficialPromptCancelTests.swift").read_text()
    assert 'timeout: 60' in swift and 'timeout: 180' in swift
    assert 'ProbeOfficialActivateCancel' not in source


@pytest.mark.parametrize("phase", sorted(probe.ZIP_PROGRESS_PHASES))
def test_zip_progress_accepts_only_fixed_phase_and_scalar_observations(phase):
    value={"schema":1,"phase":phase,"observations":8,"elapsed_seconds":12.5,"exported_files":3,
           "imported_files":2,"failed_files":0,"copied_bytes":4096,"total_bytes":4096,
           "backend_state":"export_ready", **{key:False for key in probe.ZIP_PROGRESS_FLAGS}}
    assert probe.zip_progress_observation(value)==value


@pytest.mark.parametrize("value", (None, [], {}, {"schema":True,"phase":"export_waiting"},
    {"schema":2,"phase":"export_waiting"}, {"schema":1,"phase":"arbitrary-path"},
    {"schema":1,"phase":[]}, {"schema":1,"phase":True}))
def test_zip_progress_rejects_unknown_schema_or_phase(value):
    assert probe.zip_progress_observation(value)=={}


@pytest.mark.parametrize("field,bad", [(key,value) for key in probe.ZIP_PROGRESS_FLAGS for value in (1, "true")] + [
    ("observations",True),("observations",-1),("observations",1001),("observations",1.0),
    ("exported_files",1000001),("imported_files",float("inf")),("failed_files",-1),
    ("copied_bytes",True),("copied_bytes",1024**4+1),("total_bytes",-1),
    ("elapsed_seconds",True),("elapsed_seconds",float("nan")),("elapsed_seconds",float("inf")),
    ("elapsed_seconds",-1),("elapsed_seconds",120.01),("backend_state","user-supplied-text")])
def test_zip_progress_drops_nonfinite_or_unbounded_optional_fields(field,bad):
    value={"schema":1,"phase":"import_waiting",field:bad}
    assert probe.zip_progress_observation(value)=={"schema":1,"phase":"import_waiting"}


def test_zip_progress_source_emits_only_changed_bounded_safe_observations():
    source=(Path(__file__).resolve().parents[1]/"ios-unified/probe/main.m").read_text()
    helper=source.split("static void ProbeZIPRoundTripProgress(",1)[1].split("static void ProbeZIPRoundTripPoll(",1)[0]
    assert '[state[@"last_progress"] isEqual:clean]' in helper
    assert 'emitted>=64 && !terminal' in helper
    assert 'MIN(1000,' in helper and 'MIN(120.0,' in helper
    for private in ('job[@"output_path"]','job[@"url"]','job[@"password"]','job[@"user_id"]','job[@"error"]'):
        assert private not in helper
    assert 'CFBooleanGetTypeID()' in helper and 'isfinite(count)' in helper
    phase_part=helper.split('if (![@[',1)[1].split('containsObject:phase]',1)[0]
    import re
    phases={json.loads(piece) for piece in re.findall(r'@?("(?:\\.|[^"\\])*")',phase_part)}
    assert phases==set(probe.ZIP_PROGRESS_PHASES)


def test_zip_progress_checkpoint_and_summary_never_export_paths_urls_or_credentials(tmp_path):
    documents=tmp_path/"Documents";documents.mkdir()
    progress={"schema":1,"phase":"source_hashing","observations":4,"elapsed_seconds":1.5,
        "export_ready":True,"exported_files":2,"backend_state":"export_ready",
        **{key:"DO-NOT-EXPORT" for key in ("path","url","output_path","error","user_id","password","raw_input","job")}}
    value={"schema":1,"stage":"settings_zip_roundtrip_progress","zip_roundtrip_progress":progress}
    (documents/"embedded-probe-checkpoint.json").write_text(json.dumps(value))
    clean=probe.failure_checkpoint(tmp_path)
    assert clean["stage"]=="settings_zip_roundtrip_progress"
    assert clean["zip_roundtrip_progress"]=={key:progress[key] for key in ("schema","phase","observations","elapsed_seconds","export_ready","exported_files","backend_state")}
    summary=probe.safe_failure_summary({"error":"settings_zip_roundtrip_failed","native_checkpoint":clean})
    assert summary["native"]["zip_roundtrip_progress"]==clean["zip_roundtrip_progress"]
    assert "DO-NOT-EXPORT" not in json.dumps(clean)+json.dumps(summary)



def test_optional_process_sample_cannot_replace_original_failure_and_runs_before_cleanup(app,tmp_path):
    controller=FakeSimctl(tmp_path/"container")
    observed=native_report();observed["keyboard"]["during_init"]["field_creation_count"]=2
    sequence=[]
    def simctl(arguments,timeout):
        if arguments[0] in ("shutdown","delete"):sequence.append(arguments[0])
        return controller(arguments,timeout)
    class BrokenDiagnosticSampler:
        def __init__(self,*args):pass
        def prepare(self):return True
        def clear_launch(self):pass
        def note_launch(self,raw):pass
        def capture(self,checkpoint):
            sequence.append("sample")
            raise RuntimeError("DO-NOT-EXPORT")
    with mock.patch.object(probe.sys,"platform","darwin"), \
            mock.patch.object(probe,"_simctl",simctl), \
            mock.patch.object(probe,"OwnedProbeProcessSampler",BrokenDiagnosticSampler), \
            mock.patch(__name__+".native_report",return_value=observed):
        result=probe.run_probe(app,tmp_path/"failure-with-optional-sample.json")
    assert result["error"]=="keyboard_during_init_failed"
    assert result["process_sample"]["error_code"]=="sample_failed"
    assert sequence.index("sample")<sequence.index("shutdown")<sequence.index("delete")
    assert result["cleanup"]=={"shutdown":True,"delete":True}
    assert "DO-NOT-EXPORT" not in json.dumps(result)
