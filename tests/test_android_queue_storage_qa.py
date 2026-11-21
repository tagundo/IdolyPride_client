from __future__ import annotations

import copy
import shutil
import subprocess

import pytest

from tools import build_android_queue_qa as qa


CHALLENGE = "a" * 64
UID = 10123
BUILT = {"production_queue_sha256": "b" * 64, "source_snapshot_sha256": "c" * 64}
HOST_ENFORCEMENT = {"source": "adb_shell_getenforce", "before": "Enforcing", "after": "Enforcing"}


def report():
    diagnostic = {"storage_stage": "none", "storage_errno": 0}
    cases = [
        {"name": "legacy_hardlink_denied", "return": -1, "errno": 1, "source_preserved_target_absent": True},
        {"name": "install_new_no_clobber", "existing_return": -1, "existing_errno": 17,
         "fresh_return": 0, "fresh_errno": 0, "both_existing_files_preserved": True, "fresh_single_link_install": True},
        {"name": "queue_roundtrip", **diagnostic, "queue_error": "none", "reopened_count": 2, "generation": 2,
         "descriptor_preserved": True, "private_single_link_journal": True,
         "private_zero_byte_single_link_lock_preserved": True, "temporary_files_absent": True},
        {"name": "queue_existing_target_rejected", **diagnostic, "queue_error": "queue_storage_changed",
         "sentinel_preserved": True, "state_unmodified": True},
        *[{"name": name, **diagnostic, "queue_error": "unsafe_queue_storage", "symlink_and_sentinel_preserved": True}
          for name in ("journal_symlink_rejected", "lock_symlink_rejected")],
        {"name": "journal_tamper_rejected", **diagnostic, "queue_error": "queue_storage_changed",
         "reopen_error": "queue_corrupt", "tampered_bytes_preserved": True, "state_unmodified": True},
    ]
    for row in cases: row.update(required=True, status="passed")
    return {"schema": 1, "package": qa.PACKAGE, "challenge": CHALLENGE, "java_uid": UID, "java_pid": 1234,
            "android_api": 35, "phase": "completed", "passed": True,
            "native": {"uid": UID, "euid": UID, "pid": 1234, "challenge": CHALLENGE,
                       "selinux_enforcing": True, "selinux_context": "u:r:untrusted_app:s0:c123,c256,c512,c768",
                       "selinux_enforcement_source": "app_selinuxfs_enforce", "selinux_enforce_read_status": "read",
                       "selinux_enforce_read_errno": 0,
                       "private_storage_owner_mode": True, **BUILT, "cases": cases}}


def validate(value):
    return qa.validate_runtime_report(value, BUILT, CHALLENGE, UID, HOST_ENFORCEMENT)


def test_accept_actual_policy_denial_and_all_production_queue_proofs():
    assert validate(report()) == report()
    value = report(); value["native"]["cases"][0]["errno"] = 13
    assert validate(value) == value
    value["native"]["selinux_context"] = "u:r:untrusted_app_32:s0:c123,c256"
    assert validate(value) == value


@pytest.mark.parametrize("field,value", [
    ("phase", "failed"), ("phase", "running"), ("passed", False), ("passed", 1),
    ("package", "com.android.shell"), ("challenge", "d" * 64), ("java_uid", 2000),
    ("java_pid", 0), ("java_pid", True), ("android_api", 29), ("android_api", True),
    ("native", None), ("error", "required_case_failed"),
])
def test_reject_build_only_failed_stale_or_other_process_reports(field, value):
    proof = report(); proof[field] = value
    with pytest.raises(ValueError): validate(proof)


@pytest.mark.parametrize("field,value", [
    ("uid", 0), ("uid", 2000), ("uid", "10123"), ("euid", 0), ("pid", 999),
    ("selinux_enforcing", False), ("selinux_enforcing", 1), ("selinux_context", "u:r:shell:s0"),
    ("selinux_context", "u:r:su:s0"), ("selinux_context", "u:r:untrusted_app_fake:s0"),
    ("selinux_context", "u:r:untrusted_app:s0\n"), ("private_storage_owner_mode", False),
    ("challenge", "0" * 64), ("production_queue_sha256", "0" * 64),
    ("source_snapshot_sha256", "0" * 64), ("error", "attestation_unavailable"),
])
def test_reject_missing_app_sandbox_or_compiled_source_identity(field, value):
    proof = report(); proof["native"][field] = value
    with pytest.raises(ValueError): validate(proof)


@pytest.mark.parametrize("index", range(7))
@pytest.mark.parametrize("mutation", ("missing", "duplicate", "unsupported", "failed", "optional"))
def test_each_case_is_mandatory_and_cannot_be_skipped(index, mutation):
    proof = report(); rows = proof["native"]["cases"]
    if mutation == "missing": rows.pop(index)
    elif mutation == "duplicate": rows.append(copy.deepcopy(rows[index]))
    elif mutation == "optional": rows[index]["required"] = False
    else: rows[index]["status"] = mutation
    with pytest.raises(ValueError): validate(proof)


