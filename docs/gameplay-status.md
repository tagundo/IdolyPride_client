# 로컬 게임 상태 구현 범위

`Gameplay`와 `Quest`는 6.1.1 스키마와 같은 버전의 마스터를 사용합니다. 현재 구현은 부팅·홈 응답, 라이브 목록, 일부 사용자 설정·배치·튜토리얼·덱 상태의 보존입니다. Android 사용자 기기에서 홈 화면과 중앙 모델 표시를 확인했습니다. 라이브 메뉴·5인 기본 편성·시작 버튼 표시도 확인했으며 전투 시작·결과 계산은 미구현입니다.

## 제목 화면의 환불 기간 조회

`Refund.GetTerm`은 `System.Check` 다음, `Auth.Login` 전에 호출되는 익명 조회입니다. v0.2.1은 로그인 없이 `startDatetime=endDatetime=4102444800000`(2100-01-01 UTC), `shopInvalidStartDatetime=0`을 반환합니다. 공식 환불 신청·잔액 조회는 실행하지 않습니다.

6.1.1의 `TitleView.StartAnimationAsync` 상태 머신(`0x5173d0c`)은 시작·종료 값 0을 무제한 기간으로 취급하므로 둘 다 0으로 두면 환불 버튼이 나타납니다. 미래 시작·종료를 사용해 환불 화면을 비활성화합니다. `CheckOpenStoneShop`(`0x528d338`)은 `IsBefore(shopInvalidStartDatetime)`을 사용하므로 0은 유료 상점 진입을 닫습니다. `GetPaidStone`과 사용자 데이터에는 기존 인증 검사를 유지합니다.

실제 Android에서 관측한 `System.Check → Refund.GetTerm`을 재현한 뒤 `Auth.Login`으로 이어지는 흐름을 HTTP/2·grpcio와 에뮬레이터 검사에 포함하며, 이 조회가 기존 프로필·세션을 바꾸지 않는지 검증합니다.

## 구현한 RPC

| RPC | 로컬 동작 | 저장되는 내용 |
| --- | --- | --- |
| `Home.Login` | 설정 수신·로그인 시각 갱신 | `SettingInfo`, `user.lastLoginTime`, JST 날짜별 `totalCount.loginCount` |
| `Home.Enter` | 마스터 기반 현재 메인 지역·현재 하이어라키 등급·홈 컨테이너 반환 | 읽기 전용; 보상·이벤트는 생성하지 않음 |
| `Home.SetReview` | 리뷰 확인 상태 기록 | `user.isReviewed=true` |
| `Home.SetCharacterPosition` | 소유 캐릭터·배치 유형을 검증하고 갱신 | `homePositions` |
| `Dokan.List` | 비어 있는 로컬 팝업 목록 | 없음 |
| `Notice.List` | 비어 있는 로컬 공지 목록 | 없음 |
| `Master.GetVersion` | 묶음의 `!version.txt` 반환 | 없음 |
| `Tutorial.Init` | 이름과 최초 GameStart 체크포인트 설정 | `user.name`, GameStart step 최소 10 |
| `Tutorial.Progress` | 알려진 유형·마스터 체크포인트의 진행을 단조 증가 | `tutorials`, GameStart 완료 시각 |
| `Tutorial.Skip` | GameStart 튜토리얼만 완료 처리 | GameStart step 최소 150·완료 시각 |
| `Deck.Save` | 기존 덱의 수동 편집, 카드·외형·사진·장비 소유 관계 검증 | `decks`, `deckPositions`, 제거된 슬롯의 `deletedData` |
| `Deck.Delete` | 지정한 기존 덱 삭제 | 덱·배치 제거 및 `deletedData` |
| `Quest.Top` | 메인 라이브 그룹·지역·퀘스트와 저장된 진행도 조회 | 읽기 전용 |
| `Quest.ListMain` | 같은 메인 목록·진행도 조회 | 읽기 전용 |
| `Quest.ListAsset` | 저장된 5인 덱의 캐릭터·실효 의상·헤어 ID를 리소스 준비용으로 반환 | 읽기 전용 |

