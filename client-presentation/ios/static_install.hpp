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
    struct SectionSpan { uintptr_t begin,end; };
    SectionSpan text_sections[128]{};unsigned text_section_count=0;
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
            const uint32_t section_count=read<uint32_t>(const_cast<unsigned char *>(bytes),offset+64);
            if (section_count>128 || section_count>(length-72)/80) return false;
            if (!std::memcmp(bytes+offset+8,"__TEXT\0\0\0\0\0\0\0\0\0\0",16)) {
                if (va!=0 || text.size) return false; text={image_base,span,protection};
                for (unsigned j=0;j<section_count;++j) {
                    const size_t at=offset+72+j*80;
                    const uintptr_t start=read<uint64_t>(const_cast<unsigned char *>(bytes),at+32);
                    const uintptr_t extent=read<uint64_t>(const_cast<unsigned char *>(bytes),at+40);
                    if (start>span || extent>span-start || text_section_count==128) return false;
                    text_sections[text_section_count++]={start,start+extent};
                }
            }
            if (!std::memcmp(bytes+offset+8,"__DATA\0\0\0\0\0\0\0\0\0\0",16)) data={image_base+va,span,protection};
        }
        offset+=length;
    }
    if (!uuid || offset!=32+size) return false;
    for (const auto &entry:pin::all) {
        const uintptr_t address=image_base+entry.rva;
        if (!within(text,address,16,5)) return false;
        if (!entry.gateway) {
            if (entry.relay_in || entry.relay_out || std::memcmp(reinterpret_cast<void *>(address),entry.bytes,16)) return false;
            continue;
        }
        uint32_t displaced=0;std::memcpy(&displaced,entry.bytes,4);
        const bool compare_branch=(displaced&0x7e000000u)==0x34000000u;
        const bool relayed=entry.relay_in || entry.relay_out;
        if (relayed) {
            if (!entry.relay_in || entry.relay_out!=entry.relay_in+4 || (entry.relay_in&3)
                    || compare_branch || !within(text,image_base+entry.relay_in,8,5)) return false;
            for (unsigned j=0;j<text_section_count;++j)
                if (entry.relay_in<text_sections[j].end && text_sections[j].begin<entry.relay_out+4) return false;
            for (const auto &other:pin::all)
                if ((entry.relay_in<other.rva+16 && other.rva<entry.relay_out+4)
                        || (other.gateway && entry.relay_in<other.gateway+32 && other.gateway<entry.relay_out+4)) return false;
            uint32_t incoming=0,outgoing=0;
            if (!arm_branch(entry.relay_in,entry.gateway,&incoming)
                    || !arm_branch(entry.relay_out,entry.rva+4,&outgoing)
                    || read<uint32_t>(reinterpret_cast<void *>(image_base+entry.relay_in),0)!=incoming
                    || read<uint32_t>(reinterpret_cast<void *>(image_base+entry.relay_out),0)!=outgoing) return false;
        }
        if (!within(text,image_base+entry.gateway,compare_branch?32:28,5)
                || !within(data,image_base+entry.slot,8,3) || (entry.slot&7)
                || read<uintptr_t>(reinterpret_cast<void *>(image_base+entry.slot),0)) return false;
        uint32_t branch,back;
        if (!arm_branch(entry.rva,relayed?entry.relay_in:entry.gateway,&branch)
                || !arm_branch(entry.gateway+24,relayed?entry.relay_out:entry.rva+4,&back)
                || read<uint32_t>(reinterpret_cast<void *>(address),0)!=branch
                || std::memcmp(reinterpret_cast<void *>(address+4),entry.bytes+4,12)) return false;
        const intptr_t page=static_cast<intptr_t>(entry.slot>>12)-static_cast<intptr_t>(entry.gateway>>12);
        if (page<-(1<<20) || page>=(1<<20)) return false;
        uint32_t words[8]={0x90000010u | ((static_cast<uint32_t>(page)&3)<<29)
            | (((static_cast<uint32_t>(page)>>2)&0x7ffff)<<5),
            0x91000210u | static_cast<uint32_t>((entry.slot&0xfff)<<10),0xc8dffe10u,0xb4000050u,0xd61f0200u,0,back};
        words[5]=displaced;
        if (compare_branch) {
            if ((displaced&31u)==16u || (displaced&31u)==17u) return false;
            int32_t immediate=static_cast<int32_t>((displaced>>5)&0x7ffffu);
            if (immediate&(1<<18)) immediate-=1<<19;
            const intptr_t taken=static_cast<intptr_t>(entry.rva)+static_cast<intptr_t>(immediate)*4;
            if (taken<0 || !arm_branch(entry.gateway+28,static_cast<uintptr_t>(taken),&words[7])) return false;
            words[5]=(displaced&~(0x7ffffu<<5))|(2u<<5);
        }
        if (std::memcmp(reinterpret_cast<void *>(image_base+entry.gateway),words,compare_branch?32:28)) return false;
    }
    return true;
}
struct Hook { const pin::Entry *entry; void *replacement; void **original; };
// All objects read here are zero/constant-initialized; this path does not
// invoke Unity or make network calls. The constructor may arm a mapped image
// synchronously so startup FontAsset.Awake cannot race the worker scheduler.
const void *mapped_unity_header() {
    constexpr const char suffix[]="/UnityFramework.framework/UnityFramework";
    const void *header=nullptr;
    const unsigned count=_dyld_image_count();
    for (unsigned i=0;i<count;++i) {
        const char *name=_dyld_get_image_name(i);if (!name) continue;
        if (::strstr(name,"/AppKit.framework/")) desktop_host=true;
        const size_t length=std::strlen(name);
        if (length>=sizeof suffix-1 && !std::strcmp(name+length-(sizeof suffix-1),suffix))
            header=_dyld_get_image_header(i);
    }
    return header;
}
void *install(void *) {
    const void *header=nullptr;
    for (unsigned attempt=0;attempt<900 && !header;++attempt) {
        header=mapped_unity_header();
        if (!header) pause_ms(200);
    }
    if (!header) { set_state("unsupported"); return nullptr; }
    image_base=reinterpret_cast<uintptr_t>(header);
    if (!verify_static_image(header)) { set_state("unsupported"); return nullptr; }
    if(!mp4_prepare_native_clock(image_base)){set_state("unsupported");return nullptr;}
    load_calls();
    shared_cache_load_calls();
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
        HOOK(costume_sorted,costume_sorted_hook,costume_sorted_original),
        HOOK(font_awake,font_awake_hook,font_awake_original),
        HOOK(sound_bgm_volume,sound_bgm_volume_hook,sound_bgm_volume_original),
        HOOK(sound_bgm_soundable,sound_bgm_soundable_hook,sound_bgm_soundable_original),
        HOOK(sound_se_volume,sound_se_volume_hook,sound_se_volume_original),
        HOOK(sound_se_soundable,sound_se_soundable_hook,sound_se_soundable_original),
        HOOK(sound_voice_volume,sound_voice_volume_hook,sound_voice_volume_original),
        HOOK(sound_voice_soundable,sound_voice_soundable_hook,sound_voice_soundable_original),
        HOOK(sound_bind,sound_bind_hook,sound_bind_original),
        HOOK(sound_save,sound_save_hook,sound_save_original),
        HOOK(shared_setup,shared_setup_hook,shared_setup_original),
        HOOK(shared_is_cached,shared_is_cached_hook,shared_is_cached_original),
        HOOK(shared_file_path,shared_file_path_hook,shared_file_path_original),
        HOOK(shared_pre_download,shared_pre_download_hook,shared_pre_download_original),
        HOOK(shared_downloader_update,shared_downloader_update_hook,shared_downloader_update_original),
        HOOK(mp4_presenter_update,mp4_presenter_update_hook,mp4_presenter_update_original),
        HOOK(mp4_capture_pass,mp4_capture_pass_hook,mp4_capture_pass_original),
        HOOK(mp4_end_camera,mp4_end_camera_hook,mp4_end_camera_original),
        HOOK(mp4_graph_mode,mp4_graph_mode_hook,mp4_graph_mode_original),
        HOOK(mp4_brain_delta,mp4_brain_delta_hook,mp4_brain_delta_original),
        HOOK(mp4_core_camera,mp4_core_camera_hook,mp4_core_camera_original),
        HOOK(mp4_player_initialize,mp4_player_initialize_hook,mp4_player_initialize_original),
        HOOK(mp4_photography_initialize,mp4_photography_initialize_hook,mp4_photography_initialize_original),
        HOOK(mp4_photography_player_initialize,mp4_photography_player_initialize_hook,mp4_photography_player_initialize_original),
        HOOK(mp4_photography_end,mp4_photography_end_hook,mp4_photography_end_original),
        HOOK(mp4_native_time,mp4_native_time_hook,mp4_native_time_original),
        HOOK(mp4_brain_update,mp4_brain_update_hook,mp4_brain_update_original),
        HOOK(mp4_shader_set,mp4_shader_set_hook,mp4_shader_set_original),
        HOOK(mp4_shader_reset,mp4_shader_reset_hook,mp4_shader_reset_original),
        HOOK(mp4_actor_process,mp4_actor_process_hook,mp4_actor_process_original),
        HOOK(mp4_actor_burst,mp4_actor_burst_hook,mp4_actor_burst_original),
    };