@pytest.mark.parametrize("index,field,value", [
    (0, "return", 0), (0, "errno", 0), (0, "errno", 2), (0, "errno", 38),
    (0, "errno", True), (0, "source_preserved_target_absent", False),
    (1, "existing_return", 0), (1, "existing_errno", 1), (1, "fresh_return", -1),
    (1, "fresh_return", False), (1, "fresh_errno", False), (1, "fresh_errno", 38),
    (1, "both_existing_files_preserved", False), (1, "fresh_single_link_install", False),
    (2, "queue_error", "queue_io_failed"), (2, "storage_stage", "install_new"),
    (2, "storage_errno", 1), (2, "storage_errno", False), (2, "reopened_count", 1),
    (2, "generation", 1), (2, "descriptor_preserved", False),
    (2, "private_single_link_journal", False), (2, "temporary_files_absent", False),
    (2, "private_zero_byte_single_link_lock_preserved", False),
    (3, "queue_error", "none"), (3, "sentinel_preserved", False), (3, "state_unmodified", False),
    (4, "queue_error", "none"), (4, "symlink_and_sentinel_preserved", False),
    (5, "queue_error", "queue_corrupt"), (5, "symlink_and_sentinel_preserved", False),
    (6, "queue_error", "none"), (6, "reopen_error", "none"),
    (6, "tampered_bytes_preserved", False), (6, "state_unmodified", False),
])
def test_required_syscall_and_queue_results_are_checked(index, field, value):
    proof = report(); proof["native"]["cases"][index][field] = value
    with pytest.raises(ValueError): validate(proof)


def test_missing_diagnostics_and_other_app_uid_fail():
    for field in ("storage_stage", "storage_errno"):
        proof = report(); del proof["native"]["cases"][2][field]
        with pytest.raises(ValueError): validate(proof)
    for uid in (0, 2000, 9999, 20000, 99000, True, "10123"):
        with pytest.raises(ValueError): qa.validate_runtime_report(report(), BUILT, CHALLENGE, uid, HOST_ENFORCEMENT)
    proof = report(); del proof["native"]["cases"][2]["private_zero_byte_single_link_lock_preserved"]
    with pytest.raises(ValueError): validate(proof)


@pytest.mark.parametrize("read_errno", (1, 13))
def test_native_enforce_read_denial_is_explicit_and_needs_both_host_attestations(read_errno):
    proof = report(); proof["native"].update(selinux_enforcing=None, selinux_enforce_read_status="unavailable",
                                            selinux_enforce_read_errno=read_errno)
    assert validate(proof) == proof
    for field in ("before", "after", "source"):
        for invalid in (None, "Permissive", "Disabled", True, ""):
            host = dict(HOST_ENFORCEMENT); host[field] = invalid
            with pytest.raises(ValueError): qa.validate_runtime_report(proof, BUILT, CHALLENGE, UID, host)
        host = dict(HOST_ENFORCEMENT); del host[field]
        with pytest.raises(ValueError): qa.validate_runtime_report(proof, BUILT, CHALLENGE, UID, host)
    for host in (None, {}, "Enforcing"):
        with pytest.raises(ValueError): qa.validate_runtime_report(proof, BUILT, CHALLENGE, UID, host)


@pytest.mark.parametrize("field,value", [
    ("selinux_enforcement_source", "assumed"), ("selinux_enforce_read_status", "unsupported"),
    ("selinux_enforce_read_errno", 0), ("selinux_enforce_read_errno", 2), ("selinux_enforce_read_errno", 38),
    ("selinux_enforce_read_errno", True), ("selinux_enforcing", True), ("selinux_enforcing", False),
])
def test_unavailable_native_enforce_read_cannot_be_guessed_or_hide_other_errors(field, value):
    proof = report(); proof["native"].update(selinux_enforcing=None, selinux_enforce_read_status="unavailable",
                                            selinux_enforce_read_errno=13)
    proof["native"][field] = value
    with pytest.raises(ValueError): validate(proof)


def test_native_and_host_enforcement_fields_are_required_even_for_read_success():
    for field in ("selinux_enforcement_source", "selinux_enforce_read_status", "selinux_enforce_read_errno", "selinux_enforcing"):
        proof = report(); del proof["native"][field]
        with pytest.raises(ValueError): validate(proof)
    for field in ("before", "after"):
        host = dict(HOST_ENFORCEMENT); host[field] = "Permissive"
        with pytest.raises(ValueError): qa.validate_runtime_report(report(), BUILT, CHALLENGE, UID, host)


def test_snapshot_receipt_covers_production_queue_and_changes_when_source_changes():
    rows = qa.sources()
    assert qa.QUEUE in rows and qa.NATIVE in rows and qa.JAVA in rows and qa.FILES in rows
    changed = copy.deepcopy(rows); changed[qa.QUEUE]["sha256"] = "0" * 64
    assert qa.snapshot(changed) != qa.snapshot(rows)


