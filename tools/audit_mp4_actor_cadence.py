#!/usr/bin/env python3
"""Pin original ActorSwing integration cadence, not just export timestamps.

The selected original solvers do not derive their integration step from the
AnimationStream delta. Their positive prewarm count is a one-shot history path,
not a harmless per-frame delta override. This source proof grants no runtime
owner, job fence, solver rewrite or 120 Hz capability.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from audit_mp4_game import OriginalAndroid
from audit_mp4_ios_game import Original
from audit_mp4_actor_state import BURST_SHA
from extract_client_schema import ClientImage

STEP_BITS=0x3c888f86
STEP=struct.unpack('<f',struct.pack('<I',STEP_BITS))[0]
# Each bounded body window contains the actual default/prewarm selection and
# its origin, not a string/name match against translated or replacement code.
CHECKS={
 'android_managed': {
  'dynamic':{0x426542c:'ldr s8, [x10, #0x970]',0x42658f4:'ldr w21, [x22, #0x328]',
   0x42658f8:'mov v27.16b, v8.16b',0x4265900:'b.lt #0x4265940',
   0x4265910:'fmul s27, s0, s8',0x4265918:'str wzr, [x22, #0x328]',
   0x426591c:'str xzr, [x22, #0xf8]',0x4265920:'str wzr, [x22, #0xf4]',
   0x4265a78:'fmul s18, s27, s18'},
  'breast':{0x4264260:'ldr s15, [x8, #0x970]',0x4264508:'mov w8, #0x8f86',
   0x426450c:'movk w8, #0x3c88, lsl #16',0x4264510:'str w8, [sp, #0x5ac]',
   0x4264514:'ldr w8, [x24, #0x138]',0x4264540:'b.lt #0x4264560',
   0x426454c:'fmul s1, s1, s15',0x4264558:'str wzr, [x24, #0x138]'}},
 'ios_managed': {
  'dynamic':{0x196cf98:'mov w19, #0x8f86',0x196cf9c:'movk w19, #0x3c88, lsl #16',
   0x196d424:'b.lt #0x196d45c',0x196d430:'fmul s12, s0, s1',
   0x196d434:'str wzr, [x22, #0x328]',0x196d438:'str xzr, [x22, #0xf8]',
   0x196d43c:'str wzr, [x22, #0xf4]',0x196d45c:'mov w8, #0x8f86',
   0x196d460:'movk w8, #0x3c88, lsl #16',0x196d464:'fmov s12, w8'},
  'breast':{0x196bbc4:'mov w27, #0x8f86',0x196bbc8:'movk w27, #0x3c88, lsl #16',
   0x196bf90:'str w27, [sp, #0x25c]',0x196bf94:'ldr w23, [x19, #0x138]',
   0x196bf9c:'b.lt #0x196bfbc',0x196bfa8:'fmul s0, s0, s1',
   0x196bfb0:'str wzr, [x19, #0x138]'}},
 'android_burst': {
  'dynamic':{0x39d34:'b.lt #0x39d60',0x39d40:'str wzr, [x26, #0x328]',
   0x39d48:'str xzr, [x26, #0xf8]',0x39d4c:'str wzr, [x26, #0xf4]',
   0x39d50:'fmul s13, s3, s4',0x39d60:'mov w8, #0x8f86',
   0x39d68:'movk w8, #0x3c88, lsl #16',0x39d6c:'fmov s13, w8'},
  'breast':{0x35e40:'str wzr, [x22, #0x138]',0x35e48:'fmul s24, s1, s2',
   0x35e60:'mov w8, #0x8f86',0x35e6c:'movk w8, #0x3c88, lsl #16',
   0x35e74:'fmov s24, w8'}},
 'ios_burst': {
  'dynamic':{0x81cb67c:'str wzr, [x26, #0x328]',0x81cb684:'str xzr, [x26, #0xf8]',
   0x81cb688:'str wzr, [x26, #0xf4]',0x81cb69c:'mov w8, #0x8f86',
   0x81cb6a4:'movk w8, #0x3c88, lsl #16',0x81cb6a8:'fmov s13, w8'},
  'breast':{0x81c77f8:'str wzr, [x22, #0x138]',0x81c7800:'fmul s24, s1, s2',
   0x81c7818:'mov w8, #0x8f86',0x81c7824:'movk w8, #0x3c88, lsl #16',
   0x81c782c:'fmov s24, w8'}}}

def audit(originals):
    p=Path(originals);cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    android=OriginalAndroid((p/'android-metadata.dat').read_bytes(),(p/'android-native.so').read_bytes())
    ios=Original((p/'ios-metadata.dat').read_bytes(),(p/'ios-native.bin').read_bytes())
    burst=(p/'mp4-android-analysis/lib_burst_generated.so').read_bytes()
    assert hashlib.sha256(burst).hexdigest()==BURST_SHA
    burst_image=ClientImage((p/'android-metadata.dat').read_bytes(),burst)
    images={'android_managed':(android.b,android.offset),'ios_managed':(ios.b,ios.offset),
        'android_burst':(burst,burst_image.file_offset),'ios_burst':(ios.b,ios.offset)}
    assert struct.unpack_from('<I',android.b,android.offset(0x1c53970))[0]==STEP_BITS
    output={}
    for kind,solvers in CHECKS.items():
        data,offset=images[kind];output[kind]={'sha256':hashlib.sha256(data).hexdigest(),'solvers':{}}
        for name,expected in solvers.items():
            actual=[]
            for address,op in expected.items():
                raw=data[offset(address):offset(address)+4];instruction=list(cs.disasm(raw,address))
                assert len(instruction)==1
                decoded=instruction[0].mnemonic+' '+instruction[0].op_str
                assert decoded==op,(kind,name,hex(address),decoded,op)
                actual.append({'rva':hex(address),'bytes':raw.hex(),'instruction':decoded})
            output[kind]['solvers'][name]=actual
    return {'schema':1,'fixed_step_bits':hex(STEP_BITS),'fixed_step_seconds':STEP,
        'prewarm_one_half_step_seconds':STEP*.5,'exact_120_step_seconds':1/120,
        'sources':output,'prewarm_is_general_delta_override':False,
        'reason':'Positive count is consumed and dynamic force history is cleared; repeating it changes source history and its half step is not exact 1/120.',
        'runtime_requires':'Exact retained/fenced source job, complete NativeList identity and source-specific cadence admission. Original managed and Burst bodies remain unchanged.',
        'game_executed':False,'runtime_120_verified':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--originals',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    result=audit(args.originals);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print('Pinned original managed/Burst authored solver cadence; no runtime 120 Hz solver capability granted.')

if __name__=='__main__':main()
