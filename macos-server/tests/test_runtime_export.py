import importlib.util
import marshal
from pathlib import Path
import struct
import stat
import subprocess
import sys
import sysconfig
from zipfile import ZipFile
from zipfile import ZipInfo
import zlib

import pytest

PATH=Path(__file__).parents[1]/"cross/runtime_export.py"
SPEC=importlib.util.spec_from_file_location("runtime_export",PATH)
tool=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(tool)


def pyz(entries):
    raw=bytearray(b"PYZ\0"+importlib.util.MAGIC_NUMBER+b"\0"*4);toc=[]
    for name,kind,code in entries:
        blob=zlib.compress(marshal.dumps(code));toc.append((name,(kind,len(raw),len(blob))));raw.extend(blob)
    struct.pack_into("!I",raw,8,len(raw));raw.extend(marshal.dumps(toc));return bytes(raw)


def test_exports_original_marshal_bytes_and_excludes_old_application():
    code=compile("value=17","old-ci-path.py","exec")
    source=pyz([("dependency",0,code),("somepackage",1,code),("idoly_local.application",0,code),("engine",0,code)])
    result,skipped=tool.pyz_modules(source)
    assert set(result)=={"dependency.pyc","somepackage/__init__.pyc"}
    assert result["dependency.pyc"][:16]==importlib.util.MAGIC_NUMBER+b"\0"*12
    assert result["dependency.pyc"][16:]==marshal.dumps(code)
    assert set(skipped)=={"idoly_local.application","engine"}


def test_rejects_unsafe_or_duplicate_dependency_names():
    code=compile("x=1","public.py","exec")
    for names in (("bad/escape",),("same","same")):
        with pytest.raises(ValueError):tool.pyz_modules(pyz([(name,0,code) for name in names]))


def test_compressed_runtime_objects_are_bounded_and_no_trailing_data():
    assert tool.bounded_zlib(zlib.compress(b"abc"),3)==b"abc"
    with pytest.raises(ValueError):tool.bounded_zlib(zlib.compress(b"abc"),2)
    with pytest.raises(ValueError):tool.bounded_zlib(zlib.compress(b"abc")+b"extra",3)


def test_rejects_missing_archive_cookie():
    with pytest.raises(ValueError):tool.carchive(b"not a frozen engine")


def test_exports_ordinary_carchive_module_and_package_without_reserializing():
    raw=marshal.dumps(compile("value=17","old-runtime.py","exec"))
    entries={"struct":("m",raw),"ordinary.package":("M",raw),
             "pyimod02_importers":("m",raw),"PyInstaller.hook":("M",raw),
             "idoly_local.application":("m",raw),"engine":("s",raw),"pyi_rth_inspect":("s",raw)}
    result,excluded=tool.carchive_modules(entries)
    assert set(result)=={"struct.pyc","ordinary/package/__init__.pyc"}
    assert result["struct.pyc"]==importlib.util.MAGIC_NUMBER+b"\0"*12+raw
    assert set(excluded)=={"pyimod02_importers","PyInstaller.hook","idoly_local.application"}


@pytest.mark.parametrize("name,raw",[("../escape",b""),("ordinary",marshal.dumps({"not":"code"}))])
def test_rejects_unsafe_or_noncode_carchive_modules(name,raw):
    with pytest.raises(ValueError):tool.carchive_modules({name:("m",raw)})


def test_rejects_package_module_output_aliases():
    code=compile("value=1","original.py","exec");raw=marshal.dumps(code)
    with pytest.raises(ValueError,match="output path"):
        tool.carchive_modules({"package":("M",raw),"package.__init__":("m",raw)})
    with pytest.raises(ValueError,match="output path"):
        tool.pyz_modules(pyz([("package",1,code),("package.__init__",0,code)]))


