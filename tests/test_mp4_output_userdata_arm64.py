"""Execute unchanged native userdata getter/converter, with CAPI fixture roots.

The CAPI fixture models the official GCHandle/getTarget and write-barrier ABI;
these tests do not execute a Unity managed heap or claim a rendered frame.
"""
from pathlib import Path
import json
import struct
import pytest

ROOT=Path(__file__).resolve().parents[1]
PINS=json.loads((ROOT/'tests/mp4_output_userdata_original_fixture.json').read_text())


@pytest.mark.parametrize('platform',['android','ios'])
@pytest.mark.parametrize('case',['null','cached','cached_null','kind0_handle','kind1_handle'])
def test_original_native_userdata_route_preserves_gc_handle_abi_and_source(platform,case):
    u=pytest.importorskip('unicorn')
    from unicorn import arm64_const as r
    pin=PINS[platform];native_base=0x100000000;game_base=native_base if platform=='ios' else 0x200000000
    machine=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
    mapped=set()
    def put(address,data):
        for page in range(address&~4095,(address+len(data)+4095)&~4095,4096):
            if page not in mapped:machine.mem_map(page,4096);mapped.add(page)
        machine.mem_write(address,data)
    getter=native_base+pin['getter'];converter=native_base+pin['converter'];target=game_base+pin['target_export'];barrier=game_base+pin['barrier_export']
    put(getter,bytes.fromhex(pin['getter_body']));put(converter,bytes.fromhex(pin['converter_body']))
    put(target,struct.pack('<I',0xd65f03c0));put(barrier,struct.pack('<I',0xd65f03c0))
    if platform=='android':
        for got,cell,entry in [(pin['target_got'],pin['target_cell'],target),(pin['barrier_got'],pin['barrier_cell'],barrier)]:
            put(native_base+got,struct.pack('<Q',native_base+cell));put(native_base+cell,struct.pack('<Q',entry))
    stack=0x400000000;receiver=0x500000000;stop=0x600000000;result=0x700001234
    put(stack,bytes(8192));put(stop,struct.pack('<I',0xd503201f))
    data=bytearray(0x68);encoded=0 if case=='null'else (0x12345678ffffabcc if case=='kind0_handle'else 0x12345678ffffabcd)
    struct.pack_into('<Q',data,0x50,encoded);struct.pack_into('<I',data,0x58,2 if case.startswith('cached')else (0 if case=='kind0_handle'else 1))
    struct.pack_into('<Q',data,0x60,result if case=='cached'else 0)
    put(receiver,bytes(data));calls=[]
    def api(mu,address,size,_):
        if address==target:
            assert mu.reg_read(r.UC_ARM64_REG_W0)==(encoded&0xffffffff)
            calls.append('target');mu.reg_write(r.UC_ARM64_REG_X0,result);mu.reg_write(r.UC_ARM64_REG_PC,mu.reg_read(r.UC_ARM64_REG_LR))
        elif address==barrier:
            assert mu.reg_read(r.UC_ARM64_REG_X0)==0 and mu.reg_read(r.UC_ARM64_REG_X2)==result
            address=mu.reg_read(r.UC_ARM64_REG_X1);assert stack<=address<stack+8192
            mu.mem_write(address,struct.pack('<Q',result));calls.append('barrier');mu.reg_write(r.UC_ARM64_REG_PC,mu.reg_read(r.UC_ARM64_REG_LR))
    machine.hook_add(u.UC_HOOK_CODE,api)
    machine.reg_write(r.UC_ARM64_REG_SP,stack+4096);machine.reg_write(r.UC_ARM64_REG_LR,stop);machine.reg_write(r.UC_ARM64_REG_X0,receiver)
    machine.emu_start(getter,stop,count=100)
    expected=0 if case in('null','cached_null')else result
    assert machine.reg_read(r.UC_ARM64_REG_X0)==expected
    assert calls==(['target','barrier']if case.endswith('handle')else[])
    assert bytes(machine.mem_read(receiver,len(data)))==bytes(data)
