"""The original RT scope now includes the verified full-frame projection path."""
import subprocess

from test_mp4_output_projection import projection_executable


def test_original_render_target_pixels_are_scoped_to_manual_owner_and_restored(projection_executable):
    for mode in ("owner", "landscape", "portrait", "restore_failure", "destroyed", "reentrant_restore"):
        result = subprocess.run([str(projection_executable), mode], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
