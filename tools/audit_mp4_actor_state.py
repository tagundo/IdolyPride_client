#!/usr/bin/env python3
"""Pin typed ActorSwing/state APIs to both unchanged original clients.

This attests bindings, layouts and original fence/worker instructions. It does
not authorize an offline export: live owner/fence/job-state proofs are separate.
Android Burst is a separate image and must be verified and hooked separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original, need
from extract_client_schema import ClientImage

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "android": ("68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3", "f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e"),
    "ios": ("b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf", "d11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda"),
}
BURST_SHA = "b80c6bde7110afa1fad8ac053cb71cbac13a1479c75f6acd3198a2032141b45a"
BURST_SYMBOL = "efaef804e44554aa5845633afa905c07"
SELECT = {
    "get_job_data": ("UnityEngine.Playables.PlayableHandle", "GetJobData_Injected", 1),
    "get_job_type": ("UnityEngine.Playables.PlayableHandle", "GetJobType_Injected", 1),
    "output_target": ("UnityEngine.Animations.AnimationPlayableOutput", "InternalGetTarget", 1),
    "complete": ("Unity.Jobs.JobHandle", "Complete", 0),
    "reset_dynamic": ("ActorSwing.ActorSwingRig", "ResetDynamicBone", 0),
    "reset_breast": ("ActorSwing.ActorSwingRig", "ResetBreastBone", 0),
    "animator_mode_get": ("UnityEngine.Animator", "get_updateMode", 0),
    "animator_mode_set": ("UnityEngine.Animator", "set_updateMode", 1),
    "animator_culling_get": ("UnityEngine.Animator", "get_cullingMode", 0),
    "animator_culling_set": ("UnityEngine.Animator", "set_cullingMode", 1),
    "graph_root_count": ("UnityEngine.Playables.PlayableGraph", "GetRootPlayableCount_Injected", 1),
    "graph_root": ("UnityEngine.Playables.PlayableGraph", "GetRootPlayableInternal_Injected", 3),
    "playable_valid": ("UnityEngine.Playables.PlayableHandle", "IsValid_Injected", 1),
    "playable_time": ("UnityEngine.Playables.PlayableHandle", "GetTime_Injected", 1),
    "playable_input_count": ("UnityEngine.Playables.PlayableHandle", "GetInputCount_Injected", 1),
    "playable_input": ("UnityEngine.Playables.PlayableHandle", "GetInputHandle_Injected", 3),
    "root_transform": ("UnityEngine.Component", "get_transform", 0),
    "get_game_object": ("UnityEngine.Component", "get_gameObject", 0),
    "get_components_internal": ("UnityEngine.GameObject", "GetComponentsInternal", 6),
    "parent": ("UnityEngine.Transform", "get_parent", 0),
    "local_position": ("UnityEngine.Transform", "get_localPosition_Injected", 1),
    "local_rotation": ("UnityEngine.Transform", "get_localRotation_Injected", 1),
    "local_scale": ("UnityEngine.Transform", "get_localScale_Injected", 1),
    "set_local_position_rotation": ("UnityEngine.Transform", "SetLocalPositionAndRotation_Injected", 2),
    "set_local_scale": ("UnityEngine.Transform", "set_localScale_Injected", 1),
    "managed_process": ("ActorSwing.ActorSwingJob", "ProcessAnimation", 1),
}
FIELDS = {
    "actor_player": ("VL.Core.VLActorController", "_animationPlayer", 0x20),
    "actor_animator": ("VL.Core.VLActorController", "_animator", 0x30),
    "actor_extensions": ("VL.Core.VLActorController", "_extensions", 0x40),
    "extension_rig": ("VL.VLActorActorSwing", "_actorSwingRig", 0x28),
    "extension_player": ("VL.VLActorActorSwing", "_animationClipPlayer", 0x30),
    "extension_builder": ("VL.VLActorActorSwing", "_builder", 0x48),
    "builder_output": ("ActorSwing.ActorSwingBuilder", "_output", 0x30),
    "builder_playable": ("ActorSwing.ActorSwingBuilder", "_playable", 0x40),
    "builder_rig": ("ActorSwing.ActorSwingBuilder", "_actorSwingRig", 0x50),
    "player_animator": ("VL.VLAnimationClipPlayerBase", "_animator", 0x20),
    "player_graph": ("VL.VLAnimationClipPlayerBase", "_graph", 0x28),
    "rig_job": ("ActorSwing.ActorSwingRig", "_job", 0x50),
    "rig_initialized": ("ActorSwing.ActorSwingRig", "<isInitialized>k__BackingField", 0x58),
    "cached_ptr": ("UnityEngine.Object", "m_CachedPtr", 0x10),
}
STRUCTS = {"job": ("ActorSwing.ActorSwingJob", 0x168),
    "job_handle": ("Unity.Jobs.JobHandle", 16),
    "graph": ("UnityEngine.Playables.PlayableGraph", 16),
    "playable": ("UnityEngine.Playables.PlayableHandle", 16),
    "output": ("UnityEngine.Playables.PlayableOutputHandle", 16),
    "transform_stream_handle": ("UnityEngine.Animations.TransformStreamHandle", 12),
    "property_stream_handle": ("UnityEngine.Animations.PropertyStreamHandle", 16),
    "transform_scene_handle": ("UnityEngine.Animations.TransformSceneHandle", 8),
    "readonly_transform_handle": ("UnityEngine.Animations.Rigging.ReadOnlyTransformHandle", 24),
    "stream": ("UnityEngine.Animations.AnimationStream", 56),
    "vector3": ("UnityEngine.Vector3", 12), "quaternion": ("UnityEngine.Quaternion", 16),
    "dynamic": ("ActorSwing.ActorSwingJobDynamicBone", 0x338),
    "static": ("ActorSwing.ActorSwingJobStaticBone", 0x84),
    "breast": ("ActorSwing.ActorSwingJobBreastBone", 0x13c),
    "chain": ("ActorSwing.ActorSwingJobChainBone", 0x7c)}


def runtime_type(original, name, kind):
    tid = original.type_id(name); index = original.types[tid][1][2]
    pointer = original.qword(original.type_table + index * 8)
    prefix = original.b[original.offset(pointer):original.offset(pointer) + 16]
    need(prefix[10] == kind, "actor_runtime_type_kind_differs:" + name)
    need(struct.unpack_from("<Q", prefix)[0] == tid, "actor_runtime_type_index_differs:" + name)
    return {"type": name, "rva": hex(pointer), "prefix": prefix.hex(),
        "kind": kind, "metadata_type_definition_index": tid,
        "metadata_type_index": index, "type_table_pointer_slot": hex(original.type_table + index * 8),
        "runtime_validation": "exact_resolved_metadata_row_plus_tail8_then_exact_class_identity"}


def burst_symbol(native, original, platform):
    found=[]
    if platform=="android":
        shoff=struct.unpack_from("<Q",native,40)[0]
        stride,count=struct.unpack_from("<HH",native,58)
        sections=[struct.unpack_from("<II4QII2Q",native,shoff+i*stride)for i in range(count)]
        for section in sections:
            if section[1]!=11:continue
            strings=sections[section[6]]
            for at in range(section[4],section[4]+section[5],section[9]):
                name,kind,_,_,address,size=struct.unpack_from("<IBBHQQ",native,at)
                begin=strings[4]+name;end=native.index(0,begin,strings[4]+strings[5])
                if native[begin:end]!=BURST_SYMBOL.encode():continue
                need(kind&15==2 and address and size,"actor_burst_symbol_not_function")
                found.append({"rva":hex(address),"bytes":size,"table":"ELF_DYNSYM","kind":kind})
    else:
        symoff,count,strings,string_bytes=original.symtab
        for i in range(count):
            index,kind,section,_,address=struct.unpack_from("<IBBHQ",native,symoff+i*16)
            if index>=string_bytes:continue
            begin=strings+index;end=native.index(0,begin,strings+string_bytes)
            if native[begin:end]!=("_"+BURST_SYMBOL).encode():continue
            need(kind&1 and kind&0xe==0xe and section,"actor_burst_symbol_not_text")
            found.append({"rva":hex(address),"table":"MACHO_NLIST","kind":kind,"section":section})
    need(len(found)==1,"actor_burst_symbol_missing_or_ambiguous")
    return found[0]


def native_graph_mode(native,image,platform):
    """The originals strip the getter; attest the original setter's field path."""
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    dis=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    offset=image.file_offset if platform=="android"else image.offset
    addresses=((0x4996fc,0x7345e8,0x734214,0x72d7a4)if platform=="android"else(0xb365f4,0xdca4c0,0xdca0ac,0xdc3c60))
    methods={}
    for name,address,size in zip(("mode_icall","mode_dispatch","graph_validate","mode_setter"),addresses,(0x38,0x40,16,0x20)):
        raw=native[offset(address):offset(address)+size]
        methods[name]={"rva":hex(address),"prefix":raw[:16].hex(),"instructions":[{"rva":hex(row.address),"bytes":row.bytes.hex(),"instruction":row.mnemonic+" "+row.op_str}for row in dis.disasm(raw,address)]}
    text=lambda name:[row["instruction"]for row in methods[name]["instructions"]]
    need("bl #"+hex(addresses[1])in text("mode_icall"),"actor_graph_mode_icall_target_differs")
    need("bl #"+hex(addresses[2])in text("mode_dispatch"),"actor_graph_mode_validation_target_differs")
    need("ldr x8, [x20]"in text("mode_dispatch")and"ldr x0, [x8, #0x28]"in text("mode_dispatch"),"actor_native_graph_owner_path_differs")
    need("b #"+hex(addresses[3])in text("mode_dispatch"),"actor_graph_mode_setter_target_differs")
    need(text("mode_setter")[0]=="ldr w8, [x0, #0x18]"and"str w1, [x0, #0x18]"in text("mode_setter"),"actor_graph_mode_field_differs")
    # The named registration must independently identify the same icall body.
    key=b"UnityEngine.Playables.PlayableGraph::SetTimeUpdateMode_Injected\0"
    need(b"UnityEngine.Playables.PlayableGraph::GetTimeUpdateMode_Injected\0"not in native,"actor_graph_getter_registration_changed")
    found=native.find(key);need(found>=0 and native.find(key,found+1)<0,"actor_graph_mode_icall_name_ambiguous")
    for start,end,file_offset in image.segments:
        if file_offset<=found<file_offset+end-start:string_rva=start+found-file_offset;break
    else:raise ValueError("actor_graph_mode_icall_name_unmapped")
    pattern=struct.pack("<I",0x91000000|((string_rva&4095)<<10));at=0;registrations=[]
    while(at:=native.find(pattern,at))>=0:
        if at%4==0 and at>=8:
            for back in(4,8):
                try:
                    for start,end,file_offset in image.segments:
                        if file_offset<=at-back<file_offset+end-start:entry=start+at-back-file_offset;break
                    else:continue
                    rows=list(dis.disasm(native[at-back:at-back+20],entry));regs={}
                    for row in rows:
                        parts=row.op_str.split(", ")
                        if row.mnemonic=="adrp":regs[parts[0]]=int(parts[1][1:],0)
                        elif row.mnemonic=="add"and len(parts)==3 and parts[1]in regs and parts[2].startswith("#"):
                            regs[parts[0]]=regs[parts[1]]+int(parts[2][1:],0)
                    if len(rows)==5 and regs.get("x0")==string_rva and regs.get("x1")==addresses[0]and rows[-1].mnemonic in("b","bl"):
                        registrations.append({"rva":hex(entry),"bytes":b"".join(row.bytes for row in rows).hex()})
                except ValueError:pass
        at+=4
    need(len(registrations)==1,"actor_graph_mode_registration_differs")
    return {"engine_sha256":hashlib.sha256(native).hexdigest(),"methods":methods,
        "registration":registrations[0],"node_graph":0x28,"graph_mode":0x18,
        "read_contract":"original_Graph_IsValid_then_bounded_node_and_graph_maps_then_I32_enum_0_to_3_no_writes",
        "managed_getter_present":False,"native_getter_registered":False}


