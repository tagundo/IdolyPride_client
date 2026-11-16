"""Date labels, seven-platform filenames and manual-only release wiring."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("calendar_release_identity", ROOT/"tools/release_identity.py")
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


@pytest.mark.parametrize("value", ["2026.11.16.1", "2026.11.16.2", "2024.02.29.99"])
def test_calendar_release_accepts_canonical_real_dates(value):
    assert identity.resolve_release_version(value) == value
    assert identity.release_tag(value) == "v" + value


@pytest.mark.parametrize("value", [None, True, 20261116, "", "0.3.35", "v2026.11.16.1",
    "2026.02.29.1", "2026.04.31.1", "0000.01.01.1", "2026.00.01.1", "2026.13.01.1",
    "2026.11.00.1", "2026.1.16.1", "2026.11.6.1", "2026.11.16", "2026.11.16.0",
    "2026.11.16.01", "2026.11.16.100", "2026.11.16.-1", "2026.11.16.1\n",
    "2026.11.16.1/other", "２０２６.11.16.1"])
def test_invalid_date_or_noncanonical_sequence_cannot_be_published(value):
    with pytest.raises(ValueError, match="release_version_invalid"):
        identity.resolve_release_version(value)


def test_every_public_download_identifies_release_platform_and_language():
    version = "2026.11.16.1"
    assert identity.asset_names(version) == {
        "IdolyPride-2026.11.16.1-Server-Android.apk",
        "IdolyPride-2026.11.16.1-Server-macOS-arm64.app.zip",
        "IdolyPride-2026.11.16.1-Unified-iOS.ipa",
        "IdolyPride-2026.11.16.1-Client-Android-arm64-ko.apk",
        "IdolyPride-2026.11.16.1-Client-Android-arm64-ja.apk",
        "IdolyPride-2026.11.16.1-Client-Android-arm64-en.apk",
        "IdolyPride-2026.11.16.1-Client-PlayCover-ko.ipa",
    }
    assert not identity.asset_names(version) & identity.asset_names("2026.11.16.2")
    assert not identity.asset_names(version) & identity.asset_names("2026.11.17.1")


@pytest.mark.parametrize("name", ["unknown.apk", "../IdolyPride-Local-Server-Android.apk",
    "IdolyPride-Local-Server-Android.apk?download=1", "IdolyPride-2026.11.16.1-Server-Android.apk", None])
def test_mapping_accepts_only_known_verified_raw_inputs(name):
    with pytest.raises(ValueError, match="release_asset_source_unknown"):
        identity.asset_name(name, "2026.11.16.1")


def test_identity_preview_does_not_publish_or_choose_a_clock_dependent_version():
    import json
    run = subprocess.run([sys.executable, "-B", str(ROOT/"tools/release_identity.py"),
        "--version", "2026.11.16.2"], capture_output=True, text=True, check=True)
    result = json.loads(run.stdout)
    assert result["release_version"] == "2026.11.16.2"
    assert result["tag"] == "v2026.11.16.2"
    assert result["date_timezone"] == "Asia/Seoul"
    assert set(result["filenames"].values()) == identity.asset_names("2026.11.16.2")


def workflow(name):
    return (ROOT/".github/workflows"/name).read_text()


def test_publishing_requires_explicit_manual_opt_in_and_quoted_validated_version():
    release = workflow("release-all-platforms.yml")
    events = release.split("\npermissions:", 1)[0]
    assert "\n  workflow_dispatch:" in events and "\n  push:" not in events
    assert re.search(r"(?m)^      release_version:\n        description: [^\n]+\n        type: string\n        required: true$", events)
    assert "IDOLY_RELEASE_VERSION: '${{ inputs.release_version }}'" in release
    publish = release.split("\n  publish:\n", 1)[1]
    condition = publish.split("\n    runs-on:", 1)[0]
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "&& inputs.publish" in condition
    assert "github.event_name == 'push'" not in condition
    assert '--release-version "$IDOLY_RELEASE_VERSION"' in publish
    assert "${{ inputs.release_version }}" not in publish


def test_focused_checks_have_no_publication_credentials_or_build_steps():
    checks = workflow("verify-release-naming.yml")
    assert "\npermissions:\n  contents: read\n" in checks
    assert "contents: write" not in checks and "GH_TOKEN" not in checks
    job = checks.split("\n  naming:\n", 1)[1]
    assert "\n    permissions:" not in job and "\n    env:" not in job
    assert "tests/test_publish_optimized_release.py" in job
    assert "tests/test_release_identity.py" in job
    assert "tools/publish_optimized_release.py" not in job
