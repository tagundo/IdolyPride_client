#include "../media_policy.hpp"
#include "../../ios/media_json.hpp"
#include <cassert>
#include <string>
#include <climits>
using namespace idoly::presentation;
int main() {
    MediaPolicySettings policy;
    assert(!policy.known() && !policy.use_master_costume_order());
    assert(!policy.accept(2,0,true) && !policy.accept(1,-1,true));
    assert(policy.accept(1,0,false) && policy.known() && !policy.use_master_costume_order());
    assert(!policy.accept(1,0,true) && !policy.use_master_costume_order());
    assert(policy.accept(1,1,true) && policy.use_master_costume_order());
    assert(!policy.accept(1,0,false) && policy.use_master_costume_order());
    assert(policy.accept(1,1,true));
    assert(policy.accept(1,INT64_MAX,false) && !policy.use_master_costume_order());
    assert(!policy.accept(1,INT64_MAX,true));
    const std::string valid = "{\"schema\":1,\"revision\":9,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"title\"}";
    MediaConfigMessage result;
    assert(decode_media_settings(valid.c_str(),&result));
    assert(result.revision==9 && !result.hide_video_mv && result.mv_sort==0 && result.outfit_sort==3);
    for (size_t end=0;end<valid.size();++end) assert(!decode_media_settings(valid.substr(0,end).c_str(),&result));
    const char *mv[] = {"recent","old","title","id"}, *outfits[] = {"original","recent","old","title","id"};
    for (int i=0;i<4;++i) for (int j=0;j<5;++j) {
        std::string json="{\"outfit_sort\":\""+std::string(outfits[j])+"\",\"mv_sort\":\""+mv[i]+"\",\"hide_video_mv\":true,\"revision\":9223372036854775807,\"schema\":1}";
        assert(decode_media_settings(json.c_str(),&result));
        assert(result.mv_sort==i && result.outfit_sort==j && result.hide_video_mv && result.revision==INT64_MAX);
    }
    auto bad = [&](const std::string &from,const std::string &to) {
        std::string json=valid;json.replace(json.find(from),from.size(),to);
        result.revision=42;assert(!decode_media_settings(json.c_str(),&result));assert(result.revision==42);
    };
    for (const char *value:{"-1","1.0","1e0","true","2"}) bad("\"schema\":1","\"schema\":"+std::string(value));
    for (const char *value:{"-1","9.0","9e0","true","9223372036854775808","09"}) bad("\"revision\":9","\"revision\":"+std::string(value));
    for (const char *value:{"0","null","\"false\""}) bad("false",value);
    bad("\"recent\"","\"original\"");bad("\"title\"","\"unknown\"");
    bad("\"schema\":1","\"schema\":1,\"schema\":1");
    bad("\"schema\"","\"account\"");
    assert(!decode_media_settings((valid+"{}").c_str(),&result));
    assert(!decode_media_settings(std::string(8193,' ').c_str(),&result));
    assert(!decode_media_settings(nullptr,&result) && !decode_media_settings(valid.c_str(),nullptr));
}
