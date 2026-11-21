"""Real file-policy and Apple Foundation tests for retained MP4 outputs.

The Foundation cases run the shipping catalog in independent processes. The
portable cases exercise real filesystem objects, never a simulated Files app.
"""
from pathlib import Path
import json
import os
import platform
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "ios-unified/native"
ID = "a" * 32


@pytest.fixture(scope="module")
def file_policy(tmp_path_factory):
    compiler = shutil.which("cc")
    if not compiler:
        pytest.skip("Native C compiler required")
    folder = tmp_path_factory.mktemp("mp4-completed-policy")
    source, output = folder / "policy.c", folder / "policy"
    source.write_text(r'''
#define _GNU_SOURCE
#include "MP4CompletedFilePolicy.h"
#include <stdio.h>
int main(int argc,char **argv){
 if(argc!=3)return 2;
 int root=IDMP4LibraryOpenDirectory(argv[1]);struct stat a,b;
 int file=IDMP4LibraryOpenFinalAt(root,argv[2],&a);bool same=false;
 if(file>=0){b=a;same=IDMP4LibrarySameFile(&a,&b);b.st_size++;same=same&&!IDMP4LibrarySameFile(&a,&b);close(file);}
 if(root>=0)close(root);
 printf("%d %d %d\n",IDMP4LibraryIdentifier(argv[2]),file>=0,same);return 0;
}
''')
    built = subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror","-I",str(NATIVE),
                            str(source),"-o",str(output)],capture_output=True,text=True,timeout=30)
    assert built.returncode == 0, built.stdout+built.stderr
    def run(root, identifier=ID):
        result = subprocess.run([str(output),str(root),identifier],capture_output=True,text=True,timeout=2)
        assert result.returncode == 0,result.stdout+result.stderr
        return tuple(map(int,result.stdout.split()))
    return run


def final(root, identifier=ID):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    root.chmod(0o700)
    output=root/(identifier+".mp4")
    output.write_bytes(b"retained-native-final-mp4")
    output.chmod(0o600)
    return output.resolve()


def test_completed_private_file_policy_preserves_exact_source(file_policy,tmp_path):
    source=final(tmp_path)
    before=source.stat()
    for _ in range(3):
        assert file_policy(tmp_path)==(1,1,1)
    assert source.read_bytes()==b"retained-native-final-mp4"
    assert (source.stat().st_ino,source.stat().st_size)==(before.st_ino,before.st_size)


@pytest.mark.parametrize("shape",["empty","directory","fifo","symlink","hardlink","public_file","public_root"])
def test_completed_policy_rejects_unsafe_shapes_without_touching_them(file_policy,tmp_path,shape):
    output=tmp_path/(ID+".mp4")
    if shape=="empty":output.write_bytes(b"");output.chmod(0o600)
    elif shape=="directory":output.mkdir(mode=0o700)
    elif shape=="fifo":os.mkfifo(output,0o600)
    elif shape in ("symlink","hardlink"):
        foreign=final(tmp_path,"b"*32)
        output.symlink_to(foreign) if shape=="symlink" else os.link(foreign,output)
    else:
        final(tmp_path)
        (output if shape=="public_file" else tmp_path).chmod(0o644 if shape=="public_file" else 0o755)
    assert file_policy(tmp_path)==(1,0,0)
    assert output.lstat()


@pytest.mark.parametrize("identifier",["", "a"*31,"a"*33,"A"*32,"../"+"a"*29,"."*32])
def test_completed_policy_cannot_select_foreign_filename(file_policy,tmp_path,identifier):
    final(tmp_path)
    assert file_policy(tmp_path,identifier)==(0,0,0)


