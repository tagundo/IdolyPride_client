"""Public XCTest driver for one Cancel tap in an already-running Probe.

Only this driver's fixed project and newly owned temporary products are used.
It does not launch, activate, terminate, install, reset or discover a Probe or
Simulator. A successful log line alone is never accepted as test evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import uuid

_SOURCE_ROOT = Path(__file__).resolve().parent
_DRIVER_PATH = Path(__file__).resolve()
SOURCE_PATHS = (
    "ui_test_driver.py",
    "ui-tests/IdolyProbeCancelUITests.xcodeproj/project.pbxproj",
    "ui-tests/IdolyProbeCancelUITests.xcodeproj/xcshareddata/xcschemes/IdolyProbeCancelUITests.xcscheme",
    "ui-tests/CancelDriverHost.swift",
    "ui-tests/OfficialPromptCancelTests.swift",
)
SCHEME = "IdolyProbeCancelUITests"
TEST_IDENTIFIER = SCHEME + "/OfficialPromptCancelTests/testCancelExistingProbePrompt"
READY_MARKER = b"IDOLY_CANCEL_UITEST_WAITING_FOR_PROBE"
DUMMY_BUNDLE = "local.idoly.cancel-driver-host"
RUNNER_BUNDLE = "local.idoly.cancel-driver-uitests.xctrunner"
_LOG_LIMIT = 2 * 1024 * 1024
_JSON_LIMIT = 4 * 1024 * 1024
_PLIST_LIMIT = 256 * 1024
DIAGNOSTIC_CHECKS = frozenset(("products", "candidate_count", "plist_read", "root_schema",
    "configuration_count", "target_count", "target_contract", "test_host_path", "test_bundle_path",
    "dummy_app_path", "runner_bundle", "dummy_bundle", "complete"))
DIAGNOSTIC_TYPES = frozenset(("absent", "dict", "list", "str", "int", "bool", "bytes", "other"))
DIAGNOSTIC_TOKEN_KINDS = frozenset(("absent", "testroot", "testhost", "absolute", "relative", "url", "other"))
ERROR_CODES = frozenset(("ui_driver_udid_invalid", "ui_driver_callback_invalid", "ui_driver_deadline",
    "ui_driver_state_invalid", "ui_driver_source_invalid", "ui_driver_source_changed", "ui_driver_spawn_failed",
    "ui_driver_log_limit", "ui_driver_io_failed", "ui_driver_build_failed", "ui_driver_xctestrun_invalid",
    "ui_driver_test_failed", "ui_driver_ready_missing", "ui_driver_result_failed", "ui_driver_result_invalid",
    "ui_driver_result_target_mismatch", "ui_driver_result_destination_mismatch", "ui_driver_result_count_mismatch",
    "ui_driver_result_method_mismatch", "ui_driver_result_not_success", "ui_driver_closed"))


class DriverError(RuntimeError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in ERROR_CODES else "ui_driver_io_failed"
        super().__init__(self.code)


def _need(value, code):
    if not value:
        raise DriverError(code)


def _read(path, maximum):
    try:
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= maximum,
              "ui_driver_result_invalid")
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        _need(len(data) == info.st_size and len(data) <= maximum, "ui_driver_result_invalid")
        return data
    except DriverError:
        raise
    except Exception:
        raise DriverError("ui_driver_io_failed") from None


def _source_pins():
    pins = {}
    try:
        for relative in SOURCE_PATHS:
            path = _DRIVER_PATH if relative == "ui_test_driver.py" else _SOURCE_ROOT / relative
            _need(path.resolve(strict=True) == path and not path.is_symlink(), "ui_driver_source_invalid")
            pins[relative] = hashlib.sha256(_read(path, _PLIST_LIMIT)).hexdigest()
        return pins
    except DriverError:
        raise DriverError("ui_driver_source_invalid") from None
    except Exception:
        raise DriverError("ui_driver_source_invalid") from None


def _digest(pins):
    return hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "ui_driver_result_invalid")
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _need(type(data) is dict, "ui_driver_result_invalid")
        return data
    except DriverError:
        raise
    except Exception:
        raise DriverError("ui_driver_result_invalid") from None


def _value(node, key):
    value = node.get(key)
    _need(type(value) is dict and type(value.get("_value")) is str, "ui_driver_result_invalid")
    return value["_value"]


def _values(node, key):
    value = node.get(key)
    _need(type(value) is dict and type(value.get("_values")) is list, "ui_driver_result_invalid")
    rows = value["_values"]
    _need(len(rows) <= 128 and all(type(row) is dict for row in rows), "ui_driver_result_invalid")
    return rows


def _issues(node):
    issues = node.get("issues", {})
    _need(type(issues) is dict, "ui_driver_result_invalid")
    for key in ("errorSummaries", "testFailureSummaries"):
        if key in issues:
            _need(not _values(issues, key), "ui_driver_result_not_success")


def _metrics(node):
    metrics = node.get("metrics", {})
    _need(type(metrics) is dict, "ui_driver_result_invalid")
    observed = False
    for key, expected in (("testsCount", "1"), ("testsFailedCount", "0"), ("testsSkippedCount", "0")):
        if key in metrics:
            _need(_value(metrics, key) == expected, "ui_driver_result_count_mismatch")
            observed |= key == "testsCount"
    return observed


def _summary(raw, udid):
    root = _json(raw)
    _issues(root)
    count_seen = _metrics(root)
    actions = _values(root, "actions")
    _need(len(actions) == 1, "ui_driver_result_count_mismatch")
    action = actions[0]
    _need(_value(action, "schemeCommandName") == "Test", "ui_driver_result_invalid")
    destination = action.get("runDestination", {}).get("targetDeviceRecord", {})
    _need(type(destination) is dict and _value(destination, "identifier").upper() == udid,
          "ui_driver_result_destination_mismatch")
    result = action.get("actionResult")
    _need(type(result) is dict and _value(result, "status") == "succeeded", "ui_driver_result_not_success")
    _issues(result)
    count_seen |= _metrics(result)
    _need(count_seen, "ui_driver_result_count_mismatch")
    reference = result.get("testsRef")
    _need(type(reference) is dict, "ui_driver_result_invalid")
    identifier = _value(reference, "id")
    _need(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_~+=/-]{0,511}", identifier) is not None,
          "ui_driver_result_invalid")
    return identifier


def _test_results(raw):
    root = _json(raw)
    summaries = _values(root, "summaries")
    _need(len(summaries) == 1, "ui_driver_result_count_mismatch")
    testables = _values(summaries[0], "testableSummaries")
    _need(len(testables) == 1 and _value(testables[0], "targetName") == SCHEME,
          "ui_driver_result_target_mismatch")
    stack = list(_values(testables[0], "tests"))
    leaves, visited = [], 0
    while stack:
        node = stack.pop()
        visited += 1
        _need(visited <= 512, "ui_driver_result_invalid")
        kind = node.get("_type", {}).get("_name")
        if kind == "ActionTestSummaryGroup":
            children = _values(node, "subtests")
            _need(bool(children), "ui_driver_result_invalid")
            stack.extend(children)
        else:
            _need(kind == "ActionTestMetadata", "ui_driver_result_invalid")
            leaves.append(node)
    _need(len(leaves) == 1, "ui_driver_result_count_mismatch")
    leaf = leaves[0]
    identifiers = {"OfficialPromptCancelTests/testCancelExistingProbePrompt",
        "OfficialPromptCancelTests/testCancelExistingProbePrompt()", TEST_IDENTIFIER, TEST_IDENTIFIER + "()"}
    _need(_value(leaf, "identifier") in identifiers, "ui_driver_result_method_mismatch")
    if "name" in leaf:
        _need(_value(leaf, "name") in ("testCancelExistingProbePrompt", "testCancelExistingProbePrompt()"),
              "ui_driver_result_method_mismatch")
    _need(_value(leaf, "testStatus") == "Success", "ui_driver_result_not_success")


class ProbePromptCancelDriver:
    def __init__(self, simulator_udid, *, remaining):
        _need(type(simulator_udid) is str and re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", simulator_udid) is not None,
            "ui_driver_udid_invalid")
        _need(callable(remaining), "ui_driver_callback_invalid")
        self.udid, self._remaining = str(uuid.UUID(simulator_udid)).upper(), remaining
        self._phase, self._ready, self._closed, self._error = "idle", False, False, None
        self._process = self._log = self._work = None
        self._pins, self._proof, self._xctestrun_sha = None, None, None
        self._log_size, self._line, self._phase_deadline = 0, b"", 0
        self._output_paths = {}
        self._failure_phase, self._test_spawned = None, False
        self._metadata_diagnostic = None

    def __repr__(self):
        return "<ProbePromptCancelDriver public XCTest; diagnostics redacted>"

    def _budget(self, cap=60):
        try:
            value = self._remaining(cap)
        except BaseException:
            raise DriverError("ui_driver_deadline") from None
        _need(type(value) in (int, float) and 0 < value <= 900, "ui_driver_deadline")
        return min(cap, value)

    def _spawn(self, args, phase, cap, output, maximum):
        self._budget()
        if phase == "testing":
            self._test_spawned = True
        self._log_size, self._line, self._maximum = 0, b"", maximum
        try:
            self._log = output.open("xb")
            self._process = subprocess.Popen(args, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL if phase in ("summary", "tests") else subprocess.STDOUT,
                stdin=subprocess.DEVNULL, cwd=str(_SOURCE_ROOT), start_new_session=True)
            os.set_blocking(self._process.stdout.fileno(), False)
        except Exception:
            self._stop()
            raise DriverError("ui_driver_spawn_failed") from None
        self._phase, self._phase_deadline = phase, time.monotonic() + self._budget(cap)
        self._output_paths[phase] = output

    def start(self):
        _need(not self._closed, "ui_driver_closed")
        _need(self._phase == "idle", "ui_driver_state_invalid")
        self._pins = _source_pins()
        try:
            self._work = Path(tempfile.mkdtemp(prefix="idoly-probe-cancel-ui-")).resolve()
            self._work_identity = (self._work.stat().st_dev, self._work.stat().st_ino)
            self._derived = self._work / "DerivedData"
            self._result = self._work / "CancelResult.xcresult"
            project = _SOURCE_ROOT / "ui-tests/IdolyProbeCancelUITests.xcodeproj"
            self._spawn(["xcodebuild", "-project", str(project), "-scheme", SCHEME, "-configuration", "Debug",
                "-destination", "id=" + self.udid, "-derivedDataPath", str(self._derived),
                "CODE_SIGNING_ALLOWED=NO", "build-for-testing"], "building", 180,
                self._work / "build.log", _LOG_LIMIT)
        except DriverError:
            raise
        except Exception:
            raise DriverError("ui_driver_io_failed") from None
        return self.poll()

    def _drain(self):
        for _ in range(16):
            try:
                data = os.read(self._process.stdout.fileno(), 65536)
            except BlockingIOError:
                break
            except Exception:
                raise DriverError("ui_driver_io_failed") from None
            if not data:
                break
            _need(self._log_size + len(data) <= self._maximum, "ui_driver_log_limit")
            self._log.write(data)
            self._log_size += len(data)
            if self._phase == "testing":
                self._line += data
                lines = self._line.split(b"\n")
                self._line = lines.pop()[-1024:]
                if any(line.rstrip(b"\r") == READY_MARKER for line in lines):
                    self._ready = True
        self._log.flush()

    def _source_unchanged(self):
        _need(_source_pins() == self._pins, "ui_driver_source_changed")

    def _product(self, value, products, host=None):
        _need(type(value) is str and 0 < len(value) <= 2048 and "\\" not in value
              and "://" not in value and "?" not in value and ".." not in Path(value).parts,
              "ui_driver_xctestrun_invalid")
        value = value.replace("__TESTROOT__", str(products))
        if host is not None:
            value = value.replace("__TESTHOST__", str(host))
        path = Path(value)
        _need(path.is_absolute() and "__" not in value and not path.is_symlink(), "ui_driver_xctestrun_invalid")
        try:
            path = path.resolve(strict=True)
        except Exception:
            raise DriverError("ui_driver_xctestrun_invalid") from None
        _need(path.is_relative_to(products), "ui_driver_xctestrun_invalid")
        return path

    @staticmethod
    def _kind(value):
        if value is None:
            return "absent"
        for kind in (dict, list, str, int, bool, bytes):
            if type(value) is kind:
                return kind.__name__
        return "other"

    def _path_metadata(self, value, products, host=None):
        kind = self._kind(value)
        result = {"type": kind, "token_kind": "absent" if value is None else "other",
                  "owned": False, "exists": None}
        if type(value) is not str:
            return result
        result["token_kind"] = ("testroot" if value.startswith("__TESTROOT__/") else
            "testhost" if value.startswith("__TESTHOST__/") else "url" if "://" in value else
            "absolute" if Path(value).is_absolute() else "relative")
        expanded = value.replace("__TESTROOT__", str(products))
        if host is not None:
            expanded = expanded.replace("__TESTHOST__", str(host))
        path = Path(expanded)
        # No outside path is inspected just to construct a diagnostic.
        if path.is_absolute() and path.is_relative_to(products) and ".." not in path.parts:
            try:
                actual = path.resolve(strict=False)
                result["owned"] = actual.is_relative_to(products)
                if result["owned"]:
                    result["exists"] = actual.exists()
            except Exception:
                pass
        return result

    def _built(self):
        self._source_unchanged()
        diagnostic = self._metadata_diagnostic = {"schema": 1,
            "scope": "pre-input-generated-xctestrun", "check": "products"}
        products = (self._derived / "Build/Products").resolve(strict=True)
        _need(products.is_relative_to(self._work), "ui_driver_xctestrun_invalid")
        diagnostic["check"] = "candidate_count"
        diagnostic["all_xctestrun_count"] = min(129, len(list(products.glob("*.xctestrun"))))
        candidates = list(products.glob(SCHEME + "*iphonesimulator*.xctestrun"))
        diagnostic["candidate_count"] = min(129, len(candidates))
        _need(len(candidates) == 1, "ui_driver_xctestrun_invalid")
        path = candidates[0]
        diagnostic["check"] = "plist_read"
        raw = _read(path, _PLIST_LIMIT)
        diagnostic.update(plist_bytes=len(raw), plist_sha256=hashlib.sha256(raw).hexdigest())
        data = plistlib.loads(raw)
        diagnostic["check"] = "root_schema"
        _need(type(data) is dict, "ui_driver_xctestrun_invalid")
        metadata = data.get("__xctestrun_metadata__")
        version = metadata.get("FormatVersion") if type(metadata) is dict else None
        diagnostic["format_version_type"] = self._kind(version)
        diagnostic["format_version"] = version if type(version) is int and version in (1, 2) else None
        _need(type(version) is int and version in (1, 2), "ui_driver_xctestrun_invalid")
        if version == 1:
            # Apple's traditional scheme format stores each test target at the
            # top level. Metadata is not a target; every other key must be our
            # single fixed UI target. No extra test target is ignored.
            diagnostic["configuration_count"] = 0
            keys = [key for key in data if key != "__xctestrun_metadata__"]
            diagnostic["check"] = "target_count"
            diagnostic["target_count"] = min(129, len(keys))
            _need(keys == [SCHEME] and type(data[SCHEME]) is dict, "ui_driver_xctestrun_invalid")
            target = data[SCHEME]
        else:
            configurations = data.get("TestConfigurations")
            diagnostic["check"] = "configuration_count"
            diagnostic["configuration_count"] = min(129, len(configurations)) if type(configurations) is list else 0
            _need(type(configurations) is list and len(configurations) == 1
                  and type(configurations[0]) is dict, "ui_driver_xctestrun_invalid")
            targets = configurations[0].get("TestTargets")
            diagnostic["check"] = "target_count"
            diagnostic["target_count"] = min(129, len(targets)) if type(targets) is list else 0
            _need(type(targets) is list and len(targets) == 1 and type(targets[0]) is dict,
                  "ui_driver_xctestrun_invalid")
            target = targets[0]
        diagnostic["check"] = "target_contract"
        diagnostic["blueprint_matches"] = target.get("BlueprintName") == SCHEME
        diagnostic["is_ui_test_bundle"] = target.get("IsUITestBundle") is True
        serialized_target = json.dumps(target, sort_keys=True)
        _need("game.qualiarts.idolypride.iosprobe" not in serialized_target
              and target.get("UITargetAppBundleIdentifier", DUMMY_BUNDLE) == DUMMY_BUNDLE,
              "ui_driver_xctestrun_invalid")
        _need(diagnostic["blueprint_matches"] and diagnostic["is_ui_test_bundle"], "ui_driver_xctestrun_invalid")
        paths = diagnostic["paths"] = {}
        diagnostic["check"] = "test_host_path"
        paths["test_host"] = self._path_metadata(target.get("TestHostPath"), products)
        host = self._product(target.get("TestHostPath"), products)
        diagnostic["check"] = "test_bundle_path"
        paths["test_bundle"] = self._path_metadata(target.get("TestBundlePath"), products, host)
        test = self._product(target.get("TestBundlePath"), products, host)
        diagnostic["check"] = "dummy_app_path"
        paths["dummy_app"] = self._path_metadata(target.get("UITargetAppPath"), products)
        app = self._product(target.get("UITargetAppPath"), products)
        _need(test.name == SCHEME + ".xctest" and app.name == "CancelDriverHost.app",
              "ui_driver_xctestrun_invalid")
        bundles = diagnostic["bundles"] = {}
        for label, bundle, identifier in (("runner", host, RUNNER_BUNDLE), ("dummy", app, DUMMY_BUNDLE)):
            diagnostic["check"] = label + "_bundle"
            info = plistlib.loads(_read(bundle / "Info.plist", _PLIST_LIMIT))
            _need(type(info) is dict, "ui_driver_xctestrun_invalid")
            details = bundles[label] = {"bundle_matches": info.get("CFBundleIdentifier") == identifier,
                "platforms_type": self._kind(info.get("CFBundleSupportedPlatforms")),
                "platforms_exact": info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"]}
            _need(details["bundle_matches"] and details["platforms_exact"], "ui_driver_xctestrun_invalid")
        diagnostic["check"] = "complete"
        self._xctestrun_sha = hashlib.sha256(raw).hexdigest()
        self._spawn(["xcodebuild", "-xctestrun", str(path), "-destination", "id=" + self.udid,
            "-resultBundlePath", str(self._result), "-parallel-testing-enabled", "NO",
            "-maximum-concurrent-test-simulator-destinations", "1", "-only-testing:" + TEST_IDENTIFIER,
            "test-without-building"], "testing", 300, self._work / "test.log", _LOG_LIMIT)

    def _result_command(self, reference=None):
        _need(self._result.is_dir() and not self._result.is_symlink()
              and self._result.resolve().is_relative_to(self._work), "ui_driver_result_invalid")
        args = ["xcrun", "xcresulttool", "get", "--legacy", "--path", str(self._result), "--format", "json"]
        if reference is not None:
            args.extend(("--id", reference))
        return args

    def _ended(self, code):
        phase = self._phase
        self._log.close()
        self._log = None
        self._process.stdout.close()
        self._process = None
        _need(code == 0, "ui_driver_build_failed" if phase == "building" else
              "ui_driver_test_failed" if phase == "testing" else "ui_driver_result_failed")
        if phase == "building":
            self._built()
        elif phase == "testing":
            _need(self._ready, "ui_driver_ready_missing")
            self._spawn(self._result_command(), "summary", 30, self._work / "summary.json", _JSON_LIMIT)
        elif phase == "summary":
            raw = _read(self._output_paths["summary"], _JSON_LIMIT)
            reference = _summary(raw, self.udid)
            self._summary_sha = hashlib.sha256(raw).hexdigest()
            self._spawn(self._result_command(reference), "tests", 30, self._work / "tests.json", _JSON_LIMIT)
        elif phase == "tests":
            raw = _read(self._output_paths["tests"], _JSON_LIMIT)
            _test_results(raw)
            self._source_unchanged()
            self._proof = {"schema": 1, "status": "PASS", "execution": "public_xctest",
                "simulator_udid": self.udid, "test_identifier": TEST_IDENTIFIER,
                "tests": 1, "failures": 0, "skipped": 0, "actual_cancel_tap": True,
                "ready_marker_observed": True, "source_pins": dict(self._pins), "source_sha256": _digest(self._pins),
                "xctestrun_sha256": self._xctestrun_sha, "xcresult_summary_sha256": self._summary_sha,
                "xcresult_tests_sha256": hashlib.sha256(raw).hexdigest()}
            self._phase = "passed"

    def poll(self):
        _need(not self._closed, "ui_driver_closed")
        if self._phase not in ("idle", "passed", "failed"):
            try:
                self._budget()
                _need(time.monotonic() < self._phase_deadline, "ui_driver_deadline")
                self._drain()
                code = self._process.poll()
                if code is not None:
                    self._ended(code)
            except DriverError as error:
                self._failure_phase = self._phase
                self._error, self._phase = error.code, "failed"
                self._stop()
            except Exception:
                self._failure_phase = self._phase
                self._error, self._phase = "ui_driver_result_invalid", "failed"
                self._stop()
        phase = "building" if self._phase == "building" else self._phase if self._phase in ("passed", "failed", "idle") else "running"
        return {"phase": phase, "ready": self._ready, "error_code": self._error}

    def build_metadata_diagnostic(self):
        """A fixed, typed pre-input gate diagnostic; no plist/path/env values."""
        if (self._closed or self._phase != "failed" or self._failure_phase != "building"
                or self._test_spawned or self._ready or self._metadata_diagnostic is None):
            return None
        return json.loads(json.dumps(self._metadata_diagnostic))

    def build_failure_log(self):
        """Return only an owned pre-input build tail, never UI/result logs.

        The caller may keep a smaller bounded diagnostic artifact. Test runner
        startup permanently disables this accessor, even without a ready marker.
        """
        if (self._closed or self._phase != "failed" or self._failure_phase != "building"
                or self._test_spawned or self._ready or self._work is None):
            return None
        path = self._output_paths.get("building")
        if path != self._work / "build.log":
            return None
        try:
            directory = self._work.lstat()
            if (not stat.S_ISDIR(directory.st_mode)
                    or (directory.st_dev, directory.st_ino) != self._work_identity):
                return None
            before = path.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or not 0 < before.st_size <= _LOG_LIMIT):
                return None
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size):
                    return None
                stream.seek(max(0, before.st_size - 64 * 1024))
                tail = stream.read(64 * 1024)
                after = os.fstat(stream.fileno())
                if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                        before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                    return None
            return tail if tail else None
        except Exception:
            return None

    def finish(self):
        _need(self._phase != "idle", "ui_driver_state_invalid")
        while True:
            status = self.poll()
            if status["phase"] == "passed":
                return {**self._proof, "source_pins": dict(self._proof["source_pins"])}
            if status["phase"] == "failed":
                raise DriverError(status["error_code"])
            time.sleep(min(0.05, self._budget(1)))

    def _stop(self):
        process, self._process = self._process, None
        if process is not None:
            try:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=0.2)
            except Exception:
                pass
            try:
                process.stdout.close()
            except Exception:
                pass
        if self._log is not None:
            log, self._log = self._log, None
            try:
                log.close()
            except Exception:
                pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._stop()
        if self._work is not None:
            try:
                info = self._work.lstat()
                if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == self._work_identity:
                    shutil.rmtree(self._work)
            except Exception:
                pass
