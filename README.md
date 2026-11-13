# 홈 해금 캐시·다운로드 전송 개선 v0.3.24

**기존 사용자는 서버 앱만 v0.3.24로 업데이트하면 됩니다.** Android 게임 v0.3.21, PlayCover IPA v0.3.19와 서버 데이터 v0.3.23은 검증된 기존 파일을 그대로 재사용합니다. 서버와 게임을 종료한 뒤 서버를 업데이트하고 다시 시작합니다. 기존 앱·계정·리소스를 삭제하지 않습니다.

| 기기 | 서버 v0.3.24 | 기존 클라이언트 재사용 |
| --- | --- | --- |
| Android ARM64 | [서버 APK](IdolyPride-Local-Server-Android.apk) | [게임 APK v0.3.21](IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk) |
| Apple Silicon Mac | [서버 앱 ZIP](IdolyPride-Local-Server-macOS-arm64.app.zip) | [PlayCover IPA v0.3.19](IdolyPride-6.1.1-Local-PlayCover.ipa) |

- v0.3.23에서 목록 API만 갱신되고 홈 진입 캐시에 반영되지 않아 남아 있던 이벤트 스토리 메뉴 잠금과 촬영의 `撮影NG` 판정을 수정합니다. 감상 모드의 `Home.Enter`에 목록 API와 같은 검증된 이벤트 스토리와 촬영 관련 4개 목록 DTO를 전달합니다.
- Android 리소스 수신은 Java에서 최대 64 KiB 단위로 버퍼를 채워 Python으로 넘겨, 작은 읽기마다 발생하던 Java·Python 경계 호출을 줄입니다. 파일 전체 해시·크기 검사와 디스크 여유 공간 검사·취소를 유지합니다.
- 리소스 화면에 누적 수신량·평균 수신 속도·경과 시간, 처리 단계별 파일 수와 검증 완료 바이트/전체 바이트를 표시합니다. 기존 1·2·4·8개 병렬 다운로드 설정은 유지합니다.

일반 모드의 해금·보상 규칙과 서버 데이터는 변경하지 않습니다. 포즈 선택·감상 경로를 다루며 실제 사진 이미지 생성 API나 촬영 RPC 전체를 구현한 버전은 아닙니다.

전체 호스트 검사: 통과 5201개, 건너뜀 16개, 하위 검사 통과 351개. 전체 검사에서 실패는 없었습니다.

새 서버 두 파일의 전체 원격 다운로드 SHA-256과 익명 다운로드를 검증했습니다. 데이터 ZIP과 기존 클라이언트의 전체 SHA 검증은 동일한 고정 파일에 대한 이전 배포 기록을 재사용합니다. 실제 기기에서의 다운로드 속도 향상·게임 UI·3D 재생과 이번 Mac 앱의 GUI 실행은 검증하지 않았습니다. Mac 앱은 Linux에서 ARM64로 교차 빌드하고 런타임·struct·CA·서명 페이지·리소스 봉인·ZIP을 검사합니다.

[동일한 서버 데이터 v0.3.23 ZIP](IdolyPride-ServerData-v0.3.23.zip) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/blob/downloads/home-cache-v0.3.24/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/blob/downloads/home-cache-v0.3.24/RELEASE-VERIFICATION.json) · [변경 설명](https://github.com/tagundo/IdolyPride_client/blob/main/docs/home-media-cache-v0.3.24.md). 서버 데이터는 서버 앱에 포함되어 있어 일반 업데이트에는 별도로 받을 필요가 없습니다.

첨부 업로드 인증·Actions 사용 한도로 Assets 대신 위 개별 링크에서 제공합니다. 비공개 저장소는 GitHub 로그인 후 Download raw file로 받습니다.
