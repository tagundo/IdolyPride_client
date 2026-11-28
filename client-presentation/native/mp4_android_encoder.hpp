// SPDX-License-Identifier: AGPL-3.0-or-later
// Independent Android MediaCodec adapter. Included once by the Android native bridge.
#pragma once
#include "mp4_encoder_api.h"
#include <jni.h>
#include <climits>
#include <cstring>
#include <pthread.h>
#include <cstdlib>
#include <new>

// Opaque sRGB RGBA8 to limited-range BT.709 I420, done natively before the
// frame reaches Java (as Elichika's exporter does). Java then stages 1.5
// bytes per pixel instead of 4, and its encoder thread only copies planes.
// Kept in this header: the Android package pins at most 64 source files.
namespace idoly_mp4_i420 {
// OfflineMp4Math.transferTable(): sRGB-encoded 8-bit to BT.709 OETF, rounded.
constexpr uint8_t srgb_to_709[256]={
    0,0,1,1,1,2,2,2,3,3,3,4,4,5,5,5,
    6,6,7,7,8,9,9,10,10,11,12,13,13,14,15,16,
    17,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,
    32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,
    48,49,50,51,52,53,55,56,57,58,59,60,61,62,63,64,
    65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80,
    81,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,
    98,99,100,101,103,104,105,106,107,108,109,110,111,112,113,114,
    115,116,117,119,120,121,122,123,124,125,126,127,128,129,130,131,
    133,134,135,136,137,138,139,140,141,142,143,144,145,147,148,149,
    150,151,152,153,154,155,156,157,159,160,161,162,163,164,165,166,
    167,168,169,171,172,173,174,175,176,177,178,179,180,182,183,184,
    185,186,187,188,189,190,191,193,194,195,196,197,198,199,200,201,
    203,204,205,206,207,208,209,210,211,213,214,215,216,217,218,219,
    220,221,223,224,225,226,227,228,229,230,231,233,234,235,236,237,
    238,239,240,242,243,244,245,246,247,248,249,251,252,253,254,255};

inline size_t bytes(uint32_t width,uint32_t height){return static_cast<size_t>(width)*height*3/2;}
inline int clamp(int value,int lower,int upper){return value<lower?lower:value>upper?upper:value;}

// Rows are read first to last with row_bytes stride; Y, then U, then V, with
// no padding. Bit-identical to OfflineMp4Math.rgbaToI420 (alpha is ignored).
inline bool valid(const uint8_t*rgba,size_t row_bytes,uint32_t width,uint32_t height,const uint8_t*out,size_t out_bytes){
    return rgba&&out&&width>=2&&height>=2&&!(width&1)&&!(height&1)&&row_bytes>=static_cast<size_t>(width)*4
        &&out_bytes==bytes(width,height);
}
// Converts the row pairs starting at rows first..last-2 (even row indices).
inline void convert_rows(const uint8_t*rgba,size_t row_bytes,uint32_t width,uint32_t height,uint8_t*out,uint32_t first,uint32_t last){
    const size_t pixels=static_cast<size_t>(width)*height;
    uint8_t*const u=out+pixels;uint8_t*const v=u+pixels/4;
    for(uint32_t y=first;y<last;y+=2){
        const uint8_t*const rows[2]={rgba+static_cast<size_t>(y)*row_bytes,rgba+static_cast<size_t>(y+1)*row_bytes};
        uint8_t*const luma[2]={out+static_cast<size_t>(y)*width,out+static_cast<size_t>(y+1)*width};
        const size_t chroma_row=static_cast<size_t>(y/2)*(width/2);
        for(uint32_t x=0;x<width;x+=2){
            int red=0,green=0,blue=0;
            for(int dy=0;dy<2;++dy)for(uint32_t dx=0;dx<2;++dx){
                const uint8_t*const p=rows[dy]+static_cast<size_t>(x+dx)*4;
                const int r=srgb_to_709[p[0]],g=srgb_to_709[p[1]],b=srgb_to_709[p[2]];
                luma[dy][x+dx]=static_cast<uint8_t>(clamp(16+((47*r+157*g+16*b+128)>>8),16,235));
                red+=r;green+=g;blue+=b;
            }
            u[chroma_row+x/2]=static_cast<uint8_t>(clamp(128+((-26*red-86*green+112*blue+512)>>10),16,240));
            v[chroma_row+x/2]=static_cast<uint8_t>(clamp(128+((112*red-102*green-10*blue+512)>>10),16,240));
        }
    }
}
inline bool from_rgba(const uint8_t*rgba,size_t row_bytes,uint32_t width,uint32_t height,uint8_t*out,size_t out_bytes){
    if(!valid(rgba,row_bytes,width,height,out,out_bytes))return false;
    convert_rows(rgba,row_bytes,width,height,out,0,height);return true;
}
// Same bytes. A large frame (4K, 8K) splits its independent row pairs across
// up to four threads, so the game thread does not convert it alone. A band
// whose thread cannot start runs on the caller.
inline bool from_rgba_parallel(const uint8_t*rgba,size_t row_bytes,uint32_t width,uint32_t height,uint8_t*out,size_t out_bytes){
    if(!valid(rgba,row_bytes,width,height,out,out_bytes))return false;
    constexpr uint32_t maximum_bands=4;
    const uint32_t pairs=height/2,bands=static_cast<size_t>(width)*height>=2000000&&pairs>=maximum_bands?maximum_bands:1;
    struct Band {const uint8_t*rgba;size_t row_bytes;uint32_t width,height,first,last;uint8_t*out;pthread_t thread;bool started;};
    Band band[maximum_bands]{};
    for(uint32_t i=0;i<bands;++i){
        const uint32_t first=pairs*i/bands*2,last=pairs*(i+1)/bands*2;
        band[i]={rgba,row_bytes,width,height,first,last,out,pthread_t{},false};
    }
    auto run=[](void*value)->void*{const Band*b=static_cast<const Band*>(value);
        convert_rows(b->rgba,b->row_bytes,b->width,b->height,b->out,b->first,b->last);return nullptr;};
    for(uint32_t i=1;i<bands;++i)band[i].started=pthread_create(&band[i].thread,nullptr,run,&band[i])==0;
    run(&band[0]);
    for(uint32_t i=1;i<bands;++i){if(band[i].started)pthread_join(band[i].thread,nullptr);else run(&band[i]);}
    return true;
}
} // namespace idoly_mp4_i420

