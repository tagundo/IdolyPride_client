"""Portable malformed-input and byte-preservation checks; no Apple/device claim."""
from pathlib import Path
import copy
import hashlib
import io
import json
import plistlib
import struct
import sys
import tarfile
from zipfile import ZipFile, ZipInfo
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'ios-unified'))
import packaging_common as common
import prepare_runtime as runtime
import package_unified as package


def sha(raw): return hashlib.sha256(raw).hexdigest()

def native(platform=2,cpu=common.ARM64,name='Python',dependencies=(),signed=True):
    def dylib(command,path):
        raw=path.encode()+b'\0'; size=(24+len(raw)+7)&~7
        return (struct.pack('<6I',command,size,24,0,0,0)+raw).ljust(size,b'\0')
    build=struct.pack('<6I',0x32,24,platform,13<<16,17<<16,0)
    identity=dylib(0xD,'@rpath/'+name+'.framework/'+name)
    segment=bytearray(152);struct.pack_into('<II',segment,0,0x19,152);segment[8:14]=b'__TEXT';struct.pack_into('<QQ',segment,40,0,4096);struct.pack_into('<I',segment,64,1);struct.pack_into('<Q',segment,72+40,64);struct.pack_into('<I',segment,72+48,1024)
    commands=[build,identity,bytes(segment)]+[dylib(0xC,d) for d in dependencies]
    if signed: commands.append(struct.pack('<4I',0x1D,16,2048,32))
    body=b''.join(commands); result=bytearray(4096);struct.pack_into('<8I',result,0,0xFEEDFACF,cpu,0,6,len(commands),len(body),0,0);result[32:32+len(body)]=body;result[1024:1088]=b'C'*64
    if signed: result[2048:2080]=b'S'*32
    return bytes(result)

def framework(root,name,target='device',signed=True,dependencies=()):
    path=root/(name+'.framework');path.mkdir(parents=True)
    raw=native(2 if target=='device' else 7,name=name,signed=signed,dependencies=dependencies)
    (path/name).write_bytes(raw);(path/name).chmod(0o755)
    (path/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':name,'CFBundlePackageType':'FMWK','CFBundleSupportedPlatforms':['iPhoneOS' if target=='device' else 'iPhoneSimulator']}))
    return path

def patched(raw):
    result=bytearray(raw);count,size=struct.unpack_from('<II',raw,16);value=package.LOAD_PATH.encode()+b'\0';length=(24+len(value)+7)&~7;command=(struct.pack('<6I',0xC,length,24,0,0,0)+value).ljust(length,b'\0');result[32+size:32+size+length]=command;struct.pack_into('<II',result,16,count+1,size+length);return bytes(result)

@pytest.mark.parametrize('name',['../a','/a','a/../b','a\\b','a//b','a/./b','a\0b'])
def test_unsafe_paths_fail(name):
    with pytest.raises(ValueError): common.safe_name(name)

@pytest.mark.parametrize('platform,target',[(1,'device'),(7,'device'),(2,'simulator'),(6,'simulator')])
def test_wrong_actual_macho_platform_fails(tmp_path,platform,target):
    p=tmp_path/'binary';p.write_bytes(native(platform))
    with pytest.raises(ValueError): common.audit_macho(p,target)

def test_fat_single_arm64_device_and_wrong_cpu(tmp_path):
    body=native();offset=4096;raw=struct.pack('>7I',0xCAFEBABE,1,common.ARM64,0,offset,len(body),12).ljust(offset,b'\0')+body;p=tmp_path/'Python';p.write_bytes(raw)
    assert common.audit_macho(p,'device')['slices'][0]['architecture']=='arm64'
    p.write_bytes(native(cpu=common.X86_64))
    with pytest.raises(ValueError):common.audit_macho(p,'device')

def test_framework_dependency_and_metadata_admission(tmp_path):
    framework(tmp_path,'Python');bad=framework(tmp_path,'_ssl',dependencies=['@rpath/libcrypto.dylib'])
    with pytest.raises(ValueError):common.audit_frameworks(tmp_path,'device')
    (bad/'_ssl').write_bytes(native(name='_ssl',dependencies=['@rpath/Python.framework/Python']))
    assert set(common.audit_frameworks(tmp_path,'device'))=={'Python','_ssl'}
    (bad/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'wrong'}))
    with pytest.raises(ValueError):common.audit_frameworks(tmp_path,'device')

