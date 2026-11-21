"""Execute the portable MV job journal, including crash and filesystem failures."""
from pathlib import Path
import os
import shutil
import struct
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROFILE = "a" * 64

HARNESS = r'''
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
static bool fail_directory_sync=false;
int journal_fsync(int fd){struct stat info{};if(fail_directory_sync&&fstat(fd,&info)==0&&S_ISDIR(info.st_mode)){errno=EINVAL;return -1;}return ::fsync(fd);}
#define fsync journal_fsync
#include "client-presentation/native/mp4_queue.hpp"
#undef fsync
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
using namespace idoly_mp4_queue;
static const char* profile="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
struct RandomState{unsigned count=0,fail_at=0;bool constant=false;};
bool random_bytes(void*ctx,uint8_t*p,size_t n){RandomState&r=*static_cast<RandomState*>(ctx);++r.count;if(r.fail_at&&r.count==r.fail_at)return false;memset(p,0xa5,n);p[0]=r.constant?0:static_cast<uint8_t>(r.count);p[1]=r.constant?0:static_cast<uint8_t>(r.count>>8);return true;}
Descriptor selection(const char* timeline="tln_live_tri-004"){
    Descriptor d{};snprintf(d.stage_asset,name_capacity,"env_live_test");snprintf(d.timeline_asset,name_capacity,"%s",timeline);d.actor_count=2;d.stage_max_capacity=5;
    for(unsigned i=0;i<2;++i){Actor&a=d.actors[i];snprintf(a.character_id,name_capacity,"char_%u",i);snprintf(a.descriptor_name,name_capacity,"actor_%u",i);a.actor_index=static_cast<int32_t>(i);a.track_index=static_cast<int32_t>(i);a.audience_amount=100;a.psyllium_color_type=3;a.asset_count=2;snprintf(a.assets[0],name_capacity,"mdl_live_char_%u",i);snprintf(a.assets[1],name_capacity,"mdl_live_dress_%u",i);a.humanoid=1;a.auto_blink_disabled=1;a.render_layer_base=7;}
    return d;
}
Options options(){Options o{};o.width=1280;o.height=720;return o;}
void exact(Error actual,Error expected){if(actual!=expected){fprintf(stderr,"expected %s got %s\n",error_code(expected),error_code(actual));abort();}}
void path(char*out,const char*root,const char*name){snprintf(out,4096,"%s/%s",root,name);}
int main(int argc,char**argv){assert(argc>=3);const char*mode=argv[1];const char*root=argv[2];RandomState random{};Queue q(random_bytes,&random);
    if(!strcmp(mode,"open")){Error result=q.open(root,argc>3?argv[3]:profile);printf("%s %zu\n",error_code(result),q.count());return 0;}
    exact(q.open(root,profile),Error::ok);
    if(!strcmp(mode,"seed")){Descriptor d=selection();char a[33],b[33],claimed[33];exact(q.enqueue(d,options(),a),Error::ok);d=selection("tln_live_tri-005");exact(q.enqueue(d,options(),b),Error::ok);exact(q.claim_next(claimed),Error::ok);assert(!strcmp(a,claimed));printf("%s %s %s\n",a,b,q.at(0)->output_id);return 0;}
    if(!strcmp(mode,"recover")){assert(q.count()==2);assert(q.at(0)->state==State::interrupted);assert(!strcmp(q.at(0)->error,"process_interrupted"));assert(q.at(1)->state==State::pending);char id[33],old[33],claimed[33];memcpy(id,q.at(0)->id,33);memcpy(old,q.at(0)->output_id,33);exact(q.retry(id),Error::ok);exact(q.claim_next(claimed),Error::ok);assert(!strcmp(id,claimed));assert(strcmp(old,q.find(id)->output_id));assert(q.find(id)->attempts==2);exact(q.finish(id),Error::ok);printf("recovered\n");return 0;}
    if(!strcmp(mode,"basic")){
        Descriptor d=selection();Options o=options();char a[33],b[33],claimed[33];exact(q.enqueue(d,o,a),Error::ok);strcpy(d.actors[0].assets[1],"changed_after_enqueue");assert(strcmp(q.find(a)->descriptor.actors[0].assets[1],"changed_after_enqueue"));d=selection("tln_live_tri-005");o.fps_num=60;exact(q.enqueue(d,o,b),Error::ok);exact(q.move(b,0),Error::ok);assert(!strcmp(q.at(0)->id,b));exact(q.claim_next(claimed),Error::ok);assert(!strcmp(claimed,b));assert(q.find(b)->options.fps_num==60);assert(!strcmp(q.find(b)->descriptor.timeline_asset,"tln_live_tri-005"));exact(q.claim_next(claimed),Error::busy);exact(q.move(b,1),Error::invalid_state);exact(q.remove(b),Error::busy);exact(q.pause(b,"lifecycle_background"),Error::ok);assert(!strcmp(q.find(b)->pause_reason,"lifecycle_background"));exact(q.resume(b),Error::ok);exact(q.finish(b),Error::ok);exact(q.claim_next(claimed),Error::ok);assert(!strcmp(claimed,a));char old[33];memcpy(old,q.find(a)->output_id,33);exact(q.fail(a,"codec_failed"),Error::ok);exact(q.retry(a),Error::ok);exact(q.claim_next(claimed),Error::ok);assert(strcmp(old,q.find(a)->output_id));exact(q.cancel(a),Error::ok);exact(q.retry(a),Error::ok);exact(q.claim_next(claimed),Error::ok);exact(q.finish(a),Error::ok);assert(q.find(a)->attempts==3);exact(q.retry(a),Error::invalid_state);exact(q.remove(b),Error::ok);assert(q.count()==1);uint64_t generation=q.generation();q.close();exact(q.open(root,profile),Error::ok);assert(q.generation()==generation&&q.count()==1);assert(q.find(a)->state==State::completed&&q.find(a)->attempts==3);printf("basic\n");return 0;
    }
    if(!strcmp(mode,"limits")){
        Descriptor d=selection();Options o=options();char id[33];d.actors[1].actor_index=0;exact(q.enqueue(d,o,id),Error::invalid_descriptor);d=selection();d.actors[0].humanoid=2;exact(q.enqueue(d,o,id),Error::invalid_descriptor);d=selection();o.fps_num=24;exact(q.enqueue(d,o,id),Error::invalid_options);o=options();o.width=15;exact(q.enqueue(d,o,id),Error::invalid_options);o=options();for(size_t i=0;i<max_jobs;++i)exact(q.enqueue(d,o,id),Error::ok);exact(q.enqueue(d,o,id),Error::full);assert(q.count()==max_jobs);printf("limits\n");return 0;
    }
    if(!strcmp(mode,"snapshot")){
        Descriptor d=selection();strcpy(d.actors[0].descriptor_name,"桜・衣装 α");d.actors[1].descriptor_name[0]=0;d.actors[1].name_is_null=1;d.actors[0].collider_type=1;Options o=options();o.graphics.revision=1234567890123LL;o.graphics.custom_graphics=1;o.graphics.quality=100;o.graphics.target_fps=120;o.graphics.render_scale=1.75f;o.graphics.max_buffer_pixel=3072;o.graphics.aa_mode=2;o.graphics.shadow_resolution=2048;o.graphics.expand_photography=1;char id[33];exact(q.enqueue(d,o,id),Error::ok);o.graphics.quality=0;d.actors[0].descriptor_name[0]=0;q.close();exact(q.open(root,profile),Error::ok);const Job*j=q.at(0);assert(!strcmp(j->descriptor.actors[0].descriptor_name,"桜・衣装 α"));assert(j->descriptor.actors[1].name_is_null==1);assert(j->descriptor.actors[0].collider_type==1);assert(j->options.graphics.revision==1234567890123LL&&j->options.graphics.quality==100&&j->options.graphics.target_fps==120&&j->options.graphics.render_scale==1.75f&&j->options.graphics.max_buffer_pixel==3072&&j->options.graphics.aa_mode==2&&j->options.graphics.shadow_resolution==2048&&j->options.graphics.expand_photography==1);d=selection();strcpy(d.actors[0].descriptor_name,"\xc0\xaf");exact(q.enqueue(d,options(),id),Error::invalid_descriptor);d=selection();d.actors[0].name_is_null=1;exact(q.enqueue(d,options(),id),Error::invalid_descriptor);d=selection();o=options();o.graphics.render_scale=__builtin_nanf("");exact(q.enqueue(d,o,id),Error::invalid_options);printf("snapshot\n");return 0;
    }
    if(!strcmp(mode,"maximum")){
        Descriptor d=selection();d.actor_count=max_actors;for(size_t i=0;i<max_actors;++i){Actor&a=d.actors[i];a=Actor{};snprintf(a.character_id,name_capacity,"actor_%zu",i);a.actor_index=static_cast<int32_t>(i);a.track_index=static_cast<int32_t>(i);memset(a.descriptor_name,'n',name_capacity-1);a.asset_count=max_assets;for(size_t k=0;k<max_assets;++k){memset(a.assets[k],'a',name_capacity-1);a.assets[k][0]=static_cast<char>('a'+k);}}
        char id[33];for(size_t i=0;i<max_jobs;++i)exact(q.enqueue(d,options(),id),Error::ok);q.close();exact(q.open(root,profile),Error::ok);assert(q.count()==max_jobs&&q.at(max_jobs-1)->descriptor.actor_count==max_actors&&strlen(q.at(0)->descriptor.actors[0].assets[0])==192);printf("maximum\n");return 0;
    }
    if(!strcmp(mode,"pending_cancel")){char id[33];exact(q.enqueue(selection(),options(),id),Error::ok);exact(q.cancel(id),Error::ok);assert(!q.find(id)->output_id[0]);q.close();exact(q.open(root,profile),Error::ok);assert(q.at(0)->state==State::cancelled);exact(q.retry(id),Error::ok);q.close();exact(q.open(root,profile),Error::ok);assert(q.at(0)->state==State::pending);printf("pending_cancel\n");return 0;}
    if(!strcmp(mode,"random_failure")){
        char id[33];random.fail_at=1;exact(q.enqueue(selection(),options(),id),Error::random_failed);assert(q.count()==0);random.fail_at=random.count+2;exact(q.enqueue(selection(),options(),id),Error::random_failed);assert(q.count()==0);random.fail_at=0;random.constant=true;exact(q.enqueue(selection(),options(),id),Error::ok);exact(q.enqueue(selection(),options(),id),Error::random_failed);assert(q.count()==1);printf("random_failure\n");return 0;
    }
    if(!strcmp(mode,"replace")||!strcmp(mode,"transition_failure")){
        char id[33];exact(q.enqueue(selection(),options(),id),Error::ok);bool transition=!strcmp(mode,"transition_failure");if(transition){char claimed[33];exact(q.claim_next(claimed),Error::ok);exact(q.pause(id,"user_paused"),Error::ok);}char source[4096],other[4096];path(source,root,"queue-v1.bin");path(other,root,"replacement");int fd=::open(source,O_RDONLY),copy=::open(other,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0&&copy>=0);char buffer[4096];long n;while((n=::read(fd,buffer,sizeof(buffer)))>0)assert(::write(copy,buffer,static_cast<size_t>(n))==n);::close(fd);::close(copy);assert(::rename(other,source)==0);if(transition){exact(q.resume(id),Error::changed_storage);exact(q.finish(id),Error::changed_storage);exact(q.fail(id,"encoder_failed"),Error::changed_storage);exact(q.cancel(id),Error::changed_storage);assert(q.find(id)->state==State::paused&&!strcmp(q.find(id)->pause_reason,"user_paused"));}else exact(q.enqueue(selection(),options(),id),Error::changed_storage);assert(q.count()==1);printf("%s\n",mode);return 0;
    }
    if(!strcmp(mode,"inplace")){
        char id[33];exact(q.enqueue(selection(),options(),id),Error::ok);char source[4096];path(source,root,"queue-v1.bin");int fd=::open(source,O_WRONLY);assert(fd>=0);assert(::pwrite(fd,"x",1,0)==1);::close(fd);exact(q.enqueue(selection(),options(),id),Error::changed_storage);assert(q.count()==1);printf("inplace\n");return 0;
    }
    if(!strcmp(mode,"first_race")){
        char p[4096];path(p,root,"queue-v1.bin");int fd=::open(p,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);assert(::write(fd,"unowned",7)==7);::close(fd);char id[33];exact(q.enqueue(selection(),options(),id),Error::changed_storage);assert(q.count()==0);printf("first_race\n");return 0;
    }
    if(!strcmp(mode,"single_owner")){Queue second;exact(second.open(root,profile),Error::busy);char id[33];exact(q.enqueue(selection(),options(),id),Error::ok);q.close();exact(second.open(root,profile),Error::ok);assert(second.count()==1&&!strcmp(second.at(0)->id,id));printf("single_owner\n");return 0;}
    if(!strcmp(mode,"durability_failure")){char id[33],claimed[33];exact(q.enqueue(selection(),options(),id),Error::ok);exact(q.claim_next(claimed),Error::ok);exact(q.pause(id,"user_paused"),Error::ok);fail_directory_sync=true;exact(q.resume(id),Error::durability_uncertain);exact(q.finish(id),Error::not_open);exact(q.cancel(id),Error::not_open);q.close();fail_directory_sync=false;exact(q.open(root,profile),Error::ok);assert(q.find(id)->state==State::interrupted&&!strcmp(q.find(id)->error,"process_interrupted"));printf("durability_failure\n");return 0;}
    abort();
}
'''


