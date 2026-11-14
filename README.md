# UI 번역·스토리 특수문자 수정 v0.3.30

기존 [v0.3.29 서버](https://github.com/tagundo/IdolyPride_client/releases/tag/local-server-v0.3.29)와 사용하는 클라이언트 수정판입니다. 서버 앱은 새로 제작하지 않았습니다. APK와 PlayCover IPA는 별도 파일이며, 원하는 UI 언어 하나를 설치합니다.

한국어 고정 UI 문구 1,961개와 홈 라이브·선물·보너스·미션·최신 스토리 및 선택 배지 이미지 7개를 추가 적용했습니다. 영어 고정 UI 문구는 1,684개를 추가 적용했습니다. 이벤트가 없을 때의 안내문과 한국어 조사 처리 표기 33개도 정리했습니다.

스토리의 긴 대시가 네모로 나오던 문제는 원본 글리프와 폰트·아틀라스를 보존하고 한국어 폰트를 별도로 두어 수정했습니다. 한국어 전용 아틀라스는 1024×1024입니다. 번역과 이미지는 설치 파일에 미리 반영하며, 프레임마다 번역을 수행하지 않습니다.

새 APK·IPA 여섯 파일 모두 소스 `a6f3c687b6610ab8416e2e515bafb618e249bc03`에서 제작했습니다. 서명·파일 구성·직렬화 객체·문구·글리프 연결·이미지 픽셀 등 패키지 검사를 통과한 파일을 별도 다운로드 목록에 제공합니다. 실제 Android 및 PlayCover 화면의 재생 검증은 아직 하지 않았으며, 번역이 모두 완료되었다는 뜻은 아닙니다. 이전 버전의 사용자 플레이 결과를 이 수정판의 검증으로 사용하지 않았습니다.

| 기기 | 일본어 UI | 한국어 UI | 영어 UI |
| --- | --- | --- | --- |
| Android ARM64 | `IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk` | `IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk` | `IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk` |
| Apple Silicon Mac / PlayCover | `IdolyPride-6.1.1-Local-PlayCover-ja.ipa` | `IdolyPride-6.1.1-Local-PlayCover-ko.ipa` | `IdolyPride-6.1.1-Local-PlayCover-en.ipa` |

[다운로드 목록](https://github.com/tagundo/IdolyPride_client/tree/downloads/client-translation-v0.3.30) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/tree/downloads/client-translation-v0.3.30/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/tree/downloads/client-translation-v0.3.30/RELEASE-VERIFICATION.json). 비공개 저장소의 파일은 GitHub 로그인 후 이용합니다. 채팅에서 제공하는 임시 다운로드 링크는 별도이며 이 배포 기록에 저장하지 않습니다.

기존 계정·설정·다운로드 자료를 삭제할 필요는 없습니다. Mac IPA는 PlayCover에서 다시 서명해야 합니다.
