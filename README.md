# 아이프라 로컬 v0.3.29 시험판

**스토리 파일 연결과 Android 로딩 화면을 수정한 v0.3.29 시험판입니다. 사용자가 Android의 온라인 스토리와 비행기 모드의 새 회차 재생을 확인했습니다.**

Android 클라이언트 3개와 Android·Mac 서버 2개는 소스 `5dd78609c945f834ea17cc495e070f42050804dd`에서 제작했습니다. 데이터 ZIP은 v0.3.25, Mac IPA 3개는 v0.3.27의 동일 파일을 원래 소스와 검증 기록을 유지해 제공합니다.

| 기기 | 서버 | 일본어 UI | 한국어 UI | 영어 UI |
| --- | --- | --- | --- | --- |
| Android ARM64 | [서버 APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-Local-Server-Android.apk) | [JA APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk) | [KO APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk) | [EN APK](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk) |
| Apple Silicon Mac | [서버 ZIP](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-Local-Server-macOS-arm64.app.zip) | [JA IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-6.1.1-Local-PlayCover-ja.ipa) | [KO IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-6.1.1-Local-PlayCover-ko.ipa) | [EN IPA](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-6.1.1-Local-PlayCover-en.ipa) |

21번 진단은 인터넷 연결 상태에서 수집됐습니다. 이벤트 `adv_event_2510_01_01.txt`와 메인 `adv_main_01_01_02.txt`의 요청이 기존 파일 이름과 번역본 generation을 결합해 404로 거절된 것을 주소 해시로 확인했습니다. 서버는 검증된 원본·번역 행에서만 이 조합을 별칭으로 만들어 기존 번역 레코드로 연결합니다. 파일 크기·MD5·캐시 검사는 유지되며 알 수 없는 주소는 계속 거절합니다. 실제 고정 한국어 자료 두 개의 GET·HEAD·Range와 전체 해시를 호스트에서 확인했습니다.

Android 스토리 회전 안내 화면의 두 버튼에는 표시 효과 참조가 비어 있었습니다. 각 버튼에 이미 존재하며 로딩 화면도 참조하던 CanvasGroup 두 개로 연결했습니다. 정확한 49,540바이트 UI 파일의 2바이트만 바꾸고 다른 369개 객체와 직렬화 구조를 유지합니다. 런타임 후크·예외 숨김·프레임별 작업을 추가하지 않습니다. Unity 추출 식별자에도 수정된 파일 해시를 포함합니다. Mac IPA에는 이 Android UI 수정이 적용되지 않습니다.

서버와 클라이언트 APK는 별도 파일입니다. 원하는 UI 언어의 클라이언트 하나를 설치합니다. 기존 계정·설정·Downloads 자료를 삭제하거나 전체 리소스를 다시 받을 필요가 없습니다. 번역 패키지와 데이터 ZIP은 서버 앱에 포함됩니다. Mac IPA는 PlayCover에서 다시 서명해야 합니다.

한국어 번역은 부분 제공입니다. 확인한 ADV 3,492개 중 3,091개에 번역 변경이 있고 401개는 일본어로 남습니다. 모든 자막·이미지 글자·UI의 완전 번역을 뜻하지 않습니다. 사진 최종 생성·Firebase 업로드와 현재 포즈 촬영 조건 오류는 이번 변경으로 해결했다고 확인하지 않았습니다.

사용자는 제공한 Android 서버·한국어 클라이언트를 업데이트한 뒤 온라인에서 이벤트·메인 스토리가 재생되고, 비행기 모드에서도 이전에 열지 않은 새 회차가 재생된다고 확인했습니다. 이 결과는 사용자 답변을 근거로 기록했습니다. 설치 APK 해시·새 HTTP 요청 카운터·예외 로그 부재를 직접 측정한 자료는 없습니다. Mac 오프라인 실행·3D 재생과 Play Protect 판정은 아직 검증하지 않았습니다.

[데이터 ZIP](https://github.com/tagundo/IdolyPride_client/raw/refs/heads/downloads/story-resources-v0.3.29/IdolyPride-ServerData-v0.3.25.zip) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/blob/downloads/story-resources-v0.3.29/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/blob/downloads/story-resources-v0.3.29/RELEASE-VERIFICATION.json). 비공개 저장소에서는 GitHub 로그인 후 Download raw file을 이용합니다.
