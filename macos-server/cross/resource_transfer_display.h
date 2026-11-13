#ifndef IDOLY_RESOURCE_TRANSFER_DISPLAY_H
#define IDOLY_RESOURCE_TRANSFER_DISPLAY_H

/* Cached public counters only. No URLs, filesystem reads, or network work. */
typedef unsigned long IDTransferSize;
extern int snprintf(char *, IDTransferSize, const char *, ...);
extern int strcmp(const char *, const char *);

typedef struct {
    int present, httpStatus;
    long long elapsedMS;
    const char *kind, *phase, *objectName, *cacheKey, *errorCode, *cacheResult, *causeCode;
} IDTransferEntry;

typedef struct {
    long long served, received, requests, failures, hits, misses;
    int activeKnown, hasActive, currentKnown, failedKnown;
    IDTransferEntry current, lastFailed;
} IDTransferView;

static inline int id_transfer_plain(const char *value, IDTransferSize limit) {
    if (!value || !*value) return 0;
    for (IDTransferSize i=0;;++i) {
        unsigned char c=(unsigned char)value[i];
        if (!c) return i<=limit;
        if (i>=limit || !((c>='a' && c<='z') || (c>='A' && c<='Z')
            || (c>='0' && c<='9') || c=='_' || c=='-' || c=='.')) return 0;
    }
}

static inline int id_transfer_cache_key(const char *value) {
    if (!value) return 0;
    for (int i=0;i<64;++i)
        if (!((value[i]>='0' && value[i]<='9') || (value[i]>='a' && value[i]<='f'))) return 0;
    return value[64]==0;
}

static inline void id_transfer_count(long long value, char *output, IDTransferSize capacity) {
    if (value<0) snprintf(output,capacity,"확인 불가");
    else snprintf(output,capacity,"%lld",value);
}

static inline void id_transfer_bytes(long long value, char *output, IDTransferSize capacity) {
    if (value<0) snprintf(output,capacity,"확인 불가");
    else if (value<1024) snprintf(output,capacity,"%lld B",value);
    else if (value<1048576) snprintf(output,capacity,"%.1f KiB",(double)value/1024.0);
    else if (value<1073741824) snprintf(output,capacity,"%.1f MiB",(double)value/1048576.0);
    else snprintf(output,capacity,"%.1f GiB",(double)value/1073741824.0);
}

static inline const char *id_transfer_phase(const char *value) {
    if (!id_transfer_plain(value,24)) return "상태 확인 불가";
    if (!strcmp(value,"received")) return "접수";
    if (!strcmp(value,"resolving")) return "목록 조회";
    if (!strcmp(value,"waiting_cache")) return "캐시 대기";
    if (!strcmp(value,"sending")) return "전송 중";
    if (!strcmp(value,"completed")) return "완료";
    if (!strcmp(value,"failed")) return "실패";
    return "상태 확인 불가";
}

static inline const char *id_transfer_cache(const char *value) {
    if (!id_transfer_plain(value,24)) return "캐시 확인 불가";
    if (!strcmp(value,"pending")) return "캐시 확인 중";
    if (!strcmp(value,"cache_hit")) return "캐시 파일";
    if (!strcmp(value,"upstream")) return "CDN 받기";
    if (!strcmp(value,"cache_miss")) return "미보관";
    return "캐시 확인 불가";
}

static inline void id_transfer_entry(const IDTransferEntry *entry, int active,
        char *output, IDTransferSize capacity) {
    const char *name="리소스 확인 불가";
    if (entry->kind && !strcmp(entry->kind,"manifest")) name="목록";
    else if (id_transfer_plain(entry->objectName,160)) name=entry->objectName;
    else if (id_transfer_cache_key(entry->cacheKey)) name=entry->cacheKey;
    char http[48],error[256],elapsed[64];error[0]=elapsed[0]=0;
    if (entry->httpStatus==0) snprintf(http,sizeof http,"응답 대기");
    else if (entry->httpStatus>=100 && entry->httpStatus<=599) snprintf(http,sizeof http,"HTTP %d",entry->httpStatus);
    else snprintf(http,sizeof http,"HTTP 확인 불가");
    if (entry->errorCode && *entry->errorCode)
        snprintf(error,sizeof error," · %s",id_transfer_plain(entry->errorCode,64) ? entry->errorCode : "오류 코드 확인 불가");
    if (entry->causeCode && *entry->causeCode) {
        IDTransferSize used=0;while (used<sizeof error && error[used]) ++used;
        if (used<sizeof error) snprintf(error+used,sizeof error-used," · %s",
            id_transfer_plain(entry->causeCode,64) ? entry->causeCode : "원인 코드 확인 불가");
    }
    if (active && entry->elapsedMS>=0)
        snprintf(elapsed,sizeof elapsed," · 경과 %.1f초",(double)entry->elapsedMS/1000.0);
    snprintf(output,capacity,"%s · %s · %s · %s%s%s",name,http,
        id_transfer_phase(entry->phase),id_transfer_cache(entry->cacheResult),error,elapsed);
}

static inline void id_transfer_display(const IDTransferView *view, char *output, IDTransferSize capacity) {
    char served[64],received[64],requests[48],failures[48],hits[48],misses[48],current[768],failed[768];
    id_transfer_bytes(view->served,served,sizeof served);id_transfer_bytes(view->received,received,sizeof received);
    id_transfer_count(view->requests,requests,sizeof requests);id_transfer_count(view->failures,failures,sizeof failures);
    id_transfer_count(view->hits,hits,sizeof hits);id_transfer_count(view->misses,misses,sizeof misses);
    if (view->current.present) id_transfer_entry(&view->current,view->hasActive,current,sizeof current);
    else snprintf(current,sizeof current,"%s",view->currentKnown ? "없음" : "세부 상태 수신 대기");
    if (view->lastFailed.present) id_transfer_entry(&view->lastFailed,0,failed,sizeof failed);
    else snprintf(failed,sizeof failed,"%s",view->failedKnown ? "없음" : "세부 상태 수신 대기");
    snprintf(output,capacity,"로컬→게임 %s · CDN→서버 %s\n게임 HTTP 요청 %s · 실패 %s · 캐시 적중 %s · 미보관 %s\n%s: %s\n최근 실패: %s",
        served,received,requests,failures,hits,misses,view->hasActive ? "현재 요청" : "최근 요청",current,failed);
}

#endif
