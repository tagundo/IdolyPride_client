"""Shipping typed queue/alias cleanup with no GPU/provider call under Cancel."""
import subprocess

import pytest

from test_mp4_capture_queue import FIXTURES, compile_host


CASES = """bind_source bind_pending bind_queue bind_queue_changed bind_root1
bind_root2 bind_root3 partial_empty partial_pending foreign_same_target empty
pending reentry throws foreign prefix post_foreign ctor_withdraw queue
queue_changed foreign_already_consumed owner_still_aliases handoff_still_aliases
unwound gpu producer native_changed texture_changed handoff callout_reentry
thread lost_root withdrawn_empty consumers_callout_add foreign_during_remove
producer_epoch producer_job producer_unpublished gate_busy reader_before_load
reader_old_pointer""".split()


@pytest.fixture(scope="module")
def alias_host(tmp_path_factory):
    source = ((FIXTURES / "mp4_capture_alias_prefix.cpp.inc").read_text()
              + "\n// @ALIAS_HOST@\n"
              + (FIXTURES / "mp4_capture_alias_driver.cpp.inc").read_text())
    return compile_host(tmp_path_factory.mktemp("capture-alias"), "alias", source,
                        fixture_warnings=True)


@pytest.mark.parametrize("case", CASES)
def test_actual_typed_alias_cancel(case, alias_host):
    result = subprocess.run([str(alias_host), case], text=True, capture_output=True,
                            timeout=15)
    assert result.returncode == 0, (case, result.stderr)
