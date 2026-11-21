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
# Exact managed callbacks and native presentation leaves. Mono callbacks remain
# live during a held native TimeManager and therefore have their own owned gate.
PRESENTATION_SELECT = {
    "actor_update": ("VL.Core.VLActorController", "Update", 0),
    "actor_late": ("VL.Core.VLActorController", "LateUpdate", 0),
    "eye_late": ("VL.VLActorEye", "LateUpdate", 0),
    "face_late": ("VL.VLActorFaceTargetCorrection", "LateUpdate", 0),
    "rig_update_constraints": ("ActorSwing.ActorSwingRig", "UpdateConstraints", 0),
    "blend_mesh": ("UnityEngine.SkinnedMeshRenderer", "get_sharedMesh", 0),
    "blend_count": ("UnityEngine.Mesh", "get_blendShapeCount", 0),
    "blend_get": ("UnityEngine.SkinnedMeshRenderer", "GetBlendShapeWeight", 1),
    "blend_set": ("UnityEngine.SkinnedMeshRenderer", "SetBlendShapeWeight", 2),
    "material_float_get": ("UnityEngine.Material", "GetFloat", 1, ("System.String",)),
    "material_float_set": ("UnityEngine.Material", "SetFloat", 2, ("System.String", "System.Single")),
    "material_offset_get": ("UnityEngine.Material", "get_mainTextureOffset", 0),
    "material_offset_set": ("UnityEngine.Material", "set_mainTextureOffset", 1),
    "random_get": ("UnityEngine.Random", "get_state_Injected", 1),
    "random_set": ("UnityEngine.Random", "set_state_Injected", 1),
    "talk_process": ("VL.Unsafe.Jobs.VLActorTalkJob", "ProcessAnimation", 1),
    "playable_type": ("UnityEngine.Playables.PlayableHandle", "GetPlayableType_Injected", 1),
    "graph_playing": ("UnityEngine.Playables.PlayableGraph", "IsPlaying_Injected", 1),
    "playable_weight_get": ("UnityEngine.Playables.PlayableHandle", "GetInputWeightFromIndex_Injected", 2),
    "playable_weight_set": ("UnityEngine.Playables.PlayableHandle", "SetInputWeightFromIndex_Injected", 3),
    "playable_graph_get": ("UnityEngine.Playables.PlayableHandle", "GetGraph_Injected", 2),
    "clip_events_get": ("UnityEngine.AnimationClip", "get_events", 0),
    "script_instance": ("UnityEngine.Playables.PlayableHandle", "GetScriptInstance_Injected", 1),
    "animator_avatar": ("UnityEngine.Animator", "get_avatar", 0),
    "graph_play": ("UnityEngine.Playables.PlayableGraph", "Play_Injected", 1),
    "graph_stop": ("UnityEngine.Playables.PlayableGraph", "Stop_Injected", 1),
    "animator_active": ("UnityEngine.Behaviour", "get_isActiveAndEnabled", 0),
    "facial_ctor": ("VL.VLActorFacialSystem", ".ctor", 0),
    "talk_ctor": ("VL.VLActorTalk", ".ctor", 0),
    "material_ctor_shader": ("UnityEngine.Material", ".ctor", 1, ("UnityEngine.Shader",)),
    "material_copy": ("UnityEngine.Material", "CopyPropertiesFromMaterial", 1),
    "material_shader": ("UnityEngine.Material", "get_shader", 0),
    "material_keywords_get": ("UnityEngine.Material", "get_shaderKeywords", 0),
    "material_keywords_set": ("UnityEngine.Material", "set_shaderKeywords", 1),
    "block_ctor": ("UnityEngine.MaterialPropertyBlock", ".ctor", 0),
    "block_empty": ("UnityEngine.MaterialPropertyBlock", "get_isEmpty", 0),
    "block_dispose": ("UnityEngine.MaterialPropertyBlock", "Dispose", 0),
    "renderer_block_get": ("UnityEngine.Renderer", "GetPropertyBlock", 2),
    "renderer_block_set": ("UnityEngine.Renderer", "SetPropertyBlock", 2),
    "foot_apply": ("VL.VLActorFootShadow", "ApplyJob", 0),
    "renderer_bounds_get": ("UnityEngine.Renderer", "get_localBounds_Injected", 1),
    "renderer_bounds_set": ("UnityEngine.Renderer", "set_localBounds_Injected", 1),
    "mesh_bounds_get": ("UnityEngine.Mesh", "get_bounds_Injected", 1),
    "mesh_bounds_set": ("UnityEngine.Mesh", "set_bounds_Injected", 1),
    "mesh_vertices_get": ("UnityEngine.Mesh", "get_vertices", 0),
    "mesh_vertices_set": ("UnityEngine.Mesh", "set_vertices", 1),
}
# No object header, native handle, NativeList, PlayableHandle or reference is
# ever included in a writable scalar span. References/configurations are only
# checked for identity; they are never copied over a new graph or pooled value.
PRESENTATION_SCALARS = {
    "VL.Core.VLActorController": ("_bounds",),
    "VL.VLActorFacialSystem": ("blinkTimeScale", "useBlink", "autoBlinkDisabled", "_blinkState", "_currentBlink", "_currentBlinkTime", "_nextBlinkTime", "_blinkWeight", "_isUpdateBlink"),
    "VL.VLActorTalk": ("talkTransitionTime", "isTalk", "skipPlayStateCheck", "talkSpeed", "_defaultSourcePosition", "additiveScale", "autoAdditiveDisabled", "<talkWeight>k__BackingField", "<deltaTalkWeight>k__BackingField", "<additiveWeight>k__BackingField", "_additiveIndex", "_additiveTime", "_isUpdateAdditive", "_currentAdditiveTime", "_currentAdditiveWeight"),
    "VL.VLActorTalkFFT": ("talkThreshold", "_fftWindow", "<isTalk>k__BackingField", "<talkPower>k__BackingField"),
    "VL.VLActorEye": ("highLightLevel", "highLightOffset", "uru", "uruChangeTime"),
    "VL.VLActorFaceTargetCorrection": ("_euler",),
    "VL.VLActorFootShadow": ("rotation", "length", "size", "maxHeight", "maxLength", "_dir", "_jobScheduled"),
    "VL.Core.MaterialInfo": ("_materialIndex", "_isModifiable", "_initialized"),
    "VL.Core.VLActorModelParts": ("_rendererActive", "defaultBounds"),
    "VL.VLActorRig": (),
    "VL.VLActorExpression": (),
    "Solis.Common.SolisLookAtLimit": (),
    "Solis.Common.QuartzDriverRig": ("_isDisposed",),
    "VL.VLActorFullBodyIK": ("lookAtClampWeight", "stiffness", "maxPullIteration", "handDown", "_customLookAtEffectorInitialized", "fullBodyIkHeadOriginalPosition", "fullBodyIkHeadOriginalRotation"),
    "VL.VLActorBodyAdditiveAnimation": ("transitionTime", "_isAdditiveEnable"),
}
PRESENTATION_IDENTITIES = {
    "VL.Core.VLActorController": ("_animationPlayer", "_animator", "_avatar", "_extensions", "_children", "_childMap", "_partsIdMap", "_boneNameToTransformMap", "_buildResources"),
    "VL.VLActorFacialSystem": ("_blinkData", "_blinkDataRuntime", "_blinkLimitDataRuntime", "_facialLimitData", "_facialLimitDataRuntime", "_animationClipPlayer"),
    "VL.VLActorTalk": ("_data", "_renderers", "_animationClipPlayer", "_sourceTarget", "_playingClip", "_fft", "_additiveTransforms", "_talkBlendShapeData", "_talkData", "_talkCurveData", "_keyframeData", "_talkTargetData", "_blendShapeNameToIndex", "_scriptPlayable"),
    "VL.VLActorTalkFFT": ("_fftInputRe", "_fftInputIm", "_fftOutputRe", "_fftOutputIm", "_bitScrollArray", "_windowArray", "<audioSource>k__BackingField", "_spectrum", "_voiceSpectrum"),
    "VL.VLActorEye": ("_material",),
    "VL.VLActorFaceTargetCorrection": ("target", "angleCurve", "targets"),
    "VL.VLActorFootShadow": ("_shadowObject", "_renderer", "_meshFilter", "_mesh", "_shadows", "_verts", "_nativeVerts", "_bounds", "_uvs", "_tris", "_jobApplyAction", "_lightTransform"),
    "VL.Core.MaterialInfo": ("_instancedMaterial", "_originalMaterial", "_renderer", "<materialProperty>k__BackingField"),
    "VL.Core.VLActorModelParts": ("_assetName", "_partsId", "_boneMap", "_instanceIDToDefaultBoneInfoIndexMap", "_boneInfos", "_rootBoneLinkList", "renderers", "rendererGameObjects", "skinRenderers", "materials", "aabbTransform", "_tempMaterials", "_tempSharedMaterials", "_tempRootTransBoneList", "defaultRootTransform"),
    "VL.VLActorRig": ("_rigFurisodeBones", "_scriptPlayable", "_animationClipPlayer", "_rigFurisodes", "_output"),
    "VL.VLActorExpression": ("_expressionBones", "_scriptPlayable", "_animationClipPlayer", "_expressions", "_muscleExpressions", "_expressionSymbolsInfo", "_expressionSymbols", "_output"),
    "Solis.Common.SolisLookAtLimit": ("_animationClipPlayer", "_output", "_scriptPlayable"),
    "Solis.Common.QuartzDriverRig": ("quartzDriverRotationBones", "quartzDriverFrillBones", "quartzDriverSkirtBones", "quartzDriverHairBones", "quartzDriverHumanoidHandBones", "quartzDriverHumanoidSleeveBones", "quartzDriverHumanoidUpLegBones", "quartzDriverHumanoidArmBones", "quartzDriverWaistBones", "quartzDriverFurisodeBones", "quartzDriverPonchoBones", "_animationClipPlayer", "_output", "_scriptPlayable"),
    "VL.VLActorFullBodyIK": ("_bodyEffector", "_leftFootEffector", "_rightFootEffector", "_leftHandEffector", "_rightHandEffector", "_leftKneeHintEffector", "_rightKneeHintEffector", "_leftElbowHintEffector", "_rightElbowHintEffector", "_lookAtEffector", "_customLookAtEffector", "_effectors", "_animationClipPlayer", "_animator", "_moveReference", "_moveTarget", "_skeletonRoot", "_head", "m_IKPlayable"),
    "VL.VLActorBodyAdditiveAnimation": ("_motions", "_animationClipPlayer", "_animationControllers", "_selector"),
}
PRESENTATION_EXPORTS = {"field_offset": ("il2cpp_field_get_offset", "size_t(const FieldInfo*)")}
PRESENTATION_VALUE_BYTES = {"System.Boolean": 1, "System.Int32": 4, "System.Single": 4,
    "UnityEngine.Vector3": 12, "UnityEngine.Bounds": 24, ".BlinkState": 4, "UnityEngine.FFTWindow": 4}

