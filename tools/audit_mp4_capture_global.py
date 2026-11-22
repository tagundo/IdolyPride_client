#!/usr/bin/env python3
"""Pin native texture publication and the known setter-bypassing sheet routes.

This is a bounded native-route audit. It intentionally does not certify an
all-writer source closure merely because a managed Shader method was found.
"""
from pathlib import Path
import argparse
import hashlib
import json
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from audit_mp4_world import whole

ROOT=Path(__file__).resolve().parents[1]
PINS={
    'android':{'cell':0x1459088,'indirect':True,'entries':{
        'static_set':0x5e5790,'static_get':0x5e59b4,'core':0x685668,
        'raw_core':0x685890,'publish':0x5f13b8,'property_copy':0x684e08,
        'sheet_copy':0x67906c,'retired_texture':0x6868b0,'global_destroy':0x684a88,'sheet_get':0x686bfc,'get_index':0x6854e8}},
    'ios':{'cell':0xa93c518,'indirect':False,'entries':{
        'static_set':0xc6ee5c,'static_get':0xc6f0b8,'core':0xd108cc,
        'raw_core':0xd10afc,'publish':0xc778ac,'property_copy':0xd10138,
        'sheet_copy':0xd04074,'retired_texture':0xd11b7c,'global_destroy':0xd0feb0,'sheet_get':0xd11dc0,'get_index':0xd1072c}},
}
PUBLICATION={
    'android':{'native_entry':0x45b670,'return':0x923d4e4,'icall_slot':0xa077c20,
        'aot':{'update':(0x923d228,724),'wrapper':(0x9236624,52),'shader_string':(0x8f526c4,112),
            'request':(0x923d4fc,128),'capture_pass':(0x8dfb8bc,352)}},
    'ios':{'native_entry':0xb04424,'return':0x7bcb81c,'icall_slot':0xa91b680,
        'aot':{'update':(0x7bcb2f8,1344),'shader_string':(0x7811830,168),
            'request':(0x7bcb838,120),'capture_pass':(0x76798d8,368)}},
}
ABI={
    'static_set':'void(int32 property, NativeTexture*)',
    'static_get':'NativeTexture*(int32 property)',
    'core':'void(Sheet*, uint32 byteIndex, Key16*, NativeTexture*, uint32 subelement)',
    'raw_core':'void(Sheet*, Key16*, uint32 byteIndex, NativeRenderTexture*, uint32 mip)',
    'publish':'void(Record*, uint32 textureID, uint32 dimension, uint32 subelement, uint32 flags, Key16*)',
    'property_copy':'void(Sheet* destination, Key16*, const Sheet* source)',
    'sheet_copy':'void(Sheet* destination, const Sheet* source)',
    'retired_texture':'void(Sheet*, uint32 textureID)',
    'global_destroy':'void()',
    'sheet_get':'NativeTexture*(Sheet*, int32 property)',
    'get_index':'int32(Sheet*, Key16*, uint32 kind)',
}

