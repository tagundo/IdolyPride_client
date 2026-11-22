"""Execute shipping source/producer bodies; VM/native/physical leaves modeled."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / 'tests/fixtures/mp4_timeline_animation'
S = (ROOT / 'client-presentation/native/bridge.cpp').read_text()
H = ''.join('#include <'+name+'>\n' for name in ['cstdint','cstddef','cstring','cstdlib','atomic','new','cassert','map','string'])

def block(name):
    a, z = '// BEGIN_'+name, '// END_'+name
    assert S.count(a) == S.count(z) == 1
    return S[S.index(a):S.index(z)+len(z)]+'\n'

def f(name):
    return F.joinpath(name).read_text()

def run(tmp_path, source, cases):
    cc = shutil.which('g++')
    if not cc:
        pytest.skip('C++ sanitizer compiler unavailable')
    path, exe = tmp_path/'actual.cpp', tmp_path/'actual'
    path.write_text(source)
    cmd = [cc,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-g','-O1','-fsanitize=address,undefined','-fno-pie','-no-pie','-pthread',str(path),'-o',str(exe)]
    c = subprocess.run(cmd,capture_output=True,text=True)
    assert c.returncode == 0, c.stdout+c.stderr
    for case in cases:
        c = subprocess.run([str(exe),str(case)],capture_output=True,text=True)
        assert c.returncode == 0, (case,c.stdout,c.stderr)

def test_factory_journal(tmp_path):
    cases = 'source configure_missing offthread pins origin inspect missing_method missing_caller missing_tree wrong_root_track private_origin provider_reentry root_reentry active_receipt wrong_graph wrong_go wrong_tree wrong_owner nested infinite leaf_track leaf_self leaf_null bad_end_order source_changed original_threw invalid_return unsettled returned_changed after_changed invalidated superseded collect collect_capacity construction construction_parent construction_version construction_stale'.split()
    run(tmp_path,H+block('MP4_TIMELINE_ANIMATION_FACTORY_CORE')+f('factory-driver.cpp.inc'),cases)

@pytest.mark.parametrize('platform',['android','ios'])
def test_factory_host(tmp_path,platform):
    pins = block('MP4_TIMELINE_ANIMATION_FACTORY_PINS')
    pins = pins.replace('inline constexpr Mp4AnimationFactorySourcePins mp4_animation_factory_source_'+platform,'inline Mp4AnimationFactorySourcePins mp4_animation_factory_source_'+platform)
    pins = pins.replace('constexpr const auto&mp4_animation_factory_source=mp4_animation_factory_source_'+platform,'auto&mp4_animation_factory_source=mp4_animation_factory_source_'+platform)
    src = ('#define IDOLY_DARWIN_BRIDGE 1\n' if platform=='ios' else '')+f('factory-host-prefix.cpp.inc')+pins+block('MP4_TIMELINE_ANIMATION_FACTORY_CORE')+block('MP4_TIMELINE_ANIMATION_FACTORY_HOST')+f('factory-host-driver.cpp.inc')
    cases = 'origin_ordinary origin_private origin_none origin_foreign_go unsettled wrong_settle_identity inspect_track inspect_child inspect_wrong_type inspect_offset inspect_dead inspect_clip events legacy human nonfinite mode loop nested_child nested_wrong_caller nested_cycle clip_nested clip_wrong_caller clip_wrong_mode returned returned_foreign configured static_callback static_missing'.split()
    run(tmp_path,src,cases)

def test_factory_frontends(tmp_path):
    src = H+'using Method=void;bool game_call(){return true;}\n'+block('MP4_TIMELINE_ANIMATION_FACTORY_CORE')+'\nmp4_animation_factory::Journal mp4_animation_factories;\n'+block('MP4_TIMELINE_ANIMATION_FACTORY_PUBLICATION')+block('MP4_TIMELINE_ANIMATION_FACTORY_FRONTENDS')+f('factory-frontends-driver.cpp.inc')
    run(tmp_path,src,['root','clips','infinite','clip','root_throw','clips_throw','infinite_throw','clip_throw'])

def test_runtime_publication(tmp_path):
    run(tmp_path,f('runtime-prefix.cpp.inc')+block('MP4_TIMELINE_ANIMATION_RUNTIME_PUBLICATION_HOST')+f('runtime-driver.cpp.inc'),['all'])

def test_native_programme(tmp_path):
    run(tmp_path,H+block('MP4_TIMELINE_ANIMATION_FACTORY_CORE')+block('MP4_TIMELINE_ANIMATION_PROGRAMME_CORE')+f('programme-driver.cpp.inc'),['all'])

def test_actual_context_destructor_cache_order(tmp_path):
    src = block('MP4_TIMELINE_ANIMATION_PRODUCER_HOST')
    src = src[src.index('struct Mp4AnimationCachedPlan'):src.index('// Reuse only')]
    prefix = f('producer-cache-prefix.cpp.inc')
    a = prefix.index('~Mp4TimelineContext(){')
    z = prefix.index('\n};',a)
    start = S.index('    ~Mp4TimelineContext() {')
    destructor = S[start:S.index('    bool keep(',start)]
    prefix = prefix[:a]+destructor+prefix[z:]
    prefix = prefix.replace('namespace idoly_mp4_actor_placement','void weak_free(uint32_t){m.events.push_back(30);++m.releases;}\nnamespace idoly_mp4_actor_placement',1)
    run(tmp_path,prefix+src+f('producer-cache-driver.cpp.inc'),range(11))

def test_native_producer_runtime_and_output(tmp_path):
    src = block('MP4_TIMELINE_ANIMATION_PRODUCER_HOST')
    a = src.index('bool mp4_animation_phase_closed')
    selected = src[a:src.index('bool mp4_animation_native_output_program',a)]
    a = src.index('[[maybe_unused]] bool mp4_animation_timeline_output_closed')
    selected += src[a:src.index('// END_MP4_TIMELINE_ANIMATION_PRODUCER_HOST',a)]
    driver = f('producer-driver.cpp.inc').replace('mp4_timeline_animation_runtime;','').replace('mp4world::AnimationOutput output{};Mp4TimelineRuntime r{};','Mp4TimelineRuntime r{};')
    run(tmp_path,f('producer-prefix.cpp.inc')+selected+driver,range(38))


def test_factory_configuration_publication_concurrency(tmp_path):
    prefix = H+'#include <thread>\nusing Method=void;static const std::thread::id main_thread=std::this_thread::get_id();bool game_call(){return std::this_thread::get_id()==main_thread;}\n'
    source = prefix+block('MP4_TIMELINE_ANIMATION_FACTORY_CORE')+'\nmp4_animation_factory::Journal mp4_animation_factories;\n'+block('MP4_TIMELINE_ANIMATION_FACTORY_PUBLICATION')+block('MP4_TIMELINE_ANIMATION_FACTORY_FRONTENDS')+f('factory-publication-driver.cpp.inc')
    run(tmp_path,source,['source','throw','failed_configure'])
