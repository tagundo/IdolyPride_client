# Mac 사운드 설정 저장 보완 v0.3.27

**Mac PlayCover 클라이언트의 사운드 설정 저장을 보완한 v0.3.27입니다.** 새 IPA는 JA·KO·EN 3개이며, 서버 2개는 v0.3.26, 데이터와 Android 클라이언트 3개는 v0.3.25의 검증된 동일 파일입니다.

BGM·효과음·음성의 음량과 켜짐 설정 변경은 원래 게임 동작을 먼저 수행하고, 변경이 400ms 동안 없은 뒤 Unity 업데이트에서 원래 Save를 호출합니다. 400ms 전에 종료하거나 Unity 업데이트가 없는 상태까지 저장을 보장하지 않습니다. 실제 Mac에서 종료·재시작 후 유지되는지와 Android 사운드 동작은 이번 검증에 포함되지 않았습니다.

| 기기 | 서버 | 일본어 UI | 한국어 UI | 영어 UI |
| --- | --- | --- | --- | --- |
| Android ARM64 | [v0.3.26 APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-Local-Server-Android.apk) | [기존 JA APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk) | [기존 KO APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk) | [기존 EN APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk) |
| Apple Silicon Mac | [v0.3.26 서버 ZIP](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-Local-Server-macOS-arm64.app.zip) | [새 JA IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-6.1.1-Local-PlayCover-ja.ipa) | [새 KO IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-6.1.1-Local-PlayCover-ko.ipa) | [새 EN IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-6.1.1-Local-PlayCover-en.ipa) |

플랫폼별 원하는 UI 언어 1개만 설치합니다. Mac IPA는 PlayCover에서 다시 서명해야 합니다. UI 언어는 파일에 고정되며 ADV 언어는 서버 설정을 따릅니다. 기존 계정·앱 데이터와 Downloads 리소스를 삭제하지 않습니다.

새 IPA 3개는 같은 실제 제작 소스, 새 네이티브·IPA·언어별 폰트·UI 독립 검사에 연결합니다. 기존 33개 iOS 훅과 103개 별칭을 유지하고 사운드용 8개를 추가했습니다. 한글 11,172자 폰트, 기존 일본어 폰트, 고정 UI, 로컬 API·Octo·부트스트랩 변경 범위를 검증했습니다. 호스트 검사는 146개 통과·1개 건너뜀·하위 검사 66개 통과이며, 실제 기기 화면·3D 재생·사운드 저장 결과를 입증하지 않습니다.

[기존 데이터 ZIP](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/mac-sound-persistence-v0.3.27/IdolyPride-ServerData-v0.3.25.zip) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/blob/downloads/mac-sound-persistence-v0.3.27/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/blob/downloads/mac-sound-persistence-v0.3.27/RELEASE-VERIFICATION.json). 데이터는 서버에 포함되어 일반 업데이트에는 따로 받을 필요가 없습니다.

첨부 업로드 인증 오류와 Actions 사용 한도로 개별 Git LFS 다운로드 링크를 제공합니다. 비공개 저장소는 GitHub 로그인 후 Download raw file로 받습니다.