def presentation_schema(original):
    result=[]
    for owner,names in PRESENTATION_SCALARS.items():
        fields=original.fields(owner); rows=[]
        for name in names:
            row=fields[name]; size=PRESENTATION_VALUE_BYTES[row["type"]]
            need(row["offset"] >= 16, "actor_presentation_scalar_header:"+owner+"."+name)
            rows.append({"name":name,"offset":row["offset"],"bytes":size,"kind":"scalar","type":row["type"]})
        for name in PRESENTATION_IDENTITIES[owner]:
            row=fields[name]; t=row["type"]
            size=16 if t.startswith("Unity.Collections.Native") or (not t.endswith("[]") and t.startswith(("UnityEngine.Animations.","UnityEngine.Playables.")) and "Playable" in t) else 8
            rows.append({"name":name,"offset":row["offset"],"bytes":size,"kind":"identity","type":t})
        if owner == "VL.Core.VLActorController":
            # Embedded AABBJobData is an unboxed value: metadata field offsets
            # include the sixteen-byte box header and must be normalized.
            outer=fields["_aabbJobData"]["offset"]
            for name in ("_aabbData","_aabbTransformAccessArray","_aabbTransforms"):
                field=original.fields("VL.AABB.AABBJobData")[name]
                rows.append({"name":name,"offset":outer+field["offset"]-16,"bytes":8 if name=="_aabbTransformAccessArray" else 16,"kind":"identity","type":field["type"]})
        result.append({"type":owner,"fields":rows,"class":runtime_type(original,owner,18)})
    return result

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
    "chain": ("ActorSwing.ActorSwingJobChainBone", 0x7c),
    "talk_job": ("VL.Unsafe.Jobs.VLActorTalkJob", 96),
    "talk_blend_row": ("VL.Unsafe.Jobs.TalkBlendShapeJobData", 24),
    "talk_row": ("VL.Unsafe.Jobs.TalkJobData", 20),
    "shadow_data": ("VL.Unsafe.Jobs.ShadowData", 20),
    "aabb_data": ("VL.AABB.AABBData", 212),
    "aabb_job": ("VL.AABB.AABBJobData", 56),
    "bounds": ("UnityEngine.Bounds", 24), "vector2": ("UnityEngine.Vector2", 8)}


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


def native_output_weight(native,image,platform):
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    dis=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);offset=image.file_offset if platform=="android"else image.offset
    addresses=(0x49a610,0x7356a4,0x7342c4,0x7329e0)if platform=="android"else(0xb375d0,0xdcb79c,0xdca15c,0xdc89dc)
    result={}
    for name,address,size in zip(("icall","dispatch","validate","setter"),addresses,(0xb0,0x48,0x34,8)):
        raw=native[offset(address):offset(address)+size];code=list(dis.disasm(raw,address));result[name]={"rva":hex(address),"prefix":native[offset(address):offset(address)+16].hex(),"instructions":[{"rva":hex(i.address),"bytes":i.bytes.hex(),"instruction":i.mnemonic+" "+i.op_str}for i in code]}
    need([i["instruction"]for i in result["setter"]["instructions"]]==["str s0, [x0, #0x40]","ret "],"actor_output_weight_setter_differs")
    need(any(i["instruction"]=="ldr x0, [x8, #0x28]"for i in result["dispatch"]["instructions"]),"actor_output_weight_slot_differs")
    return {"engine_sha256":hashlib.sha256(native).hexdigest(),"slot_output":40,"weight":64,"methods":result,
        "runtime_contract":"exact_original_versioned_output_GetTarget_matches_owned_Animator_and_graph_then_bounded_finite_float_read; no_invented_managed_getter"}


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


COMMON_JOB_ROOTS=[
    ("VL.Unsafe.Jobs.VLActorRigFurisodeJob","VL.VLActorRig","_scriptPlayable",None,{"rigs":"_rigFurisodes"}),
    ("VL.Unsafe.Jobs.VLActorExpressionJob","VL.VLActorExpression","_scriptPlayable",None,{"expressions":"_expressions","muscleExpressions":"_muscleExpressions","expressionSymbolsInfo":"_expressionSymbolsInfo","expressionSymbols":"_expressionSymbols"}),
    ("Solis.Common.SolisLookAtLimitJob","Solis.Common.SolisLookAtLimit","_scriptPlayable","<_solisLookAtLimitJob>k__BackingField",{}),
    ("Solis.Common.ActorAnimationQuartzDriverJob","Solis.Common.QuartzDriverRig","_scriptPlayable","<_actorAnimationQuartzDriverJob>k__BackingField",{}),
    ("VL.IK.FullBodyIKJob","VL.VLActorFullBodyIK","m_IKPlayable",None,{})]
COMMON_CACHE={"UnityEngine.Animations.TransformStreamHandle":((0,4),(8,4)),"UnityEngine.Animations.PropertyStreamHandle":((0,4),(8,4)),"UnityEngine.Animations.TransformSceneHandle":((0,4),),"UnityEngine.Animations.PropertySceneHandle":((0,4),)}
COMMON_PRIMITIVES={"System.Boolean","System.Byte","System.SByte","System.Int16","System.UInt16","System.Int32","System.UInt32","System.Int64","System.UInt64","System.Single","System.Double","System.Char"}
def common_jobs(original):
    o=original
    def instance_fields(t):
        result={}
        for name,row in o.fields(t).items():
            _,kind,_=struct.unpack_from("<3I",o.m,o.h[24]+row["metadata_field_index"]*12)
            ptr=o.qword(o.type_table+kind*8);bits=struct.unpack_from("<I",o.b,o.offset(ptr)+8)[0]
            if not bits&16:result[name]=row
        return result
    def masks(t,base=0,depth=0):
        need(depth<16,"actor_common_job_value_depth")
        if t in COMMON_CACHE:return [{"offset":base+a,"bytes":b}for a,b in COMMON_CACHE[t]]
        if t in COMMON_PRIMITIVES or t.startswith("Unity.Collections.Native"):return []
        fields=instance_fields(t)
        if "value__"in fields:return []
        return [item for row in fields.values()if row["offset"]>=16 for item in masks(row["type"],base+row["offset"]-16,depth+1)]
    result=[]
    for job_type,component_type,playable,mirror,mirrors in COMMON_JOB_ROOTS:
        layout=o.struct_layout(job_type);fields=o.fields(job_type);component=o.fields(component_type);containers=[]
        for name,row in fields.items():
            if not row["type"].startswith("Unity.Collections.Native"):continue
            element=row["type"].split("<",1)[1][:-1];element_layout=o.struct_layout(element)
            component_field=mirrors.get(name);component_offset=component[component_field]["offset"]if component_field else component[mirror]["offset"]+row["offset"]-16
            containers.append({"field":name,"offset":row["offset"]-16,"component_offset":component_offset,
                "list":row["type"].startswith("Unity.Collections.NativeList"),"stride":element_layout["bytes"],"element_type":element,"caches":masks(element)})
        scratch=[];history=[];cpu=[]
        if job_type=="VL.IK.FullBodyIKJob":
            scratch=[{"offset":fields[name]["offset"]-16,"bytes":12}for name in("bodyPosition","_moveDelta")]
            limb=o.fields(".IKLimbHandle")["maximumExtension"]["offset"]-16
            history=[{"offset":fields[name]["offset"]-16+limb,"bytes":4}for name in("leftArm","rightArm","leftLeg","rightLeg")]
            cpu=[{"name":name,**component[name],"bytes":12}for name in("fullBodyIkHeadOriginalPosition","fullBodyIkHeadOriginalRotation")]
        result.append({"type":job_type,"component_type":component_type,"bytes":layout["bytes"],"playable_offset":component[playable]["offset"],
            "job_type":runtime_type(o,job_type,17),"component_class":runtime_type(o,component_type,18),"containers":containers,
            "caches":masks(job_type),"scratch":scratch,"history":history,"init_zero_history":history,"cpu_fields":cpu,
            "policy":"same_graph_job_container_lifetime; immutable_configuration_except_proven_handle_caches_and_fullbody_float_history; never_copy_headers_or_handles"})
    return result


def derived_callbacks(original,platform):
    """Resolve real reference/shared generic slots; open declarations have none."""
    owner="VL.VLDefaultActorController`3";row=original.types[original.type_id(owner)][1];mids={}
    for mid in range(row[9],row[9]+row[16]):
        method=struct.unpack_from("<7I4H",original.m,original.h[12]+mid*36)
        if original.string(method[0])=="LateUpdate":mids[mid]=method
    need(len(mids)==1,"actor_derived_late_declaration_differs")
    metadata=0x96dd758 if platform=="android" else 0x9c1deb8
    reg=[original.qword(metadata+k*8)for k in range(16)]
    if platform=="android":count,table=251131,0x94f2f80
    else:
        pair=0x982aed0;count,table=struct.unpack_from("<2Q",original.b,original.offset(pair)-104)
        need(count==251314,"actor_generic_pointer_count_differs")
    specs={i:v for i in range(reg[8])if(v:=struct.unpack_from("<3i",original.b,original.offset(reg[9])+i*12))[0]in mids}
    found={}
    for index in range(reg[4]):
        record=struct.unpack_from("<4i",original.b,original.offset(reg[5])+index*16)
        if record[0]not in specs:continue
        spec=specs[record[0]];need(0<=record[1]<count,"actor_generic_pointer_index_invalid")
        address=original.qword(table+record[1]*8);instance=original.qword(reg[3]+spec[1]*8)
        argc=struct.unpack_from("<I",original.b,original.offset(instance))[0];argv=original.qword(instance+8)
        args=[original.decode(original.qword(argv+k*8))for k in range(argc)]
        alias="derived_late_ref" if args==["System.Object"]*3 else "derived_late_shared" if args==["System.Object","System.Object","Unity.IL2CPP.Metadata.__Il2CppFullySharedGenericType"] else None
        need(alias and alias not in found,"actor_derived_generic_family_differs")
        found[alias]={"type":owner,"name":"LateUpdate","parameter_count":0,"static":False,"parameters":[],"return":"System.Void",
            "rva":hex(address),"prefix":original.b[original.offset(address):original.offset(address)+16].hex(),
            "metadata_method_index":spec[0],"metadata_registration":hex(metadata),"method_spec_index":record[0],"generic_arguments":args,
            "method_pointer_index":record[1],"pointer_table":hex(table),"pointer_slot":hex(table+record[1]*8),
            "native_abi":"void(void* selfX0,const MethodInfo* closedGenericX1)","contract":"gate_entire_derived_root_and_nested_base_once"}
    need(set(found)=={"derived_late_ref","derived_late_shared"},"actor_derived_generic_routes_missing")
    expected=(0x73cf2d0,0x73d244c)if platform=="android"else(0x5448b60,0x544bf40)
    need([int(found[k]["rva"],0)for k in("derived_late_ref","derived_late_shared")]==list(expected),"actor_derived_generic_addresses_differ")
    return found


def presentation_callbacks(original, platform):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    dis=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    result={}
    sizes={"android":(332,260,580,1352),"ios":(376,320,724,1444)}[platform]
    for (alias,arguments),size in zip(list(PRESENTATION_SELECT.items())[:4],sizes):
        method=original.method(*arguments);address=int(method["rva"],0)
        code=original.b[original.offset(address):original.offset(address)+size]
        instructions=list(dis.disasm(code,address))
        if alias in ("actor_update","actor_late"):
            dispatch="ldp x9, x1, [x8, #"+("0x1b8" if alias=="actor_update" else "0x1c8")+"]"
            need(any(i.mnemonic+" "+i.op_str==dispatch for i in instructions),"actor_mono_extension_dispatch_differs:"+alias)
            need(any(i.mnemonic=="blr" and i.op_str=="x9" for i in instructions),"actor_mono_extension_call_differs:"+alias)
        result[alias]={"rva":hex(address),"bytes":size,"sha256":hashlib.sha256(code).hexdigest(),
            "instructions":[{"rva":hex(i.address),"bytes":i.bytes.hex(),"instruction":i.mnemonic+" "+i.op_str}for i in instructions],
            "contract":"owned_receiver_only; held_suppresses; accepted_native_tick_once; ambient_RNG_restored_at_each_callback_return"}
    return result


