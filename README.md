# 병렬 다운로드·촬영 포즈·외출·이벤트 스토리 복원 v0.3.23

**기존 사용자는 서버 앱만 업데이트하면 됩니다.** Android 게임 v0.3.21과 PlayCover IPA v0.3.19는 검증된 기존 파일을 그대로 재사용합니다. 서버를 종료한 뒤 업데이트하고 다시 시작합니다. 기존 앱·계정·리소스를 삭제하지 않습니다.

| 기기 | 서버 v0.3.23 | 기존 클라이언트 재사용 |
| --- | --- | --- |
| Android ARM64 | [서버 APK](IdolyPride-Local-Server-Android.apk) | [게임 APK v0.3.21](IdolyPride-Local-Graphics-Diagnostic-Android-arm64.apk) |
| Apple Silicon Mac | [서버 앱 ZIP](IdolyPride-Local-Server-macOS-arm64.app.zip) | [PlayCover IPA v0.3.19](IdolyPride-6.1.1-Local-PlayCover.ipa) |

- 전체 리소스 다운로드를 기본 4개 병렬로 받고, 서버에서 동시 다운로드 수를 1·2·4·8개로 선택할 수 있습니다. 진행·취소·디스크 여유 공간 검사와 전체 파일 해시 검증을 유지합니다.
- 감상 모드 촬영에서 원본 포즈 146개와 캐릭터별 모션 연결 1,596개를 복원합니다.
- 감상 모드 교류의 외출을 원본 장소 4곳·캐릭터별 설정 80개·시선 반응 420개로 복원합니다. 외출 시작·반응 확인·종료와 재시도를 처리합니다.
- 감상 모드 이벤트 스토리 59개 그룹·291편의 목록·읽기 경로와 클라이언트 마스터의 표시 조건을 연결합니다. JP·KO·EN 감상용 마스터를 갱신하고 일반 모드 원본 카탈로그는 유지합니다.

포즈 선택·미리보기와 외출 감상 경로를 복원한 버전입니다. 실제 사진 이미지 생성 API는 아직 지원하지 않습니다. 일반 모드의 해금·보상 규칙은 변경하지 않습니다.

전체 호스트 검사: 통과 5173개, 건너뜀 16개, 하위 검사 통과 351개. 전체 검사에서 실패는 없었습니다. 전체 검사는 `ed2a428bb6007cf87930932cf21eb74b23cc95b7`에서 실행했고, 배포 커밋 `e7798c6cf9c6d3422ce4e21d845897f9540023b3`에는 README와 설명 문서 2개만 추가 변경되었습니다. 실행 코드는 동일합니다.

새 서버·데이터 ZIP은 전체 원격 다운로드 SHA-256과 익명 다운로드를 검증했습니다. 실제 기기의 CDN 다운로드 속도·게임 UI·3D 재생 및 이번 Mac 앱의 GUI 실행은 검증하지 않았습니다. Mac 앱은 Linux에서 ARM64로 교차 빌드하고 런타임·struct·CA·서명 페이지·리소스 봉인·ZIP을 검사합니다.

[서버 데이터 ZIP](IdolyPride-ServerData-v0.3.23.zip) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/blob/downloads/restored-media-v0.3.23/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/blob/downloads/restored-media-v0.3.23/RELEASE-VERIFICATION.json). 서버 데이터는 서버 앱에 포함되어 있어 일반 업데이트에는 별도로 받을 필요가 없습니다.

첨부 업로드 인증·Actions 사용 한도로 Assets 대신 위 개별 링크에서 제공합니다. 비공개 저장소는 GitHub 로그인 후 Download raw file로 받습니다.