def audit(originals):
    cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);out={}
    for platform,pins in PINS.items():
        original,native,offset=whole(originals,platform);entries={}
        for name,address in pins['entries'].items():
            instructions=[]
            # The readonly static helper ends with a tail branch. The raw core's
            # nonnull branch lies AFTER its first ret and jumps back to the common
            # epilogue, so stopping at the first ret would omit a real write path.
            explicit={'android':{'static_get':24,'raw_core':504,'get_index':108},'ios':{'static_get':20,'raw_core':508,'get_index':124}}[platform].get(name)
            for i in cs.disasm(native[offset(address):offset(address)+(explicit or 4096)],address):
                instructions.append(i)
                if explicit is None and i.mnemonic=='ret':break
            assert instructions and (explicit or instructions[-1].mnemonic=='ret'),'native_body_boundary_changed'
            entries[name]={'rva':hex(address),'prefix':native[offset(address):offset(address)+16].hex(),
                'bounded_bytes':sum(len(i.bytes)for i in instructions),
                'body':b''.join(i.bytes for i in instructions).hex(),'abi':ABI[name],
                'instructions':[{'rva':hex(i.address),'op':i.mnemonic+' '+i.op_str}for i in instructions]}
        ops=lambda name:[i['op']for i in entries[name]['instructions']]
        # This CPU publication writes the exact engine TextureID read by the getter.
        assert 'stp w1, w2, [x0]'in ops('publish')
        assert any(i.startswith('stp w21, w8, [x20, #0xc]')for i in ops('publish'))
        assert not any(i.startswith('blr ')for i in ops('publish'))
        assert 'ldr w0, [x9, w8, uxtw]'in ops('sheet_get')
        assert 'b #'+hex(pins['entries']['sheet_get'])in ops('static_get')
        # Unlike publication, these paths do NOT call the publication helper.
        publish=hex(pins['entries']['publish'])
        for name in ('property_copy','sheet_copy','retired_texture'):
            assert 'bl #'+publish not in ops(name)
        assert any(i.startswith('str q0, [x8]')for i in ops('property_copy'))
        assert any(i.startswith('str wzr, [x10]')for i in ops('retired_texture'))
        assert sum(i.startswith('bl ')for i in ops('sheet_copy'))>=3
        out[platform]={'sha256':hashlib.sha256(native).hexdigest(),
            'global_sheet_cell':hex(pins['cell']),'indirect_cell':pins['indirect'],'entries':entries,
            'all_writer_closure':False,
            'remaining_admission':'Prove or guard all bulk reset, sheet reallocation and global-cell replacement routes against the finite actual source program.',
            'normal_api_boundary':'Texture helper GPU behavior remains outside the publication gate. Direct CPU mutation routes require source-pinned bounded bodies.',
            'known_required_routes':['both texture cores','native publication leaf','per-property texture copy',
                'whole sheet copy','retired texture clear','global sheet destruction/replacement']}
        publication=PUBLICATION[platform];aot={}
        for name,(address,length)in publication['aot'].items():
            raw=original.b[original.offset(address):original.offset(address)+length]
            aot[name]={'rva':hex(address),'prefix':raw[:16].hex(),'body':raw.hex(),
                'instructions':[{'rva':hex(i.address),'op':i.mnemonic+' '+i.op_str}for i in cs.disasm(raw,address)]}
        update=original.method('VL.Rendering.VLSRPCameraController','UpdateCapturedTexture',0)
        assert update['rva']==aot['update']['rva']
        def aops(name):return [i['op']for i in aot[name]['instructions']]
        string=aops('shader_string')
        assert string[-1]=='br x2'
        assert any('x30'in i and i.startswith('ldp ')for i in string)
        if platform=='android':
            assert aops('wrapper')[-1]=='b #0x8f526c4'
            assert 'ldr x0, [x19, #0x40]'in aops('wrapper')and 'ldr x1, [x19, #0x10]'in aops('wrapper')
            assert any(i['rva']=='0x923d4e0'and i['op']=='bl #0x9236624'for i in aot['update']['instructions'])
        else:
            assert any(i['rva']=='0x7bcb818'and i['op']=='bl #0x7811830'for i in aot['update']['instructions'])
            assert 'ldr x0, [x20, #0x40]'in aops('update')and 'ldr x1, [x20, #0x10]'in aops('update')
        request=original.method('VL.Rendering.VLSRPCameraController','CaptureRequest',0)
        capture_pass=original.method('VL.Rendering.VLCapturePass','Execute',2)
        blit=original.method('UnityEngine.Rendering.CommandBuffer','Blit',2,
            ('UnityEngine.Rendering.RenderTargetIdentifier','UnityEngine.Rendering.RenderTargetIdentifier'))
        assert request['rva']==aot['request']['rva']and capture_pass['rva']==aot['capture_pass']['rva']
        assert 'bl #'+aot['update']['rva']in aops('request')
        assert 'ldr x8, [x19, #0xa0]'in aops('request')
        assert any(i.startswith('ldur q')and '[x8, #0x18]'in i for i in aops('request'))
        assert any(i.startswith('ldur q')and '[x20, #0x88]'in i for i in aops('capture_pass'))
        assert 'bl #'+blit['rva']in aops('capture_pass')
        entry=publication['native_entry']
        out[platform]['owned_publication']={'entry':{'rva':hex(entry),'prefix':native[offset(entry):offset(entry)+16].hex()},
            'original_return':hex(publication['return']),'icall_slot':hex(publication['icall_slot']),
            'aot_sha256':hashlib.sha256(original.b).hexdigest(),'aot':aot,
            'direct_output_proof':'CaptureRequest copies controller.A0.identifier40 into Capture(target,event1010). CapturePass reads its own target identifier40 and calls the exact CommandBuffer.Blit(source=1,destination=target) overload; no shader-global read is needed to select that destination.',
            'proof':'UpdateCapturedTexture exact BL return is preserved by every intervening managed wrapper tail branch to the native Shader icall. Entry x1 is the managed A0.texture object before native marshalling.',
            'runtime_requires':['actual owned typed CaptureRequest receipt','exact current controller.A0.wrapper and wrapper.texture',
                'private captured wrapper/texture lifetime','exact original x30 and property ID','same authorized request thread',
                'positive selected renderer/capture-pass source consumer closure; no export consumer requires the new shader global']}
    return out