# Source-exact native scalar/cache-normalization component, kept in the existing
# Actor input budget. Revalidated against both original engine images below.
TEMPORAL_COMPONENT = r'''
// Source-pinned native temporal component. Whole-source admission also requires
// managed mixer, topology, physical job, presentation and World ownership.
namespace idoly_mp4_native_temporal {
struct Handle {uintptr_t slot=0;uint32_t version=0,padding=0;};
static_assert(sizeof(Handle)==16,"original_versioned_playable_handle");
inline bool same(Handle a,Handle b){return a.slot==b.slot&&a.version==b.version;}
enum class Kind:uint8_t {script,mixer,layer_mixer,clip,animation_script};
enum class Lifetime:uint8_t {persistent_exact,rebuilt_logical,rebuilt_timeline=rebuilt_logical};
enum class Result:uint8_t {empty,captured,scalar_component_restored,source_restored,invalid_api,
    capacity,fence_unavailable,source_changed,inventory_changed,identity_changed,layout_unverified,
    graph_changed,logical_remap_unverified,memory_unavailable,incomplete_native_sampling_state,
    clip_binding_changed,clip_events_present,clip_not_quiescent,normalizer_failed};
// Source producer identity. All members participate; zero is not a valid token.
// 'producer' is the source owned managed Timeline/ParamMixer producer identity held by the
// caller's GC root, not an old native node pointer. asset identifies the actual
// AnimationClip for clip roles and MotionDefine/track asset for mixer roles.
struct Logical {uintptr_t producer=0,asset=0;uint64_t generation=0;uint32_t clip_index=0,layer=0,role=0;};
inline bool same(const Logical&a,const Logical&b){return a.producer==b.producer&&a.asset==b.asset
    &&a.generation==b.generation&&a.clip_index==b.clip_index&&a.layer==b.layer&&a.role==b.role;}
inline bool valid(const Logical&a){return a.producer&&a.asset&&a.generation&&a.role;}
struct Input {Handle handle{};Logical logical{};Kind kind=Kind::script;Lifetime lifetime=Lifetime::persistent_exact;};
struct Span {uint16_t offset=0;uint8_t size=0;uint64_t mask=0;};
// This table must come from the exact original native constructor/vtable/update
// proof. Android RTTI is stripped: require the actual original null RTTI cell
// plus exact source factory/type and full original vtable prefix in profile_ok.
// This source profile closes only the native temporal/cache component; managed
// factory/history and outer graph/scene ownership are independent requirements.
struct Layout {
    Kind kind=Kind::script;uintptr_t vtable=0,rtti=0;const char* rtti_name=nullptr;
    uint16_t minimum_extent=0;const Span*spans=nullptr;uint8_t span_count=0;
    uint64_t proof_id=0;bool native_history_complete=false;
    // Exact original Clip vtable+D0 cleanup and+C8 prepare, source-pinned by
    // profile_ok (including full original entry prefixes and constructor ABI).
    uintptr_t clip_cleanup=0,clip_prepare=0;uint64_t normalization_proof=0;
};
struct ClipBinding {
    uintptr_t native_animator=0,native_asset=0,binding_context=0;
    // Fingerprint of the actual owned avatar/skeleton/renderers/output binding,
    // rechecked by the host; not a fabricated mutable generation counter.
    uint64_t binding_fingerprint=0;int32_t event_count=-1;
};
inline bool same(const ClipBinding&a,const ClipBinding&b){return a.native_animator==b.native_animator
    &&a.native_asset==b.native_asset&&a.binding_context==b.binding_context
    &&a.binding_fingerprint==b.binding_fingerprint&&a.event_count==b.event_count;}
struct Lease {uint64_t epoch=0,ticket=0;};
struct Api {
    void*context=nullptr;
    bool(*begin_fence)(void*,uint64_t,Lease&)=nullptr;
    // Must verify the same main Unity thread, source epoch, blocked Native
    // animation/Fixed grants, completed Animator/Director/jobs/AABB/Actor jobs,
    // and a lease held continuously until end_fence. No frame may run in here.
    bool(*fence_held)(void*,const Lease&)=nullptr;
    void(*end_fence)(void*,const Lease&)=nullptr;
    bool(*source_current)(void*,uint64_t)=nullptr;
    bool(*inventory_exact)(void*,Handle,const Input*,size_t)=nullptr;
    bool(*mapped)(void*,uintptr_t,size_t,bool)=nullptr;
    bool(*profile_ok)(void*,const Layout&)=nullptr;
    // These bind original retained IsValid / GetGraph_Injected and original
    // GetPlayableType/factory-owned script type admission. No guessed graph or
    // native-node type fields are used here.
    bool(*handle_valid)(void*,const Handle&)=nullptr;
    bool(*get_graph)(void*,const Handle&,Handle&)=nullptr;
    bool(*graph_valid)(void*,const Handle&)=nullptr;
    bool(*typed_kind)(void*,const Input&)=nullptr;
    // Called ONLY for a record explicitly classified as rebuilt_logical.
    // Supported producer must be exact owned Timeline or ParamMixer factory;
    // native Clip roles include layer/current/previous index, not fuzzy lookup.
    // Must prove source producer+asset+index+layer+role and generation, then
    // return the new handle. A successful lookup alone is not sufficient.
    bool(*remap)(void*,uint64_t,const Input&,Input&)=nullptr;
    // Uses source producer/AnimationClip identity, actual original get_events /
    // Array.get_Length, original output->Animator ownership and current Actor
    // avatar/skeleton/renderer binding. Must root managed query results while
    // inspecting. Returning mapped addresses alone is not this proof.
    bool(*clip_binding)(void*,const Input&,uintptr_t,ClipBinding&)=nullptr;
    // Exact original DirectorManager graph/topology operation queues must be
    // drained/closed. Never roll graphAC back above unresolved queued work.
    bool(*manager_quiescent)(void*,const Lease&)=nullptr;
};
// Proven scalar field component. These are NOT the whole native object. The
// derived clip sampling buffers rooted110/120/128/130/150/158 are not copied.
// RootMath138 is also derived: its entire 0xF2 defined payload is overwritten
// before use by original full sampling. No buffer/old pointer is copied.
// Ready104/dirty102/phase174 are never rolled back.
inline constexpr Span base_spans[]={
    {0x38,4,0xffffffffu}, // seek/done/propagation/callback flags
    {0x3c,4,0xffffffffu},{0x40,4,0xffffffffu}, // native scalar config3c and time-wrap40; traversal is flags38 bit11
    {0x50,8,(~uint64_t(0))}, // last native graph frame counter observed by this node
    {0x58,8,(~uint64_t(0))}, // delayed-play remaining time
    {0x60,8,(~uint64_t(0))},{0x68,8,(~uint64_t(0))}, // current/previous time
    {0x70,8,(~uint64_t(0))},{0x78,8,(~uint64_t(0))}, // duration/speed
    {0x80,4,0xffffffffu}, // lead/delayed-state threshold input read by original dispatcher
    {0x84,4,0xffffffffu},{0x88,2,0xffffu},{0xaa,1,0xffu} // state, transition caches, seek auxiliary
};
// Source-pinned retained setters write these authored boolean bytes only.
// They must match before rebuilding logical clips; prepare derives the OTHER
// feature bytes1F2/3/4 and loop19D. Never overwrite those derived flags.
inline constexpr uint16_t clip_authored_offsets[]={0x1f0,0x1f5,0x1f1,0x1f6,0x1f7};
inline constexpr Span graph_spans[]={
    {0x20,8,(~uint64_t(0))}, // frame counter, not slot version
    {0x28,8,(~uint64_t(0))}, // previous sample clock (double), not a JobHandle
    {0x38,8,(~uint64_t(0))}, // last delta (double)
    {0x40,4,0xffffffffu}, // last timescale (float)
    {0xac,2,0xffffu} // actual deferred/update status bits
};
inline constexpr Span clip_spans[]={
    {0x38,4,0xffffffffu},{0x3c,4,0xffffffffu},{0x40,4,0xffffffffu},
    {0x50,8,(~uint64_t(0))},{0x58,8,(~uint64_t(0))},
    {0x60,8,(~uint64_t(0))},{0x68,8,(~uint64_t(0))},{0x70,8,(~uint64_t(0))},{0x78,8,(~uint64_t(0))},
    {0x80,4,0xffffffffu},{0x84,4,0xffffffffu},{0x88,2,0xffffu},{0xaa,1,0xffu},
    {0x170,4,0xffffffffu},{0x178,8,(~uint64_t(0))},
    {0x180,4,0xffffffffu},{0x1f8,1,0xffu}
};
// Source-proven graph scalar history is captured alongside matching node50.
// Native manager/global scheduling context still requires separate closure.
// The whole-graph native_history_complete gate below remains false until both
// graph and subclass sampling histories are closed, not merely the node times.
template<size_t Capacity> class SourceTemporalSnapshot {
    static constexpr size_t MaxSpans=24;
    struct Record {Input input{};Handle graph{};uintptr_t native=0;const Layout*layout=nullptr;
        uint64_t values[MaxSpans]{};ClipBinding clip{};uint8_t authored[5]{};};
    Api api_{};const Layout*layouts_=nullptr;size_t layout_count_=0,count_=0;
    uint64_t epoch_=0,graph_values_[5]{};Handle graph_{};uintptr_t graph_native_=0;
    Record records_[Capacity]{};bool captured_=false,mutation_started_=false;
    Result result_=Result::empty;
    struct Guard {const Api&a;Lease lease{};bool acquired=false;
        Guard(const Api&api,uint64_t e):a(api){acquired=a.begin_fence(a.context,e,lease);
            acquired=acquired&&lease.epoch==e&&lease.ticket&&a.fence_held(a.context,lease);}
        ~Guard(){if(lease.ticket)a.end_fence(a.context,lease);}
        bool held()const{return acquired&&a.fence_held(a.context,lease);}
    };
    bool fail(Result r){result_=r;return false;}
    bool read(uintptr_t at,void*out,size_t n)const{
        if(!at||!n||at>(~uintptr_t(0))-n||!api_.mapped(api_.context,at,n,false))return false;
        ::memcpy(out,reinterpret_cast<const void*>(at),n);return true;
    }
    bool layout_valid(const Layout&l)const{
        if(!l.vtable||!l.proof_id||!l.spans||!l.span_count||l.span_count>MaxSpans
            ||!api_.profile_ok(api_.context,l))return false;
        for(unsigned i=0;i<l.span_count;++i){const auto&s=l.spans[i];
            if(!s.size||s.size>8||!s.mask||s.offset<0x38||s.offset+s.size>l.minimum_extent)return false;
            if(s.size<8&&(s.mask>>(s.size*8)))return false;
            for(unsigned j=0;j<i;++j){const auto&p=l.spans[j];
                if(s.offset<p.offset+p.size&&p.offset<s.offset+s.size)return false;}
        }
        return true;
    }
    const Layout*layout(Kind kind,uintptr_t table)const{
        const Layout*found=nullptr;
        for(size_t i=0;i<layout_count_;++i)if(layouts_[i].kind==kind&&layouts_[i].vtable==table){
            if(found||!layout_valid(layouts_[i]))return nullptr;
            found=&layouts_[i];}
        return found;
    }
    bool graph_node(Handle h,uintptr_t&native){
        uint32_t version=0;
        if(!h.slot||(h.slot&7)||h.slot>(~uintptr_t(0))-0x30
            ||!read(h.slot+0x20,&version,4)||version!=(h.version&~1u)
            ||!read(h.slot+0x28,&native,sizeof native)||!native
            ||!api_.graph_valid(api_.context,h))return fail(Result::graph_changed);
        uint8_t inside=1;
        if(!read(native+0xc8,&inside,1)||inside)return fail(Result::fence_unavailable);
        return true;
    }
    bool node(const Input&input,Handle expected_graph,uintptr_t expected_native_graph,uintptr_t&native,const Layout*&l){
        if(!input.handle.slot||(input.handle.slot&7)||input.handle.slot>(~uintptr_t(0))-0x30)
            return fail(Result::identity_changed);
        uint32_t version=0;uintptr_t table=0,rtti=0;
        // Map and inspect the slot BEFORE invoking original native validity
        // or managed type queries. Never pass an unmapped stale slot to Unity.
        if(!read(input.handle.slot+0x20,&version,4)||version!=(input.handle.version&~1u)
            ||!read(input.handle.slot+0x28,&native,sizeof native)||!native
            ||!read(native,&table,sizeof table)||!api_.handle_valid(api_.context,input.handle)
            ||!api_.typed_kind(api_.context,input))return fail(Result::identity_changed);
        l=layout(input.kind,table);
        if(!l||table<8||!read(table-8,&rtti,sizeof rtti)||rtti!=l->rtti)return fail(Result::layout_unverified);
        if(l->rtti_name){uintptr_t name=0;if(!rtti||!read(rtti+8,&name,sizeof name))return fail(Result::layout_unverified);
            for(size_t i=0;i<96;++i){char got=0;if(!read(name+i,&got,1)||got!=l->rtti_name[i])return fail(Result::layout_unverified);
                if(!got)break;
                if(i==95)return fail(Result::layout_unverified);}}
        Handle actual_graph{};
        uintptr_t actual_native_graph=0,owner_native_graph=0;
        if(!api_.get_graph(api_.context,input.handle,actual_graph)||!same(actual_graph,expected_graph)
            ||!graph_node(actual_graph,actual_native_graph)||actual_native_graph!=expected_native_graph
            ||!read(native+0x20,&owner_native_graph,sizeof owner_native_graph)
            ||owner_native_graph!=expected_native_graph)return fail(Result::graph_changed);
        if(!api_.mapped(api_.context,native,l->minimum_extent,false))return fail(Result::memory_unavailable);
        return true;
    }
    bool clip_binding(const Input&input,uintptr_t native,const Layout&l,ClipBinding&binding){
        if(!api_.clip_binding||!l.normalization_proof||!l.clip_cleanup||!l.clip_prepare
            ||!api_.clip_binding(api_.context,input,native,binding))
            return fail(Result::incomplete_native_sampling_state);
        if(binding.event_count!=0)return fail(Result::clip_events_present);
        uintptr_t asset=0,cleanup=0,prepare=0;
        if(!binding.native_animator||!binding.native_asset||!binding.binding_fingerprint
            ||binding.native_animator>(~uintptr_t(0))-0xb0
            ||binding.binding_context!=binding.native_animator+0xb0
            ||!read(native+0x1d0,&asset,sizeof asset)||asset!=binding.native_asset
            ||!read(l.vtable+0xd0,&cleanup,sizeof cleanup)||cleanup!=l.clip_cleanup
            ||!read(l.vtable+0xc8,&prepare,sizeof prepare)||prepare!=l.clip_prepare)
            return fail(Result::clip_binding_changed);
        // Source174 may be one after an ordinary full sample; it is derived
        // cache validity, not an admission failure. Never restore its old bit.
        return true;
    }
    bool ready()const{return api_.begin_fence&&api_.fence_held&&api_.end_fence&&api_.source_current
        &&api_.inventory_exact&&api_.mapped&&api_.profile_ok&&api_.handle_valid&&api_.get_graph&&api_.graph_valid&&api_.typed_kind
        &&api_.manager_quiescent
        &&layouts_&&layout_count_;}
public:
    SourceTemporalSnapshot(Api a,const Layout*l,size_t n):api_(a),layouts_(l),layout_count_(n){}
    Result result()const{return result_;}size_t size()const{return count_;}
    bool mutation_started()const{return mutation_started_;}
    bool component_closed()const{
        if(!captured_||!count_)return false;
        for(size_t i=0;i<count_;++i){const auto&r=records_[i];
            if(!r.layout->native_history_complete)return false;
            if(r.input.kind==Kind::clip&&(!r.layout->normalization_proof
                ||!r.layout->clip_cleanup||!r.layout->clip_prepare||r.clip.event_count))return false;
        }
        return true;
    }
    bool source_restorable()const{
        // This helper is one component. Native manager/global active graphs,
        // managed mixer histories, actor jobs and scene state remain owned by
        // the outer aggregate; it must not infer whole-source restorable here.
        return false;
    }
    bool capture(uint64_t epoch,Handle graph,const Input*inputs,size_t count){
        captured_=false;mutation_started_=false;count_=0;
        if(!ready()||!epoch||!graph.slot||!inputs)return fail(Result::invalid_api);
        if(!count||count>Capacity)return fail(Result::capacity);
        Guard fence(api_,epoch);
        if(!fence.held()||!api_.manager_quiescent(api_.context,fence.lease))return fail(Result::fence_unavailable);
        if(!api_.source_current(api_.context,epoch))return fail(Result::source_changed);
        if(!api_.inventory_exact(api_.context,graph,inputs,count))return fail(Result::inventory_changed);
        uintptr_t graph_native=0;uint64_t graph_values[5]{};
        if(!graph_node(graph,graph_native))return false;
        for(unsigned i=0;i<5;++i)if(!read(graph_native+graph_spans[i].offset,&graph_values[i],graph_spans[i].size))
            return fail(Result::memory_unavailable);
        for(size_t i=0;i<count;++i){Record r{};r.input=inputs[i];r.graph=graph;
            if(r.input.lifetime==Lifetime::rebuilt_timeline&&!valid(r.input.logical))return fail(Result::logical_remap_unverified);
            for(size_t j=0;j<i;++j)if(same(inputs[j].handle,r.input.handle))return fail(Result::inventory_changed);
            if(!node(r.input,graph,graph_native,r.native,r.layout))return false;
            for(unsigned k=0;k<r.layout->span_count;++k){const auto&s=r.layout->spans[k];
                if(!read(r.native+s.offset,&r.values[k],s.size))return fail(Result::memory_unavailable);}
            if(r.input.kind==Kind::clip){
                if(!clip_binding(r.input,r.native,*r.layout,r.clip))return false;
                for(unsigned k=0;k<5;++k)if(!read(r.native+clip_authored_offsets[k],&r.authored[k],1)
                    ||r.authored[k]>1)return fail(Result::clip_binding_changed);
            }
            records_[i]=r;
        }
        if(!fence.held()||!api_.source_current(api_.context,epoch))return fail(Result::source_changed);
        epoch_=epoch;graph_=graph;graph_native_=graph_native;
        ::memcpy(graph_values_,graph_values,sizeof graph_values_);
        count_=count;captured_=true;result_=Result::captured;return true;
    }
    // Restores ONLY the proven scalar component. It does not claim buffers,
    // remaining graph execution state, managed callbacks or GPU state are
    // restored. Clip caches are logically normalized via ORIGINAL Clip-only
    // cleanup/prepare; only actual temporal scalar fields are restored.
    // No original SetTime/Play/Pause is called and no native pointer,
    // graph handle, asset reference, vtable or child topology is ever copied.
    // Read-only all-target admission for outer multi-Actor transactions. It
    // performs the same exact slot/remap/binding/map checks as restoration,
    // without original cleanup, time writes, weight changes or cache mutation.
    bool validate_scalar_component(){
        mutation_started_=false;
        if(!captured_||!ready())return fail(Result::invalid_api);
        Guard fence(api_,epoch_);
        if(!fence.held()||!api_.manager_quiescent(api_.context,fence.lease))return fail(Result::fence_unavailable);
        if(!api_.source_current(api_.context,epoch_))return fail(Result::source_changed);
        uintptr_t graph_native=0;
        if(!graph_node(graph_,graph_native)||graph_native!=graph_native_)
            return fail(Result::graph_changed);
        for(const auto&s:graph_spans)if(!api_.mapped(api_.context,graph_native+s.offset,s.size,true))
            return fail(Result::memory_unavailable);
        Input targets[Capacity]{};uintptr_t nodes[Capacity]{};
        for(size_t i=0;i<count_;++i){const auto&r=records_[i];targets[i]=r.input;
            if(r.input.lifetime==Lifetime::rebuilt_timeline){
                Input mapped{};
                if(!api_.remap||!api_.remap(api_.context,epoch_,r.input,mapped)
                    ||mapped.kind!=r.input.kind||mapped.lifetime!=Lifetime::rebuilt_timeline
                    ||!same(mapped.logical,r.input.logical))return fail(Result::logical_remap_unverified);
                targets[i]=mapped;
            }
            const Layout*l=nullptr;
            if(!node(targets[i],graph_,graph_native,nodes[i],l))return false;
            if(l!=r.layout)return fail(Result::layout_unverified);
            // Validate the original Clip-only logical normalizer and authored
            // binding before admitting any scalar/cache write.
            if(r.input.kind==Kind::clip){
                ClipBinding current{};
                if(!clip_binding(targets[i],nodes[i],*l,current))return false;
                if(!same(current,r.clip))return fail(Result::clip_binding_changed);
                for(unsigned k=0;k<5;++k){uint8_t value=0;
                    if(!read(nodes[i]+clip_authored_offsets[k],&value,1)||value!=r.authored[k])
                        return fail(Result::clip_binding_changed);}
            }
            if(r.input.lifetime==Lifetime::persistent_exact
                &&(!same(targets[i].handle,r.input.handle)||nodes[i]!=r.native))return fail(Result::identity_changed);
            for(size_t j=0;j<i;++j)if(nodes[i]==nodes[j]||same(targets[i].handle,targets[j].handle))return fail(Result::inventory_changed);
            for(unsigned k=0;k<l->span_count;++k){const auto&s=l->spans[k];
                if(!api_.mapped(api_.context,nodes[i]+s.offset,s.size,true))return fail(Result::memory_unavailable);}
        }
        // All identities, all layouts, all write mappings, all logical remaps
        // and the complete current inventory are admitted before first write.
        if(!api_.inventory_exact(api_.context,graph_,targets,count_))return fail(Result::inventory_changed);
        if(!fence.held()||!api_.source_current(api_.context,epoch_)
            ||!api_.manager_quiescent(api_.context,fence.lease))return fail(Result::fence_unavailable);
        return true;
    }
    bool restore_scalar_component(){
        mutation_started_=false;
        if(!captured_||!ready())return fail(Result::invalid_api);
        Guard fence(api_,epoch_);
        if(!fence.held()||!api_.manager_quiescent(api_.context,fence.lease))return fail(Result::fence_unavailable);
        if(!api_.source_current(api_.context,epoch_))return fail(Result::source_changed);
        uintptr_t graph_native=0;
        if(!graph_node(graph_,graph_native)||graph_native!=graph_native_)
            return fail(Result::graph_changed);
        for(const auto&s:graph_spans)if(!api_.mapped(api_.context,graph_native+s.offset,s.size,true))
            return fail(Result::memory_unavailable);
        Input targets[Capacity]{};uintptr_t nodes[Capacity]{};
        for(size_t i=0;i<count_;++i){const auto&r=records_[i];targets[i]=r.input;
            if(r.input.lifetime==Lifetime::rebuilt_timeline){
                Input mapped{};
                if(!api_.remap||!api_.remap(api_.context,epoch_,r.input,mapped)
                    ||mapped.kind!=r.input.kind||mapped.lifetime!=Lifetime::rebuilt_timeline
                    ||!same(mapped.logical,r.input.logical))return fail(Result::logical_remap_unverified);
                targets[i]=mapped;
            }
            const Layout*l=nullptr;
            if(!node(targets[i],graph_,graph_native,nodes[i],l))return false;
            if(l!=r.layout)return fail(Result::layout_unverified);
            // Validate the original Clip-only logical normalizer and authored
            // binding before admitting any scalar/cache write.
            if(r.input.kind==Kind::clip){
                ClipBinding current{};
                if(!clip_binding(targets[i],nodes[i],*l,current))return false;
                if(!same(current,r.clip))return fail(Result::clip_binding_changed);
                for(unsigned k=0;k<5;++k){uint8_t value=0;
                    if(!read(nodes[i]+clip_authored_offsets[k],&value,1)||value!=r.authored[k])
                        return fail(Result::clip_binding_changed);}
            }
            if(r.input.lifetime==Lifetime::persistent_exact
                &&(!same(targets[i].handle,r.input.handle)||nodes[i]!=r.native))return fail(Result::identity_changed);
            for(size_t j=0;j<i;++j)if(nodes[i]==nodes[j]||same(targets[i].handle,targets[j].handle))return fail(Result::inventory_changed);
            for(unsigned k=0;k<l->span_count;++k){const auto&s=l->spans[k];
                if(!api_.mapped(api_.context,nodes[i]+s.offset,s.size,true))return fail(Result::memory_unavailable);}
        }
        // All identities, all layouts, all write mappings, all logical remaps
        // and the complete current inventory are admitted before first write.
        if(!api_.inventory_exact(api_.context,graph_,targets,count_))return fail(Result::inventory_changed);
        if(!fence.held()||!api_.source_current(api_.context,epoch_)
            ||!api_.manager_quiescent(api_.context,fence.lease))return fail(Result::fence_unavailable);
        // Clip-only original normalization. Never recurse through Script or
        // rebuild unrelated mixer/job buffers; existing physical job handles
        // and their exact buffer keys remain outside this operation.
        for(size_t i=0;i<count_;++i)if(records_[i].input.kind==Kind::clip){
            const auto&r=records_[i];result_=Result::normalizer_failed;mutation_started_=true;
            reinterpret_cast<void(*)(void*)>(r.layout->clip_cleanup)(reinterpret_cast<void*>(nodes[i]));
            reinterpret_cast<void(*)(void*,void*)>(r.layout->clip_prepare)(reinterpret_cast<void*>(nodes[i]),
                reinterpret_cast<void*>(r.clip.binding_context));
            uintptr_t native=0;const Layout*l=nullptr;ClipBinding current{};
            if(!fence.held()||!node(targets[i],graph_,graph_native,native,l)||native!=nodes[i]
                ||l!=r.layout||!clip_binding(targets[i],native,*l,current)||!same(current,r.clip))return false;
            for(unsigned k=0;k<5;++k){uint8_t value=0;
                if(!read(native+clip_authored_offsets[k],&value,1)||value!=r.authored[k])
                    return fail(Result::clip_binding_changed);}
            uint8_t ready=0,dirty=0,phase=1;
            if(!read(native+0x104,&ready,1)||ready!=1||!read(native+0x102,&dirty,1)||dirty
                ||!read(native+0x174,&phase,1)||phase)return fail(Result::normalizer_failed);
            // RootMath138 is derived output scratch: original full sampler
            // overwrites all five TRS+flags before reading it. Never copy its
            // old pointer or old values into a fresh arena. The next original
            // partial evaluation sees174=0 and first executes full sampling.
        }
        mutation_started_=true;
        for(size_t i=0;i<count_;++i)for(unsigned k=0;k<records_[i].layout->span_count;++k){
            const auto&s=records_[i].layout->spans[k];uint64_t value=0;
            ::memcpy(&value,reinterpret_cast<const void*>(nodes[i]+s.offset),s.size);
            value=(value&~s.mask)|(records_[i].values[k]&s.mask);
            ::memcpy(reinterpret_cast<void*>(nodes[i]+s.offset),&value,s.size);
        }
        // Restore graph counter together with every admitted node's matching
        // last-observed counter50. This is the original SampleTime counter,
        // not a graph pointer, allocator epoch or a fabricated public setter.
        for(unsigned i=0;i<5;++i){const auto&s=graph_spans[i];
            ::memcpy(reinterpret_cast<void*>(graph_native+s.offset),&graph_values_[i],s.size);}
        // C8 is a transient "inside graph update" guard. It must be zero at
        // every fence; it is never copied back to simulate a completed job.
        if(!fence.held()||!api_.manager_quiescent(api_.context,fence.lease))return fail(Result::fence_unavailable);
        result_=Result::scalar_component_restored;return true;
    }
    bool restore_source(){
        if(!source_restorable())return fail(Result::incomplete_native_sampling_state);
        // Intentionally unreachable in this foundation: no source graph may
        // advertise complete native restore from scalar checkpoints alone.
        if(!restore_scalar_component())return false;
        result_=Result::source_restored;return true;
    }
};
} // namespace idoly_mp4_native_temporal
'''
TEMPORAL_HEADER = r'''
namespace idoly_mp4_native_temporal {
struct FunctionPin {uintptr_t rva;uint8_t bytes[16];};
struct LayoutPin {Kind kind;uintptr_t vtable,rtti;const char*name;uintptr_t functions[8];FunctionPin code[8];FunctionPin cleanup,prepare;};
inline constexpr LayoutPin android_layout_pins[]={
 {Kind::script,0x14195b8,0x0,nullptr,{0x72ab50,0x72aba0,0x72bf74,0x72beb8,0x72b66c,0x72ba6c,0x72e490,0x72bd04},{{0x72ab50,{0xfe,0x4f,0xbf,0xa9,0x08,0x18,0x40,0xf9,0x69,0x67,0x00,0xf0,0xf3,0x03,0x00,0xaa}},{0x72aba0,{0xfe,0x4f,0xbf,0xa9,0xf3,0x03,0x00,0xaa,0xea,0xff,0xff,0x97,0xe0,0x03,0x13,0xaa}},{0x72bf74,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0xe1,0x03,0x01,0x2a,0x22,0x00,0x80,0x52}},{0x72beb8,{0x08,0x20,0x20,0x1e,0x24,0x01,0x00,0x54,0x08,0x18,0x40,0xf9,0x29,0x7c,0x40,0x93}},{0x72b66c,{0xff,0x43,0x02,0xd1,0xe8,0x33,0x00,0xfd,0xfe,0x37,0x00,0xf9,0xf6,0x57,0x07,0xa9}},{0x72ba6c,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x08,0x38,0x40,0xb9}},{0x72e490,{0xe0,0x03,0x1f,0xaa,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6}},{0x72bd04,{0xff,0x03,0x02,0xd1,0xfe,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xf3,0x03,0x02,0xaa}}},{0,{}},{0,{}}},
 {Kind::mixer,0x1424060,0x0,nullptr,{0x8ed94c,0x8ed788,0x72bf74,0x72beb8,0x8e9270,0x72ba6c,0x72e490,0x72bd04},{{0x8ed94c,{0xfe,0x4f,0xbf,0xa9,0xa8,0x59,0x00,0xf0,0x08,0x81,0x01,0x91,0xf3,0x03,0x00,0xaa}},{0x8ed788,{0xfe,0x4f,0xbf,0xa9,0xa8,0x59,0x00,0xf0,0x08,0x81,0x01,0x91,0xf3,0x03,0x00,0xaa}},{0x72bf74,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0xe1,0x03,0x01,0x2a,0x22,0x00,0x80,0x52}},{0x72beb8,{0x08,0x20,0x20,0x1e,0x24,0x01,0x00,0x54,0x08,0x18,0x40,0xf9,0x29,0x7c,0x40,0x93}},{0x8e9270,{0xc0,0x03,0x5f,0xd6,0xfe,0x0f,0x1f,0xf8,0xe4,0xae,0xfc,0x97,0x00,0x2c,0x40,0xf9}},{0x72ba6c,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x08,0x38,0x40,0xb9}},{0x72e490,{0xe0,0x03,0x1f,0xaa,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6}},{0x72bd04,{0xff,0x03,0x02,0xd1,0xfe,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xf3,0x03,0x02,0xaa}}},{0,{}},{0,{}}},
 {Kind::layer_mixer,0x1424170,0x0,nullptr,{0x8f36c8,0x8f3720,0x8ef324,0x8ef3a0,0x8e9270,0x72ba6c,0x72e490,0x72bd04},{{0x8f36c8,{0xfe,0x4f,0xbf,0xa9,0x88,0x59,0x00,0xb0,0x08,0xc1,0x05,0x91,0xf3,0x03,0x00,0xaa}},{0x8f3720,{0xfe,0x4f,0xbf,0xa9,0x88,0x59,0x00,0xb0,0x08,0xc1,0x05,0x91,0xf3,0x03,0x00,0xaa}},{0x8ef324,{0xfe,0x4f,0xbf,0xa9,0xf3,0x03,0x00,0xaa,0x12,0xf3,0xf8,0x97,0xe0,0x03,0x13,0xaa}},{0x8ef3a0,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x08,0x1c,0xa0,0x4e}},{0x8e9270,{0xc0,0x03,0x5f,0xd6,0xfe,0x0f,0x1f,0xf8,0xe4,0xae,0xfc,0x97,0x00,0x2c,0x40,0xf9}},{0x72ba6c,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x08,0x38,0x40,0xb9}},{0x72e490,{0xe0,0x03,0x1f,0xaa,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6}},{0x72bd04,{0xff,0x03,0x02,0xd1,0xfe,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xf3,0x03,0x02,0xaa}}},{0,{}},{0,{}}},
 {Kind::clip,0x1423f70,0x0,nullptr,{0x8ed844,0x8ed898,0x72bf74,0x72beb8,0x8e9270,0x8ec208,0x8ea7a8,0x72bd04},{{0x8ed844,{0xfe,0x4f,0xbf,0xa9,0xa8,0x59,0x00,0xd0,0x08,0xc1,0x3d,0x91,0xf3,0x03,0x00,0xaa}},{0x8ed898,{0xfe,0x4f,0xbf,0xa9,0xa8,0x59,0x00,0xd0,0x08,0xc1,0x3d,0x91,0xf3,0x03,0x00,0xaa}},{0x72bf74,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0xe1,0x03,0x01,0x2a,0x22,0x00,0x80,0x52}},{0x72beb8,{0x08,0x20,0x20,0x1e,0x24,0x01,0x00,0x54,0x08,0x18,0x40,0xf9,0x29,0x7c,0x40,0x93}},{0x8e9270,{0xc0,0x03,0x5f,0xd6,0xfe,0x0f,0x1f,0xf8,0xe4,0xae,0xfc,0x97,0x00,0x2c,0x40,0xf9}},{0x8ec208,{0x01,0x30,0x40,0xfd,0x08,0x38,0x40,0xb9,0x09,0xe0,0x47,0x39,0x20,0x20,0x60,0x1e}},{0x8ea7a8,{0x00,0xe8,0x40,0xf9,0xc0,0x03,0x5f,0xd6,0xfe,0x0f,0x1d,0xf8,0xf6,0x57,0x01,0xa9}},{0x72bd04,{0xff,0x03,0x02,0xd1,0xfe,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xf3,0x03,0x02,0xaa}}},{0x8ec1ac,{0xfe,0x4f,0xbf,0xa9,0x08,0x10,0x44,0x39,0xf3,0x03,0x00,0xaa,0x48,0x01,0x00,0x34}},{0x8ebdb0,{0xfe,0x0f,0x1c,0xf8,0xf8,0x5f,0x01,0xa9,0xf6,0x57,0x02,0xa9,0xf4,0x4f,0x03,0xa9}}},
 {Kind::animation_script,0x1423bd8,0x0,nullptr,{0x8e91c0,0x8e9214,0x72bf74,0x72beb8,0x8e9270,0x72ba6c,0x72e490,0x72bd04},{{0x8e91c0,{0xfe,0x4f,0xbf,0xa9,0xc8,0x59,0x00,0xd0,0x08,0x61,0x2f,0x91,0xf3,0x03,0x00,0xaa}},{0x8e9214,{0xfe,0x4f,0xbf,0xa9,0xc8,0x59,0x00,0xd0,0x08,0x61,0x2f,0x91,0xf3,0x03,0x00,0xaa}},{0x72bf74,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0xe1,0x03,0x01,0x2a,0x22,0x00,0x80,0x52}},{0x72beb8,{0x08,0x20,0x20,0x1e,0x24,0x01,0x00,0x54,0x08,0x18,0x40,0xf9,0x29,0x7c,0x40,0x93}},{0x8e9270,{0xc0,0x03,0x5f,0xd6,0xfe,0x0f,0x1f,0xf8,0xe4,0xae,0xfc,0x97,0x00,0x2c,0x40,0xf9}},{0x72ba6c,{0xe8,0x0f,0x1e,0xfc,0xfe,0x07,0x00,0xf9,0xf4,0x4f,0x01,0xa9,0x08,0x38,0x40,0xb9}},{0x72e490,{0xe0,0x03,0x1f,0xaa,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6,0xc0,0x03,0x5f,0xd6}},{0x72bd04,{0xff,0x03,0x02,0xd1,0xfe,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xf3,0x03,0x02,0xaa}}},{0,{}},{0,{}}},
};
inline constexpr const char* android_temporal_engine_sha256="c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85";
inline constexpr LayoutPin ios_layout_pins[]={
 {Kind::script,0x97f2078,0x97f2108,"8Playable",{0xdc0c74,0xdc0c78,0xdc21b4,0xdc20f8,0xdc1878,0xdc1c74,0xdc4608,0xdc1f18},{{0xdc0c74,{0xe7,0xff,0xff,0x17,0xfd,0x7b,0xbf,0xa9,0xfd,0x03,0x00,0x91,0xe4,0xff,0xff,0x97}},{0xdc0c78,{0xfd,0x7b,0xbf,0xa9,0xfd,0x03,0x00,0x91,0xe4,0xff,0xff,0x97,0xfd,0x7b,0xc1,0xa8}},{0xdc21b4,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0x00,0x81,0x00,0x91,0xe1,0x03,0x01,0x2a}},{0xdc20f8,{0x28,0x7c,0x40,0x93,0x09,0x18,0x40,0xf9,0x2a,0x19,0x40,0xf9,0x08,0x20,0x20,0x1e}},{0xdc1878,{0xff,0x83,0x02,0xd1,0xe9,0x23,0x06,0x6d,0xf6,0x57,0x07,0xa9,0xf4,0x4f,0x08,0xa9}},{0xdc1c74,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0xdc4608,{0x00,0x00,0x80,0xd2,0xc0,0x03,0x5f,0xd6,0xa7,0x21,0xfb,0x17,0xfd,0x7b,0xbf,0xa9}},{0xdc1f18,{0xff,0x43,0x02,0xd1,0xf6,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xfd,0x7b,0x08,0xa9}}},{0,{}},{0,{}}},
 {Kind::mixer,0x97f7520,0x97f7600,"22AnimationMixerPlayable",{0xf3e254,0xf3e2b4,0xdc21b4,0xdc20f8,0xf3e318,0xdc1c74,0xdc4608,0xdc1f18},{{0xf3e254,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xf3e2b4,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xdc21b4,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0x00,0x81,0x00,0x91,0xe1,0x03,0x01,0x2a}},{0xdc20f8,{0x28,0x7c,0x40,0x93,0x09,0x18,0x40,0xf9,0x2a,0x19,0x40,0xf9,0x08,0x20,0x20,0x1e}},{0xf3e318,{0xc0,0x03,0x5f,0xd6,0xfd,0x7b,0xbf,0xa9,0xfd,0x03,0x00,0x91,0xa7,0xbe,0xfc,0x97}},{0xdc1c74,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0xdc4608,{0x00,0x00,0x80,0xd2,0xc0,0x03,0x5f,0xd6,0xa7,0x21,0xfb,0x17,0xfd,0x7b,0xbf,0xa9}},{0xdc1f18,{0xff,0x43,0x02,0xd1,0xf6,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xfd,0x7b,0x08,0xa9}}},{0,{}},{0,{}}},
 {Kind::layer_mixer,0x97f7a20,0x97f80d8,"27AnimationLayerMixerPlayable",{0xf4badc,0xf4bb38,0xf475cc,0xf4765c,0xf3e318,0xdc1c74,0xdc4608,0xdc1f18},{{0xf4badc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xf4bb38,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xf475cc,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xf4765c,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0xf3e318,{0xc0,0x03,0x5f,0xd6,0xfd,0x7b,0xbf,0xa9,0xfd,0x03,0x00,0x91,0xa7,0xbe,0xfc,0x97}},{0xdc1c74,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0xdc4608,{0x00,0x00,0x80,0xd2,0xc0,0x03,0x5f,0xd6,0xa7,0x21,0xfb,0x17,0xfd,0x7b,0xbf,0xa9}},{0xdc1f18,{0xff,0x43,0x02,0xd1,0xf6,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xfd,0x7b,0x08,0xa9}}},{0,{}},{0,{}}},
 {Kind::clip,0x97f7430,0x97f7618,"21AnimationClipPlayable",{0xf3e544,0xf3e59c,0xdc21b4,0xdc20f8,0xf3e318,0xf3cb94,0xf3b014,0xdc1f18},{{0xf3e544,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xf3e59c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xdc21b4,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0x00,0x81,0x00,0x91,0xe1,0x03,0x01,0x2a}},{0xdc20f8,{0x28,0x7c,0x40,0x93,0x09,0x18,0x40,0xf9,0x2a,0x19,0x40,0xf9,0x08,0x20,0x20,0x1e}},{0xf3e318,{0xc0,0x03,0x5f,0xd6,0xfd,0x7b,0xbf,0xa9,0xfd,0x03,0x00,0x91,0xa7,0xbe,0xfc,0x97}},{0xf3cb94,{0x08,0x38,0x40,0xb9,0x01,0x30,0x40,0xfd,0x20,0x20,0x60,0x1e,0xe9,0x17,0x9f,0x1a}},{0xf3b014,{0x00,0xe8,0x40,0xf9,0xc0,0x03,0x5f,0xd6,0xf6,0x57,0xbd,0xa9,0xf4,0x4f,0x01,0xa9}},{0xdc1f18,{0xff,0x43,0x02,0xd1,0xf6,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xfd,0x7b,0x08,0xa9}}},{0xf3cb2c,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xf3c73c,{0xf8,0x5f,0xbc,0xa9,0xf6,0x57,0x01,0xa9,0xf4,0x4f,0x02,0xa9,0xfd,0x7b,0x03,0xa9}}},
 {Kind::animation_script,0x97f76f0,0x97f7980,"23AnimationScriptPlayable",{0xf45640,0xf45698,0xdc21b4,0xdc20f8,0xf3e318,0xdc1c74,0xdc4608,0xdc1f18},{{0xf45640,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xf45698,{0xf4,0x4f,0xbe,0xa9,0xfd,0x7b,0x01,0xa9,0xfd,0x43,0x00,0x91,0xf3,0x03,0x00,0xaa}},{0xdc21b4,{0xc1,0x00,0xf8,0x37,0x08,0x18,0x40,0xf9,0x00,0x81,0x00,0x91,0xe1,0x03,0x01,0x2a}},{0xdc20f8,{0x28,0x7c,0x40,0x93,0x09,0x18,0x40,0xf9,0x2a,0x19,0x40,0xf9,0x08,0x20,0x20,0x1e}},{0xf3e318,{0xc0,0x03,0x5f,0xd6,0xfd,0x7b,0xbf,0xa9,0xfd,0x03,0x00,0x91,0xa7,0xbe,0xfc,0x97}},{0xdc1c74,{0xe9,0x23,0xbd,0x6d,0xf4,0x4f,0x01,0xa9,0xfd,0x7b,0x02,0xa9,0xfd,0x83,0x00,0x91}},{0xdc4608,{0x00,0x00,0x80,0xd2,0xc0,0x03,0x5f,0xd6,0xa7,0x21,0xfb,0x17,0xfd,0x7b,0xbf,0xa9}},{0xdc1f18,{0xff,0x43,0x02,0xd1,0xf6,0x57,0x06,0xa9,0xf4,0x4f,0x07,0xa9,0xfd,0x7b,0x08,0xa9}}},{0,{}},{0,{}}},
};
inline constexpr const char* ios_temporal_engine_sha256="b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf";
inline bool build_temporal_layouts(uintptr_t native_base,bool ios,Layout*out,size_t capacity){
 if(!out||capacity<5||native_base>(~uintptr_t(0))-0xa000000)return false;
 const auto*p=ios?ios_layout_pins:android_layout_pins;
 for(unsigned i=0;i<5;++i){const auto&r=p[i];const bool clip=r.kind==Kind::clip;
  out[i]={r.kind,native_base+r.vtable,r.rtti?native_base+r.rtti:0,r.name,
   static_cast<uint16_t>(clip?0x1f9:0xc0),clip?clip_spans:base_spans,
   static_cast<uint8_t>(clip?sizeof(clip_spans)/sizeof(Span):sizeof(base_spans)/sizeof(Span)),
   0xb09054e6f1ef81a6ULL^static_cast<uint64_t>(r.vtable),true,
   clip?native_base+r.cleanup.rva:0,clip?native_base+r.prepare.rva:0,
   clip?0xb09054e6f1ef81a6ULL:0};
 }
 return true;
}
// profile_ok must verify exact original-source provenance through the validated
// current build/patch receipt (the packaged image can contain approved aliases),
// every
// expected vtable pointer and function prefix in LayoutPin, exact RTTI/name,
// plus retained typed IsValid/GetGraph/event queries from the JSON receipt.
// No pointer in this table may be treated as a guessed API/unchecked call.
} // namespace idoly_mp4_native_temporal
'''
TEMPORAL_PROFILES = {'android': {'engine_sha256': 'c36ea39e5040fbcd0577f7c49d08e149e2e7dc62449d90aadce761118a816c85',
             'native_sha256': '68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3',
             'metadata_sha256': 'f03b65e71c07648215ae18d6bb787462f2b049c45212f379eaa9ea05f8ba874e',
             'layouts': {'script': {'vtable': '0x14195b8',
                                    'rtti': '0x0',
                                    'rtti_name': None,
                                    'vtable_first8': ['0x72ab50',
                                                      '0x72aba0',
                                                      '0x72bf74',
                                                      '0x72beb8',
                                                      '0x72b66c',
                                                      '0x72ba6c',
                                                      '0x72e490',
                                                      '0x72bd04'],
                                    'code_prefixes': {'0x72aba0': 'fe4fbfa9f30300aaeaffff97e00313aa',
                                                      '0x72bd04': 'ff0302d1fe5706a9f44f07a9f30302aa',
                                                      '0x72b66c': 'ff4302d1e83300fdfe3700f9f65707a9',
                                                      '0x72ba6c': 'e80f1efcfe0700f9f44f01a9083840b9',
                                                      '0x72ab50': 'fe4fbfa9081840f9696700f0f30300aa',
                                                      '0x72e490': 'e0031faac0035fd6c0035fd6c0035fd6',
                                                      '0x72bf74': 'c100f837081840f9e103012a22008052',
                                                      '0x72beb8': '0820201e24010054081840f9297c4093'},
                                    'minimum_read_extent': '0xc0',
                                    'span_set': 'base_spans',
                                    'component_only': True,
                                    'requires_typed_source_factory_provenance': True,
                                    'requires_complete_job_fence_and_manager_queues_closed': True,
                                    'requires_outer_managed_history_and_physical_job_restoration': True},
                         'mixer': {'vtable': '0x1424060',
                                   'rtti': '0x0',
                                   'rtti_name': None,
                                   'vtable_first8': ['0x8ed94c',
                                                     '0x8ed788',
                                                     '0x72bf74',
                                                     '0x72beb8',
                                                     '0x8e9270',
                                                     '0x72ba6c',
                                                     '0x72e490',
                                                     '0x72bd04'],
                                   'code_prefixes': {'0x72bd04': 'ff0302d1fe5706a9f44f07a9f30302aa',
                                                     '0x8ed788': 'fe4fbfa9a85900f008810191f30300aa',
                                                     '0x8ed94c': 'fe4fbfa9a85900f008810191f30300aa',
                                                     '0x72ba6c': 'e80f1efcfe0700f9f44f01a9083840b9',
                                                     '0x8e9270': 'c0035fd6fe0f1ff8e4aefc97002c40f9',
                                                     '0x72e490': 'e0031faac0035fd6c0035fd6c0035fd6',
                                                     '0x72bf74': 'c100f837081840f9e103012a22008052',
                                                     '0x72beb8': '0820201e24010054081840f9297c4093'},
                                   'minimum_read_extent': '0xc0',
                                   'span_set': 'base_spans',
                                   'component_only': True,
                                   'requires_typed_source_factory_provenance': True,
                                   'requires_complete_job_fence_and_manager_queues_closed': True,
                                   'requires_outer_managed_history_and_physical_job_restoration': False},
                         'layer_mixer': {'vtable': '0x1424170',
                                         'rtti': '0x0',
                                         'rtti_name': None,
                                         'vtable_first8': ['0x8f36c8',
                                                           '0x8f3720',
                                                           '0x8ef324',
                                                           '0x8ef3a0',
                                                           '0x8e9270',
                                                           '0x72ba6c',
                                                           '0x72e490',
                                                           '0x72bd04'],
                                         'code_prefixes': {'0x8f3720': 'fe4fbfa9885900b008c10591f30300aa',
                                                           '0x8ef3a0': 'e80f1efcfe0700f9f44f01a9081ca04e',
                                                           '0x8ef324': 'fe4fbfa9f30300aa12f3f897e00313aa',
                                                           '0x72bd04': 'ff0302d1fe5706a9f44f07a9f30302aa',
                                                           '0x8f36c8': 'fe4fbfa9885900b008c10591f30300aa',
                                                           '0x72ba6c': 'e80f1efcfe0700f9f44f01a9083840b9',
                                                           '0x8e9270': 'c0035fd6fe0f1ff8e4aefc97002c40f9',
                                                           '0x72e490': 'e0031faac0035fd6c0035fd6c0035fd6'},
                                         'minimum_read_extent': '0xc0',
                                         'span_set': 'base_spans',
                                         'component_only': True,
                                         'requires_typed_source_factory_provenance': True,
                                         'requires_complete_job_fence_and_manager_queues_closed': True,
                                         'requires_outer_managed_history_and_physical_job_restoration': False},
                         'clip': {'vtable': '0x1423f70',
                                  'rtti': '0x0',
                                  'rtti_name': None,
                                  'vtable_first8': ['0x8ed844',
                                                    '0x8ed898',
                                                    '0x72bf74',
                                                    '0x72beb8',
                                                    '0x8e9270',
                                                    '0x8ec208',
                                                    '0x8ea7a8',
                                                    '0x72bd04'],
                                  'code_prefixes': {'0x8ed844': 'fe4fbfa9a85900d008c13d91f30300aa',
                                                    '0x72bd04': 'ff0302d1fe5706a9f44f07a9f30302aa',
                                                    '0x8ec208': '013040fd083840b909e047392020601e',
                                                    '0x8ea7a8': '00e840f9c0035fd6fe0f1df8f65701a9',
                                                    '0x72beb8': '0820201e24010054081840f9297c4093',
                                                    '0x8e9270': 'c0035fd6fe0f1ff8e4aefc97002c40f9',
                                                    '0x72bf74': 'c100f837081840f9e103012a22008052',
                                                    '0x8ed898': 'fe4fbfa9a85900d008c13d91f30300aa'},
                                  'minimum_read_extent': '0x1f9',
                                  'span_set': 'clip_spans',
                                  'component_only': True,
                                  'requires_typed_source_factory_provenance': True,
                                  'requires_complete_job_fence_and_manager_queues_closed': True,
                                  'requires_outer_managed_history_and_physical_job_restoration': False,
                                  'cleanup_D0': '0x8ec1ac',
                                  'prepare_C8': '0x8ebdb0',
                                  'cleanup_prefix': 'fe4fbfa908104439f30300aa48010034',
                                  'prepare_prefix': 'fe0f1cf8f85f01a9f65702a9f44f03a9',
                                  'normalization': 'Clip-only original cleanup/prepare, same '
                                                   'nativeAnimator+B0 context; same5authoredconfig; '
                                                   'actualget_events.Length0; old174/104notrestored; '
                                                   'no138copy',
                                  'authored_config_bytes': ['0x1f0', '0x1f5', '0x1f1', '0x1f6', '0x1f7'],
                                  'reject_native_blendtree_or_controller_parent': True},
                         'animation_script': {'vtable': '0x1423bd8',
                                              'rtti': '0x0',
                                              'rtti_name': None,
                                              'vtable_first8': ['0x8e91c0',
                                                                '0x8e9214',
                                                                '0x72bf74',
                                                                '0x72beb8',
                                                                '0x8e9270',
                                                                '0x72ba6c',
                                                                '0x72e490',
                                                                '0x72bd04'],
                                              'code_prefixes': {'0x8e91c0': 'fe4fbfa9c85900d008612f91f30300aa',
                                                                '0x72bd04': 'ff0302d1fe5706a9f44f07a9f30302aa',
                                                                '0x72ba6c': 'e80f1efcfe0700f9f44f01a9083840b9',
                                                                '0x8e9270': 'c0035fd6fe0f1ff8e4aefc97002c40f9',
                                                                '0x72e490': 'e0031faac0035fd6c0035fd6c0035fd6',
                                                                '0x8e9214': 'fe4fbfa9c85900d008612f91f30300aa',
                                                                '0x72bf74': 'c100f837081840f9e103012a22008052',
                                                                '0x72beb8': '0820201e24010054081840f9297c4093'},
                                              'minimum_read_extent': '0xc0',
                                              'span_set': 'base_spans',
                                              'component_only': True,
                                              'requires_typed_source_factory_provenance': True,
                                              'requires_complete_job_fence_and_manager_queues_closed': True,
                                              'requires_outer_managed_history_and_physical_job_restoration': True}}},
 'ios': {'engine_sha256': 'b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf',
         'native_sha256': 'b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf',
         'metadata_sha256': 'd11a50fd75d1e6744ae10f2a6e7081ea87bcca267a42ba0a72fe497057cd2bda',
         'layouts': {'script': {'vtable': '0x97f2078',
                                'rtti': '0x97f2108',
                                'rtti_name': '8Playable',
                                'vtable_first8': ['0xdc0c74',
                                                  '0xdc0c78',
                                                  '0xdc21b4',
                                                  '0xdc20f8',
                                                  '0xdc1878',
                                                  '0xdc1c74',
                                                  '0xdc4608',
                                                  '0xdc1f18'],
                                'code_prefixes': {'0xdc20f8': '287c4093091840f92a1940f90820201e',
                                                  '0xdc4608': '000080d2c0035fd6a721fb17fd7bbfa9',
                                                  '0xdc1f18': 'ff4302d1f65706a9f44f07a9fd7b08a9',
                                                  '0xdc21b4': 'c100f837081840f900810091e103012a',
                                                  '0xdc0c74': 'e7ffff17fd7bbfa9fd030091e4ffff97',
                                                  '0xdc1c74': 'e923bd6df44f01a9fd7b02a9fd830091',
                                                  '0xdc0c78': 'fd7bbfa9fd030091e4ffff97fd7bc1a8',
                                                  '0xdc1878': 'ff8302d1e923066df65707a9f44f08a9'},
                                'minimum_read_extent': '0xc0',
                                'span_set': 'base_spans',
                                'component_only': True,
                                'requires_typed_source_factory_provenance': True,
                                'requires_complete_job_fence_and_manager_queues_closed': True,
                                'requires_outer_managed_history_and_physical_job_restoration': True},
                     'mixer': {'vtable': '0x97f7520',
                               'rtti': '0x97f7600',
                               'rtti_name': '22AnimationMixerPlayable',
                               'vtable_first8': ['0xf3e254',
                                                 '0xf3e2b4',
                                                 '0xdc21b4',
                                                 '0xdc20f8',
                                                 '0xf3e318',
                                                 '0xdc1c74',
                                                 '0xdc4608',
                                                 '0xdc1f18'],
                               'code_prefixes': {'0xdc4608': '000080d2c0035fd6a721fb17fd7bbfa9',
                                                 '0xf3e318': 'c0035fd6fd7bbfa9fd030091a7befc97',
                                                 '0xdc1f18': 'ff4302d1f65706a9f44f07a9fd7b08a9',
                                                 '0xf3e2b4': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                 '0xdc21b4': 'c100f837081840f900810091e103012a',
                                                 '0xf3e254': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                 '0xdc1c74': 'e923bd6df44f01a9fd7b02a9fd830091',
                                                 '0xdc20f8': '287c4093091840f92a1940f90820201e'},
                               'minimum_read_extent': '0xc0',
                               'span_set': 'base_spans',
                               'component_only': True,
                               'requires_typed_source_factory_provenance': True,
                               'requires_complete_job_fence_and_manager_queues_closed': True,
                               'requires_outer_managed_history_and_physical_job_restoration': False},
                     'layer_mixer': {'vtable': '0x97f7a20',
                                     'rtti': '0x97f80d8',
                                     'rtti_name': '27AnimationLayerMixerPlayable',
                                     'vtable_first8': ['0xf4badc',
                                                       '0xf4bb38',
                                                       '0xf475cc',
                                                       '0xf4765c',
                                                       '0xf3e318',
                                                       '0xdc1c74',
                                                       '0xdc4608',
                                                       '0xdc1f18'],
                                     'code_prefixes': {'0xdc4608': '000080d2c0035fd6a721fb17fd7bbfa9',
                                                       '0xf475cc': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                       '0xf3e318': 'c0035fd6fd7bbfa9fd030091a7befc97',
                                                       '0xdc1f18': 'ff4302d1f65706a9f44f07a9fd7b08a9',
                                                       '0xdc1c74': 'e923bd6df44f01a9fd7b02a9fd830091',
                                                       '0xf4bb38': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                       '0xf4badc': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                       '0xf4765c': 'e923bd6df44f01a9fd7b02a9fd830091'},
                                     'minimum_read_extent': '0xc0',
                                     'span_set': 'base_spans',
                                     'component_only': True,
                                     'requires_typed_source_factory_provenance': True,
                                     'requires_complete_job_fence_and_manager_queues_closed': True,
                                     'requires_outer_managed_history_and_physical_job_restoration': False},
                     'clip': {'vtable': '0x97f7430',
                              'rtti': '0x97f7618',
                              'rtti_name': '21AnimationClipPlayable',
                              'vtable_first8': ['0xf3e544',
                                                '0xf3e59c',
                                                '0xdc21b4',
                                                '0xdc20f8',
                                                '0xf3e318',
                                                '0xf3cb94',
                                                '0xf3b014',
                                                '0xdc1f18'],
                              'code_prefixes': {'0xf3e544': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                '0xf3e318': 'c0035fd6fd7bbfa9fd030091a7befc97',
                                                '0xdc1f18': 'ff4302d1f65706a9f44f07a9fd7b08a9',
                                                '0xdc21b4': 'c100f837081840f900810091e103012a',
                                                '0xf3cb94': '083840b9013040fd2020601ee9179f1a',
                                                '0xf3b014': '00e840f9c0035fd6f657bda9f44f01a9',
                                                '0xdc20f8': '287c4093091840f92a1940f90820201e',
                                                '0xf3e59c': 'f44fbea9fd7b01a9fd430091f30300aa'},
                              'minimum_read_extent': '0x1f9',
                              'span_set': 'clip_spans',
                              'component_only': True,
                              'requires_typed_source_factory_provenance': True,
                              'requires_complete_job_fence_and_manager_queues_closed': True,
                              'requires_outer_managed_history_and_physical_job_restoration': False,
                              'cleanup_D0': '0xf3cb2c',
                              'prepare_C8': '0xf3c73c',
                              'cleanup_prefix': 'f44fbea9fd7b01a9fd430091f30300aa',
                              'prepare_prefix': 'f85fbca9f65701a9f44f02a9fd7b03a9',
                              'normalization': 'Clip-only original cleanup/prepare, same nativeAnimator+B0 '
                                               'context; same5authoredconfig; actualget_events.Length0; '
                                               'old174/104notrestored; no138copy',
                              'authored_config_bytes': ['0x1f0', '0x1f5', '0x1f1', '0x1f6', '0x1f7'],
                              'reject_native_blendtree_or_controller_parent': True},
                     'animation_script': {'vtable': '0x97f76f0',
                                          'rtti': '0x97f7980',
                                          'rtti_name': '23AnimationScriptPlayable',
                                          'vtable_first8': ['0xf45640',
                                                            '0xf45698',
                                                            '0xdc21b4',
                                                            '0xdc20f8',
                                                            '0xf3e318',
                                                            '0xdc1c74',
                                                            '0xdc4608',
                                                            '0xdc1f18'],
                                          'code_prefixes': {'0xf45640': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                            '0xdc4608': '000080d2c0035fd6a721fb17fd7bbfa9',
                                                            '0xf45698': 'f44fbea9fd7b01a9fd430091f30300aa',
                                                            '0xf3e318': 'c0035fd6fd7bbfa9fd030091a7befc97',
                                                            '0xdc1f18': 'ff4302d1f65706a9f44f07a9fd7b08a9',
                                                            '0xdc21b4': 'c100f837081840f900810091e103012a',
                                                            '0xdc1c74': 'e923bd6df44f01a9fd7b02a9fd830091',
                                                            '0xdc20f8': '287c4093091840f92a1940f90820201e'},
                                          'minimum_read_extent': '0xc0',
                                          'span_set': 'base_spans',
                                          'component_only': True,
                                          'requires_typed_source_factory_provenance': True,
                                          'requires_complete_job_fence_and_manager_queues_closed': True,
                                          'requires_outer_managed_history_and_physical_job_restoration': True}}}}

