# 검증 상태

2026-11-14 통합 IPA 시험판을 생성하고, 실제 Apple SDK 빌드와 새 iOS Simulator에서 서버 코어 검사를 통과했습니다.

- 빌드 소스: `7afaeda34a7c762c9a7fe2ffe4ea3fc9b6c4d2a6`
- [성공한 Actions 실행](https://github.com/tagundo/IdolyPride_client/actions/runs/43584948791)
- [검증된 IPA 다운로드 브랜치](https://github.com/tagundo/IdolyPride_client/tree/downloads/ios-unified-prototype-source-7afaeda34a7c762c9a7fe2ffe4ea3fc9b6c4d2a6)
- 파일: `IdolyPride-6.1.1-Unified-iOS-ko.ipa` / 477,724,856 bytes
- SHA-256: `c696a79719a054698dfe6dc03d26d24dddc6d1acb38b892fcc624d98c3769b02`

## 통과한 검사

Xcode 16.4 / iOS SDK 18.5로 기기용 arm64 프레임워크와 시뮬레이터용 프레임워크를 빌드했습니다. Python과 표준 확장 모듈의 실제 Mach-O 플랫폼·의존성·서명을 검사하고, 기존 게임 코드·SDK·리소스 보존과 완성 IPA의 전체 멤버 SHA/CRC를 확인했습니다.

새 iPhone 16 Pro / iOS 18.5 Simulator와 새 로컬 저장소에서 다음을 확인했습니다.

- 서버의 두 리스너가 준비된 뒤 검사용 AppDelegate의 Unity 시작 진입점을 메인 스레드에서 정확히 한 번 호출.
- 네이티브 CommonCrypto의 NIST 128/256 비트 벡터. Python 작업 스레드 경계에서는 128 비트 암호화·복호화와 잘못된 IV 거부.
- 실제 암호화 H2 요청·응답으로 `System.Check`, 새 `Auth.Login`, `Home.Enter` 성공.
- 리소스 서버의 호스트 루프백 연결과 검사 후 생성한 Simulator 종료·삭제.

파일을 전달할 때 Actions ZIP 전체를 API가 제공한 SHA-256으로 검증한 다음 IPA를 스트리밍 추출했습니다. IPA의 전체 SHA, 빌드 소스 파일 해시, 입력 데이터 핀, 원본 SDK 보존 보고서를 대조했습니다. 배포된 LFS 객체도 전체 재다운로드 SHA 검증을 통과했습니다.

## 남은 검증

iPhone·iPad 실기기의 실제 게임·MV 재생, 성능과 PlayCover 실행은 아직 검증하지 않았습니다. Simulator 결과는 서버 코어와 시작 대기의 검사이며 실제 Unity 공연 실행 검사가 아닙니다. 기기 설치에는 개인 서명이 필요합니다. 선택적인 실험용 Go 라이브 시뮬레이터는 이 iOS 이식에 포함하지 않았습니다.
