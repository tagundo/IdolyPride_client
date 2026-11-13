#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../resource_transfer_display.h"

int main(void) {
    char output[2048];
    IDTransferView old={0};
    old.served=4118226035LL;old.received=0;
    old.requests=old.failures=old.hits=old.misses=-1;
    id_transfer_display(&old,output,sizeof output);
    assert(strstr(output,"로컬→게임 3.8 GiB · CDN→서버 0 B"));
    assert(strstr(output,"게임 HTTP 요청 확인 불가 · 실패 확인 불가"));
    assert(strstr(output,"세부 상태 수신 대기"));
    puts(output);
    old.activeKnown=1;
    id_transfer_display(&old,output,sizeof output);
    assert(strstr(output,"최근 실패: 세부 상태 수신 대기"));
    old.currentKnown=old.failedKnown=1;
    id_transfer_display(&old,output,sizeof output);
    assert(strstr(output,"최근 요청: 없음\n최근 실패: 없음"));

    IDTransferView active={0};
    active.served=4096;active.received=1024;active.requests=12;active.failures=3;active.hits=9;active.misses=2;
    active.activeKnown=active.hasActive=1;
    active.current=(IDTransferEntry){1,0,37123,"object","waiting_cache","adv_bond_ai_01_01.txt",0,0,"pending",0};
    active.lastFailed=(IDTransferEntry){1,503,0,"object","failed","character_body.ab",0,"octo_cache_miss","cache_miss",0};
    id_transfer_display(&active,output,sizeof output);
    assert(strstr(output,"로컬→게임 4.0 KiB · CDN→서버 1.0 KiB"));
    assert(strstr(output,"게임 HTTP 요청 12 · 실패 3 · 캐시 적중 9 · 미보관 2"));
    assert(strstr(output,"현재 요청: adv_bond_ai_01_01.txt · 응답 대기 · 캐시 대기"));
    assert(strstr(output,"경과 37.1초"));
    assert(strstr(output,"최근 실패: character_body.ab · HTTP 503 · 실패 · 미보관 · octo_cache_miss"));
    puts(output);

    /* A later cache success must not obscure the separately supplied failure. */
    active.hasActive=0;active.current.httpStatus=200;active.current.phase="completed";active.current.cacheResult="cache_hit";
    id_transfer_display(&active,output,sizeof output);
    assert(strstr(output,"최근 요청: adv_bond_ai_01_01.txt · HTTP 200 · 완료 · 캐시 파일"));
    assert(strstr(output,"최근 실패: character_body.ab · HTTP 503"));
    assert(!strstr(output,"경과"));
    for (int code=404;code<=409;code+=5) {
        active.lastFailed.httpStatus=code;
        id_transfer_display(&active,output,sizeof output);
        assert(strstr(output,code==404 ? "HTTP 404" : "HTTP 409"));
    }
    active.lastFailed.causeCode="upstream_dns";
    id_transfer_display(&active,output,sizeof output);
    assert(strstr(output," · upstream_dns"));

    active.current.objectName="https://example.test/path?token=secret";
    active.current.cacheKey="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    active.current.httpStatus=999;active.current.phase="future_phase";active.current.cacheResult="future_cache";
    active.current.errorCode="https://example.test/?secret=1";
    active.current.causeCode="?secret=1";
    active.lastFailed.present=0;active.requests=-7;
    id_transfer_display(&active,output,sizeof output);
    assert(!strstr(output,"example.test") && !strstr(output,"secret") && !strstr(output,"?"));
    assert(strstr(output,"0123456789abcdef") && strstr(output,"HTTP 확인 불가"));
    assert(strstr(output,"상태 확인 불가") && strstr(output,"오류 코드 확인 불가"));
    assert(strstr(output,"원인 코드 확인 불가"));
    assert(strstr(output,"게임 HTTP 요청 확인 불가"));
    assert(!id_transfer_plain("abc\nsecret",160));
    assert(!id_transfer_cache_key("0"));
    char shortOutput[9];memset(shortOutput,'x',sizeof shortOutput);
    id_transfer_display(&active,shortOutput,sizeof shortOutput);
    assert(shortOutput[sizeof shortOutput-1]==0);
    puts("RESOURCE_TRANSFER_DISPLAY_PASS");
    return 0;
}