def temporal_profile(native,image,platform):
    row=TEMPORAL_PROFILES[platform]
    need(hashlib.sha256(native).hexdigest()==row["engine_sha256"],"actor_temporal_engine_pin_differs")
    offset=image.file_offset if platform=="android"else image.offset
    pointer=image.read_pointer if platform=="android"else image.qword
    for name,layout in row["layouts"].items():
        table=int(layout["vtable"],0)
        need(pointer(table-8)==int(layout["rtti"],0),"actor_temporal_rtti_differs:"+name)
        need([pointer(table+i*8)for i in range(8)]==[int(x,0)for x in layout["vtable_first8"]],"actor_temporal_vtable_differs:"+name)
        for address,prefix in layout["code_prefixes"].items():
            at=offset(int(address,0));need(native[at:at+16].hex()==prefix,"actor_temporal_code_differs:"+address)
        for key in("cleanup","prepare"):
            if key+"_prefix"in layout:
                address=int(layout[key+("_D0"if key=="cleanup"else"_C8")],0);at=offset(address)
                need(native[at:at+16].hex()==layout[key+"_prefix"],"actor_temporal_normalizer_differs:"+key)
    return row


def profile(original, platform, burst, engine):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    native_pin, metadata_pin = PINS[platform]
    need(hashlib.sha256(original.b).hexdigest() == native_pin, "actor_original_native_pin_mismatch")
    need(hashlib.sha256(original.m).hexdigest() == metadata_pin, "actor_original_metadata_pin_mismatch")
    methods = {alias: original.method(*arguments) for alias, arguments in {**SELECT, **PRESENTATION_SELECT}.items()}
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
    from audit_mp4_replay import c_exports
    methods.update(c_exports(original,platform,selected=PRESENTATION_EXPORTS))
    methods.update(derived_callbacks(original,platform))
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
        "methods":methods,"fields":fields,"structs":layouts,"fence":fence,"native_graph":native_graph_mode(native,image,platform),"native_output_weight":native_output_weight(native,image,platform),"native_temporal":temporal_profile(native,image,platform),
        "handle_resolution":handle_resolution(native,image,platform),
        "presentation_schemas":presentation_schema(original),
        "presentation_callbacks":presentation_callbacks(original,platform),
        "common_jobs":common_jobs(original),
        "types":{"actor_job_type":runtime_type(original,"ActorSwing.ActorSwingJob",17),"transform_type":runtime_type(original,"UnityEngine.Transform",18),"talk_job_type":runtime_type(original,"VL.Unsafe.Jobs.VLActorTalkJob",17),
            "material_type":runtime_type(original,"UnityEngine.Material",18),"block_type":runtime_type(original,"UnityEngine.MaterialPropertyBlock",18)},
        "scope":{"game_or_gpu_executed":False,"offline_scene_pipeline_verified":False,
            "live_job_completion_and_owner_state_validation_required":True,"all_procedural_or_physics_coverage_claimed":False}}


