"""Public Android OS evidence cannot be replaced by numeric or synthetic claims."""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_interface_contract", ROOT / "tools/release_interface_contract.py")
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def passed():
    return {"actual_os_api_resource_configuration": {
        "authority": "Android public LocaleManager and WindowManager shell APIs", "sdk": 34,
        "languages": [
            {"language": "en", "title": "IDOLY PRIDE Server  0.3.37", "start": "Start server", "stop": "Stop server", "status": "Stopped", "actual_ui_observed": True},
            {"language": "ja", "title": "アイプラサーバー  0.3.37", "start": "サーバー開始", "stop": "サーバー停止", "status": "停止中", "actual_ui_observed": True},
            {"language": "ko", "title": "아이프라 서버  0.3.37", "start": "서버 시작", "stop": "서버 중지", "status": "중지됨", "actual_ui_observed": True}],
        "running_languages": [
            {"language": "en", "title": "IDOLY PRIDE Server  0.3.37", "start": "Start server", "stop": "Stop server", "status": "Running", "actual_ui_observed": True},
            {"language": "ja", "title": "アイプラサーバー  0.3.37", "start": "サーバー開始", "stop": "サーバー停止", "status": "実行中", "actual_ui_observed": True},
            {"language": "ko", "title": "아이프라 서버  0.3.37", "start": "서버 시작", "stop": "서버 중지", "status": "실행 중", "actual_ui_observed": True}],
        "wide": {
            "console": {"width_px": 1920, "height_px": 1080, "density_dpi": 320, "visible_categories": 5,
                "minimum_navigation_target_dp": 44.0, "help_closed": True, "default_panel": "checks", "default_panel_expanded": False},
            "graphics": {"width_px": 1920, "height_px": 1080, "density_dpi": 320, "visible_categories": 5,
                "minimum_navigation_target_dp": 44.0, "help_closed": True, "default_panel": "graphics", "default_panel_expanded": True},
            "actual_rotation": 1},
        "restored_portrait": {"actual_rotation": 0, "width_px": 1080, "height_px": 1920,
            "interface_language": "ko", "console_selected": True}}}


def test_complete_current_public_os_observations_are_required_and_copied():
    report = passed()
    # The contract composes with, rather than replacing, the 32 existing gates.
    report["existing_preservation_gate"] = True
    result = contract.validate_android(report)
    assert result == report[contract.FIELD]
    result["languages"][0]["title"] = "changed"
    assert report[contract.FIELD]["languages"][0]["title"] == "IDOLY PRIDE Server  0.3.37"


@pytest.mark.parametrize("report", [None, [], True, 1, {}, {contract.FIELD: True}, {contract.FIELD: {}}])
def test_missing_or_wrong_container_cannot_satisfy_public_os_gate(report):
    with pytest.raises(ValueError):
        contract.validate_android(report)


@pytest.mark.parametrize("field,value", [("authority", "synthetic resource override"), ("sdk", 33),
    ("sdk", 35), ("sdk", True), ("sdk", 34.0), ("sdk", "34"), ("languages", None), ("running_languages", None)])
def test_current_authority_sdk_and_language_scope_are_exact(field, value):
    report = passed(); report[contract.FIELD][field] = value
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("section", ["languages", "running_languages"])
@pytest.mark.parametrize("change", ["reverse", "duplicate", "missing", "extra"])
def test_all_three_language_readbacks_must_follow_en_ja_ko_order(section, change):
    report = passed(); values = report[contract.FIELD][section]
    if change == "reverse": values.reverse()
    elif change == "duplicate": values[1] = deepcopy(values[0])
    elif change == "missing": values.pop()
    else: values.append(deepcopy(values[-1]))
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("section", ["languages", "running_languages"])
@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("field,value", [("title", "아이프라 서버  0.3.37"), ("title", 1),
    ("start", "wrong"), ("stop", "wrong"), ("actual_ui_observed", False), ("actual_ui_observed", 1)])
def test_titles_controls_and_real_ui_boolean_are_observed_in_each_language(section, index, field, value):
    report = passed(); value = "wrong" if field == "title" and index == 2 else value
    report[contract.FIELD][section][index][field] = value
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("panel", ["console", "graphics"])
@pytest.mark.parametrize("field,value", [("width_px", True), ("width_px", 1920.0), ("width_px", 0),
    ("width_px", 16385), ("height_px", "1080"), ("height_px", 1920), ("density_dpi", True),
    ("density_dpi", 320.0), ("density_dpi", 119), ("density_dpi", 1001),
    ("visible_categories", 4), ("visible_categories", 5.0), ("visible_categories", True),
    ("minimum_navigation_target_dp", True), ("minimum_navigation_target_dp", 44),
    ("minimum_navigation_target_dp", 43.99), ("minimum_navigation_target_dp", float("nan")),
    ("minimum_navigation_target_dp", float("inf")), ("minimum_navigation_target_dp", 541.0),
    ("help_closed", False), ("help_closed", 1), ("default_panel", "wrong"), ("default_panel_expanded", 1)])
