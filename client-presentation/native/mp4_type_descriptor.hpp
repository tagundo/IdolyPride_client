#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstring>
#endif
#include "mp4_game_profile.hpp"

namespace idoly_mp4_game {
// GlobalMetadata.Initialize replaces Il2CppType.data's file definition index
// with a pointer to that definition's row. Its other eight bytes stay fixed.
// Code prefixes and type descriptors therefore have separate attestations.
struct TypeMetadataProfile {
    uintptr_t metadata_base_slot,metadata_header_slot;
    uint32_t definition_offsets[4];
    uint32_t definition_bytes;
};
inline constexpr TypeMetadataProfile android_type_metadata_profile = {
    0xa07f690,0xa07f698,{22225200,22225224,22225256,22225264},2986192
};
inline constexpr TypeMetadataProfile ios_type_metadata_profile = {
    0xa924018,0xa924020,{22256544,22256568,22256600,22256608},2993848
};
template<class BindingType>
inline bool type_descriptor_shape(const BindingType& original,const void* descriptor){
    return descriptor&&!std::memcmp(static_cast<const uint8_t*>(descriptor)+8,original.prefix+8,8);
}
inline bool type_metadata_layout(const TypeMetadataProfile& profile,uint32_t magic,uint32_t version,
                                 uint32_t definition_offset,uint32_t definition_bytes){
    if(magic!=0xfab11baf||version!=31||definition_bytes!=profile.definition_bytes
            ||!definition_bytes||definition_bytes%88)return false;
    for(uint32_t allowed:profile.definition_offsets)if(definition_offset==allowed)return true;
    return false;
}
template<class BindingType>
inline bool resolved_type_descriptor(const BindingType& original,const void* descriptor,
                                    uintptr_t definitions,uint32_t definition_bytes){
    if(!type_descriptor_shape(original,descriptor)||!definitions||!definition_bytes||definition_bytes%88
            ||definitions+definition_bytes<definitions)return false;
    uint64_t index=0;uintptr_t actual=0;
    std::memcpy(&index,original.prefix,sizeof index);std::memcpy(&actual,descriptor,sizeof actual);
    if(index>=definition_bytes/88)return false;
    const uintptr_t offset=static_cast<uintptr_t>(index)*88;
    if(definitions+offset<definitions)return false;
    return actual==definitions+offset;
}
} // namespace idoly_mp4_game