def test_missing_signature_and_truncated_commands(tmp_path):
    p=tmp_path/'b';p.write_bytes(native(signed=False))
    with pytest.raises(ValueError):common.audit_macho(p,'device',require_signature=True)
    p.write_bytes(native()[:40])
    with pytest.raises(ValueError):common.audit_macho(p,'device')

@pytest.mark.parametrize('variant,target',[('simulator','device'),('','simulator')])
def test_xcframework_slice_never_falls_back(variant,target):
    info={'AvailableLibraries':[{'LibraryIdentifier':'wrong','LibraryPath':'Python.framework','BinaryPath':'Python.framework/Python','SupportedPlatform':'ios','SupportedPlatformVariant':variant,'SupportedArchitectures':['arm64']}]}
    with pytest.raises(ValueError):runtime.select_library(info,target)

def test_tar_traversal_and_selected_link_rejected():
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as t:
        info=tarfile.TarInfo('../private.db');info.size=1;t.addfile(info,io.BytesIO(b'x'))
    with tarfile.open(fileobj=io.BytesIO(raw.getvalue())) as t:
        with pytest.raises(ValueError):runtime.tar_inventory(t)

def test_runtime_source_closure_is_explicit_and_rejects_grpc(tmp_path):
    src=tmp_path/'src/idoly_local';src.mkdir(parents=True);(src/'__init__.py').write_text('');(src/'ios_host.py').write_text('from . import app_runtime\n');(src/'app_runtime.py').write_text('import grpc\n')
    with pytest.raises(ValueError,match='grpcio'):runtime.runtime_sources(tmp_path,['idoly_local.ios_host'])
    (src/'app_runtime.py').write_text('from . import cli\n');(src/'cli.py').write_text('')
    with pytest.raises(ValueError,match='Developer'):runtime.runtime_sources(tmp_path,['idoly_local.ios_host'])

def test_real_core_closure_matches_manifest_without_developer_tools():
    repo=Path(__file__).resolve().parents[1];manifest=json.loads((repo/'ios-unified/runtime_inputs.json').read_text());actual=runtime.runtime_sources(repo,manifest['project_roots'])
    assert set(actual)==set(manifest['project_modules'])
    assert 'idoly_local.dream_capture' in actual and not {'idoly_local.cli','idoly_local.server','idoly_local.ios_patch'}&actual.keys()

def test_unity_patch_all_other_bytes_preserved(tmp_path):
    original=native(name='UnityFramework');p=tmp_path/'patched';p.write_bytes(patched(original));r=package.verify_unity_patch(io.BytesIO(original),p,sha(original));assert r['all_other_Unity_bytes_equal'] and not r['code_moved']
    changed=bytearray(p.read_bytes());changed[1024]^=1;p.write_bytes(changed)
    with pytest.raises(ValueError,match='changed code'):package.verify_unity_patch(io.BytesIO(original),p,sha(original))

def test_unity_patch_rejects_nonzero_padding_and_wrong_load(tmp_path):
    original=native(name='UnityFramework');p=tmp_path/'patched';p.write_bytes(patched(original));bad=bytearray(original);_,size=struct.unpack_from('<II',bad,16);bad[32+size]=1
    with pytest.raises(ValueError,match='zero padding'):package.verify_unity_patch(io.BytesIO(bad),p,sha(bad))
    p.write_bytes(patched(original).replace(b'IdolyEmbeddedServer.framework',b'XdolyEmbeddedServer.framework'))
    with pytest.raises(ValueError):package.verify_unity_patch(io.BytesIO(original),p,sha(original))


