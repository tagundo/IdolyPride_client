# Mac 서버 0.3.12

서버 엔진이 `ModuleNotFoundError: No module named struct`로 종료되던 패키징 오류를 수정했습니다. 기존 실행 파일의 CArchive에 별도로 저장된 일반 Python 모듈까지 정확한 원본 바이트로 포함합니다.

기존 서버 앱을 완전히 종료하고 ZIP에서 꺼낸 IdolyPrideLocalServer.app으로 교체하세요. 기존 PlayCover IPA와 계정·저장 데이터는 그대로 사용합니다. 데이터 폴더를 지우지 않습니다.

호스트 표준 라이브러리를 사용할 수 없는 격리 실행에서 실제 engine/payload 임포트를 검사했고, struct를 제거하면 같은 오류가 재현됩니다. 별도의 Linux 검증에서는 동일한 C 임베딩 실행부로 엔진 시작·암호화 로그인·홈·리소스 요청·종료 65개 검사를 통과했습니다. 이때 Darwin 네이티브 모듈42개만 명시적인 Linux 대체품을 썼으며 실제 Mac 실행 검증은 아닙니다.

Apple Silicon/macOS13 이상용입니다. 서버 앱은 ad-hoc 서명이며 Apple 공증은 포함되지 않습니다. 새 IPA 설치는 필요 없습니다.