@pytest.fixture(scope="module")
def queue_runner(tmp_path_factory):
    folder = tmp_path_factory.mktemp("mp4-queue-compile")
    source, executable = folder / "queue.cpp", folder / "queue"
    source.write_text(HARNESS)
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("A C++ compiler is required")
    subprocess.run([compiler, "-std=c++14", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(executable)], check=True, capture_output=True, text=True)

    def run(mode, root, *arguments):
        return subprocess.run([str(executable), mode, str(root), *arguments], check=True, capture_output=True, text=True, timeout=4).stdout.strip()

    return run


@pytest.fixture
def private(tmp_path):
    folder = tmp_path / "queue"
    folder.mkdir(mode=0o700)
    return folder


@pytest.mark.parametrize("mode", ["basic", "limits", "snapshot", "maximum", "pending_cancel", "random_failure", "replace", "transition_failure", "durability_failure", "inplace", "first_race", "single_owner"])
def test_queue_executes_transactional_order_and_failures(queue_runner, private, mode):
    assert queue_runner(mode, private) == mode
    assert private.stat().st_mode & 0o777 == 0o700
    assert not list(private.glob(".queue-*.tmp"))
    assert (private / "queue-v1.bin").stat().st_mode & 0o777 == 0o600


def test_separate_process_recovers_without_claiming_partial_mp4_complete(queue_runner, private):
    first, second, output = queue_runner("seed", private).split()
    assert len({first, second, output}) == 3
    before = (private / "queue-v1.bin").read_bytes()
    assert queue_runner("recover", private) == "recovered"
    assert (private / "queue-v1.bin").read_bytes() != before


