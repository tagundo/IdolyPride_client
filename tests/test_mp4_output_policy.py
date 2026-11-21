"""Real output pixels, immutable options, and v1 journal migration.

The original GPU and codecs are synthetic in the integration harness. The
production output policy/session/journal execute; no device result is claimed.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = r'''
#include "mp4_output_policy.hpp"
#include "mp4_queue.hpp"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
namespace out=idoly_mp4_output;
namespace qm=idoly_mp4_queue;
qm::Descriptor descriptor(){qm::Descriptor d{};std::strcpy(d.stage_asset,"stage");std::strcpy(d.timeline_asset,"timeline");d.actor_count=1;std::strcpy(d.actors[0].character_id,"rei");d.actors[0].asset_count=1;std::strcpy(d.actors[0].assets[0],"costume");return d;}
int main(int argc,char** argv){assert(argc==3);const char* mode=argv[1];
    if(!std::strcmp(mode,"policy")){
        assert(out::requested_dimensions(0,0)&&!out::requested_dimensions(0,1080));
        assert(out::dimensions(4096,4096)&&!out::dimensions(4098,1080)&&!out::dimensions(1919,1080));
        assert(out::source_dimensions(1919,1079)&&!out::source_dimensions(15,1080));
        assert(out::bitrate(0)&&out::bitrate(100000)&&out::bitrate(12340000)&&out::bitrate(200000000));
        assert(!out::bitrate(99999)&&!out::bitrate(200000001));
        assert(out::recommended_bitrate(1920,1080,60,1)==17420000);
        assert(out::recommended_bitrate(1920,1080,60,2)==11200000);
        assert(out::recommended_bitrate(1280,720,30,1)==3870000);
        assert(out::recommended_bitrate(16,16,30,1)==250000);
        assert(out::recommended_bitrate(4096,4096,60,1)==140930000);
        assert(out::resolved_bitrate(12340000,1920,1080,30,1)==12340000);
        assert(out::recommended_bitrate(1919,1080,30,1)==0);
    }else if(!std::strcmp(mode,"pixels")){
        std::vector<uint8_t> source(16*16*4);
        for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x){auto i=(y*16+x)*4;source[i]=x*16;source[i+1]=y*16;source[i+2]=200;source[i+3]=17;}
        std::vector<uint8_t> output(32*16*4+16,0x5a);uint8_t* pixels=output.data()+8;
        assert(out::resample_rgba(source.data(),source.size(),16,16,pixels,32*16*4,32,16));
        for(unsigned y=0;y<16;++y)for(unsigned x=0;x<32;++x){size_t i=(y*32+x)*4;
            assert(pixels[i+3]==255);
            if(x<8||x>=24)assert(!pixels[i]&&!pixels[i+1]&&!pixels[i+2]);
            else assert(pixels[i]==(x-8)*16&&pixels[i+1]==y*16&&pixels[i+2]==200);
        }
        for(size_t i=0;i<8;++i)assert(output[i]==0x5a&&output[output.size()-1-i]==0x5a);
        output.resize(32*32*4);assert(out::resample_rgba(source.data(),source.size(),16,16,output.data(),output.size(),32,32));
        assert(output[0]==0&&output[4]==4&&output[31*4]==240&&output[(31*32)*4+1]==240);
        assert(!out::resample_rgba(source.data(),source.size()-1,16,16,output.data(),output.size(),32,32));
        assert(!out::resample_rgba(source.data(),source.size(),16,16,output.data(),10,32,32));
        assert(!out::resample_rgba(source.data(),source.size(),16,16,source.data(),source.size(),32,16));
    }else if(!std::strcmp(mode,"odd_pixels")){
        std::vector<uint8_t> source(17*19*4,90),output(16*18*4);
        assert(out::resample_rgba(source.data(),source.size(),17,19,output.data(),output.size(),16,18));
        const auto fitted=out::fit(17,19,16,18);assert(fitted.width==16&&fitted.height==17);
        assert(output[0]==90&&output[(16*16)*4]==90&&output[(17*16)*4]==0&&output.back()==255);
    }else if(!std::strcmp(mode,"legacy")||!std::strcmp(mode,"options")){
        const char* profile="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        qm::Options o{};o.width=17;o.height=19;o.output_width=32;o.output_height=18;o.video_bitrate=12340000;
        qm::Job j{};std::strcpy(j.id,"0123456789abcdef0123456789abcdef");j.descriptor=descriptor();j.options=o;
        if(!std::strcmp(mode,"legacy")){
            // Exact original wire layout: write a v1 body and header, then
            // open it through the production migration/recovery parser.
            j.options.width=1280;j.options.height=720;j.options.video_bitrate=16000000;
            uint8_t raw[8192]{};qm::detail::Writer w{raw+qm::header_bytes,sizeof(raw)-qm::header_bytes};qm::detail::encode(w,j,1);assert(w.ok);
            std::memcpy(raw,"IDMPQ001",8);qm::detail::put32(raw+8,1);qm::detail::put32(raw+12,qm::header_bytes);std::memcpy(raw+16,profile,64);qm::detail::put64(raw+80,7);qm::detail::put32(raw+88,1);qm::detail::put32(raw+92,w.at);qm::detail::put64(raw+96,qm::detail::checksum(raw+qm::header_bytes,w.at,qm::detail::checksum(raw,96)));
            char path[4096]{};std::snprintf(path,sizeof(path),"%s/queue-v1.bin",argv[2]);int fd=::open(path,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0&&::write(fd,raw,qm::header_bytes+w.at)==static_cast<ssize_t>(qm::header_bytes+w.at));::close(fd);
        }
        qm::Queue queue;assert(queue.open(argv[2],profile)==qm::Error::ok);
        if(!std::strcmp(mode,"legacy")){assert(queue.count()==1);const auto* old=queue.at(0);assert(old->options.output_width==0&&old->options.output_height==0&&old->options.width==1280&&old->options.video_bitrate==16000000);}
        char id[33]{};assert(queue.enqueue(descriptor(),o,id)==qm::Error::ok);o.output_width=640;o.video_bitrate=32000000;
        assert(queue.find(id)->options.output_width==32&&queue.find(id)->options.output_height==18&&queue.find(id)->options.video_bitrate==12340000);
        queue.close();assert(queue.open(argv[2],profile)==qm::Error::ok);
        const auto* restored=queue.find(id);assert(restored&&restored->options.width==17&&restored->options.height==19&&restored->options.output_width==32&&restored->options.output_height==18&&restored->options.video_bitrate==12340000);
        assert(queue.retry(id)==qm::Error::invalid_state);assert(queue.cancel(id)==qm::Error::ok&&queue.retry(id)==qm::Error::ok);assert(queue.find(id)->options.output_width==32&&queue.find(id)->options.video_bitrate==12340000);
    }else return 2;
    std::puts("ok");
}
'''


@pytest.fixture(scope="module")
def policy_executable(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("C++ compiler required")
    root = tmp_path_factory.mktemp("mp4-output-policy")
    source, binary = root / "policy.cpp", root / "policy"
    source.write_text(POLICY)
    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I",
        str(ROOT / "client-presentation/native"), str(source), "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize("mode", ["policy", "pixels", "odd_pixels", "legacy", "options"])
def test_output_pixels_recommendation_and_immutable_legacy_queue(policy_executable, tmp_path, mode):
    root = tmp_path / "queue"
    root.mkdir(mode=0o700)
    result = subprocess.run([str(policy_executable), mode, str(root)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
