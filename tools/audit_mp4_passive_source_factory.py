#!/usr/bin/env python3
"""Lock passive source factory selectors, real virtual dispatch and early VM ABI.

Uses whole-verified external originals; no install, scene ownership or engine
execution is implied. Optional ARM execution covers only the real dispatch block.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from audit_mp4_world import whole
from audit_mp4_bootstrap_hooks import source_pins

ROOT=Path(__file__).resolve().parents[1]


def source_contract(text,platform):
    match=re.search(r'SourcePins '+platform+r'_birth_pins=\{(.*?)\};',text,re.S)
    if not match:raise ValueError('Missing actual source Birth pins')
    parts=[int(x,0) for x in re.findall(r'0x[0-9a-fA-F]+|\b\d+\b',match.group(1))]
    if len(parts)!=5+16+8+16+4+4:raise ValueError('Unexpected finite source contract')
    rows=re.findall(r'\{(0x[0-9a-fA-F]+),\{([^{}]+)\}\}',text.split('mp4_shader_lineage_'+platform+'={',1)[1].split(';',1)[0])
    if len(rows)!=7:raise ValueError('Expected seven finite Shader/early VM source bindings')
    early=[(int(r,0),bytes(int(v,0) for v in data.split(','))) for r,data in rows[-2:]]
    factory=source_pins(text,platform+'_bootstrap_pins')[-1]
    return {'factory':parts[0],'return':parts[1],'factory16':bytes(parts[5:21]),'caller8':bytes(parts[21:29]),'early':early,'factory24':factory}


def audit(originals:Path,bridge:Path|None=None):
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
    text=(bridge or ROOT/'client-presentation/native/bridge.cpp').read_text()
    checked={'methods':0,'dispatch_blocks':0,'layouts':0}
    for platform in ('android','ios'):
        original,_,_=whole(originals,platform)
        pins=source_contract(text,platform)
        selections=(
            ('UnityEngine.Timeline.TimelineAsset','CreatePlayable',2,False,'UnityEngine.Playables.Playable'),
            ('UnityEngine.Playables.PlayableAsset','Internal_CreatePlayable',4,True,'System.Void'),
            ('UnityEngine.Object','GetInstanceID',0,False,'System.Int32'),
            ('UnityEngine.Object','CurrentThreadIsMainThread',0,True,'System.Boolean'),
        )
        methods=[original.method(klass,name,count) for klass,name,count,_,_ in selections]
        for method,(_,_,_,static,ret) in zip(methods,selections,strict=True):
            if method['static']!=static or method['return']!=ret:raise ValueError('Exact source managed ABI changed')
            checked['methods']+=1
        if tuple(p['type'] for p in methods[0]['parameters'])!=('UnityEngine.Playables.PlayableGraph','UnityEngine.GameObject'):
            raise ValueError('Timeline factory ABI changed')
        if tuple(p['type'] for p in methods[1]['parameters'])!=('UnityEngine.Playables.PlayableAsset','UnityEngine.Playables.PlayableGraph','UnityEngine.GameObject','System.IntPtr'):
            raise ValueError('Internal factory ABI changed')
        rva=int(methods[0]['rva'],16)
        if pins['factory']!=rva or pins['factory24'][:3]!=('factory','game',rva):raise ValueError('Source factory selector changed')
        at=original.offset(rva)
        if original.b[at:at+24]!=pins['factory24'][3] or original.b[at:at+16]!=pins['factory16']:raise ValueError('Whole-original source prologue changed')
        for method,(rva,data) in zip(methods[2:],pins['early'],strict=True):
            at=original.offset(rva)
            if int(method['rva'],16)!=rva or original.b[at:at+16]!=data:raise ValueError('Early VM source service changed')
        ret=pins['return']
        if ret<=int(methods[1]['rva'],16) or ret-int(methods[1]['rva'],16)>0x200:raise ValueError('Caller is outside exact Internal factory body')
        at=original.offset(ret-8)
        if original.b[at:at+8]!=pins['caller8']:raise ValueError('Actual virtual caller changed')
        instructions=list(Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(original.b[original.offset(ret-32):original.offset(ret+4)],ret-32))
        ops=[(i.mnemonic,i.op_str) for i in instructions]
        required=[('ldr','x8, [x23]'),('mov','x0, x23'),('mov','x1, x22'),('mov','x2, x21'),('ldp','x9, x4, [x8, #0x198]'),('mov','x3, x20'),('blr','x9'),('stp','x0, x1, [x19]')]
        if len(ops)!=9 or not ops[0][0]=='cbz' or sorted(ops[1:])!=sorted(required) or ops[-2:]!=required[-2:]:raise ValueError('Virtual pair/hidden MethodInfo/Graph16/Playable16 source dispatch changed')
        for typ in ('UnityEngine.Playables.PlayableGraph','UnityEngine.Playables.Playable'):
            if original.struct_layout(typ)['bytes']!=16:raise ValueError('Real aggregate ABI changed')
        checked['dispatch_blocks']+=1;checked['layouts']+=1
    return checked


def execute_dispatch(originals:Path,platform:str,variant:int,bridge:Path|None=None):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_PC,UC_ARM64_REG_LR
    import struct
    original,_,_=whole(originals,platform)
    pins=source_contract((bridge or ROOT/'client-presentation/native/bridge.cpp').read_text(),platform)
    ret=pins['return'];start=ret-32
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    page=start&~0xfff;uc.mem_map(page,0x1000)
    uc.mem_write(start,original.b[original.offset(start):original.offset(ret+4)])
    uc.mem_map(0x400000,0x10000)
    asset,klass,method,go,output,fn=0x401000,0x402000,0x403000,0x404000,0x405000,0x406000
    graph=(0x407000+variant*0x100,20+variant*2)
    def put(at,v):uc.mem_write(at,struct.pack('<Q',v))
    put(asset,klass);put(klass+0x198,fn);put(klass+0x1a0,method)
    uc.mem_write(fn,b'\xc0\x03\x5f\xd6')
    for register,value in ((19,output),(20,go),(21,graph[1]),(22,graph[0]),(23,asset)):
        uc.reg_write(UC_ARM64_REG_X0+register,value)
    seen=[]
    def hook(uc,at,size,data):
        if at==fn:
            seen.append(([uc.reg_read(UC_ARM64_REG_X0+i) for i in range(5)],uc.reg_read(UC_ARM64_REG_LR)))
            uc.reg_write(UC_ARM64_REG_X0,0x408000);uc.reg_write(UC_ARM64_REG_X0+1,42)
        if at==ret+4:uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE,hook)
    uc.emu_start(start,ret+4,count=32)
    if seen!=[([asset,graph[0],graph[1],go,method],ret)]:raise ValueError('Actual ARM entry ABI/LR changed')
    if struct.unpack('<QQ',uc.mem_read(output,16))!=(0x408000,42):raise ValueError('Actual ARM aggregate return changed')
    return {'arguments':5,'actual_return_pc':ret,'aggregate_bytes':16}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals',type=Path,required=True)
    parser.add_argument('--bridge',type=Path)
    args=parser.parse_args();print(json.dumps(audit(args.originals,args.bridge),sort_keys=True))

if __name__=='__main__':main()
