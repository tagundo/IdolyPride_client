#!/usr/bin/env python3
"""Pin original typed output traversal helpers; no output closure is inferred."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original
from audit_mp4_actor_state import PINS
from audit_mp4_world import whole
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN

ROOT=Path(__file__).resolve().parents[1]
SELECT={
    'graph_count':('UnityEngine.Playables.PlayableGraph','GetPlayableCount_Injected',1),
    'source':('UnityEngine.Playables.PlayableOutputHandle','GetSourcePlayable_Injected',2),
}
USERDATA={'android':{'getter':0x7329b4,'converter':0x73c7a4,'converter_bytes':60,'target_got':0x1459da0,'barrier_got':0x1459018,'target_cell':0x14e8840,'barrier_cell':0x14e87e8,'target_export':0x419e268,'barrier_export':0x419e294},'ios':{'getter':0xdc89b0,'converter':0xdd23a8,'converter_bytes':48,'target_got':0,'barrier_got':0,'target_cell':0,'barrier_cell':0,'target_export':0x81ea76c,'barrier_export':0x81ea79c}}
TYPES={'animation':'UnityEngine.Animations.AnimationPlayableOutput','audio':'UnityEngine.Audio.AudioPlayableOutput','script':'UnityEngine.Playables.ScriptPlayableOutput'}


def derive(path):
    result={}
    for platform,cls in [('android',OriginalAndroid),('ios',Original)]:
        metadata=(path/(platform+'-metadata.dat')).read_bytes()
        native=(path/('android-native.so'if platform=='android'else'ios-native.bin')).read_bytes()
        assert (hashlib.sha256(native).hexdigest(),hashlib.sha256(metadata).hexdigest())==PINS[platform]
        original=cls(metadata,native)
        methods={key:original.method(*value)for key,value in SELECT.items()}
        assert methods['graph_count']['static']and methods['graph_count']['return']=='System.Int32'
        assert methods['source']['static']and methods['source']['return']=='System.Void'
        assert [p['type']for p in methods['graph_count']['parameters']]==['UnityEngine.Playables.PlayableGraph&']
        assert [p['type']for p in methods['source']['parameters']]==['UnityEngine.Playables.PlayableOutputHandle&','UnityEngine.Playables.PlayableHandle&']
        types={}
        for key,name in TYPES.items():
            tid=original.type_id(name);index=original.types[tid][1][2]
            address=original.qword(original.type_table+index*8);offset=original.offset(address)
            assert original.type_name(index)==name
            kind=(struct.unpack_from('<I',native,offset+8)[0]>>16)&255
            assert kind==17
            types[key]={'name':name,'rva':hex(address),'prefix':native[offset:offset+16].hex(),'kind':kind,'definition':tid}
        layouts={name:original.struct_layout(name)for name in ('UnityEngine.Playables.PlayableGraph','UnityEngine.Playables.PlayableHandle','UnityEngine.Playables.PlayableOutputHandle')}
        for value in layouts.values():assert value['size_table_instance_bytes']==32 and value['size_table_native_bytes']==16
        _,engine,offset=whole(path,platform);pins=USERDATA[platform];md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
        def raw(at,size):return engine[offset(at):offset(at)+size]
        getter=raw(pins['getter'],44);instructions=list(md.disasm(getter,pins['getter']))
        ops=[i.mnemonic+' '+i.op_str for i in instructions]
        assert ops[0]=='ldr x8, [x0, #0x50]'and ops[2]=='ldr w9, [x0, #0x58]'and ops[3]=='cmp w9, #2'
        assert 'ldr x0, [x0, #0x60]'in ops and ops[-1]=='b #'+hex(pins['converter'])
        converter=raw(pins['converter'],pins['converter_bytes']);converted=[i.mnemonic+' '+i.op_str for i in md.disasm(converter,pins['converter'])]
        assert converted[-1]=='ret '
        if platform=='android':
            assert converted.count('blr x8')==2
            assert 'mov x2, x0'in converted and'add x1, sp, #8'in converted and'mov x0, xzr'in converted
            # Exact original GOT values point to initialized native bridge cells.
            image=__import__('extract_client_schema').ClientImage(metadata,engine)
            assert image.read_pointer(pins['target_got'])==pins['target_cell']
            assert image.read_pointer(pins['barrier_got'])==pins['barrier_cell']
        else:
            assert any(i=='bl #'+hex(pins['target_export'])for i in converted)
            assert any(i=='bl #'+hex(pins['barrier_export'])for i in converted)
        native_userdata={'engine_sha256':hashlib.sha256(engine).hexdigest(),**pins,'getter_prefix':getter[:16].hex(),'getter_body':getter.hex(),'converter_prefix':converter[:16].hex(),'converter_body':converter.hex(),
            'target_prefix':native[original.offset(pins['target_export']):original.offset(pins['target_export'])+16].hex(),
            'barrier_prefix':native[original.offset(pins['barrier_export']):original.offset(pins['barrier_export'])+16].hex()}
        assert native_userdata['target_prefix']and native_userdata['barrier_prefix']
        result[platform]={'native_userdata':native_userdata,'native_sha256' :PINS[platform][0],'metadata_sha256':PINS[platform][1],'methods':methods,'types':types,'layouts':layouts}
    return result


def render(data):
    lines=['// Original typed output helpers generated by tools/audit_mp4_output_state.py.',
           'struct Mp4OutputHostPins {const char* native_sha256;const char* metadata_sha256;mp4game::Binding graph_count,source;mp4world::TypeBinding animation,audio,script;};',
           'struct Mp4OutputUserDataPins {const char* engine_sha256;mp4game::Binding getter,converter,target,barrier;uintptr_t target_got,barrier_got,target_cell,barrier_cell;};']
    def binding(value):return '{'+value['rva']+',{'+','.join('0x'+value['prefix'][i:i+2]for i in range(0,32,2))+'}}'
    for platform,value in data.items():
        fields=[json.dumps(value['native_sha256']),json.dumps(value['metadata_sha256'])]
        fields.extend(binding(value['methods'][key])for key in SELECT)
        fields.extend('{'+value['types'][key]['rva']+',{'+','.join('0x'+value['types'][key]['prefix'][i:i+2]for i in range(0,32,2))+'},17,'+str(value['types'][key]['definition'])+'}'for key in TYPES)
        lines.append('[[maybe_unused]] inline constexpr Mp4OutputHostPins '+platform+'_output_host_pins={'+','.join(fields)+'};')
        native=value['native_userdata'];fields=[json.dumps(native['engine_sha256'])]
        for method,prefix in [('getter','getter_prefix'),('converter','converter_prefix'),('target_export','target_prefix'),('barrier_export','barrier_prefix')]:
            fields.append('{'+hex(native[method])+',{'+','.join('0x'+native[prefix][i:i+2]for i in range(0,32,2))+'}}')
        fields.extend(hex(native[k])for k in ('target_got','barrier_got','target_cell','barrier_cell'))
        lines.append('[[maybe_unused]] inline constexpr Mp4OutputUserDataPins '+platform+'_output_userdata_pins={'+','.join(fields)+'};')
    lines+=['#ifdef IDOLY_DARWIN_BRIDGE','constexpr const auto& mp4_output_pins=ios_output_host_pins;','constexpr const auto& mp4_output_userdata_pins=ios_output_userdata_pins;','#else','constexpr const auto& mp4_output_pins=android_output_host_pins;','constexpr const auto& mp4_output_userdata_pins=android_output_userdata_pins;','#endif']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--originals',type=Path,required=True);parser.add_argument('--apply',action='store_true');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();data=derive(args.originals);generated=render(data)
    bridge=ROOT/'client-presentation/native/bridge.cpp';text=bridge.read_text()
    begin='// BEGIN_MP4_OUTPUT_HOST_PINS';end='// END_MP4_OUTPUT_HOST_PINS'
    if args.apply:
        if begin in text:
            start=text.index(begin);finish=text.index(end,start)+len(end);text=text[:start]+begin+'\n'+generated+end+text[finish:]
        else:
            marker='// BEGIN_MP4_WORLD_DIRECTOR_REGISTRY_HOST';text=text.replace(marker,begin+'\n'+generated+end+'\n'+marker,1)
        bridge.write_text(text)
    else:assert text.split(begin,1)[1].split(end,1)[0].strip()==generated.strip()
    args.output.write_text(json.dumps(data,indent=2)+'\n')

if __name__=='__main__':main()
