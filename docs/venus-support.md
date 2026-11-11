# VENUS 배틀: 개인 보존 응답의 읽기 경로

`api.Pvp`가 VENUS 배틀 서비스입니다. 로컬 처리기는 같은 계정이 보존한 Top 구성 응답으로 `Top`, `ListOpponent`와 `Quest.Top.pvpInfo`를 제공합니다. 선택한 상대의 원본 모델 응답이 있을 때만 `ListAsset`도 제공합니다. `Start`, 순위 목록, 대전 결과·레이팅 계산, 보상, 도전 횟수·티켓 소모는 구현 범위 밖입니다. 이 변경은 소스와 합성 자료의 회귀 검사 범위이며, 새 APK 배포나 실제 상대 선택 화면·대전 통과를 뜻하지 않습니다. 현재 보유 자료에 실제 같은 계정의 완전한 Top 응답이 생긴 것도 아닙니다.

시즌과 배틀 퀘스트·상대 목록은 서버의 동적 데이터입니다. 보존한 202개 마스터 테이블에는 이를 대신할 시즌·상대 테이블이 없었습니다. `Pvp.Top.topResult.pvpQuest`를 사용하며 일반 `Master.Quest`의 메인 퀘스트 ID로 대체하지 않습니다. 공개 응답에서 확인된 최신 과거 시즌은 `pvp-season-184`로, 2026-10-24 00:00~11-01 23:59:59 JST입니다. 이는 현재 시즌의 근거가 아니며 기간이나 다음 시즌을 추정해 연장하지 않습니다.

## 개인 카탈로그

기본 위치는 `master-json` 상위 디렉터리의 `pvp-catalog.json`입니다. `Pvp(..., catalog_path=...)`로 지정할 수도 있습니다. 계정과 상대 정보가 포함되므로 개인 보존 디렉터리에 두고 Git·공개 릴리스·공유 서버 payload에 넣지 않습니다. 인증 토큰이나 요청 메타데이터는 이 형식에 필요하지 않습니다.

형식은 다음과 같습니다. 응답과 요청은 전송 암호화를 해제한 protobuf 원문입니다. 아래 값은 형식 설명용이며 실행 가능한 시즌이나 계정 데이터가 아닙니다.

```json
{
  "schema": 1,
  "schema_sha256": "<local normalized schema SHA-256>",
  "master_version": "<captured Master.Get.masterTag.version>",
  "captured_at_ms": 0,
  "owner": {
    "server_user_id": "<same local account>",
    "public_user_id": "<same local account>"
  },
  "responses": [{
    "method": "/api.Pvp/Top",
    "request_b64": "",
    "request_sha256": "<SHA-256 of decoded request>",
    "response_b64": "<base64 protobuf>",
    "response_sha256": "<SHA-256 of decoded response>"
  }]
}
```

필수 응답은 `User.Get`, `Master.Get`, `Quest.Top`, `Pvp.Top` 네 개이며, 요청은 모두 빈 요청이어야 합니다. `Pvp.ListOpponent`와 상대별 `Pvp.ListAsset`은 선택적으로 보존합니다. `ListOpponent`가 없으면 `Top`에서 실제 관측된 상대만 반환합니다. 선택적 목록에만 있는 상대도 원본 목록 그대로 검증하며, 서로 다른 상대의 상충하는 정보를 합치지 않습니다.

모델 응답이 없는 상대도 Top·상대 목록에서 읽을 수 있습니다. 그 상대의 `ListAsset`을 요청하면 고정된 `FAILED_PRECONDITION` 사유 `opponent_appearance_missing`으로 거절합니다. 보존한 어느 목록에도 없는 상대는 `INVALID_ARGUMENT`입니다. 다른 상대의 모델을 복사하거나 누락된 응답·의상·헤어를 생성하지 않습니다. 변환기와 오프라인 복원 도구도 실제 캡처 레코드만 저장합니다.

선택적으로 **제공된** `ListAsset`은 모두 검증합니다. 요청의 실제 시즌·상대 식별자, 양수 `deckNumber`, 다섯 상대 모델과 카드별 외형 호환성이 맞아야 합니다. 잘못된 모델 응답을 무시하고 Top만 제공하는 우회는 허용하지 않습니다. 일부 상대 모델만 보존한 경우에도, 보존된 응답 하나가 잘못되면 Top·상대 목록과 다른 상대의 모델 조회까지 전체 읽기를 거절합니다.