def test_export_runtime_merges_bootstrap_and_reports_original_bytes(tmp_path,monkeypatch):
    code=compile("value=1","original.py","exec");raw=marshal.dumps(code)
    entries={"struct":("m",raw),"pyimod02_importers":("m",raw),"PYZ.pyz":("z",pyz([("dependency",0,code)]))}
    monkeypatch.setattr(tool,"carchive",lambda _:entries)
    source=tmp_path/"runtime.zip"
    with ZipFile(source,"w") as archive:
        archive.writestr(tool.PREFIX+"IdolyServerEngine",b"parser covered by actual-layout test")
        info=ZipInfo(tool.PREFIX+"_internal/datafile");info.external_attr=(stat.S_IFREG|0o644)<<16
        archive.writestr(info,b"preserved")
    report=tool.export_runtime(source,tmp_path/"export")
    assert (tmp_path/"export/_internal/struct.pyc").read_bytes()==importlib.util.MAGIC_NUMBER+b"\0"*12+raw
    assert not (tmp_path/"export/_internal/pyimod02_importers.pyc").exists()
    assert list(report["carchive_module_sha256"])==["struct.pyc"]
    assert report["carchive_modules_excluded"]==["pyimod02_importers"]
    entries["PYZ.pyz"]=("z",pyz([("struct",0,code)]))
    with pytest.raises(ValueError,match="collides with PYZ"):
        tool.export_runtime(source,tmp_path/"collision")


def test_actual_retained_runtime_isolated_engine_import_closure(tmp_path):
    """Portable bytecode/layout proof; native Linux replacements are explicit.

    This does not execute Darwin extensions or claim a Mac/server launch.
    CPython's initial cached source modules are removed and no host stdlib or
    site-packages path is available to hide a missing exported wrapper.
    """
    source=Path("/workspace/shared/artifacts/release-v0.3.0-candidate/assets/IdolyPride-Local-Server-macOS-arm64.app.zip")
    if not source.is_file():pytest.skip("Retained public Mac030 runtime is not available")
    assert sys.version_info[:2]==(3,12)
    internal=tmp_path/"_internal";internal.mkdir()
    with ZipFile(source) as archive:
        entries=tool.carchive(archive.read(tool.PREFIX+"IdolyServerEngine"))
        pyzs=[raw for kind,raw in entries.values() if kind=="z"]
        modules,_=tool.pyz_modules(pyzs[0]);bootstrap,excluded=tool.carchive_modules(entries)
        assert set(bootstrap)=={"struct.pyc"}
        assert set(excluded)=={"pyimod01_archive","pyimod02_importers","pyimod03_ctypes"}
        assert not modules.keys() & bootstrap.keys()
        modules.update(bootstrap)
        base=internal/"base_library.zip";base.write_bytes(archive.read(tool.PREFIX+"_internal/base_library.zip"))
        assert any("/_struct.cpython-312-darwin.so" in name for name in archive.namelist())
    for name,raw in modules.items():
        target=internal/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    fresh=Path(__file__).resolve().parents[1]
    script="""
import sys
sys.path = sys.argv[1:]
for name, module in list(sys.modules.items()):
    if name != '__main__' and getattr(getattr(module, '__spec__', None), 'origin', None) not in ('built-in', 'frozen'):
        del sys.modules[name]
assert 'struct' not in sys.modules and 'zipfile' not in sys.modules
import engine, payload, struct, zipfile, ssl, sqlite3, ctypes, multiprocessing, concurrent.futures, urllib.request, inspect
assert struct.__file__ == sys.path[3] + '/struct.pyc'
assert engine.__file__ == sys.path[0] + '/engine.py'
assert payload.__file__ == sys.path[0] + '/payload.py'
assert struct.pack('>I', 123) == b'\\0\\0\\0{'
print('ISOLATED_ACTUAL_LAYOUT_IMPORT_CLOSURE_PASS')
"""
    command=[sys.executable,"-I","-S","-B","-c",script,str(fresh),str(fresh.parents[0]/"src"),
             str(base),str(internal),sysconfig.get_config_var("DESTSHARED")]
    result=subprocess.run(command,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert "ISOLATED_ACTUAL_LAYOUT_IMPORT_CLOSURE_PASS" in result.stdout
    # Same process isolation must reproduce the reported failure if the newly
    # required CArchive wrapper is omitted, despite a full host Python install.
    (internal/"struct.pyc").unlink()
    result=subprocess.run(command,capture_output=True,text=True,timeout=20)
    assert result.returncode!=0 and "No module named 'struct'" in result.stderr,result.stderr
