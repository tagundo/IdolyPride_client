# 아이프라 로컬 v0.3.28 시험판

**로컬 리소스 연결과 진단을 보완한 v0.3.28 시험판입니다. 실제 Android 비행기 모드 재검증은 아직 완료되지 않았습니다.**

Android 클라이언트 3개와 Android·Mac 서버 2개는 소스 `45378d05d3b987923a3f6ca67a23c7166cf56b35`에서 새로 제작했습니다. 데이터 ZIP은 v0.3.25, Mac용 IPA 3개는 v0.3.27의 동일 파일을 원래 제작 소스와 검증 기록을 유지해 제공합니다.

| 기기 | 서버 | 일본어 UI | 한국어 UI | 영어 UI |
| --- | --- | --- | --- | --- |
| Android ARM64 | [서버 APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-Local-Server-Android.apk) | [JA APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk) | [KO APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk) | [EN APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk) |
| Apple Silicon Mac | [서버 ZIP](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-Local-Server-macOS-arm64.app.zip) | [JA IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-6.1.1-Local-PlayCover-ja.ipa) | [KO IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-6.1.1-Local-PlayCover-ko.ipa) | [EN IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-6.1.1-Local-PlayCover-en.ipa) |

원하는 UI 언어의 클라이언트 하나를 설치합니다. 서버 APK와 클라이언트 APK는 별도 파일입니다. Mac IPA는 PlayCover에서 다시 서명해야 합니다. 기존 계정·앱 데이터와 Downloads 리소스는 삭제하지 않습니다. 데이터 ZIP과 번역 자료는 서버 앱에 포함됩니다.

Android에서는 로컬 HTTP 응답이 정상이어도 외부 인터넷 연결 검사 때문에 다운로드 완료가 거부될 수 있는 경로를 확인했습니다. 고정된 `http://127.0.0.1:8080/octo/…`의 정규 리소스 객체 URL에 한해 해당 연결 검사를 처리합니다. 기존 HTTP·파일 I/O·오류·MD5 검증은 유지합니다. 다른 URL과 전역 Unity 연결 상태를 바꾸거나 다운로드 성공을 만들어내지 않습니다. 서버에 HTTP 요청·캐시 적중·실패 경로 표시도 추가했습니다.

촬영 초기화에는 누락된 예약 이미지 번호를 최대 20개까지 보완하는 변경이 포함됩니다. 사진 최종 생성·Firebase 업로드는 아직 지원하지 않습니다. 현재 보고된 포즈 촬영 INVALID_ARGUMENT와 RadioButtonView.SetDisabled 예외가 해결되었다고 확인된 상태는 아닙니다.

한국어 번역은 부분 제공입니다. 현재 확인한 ADV 3,492개 중 3,091개에 번역 변경이 있고 401개는 일본어로 남습니다. 자막·이미지 글자·모든 UI의 완전 번역을 뜻하지 않습니다.

최신 Elichika `v2026.11.12.4`의 소스와 실제 APK의 제한된 manifest·DEX·리소스를 비교했습니다. Elichika APK 전체 SHA·서명이나 실제 오프라인 실행은 검증하지 않았습니다. 새 파일은 소스·패키지·서명·원격 전체 SHA를 검사했지만 실제 Mac 오프라인 실행·3D 재생과 Play Protect 판정은 이번 확인에 포함되지 않습니다.

[데이터 ZIP](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/local-resources-v0.3.28/IdolyPride-ServerData-v0.3.25.zip) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/blob/downloads/local-resources-v0.3.28/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/blob/downloads/local-resources-v0.3.28/RELEASE-VERIFICATION.json). 일반 업데이트에는 데이터 ZIP을 따로 받을 필요가 없습니다.

개별 Git LFS 다운로드 링크를 제공합니다. 비공개 저장소에서는 GitHub 로그인 후 Download raw file을 이용합니다.
