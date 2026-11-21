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
Descriptor photo_selection(){
    Descriptor d=selection();PhotoSelection&p=d.photo;p.source_kind=1;p.is_preview=1;p.is_original=1;p.screen_transition=1;
    strcpy(p.stage_id,"stage-master-001");strcpy(p.music_id,"tri-004");p.actor_count=d.actor_count;
    for(size_t i=0;i<p.actor_count;++i){snprintf(p.actors[i].costume_id,name_capacity,"costume-char-%zu",i);snprintf(p.actors[i].hair_id,name_capacity,"hair-char-%zu",i);}
    return d;
}
Options options(){Options o{};o.width=1280;o.height=720;return o;}
void exact(Error actual,Error expected){if(actual!=expected){fprintf(stderr,"expected %s got %s\n",error_code(expected),error_code(actual));abort();}}
void path(char*out,const char*root,const char*name){snprintf(out,4096,"%s/%s",root,name);}
int main(int argc,char**argv){assert(argc>=3);const char*mode=argv[1];const char*root=argv[2];RandomState random{};Queue q(random_bytes,&random);
    if(!strcmp(mode,"open")){Error result=q.open(root,argc>3?argv[3]:profile);printf("%s %zu\n",error_code(result),q.count());return 0;}
    exact(q.open(root,profile),Error::ok);
    if(!strcmp(mode,"photo_seed")){char id[33];exact(q.enqueue(photo_selection(),options(),id),Error::ok);printf("photo_seed\n");return 0;}
    if(!strcmp(mode,"photo_roundtrip")){
        Descriptor d=photo_selection();Options o=options();o.output_width=1920;o.output_height=1080;o.video_bitrate=12340000;char id[33],normal[33];
        exact(q.enqueue(d,o,id),Error::ok);strcpy(d.photo.stage_id,"mutated-after-enqueue");strcpy(d.photo.actors[0].costume_id,"mutated-costume");
        assert(!strcmp(q.find(id)->descriptor.photo.stage_id,"stage-master-001"));exact(q.enqueue(selection(),options(),normal),Error::ok);
        q.close();exact(q.open(root,profile),Error::ok);assert(q.count()==2);const Job*j=q.find(id);const PhotoSelection&p=j->descriptor.photo;
        assert(p.source_kind==1&&p.is_preview==1&&p.is_original==1&&p.screen_transition==1&&p.actor_count==2);
        assert(!strcmp(p.stage_id,"stage-master-001")&&!strcmp(p.music_id,"tri-004")&&!strcmp(p.actors[0].costume_id,"costume-char-0")&&!strcmp(p.actors[1].hair_id,"hair-char-1"));
        assert(j->options.output_width==1920&&j->options.output_height==1080&&j->options.video_bitrate==12340000);
        assert(q.find(normal)->descriptor.photo.source_kind==0&&detail::photo(q.find(normal)->descriptor.photo,2));
        char claimed[33];exact(q.claim_next(claimed),Error::ok);assert(!strcmp(id,claimed));exact(q.fail(id,"codec_failed"),Error::ok);exact(q.retry(id),Error::ok);
        assert(q.find(id)->descriptor.photo.source_kind==1&&!strcmp(q.find(id)->descriptor.photo.actors[1].hair_id,"hair-char-1"));printf("photo_roundtrip\n");return 0;
    }
    if(!strcmp(mode,"photo_limits")){
        Options o=options();char id[33];Descriptor d=selection();d.photo.source_kind=2;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=selection();d.photo.is_preview=1;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=selection();d.photo.actor_count=1;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=selection();d.photo.stage_id[1]='x';exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=selection();d.photo.actors[max_actors-1].hair_id[1]='x';exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.actor_count=1;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.actor_count=max_actors+1;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.is_preview=2;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.is_original=2;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.screen_transition=2;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.screen_transition=0;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.stage_id[0]=0;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();strcpy(d.photo.music_id,"../music");exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.actors[0].costume_id[0]=0;exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();strcpy(d.photo.actors[1].hair_id,"hair/id");exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();strcpy(d.photo.actors[2].costume_id,"unused");exact(q.enqueue(d,o,id),Error::invalid_descriptor);
        d=photo_selection();d.photo.screen_transition=0;d.photo.is_original=0;exact(q.enqueue(d,o,id),Error::ok);
        Job job{};job.descriptor=photo_selection();uint8_t raw[4096]{};detail::Writer writer{raw,sizeof(raw)};
        detail::encode(writer,job,2);assert(!writer.ok); // Never silently erase a Photo transition into a v2 job.
        printf("photo_limits\n");return 0;
    }
    if(!strcmp(mode,"legacy1")||!strcmp(mode,"legacy2")){
        const uint32_t version=!strcmp(mode,"legacy1")?1:2;q.close();Job j{};memset(j.id,'1',32);j.descriptor=selection();j.options=options();j.options.output_width=640;j.options.output_height=480;
        auto*raw=static_cast<uint8_t*>(calloc(max_wire_bytes,1));assert(raw);detail::Writer w{raw+header_bytes,max_wire_bytes-header_bytes};detail::encode(w,j,version);assert(w.ok);
        memcpy(raw,"IDMPQ001",8);detail::put32(raw+8,version);detail::put32(raw+12,header_bytes);memcpy(raw+16,profile,64);detail::put64(raw+80,7);detail::put32(raw+88,1);detail::put32(raw+92,static_cast<uint32_t>(w.at));detail::put64(raw+96,detail::checksum(raw+header_bytes,w.at,detail::checksum(raw,96)));
        char target[4096];path(target,root,"queue-v1.bin");int fd=::open(target,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0&&::write(fd,raw,header_bytes+w.at)==static_cast<long>(header_bytes+w.at));::close(fd);free(raw);
        printf("%s\n",mode);return 0;
    }
    if(!strcmp(mode,"legacy_migrate")){
        assert(argc==4&&q.count()==1);const Job*j=q.at(0);assert(j->descriptor.photo.source_kind==0&&detail::photo(j->descriptor.photo,j->descriptor.actor_count));
        assert(j->options.output_width==(!strcmp(argv[3],"1")?0U:640U));char id[33];memcpy(id,j->id,33);exact(q.cancel(id),Error::ok);
        q.close();exact(q.open(root,profile),Error::ok);assert(q.find(id)->state==State::cancelled&&q.find(id)->descriptor.photo.source_kind==0);
        assert(!strcmp(q.find(id)->descriptor.stage_asset,"env_live_test")&&q.find(id)->descriptor.actor_count==2);printf("legacy_migrate\n");return 0;
    }
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
    if(!strcmp(mode,"maximum")||!strcmp(mode,"maximum_photo")){
        Descriptor d=selection();d.actor_count=max_actors;for(size_t i=0;i<max_actors;++i){Actor&a=d.actors[i];a=Actor{};snprintf(a.character_id,name_capacity,"actor_%zu",i);a.actor_index=static_cast<int32_t>(i);a.track_index=static_cast<int32_t>(i);memset(a.descriptor_name,'n',name_capacity-1);a.asset_count=max_assets;for(size_t k=0;k<max_assets;++k){memset(a.assets[k],'a',name_capacity-1);a.assets[k][0]=static_cast<char>('a'+k);}}
        if(!strcmp(mode,"maximum_photo")){d.photo.source_kind=1;d.photo.actor_count=max_actors;memset(d.photo.stage_id,'s',name_capacity-1);memset(d.photo.music_id,'m',name_capacity-1);for(auto&actor:d.photo.actors){memset(actor.costume_id,'c',name_capacity-1);memset(actor.hair_id,'h',name_capacity-1);}}
        char id[33];for(size_t i=0;i<max_jobs;++i)exact(q.enqueue(d,options(),id),Error::ok);q.close();exact(q.open(root,profile),Error::ok);assert(q.count()==max_jobs&&q.at(max_jobs-1)->descriptor.actor_count==max_actors&&strlen(q.at(0)->descriptor.actors[0].assets[0])==192);
        if(!strcmp(mode,"maximum_photo")){assert(q.at(0)->descriptor.photo.actor_count==max_actors&&strlen(q.at(max_jobs-1)->descriptor.photo.actors[max_actors-1].hair_id)==192);}printf("%s\n",mode);return 0;
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
    compiled = subprocess.run([compiler, "-std=c++14", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(source), "-o", str(executable)], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr

    def run(mode, root, *arguments):
        return subprocess.run([str(executable), mode, str(root), *arguments], check=True, capture_output=True, text=True, timeout=4).stdout.strip()

    return run


@pytest.fixture
def private(tmp_path):
    folder = tmp_path / "queue"
    folder.mkdir(mode=0o700)
    return folder


@pytest.mark.parametrize("mode", ["basic", "limits", "snapshot", "maximum", "maximum_photo", "photo_roundtrip", "photo_limits", "pending_cancel", "random_failure", "replace", "transition_failure", "durability_failure", "inplace", "first_race", "single_owner"])
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


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_outgame_journal_stays_read_only_until_ordinary_v3_transaction(queue_runner, private, version):
    assert queue_runner(f"legacy{version}", private) == f"legacy{version}"
    journal = private / "queue-v1.bin"
    before = journal.read_bytes()
    assert struct.unpack_from("<I", before, 8)[0] == version
    assert queue_runner("open", private) == "none 1"
    assert journal.read_bytes() == before
    assert queue_runner("legacy_migrate", private, str(version)) == "legacy_migrate"
    migrated = journal.read_bytes()
    assert struct.unpack_from("<I", migrated, 8)[0] == 3
    assert len(migrated) <= 1024 * 1024
    assert queue_runner("open", private) == "none 1"


def checksum(body):
    value = 14695981039346656037
    for byte in body:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def photo_wire_offsets(body):
    """Locate the specified v3 photo fields after the unchanged v2 job prefix."""
    assert struct.unpack_from("<I", body, 8)[0] == 3
    cursor = 104

    def string():
        nonlocal cursor
        start = cursor
        size, = struct.unpack_from("<H", body, cursor)
        cursor += 2 + size
        return start, start + 2, size

    string()  # job identity
    string()  # output identity
    cursor += 8  # state, attempts
    string()  # error
    string()  # pause reason
    cursor += 76  # v2 geometry/options and graphics snapshot
    string()  # resolved stage asset
    string()  # resolved timeline asset
    cursor += 8  # stage capacity, detached flag
    actors, = struct.unpack_from("<I", body, cursor)
    cursor += 4
    for _ in range(actors):
        string()  # character
        string()  # display name
        cursor += 44  # actor indices/settings/flags
        assets, = struct.unpack_from("<I", body, cursor)
        cursor += 4
        for _ in range(assets):
            string()
    fields = dict(source_kind=cursor, is_preview=cursor + 4, is_original=cursor + 8, screen_transition=cursor + 12)
    cursor += 16
    fields["stage_id"] = string()
    fields["music_id"] = string()
    fields["actor_count"] = cursor
    photo_actors, = struct.unpack_from("<I", body, cursor)
    cursor += 4
    fields["actors"] = [(string(), string()) for _ in range(photo_actors)]
    assert cursor == len(body)
    return fields


@pytest.mark.parametrize("change", ["source_kind", "noncanonical_outgame", "wide_flag", "actor_count_bound",
    "actor_count_mismatch", "base_original", "stage_path", "embedded_nul", "empty_hair", "truncated", "unknown_version"])
def test_v3_photo_transition_corruption_is_rejected_with_valid_checksum(queue_runner, private, change):
    assert queue_runner("photo_seed", private) == "photo_seed"
    journal = private / "queue-v1.bin"
    body = bytearray(journal.read_bytes())
    fields = photo_wire_offsets(body)
    if change == "source_kind":
        struct.pack_into("<I", body, fields["source_kind"], 2)
    elif change == "noncanonical_outgame":
        struct.pack_into("<I", body, fields["source_kind"], 0)
    elif change == "wide_flag":
        struct.pack_into("<I", body, fields["is_preview"], 256)
    elif change == "actor_count_bound":
        struct.pack_into("<I", body, fields["actor_count"], 33)
    elif change == "actor_count_mismatch":
        struct.pack_into("<I", body, fields["actor_count"], 1)
    elif change == "base_original":
        struct.pack_into("<I", body, fields["screen_transition"], 0)
    elif change == "stage_path":
        body[fields["stage_id"][1]] = ord("/")
    elif change == "embedded_nul":
        body[fields["stage_id"][1]] = 0
    elif change == "empty_hair":
        size_at, data_at, size = fields["actors"][0][1]
        del body[data_at:data_at + size]
        struct.pack_into("<H", body, size_at, 0)
    elif change == "truncated":
        del body[-1:]
    else:
        struct.pack_into("<I", body, 8, 4)
    struct.pack_into("<I", body, 92, len(body) - 104)
    struct.pack_into("<Q", body, 96, checksum(body[:96] + body[104:]))
    journal.write_bytes(body)
    assert queue_runner("open", private) == "queue_corrupt 0"
    assert journal.read_bytes() == body


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