def handle_resolution(native,image,platform):
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    dis=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    offset=image.file_offset if platform=="android"else image.offset
    result={}
    for name,address in (("transform",0x8e42ac if platform=="android"else 0xf40410),
                         ("property",0x8e4c80 if platform=="android"else 0xf40e70)):
        raw=native[offset(address):offset(address)+84];rows=list(dis.disasm(raw,address))
        need(len(rows)==21 and rows[-1].mnemonic=="ret","actor_handle_resolver_boundary_differs")
        need(not any(row.mnemonic in("bl","blr","br")for row in rows),"actor_handle_resolver_unknown_call")
        stores=[row.op_str for row in rows if row.mnemonic.startswith(("st","cas","swp"))]
        need(stores==["w8, [x0, #8]","w8, [x0, #8]","w8, [x0]"],"actor_handle_resolver_write_set_differs")
        need(any(row.mnemonic=="ldrsw"and row.op_str=="x8, [x0, #4]"for row in rows),"actor_handle_resolver_identity_index_differs")
        result[name]={"rva":hex(address),"bytes":raw.hex(),"mutable_cache_offsets":[0,8],
            "immutable_handle_index":4,"immutable_bind_type":12 if name=="property"else None,
            "instructions":[{"rva":hex(row.address),"bytes":row.bytes.hex(),"instruction":row.mnemonic+" "+row.op_str}for row in rows]}
    return result


