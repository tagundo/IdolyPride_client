# 포즈·홈 대화·한글·번역·Mac 보관 폴더 v0.3.25

**서버와 선택한 언어의 게임 클라이언트를 모두 v0.3.25로 업데이트합니다.** 기존 앱·계정·리소스를 삭제하지 않습니다. 서버와 게임을 종료한 뒤 업데이트하고 다시 시작합니다.

| 기기 | 서버 | 일본어 UI | 한국어 UI | 영어 UI |
| --- | --- | --- | --- | --- |
| Android ARM64 | [서버 APK](IdolyPride-Local-Server-Android.apk) | [JA APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ja.apk) | [KO APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64-ko.apk) | [EN APK](IdolyPride-Local-Graphics-Diagnostic-Android-arm64-en.apk) |
| Apple Silicon Mac | [서버 앱 ZIP](IdolyPride-Local-Server-macOS-arm64.app.zip) | [JA IPA](IdolyPride-6.1.1-Local-PlayCover-ja.ipa) | [KO IPA](IdolyPride-6.1.1-Local-PlayCover-ko.ipa) | [EN IPA](IdolyPride-6.1.1-Local-PlayCover-en.ipa) |

각 플랫폼의 클라이언트 3개는 같은 앱의 언어별 대체 파일입니다. **원하는 언어 1개만 설치**합니다. 언어를 바꾸려면 해당 파일로 업데이트합니다. UI 언어는 설치 파일에 고정되고 ADV 언어는 서버의 번역 설정을 따릅니다. Android 패키지·서명 인증서와 IPA 번들 ID를 언어별로 동일하게 유지합니다.

- 감상 모드 포즈 촬영은 1명부터 원본 무대의 최대 수용 인원까지 허용합니다. 3인 무대에서 1·2명을 선택했을 때 서버가 거부하던 문제를 수정합니다. 인원 초과·소유권·의상 호환성과 원본 제외 조건은 계속 검사합니다.
- 새 서버 데이터에 원본 홈 대화 559개·대사 3,091줄을 추가하고, 감상 모드 `Home.ReadTalk`의 첫 읽기·현재 캐릭터 상태 응답·재시도를 처리합니다. 일반 모드의 해금·보상 규칙을 변경하지 않습니다.
- 6개 클라이언트에 OFL 라이선스의 Pretendard JP 폴백 폰트를 포함합니다. 한글 완성형 11,172자의 포함 여부, 기존 일본어 폰트와 다른 Unity 객체 보존 및 폴백 연결을 검사합니다. JA·KO·EN별 원본 I18n 4,199키 테이블을 미리 반영합니다. 원문 대비 KO는 3,822키, EN은 3,845키의 내용이 변경됩니다. 일부 고정 문구·커스텀 오버레이는 이번 번역에 연결하지 않아 원문이 남습니다.
- 서버에는 KO·EN ADV 자막·대사 리소스를 제공하는 별도 번역 번들을 포함합니다. 원본 마스터 데이터와 번역 번들은 별도 SHA로 검증합니다. ADV 리소스 3,492개 중 KO는 3,091개 번역·401개 누락, EN은 3,093개 변경·398개 원문과 동일·1개 누락입니다. 번역 자료의 출처·리비전·자료 조건과 원문 유지 수를 보존합니다.
- Mac 서버 앱에서 서버를 멈춘 뒤 **게임 리소스 보관 → 보관 폴더 변경**으로 저장 위치를 고를 수 있습니다. 선택한 경로를 유지하며, Finder에서 열기와 기본 Downloads 위치 복원을 제공합니다. 다음 서버 시작부터 적용하고, 기존 파일을 자동으로 옮기거나 삭제하지 않습니다.
- 리소스 캐시를 닫은 뒤 대기 중이던 복사 작업이 차례를 받더라도 새 파일을 열지 않도록 수정했습니다.

실제 원본 데이터와 동일한 암호화 요청으로 이전 서버의 거부·수정 서버의 허용 및 인원 초과 거부를 비교했습니다. 대화 첫 읽기·재시도와 일반 모드 상태 보존도 검증합니다. 사진 이미지 생성 API나 촬영 RPC 전체를 구현한 버전은 아닙니다.

전체 호스트 검사: 통과 5381개, 건너뜀 16개, 하위 검사 통과 353개. 실패는 없었습니다.

새 데이터 ZIP·서버 2개·클라이언트 6개의 전체 원격 다운로드 SHA-256과 익명 다운로드를 검증했습니다. 데이터 제작 커밋은 `1a0dcd15d9016cc1b9548b0bd6c6bc71f8f01356`이며, 최종 배포 소스에서도 동일한 입력 파일을 확인했습니다. 서버 2개와 전체 호스트 검사는 최종 소스 `0f9f89785848291c44ecaf6ac6b42a213f7f2db1`에 연결합니다. Android 클라이언트 3개는 실제 제작 소스 `751238f4b1d892eea18f7138bbca0d0432c6b37d`, IPA 3개는 `641a142ebae0f1c0a095979d68fc96655272d719`에 연결합니다. Android→iOS 소스 차이는 승인된 C++ import stub의 단일 export 추가뿐이며, 그 이후 변경은 Mac 서버·Markdown 문서와 각각 검증된 서버 전용 변경에 한정되어 클라이언트 제작 입력을 유지했습니다.

실제 기기 게임 화면의 한글·번역 표시, 3D 재생과 이번 Mac 앱 GUI 실행은 검증하지 않았습니다. Mac 앱은 Linux에서 ARM64로 교차 빌드해 런타임·struct·CA·서명 페이지·리소스 봉인·ZIP을 검사합니다. IPA는 PlayCover에서 다시 서명해 설치합니다.

[새 서버 데이터 ZIP](IdolyPride-ServerData-v0.3.25.zip) · [SHA256SUMS](https://github.com/tagundo/IdolyPride_client/blob/downloads/pose-font-v0.3.25/SHA256SUMS) · [배포 검증](https://github.com/tagundo/IdolyPride_client/blob/downloads/pose-font-v0.3.25/RELEASE-VERIFICATION.json) · [소스 정책](https://github.com/tagundo/IdolyPride_client/blob/downloads/pose-font-v0.3.25/COMPONENT-SOURCE-POLICY.json) · [변경 설명](https://github.com/tagundo/IdolyPride_client/blob/main/docs/pose-font-v0.3.25.md). 데이터와 번역 번들은 서버 앱에 포함되어 있어 일반 업데이트에는 따로 받을 필요가 없습니다.

첨부 업로드 인증·Actions 사용 한도로 Assets 대신 위 개별 링크에서 제공합니다. 비공개 저장소는 GitHub 로그인 후 Download raw file로 받습니다.
