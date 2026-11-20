// SPDX-License-Identifier: AGPL-3.0-or-later
#pragma once
#include <jni.h>
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
extern "C" JNIEXPORT jstring JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeStatus(JNIEnv*env,jclass) {
    char json[1024]{};
    return env->NewStringUTF(IDMP4SessionStatus(json,sizeof(json))?json:"{\"phase\":\"failed\",\"error_code\":\"status_unavailable\"}");
}
extern "C" JNIEXPORT void JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeCancel(JNIEnv*,jclass){IDMP4SessionCancel();}
extern "C" JNIEXPORT jboolean JNICALL
Java_game_qualiarts_idolypride_localserver_UnifiedMP4Export_nativeReady(JNIEnv*,jclass){return IDMP4SessionReady()?JNI_TRUE:JNI_FALSE;}