def profile(original, platform, burst, engine):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    native_pin, metadata_pin = PINS[platform]
    need(hashlib.sha256(original.b).hexdigest() == native_pin, "actor_original_native_pin_mismatch")
    need(hashlib.sha256(original.m).hexdigest() == metadata_pin, "actor_original_metadata_pin_mismatch")
    methods = {alias: original.method(*arguments) for alias, arguments in SELECT.items()}
    graph_row=original.types[original.type_id("UnityEngine.Playables.PlayableGraph")][1]
    graph_names={original.string(struct.unpack_from("<I",original.m,original.h[12]+mid*36)[0])
        for mid in range(graph_row[9],graph_row[9]+graph_row[16])}
    need(not graph_names.intersection(("GetTimeUpdateMode","GetTimeUpdateMode_Injected")),"actor_managed_graph_getter_changed")
    for method in methods.values():
        args = [] if method["static"] else ["void*"]
        args.extend(original.native_type(row["type"]) for row in method["parameters"])
        method["native_abi"] = original.native_type(method["return"]) + "(" + ",".join([*args, "const MethodInfo*"]) + ")"
    need(methods["managed_process"]["parameters"][0]["type"] == "UnityEngine.Animations.AnimationStream", "actor_process_signature_differs")
    methods["managed_process"]["native_abi"] = "void(void* unboxedJobX0,const AnimationStream56* indirectX1,const MethodInfo* X2)"
    fields = {}
    for alias, (owner, name, expected) in FIELDS.items():
        row = original.fields(owner)[name]
        need(row["offset"] == expected, "actor_field_differs:" + alias)
        fields[alias] = {"owner": owner, "name": name, **row}
    fields["native_animator_job"] = {"offset": 0x238, "type": "Unity.Jobs.JobHandle", "scope": "native_Animator_not_managed_metadata"}
    layouts = {}
    for alias, (name, expected) in STRUCTS.items():
        row = original.struct_layout(name)
        need(row["bytes"] == expected, "actor_struct_size_differs:" + alias)
        layouts[alias] = {"type": name, **row}
    need([layouts["job"]["fields"][name] for name in ("dynamicBones", "staticBones", "breastBones", "chainBones", "_time")] == [0x28, 0x38, 0x48, 0x98, 0x164], "actor_job_fields_differ")
    native = engine if platform == "android" else original.b
    need(hashlib.sha256(native).hexdigest() == ("c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85" if platform == "android" else native_pin), "actor_engine_pin_mismatch")
    image = ClientImage(original.m, native) if platform == "android" else original
    offset = image.file_offset if platform == "android" else image.offset
    dis = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    fence_rva = 0x8b369c if platform == "android" else 0xf0abd4
    instruction = list(dis.disasm(native[offset(fence_rva):offset(fence_rva)+4], fence_rva))[0]
    need(instruction.mnemonic == "add" and instruction.op_str == "x24, x23, #0x238", "actor_animator_fence_address_differs")
    retire_rva = 0x62c988 if platform == "android" else 0xcb6a98
    retired = list(dis.disasm(native[offset(retire_rva):offset(retire_rva)+8], retire_rva))
    need([(row.mnemonic,row.op_str) for row in retired] == [("str","xzr, [x20]"),("str","wzr, [x20, #8]")], "actor_original_complete_retire_differs")
    fence = {"engine_sha256": hashlib.sha256(native).hexdigest(),
        "address": {"rva": hex(fence_rva), "bytes": instruction.bytes.hex(), "instruction": instruction.mnemonic+" "+instruction.op_str},
        "retire": [{"rva":hex(row.address),"bytes":row.bytes.hex(),"instruction":row.mnemonic+" "+row.op_str} for row in retired],
        "contract": "Complete_actual_retained_Animator_cached_ptr_plus_0x238_not_copy; validate_identity_before_and_after"}
    burst_bytes = burst if platform == "android" else original.b
    burst_sha = BURST_SHA if platform == "android" else native_pin
    need(hashlib.sha256(burst_bytes).hexdigest() == burst_sha, "actor_burst_image_pin_mismatch")
    burst_image = ClientImage(original.m, burst_bytes) if platform == "android" else original
    burst_offset = burst_image.file_offset if platform == "android" else burst_image.offset
    burst_rva = 0x34428 if platform == "android" else 0x81c615c
    symbol=burst_symbol(burst_bytes,original,platform)
    need(symbol["rva"]==hex(burst_rva),"actor_burst_symbol_address_differs")
    prefix = burst_bytes[burst_offset(burst_rva):burst_offset(burst_rva)+16].hex()
    need(prefix == ("ee0f19fcedb3006debab016de9a3026d" if platform == "android" else "ef3bb96ded33016deb2b026de923036d"), "actor_burst_entry_differs")
    branch_code=list(dis.disasm(burst_bytes[burst_offset(burst_rva):burst_offset(burst_rva)+0x40],burst_rva))
    need(any(row.mnemonic=="cbz"and row.op_str.startswith("w2, ")for row in branch_code),"actor_burst_rootmotion_dispatch_differs")
    need(any(row.mnemonic=="cmp"and row.op_str=="w2, #1"for row in branch_code),"actor_burst_animation_dispatch_differs")
    methods["burst_execute"] = {"rva":hex(burst_rva),"prefix":prefix,"symbol":BURST_SYMBOL,
        "native_abi":"void(void* jobX0,const AnimationStream56* streamX1,intptr_t methodIndexX2,JobRanges* rangesX3,int32_t jobIndexW4)",
        "image":"lib_burst_generated.so" if platform=="android" else "UnityFramework",
        "native_sha256":burst_sha,"process_tag":1,"root_motion_tag":0,
        "symbol_proof":symbol,"dispatch_instructions":[{"rva":hex(row.address),"bytes":row.bytes.hex(),"instruction":row.mnemonic+" "+row.op_str}for row in branch_code],
        "runtime_requirement":"both_managed_and_burst_routes_verified_installed_before_owned_registry_publication"}
    return {"sources":{"native_sha256":native_pin,"metadata_sha256":metadata_pin,"burst_native_sha256":burst_sha},
        "methods":methods,"fields":fields,"structs":layouts,"fence":fence,"native_graph":native_graph_mode(native,image,platform),
        "handle_resolution":handle_resolution(native,image,platform),
        "types":{"actor_job_type":runtime_type(original,"ActorSwing.ActorSwingJob",17),"transform_type":runtime_type(original,"UnityEngine.Transform",18)},
        "scope":{"game_or_gpu_executed":False,"offline_scene_pipeline_verified":False,
            "live_job_completion_and_owner_state_validation_required":True,"all_procedural_or_physics_coverage_claimed":False}}


