# 아이프라 로컬 v0.3.16

Android 서버의 게임 APK 설치·수정 기능과 설치 권한, 내장 클라이언트 APK를 제거했습니다. 디버그를 허용하지 않는 서버 배포판입니다. 클라이언트는 별도 파일로 제공합니다. Android·iOS 공통으로 콜백 내 같은 타입 검사를 재사용하고, Mac 360 LIVE의 UI 좌표 변환을 줄였습니다. 실제 FPS 개선량과 Play 프로텍트 경고 해제 여부는 아직 실기기에서 확인하지 못했습니다.

## 파일

파일명 | 용도 | 크기
--- | --- | ---
[IdolyPride-Local-Server-Android.apk](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/apps-v0.3.16/IdolyPride-Local-Server-Android.apk) | Android 서버 업데이트 | 99667840 B
[IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/apps-v0.3.16/IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk) | Android 그래픽 지원 진단 클라이언트 업데이트 | 159434770 B
[IdolyPride-Local-Server-macOS-arm64.app.zip](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/apps-v0.3.16/IdolyPride-Local-Server-macOS-arm64.app.zip) | Mac 서버 앱 업데이트 | 101801373 B
[IdolyPride-6.1.1-Local-PlayCover.ipa](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/apps-v0.3.16/IdolyPride-6.1.1-Local-PlayCover.ipa) | PlayCover용 클라이언트 업데이트 | 146437888 B

GitHub에서 비공개 저장소 접근 권한이 있는 계정으로 로그인해야 합니다. 앱 파일 대신 LFS 포인터가 열리면 파일 화면의 Download raw file을 사용합니다.

## 설치

1. 게임과 서버를 종료한 뒤 사용하는 기기의 서버와 클라이언트를 각각 업데이트합니다. 기존 앱이나 데이터를 지우지 않습니다.
2. Android는 서버를 시작하고 **진단 게임 실행** 또는 **그래픽 지원 게임 실행**으로 이 클라이언트를 엽니다. 일반 로컬 실행 버튼은 기존 별도 리소스판을 열 수 있습니다.
3. Mac은 ZIP을 풀어 앱을 응용 프로그램 폴더에 옮기고, IPA를 PlayCover에 가져와 기존 로컬 게임을 업데이트합니다.
4. MV 진입·종료 회전 대기는 Android·Mac 모두 기본 켜짐이며 기존 저장한 선택은 유지합니다.

Play 프로텍트 차단은 일반 출처 확인과 다릅니다. 새 APK에서도 차단되면 Google 재검토가 필요할 수 있습니다. 이 파일을 Play 프로텍트 통과 판정을 받은 버전으로 표시하지 않습니다. [권한·배포 변경](https://github.com/tagundo/IdolyPride_client/blob/a00799d7d5ab07c00ab5c891e629c5c17d791c28/docs/android-distribution.md) · [성능 개선 범위](https://github.com/tagundo/IdolyPride_client/blob/a00799d7d5ab07c00ab5c891e629c5c17d791c28/docs/mv-performance-audit.md)

## 검증

소스: `a00799d7d5ab07c00ab5c891e629c5c17d791c28`. 호스트 코드·파일 보존·서명 검사는 실기기 실행, Play 프로텍트 검사, FPS 측정과 구분합니다. 각 파일의 SHA-256은 SHA256SUMS와 RELEASE-VERIFICATION.json에 있습니다. 서버의 패키지와 서명을 유지해 기존 업데이트 경로를 보존합니다.