namespace idoly_mp4_android {
namespace {
struct JavaBridge {
    JavaVM *vm = nullptr;
    jclass type = nullptr; // Process-owned global ref, registered by the app class loader.
    jmethodID create = nullptr, append = nullptr, poll = nullptr, finish = nullptr;
    jmethodID cancel = nullptr, terminal = nullptr, error = nullptr;
};
JavaBridge bridge;
pthread_mutex_t bridge_lock = PTHREAD_MUTEX_INITIALIZER;

class MutexGuard {
public:
    explicit MutexGuard(pthread_mutex_t *lock) : lock_(lock) { pthread_mutex_lock(lock_); }
    ~MutexGuard() { pthread_mutex_unlock(lock_); }
private:
    pthread_mutex_t *lock_;
    MutexGuard(const MutexGuard &) = delete;
    MutexGuard &operator=(const MutexGuard &) = delete;
};

void error_text(char *destination, size_t capacity, const char *code) {
    if (!destination || capacity == 0) return;
    const size_t length = std::strlen(code);
    const size_t copied = length < capacity - 1 ? length : capacity - 1;
    std::memcpy(destination, code, copied); destination[copied] = '\0';
}

class Environment {
public:
    explicit Environment(JavaVM *vm) : vm_(vm) {
        if (!vm_) return;
        jint result = vm_->GetEnv(reinterpret_cast<void **>(&env_), JNI_VERSION_1_6);
        if (result == JNI_EDETACHED) {
#ifdef __ANDROID__
            result = vm_->AttachCurrentThread(&env_, nullptr);
#else
            result = vm_->AttachCurrentThread(reinterpret_cast<void **>(&env_), nullptr);
#endif
            attached_ = result == JNI_OK;
        }
        if (result != JNI_OK) env_ = nullptr;
    }
    ~Environment() { if (attached_) vm_->DetachCurrentThread(); }
    JNIEnv *get() const { return env_; }
private:
    JavaVM *vm_;
    JNIEnv *env_ = nullptr;
    bool attached_ = false;
};

bool exception(JNIEnv *env) {
    if (!env->ExceptionCheck()) return false;
    // Exception text may contain private filesystem paths; C ABI only returns stable codes.
    env->ExceptionClear(); return true;
}

struct Encoder {
    pthread_mutex_t lock;
    JavaBridge java;
    jobject object = nullptr;
    uint32_t width = 0, height = 0;
    // Native I420 staging for the frame being offered. A RETRY resubmits the
    // same frame, so its conversion is reused until Java accepts it.
    uint8_t *i420 = nullptr;
    size_t i420_bytes = 0;
    const uint8_t *converted_source = nullptr;
    uint64_t converted_index = 0;
    bool converted = false;
    char error[192] = {};
};

bool java_error(JNIEnv *env, Encoder *encoder) {
    if (!exception(env)) return false;
    error_text(encoder->error, sizeof(encoder->error), "encoder_java_exception"); return true;
}

bool registered(JavaBridge *copy) {
    MutexGuard guard(&bridge_lock);
    *copy = bridge; return copy->vm && copy->type;
}

void read_error(JNIEnv *env, Encoder *encoder, char *target, size_t capacity) {
    jstring value = static_cast<jstring>(env->CallObjectMethod(encoder->object, encoder->java.error));
    if (java_error(env, encoder)) { error_text(target, capacity, encoder->error); return; }
    if (value) {
        const char *text = env->GetStringUTFChars(value, nullptr);
        if (text) {
            if (*text) error_text(encoder->error, sizeof(encoder->error), text);
            env->ReleaseStringUTFChars(value, text);
        } else exception(env);
        env->DeleteLocalRef(value);
    }
    error_text(target, capacity, encoder->error);
}
} // namespace

extern "C" JNIEXPORT jboolean JNICALL
Java_game_qualiarts_idolypride_localserver_mp4_OfflineMp4Encoder_registerEncoderClass(
        JNIEnv *env, jclass, jclass encoder_class) {
    if (!encoder_class) return JNI_FALSE;
    MutexGuard guard(&bridge_lock);
    if (bridge.type) return env->IsSameObject(bridge.type, encoder_class) ? JNI_TRUE : JNI_FALSE;
    JavaBridge candidate;
    if (env->GetJavaVM(&candidate.vm) != JNI_OK) return JNI_FALSE;
    candidate.type = static_cast<jclass>(env->NewGlobalRef(encoder_class));
    if (exception(env) || !candidate.type) return JNI_FALSE;
    candidate.create = env->GetStaticMethodID(candidate.type, "create",
        "(IIIIIIIIJJLjava/lang/String;Ljava/lang/String;Ljava/lang/String;I)"
        "Lgame/qualiarts/idolypride/localserver/mp4/OfflineMp4Encoder;");
    if (!exception(env)) candidate.append = env->GetMethodID(candidate.type, "appendI420", "(Ljava/nio/ByteBuffer;J)I");
    if (!exception(env)) candidate.poll = env->GetMethodID(candidate.type, "nativeStatus", "()[J");
    if (!exception(env)) candidate.finish = env->GetMethodID(candidate.type, "finish", "()I");
    if (!exception(env)) candidate.cancel = env->GetMethodID(candidate.type, "cancel", "()V");
    if (!exception(env)) candidate.terminal = env->GetMethodID(candidate.type, "isTerminal", "()Z");
    if (!exception(env)) candidate.error = env->GetMethodID(candidate.type, "errorCode", "()Ljava/lang/String;");
    bool failed = exception(env) || !candidate.create || !candidate.append || !candidate.poll
        || !candidate.finish || !candidate.cancel || !candidate.terminal || !candidate.error;
    if (failed) { env->DeleteGlobalRef(candidate.type); return JNI_FALSE; }
    bridge = candidate; return JNI_TRUE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeInitializeEncoder(
        JNIEnv *env, jclass type, jclass encoder_class) {
    return Java_game_qualiarts_idolypride_localserver_mp4_OfflineMp4Encoder_registerEncoderClass(
            env, type, encoder_class);
}

extern "C" IDMP4EncoderHandle IDMP4EncoderCreate(const IDMP4EncoderConfig *config,
        char *error_code, size_t capacity) {
    error_text(error_code, capacity, "");
    if (!config || config->struct_size != sizeof(IDMP4EncoderConfig) || config->abi_version != 1
            || config->reserved != 0 || !config->pcm_f32_path || !config->partial_path || !config->final_path
            || config->width > INT_MAX || config->height > INT_MAX || config->fps_num > INT_MAX
            || config->fps_den > INT_MAX || config->video_bitrate > INT_MAX || config->audio_bitrate > INT_MAX
            || config->audio_sample_rate > INT_MAX || config->audio_channels > INT_MAX
            || config->audio_sample_frames > LLONG_MAX || config->video_frame_count > LLONG_MAX) {
        error_text(error_code, capacity, "invalid_encoder_config"); return nullptr;
    }
    JavaBridge java;
    if (!registered(&java)) { error_text(error_code, capacity, "encoder_java_not_registered"); return nullptr; }
    Environment scope(java.vm); JNIEnv *env = scope.get();
    if (!env) { error_text(error_code, capacity, "encoder_jvm_unavailable"); return nullptr; }
    jstring pcm = env->NewStringUTF(config->pcm_f32_path);
    jstring partial = pcm ? env->NewStringUTF(config->partial_path) : nullptr;
    jstring final = partial ? env->NewStringUTF(config->final_path) : nullptr;
    if (exception(env) || !final) {
        if (pcm) env->DeleteLocalRef(pcm);
        if (partial) env->DeleteLocalRef(partial);
        if (final) env->DeleteLocalRef(final);
        error_text(error_code, capacity, "encoder_path_allocation_failed"); return nullptr;
    }
    jobject instance = env->CallStaticObjectMethod(java.type, java.create,
        static_cast<jint>(config->width), static_cast<jint>(config->height),
        static_cast<jint>(config->fps_num), static_cast<jint>(config->fps_den),
        static_cast<jint>(config->video_bitrate), static_cast<jint>(config->audio_sample_rate),
        static_cast<jint>(config->audio_channels), static_cast<jint>(config->audio_bitrate),
        static_cast<jlong>(config->audio_sample_frames), static_cast<jlong>(config->video_frame_count),
        pcm, partial, final, static_cast<jint>(config->video_codec));
    env->DeleteLocalRef(pcm); env->DeleteLocalRef(partial); env->DeleteLocalRef(final);
    if (exception(env) || !instance) { error_text(error_code, capacity, "encoder_create_failed"); return nullptr; }
    void *storage = std::malloc(sizeof(Encoder));
    Encoder *encoder = storage ? new (storage) Encoder{} : nullptr;
    if (!encoder) {
        env->CallVoidMethod(instance, java.cancel); exception(env); env->DeleteLocalRef(instance);
        error_text(error_code, capacity, "encoder_allocation_failed"); return nullptr;
    }
    if (pthread_mutex_init(&encoder->lock, nullptr) != 0) {
        env->CallVoidMethod(instance, java.cancel); exception(env); env->DeleteLocalRef(instance);
        encoder->~Encoder(); std::free(encoder);
        error_text(error_code, capacity, "encoder_lock_allocation_failed"); return nullptr;
    }
    encoder->java = java; encoder->width = config->width; encoder->height = config->height;
    encoder->i420_bytes = idoly_mp4_i420::bytes(config->width, config->height);
    encoder->i420 = encoder->i420_bytes ? static_cast<uint8_t *>(std::malloc(encoder->i420_bytes)) : nullptr;
    if (!encoder->i420) {
        env->CallVoidMethod(instance, java.cancel); exception(env); env->DeleteLocalRef(instance);
        pthread_mutex_destroy(&encoder->lock); encoder->~Encoder(); std::free(encoder);
        error_text(error_code, capacity, "encoder_frame_allocation_failed"); return nullptr;
    }
    encoder->object = env->NewGlobalRef(instance);
    if (exception(env) || !encoder->object) {
        env->CallVoidMethod(instance, java.cancel); exception(env);
        env->DeleteLocalRef(instance); pthread_mutex_destroy(&encoder->lock); std::free(encoder->i420);
        encoder->~Encoder(); std::free(encoder);
        error_text(error_code, capacity, "encoder_global_reference_failed"); return nullptr;
    }
    env->DeleteLocalRef(instance); return encoder;
}

extern "C" int IDMP4EncoderAppendFrame(IDMP4EncoderHandle handle, const uint8_t *rgba,
        size_t row_bytes, uint64_t frame_index) {
    if (!handle || !rgba || frame_index > LLONG_MAX || row_bytes > INT_MAX) return IDMP4_ERROR;
    Encoder *encoder = static_cast<Encoder *>(handle); MutexGuard guard(&encoder->lock);
    if (row_bytes < static_cast<size_t>(encoder->width) * 4 || encoder->height == 0
            || row_bytes > static_cast<size_t>(LLONG_MAX) / encoder->height) return IDMP4_ERROR;
    // Convert once per offered frame; Java copies the planes into its own slot.
    if (!encoder->converted || encoder->converted_index != frame_index || encoder->converted_source != rgba) {
        encoder->converted = false;
        if (!idoly_mp4_i420::from_rgba_parallel(rgba, row_bytes, encoder->width, encoder->height,
                encoder->i420, encoder->i420_bytes)) return IDMP4_ERROR;
        encoder->converted = true; encoder->converted_index = frame_index; encoder->converted_source = rgba;
    }
    Environment scope(encoder->java.vm); JNIEnv *env = scope.get();
    if (!env) return IDMP4_ERROR;
    jobject bytes = env->NewDirectByteBuffer(encoder->i420, static_cast<jlong>(encoder->i420_bytes));
    if (java_error(env, encoder) || !bytes) return IDMP4_ERROR;
    jint result = env->CallIntMethod(encoder->object, encoder->java.append, bytes, static_cast<jlong>(frame_index));
    env->DeleteLocalRef(bytes);
    if (java_error(env, encoder)) return IDMP4_ERROR;
    if (result == IDMP4_ACCEPTED) encoder->converted = false;
    return result == IDMP4_ACCEPTED || result == IDMP4_RETRY ? result : IDMP4_ERROR;
}

extern "C" int IDMP4EncoderPoll(IDMP4EncoderHandle handle, IDMP4EncoderStatus *status) {
    if (!handle || !status || status->struct_size != sizeof(IDMP4EncoderStatus) || status->abi_version != 1)
        return IDMP4_ERROR;
    Encoder *encoder = static_cast<Encoder *>(handle); MutexGuard guard(&encoder->lock);
    Environment scope(encoder->java.vm); JNIEnv *env = scope.get(); if (!env) return IDMP4_ERROR;
    jlongArray fields = static_cast<jlongArray>(env->CallObjectMethod(encoder->object, encoder->java.poll));
    if (java_error(env, encoder) || !fields) return IDMP4_ERROR;
    if (env->GetArrayLength(fields) != 7) { env->DeleteLocalRef(fields); return IDMP4_ERROR; }
    jlong values[7]; env->GetLongArrayRegion(fields, 0, 7, values); env->DeleteLocalRef(fields);
    if (java_error(env, encoder)) return IDMP4_ERROR;
    for (jlong value : values) if (value < 0) return IDMP4_ERROR;
    if (values[0] < IDMP4_STARTING || values[0] > IDMP4_FAILED || values[1] > 3) return IDMP4_ERROR;
    IDMP4EncoderStatus result = {};
    result.struct_size = sizeof(result); result.abi_version = 1;
    // Terminal phases are only exposed after worker cleanup has finished.
    result.phase = (values[0] >= IDMP4_COMPLETED && values[0] != IDMP4_CANCELLING && !values[6])
        ? static_cast<uint32_t>(IDMP4_FINISHING) : static_cast<uint32_t>(values[0]);
    result.queued_frames = static_cast<uint32_t>(values[1]);
    result.submitted_frames = static_cast<uint64_t>(values[2]); result.encoded_frames = static_cast<uint64_t>(values[3]);
    result.audio_frames = static_cast<uint64_t>(values[4]); result.bytes_written = static_cast<uint64_t>(values[5]);
    read_error(env, encoder, result.error_code, sizeof(result.error_code));
    *status = result; return IDMP4_ACCEPTED;
}

extern "C" int IDMP4EncoderFinish(IDMP4EncoderHandle handle) {
    if (!handle) return IDMP4_ERROR;
    Encoder *encoder = static_cast<Encoder *>(handle); MutexGuard guard(&encoder->lock);
    Environment scope(encoder->java.vm); JNIEnv *env = scope.get(); if (!env) return IDMP4_ERROR;
    jint result = env->CallIntMethod(encoder->object, encoder->java.finish);
    return java_error(env, encoder) ? IDMP4_ERROR : result;
}

extern "C" void IDMP4EncoderCancel(IDMP4EncoderHandle handle) {
    if (!handle) return;
    Encoder *encoder = static_cast<Encoder *>(handle); MutexGuard guard(&encoder->lock);
    Environment scope(encoder->java.vm); JNIEnv *env = scope.get(); if (!env) return;
    env->CallVoidMethod(encoder->object, encoder->java.cancel); java_error(env, encoder);
}

extern "C" int IDMP4EncoderDestroy(IDMP4EncoderHandle handle) {
    if (!handle) return IDMP4_ACCEPTED;
    Encoder *encoder = static_cast<Encoder *>(handle);
    {
        MutexGuard guard(&encoder->lock);
        // A caller abandons the handle after ERROR; release the native frame
        // buffer then. RETRY keeps everything for the next Destroy.
        const auto abandon = [encoder] {
            std::free(encoder->i420); encoder->i420 = nullptr; encoder->i420_bytes = 0; encoder->converted = false;
            return IDMP4_ERROR;
        };
        Environment scope(encoder->java.vm); JNIEnv *env = scope.get(); if (!env) return abandon();
        jboolean done = env->CallBooleanMethod(encoder->object, encoder->java.terminal);
        if (java_error(env, encoder)) return abandon();
        if (!done) return IDMP4_RETRY;
        env->DeleteGlobalRef(encoder->object); encoder->object = nullptr;
    }
    // The C ABI requires the caller to stop concurrent producers/pollers before Destroy.
    pthread_mutex_destroy(&encoder->lock); std::free(encoder->i420); encoder->~Encoder(); std::free(encoder); return IDMP4_ACCEPTED;
}
} // namespace idoly_mp4_android
