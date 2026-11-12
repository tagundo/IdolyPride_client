# Android MT 확인판 v0.3.17

멀티스레드 렌더링을 요청하는 선택과 실제 게임에서 읽은 모드를 구분하는 확인판입니다. 기본값은 원본 실행입니다. 실기기 활성화·안정성·FPS 개선을 이미 확인한 버전은 아닙니다. Mac 배포는 기존 v0.3.16을 사용합니다.

## 다운로드

- [IdolyPride-Local-Server-Android.apk](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/android-mt-v0.3.17/IdolyPride-Local-Server-Android.apk) · 99680128 B
- [IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/android-mt-v0.3.17/IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk) · 159438866 B

GitHub 링크는 저장소 접근 권한이 있는 계정으로 로그인해야 합니다. 파일 해시는 SHA256SUMS와 RELEASE-VERIFICATION.json에서 확인합니다.

## 확인 순서

1. 서버와 진단 게임 APK를 모두 업데이트합니다. 기존 앱과 데이터를 삭제하지 않습니다.
2. Android 앱 정보에서 아이프라 진단을 강제 종료합니다. 서버를 시작하고 **다중 스레드 렌더링 시작 실험**을 켭니다.
3. 서버의 **진단 게임 실행** 또는 **그래픽 지원 게임 실행**으로 게임을 새로 열어 같은 라이브 촬영·360 LIVE 장면을 재생합니다.
4. 서버로 돌아와 **실제 측정: MultiThreaded (2 · 다중 스레드)**인지 확인합니다. 체크박스의 '요청'만으로 적용된 것으로 판단하지 않습니다.
5. 0·1이 계속 표시되면 적용되지 않은 관측입니다. 대기·초기화 실패·오래된 관측도 구분하고 진단 기록을 보관합니다.
6. 원본과 비교할 때는 게임을 강제 종료한 후 옵션을 끄고 새로 실행합니다. 해상도·품질·목표 FPS·Graphics Jobs는 같이 바꾸지 않습니다.

게임 프로세스가 살아 있는 상태에서 다시 버튼만 누르면 시작 옵션이 적용되지 않을 수 있습니다. 일반 로컬 실행 버튼은 이전 별도 리소스판을 열 수 있으므로 진단 게임 버튼을 사용합니다.

CPU·GPU 프레임 시간은 이 판에서 NULL이며 FPS 개선을 추정하지 않습니다. 화면을 떠나 게임이 멈추면 관측이 오래된 상태로 바뀔 수 있고 직전 값은 진단 JSON에 남습니다. 서버 설치 권한·내장 APK·디버그 허용은 복구하지 않았습니다.

[설명·진단 필드·비교 방법](https://github.com/tagundo/IdolyPride_client/blob/acd5881b9a4acb538f460481ff7cfa0f317aa4b9/docs/android-mt-verification.md)

소스: `acd5881b9a4acb538f460481ff7cfa0f317aa4b9`. 호스트·서명·파일 보존 검증과 실제 기기 관측을 구분합니다.
