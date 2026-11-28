"""Publication rejects skipped, replaced or unpinned recovery contract evidence."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tools import publish_optimized_release as release

SOURCE = "a" * 40
NAMES = (
    "test_generated_preference_supplement_matches_recorded_original_tables",
    "test_actual_pinned_supplement_fallback_updates_owned_card_and_decoration",
    "test_actual_pinned_media_inventory_includes_all_verified_decorations",
)


@pytest.fixture
def evidence(tmp_path):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests="3", failures="0", errors="0", skipped="0")
    for name in NAMES:
        ET.SubElement(suite, "testcase", name=name, classname="tests.test_profile_preferences")
    path = tmp_path / "preference-contracts.xml"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    latest_root = ET.Element("testsuites")
    latest_suite = ET.SubElement(latest_root, "testsuite", tests="2", failures="0", errors="0", skipped="0")
    version = release.LATEST_SERVER_DATA.load_pin()["upgrade_proof"]["original_master"]["version"]
    for platform in ("android", "ios"):
        case = ET.SubElement(latest_suite, "testcase", name="test_actual_latest_media_preparation_and_restart_preserve_accounts[" + platform + "]")
        properties = ET.SubElement(case, "properties")
        for name, value in {"payload_sha256": release.DATA_PIN["sha256"], "master_version": version,
                            "resource_platform": platform}.items():
            ET.SubElement(properties, "property", name=name, value=value)
    ET.ElementTree(latest_root).write(tmp_path / "latest-media-contracts.xml", encoding="utf-8", xml_declaration=True)
    contracts = {
        # The three actual preference master tests consume the immutable base
        # donor. Native packages independently pin the prepared Love upgrade.
        "input": dict(release.BASE_DATA_PIN),
        "master_version": "961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60",
        "selected_counts": {"CardImage": 611, "Decoration": 361},
        "module_sha256": release.digest(release.ROOT / "src/idoly_local/preference_master_data.py"),
        "supplement_report_sha256": release.digest(release.ROOT / "docs/preference-master-data.json"),
        "tests": {"count": 3, "failures": 0, "errors": 0, "skipped": 0},
        "junit": {"name": path.name, "bytes": path.stat().st_size, "sha256": release.digest(path)},
    }
    report = {"schema": 1, "status": "PASS", "source_commit": SOURCE,
              "validation": {"pytest_passed": True, "compileall_passed": True,
                             "actual_preference_master_contracts_passed": True},
              "preference_master_contracts": contracts}
    return report, tmp_path, path


def test_all_required_real_master_cases_and_source_digests_are_accepted(evidence):
    report, directory, _ = evidence
    assert release.validate_portable(report, SOURCE, directory) is None


@pytest.mark.parametrize("change", (
    "missing-contracts", "false-gate", "wrong-input", "wrong-version", "wrong-counts",
    "module-changed", "proof-changed", "too-few", "boolean-count", "reported-skip",
    "reported-error", "reported-failure", "junit-name", "junit-bytes", "junit-hash",
))
def test_report_flags_cannot_substitute_for_actual_pinned_contracts(evidence, change):
    original, directory, _ = evidence
    report = deepcopy(original)
    proof = report["preference_master_contracts"]
    if change == "missing-contracts": del report["preference_master_contracts"]
    elif change == "false-gate": report["validation"]["actual_preference_master_contracts_passed"] = False
    elif change == "wrong-input": proof["input"]["sha256"] = "0" * 64
    elif change == "wrong-version": proof["master_version"] = "other"
    elif change == "wrong-counts": proof["selected_counts"]["CardImage"] = 610
    elif change == "module-changed": proof["module_sha256"] = "0" * 64
    elif change == "proof-changed": proof["supplement_report_sha256"] = "0" * 64
    elif change == "too-few": proof["tests"]["count"] = 2
    elif change == "boolean-count": proof["tests"]["count"] = True
    elif change == "reported-skip": proof["tests"]["skipped"] = 1
    elif change == "reported-error": proof["tests"]["errors"] = 1
    elif change == "reported-failure": proof["tests"]["failures"] = 1
    elif change == "junit-name": proof["junit"]["name"] = "../elsewhere.xml"
    elif change == "junit-bytes": proof["junit"]["bytes"] += 1
    elif change == "junit-hash": proof["junit"]["sha256"] = "0" * 64
    with pytest.raises(release.ReleaseError):
        release.validate_portable(report, SOURCE, directory)


@pytest.mark.parametrize("change", ("skip", "failure", "error", "case-replaced", "case-missing", "invalid-xml"))
def test_junit_is_independently_checked_even_when_report_claims_success(evidence, change):
    report, directory, path = evidence
    tree = ET.parse(path)
    cases = tree.findall(".//testcase")
    if change in ("skip", "failure", "error"):
        ET.SubElement(cases[0], {"skip": "skipped"}.get(change, change))
    elif change == "case-replaced":
        cases[0].set("name", "unrelated-passing-test")
    elif change == "case-missing":
        tree.find(".//testsuite").remove(cases[0])
    if change == "invalid-xml": path.write_bytes(b"<not-complete")
    else: tree.write(path, encoding="utf-8", xml_declaration=True)
    # Digest correctness alone must not permit skipped or substituted cases.
    report["preference_master_contracts"]["junit"].update(
        bytes=path.stat().st_size, sha256=release.digest(path))
    with pytest.raises(release.ReleaseError):
        release.validate_portable(report, SOURCE, directory)


def test_prepared_native_payload_cannot_relabel_the_immutable_preference_input(evidence):
    report, directory, _ = evidence
    assert release.DATA_PIN != release.BASE_DATA_PIN
    report["preference_master_contracts"]["input"] = dict(release.DATA_PIN)
    with pytest.raises(release.ReleaseError, match="public_input_pin_differs"):
        release.validate_portable(report, SOURCE, directory)


def test_successful_base_contracts_cannot_replace_actual_latest_media_evidence(evidence):
    report, directory, _ = evidence
    (directory / "latest-media-contracts.xml").unlink()
    with pytest.raises(release.ReleaseError, match="latest_media_junit_missing"):
        release.validate_portable(report, SOURCE, directory)