`Deck.Save`는 배치 1~5와 중복 참조·장비 수량·슬롯·캐릭터 제한을 검증합니다. 신규 덱 번호 할당, 자동 편성, 버디 대여, 캐릭터 그룹 제한 장비는 아직 `UNIMPLEMENTED`입니다. 일반 캐릭터 제한 장비는 동봉한 `Accessory` 마스터로 검증합니다.

메인 라이브 목록은 `AreaGroup`·`Area`·`Quest`의 실제 참조와 순서를 검증합니다. 현재 묶음에는 메인 5그룹·125지역·939퀘스트가 있습니다. 신규 프로필은 첫 지역·첫 퀘스트만 플레이 가능으로 표시하며 이후 진행은 저장된 지역 클리어 수와 개별 퀘스트 기록을 사용합니다. 목록 조회가 클리어·점수·재화·티켓·튜토리얼을 변경하지 않습니다. 해석하지 못한 해금 조건은 잠긴 상태로 둡니다. `Quest.Top`이 반드시 읽는 PvP 컨테이너와 유효한 하이어라키 등급은 제공하지만, 경쟁 시즌·상대·보상은 만들지 않습니다. 전투 시작과 결과 계산은 아직 구현하지 않았습니다.

v0.2.8은 `Quest.Top`의 `contestArea`도 실제 하이스코어 지역·23개 퀘스트와 저장된 기록으로 제공합니다. 콜백에서 null을 저장할 수 있더라도 이후 `LiveTopScreenPresenter.RequestLiveProgressAsync`(`0x5759ce8`~`0x5759cf4`)가 이를 반드시 읽으므로 필드 부재는 유효한 비활성 응답이 아닙니다. v0.2.7의 사용자 기기에서 `Quest.Top → OK` 직후 발생한 null 참조와 이 분기를 확인했습니다. 하이스코어 지역·퀘스트는 잠긴 상태이며 경쟁전·보상·캠페인은 생성하지 않습니다.

GameStart가 미완료(기록 없음 또는 완료 단계 150 미만)이면 실제 튜토리얼 그룹 1개·지역 1개·full/short 퀘스트 2개도 목록에 포함합니다. 두 퀘스트는 대체 선택지이며 메인 지역 클리어 순서에 묶지 않습니다. 이때 전체 그룹 목록은 6그룹·126지역·941퀘스트입니다. 완료 계정에는 기본 메인 5그룹만 반환합니다. 이 조회는 튜토리얼을 진행하거나 완료시키지 않습니다.

해당 변경 응답은 `commonResponse.updatedData`에 반영됩니다. 일반 게임 동작은 활성 로컬 세션을 유지하며, snapshot과 설정을 SQLite의 단일 트랜잭션에서 갱신합니다. 동시 요청의 변경 유실, 잘못된 요청의 부분 저장, 스키마가 다른 snapshot 수정은 거부합니다. protobuf의 알 수 없는 필드도 정상 수정 뒤 유지합니다.

`Home.Enter`는 `HierarchyDetailGrade`·`HierarchyGrade`의 실제 참조를 검증합니다. 현재 점수에서 전역 순위가 필요 없는 등급을 선택하며 순위·보상을 생성하지 않습니다. 신규 프로필의 0점 기본 등급은 현재 마스터의 `hie-007-003`입니다. 기존 snapshot의 빈 하이어라키에는 응답에서만 기본 등급을 적용하며 저장된 계정 상태는 변경하지 않습니다. 잘못된 마스터 참조는 명시적으로 거부합니다. Android 6.1.1 `HomeTop.SetHomeEnterData`(`0x566c15c`)는 현재 등급을 무조건 읽고, 조회 실패 시 `0x566c1c8`에서 null 참조로 중단합니다.