def package_fixture(tmp_path,target='device'):
    root=tmp_path/'runtime';fr=root/'Frameworks';framework(fr,'Python',target);stdlib=root/'python-stdlib';stdlib.mkdir();(stdlib/'os.py').write_text('#pure\n');host=root/'LocalServer/python/idoly_local';host.mkdir(parents=True);(host/'ios_host.py').write_text('#host\n')
    files={str(p.relative_to(root)):{'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())} for p in root.rglob('*') if p.is_file()};report={'target':target,'python_abi':'3.13','protobuf_implementation':'python','frameworks_codesign_verify_passed':True,'files':files,'extension_mappings':{},'frameworks':{'Python':{}}};(root/'runtime-report.json').write_text(json.dumps(report))
    native_root=framework(tmp_path/'native','IdolyEmbeddedServer',target,dependencies=['@rpath/Python.framework/Python'])
    data=tmp_path/'Data.zip';data.write_bytes(b'public-data');trans=tmp_path/'Translations.zip';trans.write_bytes(b'public-translations');web=tmp_path/'web';web.mkdir()
    for name in ['index.html','styles.css','app.js']:(web/name).write_text('local '+name)
    unity=native(name='UnityFramework');main=b'ORIGINAL MAIN';source=tmp_path/'base.ipa'
    with ZipFile(source,'w') as z:
        z.writestr('Payload/Game.app/Info.plist',plistlib.dumps({'CFBundleExecutable':'Main','CFBundleIdentifier':'game.original'}));z.writestr('Payload/Game.app/'+package.UNITY,unity);z.writestr('Payload/Game.app/Main',main);z.writestr('Payload/Game.app/Frameworks/SDK.framework/SDK',b'ORIGINAL SDK')
    replacement=tmp_path/'Unity';replacement.write_bytes(patched(unity));manifest={'inputs':{'base_ipa':{'bytes':source.stat().st_size,'sha256':sha(source.read_bytes())},'original_unity':{'sha256':sha(unity)},'server_data':{'bytes':data.stat().st_size,'sha256':sha(data.read_bytes())},'translations':{'bytes':trans.stat().st_size,'sha256':sha(trans.read_bytes()),'manifest_sha256':'a'*64,'version':'0.3.31'}},'capacity':{'max_runtime_bytes':2*1024**2,'max_archive_entries':8192,'max_ipa_bytes':8*1024**2,'max_expanded_bytes':16*1024**2}}
    return root,native_root,data,trans,source,replacement,manifest,web

def test_full_small_package_preserves_original_main_and_sdk(tmp_path):
    runtime_root,nat,data,trans,source,replacement,manifest,web=package_fixture(tmp_path);out=tmp_path/'unified.ipa';report=package.package(source,replacement,runtime_root,nat,data,trans,out,source_commit='b'*40,manifest=manifest,web_root=web)
    assert report['original_SDK_members_unchanged'] and report['max_stream_chunk_bytes']==65536 and not report['actual_device_or_PlayCover_execution']
    with ZipFile(out) as z:
        assert z.read('Payload/Game.app/Main')==b'ORIGINAL MAIN' and z.read('Payload/Game.app/Frameworks/SDK.framework/SDK')==b'ORIGINAL SDK'
        metadata=plistlib.loads(z.read('Payload/Game.app/Info.plist')); assert metadata['UIFileSharingEnabled'] is True and metadata['CFBundleVersion']=='156.9107' and metadata['CFBundleDisplayName']=='아이프라 로컬' and metadata['CFBundleIdentifier']=='game.original'
        assert z.read('Payload/Game.app/LocalServer/ServerData.zip')==b'public-data'

def test_simulator_stage_needs_no_game_but_never_device_package(tmp_path):
    root,nat,data,trans,source,replacement,manifest,web=package_fixture(tmp_path,'simulator');prepared=tmp_path/'Prepared.app';package.stage_app(root,nat,data,trans,prepared,manifest=manifest,web_root=web)
    assert (prepared/'LocalServer/ServerData.zip').read_bytes()==b'public-data' and not (prepared/'Main').exists()
    with pytest.raises(ValueError):package.package(source,replacement,root,nat,data,trans,tmp_path/'bad.ipa',source_commit='b'*40,manifest=manifest,web_root=web)

def test_runtime_extra_files_and_broken_fwork_rejected(tmp_path):
    root,nat,data,trans,source,replacement,manifest,web=package_fixture(tmp_path);(root/'private.db').write_bytes(b'never-bundle')
    with pytest.raises(ValueError,match='inventory'):package.runtime_files(root,'device',manifest)
    (root/'private.db').unlink();r=json.loads((root/'runtime-report.json').read_text());r['extension_mappings']={'_socket':{'fwork':'python-stdlib/os.py','origin':'python-stdlib/os.py','binary':'Frameworks/Python.framework/Python'}};(root/'runtime-report.json').write_text(json.dumps(r))
    with pytest.raises(ValueError,match='mapping'):package.runtime_files(root,'device',manifest)

@pytest.mark.parametrize('target',['device','simulator'])
def test_generated_outer_translation_pin_is_consumed_by_actual_runtime_validator(tmp_path,target):
    from idoly_local.bundled_translations import read_translation_metadata
    root,nat,data,trans,source,replacement,manifest,web=package_fixture(tmp_path,target)
    _,generated,_=package.bundle_files(root,nat,data,trans,target,manifest,web)
    path=tmp_path/'bundledTranslations.json';path.write_bytes(generated['LocalServer/bundledTranslations.json'])
    actual=read_translation_metadata(path,platform='ios')
    assert actual=={'schema':1,'platform':'ios','sha256':sha(trans.read_bytes()),'bytes':trans.stat().st_size}


def test_simulator_vendor_plist_corrected_after_real_binary_platform_audit(tmp_path):
    path=framework(tmp_path,'Python',target='simulator');info_path=path/'Info.plist';info=plistlib.loads(info_path.read_bytes());info['CFBundleSupportedPlatforms']=['iPhoneOS'];info_path.write_bytes(plistlib.dumps(info));before=common.sha_file(path/'Python')
    result=runtime.normalize_python_framework_metadata(path,'simulator',{'arm64'})
    assert result['vendor_Simulator_metadata_corrected'] is True
    assert plistlib.loads(info_path.read_bytes())['CFBundleSupportedPlatforms']==['iPhoneSimulator']
    assert common.sha_file(path/'Python')==before
    assert common.audit_frameworks(tmp_path,'simulator')['Python']['slices'][0]['build_version']['platform']==7


@pytest.mark.parametrize('actual_target,requested_target,expected_architectures',[('device','simulator',{'arm64'}),('simulator','simulator',{'x86_64'}),('simulator','device',{'arm64'})])
def test_python_plist_normalization_never_substitutes_for_binary_platform_and_arch(tmp_path,actual_target,requested_target,expected_architectures):
    path=framework(tmp_path,'Python',target=actual_target);info_path=path/'Info.plist';before=info_path.read_bytes()
    with pytest.raises(ValueError):runtime.normalize_python_framework_metadata(path,requested_target,expected_architectures)
    assert info_path.read_bytes()==before


def language_package_fixture(tmp_path, target='device'):
    values = package_fixture(tmp_path, target)
    root,nat,data,trans,source,replacement,manifest,web = values
    base_data = {'Data/sharedassets0.assets': b'common-fonts',
                 'Data/resources.assets': b'Korean UI',
                 'Data/Managed/Metadata/global-metadata.dat': b'Korean metadata'}
    with ZipFile(source,'a') as z:
        for name, raw in base_data.items(): z.writestr('Payload/Game.app/'+name, raw)
    manifest['inputs']['base_ipa'] = {'bytes':source.stat().st_size, 'sha256':sha(source.read_bytes())}
    manifest['inputs']['stock_ipa'] = {'sha256':'a'*64}
    manifest['inputs']['english_ui'] = {'sha256':'b'*64}
    common = {'Data/sharedassets0.assets': {'bytes':len(base_data['Data/sharedassets0.assets']), 'sha256':sha(base_data['Data/sharedassets0.assets'])}}
    overlays = ('Data/resources.assets','Data/Managed/Metadata/global-metadata.dat')
    languages = {'ko':{name:{'bytes':len(base_data[name]), 'sha256':sha(base_data[name]),'source':'base'} for name in overlays}}
    archive_data = {}
    for code in ('ja','en'):
        languages[code] = {}
        for name in overlays:
            raw = (code+':'+name).encode();member=code+'/'+name;archive_data[member]=raw
            languages[code][name]={'bytes':len(raw),'sha256':sha(raw),'source':'archive','member':member}
    language = {'schema':1,'policy':'ios-prebuilt-client-data-v1','bundle_id':'local.idoly.client-data',
                'common':common,'languages':languages,'source':{'stock_ipa_sha256':'a'*64,
                'base_ipa_sha256':manifest['inputs']['base_ipa']['sha256'],'english_ui_sha256':'b'*64}}
    client_zip=tmp_path/'client-languages.zip'
    with ZipFile(client_zip,'w') as z:
        for name, raw in archive_data.items():z.writestr(name,raw)
        z.writestr('manifest.json',json.dumps(language))
    descriptor=tmp_path/'client-languages.json'
    descriptor.write_text(json.dumps({'schema':1,'bytes':client_zip.stat().st_size,'sha256':sha(client_zip.read_bytes())}))
    return values,client_zip,descriptor,language,base_data


def rewrite_language_archive(path, descriptor, replacement):
    with ZipFile(path) as z: contents={i.filename:z.read(i) for i in z.infolist()}
    replacement(contents)
    with ZipFile(path,'w') as z:
        for name,raw in contents.items():z.writestr(name,raw)
    descriptor.write_text(json.dumps({'schema':1,'bytes':path.stat().st_size,'sha256':sha(path.read_bytes())}))


def test_device_package_contains_three_language_data_without_changing_base_data(tmp_path):
    values,client_zip,descriptor,language,base_data=language_package_fixture(tmp_path)
    root,nat,data,trans,source,replacement,manifest,web=values
    out=tmp_path/'unified.ipa'
    report=package.package(source,replacement,root,nat,data,trans,out,source_commit='c'*40,
                           manifest=manifest,web_root=web,client_languages=client_zip,client_languages_metadata=descriptor)
    assert set(report['client_languages']['manifest']['languages'])=={'ja','ko','en'}
    assert report['client_languages']['descriptor']['sha256']==sha(client_zip.read_bytes())
    with ZipFile(out) as z:
        assert z.read('Payload/Game.app/LocalServer/client-languages.zip')==client_zip.read_bytes()
        assert z.read('Payload/Game.app/LocalServer/client-languages.json')==descriptor.read_bytes()
        for name,raw in base_data.items():assert z.read('Payload/Game.app/'+name)==raw
        assert z.read('Payload/Game.app/Main')==b'ORIGINAL MAIN'


def test_simulator_stage_copies_full_data_nonexecutable_and_actual_worker_prepares_english(tmp_path):
    from idoly_local.ios_client_data import prepare_client_data
    values,client_zip,descriptor,language,base_data=language_package_fixture(tmp_path,'simulator')
    root,nat,data,trans,source,replacement,manifest,web=values
    out=tmp_path/'Prepared.app'
    report=package.stage_app(root,nat,data,trans,out,manifest=manifest,web_root=web,base_ipa=source,
                             client_languages=client_zip,client_languages_metadata=descriptor)
    assert report['base_Data']['files']==len(base_data) and report['base_Data']['nonexecutable_data_only'] is True
    assert {str(p.relative_to(out)) for p in (out/'Data').rglob('*') if p.is_file()}==set(base_data)
    for name,raw in base_data.items():
        assert (out/name).read_bytes()==raw and (out/name).stat().st_mode&0o777==0o644
    assert not (out/'Main').exists() and not (out/'Frameworks/SDK.framework/SDK').exists()
    (tmp_path/'state').mkdir()
    prepared=prepare_client_data(out,tmp_path/'state','en')
    result=Path(prepared['bundle_path'])
    assert (result/'Data/resources.assets').read_bytes()==b'en:Data/resources.assets'
    assert (result/'Data/sharedassets0.assets').read_bytes()==b'common-fonts'
    assert (out/'Data/resources.assets').read_bytes()==b'Korean UI'


def test_real_manifest_requires_language_package_and_matching_source_pins(tmp_path):
    values,client_zip,descriptor,language,_=language_package_fixture(tmp_path)
    manifest=values[6]
    with pytest.raises(ValueError,match='package is required'):package.client_language_files(None,None,manifest)
    with pytest.raises(ValueError,match='both required'):package.client_language_files(client_zip,None,manifest)
    manifest['inputs']['stock_ipa']['sha256']='d'*64
    with pytest.raises(ValueError,match='source pin'):package.client_language_files(client_zip,descriptor,manifest)


@pytest.mark.parametrize('mutation',[lambda row:row.update(bytes=True),lambda row:row.update(bytes=1),
    lambda row:row.update(sha256='x'*64),lambda row:row.update(extra='untrusted'),lambda row:row.update(schema=True)])
def test_language_outer_descriptor_is_strict_and_hash_bound(tmp_path,mutation):
    values,client_zip,descriptor,_,_=language_package_fixture(tmp_path)
    row=json.loads(descriptor.read_text());mutation(row);descriptor.write_text(json.dumps(row))
    with pytest.raises(ValueError):package.client_language_files(client_zip,descriptor,values[6])


@pytest.mark.parametrize('extra',['../outside','en/Data/unexpected.assets'])
def test_language_archive_rejects_extra_or_traversing_member(tmp_path,extra):
    values,client_zip,descriptor,_,_=language_package_fixture(tmp_path)
    rewrite_language_archive(client_zip,descriptor,lambda data:data.update({extra:b'not selected'}))
    with pytest.raises(ValueError,match='inventory'):package.client_language_files(client_zip,descriptor,values[6])


def test_language_descriptor_and_baseline_data_cannot_be_symlinks_or_missing(tmp_path):
    values,client_zip,descriptor,_,_=language_package_fixture(tmp_path,'simulator')
    root,nat,data,trans,source,replacement,manifest,web=values
    link=tmp_path/'descriptor-link.json';link.symlink_to(descriptor)
    with pytest.raises(ValueError,match='non-symlink'):package.client_language_files(client_zip,link,manifest)
    with pytest.raises(ValueError,match='requires the pinned base IPA Data'):
        package.stage_app(root,nat,data,trans,tmp_path/'Missing.app',manifest=manifest,web_root=web,
                           client_languages=client_zip,client_languages_metadata=descriptor)


def test_device_language_manifest_common_hash_must_match_original_data(tmp_path):
    values,client_zip,descriptor,_,_=language_package_fixture(tmp_path)
    def wrong_common(contents):
        value=json.loads(contents['manifest.json']);value['common']['Data/sharedassets0.assets']['sha256']='c'*64
        contents['manifest.json']=json.dumps(value).encode()
    rewrite_language_archive(client_zip,descriptor,wrong_common)
    root,nat,data,trans,source,replacement,manifest,web=values
    with pytest.raises(ValueError,match='Base Data SHA'):
        package.package(source,replacement,root,nat,data,trans,tmp_path/'unified.ipa',source_commit='c'*40,
                        manifest=manifest,web_root=web,client_languages=client_zip,client_languages_metadata=descriptor)


def test_language_archive_rejects_executable_data_permission(tmp_path):
    values,client_zip,descriptor,_,_=language_package_fixture(tmp_path)
    with ZipFile(client_zip) as z:contents={i.filename:z.read(i) for i in z.infolist()}
    with ZipFile(client_zip,'w') as z:
        for name,raw in contents.items():
            info=ZipInfo(name);info.external_attr=0o100755<<16 if name.startswith('en/') else 0o100644<<16
            z.writestr(info,raw)
    descriptor.write_text(json.dumps({'schema':1,'bytes':client_zip.stat().st_size,'sha256':sha(client_zip.read_bytes())}))
    with pytest.raises(ValueError,match='nonexecutable data'):package.client_language_files(client_zip,descriptor,values[6])


def test_all_language_resource_verifier_reconstructs_and_reuses_each_variant(tmp_path):
    import importlib.util
    tool=Path(__file__).resolve().parents[1]/'ios-unified/verify_client_languages.py'
    spec=importlib.util.spec_from_file_location('client_language_verifier_test',tool)
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    values,client_zip,descriptor,language,base_data=language_package_fixture(tmp_path,'simulator')
    root,nat,data,trans,source,replacement,manifest,web=values
    out=tmp_path/'Prepared.app'
    package.stage_app(root,nat,data,trans,out,manifest=manifest,web_root=web,base_ipa=source,
                      client_languages=client_zip,client_languages_metadata=descriptor)
    report=verifier.verify(out,tmp_path/'verification',expected_sources=language['source'])
    assert report['status']=='PASS' and report['Unity_executed'] is False
    assert [r['language'] for r in report['languages']]==['ja','ko','en']
    assert all(r['files']==3 and r['second_reused'] is True for r in report['languages'])
    assert str(tmp_path) not in json.dumps(report)
    assert all((out/name).read_bytes()==raw for name,raw in base_data.items())
    with pytest.raises(ValueError,match='Fresh absolute'):
        verifier.verify(out,tmp_path/'verification',expected_sources=language['source'])
