"""Reuse audited Darwin Python binaries; export PYZ bytecode without recompiling it."""
from __future__ import annotations
import hashlib
import importlib.util
import marshal
from pathlib import Path, PurePosixPath
import stat
import struct
import sys
from zipfile import ZipFile
import zlib

PREFIX="IdolyPrideLocalServer.app/Contents/Resources/runtime/"
MAX_MEMBER=32*1024*1024


def bounded_zlib(raw,maximum):
    obj=zlib.decompressobj();result=obj.decompress(raw,maximum+1)
    if len(result)>maximum or obj.unconsumed_tail or not obj.eof or obj.unused_data:
        raise ValueError("Compressed runtime object exceeds its boundary")
    return result


def carchive(raw):
    pos=raw.rfind(b"MEI\014\013\012\013\016")
    if pos<0 or pos+88>len(raw):raise ValueError("Missing frozen Python archive")
    _,size,toff,tlen,version,_=struct.unpack_from("!8sIIII64s",raw,pos)
    base=pos+88-size
    if version!=312 or not 0<=base<=pos or not 0<=toff<=size or base+toff+tlen>pos:
        raise ValueError("Frozen Python archive bounds/version differ")
    toc=raw[base+toff:base+toff+tlen];at=0;entries={}
    while at<len(toc):
        if at+18>len(toc):raise ValueError("Truncated frozen archive entry")
        length,off,compressed_size,size,compressed,kind=struct.unpack_from("!IIIIBB",toc,at)
        if length<18 or at+length>len(toc) or base+off+compressed_size>pos or not 0<=size<=MAX_MEMBER:
            raise ValueError("Frozen archive entry is out of bounds")
        name=toc[at+18:at+length].rstrip(b"\0").decode("utf-8")
        if name in entries:raise ValueError("Duplicate frozen archive entry")
        blob=raw[base+off:base+off+compressed_size]
        if compressed:blob=bounded_zlib(blob,size)
        if len(blob)!=size:raise ValueError("Frozen archive entry size differs")
        entries[name]=(chr(kind),blob);at+=length
    return entries


def pyz_modules(raw):
    if sys.version_info[:2]!=(3,12) or raw[:4]!=b"PYZ\0" or raw[4:8]!=importlib.util.MAGIC_NUMBER:
        raise ValueError("Use matching CPython3.12 bytecode magic")
    offset=struct.unpack_from("!I",raw,8)[0]
    if not 12<=offset<len(raw) or len(raw)-offset>2*1024*1024:raise ValueError("PYZ table bounds differ")
    toc=marshal.loads(raw[offset:])
    rows=list(toc.items()) if isinstance(toc,dict) else list(toc)
    if len(rows)>4096:raise ValueError("PYZ module count exceeds its bound")
    names=set();result={};skipped=[]
    for name,entry in rows:
        if not isinstance(name,str) or name in names or any(not part.isidentifier() for part in name.split(".")):
            raise ValueError("Unsafe/duplicate PYZ module name")
        names.add(name)
        if name in ("engine","payload","__main__") or name=="idoly_local" or name.startswith("idoly_local."):
            skipped.append(name);continue
        kind,start,size=entry
        if kind==3:continue # Namespace packages are supplied by their children/data directories.
        if kind not in (0,1) or not 12<=start<=offset or not 0<=size<=offset-start:
            raise ValueError("PYZ module bounds/type differ")
        code=bounded_zlib(raw[start:start+size],MAX_MEMBER)
        # Keep exact original marshal bytes; no code-object reserialization.
        path=name.replace(".","/")+("/__init__.pyc" if kind==1 else ".pyc")
        result[path]=raw[4:8]+b"\0"*12+code
    return result,skipped


def export_runtime(source,destination):
    destination=Path(destination)
    if destination.exists():raise ValueError("Choose an unused runtime directory")
    with ZipFile(source) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError("Duplicate Mac bundle member")
        selected=[i for i in archive.infolist() if i.filename.startswith(PREFIX+"_internal/")]
        if not selected or sum(i.file_size for i in selected)>96*1024*1024:raise ValueError("Runtime exceeds its bound")
        entries=carchive(archive.read(PREFIX+"IdolyServerEngine"))
        pyzs=[raw for kind,raw in entries.values() if kind=="z"]
        if len(pyzs)!=1:raise ValueError("Expected one frozen dependency archive")
        modules,skipped=pyz_modules(pyzs[0]);destination.mkdir(parents=True)
        hashes={};symlinks={}
        for info in selected:
            relative=PurePosixPath(info.filename[len(PREFIX):])
            if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative) or info.file_size>MAX_MEMBER:
                raise ValueError("Unsafe runtime member")
            target=destination.joinpath(*relative.parts);target.parent.mkdir(parents=True,exist_ok=True)
            mode=info.external_attr>>16
            if info.is_dir():target.mkdir(exist_ok=True);continue
            raw=archive.read(info)
            if stat.S_ISLNK(mode):
                link=raw.decode("utf-8")
                resolved=(target.parent/link).resolve()
                if not resolved.is_relative_to(destination.resolve()):raise ValueError("Runtime symlink leaves bundle")
                target.symlink_to(link);symlinks[str(relative)]=link
            elif stat.S_ISREG(mode):
                target.write_bytes(raw);target.chmod(mode&0o777);hashes[str(relative)]=hashlib.sha256(raw).hexdigest()
            else:raise ValueError("Unexpected runtime file type")
        for relative,raw in modules.items():
            target=destination/"_internal"/relative
            if target.exists():raise ValueError("Exported Python module collides with original runtime data")
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        return {"python_version":"3.12","python_magic":importlib.util.MAGIC_NUMBER.hex(),
            "original_file_sha256":hashes,"symlinks":symlinks,"exported_module_sha256":{n:hashlib.sha256(b).hexdigest() for n,b in modules.items()},
            "old_application_modules_excluded":skipped,"old_bootloader_copied":False,
            "python_library":"_internal/Python.framework/Versions/3.12/Python"}