#undef HOOK
    for (auto &hook:hooks) {
        if (!hook.entry->gateway || !hook.entry->slot) { set_state("init_failed"); return nullptr; }
        *hook.original=reinterpret_cast<void *>(image_base+hook.entry->gateway+20);
    }
    if (!rotation::ready_for_publish() || !preview_ui.ready() || !korean_fallback.ready() || !korean_list_factory.ready() || !sound_tracker.ready()) { set_state("init_failed"); return nullptr; }
    if(!mp4_install_native_clock_api()){set_state("init_failed");return nullptr;}
    // All originals are valid before the first replacement is visible. Any
    // concurrent invocation during publication takes the original path.
    for (auto &hook:hooks) __atomic_store_n(reinterpret_cast<uintptr_t *>(image_base+hook.entry->slot),
        reinterpret_cast<uintptr_t>(hook.replacement),__ATOMIC_RELEASE);
    mp4_actor_managed_installed.store(true,std::memory_order_release);
    mp4_actor_burst_installed.store(true,std::memory_order_release);
    shared_hooks_ready.store(true,std::memory_order_release);
    pthread_mutex_lock(&status_mutex);
    state.fps=state.quality=state.resolution=state.aa=state.shadow=state.expanded=true;
    pthread_mutex_unlock(&status_mutex);
    ready.store(true,std::memory_order_release); return nullptr;
}
