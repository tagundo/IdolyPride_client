# 이미지 트레이닝·VENUS 개인 데이터 보존

Mac에서는 [아이프라 이벤트 보존 앱 v0.1.0](https://github.com/tagundo/IdolyPride_client/releases/download/event-preserver-v0.1.0/IdolyPride-Event-Preserver-Mac-arm64.zip)을 우선 사용하세요. Apple Silicon macOS 13 이상이며 Python 설치가 필요 없습니다. ZIP을 풀어 앱을 실행하고 보존 위치를 선택하세요. 기존 PlayCover 일본판의 저장 기록을 먼저 오프라인으로 검사하고, 계정을 선택한 뒤 **기존 계정으로 로그인하고 이미지 트레이닝·VENUS 메뉴 조회**를 체크해 **보존 시작**을 누릅니다. 비밀번호나 인증 파일을 채팅에 보낼 필요가 없습니다. 인증 정보는 Mac의 메모리에서만 사용하며 보존 파일에 요청 세션 메타데이터를 저장하지 않습니다.

이 앱은 ad-hoc 서명이며 Apple 공증은 받지 않았습니다. macOS가 실행을 차단하면 시스템 설정의 **개인정보 보호 및 보안**에서 다운로드 출처와 앱을 확인한 뒤 열 수 있습니다. [검증 파일과 해시](https://github.com/tagundo/IdolyPride_client/releases/tag/event-preserver-v0.1.0)도 함께 제공합니다. 실제 Mac에서 앱 창·오프라인 점검·이동 후 실행·TLS 인증서를 확인했지만, 사용자 계정으로 공식 서버에 로그인하는 단계는 아직 직접 검증하지 못했습니다.

기존 `export_playcover_auth.py --diagnose`의 `matched_rows: 128`·`group_number: 1`은 PlayChain 저장 그룹의 진단이며 실제 Firebase 계정 수를 뜻하지 않습니다. 배포된 보존 앱 v0.1.0은 실제 UID·앱·프로젝트가 같은 인증 버전 중 검증된 최신 발급 시각을 선택합니다. 서로 다른 UID나 같은 발급 시각의 충돌은 자동 선택하지 않습니다. 단일 원문을 내보내는 기존 `--output` 명령의 다중 항목 오류와 보존 앱의 계정 선택 동작을 구분하며, 인증 원문을 채팅에 보낼 필요는 없습니다.

공식 서버에 로그인하면 기존 게임 세션이 갱신될 수 있습니다. 이미지 트레이닝·VENUS 메뉴 방문 과정에서도 공식 서버의 월간·시즌 정리나 일반 메뉴 로그인 보상이 적용될 수 있습니다. 도구는 포토 촬영·에리어 생성·초기화·라이브·대전을 자동 실행하지 않습니다. 생성된 에리어가 없다면 새 에리어를 대신 만들지 않습니다. 보존 폴더에는 계정·보유품·상대 정보가 들어 있으므로 **폴더·JSON·protobuf 파일을 Git, 릴리스, 채팅에 올리지 마세요.**

명령줄을 사용하는 경우 기본 실행은 오프라인 검사입니다.

```sh
python3 tools/preserve_playcover_events.py --inspect
```

공식 연결은 `--login-existing-account`, 이벤트 메뉴 방문은 추가로 `--visit-current-menus`가 필요합니다. 여러 계정이 발견되면 앱에서 검사 결과의 계정을 선택하세요. 검사 뒤 계정 구성이 바뀌면 다시 검사해야 합니다. 원본 보존은 로컬 복원에 실패해도 그대로 남습니다.

보존이 끝났다면 아래 명령으로 **기존 서버 데이터와 다른 새 폴더**에 복원할 수 있습니다. `--event`는 `dream`, `venus`, `both` 중 하나를 반드시 지정합니다. 한 이벤트의 자료만 완전하면 해당 이벤트만 선택하세요.

```sh
python3 tools/restore_event_capture.py \
  --archive /path/to/private-capture \
  --event both \
  --output /path/to/new-private-restore
```

이 작업은 네트워크를 사용하지 않습니다. 원본 파일의 해시·스키마·계정·최종 `User.Get` 스냅샷을 검증하고, 새 프로필 `preserved`의 `state.db`와 `user-get.pb`, 선택한 개인 카탈로그를 만듭니다. 기존 폴더를 덮어쓰지 않습니다. 시즌 시각·진행도·영구 계정 식별자를 유지하며 보상·초기화·새 로그인 세션을 추가하지 않습니다. 자료가 부족하면 오류로 중단하고 임시 파일을 정리합니다.

로컬 서버에는 **같은 버전의 디코딩된 마스터**와 개인 카탈로그 경로를 지정하세요. 이미지 트레이닝만 복원했다면 `--pvp-catalog`를 생략하고, VENUS만 복원했다면 `--dream-catalog`를 생략합니다. 도구의 성공 출력에도 실행 명령 예시가 표시됩니다.

```sh
python3 -m idoly_local serve \
  --state /path/to/new-private-restore/state.db \
  --profile preserved \
  --fixtures /path/to/new-private-restore/empty-fixtures \
  --master-dir /path/to/matching-master-json \
  --dream-catalog /path/to/new-private-restore/dream-private-catalog.json \
  --pvp-catalog /path/to/new-private-restore/pvp-catalog.json
```

현재 복원 범위는 보존한 이미지 트레이닝 정보·생성 에리어·재료 목록과 VENUS 메뉴·상대 모델의 읽기 경로입니다. 에리어 생성·성장·이미지 트레이닝 라이브·VENUS 대전·보상은 추가 구현이 필요합니다. 누락된 자료나 종료된 시즌을 날짜 변경으로 활성화하지 않습니다. 현재 클라우드에서는 실제 계정 로그인이나 게임 UI까지 검증하지 못했으며 합성 자료로 검증했습니다.

[공식 서비스 종료 공지](https://x.com/idolypride/status/2116003197991170275)는 **2027년 3월 1일**을 안내합니다. 관측된 이미지 트레이닝 월간 기간은 **2026년 11월 15일 11:59:59 JST**까지입니다. 이는 해당 월간 미션·운영 기간의 근거이며, 모든 생성 에리어가 그때 삭제된다는 증거는 아닙니다. 현재 자료를 먼저 보존하고 전체 기능 복구와 구분해야 합니다.
