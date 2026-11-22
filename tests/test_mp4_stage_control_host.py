"""Bounded original Control/Director state proofs use shipping Bridge bodies.

No shared-workspace helper copy is compiled. Fixtures supply adversarial C API
models; the implementations and factory exception paths are extracted from
bridge.cpp on each run. These are CPU/source proofs, not a device/GPU MP4 test.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess

NATIVE = Path(__file__).resolve().parents[1] / "client-presentation" / "native"
FIXTURES = Path(__file__).parent / "fixtures" / "mp4_stage_control"


def _between(source: str, begin: str, end: str) -> str:
    start = source.index(begin)
    stop = source.index(end, start + len(begin))
    return source[start:stop]


def _function(source: str, name: str, return_type: str = "bool") -> str:
    """Find a function's complete body, excluding subsequent unrelated hosts."""
    start = source.index(return_type + " " + name + "(")
    brace = source.index("{", start)
    # The bounded source-only predicate has no brace characters in literals.
    depth = 0
    for end in range(brace, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if not depth:
                return source[start:end + 1] + "\n"
    raise AssertionError("unterminated shipping function: " + name)


def _write_shipping_bodies(destination: Path) -> None:
    source = (NATIVE / "bridge.cpp").read_text()
    bodies = {
        "pins.inc": _between(source, "struct Mp4StageOtherPins{", "// BEGIN_MP4_STAGE_PARTICLE_ADMISSION_HOST"),
        "particle-admission-receipt-host.cpp": _between(source,
            "// BEGIN_MP4_STAGE_PARTICLE_ADMISSION_HOST", "// END_MP4_STAGE_PARTICLE_ADMISSION_HOST"),
        "particle-admission-wiring.cpp.inc": "\n".join(_function(source, name, "Mp4SceneResult") for name in (
            "mp4_stage_admit", "mp4_stage_capture")),
        "activation-node-scope.hpp.inc": _between(source,
            "namespace idoly_mp4_activation_nodes {", "} // namespace idoly_mp4_activation_nodes")
            + "} // namespace idoly_mp4_activation_nodes\n",
        "activation-node-host.cpp": _between(source,
            "namespace mp4an = idoly_mp4_activation_nodes;", "struct Mp4ActivationTargetPins"),
        "activation-target-scope.hpp.inc": _between(source,
            "namespace idoly_mp4_activation_targets {", "} // namespace idoly_mp4_activation_targets")
            + "} // namespace idoly_mp4_activation_targets\n",
        "activation-family.cpp.inc": "\n".join(_function(source, name) for name in (
            "mp4_activation_callback_table", "mp4_activation_volume_callbacks",
            "mp4_activation_component_family")),
        "activation-subtree.cpp.inc": _function(source, "mp4_activation_subtree_inventory"),
        "activation-callback-origin.cpp": _between(source,
            "enum class Mp4ActivationOperation", "// END_MP4_ACTIVATION_SOURCE_HOST"),
        "control-asset-scope.hpp.inc": _between(
            source, "namespace idoly_mp4_control_assets {",
            "} // namespace idoly_mp4_control_assets")
            + "} // namespace idoly_mp4_control_assets\n",
        "provider.cpp": _between(source, "bool mp4_stage_other_pins_ready()",
                                  "namespace idoly_mp4_control_assets {"),
        "control-source-schema-pins.cpp": _function(source, "mp4_control_source_pins_ready"),
        "control-passive.cpp": _between(source,
            "constexpr size_t mp4_control_passive_capacity = 512;",
            "bool mp4_control_factory_authorized("),
        "control-factory-invoke.cpp.inc": _between(source,
            "using Mp4ControlFactory =", "uint32_t mp4_control_director_type ="),
        "director-edges.cpp": _between(source,
            "uint32_t mp4_control_director_type =", "struct Mp4DirectorControlPins"),
        "director-node-scope.hpp.inc": _between(source,
            "namespace idoly_mp4_director_nodes {", "} // namespace idoly_mp4_director_nodes")
            + "} // namespace idoly_mp4_director_nodes\n",
        "director-node-host.cpp": _between(source,
            "namespace mp4dn = idoly_mp4_director_nodes;", "// BEGIN_MP4_DIRECTOR_SOURCE_EDGE_HOST"),
        "director-source-edge.cpp": _between(source,
            "// BEGIN_MP4_DIRECTOR_SOURCE_EDGE_HOST", "// END_MP4_DIRECTOR_SOURCE_EDGE_HOST"),
        "control-source-promotion.cpp": _between(source,
            "struct Mp4ControlPromotionRequest", "struct Mp4ProFlarePins"),
    }
    for name, body in bodies.items():
        (destination / name).write_text(body)


def test_shipping_stage_control_models(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    assert compiler, "host C++ compiler required"
    _write_shipping_bodies(tmp_path)
    explicit = {
        "particle-admission-wiring": ["normal", "no_attempt", "collect_throw", "collect_failed",
            "particles_failed", "psyllium_failed", "palette_wait", "equipment_configure_failed",
            "equipment_failed", "equipment_throw", "observe_failed", "observe_throw", "cleanup_failed",
            "cleanup_throw", "seal_failed", "capture_inventory", "capture_controls", "capture_receipt"],
        "control-assets": ["normal", "capture_invalid", "capture_partial", "infinity",
            "unknown", "untrusted", "unreceipted", "input_change", "inflight",
            "owner_lost", "original_exception", "wrong_result", "cleanup_false",
            "restore_superseded", "restore_owner_lost", "restore_writer_failed",
            "reuse", "inventory_exception"],
        "provider": ["admission", "admit_foreign", "admit_duplicate", "admit_receipt", "admit_timeline_sibling", "admit_unpublished",
            "pins_lost", "source_lost", "zero_seed", "seed_changed", "wrong_particle",
            "wrong_path", "wrong_graph", "uncaptured", "scope_lost", "producer_lost",
            "wrong_producer", "source_epoch", "restore", "restore_pending", "restore_plan",
            "light", "unknown", "control_runtime", "light_runtime", "unknown_runtime",
            "active", "userdata"],
        "director-edges": ["normal", "hierarchy", "disabled", "null_source", "self_guard",
            "same_asset", "first_asset_differs", "no_directors", "unknown_clip", "pins_lost",
            "source_not_current", "bad_track", "duplicate_track", "bad_schema", "bad_flag",
            "prefab", "bad_hierarchy", "dead_source", "dead_owner", "dead_first",
            "duplicate_child", "null_child", "non_director", "null_child_asset", "self_child",
            "callback_reject", "retain_failure", "empty", "too_many", "sequence_exhausted",
            "changed_source", "changed_child_asset", "source_lost", "changed_input",
            "authored_normal", "authored_unbuilt", "authored_no_graph", "authored_wrong_epoch",
            "authored_wrong_owner", "authored_initial_catalogue_lost", "authored_cycle",
            "authored_empty", "authored_duplicate_clip", "authored_duplicate_track",
            "authored_metadata_changed", "authored_catalogue_lost"],
        "control-passive": ["normal", "before_pins", "before_method", "before_graph",
            "before_schema", "before_owner", "before_dead_asset", "before_retain",
            "before_foreign", "after_source", "after_input", "after_graph", "after_weak",
            "after_foreign", "after_nan", "original_exception", "weak_expired",
            "historical_expired", "input_changed", "cache_changed", "graph_changed",
            "source_changed", "owner_changed", "foreign_dirty", "original_retry_exception", "reuse"],
    }
    total = 0
    for fixture in sorted(FIXTURES.glob("*.cpp")):
        text = fixture.read_text()
        fixture_path = tmp_path / ("fixture-" + fixture.name)
        fixture_path.write_text(text)
        binary = tmp_path / fixture.stem
        cases = explicit.get(fixture.stem, ["normal"])
        inferred = re.findall(r'\b(?:c|mode|scenario)\s*==\s*"([^\"]+)"', text)
        # Legacy fixtures have explicit lists; passive adds the promotion paths.
        if fixture.stem not in explicit:
            cases += inferred
        elif fixture.stem == "control-passive":
            cases += [case for case in inferred if case.startswith("promote_")]
        cases = list(dict.fromkeys(cases))
        build = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
            "-g", str(fixture_path), "-o", str(binary)],
            capture_output=True, text=True)
        assert build.returncode == 0, (fixture.name, build.stdout, build.stderr)
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1")
        for case in cases:
            result = subprocess.run([str(binary), case], env=env, capture_output=True, text=True)
            assert result.returncode == 0, (fixture.name, case, result.stdout, result.stderr)
        total += len(cases)
    assert total >= 440, total