def render(profiles):
    aliases = [*SELECT,*PRESENTATION_SELECT,*PRESENTATION_EXPORTS,"derived_late_ref","derived_late_shared","burst_execute"]
    fields = [*FIELDS,"native_animator_job"]
    lines = ["// SPDX-License-Identifier: AGPL-3.0-or-later", "#pragma once",
        "// Generated by tools/audit_mp4_actor_state.py from exact original clients.",
        "#ifndef IDOLY_DARWIN_BRIDGE", "#include <stdint.h>", "#include <stddef.h>", "#include <string.h>", "#endif", TEMPORAL_COMPONENT, TEMPORAL_HEADER, "namespace idoly_mp4_actor {",
        "struct ActorBinding { uintptr_t rva;uint8_t prefix[16]; };",
        "struct ActorPresentationField { uint16_t offset,bytes;bool identity; };",
        "struct ActorPresentationSchema { const char* type;ActorBinding klass;const ActorPresentationField* fields;uint16_t count; };",
        "struct ActorValueRange { uint16_t offset,bytes; };",
        "struct ActorFixedContainer { uint16_t offset,component_offset,stride;bool list;const ActorValueRange* caches;uint16_t cache_count; };",
        "struct ActorFixedJobSchema { const char* type;const char* component_type;ActorBinding job_type,component_class;uint16_t bytes,playable_offset;const ActorFixedContainer* containers;uint16_t container_count;const ActorValueRange* caches;uint16_t cache_count;const ActorValueRange* scratch;uint16_t scratch_count;const ActorValueRange* history;uint16_t history_count; };",
        "struct ActorNativeGraphProfile { const char* engine_sha256;ActorBinding mode_icall,mode_dispatch,graph_validate,mode_setter;uint32_t node_graph,graph_mode; };",
        "struct ActorNativeOutputProfile { const char* engine_sha256;ActorBinding icall,dispatch,validate,setter;uint32_t slot_output,weight; };",
        "struct ActorFields {"]
    lines += ["    uint32_t "+name+";" for name in fields]
    lines += ["};", "struct ActorProfile {", "    const char* native_sha256;const char* metadata_sha256;const char* burst_native_sha256;"]
    lines += ["    ActorBinding "+name+";" for name in [*aliases,"actor_job_type","transform_type","talk_job_type","material_type","block_type"]]
    lines += ["    ActorFields fields;", "    ActorNativeGraphProfile native_graph;", "    ActorNativeOutputProfile native_output;", "};"]
    for platform, value in profiles.items():
        lines += ["inline constexpr ActorProfile "+platform+"_actor_profile={"]
        lines += ["    \""+value["sources"][key]+"\"," for key in ("native_sha256","metadata_sha256","burst_native_sha256")]
        for name in [*aliases,"actor_job_type","transform_type","talk_job_type","material_type","block_type"]:
            row = value["methods" if name in aliases else "types"][name]
            lines += ["    {"+row["rva"]+",{"+",".join("0x"+row["prefix"][i:i+2] for i in range(0,32,2))+"}}, // "+name]
        lines += ["    {"+",".join(hex(value["fields"][name]["offset"]) for name in fields)+"},"]
        graph=value["native_graph"]
        lines += ["    {\""+graph["engine_sha256"]+"\","]
        for name in("mode_icall","mode_dispatch","graph_validate","mode_setter"):
            row=graph["methods"][name]
            lines += ["        {"+row["rva"]+",{"+",".join("0x"+row["prefix"][i:i+2]for i in range(0,32,2))+"}}, // "+name]
        lines += ["        "+hex(graph["node_graph"])+","+hex(graph["graph_mode"])+"},"]
        output=value["native_output_weight"]
        lines += ["    {\""+output["engine_sha256"]+"\","]
        for name in("icall","dispatch","validate","setter"):
            row=output["methods"][name]
            lines += ["        {"+row["rva"]+",{"+",".join("0x"+row["prefix"][i:i+2]for i in range(0,32,2))+"}},"]
        lines += ["        "+str(output["slot_output"])+","+str(output["weight"])+"}","};"]
    for platform,value in profiles.items():
        for index,schema in enumerate(value["presentation_schemas"]):
            lines += ["inline constexpr ActorPresentationField "+platform+"_presentation_fields_"+str(index)+"[]={"]
            lines += ["    {"+str(f["offset"])+","+str(f["bytes"])+","+("true" if f["kind"]=="identity" else "false")+"}, // "+f["name"] for f in schema["fields"]]
            lines += ["};"]
        lines += ["inline constexpr ActorPresentationSchema "+platform+"_presentation_schemas[]={"]
        for index,schema in enumerate(value["presentation_schemas"]):
            row=schema["class"]
            lines += ["    {\""+schema["type"]+"\",{"+row["rva"]+",{"+",".join("0x"+row["prefix"][i:i+2]for i in range(0,32,2))+"}},"+platform+"_presentation_fields_"+str(index)+","+str(len(schema["fields"]))+"},"]
        lines += ["};"]
    for platform,value in profiles.items():
        def ranges(name,rows):
            if not rows:return "nullptr",0
            lines.append("inline constexpr ActorValueRange "+name+"[]={"+",".join("{"+str(r["offset"])+","+str(r["bytes"])+"}"for r in rows)+"};")
            return name,len(rows)
        roots=[]
        for index,row in enumerate(value["common_jobs"]):
            stem=platform+"_fixed_job_"+str(index);containers=[]
            for ci,container in enumerate(row["containers"]):
                cache,count=ranges(stem+"_container_"+str(ci)+"_caches",container["caches"])
                containers.append("{"+",".join(str(container[k])for k in("offset","component_offset","stride"))+","+("true"if container["list"]else"false")+","+cache+","+str(count)+"}")
            if containers:lines.append("inline constexpr ActorFixedContainer "+stem+"_containers[]={"+",".join(containers)+"};")
            cache,ncache=ranges(stem+"_caches",row["caches"]);scratch,nscratch=ranges(stem+"_scratch",row["scratch"]);history,nhistory=ranges(stem+"_history",row["history"])
            binding=lambda b:"{"+b["rva"]+",{"+",".join("0x"+b["prefix"][i:i+2]for i in range(0,32,2))+"}}"
            roots.append("{\""+row["type"]+"\",\""+row["component_type"]+"\","+binding(row["job_type"])+","+binding(row["component_class"])+","+str(row["bytes"])+","+str(row["playable_offset"])+","+(stem+"_containers"if containers else"nullptr")+","+str(len(containers))+","+cache+","+str(ncache)+","+scratch+","+str(nscratch)+","+history+","+str(nhistory)+"}")
        lines.append("inline constexpr ActorFixedJobSchema "+platform+"_fixed_job_schemas[]={"+",\n".join(roots)+"};")
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
