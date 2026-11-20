// SPDX-License-Identifier: AGPL-3.0-or-later
// Independent Android MediaCodec adapter. Included once by the Android native bridge.
#pragma once
#include "mp4_encoder_api.h"
#include <jni.h>
#include <climits>
#include <cstring>
#include <mutex>
#include <new>

namespace idoly_mp4_android {
namespace {
struct JavaBridge {
    JavaVM *vm = nullptr;
    jclass type = nullptr; // Process-owned global ref, registered by the app class loader.
    jmethodID create = nullptr, append = nullptr, poll = nullptr, finish = nullptr;
    jmethodID cancel = nullptr, terminal = nullptr, error = nullptr;
};
JavaBridge bridge;
std::mutex bridge_lock;

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
    std::mutex lock;
    JavaBridge java;
    jobject object = nullptr;
    uint32_t width = 0, height = 0;
    char error[192] = {};
};

bool java_error(JNIEnv *env, Encoder *encoder) {
    if (!exception(env)) return false;
    error_text(encoder->error, sizeof(encoder->error), "encoder_java_exception"); return true;
}

bool registered(JavaBridge *copy) {
    std::lock_guard<std::mutex> guard(bridge_lock);
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
    std::lock_guard<std::mutex> guard(bridge_lock);
    if (bridge.type) return env->IsSameObject(bridge.type, encoder_class) ? JNI_TRUE : JNI_FALSE;
    JavaBridge candidate;
    if (env->GetJavaVM(&candidate.vm) != JNI_OK) return JNI_FALSE;
    candidate.type = static_cast<jclass>(env->NewGlobalRef(encoder_class));
    if (exception(env) || !candidate.type) return JNI_FALSE;
    candidate.create = env->GetStaticMethodID(candidate.type, "create",
        "(IIIIIIIIJJLjava/lang/String;Ljava/lang/String;Ljava/lang/String;I)"
        "Lgame/qualiarts/idolypride/localserver/mp4/OfflineMp4Encoder;");
    if (!exception(env)) candidate.append = env->GetMethodID(candidate.type, "appendFrame", "(Ljava/nio/ByteBuffer;IJ)I");
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
    Encoder *encoder = new (std::nothrow) Encoder;
    if (!encoder) {
        env->CallVoidMethod(instance, java.cancel); exception(env); env->DeleteLocalRef(instance);
        error_text(error_code, capacity, "encoder_allocation_failed"); return nullptr;
    }
    encoder->java = java; encoder->width = config->width; encoder->height = config->height;
    encoder->object = env->NewGlobalRef(instance);
    if (exception(env) || !encoder->object) {
        env->CallVoidMethod(instance, java.cancel); exception(env);
        env->DeleteLocalRef(instance); delete encoder;
        error_text(error_code, capacity, "encoder_global_reference_failed"); return nullptr;
    }
    env->DeleteLocalRef(instance); return encoder;
}

extern "C" int IDMP4EncoderAppendFrame(IDMP4EncoderHandle handle, const uint8_t *rgba,
        size_t row_bytes, uint64_t frame_index) {
    if (!handle || !rgba || frame_index > LLONG_MAX || row_bytes > INT_MAX) return IDMP4_ERROR;
    Encoder *encoder = static_cast<Encoder *>(handle); std::lock_guard<std::mutex> guard(encoder->lock);
    if (row_bytes < static_cast<size_t>(encoder->width) * 4 || encoder->height == 0
            || row_bytes > static_cast<size_t>(LLONG_MAX) / encoder->height) return IDMP4_ERROR;
    size_t length = row_bytes * (encoder->height - 1) + static_cast<size_t>(encoder->width) * 4;
    Environment scope(encoder->java.vm); JNIEnv *env = scope.get();
    if (!env) return IDMP4_ERROR;
    jobject bytes = env->NewDirectByteBuffer(const_cast<uint8_t *>(rgba), static_cast<jlong>(length));
    if (java_error(env, encoder) || !bytes) return IDMP4_ERROR;
    jint result = env->CallIntMethod(encoder->object, encoder->java.append, bytes,
                                    static_cast<jint>(row_bytes), static_cast<jlong>(frame_index));
    env->DeleteLocalRef(bytes);
    if (java_error(env, encoder)) return IDMP4_ERROR;
    return result == IDMP4_ACCEPTED || result == IDMP4_RETRY ? result : IDMP4_ERROR;
}

extern "C" int IDMP4EncoderPoll(IDMP4EncoderHandle handle, IDMP4EncoderStatus *status) {
    if (!handle || !status || status->struct_size != sizeof(IDMP4EncoderStatus) || status->abi_version != 1)
        return IDMP4_ERROR;
    Encoder *encoder = static_cast<Encoder *>(handle); std::lock_guard<std::mutex> guard(encoder->lock);
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
    Encoder *encoder = static_cast<Encoder *>(handle); std::lock_guard<std::mutex> guard(encoder->lock);
    Environment scope(encoder->java.vm); JNIEnv *env = scope.get(); if (!env) return IDMP4_ERROR;
    jint result = env->CallIntMethod(encoder->object, encoder->java.finish);
    return java_error(env, encoder) ? IDMP4_ERROR : result;
}

extern "C" void IDMP4EncoderCancel(IDMP4EncoderHandle handle) {
    if (!handle) return;
    Encoder *encoder = static_cast<Encoder *>(handle); std::lock_guard<std::mutex> guard(encoder->lock);
    Environment scope(encoder->java.vm); JNIEnv *env = scope.get(); if (!env) return;
    env->CallVoidMethod(encoder->object, encoder->java.cancel); java_error(env, encoder);
}

extern "C" int IDMP4EncoderDestroy(IDMP4EncoderHandle handle) {
    if (!handle) return IDMP4_ACCEPTED;
    Encoder *encoder = static_cast<Encoder *>(handle);
    {
        std::lock_guard<std::mutex> guard(encoder->lock);
        Environment scope(encoder->java.vm); JNIEnv *env = scope.get(); if (!env) return IDMP4_ERROR;
        jboolean done = env->CallBooleanMethod(encoder->object, encoder->java.terminal);
        if (java_error(env, encoder)) return IDMP4_ERROR;
        if (!done) return IDMP4_RETRY;
        env->DeleteGlobalRef(encoder->object); encoder->object = nullptr;
    }
    // The C ABI requires the caller to stop concurrent producers/pollers before Destroy.
    delete encoder; return IDMP4_ACCEPTED;
}
} // namespace idoly_mp4_android
