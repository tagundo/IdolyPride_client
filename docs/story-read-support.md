# 스토리 읽기 지원 범위

`Story.Read`, `Story.ReadEvent`, `Story.ReadExtra`는 `fresh-official-2026-10-25` 공개 기본 목록에 포함된 **425개 Story ID**만 지원합니다. 정확한 ID는 [story_read_rules.py](../src/idoly_local/story_read_rules.py)에 고정되어 있습니다. 이벤트 에피소드 272개와 특별 스토리 에피소드 154개가 425개 고유 Story를 참조합니다.

대상 스키마는 6.1.1이며 정규화된 descriptor SHA-256은 `0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3`, 마스터 버전은 `961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60`입니다. 다른 버전에 이 규칙을 자동 적용하지 않습니다.

| 대상 | 고유 Story 수 | 첫 읽기 또는 건너뛰기 |
| --- | ---: | --- |
| 보상이 없는 특별 스토리 | 143 | 해당 `UserStory.statusType`을 `Read(2)`로 저장 |
| `rewardId = rd_auto;stone;;30` | 282 | `Read(2)` 저장과 무료 스톤 30개 증가를 한 트랜잭션으로 처리 |

일반 재생 완료는 `isLast=true`, 건너뛰기·다른 스토리로 이동하며 이전 스토리를 마무리하는 호출은 `false`입니다. 두 값 모두 읽음 처리 경로입니다. 클라이언트가 이미 읽음으로 판단하면 RPC를 생략합니다. 원본 6.1.1 ARM64의 `Player.ReadOrSkipStoryAsync`와 `ReadStoryAsync` 호출 흐름으로 확인했으며, 중간 ADV 파트가 끝날 때마다 읽기 요청을 보내는 구조가 아닙니다.

계정별 목록 fixture의 잠금·빈 목록이 공개 기본 목록보다 우선합니다. 특별 스토리는 계정의 `Story.ListExtra`, 계정의 `Home.Enter.extraStoryPartInfos`, 공개 기본 목록 순서로 권한을 정합니다. 직접 Story ID로 호출해도 같은 부모·에피소드 권한을 확인합니다. 요청별로 가져온 응답도 함께 검사합니다. 여러 응답의 잠금 정보가 서로 다르면 최신 상태를 추측하지 않고 `FAILED_PRECONDITION`으로 거부하며, 응답 순서나 관련 없는 계정 갱신 필드의 차이는 권한 차이로 취급하지 않습니다. 일반 조건 해석으로 새로운 에피소드를 해금하지 않습니다.

`Read(2)` 행이 일회성 수령 기록입니다. 읽음 저장과 재화 증가는 `State.mutate_snapshot`의 동일한 SQLite 트랜잭션에서 일어나며, 재요청은 보상을 다시 주지 않습니다. 보상 응답의 `RewardResult`는 현 프로필의 무료 스톤 잔액으로 `beforeAmount`, `afterAmount`, `amountI64=30`, `resourceType=15`를 구성합니다. 재요청에서도 현재 잔액을 `CommonResponse.updatedData.balance`로 전달합니다. 유료 스톤은 변경하지 않습니다. `Setting.freeStoneLimit` 또는 protobuf int32 한도를 넘으면 읽음 저장까지 함께 거부하며, 선물함 전송·상한 초과 보상 소멸을 추측하지 않습니다.

기존 `UserStory`의 세 플래그와 알 수 없는 protobuf 필드를 보존합니다. `isInvalid` 또는 지원하지 않는 상태 행은 거부합니다. 다른 스토리, 설정, 세션, 레슨 시계와 다른 프로필은 변경하지 않습니다. 본 기능은 스토리 재생 파일이나 보이스를 만들어 주지 않으며, 클라이언트의 기존 에셋 다운로드 경로를 사용합니다.

## 근거와 출처

목록 출처와 고정 해시는 [공개 스토리 기본 목록](story-catalog-data.md)에 있습니다. 원본 공개 자료는 [Project-Hoshimi/sumire-sr-data의 고정 커밋](https://github.com/Project-Hoshimi/sumire-sr-data/tree/c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02)입니다.

추가 보상 응답 근거는 같은 커밋의 [`captures/2026-09-14_a12r/raw/00092.resp-plain.Story:Read.bin`](https://github.com/Project-Hoshimi/sumire-sr-data/blob/c40ea107b9cc8e53ae1705f82a5c39cc9fe3be02/captures/2026-09-14_a12r/raw/00092.resp-plain.Story%3ARead.bin)입니다. 56바이트 원본의 SHA-256은 `48d4024347eab630aebc3bb88f6efb926f0ddfd6b5f68de7048cf7d518ad26ae`, Git blob은 `a7d476fc696fb1b0e440e7e16b07d41c371a24c4`입니다. 이 응답은 무료 스톤 30개 `RewardResult`, `Read(2)` 행과 무료 잔액 갱신만 포함합니다. 참조 계정의 절대 잔액·계정 기록을 런타임 자료로 복사하지 않았습니다.

고정 마스터의 `Condition` 30,786행과 `Message` 1,853행·`Telephone` 549행의 해금 조건을 재귀적으로 조사했습니다. `ReadStory` 조건이 참조하는 307개 Story 중 위 425개는 없었으며, 조건 참조 누락·순환도 없었습니다. 따라서 이 범위에서 메시지·전화의 읽기 연동 스케줄을 임의로 생성하지 않습니다. 이 결과는 모든 종류의 향후 스토리 부작용을 구현했다는 뜻이 아닙니다. 카드·포토 스토리, 일반 스토리 해금, 다른 보상과 내러티브 예약은 계속 별도 구현 범위입니다.

[solis-server](https://github.com/vertesan/solis-server)의 원자적 읽음·보상 처리 구조도 참고했습니다. 해당 서버는 AGPL-3.0이며, 여기의 코드는 해당 구현을 복사하지 않고 복구한 스키마·원본 클라이언트·고정 공개 마스터와 응답을 근거로 작성했습니다. 데이터 원출처와 고정 커밋은 위 링크에 유지합니다.
