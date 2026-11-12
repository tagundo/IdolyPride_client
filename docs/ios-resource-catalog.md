# iOS 리소스 카탈로그

PlayCover용 6.1.1 클라이언트는 Octo의 앱 번호 `212`, 버전 `105051`을 사용합니다. Android의 `205051`과 다르므로 Mac 서버에는 별도 iOS 카탈로그가 필요합니다. 원본 iOS `SolisOctoSetupper.GetD`의 기본값 `105000`과 클라이언트의 `51`을 대조했으며, 계정 인증 없이 공개 카탈로그를 보존했습니다.

현재 고정된 iOS 아카이브는 리비전 `1159`, 원본 protobuf `5,841,650`바이트, SHA-256 `b431d531ef393ff1807229bbee4bbe75d4c9821007329f91e4822527d9844e9b`입니다. 에셋 번들 49,370개와 일반 리소스 5,072개의 원본 식별자·크기·MD5·업로드 버전을 유지합니다. 로컬 응답은 다운로드 URL 형식만 이 서버의 주소로 바꿉니다.

번들에는 `data/public-octo-ios/settings.json`과 `data/public-octo-ios/manifest.pb`를 넣습니다. Android의 `data/public-octo/`와 캐시가 섞이지 않도록 iOS 캐시는 `octo-cache-ios/`에 보관합니다. `settings.json`은 Android와 같은 일곱 필드를 사용하되 버전과 리비전을 iOS 값으로 검증합니다. 공개 SDK 설정만 포함하며 계정 토큰·인증 백업·저장 DB를 넣지 않습니다.

공개 서버 페이로드를 새로 만들 때는 다음 옵션을 사용합니다. 두 플랫폼의 카탈로그를 같은 페이로드에 넣을 수 있습니다.

```sh
python3 tools/build_server_payload.py \
  --data-dir data \
  --octo-data /path/to/public-octo \
  --ios-octo-data /path/to/public-octo-ios \
  --output /path/to/ServerData.zip
```

Mac 앱의 엔진은 `resource_platform="ios"`를 명시해서 시작합니다. 기본 Python 런타임의 플랫폼은 기존 Android 동작을 유지합니다. 각 게이트웨이는 자신의 버전 경로만 응답하며 다른 플랫폼의 경로는 `404`로 거부합니다. 요청 리비전은 `0` 또는 보존된 리비전만 지원하고, 보존하지 않은 이력은 `409`로 거부합니다.

`download_missing_resources`는 게임이 요청한 파일을 보존할지 정하는 불리언입니다. 끄면 이미 검증해서 보관한 파일만 제공합니다. 서버 앱이나 이 옵션이 클라이언트 IPA·APK를 설치하지는 않습니다. 원본 크기와 MD5 검증을 통과한 리소스만 게임에 전달하며, 전송 완료는 Unity가 장면을 재생했다는 뜻이 아닙니다.

Android와 iOS에서 직접 복구한 6.1.1 protobuf는 파일 359개의 정의가 모두 동일했습니다. 게임 API와 공개 마스터는 공유할 수 있지만 플랫폼별 Unity 리소스 카탈로그는 구분해야 합니다. Mac 페이로드 설치기는 JSON 마스터 49개와 감상 모드의 마스터 태그 및 여섯 오버레이 팩도 허용하며, 기존 `state.db`, `media-state.db`, 인증 백업을 설치 대상에 포함하지 않습니다.

검증은 실제 공개 iOS 매니페스트의 암호화 왕복, 원본 리소스·에셋 번들의 크기/MD5, 별도 캐시, 두 프로필의 로컬 암호화 RPC를 포함합니다. Linux에서 통과한 서버 검증은 macOS 앱 실행이나 PlayCover 게임 화면 검증을 대신하지 않습니다.