카탈로그는 최대 32 MiB, 각 요청·응답은 최대 16 MiB, 응답 레코드는 최대 256개입니다. 로드할 때 base64·SHA-256·중복 레코드·스키마·마스터 버전과 팩 메타데이터를 확인합니다. 해시는 보존 중 변경을 찾는 장치이며 공식 서버의 디지털 서명은 아닙니다. 개인 수집기가 동일한 세션에서 얻은 원본 요청과 응답을 연결해야 합니다.

로컬 프로필의 영구 식별자 두 개, 현재 `User.Get` 스냅샷, 보존 `User.Get`, 카탈로그 소유자 정보가 모두 일치해야 합니다. 메인 11지역의 마스터 퀘스트 목록과 실제 완료 기록도 확인합니다. 필수 Top 구성 누락·잘못된 제공 응답·다른 계정·마스터 불일치·미래 수집 시각·종료된 시즌은 `FAILED_PRECONDITION`으로 거절합니다. 당시 도전 횟수와 순위는 보존한 `Quest.Top` 값 그대로이며 새 횟수나 순위를 계산하지 않습니다. 날짜를 바꾸어 시즌을 계속 활성화하지 않습니다.

## 모델과 상태 보존

자신의 `ListAsset.characterAssets`는 현재 로컬 계정의 저장된 5인 덱에서 계산합니다. 의상·헤어·포토·액세서리의 실제 보유와 슬롯·수량·마스터 참조를 기존 `Quest.ListAsset`과 같은 코드로 확인합니다. 상대 모델은 보존한 `opponentCharacterAssets`를 사용하고 상대 카드의 슬롯별 캐릭터와 의상·헤어의 호환성을 대조합니다. 다른 계정의 덱을 자신의 덱으로 복사하지 않습니다.

보존 응답의 `commonResponse`에는 공식 서버에서 적용되던 계정 갱신이 있을 수 있어 제거하고 빈 값으로 반환합니다. 그 밖의 알려지지 않은 protobuf 필드는 유지합니다. 요청을 반복하거나 서버를 재시작해도 DB의 계정·덱·소지품·세션·설정·레슨 시계·다른 프로필을 변경하지 않습니다. 오류에는 개인 식별자나 파일 경로를 넣지 않습니다. 카탈로그가 없거나 사용할 수 없을 때 퀘스트 메뉴의 새 헤더는 표시하지 않으며, VENUS 요청은 빈 성공 응답 대신 오류를 반환합니다.

## 원본의 조회 단계 근거

원본 Android 6.1.1의 `PvpLivePlayerSelectScreenPresenter.<InitializeAsync>d__8.MoveNext` (`0x57ca5dc`)는 `SetupModelAsync` 후 `SetupListAsync`를 호출합니다. 모델 구성 (`0x57ccad0`)에서는 `LiveWindowPresenter.RequestPvpTopAsync` (`0x575eda0`)를 먼저 요청합니다. 별도의 덱 선택 단계인 `PvpLiveDeckSelectScreenPresenter.<ListLiveCharacterAssetInfoAsync>d__0.MoveNext` (`0x57c5d94`)가 `0x57c5ee4`에서 `Pvp.ListAssetAsync`를 호출합니다. 이 원본 호출 맵에 맞춰 Top 구성과 선택한 상대의 모델 조회 요건을 나눴습니다. 이는 정적 호출 순서 근거이며, 실제 계정 자료로 UI를 검증한 결과는 아닙니다.

2026-11-11의 관련 검사 87개는 모두 통과했습니다. Top 구성만 보존한 경우, 일부 모델만 있는 경우, 잘못된 제공 모델, 소유자·시즌·마스터·해금 조건, 고정 오류와 계정 상태 보존을 다룹니다. 암호화 HTTP/2 경로와 오프라인 변환·복원도 합성 자료로 검사했으며, 실제 게임·공식 계정이나 대전 엔진을 실행한 결과는 아닙니다.

기존 네이티브 배틀 엔진의 2인·10카드 입력 처리와 점수 산출은 별도 합성 입력으로 확인했습니다. 이는 실제 VENUS 퀘스트, 상대의 전체 능력·스킬·장비, 승패·레이팅·티켓·보상 규칙을 검증한 것이 아닙니다. 실제 플레이 복구에는 정상적인 `Pvp.Start` 관측 결과와 규칙 검증이 더 필요합니다. 보존 도구가 자동으로 대전을 시작하거나 티켓·보상을 조작해서는 안 됩니다.