def test_landscape_bounds_density_targets_visibility_help_and_fold_types_are_strict(panel, field, value):
    report = passed(); report[contract.FIELD]["wide"][panel][field] = value
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("panel", ["console", "graphics"])
def test_each_default_fold_state_is_required(panel):
    report = passed(); value = report[contract.FIELD]["wide"][panel]
    value["default_panel_expanded"] = not value["default_panel_expanded"]
    with pytest.raises(ValueError): contract.validate_android(report)


def test_console_and_graphics_are_observed_in_the_same_native_window():
    report = passed(); report[contract.FIELD]["wide"]["graphics"]["width_px"] = 1919
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("section,field,value", [("wide", "actual_rotation", True),
    ("wide", "actual_rotation", 0), ("wide", "actual_rotation", 1.0),
    ("restored_portrait", "actual_rotation", False), ("restored_portrait", "actual_rotation", 1),
    ("restored_portrait", "actual_rotation", 0.0), ("restored_portrait", "width_px", True),
    ("restored_portrait", "height_px", 1080), ("restored_portrait", "height_px", 16385),
    ("restored_portrait", "interface_language", "en"), ("restored_portrait", "console_selected", 1),
    ("restored_portrait", "console_selected", False)])
def test_actual_rotation_and_final_korean_portrait_console_restore_are_required(section, field, value):
    report = passed(); report[contract.FIELD][section][field] = value
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("path", [(), ("languages", 0), ("running_languages", 0), ("wide",), ("wide", "console"),
    ("wide", "graphics"), ("restored_portrait",)])
def test_missing_and_extra_nested_claims_are_rejected(path):
    for change in ("remove", "extra"):
        report = passed(); value = report[contract.FIELD]
        for key in path: value = value[key]
        if change == "remove": del value[next(iter(value))]
        else: value["unobserved_claim"] = True
        with pytest.raises(ValueError): contract.validate_android(report)


def test_exact_language_labels_and_server_version_match_packaged_source():
    for language, expected in contract.READBACKS.items():
        path = ROOT / "android-server/app/src/main/res" / ("values-" + language) / "strings.xml"
        rows = {node.get("name"): "".join(node.itertext()) for node in ET.parse(path).getroot() if node.tag == "string"}
        assert tuple(rows[key] for key in ("app_name", "start_server", "stop_server")) == expected
        assert tuple(rows[key] for key in ("status_stopped", "status_running")) == contract.STATUS_READBACKS[language]
    tree = ast.parse((ROOT / "tools/release_platform_builds.py").read_text())
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Tuple) and any(isinstance(item, ast.Name) and item.id == "VERSION" for item in target.elts) for target in node.targets))
    assert ast.literal_eval(assignment.value)[0] == contract.VERSION


@pytest.mark.parametrize("section", ["languages", "running_languages"])
@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("value", [None, True, 1, "wrong"])
def test_each_stopped_and_running_status_is_an_exact_real_language_readback(section, index, value):
    report = passed(); report[contract.FIELD][section][index]["status"] = value
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("section,wrong", [("languages", "중지됨"), ("running_languages", "실행 중")])
@pytest.mark.parametrize("index", [0, 1])
def test_observed_korean_status_regression_in_english_or_japanese_is_rejected(section, wrong, index):
    report = passed(); report[contract.FIELD][section][index]["status"] = wrong
    with pytest.raises(ValueError): contract.validate_android(report)


def test_cached_stopped_status_cannot_satisfy_running_service_proof():
    report = passed(); report[contract.FIELD]["running_languages"] = deepcopy(report[contract.FIELD]["languages"])
    with pytest.raises(ValueError): contract.validate_android(report)


@pytest.mark.parametrize("section", ["languages", "running_languages"])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_stopped_and_running_rows_without_status_are_rejected(section, index):
    report = passed(); del report[contract.FIELD][section][index]["status"]
    with pytest.raises(ValueError): contract.validate_android(report)


def test_legacy_os_receipt_without_running_language_observations_is_rejected():
    report = passed(); del report[contract.FIELD]["running_languages"]
    with pytest.raises(ValueError): contract.validate_android(report)
