"""Actual initial-source/ACTIVE GPU markers; engine/query leaves modeled."""
from pathlib import Path
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'tests/fixtures/mp4_active_gpu_workers'
MODES=['initial_no_cpu', 'initial_no_images', 'initial_too_late', 'initial_no_programme', 'initial_wait_once', 'initial_create_throw', 'initial_execute_throw', 'initial_source_lost_poll', 'initial_no_work_is_not_fence', 'initial_receipt_cannot_replace_ledger', 'baseline', 'historical_no_old_roster', 'production_empty', 'frame_complete', 'readback_missing', 'readback_wrong_operation', 'adapter_active', 'readback_active', 'adapter_pending', 'publication_pending', 'publication_bad_return', 'queue_nonempty', 'queue_readers', 'queue_untracked', 'queue_foreign', 'queue_cancel', 'queue_capture_tls', 'request_tls', 'bank_tls', 'native_reader', 'native_write_changed', 'native_untracked', 'render_depth', 'unowned_render_depth', 'render_ticket', 'draw_pending', 'draw_active', 'draw_unknown', 'draw_sealed', 'aux_pending', 'aux_missing_dispatch', 'poll_reentry_native_write', 'job_mismatch', 'foreign_production', 'frame_sealed', 'offthread']


def marker(text,name):
    begin=text.index('// BEGIN_'+name)
    end=text.index('// END_'+name,begin)
    return text[begin:end]


@pytest.fixture(scope='module')
def binaries(tmp_path_factory):
    bridge=(ROOT/'client-presentation/native/bridge.cpp').read_text()
    camera=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
    adapter=(ROOT/'client-presentation/native/mp4_game_adapter.hpp').read_text()
    core=marker(bridge,'MP4_GPU_FENCE_CORE')
    assert '// BEGIN_MP4_GPU_OPEN_WORKERS' in core
    start=bridge.index('namespace mp4_gl_completion {')
    end=bridge.index('} // namespace mp4_gl_completion',start)+len('} // namespace mp4_gl_completion')
    observer=bridge[start:end]
    ledger=(F/'ledger.cpp.inc').read_text().replace('// SHIPPING_GL_OBSERVER',observer).replace('// SHIPPING_GPU_FENCE_CORE',core)
    host_prefix=ledger.split('static Context ctx')[0]
    host_prefix='#include <atomic>\n#include <iostream>\n#include <functional>\nstd::function<void()>gpu_query_action;\n'+host_prefix
    host_prefix=host_prefix.replace('++h.queries;if(h.gl_switch_query)','++h.queries;if(gpu_query_action)gpu_query_action();if(h.gl_switch_query)')
    prefix=(F/'prefix.cpp.inc').read_text()
    work=marker(adapter,'MP4_ADAPTER_CAPTURE_WORKERS')
    prefix=prefix.replace('// SHIPPING_CAPTURE_WORK_SNAPSHOT','struct ModelGame {\n'+work+'\n CaptureWorkers capture_workers_{};bool capture_request_running_=false,capture_pending_=false,capture_pass_seen_=false,capture_submitted_=false;\n}game;')
    native=marker(bridge,'MP4_CAPTURE_NATIVE_PUBLICATION_HOST').split('#ifdef IDOLY_DARWIN_BRIDGE')[0]
    prefix=prefix.replace('// SHIPPING_NATIVE_READER',native)
    start=bridge.index('namespace idoly_mp4_capture_queue {\nclass Gate')
    end=bridge.index('// END_MP4_CAPTURE_QUEUE_GATE',start)
    replacements={
        'REQUEST_GUARD':marker(camera,'MP4_CAPTURE_PUBLICATION_GUARD'),
        'PRODUCTION_BANK':marker(camera,'MP4_CAPTURE_PRODUCTION_BANK'),
        'QUEUE_GATE':bridge[start:end],
        'QUEUE_JOURNAL':marker(bridge,'MP4_CAPTURE_QUEUE_JOURNAL'),
    }
    for key,body in replacements.items():prefix=prefix.replace('// SHIPPING_'+key,body)
    host=host_prefix+prefix+marker(bridge,'MP4_INITIAL_SOURCE_GPU_FENCE')+marker(bridge,'MP4_ACTIVE_GPU_WORKERS')+(F/'driver.cpp.inc').read_text()
    texts={'host':host,'ledger':ledger,'adapter':(F/'adapter.cpp.inc').read_text()}
    folder=tmp_path_factory.mktemp('active-gpu-workers')
    result={}
    for platform in ('android','ios'):
        for kind,text in texts.items():
            source=folder/(kind+'-'+platform+'.cpp');binary=folder/(kind+'-'+platform)
            source.write_text(text)
            flags=['-DIDOLY_DARWIN_BRIDGE=1']if platform=='ios'else[]
            subprocess.run(['g++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',*flags,'-I',str(ROOT/'client-presentation/native'),str(source),'-o',str(binary)],check=True)
            result[platform,kind]=binary
    return result


@pytest.mark.parametrize('platform,mode',[(p,m)for p in ('android','ios')for m in MODES])
def test_actual_active_gpu_workers(binaries,platform,mode):
    subprocess.run([str(binaries[platform,'host']),mode],check=True,timeout=30)


@pytest.mark.parametrize('platform',('android','ios'))
def test_actual_open_gpu_ledger(binaries,platform):
    result=subprocess.run([str(binaries[platform,'ledger'])],check=True,capture_output=True,text=True,timeout=30)
    assert '63 substantive cases passed' in result.stdout


@pytest.mark.parametrize('platform',('android','ios'))
def test_actual_adapter_capture_readback_receipts(binaries,platform):
    subprocess.run([str(binaries[platform,'adapter'])],check=True,timeout=30)
