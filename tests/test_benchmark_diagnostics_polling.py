"""The benchmark may project exactly three validated additions, untimed."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("polling_benchmark", Path(__file__).resolve().parents[1]/"tools/benchmark_diagnostics_polling.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def outputs(role):
    poll = {"profile": "sandbox", "running": False,
            "client_diagnostics": {"received_events": 200, "stored_events": 200, "summary": "kept"},
            "arbitrary_legacy_value": {"deep": [1, "kept", None]}}
    if role == "candidate": poll.update(bench.management_defaults())
    exported = {"schema": 1, "runtime": deepcopy(poll),
                "client_diagnostics": {"events": [{"frame": "kept"}]}}
    return poll, exported


def row(role, poll=None, exported=None):
    if poll is None: poll, exported = outputs(role)
    projected, projected_export, evidence = bench.project_outputs(poll, exported, role)
    return {"role": role, "comparison_scope": bench.comparison_scope(), "management_contract": evidence,
            "summary_sha256": bench.canonical_hash(poll["client_diagnostics"]),
            "poll_sha256": bench.canonical_hash(projected), "export_sha256": bench.canonical_hash(projected_export),
            "full_poll_sha256": bench.canonical_hash(poll), "full_export_sha256": bench.canonical_hash(exported),
            "benchmark_sha256": hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest()}


def test_only_exact_additions_differ_and_both_full_hashes_are_retained():
    rows = {role: [row(role), row(role)] for role in bench.ROLES}
    shared, full = bench.compare_outputs(rows)
    assert set(shared) == {"summary_sha256", "poll_sha256", "export_sha256"}
    assert full["baseline"]["poll_sha256"] == shared["poll_sha256"]
    assert full["baseline"]["export_sha256"] == shared["export_sha256"]
    assert full["candidate"]["poll_sha256"] != shared["poll_sha256"]
    assert full["candidate"]["export_sha256"] != shared["export_sha256"]
    assert bench.comparison_scope()["timed_operation"] == "full Runtime.status()"
    assert bench.comparison_scope()["tracemalloc_operation"] == "full Runtime.status()"


@pytest.mark.parametrize("role,side,case", [
    ("baseline", "poll", "added"), ("baseline", "export", "added"),
    ("candidate", "poll", "missing"), ("candidate", "export", "missing"),
    ("candidate", "poll", "none"), ("candidate", "poll", "schema_bool"),
    ("candidate", "poll", "flag_zero"), ("candidate", "export", "extra_nested"),
    ("candidate", "poll", "nondefault"), ("candidate", "export", "bound_profile"),
])
def test_roles_missing_partial_wrong_types_or_nondefault_management_are_rejected(role, side, case):
    poll, exported = outputs(role)
    target = poll if side == "poll" else exported["runtime"]
    if case == "added": target["durable_history"] = bench.management_defaults()["durable_history"]
    elif case == "missing": target.pop("startup_checks")
    elif case == "none": target["account_selection"] = None
    elif case == "schema_bool": target["durable_history"]["schema"] = True
    elif case == "flag_zero": target["account_selection"]["restart_required"] = 0
    elif case == "extra_nested": target["startup_checks"]["unreviewed"] = "not allowed"
    elif case == "nondefault": target["durable_history"]["retained_records"] = 1
    elif case == "bound_profile": target["account_selection"]["active_profile"] = "other"
    with pytest.raises(ValueError): bench.project_outputs(poll, exported, role)


@pytest.mark.parametrize("case", ("new_poll_key", "changed_legacy_value", "new_export_key", "changed_export_value"))
def test_projection_preserves_every_unreviewed_key_and_existing_value_for_comparison(case):
    poll, exported = outputs("candidate")
    if case == "new_poll_key": poll["unexpected_new_field"] = "must be compared"
    elif case == "changed_legacy_value": poll["arbitrary_legacy_value"]["deep"][0] = 999
    elif case == "new_export_key": exported["unexpected_new_field"] = "must be compared"
    else: exported["client_diagnostics"]["events"][0]["frame"] = "changed"
    rows = {"baseline": [row("baseline")], "candidate": [row("candidate", poll, exported)]}
    with pytest.raises(ValueError, match="legacy output mismatch"): bench.compare_outputs(rows)


def test_projection_does_not_mutate_the_actual_full_objects():
    poll, exported = outputs("candidate"); before = deepcopy((poll, exported))
    projected, projected_export, evidence = bench.project_outputs(poll, exported, "candidate")
    assert (poll, exported) == before
    assert not set(bench.MANAGEMENT_KEYS) & projected.keys()
    assert not set(bench.MANAGEMENT_KEYS) & projected_export["runtime"].keys()
    assert bench.strict_equal(evidence, bench.expected_management_evidence("candidate"))


@pytest.mark.parametrize("case", ("role", "full_missing", "baseline_full_changed", "candidate_full_hidden", "contract_partial", "scope_extra", "hash_type"))
def test_raw_full_provenance_and_strict_comparison_contract_are_mandatory(case):
    rows = {role: [row(role)] for role in bench.ROLES}
    candidate = rows["candidate"][0]
    if case == "role": candidate["role"] = "baseline"
    elif case == "full_missing": candidate.pop("full_export_sha256")
    elif case == "baseline_full_changed": rows["baseline"][0]["full_poll_sha256"] = "c"*64
    elif case == "candidate_full_hidden": candidate["full_export_sha256"] = candidate["export_sha256"]
    elif case == "contract_partial": candidate["management_contract"]["poll"].pop("account_selection")
    elif case == "scope_extra": candidate["comparison_scope"]["excluded_runtime_fields_after_validation"].append("client_diagnostics")
    else: candidate["full_poll_sha256"] = True
    with pytest.raises(ValueError): bench.compare_outputs(rows)


def test_full_outputs_must_stay_constant_within_each_source_role():
    rows = {role: [row(role), row(role)] for role in bench.ROLES}
    rows["candidate"][1]["full_poll_sha256"] = "e"*64
    with pytest.raises(ValueError, match="Full output changed"): bench.compare_outputs(rows)


def test_coordinator_freezes_roles_script_identity_and_comparison_scope(tmp_path, monkeypatch):
    roots = {role: tmp_path/role for role in bench.ROLES}
    for root in roots.values():
        modules = root/"src/idoly_local"; modules.mkdir(parents=True)
        for module in ("app_runtime.py", "diagnostics.py"): (modules/module).write_text("# source identity fixture\n")
    calls = []
    def fake_worker(script, root, cwd, iterations, trace, role):
        calls.append((role, iterations, trace))
        result = row(role)
        result.update(schema=1, source_root=str(root), iterations=iterations,
            history_deepcopy_calls={"poll": 1, "explicit_export": 2} if role == "baseline" else {"poll": 0, "explicit_export": 1},
            wall_microseconds_per_poll=4.0 if role == "baseline" else 1.0,
            cpu_microseconds_per_poll=3.0 if role == "baseline" else 1.0)
        return result
    monkeypatch.setattr(bench, "run_worker", fake_worker)
    work = tmp_path/"work"; output = work/"report.json"
    bench.coordinator(["--baseline-root", str(roots["baseline"]), "--candidate-root", str(roots["candidate"]),
                       "--work", str(work), "--output", str(output), "--iterations", "100", "--repeats", "3", "--tracemalloc"])
    report = json.loads(output.read_bytes())
    assert [role for role, _, _ in calls] == ["baseline", "candidate", "candidate", "baseline", "baseline", "candidate"]
    assert all(iterations == 100 and trace is True for _, iterations, trace in calls)
    assert "identical_outputs" not in report
    assert bench.strict_equal(report["comparison_scope"], bench.comparison_scope())
    assert bench.strict_equal(report["management_contract"], bench.management_contract())
    assert report["benchmark_sha256"] == hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest()
    assert set(report["full_outputs"]) == set(bench.ROLES)