`Home.Enter`의 이벤트·활동·배너 컨테이너는 로컬 콘텐츠가 없다는 구조를 반환합니다. 급여·자동 보상·진행 중인 활동 결과를 만들어내지는 않습니다. 메인 지역 선택에는 `Area` 마스터가 필요하며 다른 지역 유형을 임의로 메인 지역으로 취급하지 않습니다.

진행 중인 특별 홈 이벤트가 없으면 `homeFishHeavenInfo` 메시지는 보내지 않습니다. Android 6.1.1의 `HomeTop.ShouldHideLoading`(`0x566c9b0`)과 홈 전환(`0x5675ff4`~`0x5676008`)은 이 메시지가 null인지 검사합니다. 빈 메시지도 존재하면 일반 로딩 화면을 숨기지 않으므로, v0.2.6은 이 선택 필드를 응답에서 제외합니다. v0.2.5와 진단판 v0.2.1의 실제 기기 기록에서 배경·캐릭터·홈 표시 전환은 통과하고 `loading_hide`만 누락된 것을 확인했습니다. 이 변경은 응답만 수정하며 저장된 계정·튜토리얼·세션을 변경하지 않습니다.

## 라이브 리소스 준비

v0.2.9의 사용자 기기에서 초기 카드 보완과 5인 편성·시작 버튼 표시를 확인한 뒤, 다음 요청인 `Quest.ListAsset`이 `UNIMPLEMENTED`로 중단됐습니다. v0.2.10은 이 읽기 전용 API를 구현합니다. 실제 전투를 시작하는 `Tutorial.StartQuest`와 `Quest.Start`는 별도 미구현 기능입니다.

응답은 저장된 덱의 자리 1~5에 해당하는 `LiveCharacterAssetInfo`의 `characterId`, `costumeId`, `hairId`만 포함합니다. 직접 선택한 외형과 비어 있는 설정의 라이브·기본 외형을 실제 마스터와 보유 관계에 따라 해석합니다. 클라이언트는 이 ID로 모델을 조회하고 무대·음악 등은 퀘스트의 원본 마스터를 통해 준비합니다. 리소스 경로는 기존 Octo 경로를 사용합니다.

원본 호출부는 일반 덱 이름도 `buddyDeckName`에 넣으므로 이 문자열만으로 대여 기능으로 취급하지 않습니다. 실제 버디 배치가 있는 요청은 아직 `UNIMPLEMENTED`입니다. 목록 조회는 snapshot·덱·설정·세션·튜토리얼·재화·라이브 기록을 변경하지 않습니다.

## 신규 프로필의 시작 데이터

`seed_starter_profile(state, schema, profile, master_dir)`는 snapshot이 없는 프로필에서만 사용합니다. 기존 공식 계정 snapshot이나 이미 생성한 로컬 프로필에는 자동 적용하지 않습니다.

시작 캐릭터는 `Character.type=1`이며 `viewConditionId`·`unlockConditionId`가 모두 빈 일반 캐릭터 17명입니다. Android 6.1.1의 `GetSubCharacterCandidate`는 보유 목록을 검사하지 않고 이 마스터 풀에서 홈 배경 인물을 선택합니다. 이어 `CreateActorDescriptor`는 `UserCharacter.FindById` 결과를 무조건 읽으므로 5명만 준비하면 나머지 12명 선택 시 null 참조가 발생할 수 있습니다. 조건이 있는 `char-kan/kor/mhk` 등은 제외합니다. 이 17명은 실제 `initial_user_reward`의 캐릭터 목록과도 일치합니다.

`Setting.tutorialPhotoShootingCharacterIds`의 5명은 기본 즐겨찾기·홈 배치에 사용합니다. 각 캐릭터의 기본·라이브 의상과 헤어 소유 관계·착용 가능성을 실제 마스터로 검증합니다. 활동 레벨 1 체력은 `CharacterActivityLevel`에서 가져오며 최초 메인 지역의 퀘스트 참조도 검증합니다.

