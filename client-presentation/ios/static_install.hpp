// All executable patches are made before packaging/signing, never at runtime.
struct DarwinSegment { uintptr_t begin=0, size=0; unsigned protection=0; };
bool within(const DarwinSegment &segment, uintptr_t address, size_t size, unsigned protection) {
    return (segment.protection&protection)==protection && address>=segment.begin
        && size<=segment.size && address-segment.begin<=segment.size-size;
}
bool arm_branch(uintptr_t from, uintptr_t to, uint32_t *instruction) {
    const intptr_t delta=static_cast<intptr_t>(to)-static_cast<intptr_t>(from);
    if ((delta&3) || delta<-(1ll<<27) || delta>=(1ll<<27)) return false;
    *instruction=0x14000000u | (static_cast<uint32_t>(delta/4)&0x3ffffffu); return true;
}
bool verify_static_image(const void *header) {
    // The packager locks the complete source SHA; this checks UUID, every call
    // site's prefix, branch, gateway and pristine mutable pointer before arming.
    const auto *bytes=static_cast<const unsigned char *>(header);
    if (read<uint32_t>(const_cast<void *>(header),0)!=0xfeedfacf
            || read<uint32_t>(const_cast<void *>(header),4)!=0x0100000c) return false;
    uint32_t count=read<uint32_t>(const_cast<void *>(header),16), size=read<uint32_t>(const_cast<void *>(header),20);
    if (count>128 || size>65536 || size<8) return false;
    DarwinSegment text,data; bool uuid=false;
    size_t offset=32;
    for (unsigned i=0;i<count;++i) {
        if (offset+8>32+size) return false;
        const uint32_t command=read<uint32_t>(const_cast<unsigned char *>(bytes),offset);
        const uint32_t length=read<uint32_t>(const_cast<unsigned char *>(bytes),offset+4);
        if (length<8 || offset+length>32+size) return false;
        if (command==0x1b && length==24) uuid=!std::memcmp(bytes+offset+8,pin::uuid,16);
        if (command==0x19 && length>=72) {
            const uintptr_t va=read<uint64_t>(const_cast<unsigned char *>(bytes),offset+24);
            const uintptr_t span=read<uint64_t>(const_cast<unsigned char *>(bytes),offset+32);
            const unsigned protection=read<uint32_t>(const_cast<unsigned char *>(bytes),offset+60);
            if (!std::strcmp(reinterpret_cast<const char *>(bytes+offset+8),"__TEXT")) {
                if (va!=0) return false; text={image_base,span,protection};
            }
            if (!std::strcmp(reinterpret_cast<const char *>(bytes+offset+8),"__DATA")) data={image_base+va,span,protection};
        }
        offset+=length;
    }
    if (!uuid || offset!=32+size) return false;
    for (const auto &entry:pin::all) {
        const uintptr_t address=image_base+entry.rva;
        if (!within(text,address,16,5)) return false;
        if (!entry.gateway) {
            if (std::memcmp(reinterpret_cast<void *>(address),entry.bytes,16)) return false;
            continue;
        }
        if (!within(text,image_base+entry.gateway,28,5)
                || !within(data,image_base+entry.slot,8,3) || (entry.slot&7)
                || read<uintptr_t>(reinterpret_cast<void *>(image_base+entry.slot),0)) return false;
        uint32_t branch,back;
        if (!arm_branch(entry.rva,entry.gateway,&branch) || !arm_branch(entry.gateway+24,entry.rva+4,&back)
                || read<uint32_t>(reinterpret_cast<void *>(address),0)!=branch
                || std::memcmp(reinterpret_cast<void *>(address+4),entry.bytes+4,12)) return false;
        const intptr_t page=static_cast<intptr_t>(entry.slot>>12)-static_cast<intptr_t>(entry.gateway>>12);
        if (page<-(1<<20) || page>=(1<<20)) return false;
        uint32_t words[7]={0x90000010u | ((static_cast<uint32_t>(page)&3)<<29)
            | (((static_cast<uint32_t>(page)>>2)&0x7ffff)<<5),
            0x91000210u | static_cast<uint32_t>((entry.slot&0xfff)<<10),0xc8dffe10u,0xb4000050u,0xd61f0200u,0,back};
        std::memcpy(&words[5],entry.bytes,4);
        if (std::memcmp(reinterpret_cast<void *>(image_base+entry.gateway),words,sizeof words)) return false;
    }
    return true;
}
struct Hook { const pin::Entry *entry; void *replacement; void **original; };
void *install(void *) {
    const void *header=nullptr;
    constexpr const char suffix[]="/UnityFramework.framework/UnityFramework";
    for (unsigned attempt=0;attempt<900 && !header;++attempt) {
        const unsigned count=_dyld_image_count();
        for (unsigned i=0;i<count;++i) {
            const char *name=_dyld_get_image_name(i); if (!name) continue;
            if (::strstr(name,"/AppKit.framework/")) desktop_host=true;
            const size_t length=std::strlen(name);
            if (length>=sizeof suffix-1 && !std::strcmp(name+length-(sizeof suffix-1),suffix)) {
                header=_dyld_get_image_header(i);
            }
        }
        if (!header) pause_ms(200);
    }
    if (!header) { set_state("unsupported"); return nullptr; }
    image_base=reinterpret_cast<uintptr_t>(header);
    if (!verify_static_image(header)) { set_state("unsupported"); return nullptr; }
    load_calls();
#define HOOK(entry, replacement, original) {&pin::entry,reinterpret_cast<void *>(replacement),reinterpret_cast<void **>(&original)}
    Hook hooks[]={
        HOOK(q_set,quality_set_hook,quality_set_original), HOOK(q_apply,quality_apply_hook,quality_apply_original),
        HOOK(q_init,quality_init_hook,quality_init_original), HOOK(q_update,quality_update_hook,quality_update_original),
        HOOK(app_fps_set,app_fps_set_hook,app_fps_set_original),
        HOOK(rt_update,rt_hook,rt_original), HOOK(limited_resolution,limited_hook,limited_original),
        HOOK(scene_main_update,main_update_hook,scene_main_update_original), HOOK(scene_main_reset,main_reset_hook,scene_main_reset_original),
        HOOK(scene_pano_update,pano_update_hook,scene_pano_update_original), HOOK(scene_pano_reset,pano_reset_hook,scene_pano_reset_original),
        HOOK(target_update,target_update_hook,target_update_original), HOOK(target_late,target_late_hook,target_late_original),
        HOOK(fov_get,fov_get_hook,fov_get_original), HOOK(fov_set,fov_set_hook,fov_set_original),
        HOOK(focal_get,focal_get_hook,focal_get_original), HOOK(focal_set,focal_set_hook,focal_set_original),
        HOOK(aa_init,aa_hook,aa_original), HOOK(shadow_update,shadow_hook,shadow_original),
        HOOK(rotation_wait,rotation::wait_hook,rotation::original_wait),
        HOOK(rotation_wait_label,rotation::wait_label_hook,rotation::original_wait_label),
        HOOK(rotation_wait_simple,rotation::wait_simple_hook,rotation::original_wait_simple),
        HOOK(rotation_wait_preview,rotation::wait_preview_hook,rotation::original_wait_preview),
        HOOK(orientation_internal_move,rotation::internal_move_hook,rotation::original_internal_move),
        HOOK(orientation_starts_portrait_ready,rotation::starts_portrait_hook,rotation::original_starts_portrait),
        HOOK(orientation_starts_landscape_ready,rotation::starts_landscape_hook,rotation::original_starts_landscape),
        HOOK(orientation_fixed_portrait_ready,rotation::fixed_portrait_hook,rotation::original_fixed_portrait),
        HOOK(orientation_fixed_landscape_ready,rotation::fixed_landscape_hook,rotation::original_fixed_landscape),
        HOOK(orientation_after_ready,rotation::after_hook,rotation::original_after),
        HOOK(mv_ui_initialize,mv_ui_initialize_hook,mv_ui_initialize_original),
        HOOK(preview_ui_bind,preview_ui_bind_hook,preview_ui_bind_original),
    };
#undef HOOK
    for (auto &hook:hooks) {
        if (!hook.entry->gateway || !hook.entry->slot) { set_state("init_failed"); return nullptr; }
        *hook.original=reinterpret_cast<void *>(image_base+hook.entry->gateway+20);
    }
    if (!rotation::ready_for_publish() || !preview_ui.ready()) { set_state("init_failed"); return nullptr; }
    // All originals are valid before the first replacement is visible. Any
    // concurrent invocation during publication takes the original path.
    for (auto &hook:hooks) __atomic_store_n(reinterpret_cast<uintptr_t *>(image_base+hook.entry->slot),
        reinterpret_cast<uintptr_t>(hook.replacement),__ATOMIC_RELEASE);
    pthread_mutex_lock(&status_mutex);
    state.fps=state.quality=state.resolution=state.aa=state.shadow=state.expanded=true;
    pthread_mutex_unlock(&status_mutex);
    ready.store(true,std::memory_order_release); return nullptr;
}