def profile_text(profiles):
    lines=['// BEGIN_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE','namespace idoly_mp4_capture_global_native {',
        'struct Binding {uintptr_t rva;uint8_t prefix[16];};',
        'struct Profile {uintptr_t global_sheet_cell;bool indirect_cell;Binding static_set,static_get,core,raw_core,publish,property_copy,sheet_copy,retired_texture,global_destroy,sheet_get,get_index;};']
    for platform,p in profiles.items():
        lines.append('inline constexpr Profile '+platform+'_profile={'+p['global_sheet_cell']+','+str(p['indirect_cell']).lower()+',')
        for name,row in p['entries'].items():
            prefix=row['prefix'];lines.append(' {'+row['rva']+',{'+','.join('0x'+prefix[i:i+2]for i in range(0,32,2))+'}}, // '+name)
        lines.append('};')
    lines+=['} // namespace idoly_mp4_capture_global_native','// END_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE']
    return '\n'.join(lines)

def publication_text(profiles):
    lines=['// BEGIN_MP4_CAPTURE_PUBLICATION_PROFILE','namespace idoly_mp4_capture_publication {',
        'using Binding=idoly_mp4_capture_global_native::Binding;',
        'struct Profile {Binding native_entry;uintptr_t original_return,icall_slot;Binding update,wrapper,shader_string;};']
    def binding(row):
        if not row:return '{0,{}}'
        return '{'+row['rva']+',{'+','.join(hex(b)for b in bytes.fromhex(row['prefix']))+'}}'
    for platform,p in profiles.items():
        p=p['owned_publication'];aot=p['aot']
        lines.append('inline constexpr Profile '+platform+'_profile={'+binding(p['entry'])+','+p['original_return']+','+p['icall_slot']+','+
            binding(aot['update'])+','+binding(aot.get('wrapper'))+','+binding(aot['shader_string'])+'};')
    lines+=['} // namespace idoly_mp4_capture_publication','// END_MP4_CAPTURE_PUBLICATION_PROFILE']
    return '\n'.join(lines)

def main():
    p=argparse.ArgumentParser();p.add_argument('--originals',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--check-header',action='store_true');args=p.parse_args()
    profiles=audit(args.originals)
    if args.check_header:
        text=(ROOT/'client-presentation/native/mp4_camera_owner.hpp').read_text()
        start=text.index('// BEGIN_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE');end=text.index('// END_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE')+len('// END_MP4_CAPTURE_GLOBAL_NATIVE_PROFILE')
        assert text[start:end]==profile_text(profiles),'native_capture_profile_changed'
        start=text.index('// BEGIN_MP4_CAPTURE_PUBLICATION_PROFILE');end=text.index('// END_MP4_CAPTURE_PUBLICATION_PROFILE')+len('// END_MP4_CAPTURE_PUBLICATION_PROFILE')
        assert text[start:end]==publication_text(profiles),'owned_publication_profile_changed'
    args.out.write_text(json.dumps({'schema':1,'platforms':profiles},indent=2)+'\n')
    print('Pinned native binding routes and exact owned-publication callers; all-writer and shader-consumer admission remain separate.')

if __name__=='__main__':main()
