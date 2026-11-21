// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#ifndef IDOLY_DARWIN_BRIDGE
#include <cstdint>
#endif
namespace idoly_mp4_game {
// Receiver and Type must come from the already verified timeline camera and
// pinned controller descriptor. This helper never discovers a camera, creates
// a component, or substitutes a different output camera.
struct CameraOwnerCalls {
    bool(*is_type)(void*,const char*)=nullptr;
    bool(*alive)(void*)=nullptr;
    uint32_t(*retain)(void*)=nullptr;
    void*(*retained)(uint32_t)=nullptr;
    void(*release)(uint32_t)=nullptr;
    void*(*get_component)(void*,void*,const void*)=nullptr;
    void*(*controller_camera)(void*,const void*)=nullptr;
};
struct CameraOwnerResult {
    // Nonzero handle transfers ownership to the caller. Retain/use the target
    // in the selected-scene adapter before releasing this temporary handle.
    uint32_t handle=0;
    const char* error="selected_camera_controller_absent";
};
inline CameraOwnerResult recover_camera_controller(void* camera,void* controller_type,const CameraOwnerCalls& api) {
    if(!api.is_type||!api.alive||!api.retain||!api.retained||!api.release||!api.get_component||!api.controller_camera)
        return {0,"camera_owner_api_unavailable"};
    struct Root {
        const CameraOwnerCalls& api;uint32_t handle=0;
        Root(const CameraOwnerCalls& a,void* value):api(a),handle(value?api.retain(value):0){}
        ~Root(){if(handle)api.release(handle);}
        void* get()const{return handle?api.retained(handle):nullptr;}
        uint32_t transfer(){const uint32_t value=handle;handle=0;return value;}
    };
    try {
        if(!api.is_type(camera,"UnityEngine.Camera")||!api.alive(camera))return {0,"selected_output_camera_invalid"};
        if(!api.is_type(controller_type,"System.Type"))return {0,"selected_controller_type_unavailable"};
        Root receiver(api,camera),type(api,controller_type);
        if(receiver.get()!=camera)return {0,"selected_camera_handle_failed"};
        if(type.get()!=controller_type)return {0,"selected_controller_type_handle_failed"};
        void* value=api.get_component(receiver.get(),type.get(),nullptr);
        if(!value)return {0,"selected_camera_controller_absent"};
        Root result(api,value);
        if(result.get()!=value)return {0,"selected_camera_controller_handle_failed"};
        if(!api.is_type(value,"VL.Rendering.VLSRPCameraController")||!api.alive(value))
            return {0,"selected_camera_controller_wrong_type"};
        if(api.controller_camera(value,nullptr)!=receiver.get()||!api.alive(receiver.get()))
            return {0,"selected_camera_controller_camera_mismatch"};
        return {result.transfer(),"none"};
    } catch(...) {return {0,"selected_camera_controller_lookup_exception"};}
}
} // namespace idoly_mp4_game
