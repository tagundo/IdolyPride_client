// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <jni.h>
#include "mp4_session_api.h"
// The encoder class is registered by its app ClassLoader in the companion
// adapter. Session methods contain no lookup from an attached foreign thread.
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeConfigure(
    JNIEnv* env,jclass,jstring broker,jlong epoch,jstring capability,jstring output,jint platform) {
    if(!broker||!capability||!output||epoch<=0)return -1;
    const char* b=env->GetStringUTFChars(broker,nullptr);
    const char* c=b?env->GetStringUTFChars(capability,nullptr):nullptr;
    const char* o=c?env->GetStringUTFChars(output,nullptr):nullptr;
    int result=-1;
    if(o&&!env->ExceptionCheck())result=IDMP4SessionConfigure(b,static_cast<uint64_t>(epoch),c,o,platform);
    if(o)env->ReleaseStringUTFChars(output,o);
    if(c)env->ReleaseStringUTFChars(capability,c);
    if(b)env->ReleaseStringUTFChars(broker,b);
    // OOM remains a managed exception; Java owns its normal error handling.
    return result;
}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeStart(
    JNIEnv*,jclass,jint n,jint d,jint c,jint v,jint a) {
    if(n<=0||d<=0||c<=0||v<=0||a<=0)return -1;
    return IDMP4SessionStart(static_cast<uint32_t>(n),static_cast<uint32_t>(d),static_cast<uint32_t>(c),static_cast<uint32_t>(v),static_cast<uint32_t>(a));
}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeStartV2(
    JNIEnv*,jclass,jint n,jint d,jint c,jint v,jint a,jint w,jint h) {
    if(n<=0||d<=0||c<=0||v<0||a<=0||w<0||h<0)return -1;
    return IDMP4SessionStartV2(n,d,c,v,a,w,h);
}
extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeStatus(JNIEnv*env,jclass) {
    char json[4096]{};
    return env->NewStringUTF(IDMP4SessionStatus(json,sizeof(json))?json:"{\"phase\":\"failed\",\"error_code\":\"status_unavailable\"}");
}
extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeDiagnostics(JNIEnv*env,jclass) {
    char json[16384]{};
    return env->NewStringUTF(IDMP4SessionDiagnostics(json,sizeof(json))?json:"{\"export_trace\":{\"schema\":1,\"current_stage\":\"diagnostics\",\"last_error\":\"diagnostics_unavailable\",\"events\":[],\"modules\":{}}}");
}
extern "C" JNIEXPORT void JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeCancel(JNIEnv*,jclass){IDMP4SessionCancel();}
extern "C" JNIEXPORT void JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeSuspend(JNIEnv*,jclass,jint reason){IDMP4SessionSuspend(reason);}
extern "C" JNIEXPORT void JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeResume(JNIEnv*,jclass){IDMP4SessionResume();}
extern "C" JNIEXPORT jboolean JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeSelectionReady(JNIEnv*,jclass){return IDMP4SessionSelectionReady()?JNI_TRUE:JNI_FALSE;}
extern "C" JNIEXPORT jboolean JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeReady(JNIEnv*,jclass){return IDMP4SessionReady()?JNI_TRUE:JNI_FALSE;}

extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueConfigure(JNIEnv* env,jclass,jstring root,jstring exports){
    if(!root||!exports)return -1;
    const char* r=env->GetStringUTFChars(root,nullptr);
    const char* e=r?env->GetStringUTFChars(exports,nullptr):nullptr;
    const int result=e&&!env->ExceptionCheck()?IDMP4QueueConfigure(r,e):-1;
    if(e)env->ReleaseStringUTFChars(exports,e);
    if(r)env->ReleaseStringUTFChars(root,r);
    return result;
}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueEnqueue(JNIEnv*,jclass,jint n,jint d,jint c,jint v,jint a){
    return n>0&&d>0&&c>0&&v>0&&a>0?IDMP4QueueEnqueue(n,d,c,v,a):-1;
}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueEnqueueV2(JNIEnv*,jclass,jint n,jint d,jint c,jint v,jint a,jint w,jint h){
    return n>0&&d>0&&c>0&&v>=0&&a>0&&w>=0&&h>=0?IDMP4QueueEnqueueV2(n,d,c,v,a,w,h):-1;
}
extern "C" JNIEXPORT void JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeInvalidateQueueSelection(JNIEnv*,jclass){IDMP4QueueInvalidateSelection();}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueRun(JNIEnv*,jclass){return IDMP4QueueRun();}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueuePause(JNIEnv*,jclass){return IDMP4QueuePause();}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueResume(JNIEnv*,jclass){return IDMP4QueueResume();}
extern "C" JNIEXPORT jint JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueCommand(JNIEnv* env,jclass,jint operation,jstring id,jint position){
    if(!id)return -1;
    const char* value=env->GetStringUTFChars(id,nullptr);
    const int result=value&&!env->ExceptionCheck()?IDMP4QueueCommand(operation,value,position):-1;
    if(value)env->ReleaseStringUTFChars(id,value);
    return result;
}
extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeQueueStatus(JNIEnv* env,jclass){
    char json[16384]{};return env->NewStringUTF(IDMP4QueueStatus(json,sizeof(json))?json:
        "{\"schema\":1,\"available\":false,\"error_code\":\"queue_status_unavailable\",\"jobs\":[]}");
}
