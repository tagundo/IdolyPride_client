# 프로토콜 분석 메모

이 문서는 원본 바이너리 분석·공개 캡처·현재 서버 동작을 구분합니다. 사용자 Android에서는 로컬 연결판의 로그인·홈·초기 튜토리얼 진행을 확인했지만, 우리 환경에서 원본 APK의 공식 로그인 후 통신을 직접 수집한 기록은 없습니다. 원본 기준 검증과 미구현 경로는 [원본 클라이언트 기준 분석](original-client-baseline.md)에 정리했습니다.

## 분석 입력

입력은 [IdolyPride_client releases](https://github.com/tagundo/IdolyPride_client/releases)의 6.1.1입니다. 내려받은 XAPK·복호화 IPA의 SHA-256을 릴리스 asset digest와 대조했습니다.

| 플랫폼 | 확인한 버전 | 파일 SHA-256 |
| --- | --- | --- |
| Android arm64-v8a | 6.1.1 / versionCode 414 | `ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36` |
| iOS | 6.1.1 / build 156 | `33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848` |

Android IL2CPP 바이너리에서 protobuf descriptor 359개 파일·68개 서비스·428개 RPC·최상위 메시지 1,723개를 복구했고 descriptor pool 로딩과 서버 smoke test를 통과했습니다. 같은 버전 iOS 바이너리에서 독립적으로 확인한 359개 descriptor도 Android와 바이트 단위로 일치합니다. 이 결과는 스키마의 일치이며 기기 연결 성공을 뜻하지 않습니다.

descriptor 파일은 `data/protocol/idolypride-6.1.1.pb` 위치를 기본값으로 사용하며 SHA-256은 `c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad`입니다. `tools/extract_client_schema.py`로 원본 XAPK에서 다시 추출할 수 있습니다. 현재 서버는 427개 unary RPC를 등록합니다. server-streaming `/api.Health/Watch`는 등록하지 않으며 호출 시 `UNIMPLEMENTED`를 반환합니다.

소스 `b18f711`의 기본 명시 처리 경로는 52개이며 제한된 자체 처리 50개와 공개 fixture 전용 2개를 포함합니다. 나머지 unary 375개는 가져온 사용자 fixture가 없으면 기본 자체 처리가 없고, `Quest.Start`의 첫 메인 퀘스트 실험도 기본 OFF입니다. 등록된 경로 수를 전체 기능 구현 수로 계산하지 않습니다. 경로별 타입과 제한은 [RPC 분류 CSV](rpc-coverage-6.1.1.csv)를 따릅니다.

`inspect`의 `schema_sha256`은 파일 순서와 로딩 경로를 정규화한 스키마 지문이며 원본 파일 해시와 구분합니다. 현재 6.1.1의 정규화된 지문은 `0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3`입니다. 동일한 스키마를 Solis 모듈이나 내보낸 descriptor set으로 읽어도 같은 지문을 사용합니다.

공개 [SolisClient](https://github.com/vilebbit/SolisClient/tree/a72ee470a4771858f7868a0963bece2e998a43f5)의 구형 스키마도 읽을 수 있지만 6.1.1과 필드 번호·형식 차이가 있습니다. 서비스 이름이 같다는 이유로 전체 메시지 호환성을 가정하지 않습니다.

## 전송 형식

두 클라이언트에서 `Grpc.Net.Client`, `Cysharp.Net.Http.YetAnotherHttpHandler`, `Qua.Network.DefaultMarshallerFactory`와 관련 문자열을 확인했습니다. 공개 [marshaller.py](https://github.com/vilebbit/SolisClient/blob/a72ee470a4771858f7868a0963bece2e998a43f5/marshaller.py)를 참고해 독립 구현한 codec은 SolisClient와 바이트 일치·양방향 복호화 테스트를 통과했습니다.

RPC 경로는 `/api.System/Check`, `/api.Auth/Login`, `/api.User/Get` 형태입니다. 일반 protobuf 직렬화에 다음 application envelope를 적용합니다.

| 바이트 위치 | 의미 |
| --- | --- |
| 0–1 | unsigned 16-bit little-endian `DataSize = key 길이 + 2` |
| 2 | 압축 여부: `00` 일반, `01` gzip |
| 3 | IV 파생에 쓸 key material의 바이트 길이 |
| 4부터 key 길이만큼 | IV 파생용 key material |
| `4 + key 길이` 이후 | AES-CBC·PKCS#7 암호문 |

클라이언트 요청 encoder는 8바이트 .NET ticks를 key material로 사용하므로 `0a 00 <압축 여부> 08`로 시작합니다. .NET ticks는 서기 1년부터 100ns 단위이며 Unix epoch 오프셋은 `621355968000000000`입니다. 공식 서버의 익명 응답에서는 18바이트·30바이트 key material도 실제 확인했으므로 decoder는 길이를 고정하지 않습니다.

AES 키는 공개 구현의 고정 seed에 대한 MD5, IV는 `seed + key material`에 대한 MD5입니다. gzip 플래그가 있으면 복호화 후 압축을 풉니다. 빈 protobuf 바이트는 빈 전송 본문으로 보존합니다. envelope에는 별도 무결성 태그가 없습니다.

서버가 내보내는 envelope는 비압축이며, 수신 시 gzip도 허용합니다. 잘못된 헤더·AES 블록·패딩·gzip은 거부하고 압축 해제 결과는 연결된 gzip member를 합쳐 최대 16MiB로 제한합니다. gRPC 메시지 송수신 한도 역시 16MiB입니다.

이 envelope는 gRPC 라이브러리가 다루는 메시지 본문입니다. 캡처에서 수동 추출할 때 gRPC 프레임의 `압축 플래그 1바이트 + 길이 4바이트`는 별도로 제거해야 합니다. 캡처 도구가 이미 프레임을 제거했다면 다시 5바이트를 버리지 않습니다.

## 로컬 인증·응답 재생

`Auth.Login`은 요청을 protobuf로 검증한 뒤 Firebase ID token을 사용하지 않고 `local-` 접두사의 임의 토큰을 발급합니다. SQLite에는 토큰의 SHA-256과 프로필·만료 시각만 저장하며 만료는 발급 후 30일입니다. 동일 프로필의 `serverUserId`·`publicUserId`는 재시작 후에도 유지됩니다.

`new-profile`은 이름·레벨 1·로컬 식별자의 최소 `User.Get` snapshot을 생성합니다. `import-profile`은 기존 `User.Get`의 protobuf 바이트와 스키마 지문을 보존하며, 응답에 public identity가 있으면 함께 유지합니다. 인증 정보는 가져오지 않습니다. 배포 앱은 별도의 마스터 기반 초기 캐릭터·카드·아이템·기본 편성을 준비합니다. 홈·설정·일부 튜토리얼·덱 변경과 라이브 목록 조회는 구현했으며, 실제 전투·일반 보상·콘텐츠 전체 해금은 미구현입니다. 세부 범위는 [게임 상태 구현 범위](gameplay-status.md)를 참고합니다.

보호된 RPC는 metadata의 `x-auth-token`을 요구합니다. 서버 프로세스는 `--profile`로 지정한 단일 프로필을 처리하고 다른 프로필의 세션을 거부합니다. 기본 응답과 오류는 다음과 같습니다.

| 요청 | 동작 |
| --- | --- |
| `System.Check` | 점검·심사 아님, keepalive 값 반환 |
| `System.GetMetadata`, `System.CheckApp` | 빈 정상 응답 |
| `Auth.Login` | 로컬 프로필·세션 발급 |
| `Master.Rule`, `Master.GetHelpCategory` | 로그인 전에도 준비한 fixture 제공; 없으면 `UNIMPLEMENTED` |
| `Master.Get` | 준비한 MasterTag 응답, 또는 fixture; 둘 다 없으면 `UNIMPLEMENTED` |
| `User.Get` | 요청 해시별 fixture → 일반 fixture → SQLite snapshot; 모두 없으면 `UNIMPLEMENTED` |
| `Home.*`, `Tutorial.Init/Progress/Skip/StartQuest`, `Deck.Save/Delete`, `Quest.Top/ListMain/ListAsset` | fixture 우선, 없으면 구현한 로컬 상태·목록 처리 |
| `Profile.Top` | fixture 우선; 없으면 저장된 계층 포인트와 홈의 마스터 규칙으로 계급 조회, 순위 0·빈 로컬 친구 목록, 상태 변경 없음 |
| `Profile.UpdateName` | fixture 우선; 없으면 이름만 원자적으로 저장하고 `commonResponse.updatedData.user` 반환; UTF-16 1–10단위·로컬 한 줄 입력 정책, 공식 금칙어·미션 진행 제외 |
| `Profile.UpdateMessage` | fixture 우선; 없으면 기존 `profile.message`만 원자적으로 저장하고 `commonResponse.updatedData.profile` 반환; UTF-16 1–60단위·공백만인 입력과 탭 거부, 공식 금칙어·미션·보상 제외 |
| 그 밖의 알려진 RPC | fixture 또는 구현이 없으면 `UNIMPLEMENTED` |
| 알 수 없는 RPC 경로 | `UNIMPLEMENTED` |
| 보호된 RPC의 세션 누락·불일치·만료 | `UNAUTHENTICATED` |
| 잘못된 envelope·protobuf | `INVALID_ARGUMENT` |
| 현재 스키마와 다른 지문의 프로필 snapshot | `FAILED_PRECONDITION` |

fixture 저장은 protobuf 문법 검증을 거치지만 게임 규칙·아이디 참조의 의미적 일관성까지 검증하지 않습니다. 정적 응답 재생은 라이브 점수 계산, 보상 지급, 스토리 진행 같은 상태 변경을 구현하지 않습니다. fixture에는 개인 유저 데이터가 포함될 수 있으며 `Auth.*` fixture는 금지합니다.

`Profile.Top`의 순위 0은 전역 순위를 계산했다는 뜻이 아니며 빈 친구 목록은 현재 로컬 친구 관계의 범위입니다. `Profile.UpdateName`은 비어 있지 않은 이름의 공백·Unicode 정규화를 그대로 보존합니다. 원본 UI가 제출 전에 제거하는 줄바꿈·탭은 서버의 로컬 정책으로 거부하며 공식 서버의 직접 요청 처리 규칙으로 단정하지 않습니다. `Profile.UpdateMessage`도 수락한 공백·Unicode 정규화와 CR/LF를 보존합니다. 원본 소개문 입력 필드의 줄바꿈 모드는 아직 확정하지 않았으며 탭·공백만인 입력 거부는 로컬 정책입니다. 세 경로는 원본 응답 소비 코드와 6.1.1 스키마를 대조하고 자동 검증했지만 실제 프로필 UI 검증은 아직 없습니다. `Auth.Create`는 계속 미지원이며 로컬 `Auth.Login`을 원본 신규 계정 생성 구현으로 취급하지 않습니다.

## 기존 공식 세션 수집

`collect-session`은 이미 준비된 현재 공식 요청 metadata의 JSON을 사용합니다. 최상위 객체에 문자열 키·값을 두며 `x-app-version`, `x-auth-token`, `x-master-version`이 필수입니다. Android·PlayCover의 인증 저장소 내보내기는 이 명령에 포함하지 않았습니다. 기기에 로그인되어 있다는 사실만으로 클라우드 환경에 세션이 전달되지는 않습니다.

목적지는 공식 TLS endpoint `api.game-idolypride.jp:443`으로 고정합니다. 수집 목록은 `Master.Get`, `User.Get`, `Home.Enter(skipUpdate=true)`, `Dokan.List`, `Notice.List`의 5개 요청이며 각 한 번 실행합니다. 로그인·Firebase 토큰 갱신·계정 생성·`Home.Login` 일일 초기화·자동 재시도는 하지 않습니다. gRPC 오류나 `x-error-code`가 나오면 중단하며 오류 출력에 원격 메시지·세션 metadata를 포함하지 않습니다.

정상 응답은 복호화·protobuf 검증 뒤 fixture로 저장하고 MasterTag JSON을 함께 보존합니다. 중간까지 성공한 파일은 유지합니다. `--profile` 가져오기는 전체 수집 성공 뒤 실행합니다. 입력 세션 metadata는 출력물에 저장하지 않습니다. 자동 테스트는 통과했지만 실제 계정 세션으로 이 흐름을 실행한 기록은 아직 없습니다.

### Android·PlayCover의 저장소 조사

Android는 HoshimiToolkit의 `--auth-xml`이 Firebase SharedPreferences의 `GET_TOKEN_RESPONSE` 레코드를 읽는 기존 경로를 제공합니다. 이 Firebase 인증 레코드와 게임 요청의 `x-auth-token` metadata는 서로 다른 데이터입니다. XML만으로 `collect-session` 입력이 준비된다고 가정하지 않습니다.

iOS 6.1.1 바이너리에서는 Firebase의 `AuthKeychainServices`, `AuthStoredUserManager`, `AuthKeychainStorageReal`, `SecItemCopyMatching` 및 `firebase_auth_1_` 등의 문자열을 확인했습니다. [공개 Firebase Auth 구현](https://github.com/firebase/firebase-ios-sdk/blob/11.14.0/FirebaseAuth/Sources/Swift/Auth/Auth.swift#L1828-L1838)은 `firebase_auth_<GOOGLE_APP_ID>` service에 직렬화한 사용자 객체를 저장합니다. [Keychain query 구현](https://github.com/firebase/firebase-ios-sdk/blob/11.14.0/FirebaseAuth/Sources/Swift/Storage/AuthKeychainServices.swift#L224-L234)은 account에 `firebase_auth_1_` 접두사를 붙이며 DataProtection Keychain을 사용합니다. prefs plist의 토큰 저장 경로는 확인하지 못했습니다.

PlayCover는 설정에 따라 저장소가 달라집니다. 조사한 [PlayTools 커밋](https://github.com/PlayCover/PlayTools/tree/fbc88801b63c791e4ef597a2746676c69864ccc6)의 기존 `playChain` 값은 `~/Library/Containers/io.playcover.PlayCover/App Settings/<실제 bundle ID>.plist`에 있습니다. [SecItem 중계 코드](https://github.com/PlayCover/PlayTools/blob/fbc88801b63c791e4ef597a2746676c69864ccc6/PlayTools/PlayLoader.m#L104-L140)는 true일 때만 PlayChain을 사용하고 false일 때는 macOS Keychain을 호출합니다.

PlayChain을 이미 사용하는 경우의 [실제 DB 경로](https://github.com/PlayCover/PlayTools/blob/fbc88801b63c791e4ef597a2746676c69864ccc6/PlayTools/MysticRunes/PlayedAppleDB.swift#L238-L258)는 `~/Library/Containers/io.playcover.PlayCover/PlayChain/<실제 bundle ID>.db`입니다. generic-password의 `genp` 테이블은 `agrp`·`acct`·`svce`로 항목을 구분하며 `v_Data` BLOB에 값을 저장합니다. 실제 사용자 설치 버전·설정·저장 레코드는 아직 확인하지 않았습니다.

`tools/export_playcover_auth.py`는 두 알려진 게임 bundle의 기존 설정·DB 존재 여부와 스키마만 기본 진단합니다. `playChain=true`인 bundle을 명시한 경우에만 SQLite를 read-only로 열고, Firebase service와 알려진 기본·공유 account에 일치하는 단일 `NSKeyedArchiver` BLOB을 새 0600 파일로 내보냅니다. `--ipa` 또는 `--google-app-id`로 service를 좁힐 수 있으며 여러 항목이 일치하면 거부합니다. native Keychain은 읽지 않고 인증값을 터미널에 출력하지 않습니다. 실제 사용자 설치에서의 내보내기는 아직 미검증입니다.

기존 인증을 보존하려면 `playChain`을 바꾸지 않습니다. `playChainDebugging`도 켜지 않습니다. 해당 디버그 경로는 Keychain query와 결과 전체를 기록합니다. Firebase archive 내보내기와 현재 게임 세션 metadata 수집은 별도 단계입니다. archive는 `collect-session`의 JSON 입력이 아니며 in-process 세션 수집은 아직 구현하지 않았습니다.

## 마스터·Octo 보존

공식 TLS endpoint에서 인증 없는 `System.Check`·`Master.Get` 응답을 실제로 받아 복호화·protobuf 파싱에 성공했고, 원본 202개 팩·77,283,328바이트를 모두 `data/original-master/`에 보존했습니다. 버전 `961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60`은 보유한 master-diff와 일치합니다. 이것은 익명 마스터 조회·보존 검증이며 유저 계정 수집 검증과 구분합니다.

`Master.Get`용 준비 과정은 원본 MasterTag의 버전·cryptoKey·fileName·fileSize를 유지하고 `downloadUrl`만 로컬 origin으로 바꿉니다. 암호화된 MasterDB 팩을 `--asset-root/master/`에서 그대로 제공할 수 있습니다.

원본 팩이 없는 경우 `tools/build_master_packs.py`가 정확한 descriptor의 `master.table`·`master.pk` annotation을 사용해 JSON 행을 protobuf로 검증하고 로컬 SQLCipher 4 팩으로 재구성합니다. 현재 master-diff의 202개 테이블·238,940개 행을 78,475,264바이트로 생성하고 전체 202개 테이블의 복호화·역직렬화 round trip을 확인했습니다. 생성 팩의 키·버전은 로컬 재구성용이며 원본 팩과 구분합니다. 클라이언트가 생성 팩을 소비하는지는 아직 기기에서 검증하지 않았습니다.

보존한 Octo cache의 SHA-256은 `a93dae963319b056ac7e01932cb379dc9675885d670ca2f3dde1efe53d3e12be`입니다. revision 1087을 해독한 manifest에는 AssetBundle 49,370개·resource 5,072개, 파일 크기 합계 39,322,868,160바이트가 기록돼 있습니다. 이 manifest는 파일 목록·해시·크기이며 실제 콘텐츠가 아닙니다. 현재 서버는 Octo API나 전체 CDN의 동작을 에뮬레이션하지 않습니다.

## 기기 연결에서 남은 확인

바이너리의 공식 API 문자열은 `https://api.game-idolypride.jp`, Octo 문자열은 `https://api.octo-cloud.com/`입니다. 두 플랫폼의 정적 채널·호스트 분기를 분석했고 Android 로컬 연결판에서는 실제 h2c 요청을 확인했습니다. 이것은 원본 APK의 공식 HTTPS 인증 통신 검증과 다릅니다. iOS 로컬 연결판의 게임 화면 진행은 아직 미검증입니다.

Android manifest는 기본 system trust와 debug user trust 구성을 갖지만 네이티브 HTTP handler가 적용하는 신뢰·pinning 동작은 원본 실행에서 확인하지 못했습니다. iOS도 원본의 네이티브 TLS 검증과 로컬 인증서 적용 경로가 미검증입니다. 서버의 TLS 옵션과 연결판의 주소 변경은 제공하지만, 로컬 h2c 연결 성공으로 원본 HTTPS의 프록시·CA 처리를 검증했다고 볼 수 없습니다.

이 문서의 전송 형식 검증은 codec 호환성, localhost gRPC 통합, SQLite 재로딩, fixture·파일 전송·마스터 round trip과 공식 익명 조회입니다. 별도 Android 로컬 연결판의 홈·튜토리얼 진행 결과는 [실제 게임 점검](actual-game-qa.md)을 따릅니다. 이를 원본 APK의 공식 인증 통신이나 계정 수집 성공으로 확대 해석하지 않습니다.

원본 APK 기준 [실행 `42858431492`](https://github.com/tagundo/IdolyPride_client/actions/runs/42858431492), 소스 `465c14b`에서는 원본 서명을 보존해 Google Play API 35 x86_64 이미지에 설치했습니다. GitHub 호스트의 KVM과 SwiftShader·Google ARM 번역을 사용했으며, 약 160초에 `libndk_translation.so`·Unity가 포함된 네이티브 `SIGSEGV`를 기록했습니다. 수집 화면은 Android 전체 화면 안내에 가려져 타이틀·홈 진입을 관측하지 못했습니다. 에뮬레이터 전체의 암호화 패킷 메타데이터는 RPC 내용이나 공식 로그인 검증 자료가 아닙니다.

후속 [실행 `42861039882`](https://github.com/tagundo/IdolyPride_client/actions/runs/42861039882), 소스 `09e8f9a`에서는 일반 Android 안내만 닫고 사라진 것을 검증했습니다. 게임 PID는 180초까지 살아 있었지만, 30–180초 화면은 회색 게임 화면 위의 Pixel Launcher ANR 대화상자였고 Unity 초기화·타이틀·홈 진입을 관측하지 못했습니다. 정상 실행이나 크래시 해결을 입증한 결과가 아닙니다. 공식 API 36 비교 [실행 `42862969552`](https://github.com/tagundo/IdolyPride_client/actions/runs/42862969552), 소스 `34ca8d5`도 System UI ANR과 회색 화면에 막혔습니다. 일반 연결판 [실행 `42863334749`](https://github.com/tagundo/IdolyPride_client/actions/runs/42863334749), 소스 `b18f711`은 현재 호스트 서버에 RPC를 보내기 전에 게임 프로세스가 SIGSEGV로 종료됐습니다. 원본의 공식 인증 RPC 캡처와 이 환경에서의 메뉴 성공은 아직 없습니다.
