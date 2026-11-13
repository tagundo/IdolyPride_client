"""Data delivery accepts only the versioned server archive alongside app files."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("binary_lfs_name_policy",
    Path(__file__).resolve().parents[1] / "tools/publish_binary_bundle_lfs.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.mark.parametrize("name", (
    "IdolyPride-ServerData-v0.3.23.zip", "IdolyPride-ServerData-v0.3.19.zip",
    "IdolyPride-Local-Server-Android.apk", "IdolyPride-Local-Server-macOS-arm64.app.zip",
    "IdolyPride-6.1.1-Local-PlayCover.ipa",
))
def test_supported_versioned_data_and_existing_app_download_names(name):
    assert tool.artifact_name_allowed(name)


@pytest.mark.parametrize("name", (
    "archive.zip", "state.db", "IdolyPride-ServerData-latest.zip", "IdolyPride-ServerData-v0.3.zip",
    "../IdolyPride-ServerData-v0.3.23.zip", "a/IdolyPride-ServerData-v0.3.23.zip",
    "IdolyPride-ServerData-v0.3.23.zip\n", "IdolyPride-ServerData-v0.3.23.zip.exe", None, 23,
))
def test_unrelated_archives_paths_and_malformed_versions_remain_rejected(name):
    assert not tool.artifact_name_allowed(name)
