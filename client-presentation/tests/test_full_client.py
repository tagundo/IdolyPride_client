"""Tiny pure checks for normal-update packaging, without SDK/JVM/key/device."""
import hashlib
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZipInfo

import pytest

PATH=Path(__file__).resolve().parents[1]/"build_full_client.py"
SPEC=importlib.util.spec_from_file_location("presentation_full_client",PATH)
tool=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(tool)


def test_provider_addition_preserves_original_flags_components_and_identity(tmp_path):
    p=tmp_path/"AndroidManifest.xml"
    p.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="'+tool.PACKAGE+'" android:versionCode="414"><uses-sdk android:minSdkVersion="28" android:targetSdkVersion="36"/><uses-permission android:name="android.permission.INTERNET"/><application android:debuggable="false" android:extractNativeLibs="true" android:name="OriginalApplication"><activity android:name="OriginalActivity" android:exported="true"/></application></manifest>')
    original=tool.xml_shape(ET.parse(p).getroot());tool.add_provider(p)
    root=ET.parse(p).getroot();app=root.find('application');provider=app[-1]
    assert provider.attrib=={tool.ANDROID+'name':tool.PROVIDER,tool.ANDROID+'authorities':tool.AUTHORITY,tool.ANDROID+'exported':'false',tool.ANDROID+'initOrder':'1'}
    app.remove(provider);assert tool.xml_shape(root)==original
    with pytest.raises(ValueError,match='already'):tool.add_provider(p)


def test_provider_addition_rejects_other_package_without_writes(tmp_path):
    p=tmp_path/'AndroidManifest.xml';p.write_text('<manifest package="another.app"><application/></manifest>');before=p.read_bytes()
    with pytest.raises(ValueError):tool.add_provider(p)
    assert p.read_bytes()==before


def test_next_dex_keeps_all_five_existing_diagnostic_dexes():
    assert tool.next_dex({'classes.dex','classes2.dex','classes3.dex','classes4.dex','classes5.dex'})=='classes6.dex'
    with pytest.raises(ValueError):tool.next_dex({'classes2.dex'})


def test_stream_copies_original_member_bytes_and_zero_attributes(tmp_path):
    source,target=tmp_path/'base.apk',tmp_path/'output.apk'
    with ZipFile(source,'w') as z:
        z.writestr('AndroidManifest.xml',b'old manifest')
        i=ZipInfo('classes.dex');z.writestr(i,b'original SDK');z.getinfo(i.filename).external_attr=0
        z.writestr('assets/bin/Data/unity_app_guid',b'original GUID')
    additions={'classes6.dex':b'own DEX',tool.MARKER:json.dumps(tool.marker()).encode()}
    tool.stream_apk(source,target,b'new manifest',additions)
    with ZipFile(target) as z:
        assert z.read('classes.dex')==b'original SDK' and z.getinfo('classes.dex').external_attr==0
        assert z.read('assets/bin/Data/unity_app_guid')==b'original GUID'
        assert z.read('AndroidManifest.xml')==b'new manifest' and z.read('classes6.dex')==b'own DEX'


def test_public_cache_preserves_bytes_modes_times_and_rejects_links(tmp_path):
    source=tmp_path/'public';source.write_bytes(b'public input');source.chmod(0o600);before=source.stat()
    cache=tool.PublicCache();expected=hashlib.sha256(source.read_bytes()).hexdigest();cache.register(source,expected)
    after=source.stat();assert (after.st_mode,after.st_size,after.st_mtime_ns,after.st_ctime_ns)==(before.st_mode,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
    link=tmp_path/'link';link.symlink_to(source)
    with pytest.raises(ValueError):cache.register(link,expected)
    with pytest.raises(ValueError):cache.register(source,'0'*64)
    with pytest.raises(ValueError):cache.register(source,None,own=True)


def test_compiled_tree_compares_typed_attributes_not_source_lines():
    old='  E: manifest (line=1)\n    A: package="'+tool.PACKAGE+'"\n    E: application (line=2)\n      A: http://schemas.android.com/apk/res/android:debuggable(0x1)=false\n'
    provider='      E: provider (line=3)\n        A: http://schemas.android.com/apk/res/android:name(0x1)="'+tool.PROVIDER+'"\n        A: http://schemas.android.com/apk/res/android:authorities(0x2)="'+tool.AUTHORITY+'"\n        A: http://schemas.android.com/apk/res/android:exported(0x3)=false\n        A: http://schemas.android.com/apk/res/android:initOrder(0x4)=1\n'
    assert tool.compiled_tree(old)==tool.compiled_tree(old.replace('line=1','line=99')+provider,remove_provider=True)
    assert tool.compiled_tree(old)!=tool.compiled_tree(old.replace('=false','=true'))
    with pytest.raises(ValueError):tool.compiled_tree(old+provider.replace('exported(0x3)=false','exported(0x3)=true'),remove_provider=True)


def test_standalone_marker_has_only_public_compatibility_fields():
    assert tool.marker()=={'schema':1,'bridge_version':1,'target_package':tool.PACKAGE,'base_version_code':414,'native_library_sha256':tool.NATIVE_SHA256}


def test_dual_signature_output_verification_includes_v2_sdk_range_only_for_verifier():
    command=tool.output_verify_command(['java','-jar','apksigner.jar'],Path('output.apk'))
    assert command==['java','-jar','apksigner.jar','verify','--verbose','--print-certs','--min-sdk-version','24',Path('output.apk')]
    assert 'sign' not in command and 'AndroidManifest.xml' not in command
