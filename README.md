# 리소스 전송 진단·번역 시작 오류 수정 v0.3.26

**서버 앱만 v0.3.26으로 업데이트합니다.** 기존 게임 클라이언트를 계속 사용할 수 있습니다. 아래 언어별 클라이언트·데이터·번역 번들은 v0.3.25와 동일한 파일입니다. 기존 앱·계정·Downloads 리소스를 삭제하지 않습니다.

- KO·EN 번역이나 갱신된 JA 게이트웨이 목록이 남아 있을 때, 다음 서버 시작이 이를 원본 목록으로 잘못 검증하던 문제를 수정합니다. 원본 목록의 무결성 검사는 유지합니다.
- 미리 받은 파일은 서버가 사용하는 같은 리소스 보관 폴더에 있으면 다시 사용합니다. 원본 파일과 번역된 파일은 각각의 목록·해시로 구분합니다. 인터넷 연결이 필요한 누락 파일까지 오프라인으로 제공한다고 주장하지 않습니다.
- v0.3.24 등 기존 서버에서 전체 다운로드 진행이 멈출 때 확인할 수 있도록 로컬 제공량·CDN 수신량·현재 요청·최근 실패 요청을 제한된 진단 정보로 표시합니다. HTTP 오류와 현재/누적 상태를 구분하며, 이번 진단 추가만으로 실제 기기의 정지 원인이 해결되었다고 주장하지 않습니다.

| 기기 | 새 서버 | 기존 일본어 UI | 기존 한국어 UI | 기존 영어 UI |
| --- | --- | --- | --- | --- |
| Android ARM64 | [서버 APK](IdolyPride-Local-Server-Android.apk) | [JA APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk) | [KO APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk) | [EN APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk) |
| Apple Silicon Mac | [서버 앱 ZIP](IdolyPride-Local-Server-macOS-arm64.app.zip) | [JA IPA](IdolyPride-6.1.1-Local-PlayCover-ja.ipa) | [KO IPA](IdolyPride-6.1.1-Local-PlayCover-ko.ipa) | [EN IPA](IdolyPride-6.1.1-Local-PlayCover-en.ipa) |

게임 클라이언트는 플랫폼별 원하는 언어 1개만 설치합니다. 이미 v0.3.25를 사용 중이면 다시 설치할 필요가 없습니다. UI 언어는 클라이언트 파일에 고정되며 ADV 언어는 서버 설정을 따릅니다.

새 서버 2개는 최종 소스와 새 독립 QA에 연결합니다. 재사용하는 데이터 1개와 클라이언트 6개는 기존 파일의 전체 SHA·제작 소스·독립 QA·LFS 커밋을 그대로 보존합니다. 번역 번들은 새 서버 안에 같은 검증된 바이트로 포함됩니다.

전체 호스트 검사: 통과 5414개, 건너뜀 17개, 하위 검사 통과 353개. 실제 기기 화면·3D 재생·Mac GUI 검증은 포함하지 않습니다.

[기존 데이터 ZIP](IdolyPride-ServerData-v0.3.25.zip) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/blob/downloads/translation-cache-hotfix-v0.3.26/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/blob/downloads/translation-cache-hotfix-v0.3.26/RELEASE-VERIFICATION.json) · [변경 설명](https://github.com/tagundo/IdolyPride_client/blob/main/docs/translation-cache-v0.3.26.md). 데이터는 서버에 포함되어 일반 업데이트에는 따로 받을 필요가 없습니다.

첨부 업로드 인증·Actions 사용 한도로 Assets 대신 위 개별 링크에서 제공합니다. 비공개 저장소는 GitHub 로그인 후 Download raw file로 받습니다.
