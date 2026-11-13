# 서버 응답·저장 처리 최적화 v0.3.22

기존 사용자는 **서버 앱만 업데이트**합니다. Android 게임은 v0.3.21, PlayCover IPA는 v0.3.19의 검증된 파일을 그대로 재사용합니다. 서버를 종료한 뒤 업데이트하고 다시 시작합니다. 기존 앱·계정·리소스는 삭제하지 않습니다.

| 기기 | 새 서버 | 기존 클라이언트 재사용 |
| --- | --- | --- |
| Android ARM64 | [서버 APK](IdolyPride-Local-Server-Android.apk) | [게임 APK v0.3.21](IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk) |
| Apple Silicon Mac | [서버 앱 ZIP](IdolyPride-Local-Server-macOS-arm64.app.zip) | [PlayCover IPA v0.3.19](IdolyPride-6.1.1-Local-PlayCover.ipa) |

촬영·360 LIVE·Company·선물함·친구·감상 모드 스토리의 읽기 전용 요청 14개에서 빈 갱신 메시지를 생략합니다. 덱 저장은 해당 덱과 배치만 응답하고, 특별 스토리의 고정 마스터 연결 검증을 재사용합니다. 같은 이름·소개·설정 저장의 불필요한 직렬화·실제 DB 갱신을 줄입니다. 소유권·보상·재시도용 현재 행 ACK는 유지합니다.

일반화한 빈 메시지 제거를 삭제 응답에 적용하지 않습니다. 덱 삭제의 원본이 요구하는 빈 updatedData는 유지합니다. 리소스 다운로드의 파일 전체 검사는 유지합니다.

전체 호스트 검사에서 4,988개와 351개 하위 검사를 통과했습니다. 새 덱 부분 응답에 맞지 않던 기존 CI 기대치를 수정한 뒤 관련 160개 검사를 통과했습니다. 실제 기기의 지연·FPS 변화와 이번 Mac 앱의 GUI 실행은 계측하지 않았습니다.

[SHA256SUMS](SHA256SUMS) · [배포 검증](RELEASE-VERIFICATION.json) · [변경 범위](https://github.com/tagundo/IdolyPride_client/blob/main/docs/wardrobe-exit-latency.md). 비공개 저장소는 GitHub 로그인 후 **Download raw file**로 받습니다. 첨부 업로드 인증·Actions 사용 한도 때문에 Assets 대신 이 브랜치에서 파일을 제공합니다.
