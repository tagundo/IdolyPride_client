"""Bounded, read-only synchronous exit timing with untouched original tasks."""
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def test_wardrobe_timing_originals_and_concurrent_snapshot(tmp_path):
    binary = tmp_path / "wardrobe-timing"
    compiler = shutil.which("c++")
    assert compiler, "A C++17 compiler is required for native helper verification"
    subprocess.run([compiler, "-std=c++17", "-pthread", "-O2", "-Wall", "-Wextra", "-Werror",
                    str(HERE / "wardrobe_timing_test.cpp"), "-o", str(binary)], check=True)
    output = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)
    rows = [json.loads(line) for line in output.stdout.splitlines()]
    assert len(rows) == 5
    keys = {"schema", "room", "phase", "active", "in_original", "elapsed_ms", "last_sync_ms",
            "max_sync_ms", "max_sync_stage", "sequence", "spans"}
    assert all(set(row) == keys for row in rows)
    assert rows[0] == dict(schema=1, room="none", phase="idle", active=False, in_original=False,
                           elapsed_ms=None, last_sync_ms=0, max_sync_ms=0, max_sync_stage="none",
                           sequence=0, spans=[])
    assert rows[1]["spans"] == [dict(stage="preclose", duration_ms=50),
                                  dict(stage="unload", duration_ms=36800),
                                  dict(stage="back", duration_ms=37000)]
    assert rows[2]["phase"] == "completed" and rows[2]["elapsed_ms"] == 37000
    assert rows[3]["room"] == "fitting_room" and len(rows[3]["spans"]) == 2
    assert rows[3]["spans"][-1] == dict(stage="back", duration_ms=12)
    assert rows[4]["phase"] == "preclose" and rows[4]["elapsed_ms"] == 37000
    assert rows[4]["spans"] == [dict(stage="preclose", duration_ms=37000)]