현재 신규 데이터에는 레벨 1 매니저, 위 캐릭터·외형, 홈 배치와 GameStart step 0이 포함됩니다. v0.2.9는 원본 `Reward.initial_user_reward`에 정의된 초기 카드 17개·촬영 아이템 1개·레슨 피스 100개를 함께 준비합니다. 초기 지급을 처리한 공식 RPC와 시점은 확인하지 못했으므로 이 부분은 마스터에 근거한 로컬 계정 생성 정책입니다. `initial_user_gift`, 프리미엄 재화·클리어 보상·튜토리얼 완료·기능 전체 해금은 적용하지 않습니다. 마스터 참조 검증이 실패하면 부분 프로필이나 snapshot을 남기지 않습니다.

초기 카드는 레벨 1·마스터의 초기 레어도와 기본 능력치를 갖습니다. 수치는 원본 `CalcCardParameter`(`0x46a4b7c`)의 두 번 내림 계산을 따르며, `CardLevelRelease`의 레벨 1 해금만 현재·기본 스킬과 포토 슬롯에 반영합니다. 예를 들어 초기 코토노는 보컬 93·댄스 74·비주얼 64·스태미나 935이며 첫 스킬과 포토 2칸만 해금됩니다. 아직 배우지 않은 스킬은 ID도 비워야 합니다. 클라이언트는 스킬 레벨 0이어도 유효한 ID가 있으면 배운 스킬로 판단합니다.

기본 덱은 `Setting.tutorialPhotoShootingCharacterIds`의 5명에 해당하는 보유 초기 카드와 라이브 의상·헤어로 편성합니다. 이는 로컬 기본 편성이며 공식 튜토리얼의 고정 편성이라고 주장하지 않습니다. Android 원본 `DeckBase.get_IsPlayable`(`0x51f02a0`)은 다섯 자리의 `UserCard`가 모두 있는지 검사하고, 하나라도 없으면 `SetDeck`과 `FabStateModel.Toggle(false)`를 통해 라이브 시작 버튼을 숨깁니다. v0.2.8 사용자 화면에서는 라이브 메뉴는 열렸지만 빈 기본 덱 때문에 안내 손가락이 빈 버튼 위치를 가리켰습니다. 이 편성 보완은 실제 전투 시작·결과 계산 구현과 별개입니다.

`repair_starter_roster`는 출처 표시가 있는 구형 로컬 프로필 또는 이전 서버의 5명·기본 외형·빈 `Local deck`·고정 홈 배치·식별자가 일치하는 구성을 보완합니다. 출처 없는 데이터에 다른 인벤토리·잔액이 있으면 보정하지 않습니다. 가져오기는 출처 0으로 표시하여 제외하며, 로스터 보완은 출처 버전을 2까지 갱신합니다. 누락 캐릭터 추가와 버전 갱신은 한 SQLite 트랜잭션으로 수행합니다. 기존 캐릭터·외형·진행·이름·설정·세션·알 수 없는 protobuf 필드는 유지합니다.

v0.2.7의 기본 배치 보정은 버전 3이며 홈·트레이닝·활동·아이돌 4곳에 서로 다른 보유 캐릭터를 지정합니다. 같은 캐릭터·외형의 로딩 작업은 같은 3D 객체를 캐시에서 공유하므로, 비활성 화면의 늦은 작업이 활성 홈 객체의 위치와 표시 참조를 바꿀 수 있습니다. 원본 코드의 실행으로 이 간섭과 서로 다른 캐릭터를 사용하는 경우의 분리를 확인했고, 업데이트 후 사용자 기기에서 중앙 모델 표시가 복구된 것을 확인했습니다.

`repair_starter_home_positions`는 버전 2의 정확한 구형 기본 구성(4곳 모두 첫 기본 캐릭터·랜덤 배치 없음)만 버전 3으로 보완합니다. 기본 홈 1번의 캐릭터는 유지하고 나머지 3곳의 캐릭터만 분리합니다. 로스터 보완 다음에 실행하므로 구형 5명 프로필도 순서대로 갱신됩니다. 가져온 계정이나 기본 구성으로 인식되지 않는 배치, 직접 바꾼 배치·랜덤 배치는 건드리지 않으며 세션·설정·튜토리얼·기타 protobuf 필드를 보존합니다.

