"""Original Actor state APIs/layouts and their exact compiled source contract."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/"client-presentation/native"
PROFILE=NATIVE/"mp4_actor_state_profile.json"
DATA=json.loads(PROFILE.read_text())["platforms"]


@pytest.mark.parametrize("platform",["android","ios"])
def test_actor_profile_original_owner_and_value_layouts(platform):
    value=DATA[platform]
    assert value["fields"]["native_animator_job"]["offset"]==0x238
    assert value["fields"]["cached_ptr"]["offset"]==0x10
    assert [value["fields"][key]["offset"]for key in ("actor_player","actor_animator","actor_extensions")]==[0x20,0x30,0x40]
    assert [value["fields"][key]["offset"]for key in ("extension_rig","extension_player","extension_builder")]==[0x28,0x30,0x48]
    assert [value["fields"][key]["offset"]for key in ("builder_output","builder_playable","builder_rig")]==[0x30,0x40,0x50]
    assert [value["fields"][key]["offset"]for key in ("player_animator","player_graph","rig_job","rig_initialized")]==[0x20,0x28,0x50,0x58]
    assert value["structs"]["job"]["bytes"]==0x168
    assert [value["structs"]["job"]["fields"][key]for key in ("dynamicBones","staticBones","breastBones","chainBones","_time")]==[0x28,0x38,0x48,0x98,0x164]
    assert [value["structs"][key]["bytes"]for key in ("dynamic","static","breast","chain")]==[0x338,0x84,0x13c,0x7c]
    assert value["structs"]["job_handle"]["fields"]=={"jobGroup":0,"version":8}
    assert [value["structs"][key]["bytes"]for key in ("job_handle","graph","playable","output","stream","vector3","quaternion")]==[16,16,16,16,56,12,16]


@pytest.mark.parametrize("platform",["android","ios"])
def test_actor_profile_uses_both_exact_typed_worker_routes(platform):
    methods=DATA[platform]["methods"]
    assert methods["managed_process"]["rva"]==("0x42639e0"if platform=="android"else"0x196b208")
    assert methods["managed_process"]["parameters"]==[{"name":"stream","type":"UnityEngine.Animations.AnimationStream","metadata_type_index":methods["managed_process"]["parameters"][0]["metadata_type_index"]}]
    assert "indirectX1"in methods["managed_process"]["native_abi"]
    burst=methods["burst_execute"]
    assert burst["rva"]==("0x34428"if platform=="android"else"0x81c615c")
    assert burst["symbol_proof"]["rva"]==burst["rva"]
    assert "rangesX3,int32_t jobIndexW4"in burst["native_abi"]
    assert burst["process_tag"]==1 and burst["root_motion_tag"]==0
    instructions=[row["instruction"]for row in burst["dispatch_instructions"]]
    assert "cmp w2, #1"in instructions
    assert any(row.startswith("cbz w2, ")for row in instructions)
    assert burst["runtime_requirement"]=="both_managed_and_burst_routes_verified_installed_before_owned_registry_publication"


@pytest.mark.parametrize("platform",["android","ios"])
def test_actor_profile_fence_completes_actual_native_animator_storage(platform):
    fence=DATA[platform]["fence"]
    assert fence["address"]["instruction"]=="add x24, x23, #0x238"
    assert [row["instruction"]for row in fence["retire"]]==["str xzr, [x20]","str wzr, [x20, #8]"]
    assert "not_copy"in fence["contract"]
    assert DATA[platform]["methods"]["complete"]["type"]=="Unity.Jobs.JobHandle"
    assert not DATA[platform]["methods"]["complete"]["static"]


@pytest.mark.parametrize("platform",["android","ios"])
def test_actor_profile_mutable_types_have_exact_runtime_attestation(platform):
    value=DATA[platform]
    for alias,kind in (("actor_job_type",17),("transform_type",18)):
        row=value["types"][alias]
        prefix=bytes.fromhex(row["prefix"])
        assert prefix[10]==kind and row["kind"]==kind
        assert int.from_bytes(prefix[:8],"little")==row["metadata_type_definition_index"]
        assert row["runtime_validation"]=="exact_resolved_metadata_row_plus_tail8_then_exact_class_identity"
    assert value["scope"]["offline_scene_pipeline_verified"]is False
    assert value["scope"]["all_procedural_or_physics_coverage_claimed"]is False


@pytest.mark.parametrize("platform",["android","ios"])
def test_actor_native_graph_mode_proves_field_instead_of_inventing_getter(platform):
    graph=DATA[platform]["native_graph"]
    assert graph["managed_getter_present"]is False and graph["native_getter_registered"]is False
    assert graph["node_graph"]==0x28 and graph["graph_mode"]==0x18
    methods=graph["methods"]
    dispatch=[row["instruction"]for row in methods["mode_dispatch"]["instructions"]]
    assert "bl #"+methods["graph_validate"]["rva"]in dispatch
    assert "ldr x8, [x20]"in dispatch and "ldr x0, [x8, #0x28]"in dispatch
    assert "b #"+methods["mode_setter"]["rva"]in dispatch
    assert methods["mode_setter"]["instructions"][0]["instruction"]=="ldr w8, [x0, #0x18]"
    assert "original_Graph_IsValid"in graph["read_contract"]and"no_writes"in graph["read_contract"]


@pytest.mark.parametrize("platform",["android","ios"])
def test_actor_original_native_setter_updates_exact_graph_mode_field(platform):
    # Execute the actual original leaf for non-Manual values. Manual(3) has
    # its own original timing-reset tail and is not emulated as a fake RET.
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_LR
    row=DATA[platform]["native_graph"]["methods"]["mode_setter"]
    address=int(row["rva"],0);page=address&~4095
    body=b"".join(bytes.fromhex(value["bytes"])for value in row["instructions"])
    for mode in range(3):
        uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);uc.mem_map(page,4096);uc.mem_write(address,body)
        uc.mem_map(0x20000000,4096);uc.mem_map(0x30000000,4096)
        memory=bytearray(b"\xa5"*256);memory[0x18:0x1c]=(9).to_bytes(4,"little")
        uc.mem_write(0x20000000,bytes(memory));uc.reg_write(UC_ARM64_REG_X0,0x20000000)
        uc.reg_write(UC_ARM64_REG_X1,mode);uc.reg_write(UC_ARM64_REG_LR,0x30000000)
        uc.emu_start(address,0x30000000,count=32)
        memory[0x18:0x1c]=mode.to_bytes(4,"little")
        assert bytes(uc.mem_read(0x20000000,256))==memory


@pytest.mark.parametrize("platform",["android","ios"])
@pytest.mark.parametrize("kind",["transform","property"])
def test_actor_original_handle_resolve_changes_caches_and_preserves_identity(platform,kind):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_LR
    row=DATA[platform]["handle_resolution"][kind]
    assert row["mutable_cache_offsets"]==[0,8]and row["immutable_handle_index"]==4
    address=int(row["rva"],0);uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    uc.mem_map(address&~4095,4096);uc.mem_write(address,bytes.fromhex(row["bytes"]))
    uc.mem_map(0x20000000,4096);uc.mem_map(0x30000000,4096)
    # Original invalid-index resolution still updates both cache fields. Its
    # immutable identity and property bindType must survive that real mutation.
    memory=bytearray(b"\xa5"*32);memory[:4]=(77).to_bytes(4,"little")
    memory[4:8]=(-1).to_bytes(4,"little",signed=True)
    uc.mem_write(0x20000000,bytes(memory));uc.reg_write(UC_ARM64_REG_X0,0x20000000)
    uc.reg_write(UC_ARM64_REG_X1,0);uc.reg_write(UC_ARM64_REG_LR,0x30000000)
    uc.emu_start(address,0x30000000,count=32)
    expected=bytearray(memory);expected[:4]=(1).to_bytes(4,"little")
    expected[8:12]=(-1).to_bytes(4,"little",signed=True)
    assert bytes(uc.mem_read(0x20000000,32))==expected


def test_actor_profile_header_is_exact_generated_data_and_compiles(tmp_path):
    sys.path.insert(0,str(ROOT/"tools"))
    try:
        spec=importlib.util.spec_from_file_location("audit_actor",ROOT/"tools/audit_mp4_actor_state.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        assert module.render(DATA)==(NATIVE/"mp4_actor_state_profile.hpp").read_text()
    finally:sys.path.pop(0)
    compiler=shutil.which("g++")
    assert compiler,"C++ compiler required"
    code='''#include "mp4_actor_state_profile.hpp"
using namespace idoly_mp4_actor;
static_assert(android_actor_profile.fields.native_animator_job==0x238);
static_assert(ios_actor_profile.fields.builder_playable==0x40);
static_assert(android_actor_profile.managed_process.rva==0x42639e0);
static_assert(ios_actor_profile.managed_process.rva==0x196b208);
int main(){return 0;}
'''
    subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror","-I",str(NATIVE),"-x","c++","-","-o",str(tmp_path/"profile")],input=code,text=True,check=True,capture_output=True)
    subprocess.run([str(tmp_path/"profile")],check=True)


def test_actor_profile_reproduces_from_both_whole_originals(tmp_path):
    originals=os.environ.get("IDOLY_MP4_ORIGINALS_DIR")
    if not originals:pytest.skip("whole-original regeneration requires pinned original files")
    subprocess.run([sys.executable,str(ROOT/"tools/audit_mp4_actor_state.py"),"--originals",originals,"--output-dir",str(tmp_path)],check=True,capture_output=True,text=True)
    for name in ("mp4_actor_state_profile.hpp","mp4_actor_state_profile.json"):
        assert (tmp_path/name).read_bytes()==(NATIVE/name).read_bytes()
