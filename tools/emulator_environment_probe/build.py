#!/usr/bin/env python3
"""Build a synthetic-only ARM64 CPU/GLES probe without including game code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_STORED

HERE = Path(__file__).resolve().parent
PACKAGE = 'org.idolypride.environmentprobe'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def run(command):
    p = subprocess.run([str(x) for x in command], capture_output=True, text=True, timeout=240)
    if p.returncode:
        raise RuntimeError('build_command_failed: ' + p.stderr[-3000:])
    return p.stdout

def build(output, sdk, ndk, java):
    output = output.resolve()
    if output.exists(): raise ValueError('output_exists')
    tools = sdk / 'build-tools/34.0.0'
    android = sdk / 'platforms/android-34/android.jar'
    llvm = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    manifest = ET.parse(HERE / 'AndroidManifest.xml').getroot()
    if manifest.get('package') != PACKAGE or manifest.findall('uses-permission'):
        raise ValueError('manifest_must_have_no_permissions')
    sources = [HERE/'AndroidManifest.xml', HERE/'probe.c', HERE/'conversion.S', Path(__file__).resolve(), HERE/'src/org/idolypride/environmentprobe/ProbeActivity.java']
    hashes = {str(p.relative_to(HERE)): sha(p) for p in sources}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.environment-probe-', dir=output.parent) as td:
        work = Path(td)
        key = work/'synthetic-public.keystore'
        run([java/'keytool','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','synthetic-probe-public','-keyalg','RSA','-keysize','2048','-validity','36500','-dname','CN=SyntheticEnvironmentProbe'])
        lib = work/'libidoly_environment_probe.so'
        run([llvm/'aarch64-linux-android28-clang','-std=c11','-O2','-fPIC','-shared','-Wall','-Wextra','-Werror',HERE/'probe.c',HERE/'conversion.S','-Wl,-z,max-page-size=16384','-Wl,--build-id=sha1','-lEGL','-lGLESv3','-o',lib])
        data = lib.read_bytes()
        if data[:4] != b'\x7fELF' or struct.unpack_from('<H',data,18)[0] != 183: raise ValueError('not_arm64')
        phoff=struct.unpack_from('<Q',data,32)[0]; ents,count=struct.unpack_from('<HH',data,54)
        aligns=[]
        for i in range(count):
            typ,flags,off,va,pa,fs,ms,align=struct.unpack_from('<II6Q',data,phoff+i*ents)
            if typ==1:
                aligns.append(align)
                if align != 16384: raise ValueError('native_alignment')
        instruction=bytes.fromhex('21b8a15e21d8215e')
        if data.count(instruction) != 1: raise ValueError('exact_fcvtzs_instruction_not_unique')
        classes=work/'classes';dex=work/'dex';classes.mkdir();dex.mkdir()
        run([java/'javac','--release','8','-classpath',android,'-d',classes,sources[-1]])
        run([tools/'d8','--release','--min-api','28','--lib',android,'--output',dex,*sorted(classes.rglob('*.class'))])
        unsigned=work/'unsigned.apk'
        run([tools/'aapt2','link','-o',unsigned,'--manifest',HERE/'AndroidManifest.xml','-I',android])
        provenance={'schema':1,'synthetic_only':True,'game_included':False,'network_permission':False,'runtime_verified':False,'source_sha256':hashes,'native_sha256':sha(lib),'instruction_word':'5ea1b821','instruction_fixture':'FCVTZS S1,S1 then SCVTF S1,S1; inputs 3.75 and -3.75','shader_fixture':'GLES3 live uniform vec4[300] used by every vertex or fragment invocation','ndk_version':ndk.name,'java_target':8}
        with ZipFile(unsigned,'a') as z:
            z.write(lib,'lib/arm64-v8a/libidoly_environment_probe.so',compress_type=ZIP_STORED)
            z.write(dex/'classes.dex','classes.dex',compress_type=ZIP_STORED)
            z.writestr('assets/provenance.json',json.dumps(provenance,sort_keys=True)+'\n')
        aligned=work/'aligned.apk'
        run([tools/'zipalign','-f','16384',unsigned,aligned])
        signed=work/'signed.apk'
        run([tools/'apksigner','sign','--ks',key,'--ks-key-alias','synthetic-probe-public','--ks-pass','pass:android','--key-pass','pass:android','--out',signed,aligned])
        signature=run([tools/'apksigner','verify','--verbose','--print-certs',signed])
        certificate=next(line.split(': ',1)[1] for line in signature.splitlines() if 'certificate SHA-256 digest:' in line)
        run([tools/'zipalign','-c','16384',signed])
        badging=run([tools/'aapt2','dump','badging',signed])
        if "package: name='"+PACKAGE+"'" not in badging or "native-code: 'arm64-v8a'" not in badging or 'uses-permission:' in badging: raise ValueError('bad_apk_inventory')
        with ZipFile(signed) as z:
            libs=[n for n in z.namelist() if n.endswith('.so')]
            if libs != ['lib/arm64-v8a/libidoly_environment_probe.so'] or hashlib.sha256(z.read(libs[0])).hexdigest()!=sha(lib):raise ValueError('native_inventory_changed')
            if json.loads(z.read('assets/provenance.json')) != provenance:raise ValueError('provenance_changed')
        if any(sha(HERE/name)!=expected for name,expected in hashes.items()):raise ValueError('sources_changed_during_build')
        report={**provenance,'package':PACKAGE,'activity':PACKAGE+'.ProbeActivity','report_path':'files/report.json','log_tag':'IdolyEnvironmentProbe','apk_sha256':sha(signed),'apk_bytes':signed.stat().st_size,'certificate_sha256':certificate,'public_throwaway_keystore_sha256':sha(key),'permissions':[],'signature_verified':True,'alignment_bytes':16384,'native_load_alignments':aligns,'build_tools':'34.0.0','android_target':34}
        shutil.copyfile(signed,output)
        (output.with_suffix('.evidence.json')).write_text(json.dumps(report,indent=2)+'\n')
        (output.parent/'SHA256SUMS').write_text(sha(output)+'  '+output.name+'\n'+sha(output.with_suffix('.evidence.json'))+'  '+output.with_suffix('.evidence.json').name+'\n')
        return report

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--output',type=Path,required=True)
    a.add_argument('--sdk',type=Path,help='Android SDK root; defaults to ANDROID_HOME/ANDROID_SDK_ROOT')
    a.add_argument('--ndk',type=Path,help='NDK root; defaults to SDK/ndk/26.3.11579264')
    a.add_argument('--java',type=Path,help='JDK bin directory; defaults to JAVA_HOME/bin or javac on PATH')
    n=a.parse_args()
    sdk=n.sdk or (Path(os.environ['ANDROID_HOME']) if os.environ.get('ANDROID_HOME') else
                  Path(os.environ['ANDROID_SDK_ROOT']) if os.environ.get('ANDROID_SDK_ROOT') else None)
    java=n.java or (Path(os.environ['JAVA_HOME'])/'bin' if os.environ.get('JAVA_HOME') else
                    Path(shutil.which('javac')).parent if shutil.which('javac') else None)
    if sdk is None or java is None:
        a.error('Set --sdk and --java or the corresponding Android SDK/JDK environment variables')
    print(json.dumps(build(n.output,sdk,n.ndk or sdk/'ndk/26.3.11579264',java),indent=2))
