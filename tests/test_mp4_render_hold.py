"""Entire shipping render-hold bodies; original engine/query leaves are modeled."""
from pathlib import Path
import shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'tests/fixtures'
def block(s,name):
 a=s.index('// BEGIN_'+name);b=s.index('// END_'+name,a);return s[a:b]
@pytest.fixture(scope='module',params=['android','ios'])
def host(request,tmp_path_factory):
 bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
 source=(F/'mp4_render_hold_prefix.cpp.inc').read_text()
 for key,marker in [('CORE','MP4_RENDER_HOLD_CORE'),('HOST','MP4_RENDER_HOLD_HOST'),('RETIREMENT','MP4_RENDER_HOLD_RETIREMENT'),('CONSUMERS','MP4_GRAPHICS_CONSUMERS_RETIRED')]:source=source.replace('// SHIPPING_'+key,block(bridge,marker))
 source+=(F/'mp4_render_hold_driver.cpp.inc').read_text()
 path=tmp_path_factory.mktemp('render-hold-'+request.param)/'host.cpp';path.write_text(source);binary=path.with_suffix('')
 flags=['-DIDOLY_DARWIN_BRIDGE=1']if request.param=='ios'else[]
 r=subprocess.run([shutil.which('g++')or'clang++','-std=c++17','-g','-O1','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-fno-pie','-no-pie','-pthread',*flags,str(path),'-o',str(binary)],capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
 return binary
@pytest.mark.parametrize("case",['ordinary', 'missing_manual', 'frontend_wrong_replacement', 'frontend_missing_stub', 'existing_original_wait', 'ordinary_blocked', 'private_main', 'private_no_ticket', 'private_no_srp_receipt', 'private_wrong_context', 'private_no_programme', 'unexpected_nested', 'automatic_throw', 'offthread_held', 'manual_no_origin', 'manual_no_aux', 'manual_private', 'manual_nested', 'manual_throw', 'gpu_checkpoint_wait', 'activity_invalidates', 'scope_not_retired', 'logical_not_restored', 'full_capture_abort_before_primary', 'no_work_requires_cleanup', 'readback_wait', 'handoff', 'abandon', 'handoff_wrong_receiver', 'old_stack_cannot_forward', 'wrong_job', 'frontend_withdraw', 'reader_overflow', 'direct_without_frame', 'direct_good', 'direct_no_submit', 'direct_throw', 'direct_bad_frame', 'direct_bad_context', 'direct_duplicate', 'direct_wrong_receipt', 'direct_held_current', 'frame_bad_physical', 'frame_wrong_context', 'frame_no_reentry', 'frame_stale_physical', 'consumers_not_final', 'consumers_zero', 'consumers_slots', 'consumers_callback', 'consumers_request', 'consumers_readback', 'consumers_bank', 'consumers_gpu_wait', 'consumers_same_job', 'consumers_old_activity', 'consumers_after_frame_finish'])
def test_actual_render_hold(host,case):
 r=subprocess.run([str(host),case],capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