def checksum(body):
    value = 14695981039346656037
    for byte in body:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


@pytest.mark.parametrize("change", ["flip", "truncate", "append", "unknown_state", "oversized_count"])
def test_rejects_corrupt_or_semantically_invalid_journal_without_replacing_it(queue_runner, private, change):
    queue_runner("seed", private)
    journal = private / "queue-v1.bin"
    body = bytearray(journal.read_bytes())
    if change == "flip":
        body[-1] ^= 1
    elif change == "truncate":
        body = body[:100]
    elif change == "append":
        body += b"extra"
    else:
        if change == "oversized_count":
            struct.pack_into("<I", body, 88, 100_000)
        else:
            cursor = 104
            for _ in range(2):
                size, = struct.unpack_from("<H", body, cursor)
                cursor += 2 + size
            struct.pack_into("<I", body, cursor, 999)
        struct.pack_into("<Q", body, 96, checksum(body[:96] + body[104:]))
    journal.write_bytes(body)
    assert queue_runner("open", private) == "queue_corrupt 0"
    assert journal.read_bytes() == body


def test_profile_identity_change_cannot_replay_other_original_client(queue_runner, private):
    queue_runner("seed", private)
    journal = private / "queue-v1.bin"
    before = journal.read_bytes()
    assert queue_runner("open", private, "b" * 64) == "queue_profile_mismatch 0"
    assert journal.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink", "mode"])
def test_journal_cannot_follow_links_or_block_on_special_files(queue_runner, private, kind):
    journal = private / "queue-v1.bin"
    if kind in {"symlink", "fifo"}:
        if kind == "symlink":
            target = private.parent / "outside"
            target.write_bytes(b"preserved")
            journal.symlink_to(target)
        else:
            os.mkfifo(journal, 0o600)
    else:
        queue_runner("seed", private)
        if kind == "hardlink":
            os.link(journal, private / "second-link")
        else:
            journal.chmod(0o640)
    result = queue_runner("open", private)
    assert result in {"unsafe_queue_storage 0", "queue_corrupt 0"}
    if kind == "symlink":
        assert target.read_bytes() == b"preserved"


def test_queue_requires_private_directory_and_does_not_create_or_chmod_it(queue_runner, private):
    private.chmod(0o755)
    assert queue_runner("open", private) == "unsafe_queue_storage 0"
    assert private.stat().st_mode & 0o777 == 0o755
    assert not list(private.iterdir())
