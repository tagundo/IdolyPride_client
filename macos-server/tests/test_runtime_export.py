import importlib.util
import marshal
from pathlib import Path
import struct
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
