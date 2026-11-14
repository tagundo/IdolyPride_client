import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "ios-unified/ci_build.py"
spec = importlib.util.spec_from_file_location("unified_ci", path)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def runtime(version, available=True, kind="iOS"):
    return {"identifier": "com.apple.CoreSimulator.SimRuntime." + kind + "-" + version.replace(".", "-"),
            "version": version, "isAvailable": available}


def test_active_xcode_18_sdk_avoids_newer_installed_26_runtime():
    catalog = {"runtimes": [runtime("26.2"), runtime("18.5"), runtime("18.4")]}
    assert ci.compatible_runtime("18.5", catalog).endswith("iOS-18-5")


def test_unavailable_or_other_platform_runtime_cannot_win():
    catalog = {"runtimes": [runtime("18.5", False), runtime("18.5", kind="tvOS"), runtime("18.4")]}
    assert ci.compatible_runtime("18.5.0", catalog).endswith("iOS-18-4")


def test_no_compatible_runtime_fails_before_simulator_creation():
    with pytest.raises(ValueError, match="compatible"):
        ci.compatible_runtime("18.5", {"runtimes": [runtime("26.2")]})