v0.2.9의 `repair_starter_inventory`는 버전 3으로 표시된 로컬 기본 계정 중 레벨 1·빈 `Local deck` 하나·카드/아이템/편성 없음·저장된 GameStart 단계 0 또는 10·라이브 기록 없음인 경우에만 초기 지급과 5인 편성을 한 번 보완하고 버전 4로 갱신합니다. 가져온 계정·사용자 인벤토리나 덱·진행된 계정은 제외합니다. 캐릭터·홈·이름·설정·세션·튜토리얼과 알 수 없는 protobuf 필드를 유지하며, 새 지급과 출처 버전은 같은 SQLite 트랜잭션에서 저장합니다.

사용하는 마스터 파일은 `tools/build_server_payload.py`의 `TABLES`에 명시한 정규 테이블과 `!version.txt`입니다. v0.2.9는 초기 지급 참조 검증을 위해 `Reward`, `Item`, `CardLevelRelease`, `Skill`도 포함합니다. 번들의 정규 JSON은 protobuf 필드 이름과 숫자 enum을 사용합니다.

## 근거·검증

- 실제 6.1.1의 `api/home.proto`, `api/tutorial.proto`, `api/common_response.proto`, `transaction/user.proto`, `transaction/user_tutorial.proto` descriptor로 요청·응답 필드와 변경 목록을 확인했습니다.
- iOS native `UserTutorialCollection.IsFinished`의 `0x1e0d274`에서 GameStart 완료 조건 `step > 149`를 확인했습니다. 마스터에도 마지막 체크포인트 150이 있습니다. 다른 튜토리얼을 함께 완료시키지 않습니다.
- `TimeManager.GetDeviceNowUnixTime`의 `0x1d29230`은 UTC epoch 차이에 `TimeSpan.TotalMilliseconds`를 적용합니다. 따라서 저장 시각은 Unix 밀리초입니다.
- 독립 최소 스키마와 실제 6.1.1 스키마 양쪽에서 상태 보존·설정·JST 날짜 경계·병렬 변경·오류 롤백·알 수 없는 필드 유지·실제 마스터 참조를 테스트했습니다. 외부 스키마·마스터가 없는 fresh clone에서도 최소 스키마 테스트는 실행됩니다.

`Tutorial.StartQuest`, 활동 보상, 카드 육성, 가챠·구매 등 나머지 게임 로직은 이 모듈이 처리하지 않습니다. 준비된 fixture도 없으면 `UNIMPLEMENTED`를 반환합니다. 현재 튜토리얼 완료 표시는 전투·보상 계산의 구현을 뜻하지 않습니다.

## 다음 구현 근거

- 같은 버전의 `Reward.initial_user_reward`를 신규 계정의 초기 카드·아이템 준비에 사용합니다. 공식 지급 RPC와 시점은 아직 확인하지 못했으므로 이는 로컬 생성 정책이며, 후속 선물·일반 보상 지급 계약은 별도 구현이 필요합니다.
- 덱의 신규 번호 발급·자동 편성·버디 대여와 캐릭터 그룹 장비 제한은 추가 계약·마스터 검증이 필요합니다.
- Android `LiveTutorialPresenter.RequestFullTutorialLiveAsync`의 `0x42f8664`에서 `Tutorial.StartQuestAsync` 호출을 확인했습니다. 응답에는 라이브 차트·스킬·사용자 정보가 필요합니다. `Setting`의 `qt-tutorial-short/full` 퀘스트만으로 빈 성공 응답을 만들 수는 없습니다.
- 모델·음성·영상은 기존 Octo 리소스 경로를 사용합니다. 홈 표시 성공 및 원본 마스터 제공과 별개로, 전체 리소스의 오프라인 보존·주소 연결은 추가 구현과 게임 기기 검증이 필요합니다.