def test_completed_policy_rejects_symlink_export_directory(file_policy,tmp_path):
    actual=tmp_path/"actual";final(actual)
    alias=tmp_path/"alias";alias.symlink_to(actual,target_is_directory=True)
    assert file_policy(alias)==(1,0,0)


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    if platform.system()!="Darwin" or not shutil.which("xcrun"):
        pytest.skip("Actual Apple Foundation SDK required")
    folder=tmp_path_factory.mktemp("mp4-completed-foundation")
    source,output=folder/"library.m",folder/"library"
    source.write_text(r'''
#import <Foundation/Foundation.h>
#import "IdolyMP4Library.h"
#include <stdio.h>
int main(int argc,char **argv){@autoreleasepool{
 if(argc!=4)return 2;
 NSString *root=[[NSString stringWithUTF8String:argv[1]]stringByResolvingSymlinksInPath];
 NSString *operation=[NSString stringWithUTF8String:argv[2]],*raw=[NSString stringWithUTF8String:argv[3]],*error=nil;
 NSDictionary *arg=[NSJSONSerialization JSONObjectWithData:[raw dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
 NSArray *jobs=arg[@"jobs"]?:@[];NSString *queue=arg[@"queue_exports"];
 NSDictionary *reply=nil;
 if([operation isEqual:@"bookmark"]){BOOL ok=IDMP4LibraryBookmark(root,arg[@"exports"],&error);reply=@{@"ok":@(ok),@"error":ok?@"":error};}
 else if([operation isEqual:@"status"]){NSDictionary *status=IDMP4LibraryStatus(root,jobs,queue,[arg[@"offset"]unsignedIntegerValue],&error);reply=status?:@{@"error":error};}
 else if([operation isEqual:@"file"]){NSURL *url=IDMP4LibraryFile(root,jobs,queue,arg[@"export_id"],&error);reply=url?@{@"file":url.path}:@{@"error":error};}
 else return 3;
 NSData *json=[NSJSONSerialization dataWithJSONObject:reply options:0 error:NULL];fwrite(json.bytes,1,json.length,stdout);puts("");
 }return 0;}
''')
    compiler=subprocess.check_output(["xcrun","--sdk","macosx","--find","clang"],text=True).strip()
    sdk=subprocess.check_output(["xcrun","--sdk","macosx","--show-sdk-path"],text=True).strip()
    result=subprocess.run([compiler,"-isysroot",sdk,"-mmacosx-version-min=12.0","-fobjc-arc","-fblocks",
                           "-Wall","-Wextra","-Werror","-I",str(NATIVE),str(source),str(NATIVE/"IdolyMP4Library.m"),
                           "-framework","Foundation","-o",str(output)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,"Foundation catalog compilation failed:\n"+result.stdout+result.stderr
    def run(root,operation,**args):
        root=root.resolve();root.chmod(0o700)
        args={key:str(Path(value).resolve()) if key in ("exports","queue_exports") else value for key,value in args.items()}
        result=subprocess.run([str(output),str(root),operation,json.dumps(args)],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        return json.loads(result.stdout)
    return run


def broker(root, seed=1):
    folder=root/(".idoly-mp4-audio-"+format(seed,"032x"))
    exports=folder/"exports"
    exports.mkdir(parents=True,mode=0o700)
    folder.chmod(0o700);exports.chmod(0o700)
    return exports.resolve()


def test_bookmark_precedes_capture_and_survives_publish_before_completion_poll(library,tmp_path):
    exports=broker(tmp_path)
    assert library(tmp_path,"bookmark",exports=str(exports))["ok"]
    assert library(tmp_path,"status")["records"]==[]
    index=tmp_path/".idoly-mp4-completed/roots-v1.json"
    assert json.loads(index.read_text())["roots"]==[exports.parent.name]
    # The producer process may die immediately after final rename. No UI poll,
    # current SessionStatus or new native session is needed by this new process.
    source=final(exports)
    row=library(tmp_path,"status")["records"][0]
    assert row=={"export_id":ID,"bytes":source.stat().st_size,"created_ms":row["created_ms"]}
    assert library(tmp_path,"file",export_id=ID)["file"]==str(source)
    for _ in range(3):
        assert library(tmp_path,"file",export_id=ID)["file"]==str(source)
    assert source.read_bytes()==b"retained-native-final-mp4"


def test_completed_history_survives_next_job_new_broker_and_relaunch(library,tmp_path):
    first=broker(tmp_path,1);second=broker(tmp_path,2)
    assert library(tmp_path,"bookmark",exports=str(first))["ok"]
    old=final(first)
    assert library(tmp_path,"bookmark",exports=str(second))["ok"]
    assert library(tmp_path,"status")["total"]==1
    new=final(second,"b"*32)
    assert {r["export_id"] for r in library(tmp_path,"status")["records"]}=={ID,"b"*32}
    assert old.exists() and new.exists()
    assert library(tmp_path,"file",export_id=ID)["file"]==str(old)


def test_legacy_migration_is_one_level_and_never_adopts_partials_or_unknown_queue(library,tmp_path):
    legacy=broker(tmp_path);kept=final(legacy)
    (legacy/("b"*32+".partial.mp4")).write_bytes(b"not-final")
    final(tmp_path/"arbitrary/exports","c"*32)
    nested=broker(tmp_path/"nested",2);final(nested,"d"*32)
    queue=tmp_path/".idoly-mp4-library/exports";final(queue,"e"*32)
    status=library(tmp_path,"status",queue_exports=str(queue))
    assert [row["export_id"] for row in status["records"]]==[ID]
    assert kept.exists() and list(queue.iterdir())


def test_only_completed_queue_journal_records_are_exposed(library,tmp_path):
    queue=tmp_path/".idoly-mp4-library/exports";source=final(queue)
    row={"job_id":"b"*32,"output_id":ID,"state":"pending"}
    assert library(tmp_path,"status",queue_exports=str(queue),jobs=[row])["records"]==[]
    row["state"]="completed"
    status=library(tmp_path,"status",queue_exports=str(queue),jobs=[row])
    assert status["total"]==1 and status["records"][0]["job_id"]=="b"*32
    assert library(tmp_path,"file",export_id=ID,queue_exports=str(queue),jobs=[row])["file"]==str(source)
    assert library(tmp_path,"file",queue_exports=str(queue),jobs=[row])["error"]=="mp4_export_not_ready"


def test_partial_and_unsafe_files_do_not_become_catalog_outputs(library,tmp_path):
    exports=broker(tmp_path);assert library(tmp_path,"bookmark",exports=str(exports))["ok"]
    source=final(exports)
    (exports/("b"*32+".mp4")).symlink_to(source)
    os.link(source,exports/("c"*32+".mp4"))
    empty=exports/("d"*32+".mp4");empty.touch(mode=0o600)
    public=final(exports,"e"*32);public.chmod(0o644)
    os.mkfifo(exports/("f"*32+".mp4"),0o600)
    assert library(tmp_path,"status")["records"]==[]
    assert source.exists() and public.exists()


def test_metadata_symlink_or_malformed_index_blocks_capture_without_deleting_media(library,tmp_path):
    exports=broker(tmp_path);source=final(exports)
    metadata=tmp_path/".idoly-mp4-completed";metadata.mkdir(mode=0o700)
    target=tmp_path/"foreign.json";target.write_text('{"schema":1,"roots":[]}');target.chmod(0o600)
    index=metadata/"roots-v1.json";index.symlink_to(target)
    assert library(tmp_path,"bookmark",exports=str(exports))["error"]=="mp4_catalog_unavailable"
    index.unlink();index.write_text('{"schema":true,"roots":[]}');index.chmod(0o600)
    assert library(tmp_path,"bookmark",exports=str(exports))["error"]=="mp4_catalog_unavailable"
    assert source.exists() and target.exists()


def test_pagination_returns_requested_stale_offset_without_leaking_paths(library,tmp_path):
    exports=broker(tmp_path);assert library(tmp_path,"bookmark",exports=str(exports))["ok"]
    for i in range(33):final(exports,format(i+1,"032x"))
    first=library(tmp_path,"status");second=library(tmp_path,"status",offset=32)
    assert first["total"]==33 and len(first["records"])==32 and first["has_more"]
    assert second["total"]==33 and len(second["records"])==1 and not second["has_more"]
    assert len({r["export_id"] for r in first["records"]+second["records"]})==33
    stale=library(tmp_path,"status",offset=65536)
    assert stale["offset"]==65536 and stale["total"]==33 and stale["records"]==[] and not stale["has_more"]
    assert str(tmp_path) not in json.dumps(first)


def test_full_catalog_refuses_capture_and_never_evicts_unsaved_outputs(library,tmp_path):
    exports=broker(tmp_path);assert library(tmp_path,"bookmark",exports=str(exports))["ok"]
    for i in range(1024):final(exports,format(i+1,"032x"))
    next_exports=broker(tmp_path,2)
    assert library(tmp_path,"bookmark",exports=str(next_exports))["error"]=="mp4_catalog_capacity"
    assert len(list(exports.glob("*.mp4")))==1024
    assert library(tmp_path,"status")["total"]==1024
    assert library(tmp_path,"file",export_id=format(1,"032x"))["file"].startswith(str(exports))


def test_root_capacity_prunes_only_empty_bookmarks(library,tmp_path):
    leaves=[]
    for i in range(256):
        exports=broker(tmp_path,i+1);final(exports,format(i+1,"032x"));leaves.append(exports.parent.name)
    metadata=tmp_path/".idoly-mp4-completed";metadata.mkdir(mode=0o700)
    index=metadata/"roots-v1.json";index.write_text(json.dumps({"schema":1,"roots":leaves}));index.chmod(0o600)
    next_exports=broker(tmp_path,257)
    assert library(tmp_path,"bookmark",exports=str(next_exports))["error"]=="mp4_catalog_capacity"
    assert json.loads(index.read_text())["roots"]==leaves
    (tmp_path/leaves[0]/"exports"/(format(1,"032x")+".mp4")).unlink()
    assert library(tmp_path,"bookmark",exports=str(next_exports))["ok"]
    saved=json.loads(index.read_text())["roots"]
    assert leaves[0] not in saved and next_exports.parent.name in saved and len(saved)==256


def test_duplicate_ids_fail_closed_without_deleting_either_output(library,tmp_path):
    first=broker(tmp_path,1);second=broker(tmp_path,2)
    a=final(first);b=final(second)
    assert library(tmp_path,"status")["error"]=="mp4_catalog_unavailable"
    assert a.exists() and b.exists()


def test_directory_scan_has_a_strict_bound_and_preserves_existing_files(library,tmp_path):
    exports=broker(tmp_path);assert library(tmp_path,"bookmark",exports=str(exports))["ok"]
    source=final(exports)
    for i in range(4096):(exports/("ignored-"+str(i))).touch(mode=0o600)
    assert library(tmp_path,"status")["error"]=="mp4_catalog_unavailable"
    assert source.exists() and len(list(exports.iterdir()))==4097
