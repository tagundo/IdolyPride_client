# 교류 메뉴 읽기

v0.3.7의 별도 감상 계정에서 `Company.Top`·`Company.EnjoyCharacterTop`을 제공합니다. 이전 버전의 교류 메뉴는 `Company.Top → UNIMPLEMENTED`로 중단됐습니다. 원본 `CompanyWindow.UpdateInfoAsync`의 Top 호출과 캐릭터별 EnjoyCharacterTop 호출을 확인해 구현했습니다.

실제 마스터의 등급 55개·신뢰도 50단계와 정식 캐릭터 20명의 각 60단계를 사용합니다. 나머지 감상 캐릭터 8명에게 없는 교류 설정을 만들지 않습니다. 원본 교류 목록도 `GetAllMain → Character.IsNormal`로 정식 캐릭터를 선택합니다. 캐릭터 모델은 받은 level 목록의 첫 항목을 사용하므로 실제 설정이 없는 직접 요청은 빈 성공 대신 거절합니다.

기존 `UserCompany`·캐릭터 포인트·보유 미션을 보존하며, 저장된 미션만 원본 분류로 전달합니다. 목록 조회가 미션을 보고하거나 진행·재화·수령 이력·다른 사용자 순위를 생성하지 않습니다. 월별 급여·순위는 로컬의 미집계 값 0이며 보상 수령 플래그는 모두 false입니다. 보상 수령·아이템 소비·미션 보고·랭킹은 별도 미지원 범위입니다. 일반 계정의 기존 경로는 유지합니다.

`Story.ReadCharacterCompanyEnjoyStory`도 감상 모드에서 지원합니다. `Character.companyEnjoyStories`의 실제 캐릭터·번호·Story 연결(20명, 160편)을 확인해 읽음으로 저장합니다. 보유하지 않은 캐릭터와 잘못된 번호는 거절하며, 완료·스킵·재요청은 포인트나 보상을 만들지 않습니다. 기존 성장·의상·잔액·다른 프로필은 보존합니다.

서버 데이터에는 기존 45개 JSON 외에 `CompanyGrade`, `CompanyTrustLevel`, `CompanyEnjoyCharacterLevel`, `CompanyEnjoyCharacterLevelSetting`이 필요합니다. 이 네 표는 기존 원본 암호화 마스터 202개에 이미 포함된 데이터를 추가 디코딩한 것으로, 앱 데이터 번들의 합계는 49개 JSON입니다. 원본 클라이언트 팩·공개 리소스·스토리 자료는 유지합니다.

실제 공개 마스터를 사용한 임시 서버에서 Top·20명 전체 캐릭터 조회·스토리 읽기/재시도와 DB·설정·선택·잔액 보존을 검사했습니다. 이는 실제 게임의 교류 화면과 모든 하위 기능을 끝까지 검증했다는 뜻은 아닙니다.