@pytest.fixture(scope="module")
def native_directory_probe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("queue-files-native")
    compiler = shutil.which("c++")
    assert compiler, "Native queue filename regression requires a C++ compiler"
    source = directory / "probe.cpp"
    source.write_text('#include "queue_probe_files.hpp"\n'
                      'int main(int argc,char**argv){if(argc!=2)return 3;'
                      'try{return idoly_queue_storage_qa::no_temporary_files(argv[1])?0:1;}'
                      'catch(...){return 2;}}\n')
    executable = directory / "probe"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str((qa.ROOT / qa.FILES).parent),
                    str(source), "-o", str(executable)], check=True, timeout=30, capture_output=True)
    return executable


@pytest.mark.parametrize("extra,expected", [
    (None, 0), ("queue-v1.bin", 0),
    (".queue-" + "a" * 32 + ".tmp", 1), (".queue-", 1), (".queue-bad", 1),
    (".queue-" + "a" * 31 + ".tmp", 1), (".queue-" + "g" * 32 + ".tmp", 1),
    (".queue-v1.lock.tmp", 1), (".queue-v1.lock.extra", 1), (".queue-v2.lock", 1),
])
def test_native_directory_check_allows_only_exact_persistent_lock(native_directory_probe, tmp_path, extra, expected):
    lock = tmp_path / ".queue-v1.lock"; lock.touch(mode=0o600)
    if extra is not None: (tmp_path / extra).touch(mode=0o600)
    result = subprocess.run([str(native_directory_probe), str(tmp_path)], timeout=10, capture_output=True)
    assert result.returncode == expected
    assert lock.is_file() and lock.stat().st_size == 0


def test_optional_ui_and_logcat_evidence_is_bounded_and_owned(monkeypatch, tmp_path):
    commands = []
    temporary = "/data/local/tmp/idoly-queue-storage-" + CHALLENGE + ".xml"
    tree = ('<?xml version="1.0"?><hierarchy><node package="' + qa.PACKAGE + '" /></hierarchy>').encode()
    png = b"\x89PNG\r\n\x1a\nsmall-test-image"
    def run(command, **kwargs):
        commands.append(command)
        tail = command[3:]
        if tail[:2] == ["shell", "test"] and tail[2] in ("-e", "-L"):
            assert tail[3] == temporary
            return subprocess.CompletedProcess(command, 1, b"", b"")
        if tail == ["shell", "pidof", "-s", qa.PACKAGE]: data = b"1234\n"
        elif tail == ["logcat", "-d", "--pid", "1234", "-t", "200"]: data = b"own process only\n"
        elif tail == ["shell", "uiautomator", "dump", temporary]: data = b"UI hierarchy dumped"
        elif tail == ["shell", "test", "-f", temporary]: data = b""
        elif tail == ["exec-out", "cat", temporary]: data = tree
        elif tail == ["exec-out", "screencap", "-p"]: data = png
        elif tail == ["shell", "rm", "-f", "--", temporary]: data = b""
        else: raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, data, b"")
    monkeypatch.setattr(qa.subprocess, "run", run)
    result = qa.collect_optional_evidence(tmp_path, ["adb", "-s", "emulator-5554"], CHALLENGE)
    assert result["logcat_pid"] == 1234 and (tmp_path / "activity.png").read_bytes() == png
    assert (tmp_path / "ui-tree.xml").read_bytes() == tree
    assert all("--pid" in command for command in commands if "logcat" in command)
    assert commands[-1][3:] == ["shell", "rm", "-f", "--", temporary]


def test_other_app_ui_and_missing_pid_do_not_collect_or_block_storage_evidence(monkeypatch, tmp_path):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if "test" in command and "-f" not in command:
            return subprocess.CompletedProcess(command, 1, b"", b"")
        data = b'<?xml version="1.0"?><hierarchy><node package="another.app" /></hierarchy>'
        if "test" in command or "rm" in command: data = b""
        return subprocess.CompletedProcess(command, 1 if "pidof" in command else 0, data, b"")
    monkeypatch.setattr(qa.subprocess, "run", run)
    result = qa.collect_optional_evidence(tmp_path, ["adb", "-s", "emulator-5554"], CHALLENGE)
    assert result == {"logcat_error_type": "ValueError", "ui_error_type": "ValueError"}
    assert not list(tmp_path.iterdir())
    assert not any("screencap" in command or "logcat" in command for command in commands)


@pytest.mark.parametrize("existing", ("-e", "-L"))
def test_optional_xml_capture_never_overwrites_or_removes_preexisting_path(monkeypatch, tmp_path, existing):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if "pidof" in command: return subprocess.CompletedProcess(command, 1, b"", b"")
        assert command[3:5] == ["shell", "test"] and command[5] in ("-e", "-L")
        return subprocess.CompletedProcess(command, 0 if command[5] == existing else 1, b"", b"")
    monkeypatch.setattr(qa.subprocess, "run", run)
    result = qa.collect_optional_evidence(tmp_path, ["adb", "-s", "emulator-5554"], CHALLENGE)
    assert result["ui_error_type"] == "ValueError"
    assert not any("uiautomator" in command or "rm" in command for command in commands)