def render(profiles):
    aliases = [*SELECT,"burst_execute"]
    fields = [*FIELDS,"native_animator_job"]
    lines = ["// SPDX-License-Identifier: AGPL-3.0-or-later", "#pragma once",
        "// Generated by tools/audit_mp4_actor_state.py from exact original clients.",
        "#ifndef IDOLY_DARWIN_BRIDGE", "#include <stdint.h>", "#endif", "namespace idoly_mp4_actor {",
        "struct ActorBinding { uintptr_t rva;uint8_t prefix[16]; };",
        "struct ActorNativeGraphProfile { const char* engine_sha256;ActorBinding mode_icall,mode_dispatch,graph_validate,mode_setter;uint32_t node_graph,graph_mode; };",
        "struct ActorFields {"]
    lines += ["    uint32_t "+name+";" for name in fields]
    lines += ["};", "struct ActorProfile {", "    const char* native_sha256;const char* metadata_sha256;const char* burst_native_sha256;"]
    lines += ["    ActorBinding "+name+";" for name in [*aliases,"actor_job_type","transform_type"]]
    lines += ["    ActorFields fields;", "    ActorNativeGraphProfile native_graph;", "};"]
    for platform, value in profiles.items():
        lines += ["inline constexpr ActorProfile "+platform+"_actor_profile={"]
        lines += ["    \""+value["sources"][key]+"\"," for key in ("native_sha256","metadata_sha256","burst_native_sha256")]
        for name in [*aliases,"actor_job_type","transform_type"]:
            row = value["methods" if name in aliases else "types"][name]
            lines += ["    {"+row["rva"]+",{"+",".join("0x"+row["prefix"][i:i+2] for i in range(0,32,2))+"}}, // "+name]
        lines += ["    {"+",".join(hex(value["fields"][name]["offset"]) for name in fields)+"},"]
        graph=value["native_graph"]
        lines += ["    {\""+graph["engine_sha256"]+"\","]
        for name in("mode_icall","mode_dispatch","graph_validate","mode_setter"):
            row=graph["methods"][name]
            lines += ["        {"+row["rva"]+",{"+",".join("0x"+row["prefix"][i:i+2]for i in range(0,32,2))+"}}, // "+name]
        lines += ["        "+hex(graph["node_graph"])+","+hex(graph["graph_mode"])+"}","};"]
    return "\n".join([*lines,"} // namespace idoly_mp4_actor",""])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,default=ROOT/"client-presentation/native")
    args=parser.parse_args(); p=args.originals
    profiles={}
    for platform,constructor,metadata,native in (("android",OriginalAndroid,"android-metadata.dat","android-native.so"),("ios",Original,"ios-metadata.dat","ios-native.bin")):
        original=constructor((p/metadata).read_bytes(),(p/native).read_bytes())
        profiles[platform]=profile(original,platform,(p/"mp4-android-analysis/lib_burst_generated.so").read_bytes(),(p/"mp4-android-analysis/libunity.so").read_bytes())
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"mp4_actor_state_profile.json").write_text(json.dumps({"schema":1,"platforms":profiles},indent=2)+"\n")
    (args.output_dir/"mp4_actor_state_profile.hpp").write_text(render(profiles))
    print("PASS original Actor state bindings/layouts, pure fence address, dual worker image pins; live pipeline admission remains separate")


if __name__=="__main__":main()
