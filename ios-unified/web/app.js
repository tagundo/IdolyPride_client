(function (root) {
  "use strict";

  const MAX_ID = 2147483647;
  const MAX_PENDING = 16;
  const MAX_DIAGNOSTIC_BYTES = 32768;
  const MAX_DIAGNOSTIC_WIRE_BYTES = 65000;
  const ACTIVE_JOBS = new Set(["preparing", "running", "export_ready", "cancelling"]);
  const LANGUAGES = {ko: "한국어", ja: "日本語", en: "English"};
  const INTERFACE_LANGUAGES = ["system", "ko", "ja", "en"];
  const SCALE_PRESETS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
  const BUFFER_PRESETS = [720, 1080, 1440, 1920, 2560, 3840, 4096];
  const UI_TRANSLATIONS = {
  "en": {
    "변경하면 자동으로 저장됩니다.": "Changes are saved automatically.",
    "변경 사항을 저장할 준비가 되었습니다.": "Changes are waiting to be saved.",
    "저장 중…": "Saving…",
    "자동 저장했습니다.": "Saved automatically.",
    "설정을 저장하지 못했습니다. 다시 시도를 눌러 주세요.": "Could not save settings. Choose Retry.",
    "입력값의 범위를 확인해 주세요. 유효한 값만 자동으로 저장합니다.": "Check the allowed ranges. Only valid values are saved automatically.",
    "게임을 시작하기 전에 설정 저장을 확인하고 있습니다.": "Checking saved settings before starting the game.",
    "설정을 저장하지 못해 게임을 시작하지 않았습니다. 입력값과 저장 상태를 확인해 주세요.": "The game was not started because settings could not be saved. Check the values and save status.",
    "ZIP 선택 대기": "Waiting for ZIP selection",
    "ZIP 복사 중": "Copying ZIP",
    "ZIP 검증 준비": "Preparing ZIP validation",
    "파일 앱에서 ZIP을 선택해 주세요.": "Choose a ZIP in the Files app.",
    "선택한 ZIP을 준비하고 있습니다. 파일 제공자의 다운로드가 필요할 수 있습니다.": "Preparing the selected ZIP. The file provider may need to download it first.",
    "ZIP을 앱 보관 폴더로 복사하고 있습니다.": "Copying the ZIP into app storage.",
    "복사를 마쳤습니다. ZIP 목록과 내용을 검증하고 있습니다.": "Copy complete. Validating the ZIP catalog and contents.",
    "ZIP 가져오기를 마치지 못했습니다.": "Could not finish importing the ZIP.",
    "리소스 작업 진행률": "Resource task progress",
    "IDOLY PRIDE 로컬 설정": "IDOLY PRIDE Local Settings",
    "서버 설정": "Server settings",
    "새로고침": "Refresh",
    "서버 상태": "Server status",
    "확인 중": "Checking",
    "기기에 저장된 설정을 불러옵니다.": "Loading settings saved on this device.",
    "변경한 감상 모드·언어·자동 받기는 다음 앱 실행부터 적용됩니다.": "Changes to viewing mode, game language and automatic downloads apply next time you open the app.",
    "감상 모드·언어": "Viewing mode and language",
    "저장 후 앱을 완전히 종료하고 다시 실행하면 적용됩니다. 일반 모드의 저장 자료는 따로 유지됩니다.": "Save, fully close the app, then reopen it to apply changes. Normal-mode save data is kept separately.",
    "감상 모드 · 전체 해금": "Viewing mode · Unlock all",
    "없는 리소스 자동 받기": "Automatically download missing resources",
    "게임 언어": "Game language",
    "한국어": "Korean",
    "다음 실행 설정 저장": "Save for next launch",
    "현재 적용 값 확인 중": "Checking active settings",
    "그래픽·촬영 화면": "Graphics and photography",
    "대기": "Waiting",
    "사용자 그래픽 설정": "Use custom graphics settings",
    "그래픽 품질": "Graphics quality",
    "원본": "Original",
    "최저": "Lowest",
    "낮음": "Low",
    "보통": "Medium",
    "높음": "High",
    "목표 프레임 수": "Target frame rate",
    "3D 렌더 배율": "3D render scale",
    "렌더 버퍼 최대 크기": "Maximum render buffer size",
    "가장자리 다듬기": "Anti-aliasing",
    "없음": "None",
    "캐릭터 그림자": "Character shadows",
    "촬영·360 화면 확장": "Expand photography and 360 view",
    "화면 확장은 그래픽 설정과 독립적으로 적용됩니다. 목표 프레임 수는 실제 성능을 보장하지 않습니다.": "View expansion is independent of custom graphics settings. The target frame rate does not guarantee actual performance.",
    "그래픽 설정 저장": "Save graphics settings",
    "게임 적용 상태 확인 중": "Checking settings applied in the game",
    "MV 재생": "MV playback",
    "화면 회전 후 재생 시작": "Wait for rotation before playback",
    "기본값은 켜짐입니다. 화면이 가로 방향으로 바뀔 때까지 기다립니다.": "Enabled by default. Waits until the screen turns to landscape.",
    "재생 설정 저장": "Save playback settings",
    "MV·의상 목록": "MV and outfit lists",
    "영상 MV 숨기기": "Hide video MVs",
    "MV 정렬": "MV order",
    "최신순": "Newest first",
    "오래된 순": "Oldest first",
    "이름순": "Name",
    "ID순": "ID",
    "의상 정렬": "Outfit order",
    "목록 설정 저장": "Save list settings",
    "목록 설정은 다음 앱 실행부터 적용됩니다.": "List settings apply next time you open the app.",
    "iOS 리소스 보관": "iOS resource storage",
    "받은 파일은 크기·MD5를 검증해 기기에 보관합니다. 중단 후 다시 받으면 검증된 파일을 재사용합니다.": "Downloaded files are checked by size and MD5 before storage. Resuming reuses verified files.",
    "동시 다운로드": "Parallel downloads",
    "1개": "1",
    "2개": "2",
    "4개 · 기본": "4 · Default",
    "8개": "8",
    "목록·용량 확인": "Check list and size",
    "전체 리소스 받기": "Download all resources",
    "서버 상태를 확인하고 있습니다.": "Checking server status.",
    "ZIP 가져오기": "Import ZIP",
    "ZIP 내보내기": "Export ZIP",
    "작업 취소": "Cancel task",
    "iOS 게임 리소스 ZIP을 선택하면 파일을 검증해 이 앱에 보관합니다. 완료 후 게임 시작을 누르세요. 직접 압축을 풀 필요는 없습니다. 내보내기에는 현재 보관된 파일만 포함됩니다.": "Choose an iOS game resource ZIP to verify its files and store them in this app. When import finishes, tap Start game. You do not need to extract the ZIP yourself. Exports include only files already stored.",
    "진단": "Diagnostics",
    "게임 진단 대기 중": "Waiting for game diagnostics",
    "상태·최근 기록 보기": "View status and recent logs",
    "기록 없음": "No logs",
    "설정은 이 기기에 저장됩니다.": "Settings are saved on this device.",
    "요청을 처리하지 못했습니다.": "Could not process the request.",
    "허용되지 않은 설정 요청입니다.": "This settings request is not allowed.",
    "설정 화면이 닫혀 있습니다.": "The settings screen is closed.",
    "앱 안에서 설정 화면을 열어 주세요.": "Open settings from inside the app.",
    "진행 중인 요청을 마친 후 다시 시도해 주세요.": "Wait for the current request to finish, then try again.",
    "응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요.": "The response is taking longer than expected. Refresh to check the status.",
    "앱에 요청을 전달하지 못했습니다.": "Could not send the request to the app.",
    "설정 화면이 숨겨졌습니다.": "The settings screen was hidden.",
    "설정 화면이 닫혔습니다.": "The settings screen was closed.",
    "설정을 먼저 불러와 주세요.": "Load settings first.",
    "설정 값의 범위를 확인해 주세요.": "Check the allowed setting ranges.",
    "준비": "Preparing",
    "진행 중": "In progress",
    "내보내기 준비": "Preparing export",
    "취소 중": "Cancelling",
    "완료": "Complete",
    "일부 완료": "Partially complete",
    "실패": "Failed",
    "취소됨": "Cancelled",
    "ZIP 준비 중": "Preparing ZIP",
    "받기": "Download",
    "가져오기": "Import",
    "내보내기": "Export",
    "작업": "Task",
    " · 검증 ": " · Verified ",
    "개 · ": " files · ",
    "\n수신 ": "\nReceived ",
    " · 재사용 ": " · Reused ",
    "개 · 가져옴 ": " files · Imported ",
    "개\n실패 ": " files\nFailed ",
    "개 · 미보관 ": " files · Not stored ",
    "개": " files",
    "연결": "Connecting",
    "검증": "Verifying",
    "저장": "Saving",
    "복사": "Copying",
    "동시 ": "Parallel ",
    "평균 ": "Average ",
    "초\n": " sec\n",
    "\n오류: ": "\nError: ",
    "ZIP 작업을 준비하고 있습니다.": "Preparing the ZIP task.",
    "포함 목록 ": "Catalog ",
    "목록·용량 확인을 누르면 전체 예상 용량을 표시합니다.": "Choose Check list and size to see the estimated total size.",
    "서버가 준비되면 리소스를 관리할 수 있습니다.": "You can manage resources when the server is ready.",
    "\n\n최근 기록\n": "\n\nRecent logs\n",
    "준비 중": "Starting",
    "실행 중": "Running",
    "시작 실패": "Startup failed",
    "종료됨": "Stopped",
    "로컬 서버가 게임 연결을 기다리고 있습니다.": "The local server is waiting for the game to connect.",
    "서버와 데이터를 준비하고 있습니다.": "Preparing the server and data.",
    "로컬 서버가 실행 중이 아닙니다.": "The local server is not running.",
    "현재: ": "Active: ",
    "감상 모드": "Viewing mode",
    "일반 모드": "Normal mode",
    " · 자동 받기 ": " · Automatic downloads ",
    "켜짐": "On",
    "꺼짐": "Off",
    "현재 적용 값은 서버 준비 후 표시됩니다.": "Active settings appear when the server is ready.",
    "적용 대기": "Waiting to apply",
    "게임 적용 확인": "Applied in game",
    "원본 설정": "Original settings",
    "미지원": "Unsupported",
    "장면 대기": "Waiting for scene",
    "초기화 실패": "Initialization failed",
    "게임에서 현재 그래픽 설정을 확인했습니다. 화면 확장은 촬영 장면에서 확인해 주세요.": "The game confirmed the current graphics settings. Check view expansion in a photography scene.",
    "설정이 저장되었습니다. 촬영·360 장면에서 적용 상태를 확인합니다.": "Settings saved. Application is checked in photography and 360 scenes.",
    "저장 확인과 게임 적용 확인은 다릅니다. 해당 장면에 들어가 적용 상태를 확인해 주세요.": "Saving settings and confirming them in the game are separate. Open the relevant scene to check application.",
    "변경한 목록 설정은 다음 앱 실행부터 적용됩니다.": "Changed list settings apply next time you open the app.",
    "서버 상태 형식을 확인하지 못했습니다.": "Could not read the server status format.",
    "저장했습니다. 다음 앱 실행부터 적용됩니다.": "Saved. Changes apply next time you open the app.",
    "설정을 저장했습니다. 게임 적용 상태를 확인해 주세요.": "Settings saved. Check whether they are applied in the game.",
    "파일 선택을 취소했습니다.": "File selection cancelled.",
    "리소스 목록을 확인했습니다.": "Resource list checked.",
    "리소스 받기를 시작했습니다.": "Resource download started.",
    "작업 취소를 요청했습니다.": "Cancellation requested.",
    "ZIP 가져오기를 시작했습니다. 진행 상태를 확인해 주세요.": "ZIP import started. Check its progress.",
    "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요.": "ZIP ready. Save it using the Files app.",
    "ZIP을 준비하고 있습니다. 완료되면 파일 앱에서 저장할 수 있습니다.": "Preparing ZIP. You can save it using the Files app when ready.",
    "ZIP 작업을 마치지 못했습니다. 확인된 파일과 기존 보관 자료는 유지됩니다.": "The ZIP task could not be completed. Verified files and existing stored data are kept.",
    "ZIP 가져오기를 마쳤습니다.": "ZIP import complete.",
    "원본 유지 (0)": "Keep original (0)",
    "서버 화면 언어": "Server interface language",
    "기기 언어": "Device language",
    "직접 입력": "Custom value",
    "배율": "Scale",
    "최대 크기": "Maximum size",
    "현재 그래픽 값": "Current graphics values",
    "서버 시작": "Start server",
    "다시 시도": "Retry",
    "게임 시작": "Start game",
    "게임으로 돌아가기": "Return to game",
    "서버 메뉴 닫기": "Close server menu",
    "언어 설정 저장": "Save language settings",
    "이 화면만 닫습니다. 서버는 계속 실행됩니다.": "Only this screen closes. The server keeps running.",
    "프리셋": "Preset",
    "서버 화면 언어는 게임 언어와 별개입니다.": "The server interface language is separate from the game language.",
    "낮음 (10)": "Low (10)",
    "중간 (20)": "Medium (20)",
    "높음 (30)": "High (30)",
    "최고 (40)": "Highest (40)",
    "촬영용 (100)": "Photography (100)",
    "1배 (기본)": "1× (Default)",
    "2배": "2×",
    "4096 px (기본)": "4096 px (Default)",
    "직접 입력 값": "Custom value",
    "서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "Save the settings below to keep the server interface language.",
    "서버 화면 언어를 저장하지 못했습니다. 다시 선택해 주세요.": "The server interface language could not be saved. Please select it again.",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요.": "This changes the interface language only. Choose the game language separately.",
    "0.25배": "0.25×",
    "0.5배": "0.5×",
    "0.75배": "0.75×",
    "1.25배": "1.25×",
    "1.5배": "1.5×",
    "감상 모드·게임 언어": "Viewing mode and game language",
    "끔 (0)": "Off (0)",
    "원본 유지 (-1)": "Keep original (-1)",
    "앱을 열면 이 서버 메뉴가 먼저 표시됩니다. 서버가 준비되면 오른쪽 위의 ‘게임 시작’을 누르세요. 게임 중에는 화면 오른쪽 위 모서리를 한 손가락으로 2초간 누르면 이 메뉴를 다시 엽니다. Mac에서는 앱 메뉴의 ‘로컬 서버 설정…’ 또는 ⌘⇧,도 사용할 수 있습니다.": "This server menu opens first. When the server is ready, choose Start Game at the top right. During gameplay, hold the upper-right corner with one finger for 2 seconds to reopen this menu. On Mac, you can also use Local Server Settings… in the app menu or ⌘⇧,.",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요. 서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "This changes the interface language only. Choose the game language separately. Save the settings below to keep the server interface language.",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요. 서버 화면 언어는 선택하면 바로 적용되고 저장됩니다.": "This changes the interface language only. Choose the game language separately. The server interface language is applied and saved immediately when selected.",
    "3D 렌더 배율 선택": "Choose 3D render scale",
    "3D 렌더 배율 직접 입력 값": "Custom 3D render scale",
    "렌더 버퍼 최대 크기 선택": "Choose maximum render buffer size",
    "렌더 버퍼 최대 크기 직접 입력 값": "Custom maximum render buffer size",
    "리소스 검증 진행률": "Resource verification progress",
    "게임 시작 전의 변경은 ‘게임 시작’ 때 적용됩니다. 게임 시작 후의 감상 모드·언어 변경은 다음 앱 실행부터 적용됩니다.": "Changes saved before starting the game apply when you choose Start Game. Viewing mode and game language changed during gameplay apply next time you open the app.",
    "설정은 자동으로 저장됩니다. 게임 시작 전에 선택한 언어로 시작합니다. 게임을 시작한 뒤 변경한 언어는 앱을 다시 실행하면 적용됩니다. 번역이 없는 문구·이미지는 원본으로 표시합니다.": "Settings are saved automatically. The selected language is used when you start the game. Language changes made after the game starts apply when you reopen the app. Missing translations and untranslated images keep the original content.",
    "설정 저장": "Save settings",
    "저장했습니다. 게임 시작 전이면 ‘게임 시작’ 때 적용됩니다. 이미 게임을 시작했다면 다음 앱 실행부터 적용됩니다.": "Saved. Before gameplay, changes apply when you choose Start Game. If the game has already started, they apply next time you open the app.",
    "진단 전체 복사": "Copy all diagnostics",
    "진단을 복사했습니다.": "Diagnostics copied.",
    "진단을 복사하지 못했습니다. 다시 시도해 주세요.": "Could not copy diagnostics. Please try again.",
    "… 표시 한도로 나머지 진단은 생략했습니다.": "… Remaining diagnostics omitted at the display limit."
  },
  "ja": {
    "변경하면 자동으로 저장됩니다.": "変更すると自動的に保存されます。",
    "변경 사항을 저장할 준비가 되었습니다.": "変更内容の保存を待っています。",
    "저장 중…": "保存中…",
    "자동 저장했습니다.": "自動保存しました。",
    "설정을 저장하지 못했습니다. 다시 시도를 눌러 주세요.": "設定を保存できませんでした。「再試行」を押してください。",
    "입력값의 범위를 확인해 주세요. 유효한 값만 자동으로 저장합니다.": "入力値の範囲を確認してください。有効な値だけを自動保存します。",
    "게임을 시작하기 전에 설정 저장을 확인하고 있습니다.": "ゲーム開始前に設定の保存を確認しています。",
    "설정을 저장하지 못해 게임을 시작하지 않았습니다. 입력값과 저장 상태를 확인해 주세요.": "設定を保存できなかったためゲームを開始しませんでした。入力値と保存状態を確認してください。",
    "ZIP 선택 대기": "ZIP選択待ち",
    "ZIP 복사 중": "ZIPをコピー中",
    "ZIP 검증 준비": "ZIP検証を準備中",
    "파일 앱에서 ZIP을 선택해 주세요.": "ファイルアプリでZIPを選択してください。",
    "선택한 ZIP을 준비하고 있습니다. 파일 제공자의 다운로드가 필요할 수 있습니다.": "選択したZIPを準備しています。ファイル提供元によるダウンロードが必要な場合があります。",
    "ZIP을 앱 보관 폴더로 복사하고 있습니다.": "ZIPをアプリの保管フォルダにコピーしています。",
    "복사를 마쳤습니다. ZIP 목록과 내용을 검증하고 있습니다.": "コピーが完了しました。ZIPの一覧と内容を検証しています。",
    "ZIP 가져오기를 마치지 못했습니다.": "ZIPの取り込みを完了できませんでした。",
    "리소스 작업 진행률": "リソース作業の進捗",
    "IDOLY PRIDE 로컬 설정": "IDOLY PRIDE ローカル設定",
    "서버 설정": "サーバー設定",
    "새로고침": "更新",
    "서버 상태": "サーバー状態",
    "확인 중": "確認中",
    "기기에 저장된 설정을 불러옵니다.": "この端末に保存された設定を読み込みます。",
    "변경한 감상 모드·언어·자동 받기는 다음 앱 실행부터 적용됩니다.": "鑑賞モード・ゲーム言語・自動ダウンロードの変更は、次回のアプリ起動時に適用されます。",
    "감상 모드·언어": "鑑賞モード・言語",
    "저장 후 앱을 완전히 종료하고 다시 실행하면 적용됩니다. 일반 모드의 저장 자료는 따로 유지됩니다.": "保存後、アプリを完全に終了して再起動すると適用されます。通常モードのセーブデータは別に保持されます。",
    "감상 모드 · 전체 해금": "鑑賞モード・全解放",
    "없는 리소스 자동 받기": "未保存リソースを自動ダウンロード",
    "게임 언어": "ゲーム言語",
    "한국어": "韓国語",
    "다음 실행 설정 저장": "次回起動時の設定を保存",
    "현재 적용 값 확인 중": "現在の適用値を確認中",
    "그래픽·촬영 화면": "グラフィック・撮影画面",
    "대기": "待機",
    "사용자 그래픽 설정": "カスタムグラフィック設定を使用",
    "그래픽 품질": "グラフィック品質",
    "원본": "元の設定",
    "최저": "最低",
    "낮음": "低",
    "보통": "中",
    "높음": "高",
    "목표 프레임 수": "目標フレームレート",
    "3D 렌더 배율": "3D描画倍率",
    "렌더 버퍼 최대 크기": "描画バッファの最大サイズ",
    "가장자리 다듬기": "アンチエイリアス",
    "없음": "なし",
    "캐릭터 그림자": "キャラクターの影",
    "촬영·360 화면 확장": "撮影・360画面の表示領域を拡張",
    "화면 확장은 그래픽 설정과 독립적으로 적용됩니다. 목표 프레임 수는 실제 성능을 보장하지 않습니다.": "表示領域の拡張はグラフィック設定とは独立して適用されます。目標フレームレートは実際の動作性能を保証するものではありません。",
    "그래픽 설정 저장": "グラフィック設定を保存",
    "게임 적용 상태 확인 중": "ゲームへの適用状態を確認中",
    "MV 재생": "MV再生",
    "화면 회전 후 재생 시작": "画面の回転後に再生開始",
    "기본값은 켜짐입니다. 화면이 가로 방향으로 바뀔 때까지 기다립니다.": "初期設定はオンです。画面が横向きになるまで待機します。",
    "재생 설정 저장": "再生設定を保存",
    "MV·의상 목록": "MV・衣装一覧",
    "영상 MV 숨기기": "動画MVを非表示",
    "MV 정렬": "MVの並び順",
    "최신순": "新しい順",
    "오래된 순": "古い順",
    "이름순": "名前順",
    "ID순": "ID順",
    "의상 정렬": "衣装の並び順",
    "목록 설정 저장": "一覧設定を保存",
    "목록 설정은 다음 앱 실행부터 적용됩니다.": "一覧設定は、次回のアプリ起動時に適用されます。",
    "iOS 리소스 보관": "iOSリソースの保存",
    "받은 파일은 크기·MD5를 검증해 기기에 보관합니다. 중단 후 다시 받으면 검증된 파일을 재사용합니다.": "ダウンロードしたファイルはサイズ・MD5を検証して端末に保存します。中断後に再開すると、検証済みのファイルを再利用します。",
    "동시 다운로드": "同時ダウンロード数",
    "1개": "1個",
    "2개": "2個",
    "4개 · 기본": "4個・初期値",
    "8개": "8個",
    "목록·용량 확인": "一覧・容量を確認",
    "전체 리소스 받기": "全リソースをダウンロード",
    "서버 상태를 확인하고 있습니다.": "サーバー状態を確認しています。",
    "ZIP 가져오기": "ZIPを読み込む",
    "ZIP 내보내기": "ZIPを書き出す",
    "작업 취소": "処理を中止",
    "iOS 게임 리소스 ZIP을 선택하면 파일을 검증해 이 앱에 보관합니다. 완료 후 게임 시작을 누르세요. 직접 압축을 풀 필요는 없습니다. 내보내기에는 현재 보관된 파일만 포함됩니다.": "iOSゲームリソースのZIPを選ぶと、ファイルを検証してこのアプリに保管します。完了したら「ゲーム開始」を押してください。自分でZIPを展開する必要はありません。書き出しには保管済みのファイルのみが含まれます。",
    "진단": "診断",
    "게임 진단 대기 중": "ゲームの診断待ち",
    "상태·최근 기록 보기": "状態・最近のログを表示",
    "기록 없음": "ログなし",
    "설정은 이 기기에 저장됩니다.": "設定はこの端末に保存されます。",
    "요청을 처리하지 못했습니다.": "リクエストを処理できませんでした。",
    "허용되지 않은 설정 요청입니다.": "許可されていない設定リクエストです。",
    "설정 화면이 닫혀 있습니다.": "設定画面が閉じています。",
    "앱 안에서 설정 화면을 열어 주세요.": "アプリ内から設定画面を開いてください。",
    "진행 중인 요청을 마친 후 다시 시도해 주세요.": "実行中のリクエストが完了してから、もう一度お試しください。",
    "응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요.": "応答に時間がかかっています。更新して状態をご確認ください。",
    "앱에 요청을 전달하지 못했습니다.": "アプリにリクエストを送信できませんでした。",
    "설정 화면이 숨겨졌습니다.": "設定画面が非表示になりました。",
    "설정 화면이 닫혔습니다.": "設定画面が閉じられました。",
    "설정을 먼저 불러와 주세요.": "先に設定を読み込んでください。",
    "설정 값의 범위를 확인해 주세요.": "設定値の範囲をご確認ください。",
    "준비": "準備",
    "진행 중": "処理中",
    "내보내기 준비": "書き出し準備",
    "취소 중": "中止中",
    "완료": "完了",
    "일부 완료": "一部完了",
    "실패": "失敗",
    "취소됨": "中止済み",
    "ZIP 준비 중": "ZIP準備中",
    "받기": "ダウンロード",
    "가져오기": "読み込み",
    "내보내기": "書き出し",
    "작업": "処理",
    " · 검증 ": "・検証済み ",
    "개 · ": "個・",
    "\n수신 ": "\n受信 ",
    " · 재사용 ": "・再利用 ",
    "개 · 가져옴 ": "個・読み込み ",
    "개\n실패 ": "個\n失敗 ",
    "개 · 미보관 ": "個・未保存 ",
    "개": "個",
    "연결": "接続",
    "검증": "検証",
    "저장": "保存",
    "복사": "コピー",
    "동시 ": "同時 ",
    "평균 ": "平均 ",
    "초\n": "秒\n",
    "\n오류: ": "\nエラー: ",
    "ZIP 작업을 준비하고 있습니다.": "ZIP処理を準備しています。",
    "포함 목록 ": "収録一覧 ",
    "목록·용량 확인을 누르면 전체 예상 용량을 표시합니다.": "「一覧・容量を確認」を押すと、合計の推定容量を表示します。",
    "서버가 준비되면 리소스를 관리할 수 있습니다.": "サーバーの準備が完了すると、リソースを管理できます。",
    "\n\n최근 기록\n": "\n\n最近のログ\n",
    "준비 중": "準備中",
    "실행 중": "実行中",
    "시작 실패": "起動失敗",
    "종료됨": "停止済み",
    "로컬 서버가 게임 연결을 기다리고 있습니다.": "ローカルサーバーはゲームの接続を待っています。",
    "서버와 데이터를 준비하고 있습니다.": "サーバーとデータを準備しています。",
    "로컬 서버가 실행 중이 아닙니다.": "ローカルサーバーは実行されていません。",
    "현재: ": "現在: ",
    "감상 모드": "鑑賞モード",
    "일반 모드": "通常モード",
    " · 자동 받기 ": "・自動ダウンロード ",
    "켜짐": "オン",
    "꺼짐": "オフ",
    "현재 적용 값은 서버 준비 후 표시됩니다.": "サーバーの準備が完了すると、現在の適用値を表示します。",
    "적용 대기": "適用待ち",
    "게임 적용 확인": "ゲームへの適用を確認",
    "원본 설정": "元の設定",
    "미지원": "未対応",
    "장면 대기": "シーン待ち",
    "초기화 실패": "初期化失敗",
    "게임에서 현재 그래픽 설정을 확인했습니다. 화면 확장은 촬영 장면에서 확인해 주세요.": "ゲームで現在のグラフィック設定を確認しました。表示領域の拡張は撮影シーンでご確認ください。",
    "설정이 저장되었습니다. 촬영·360 장면에서 적용 상태를 확인합니다.": "設定を保存しました。撮影・360シーンで適用状態を確認します。",
    "저장 확인과 게임 적용 확인은 다릅니다. 해당 장면에 들어가 적용 상태를 확인해 주세요.": "設定の保存とゲームへの適用確認は別です。対象のシーンで適用状態をご確認ください。",
    "변경한 목록 설정은 다음 앱 실행부터 적용됩니다.": "変更した一覧設定は、次回のアプリ起動時に適用されます。",
    "서버 상태 형식을 확인하지 못했습니다.": "サーバー状態の形式を確認できませんでした。",
    "저장했습니다. 다음 앱 실행부터 적용됩니다.": "保存しました。次回のアプリ起動時に適用されます。",
    "설정을 저장했습니다. 게임 적용 상태를 확인해 주세요.": "設定を保存しました。ゲームへの適用状態をご確認ください。",
    "파일 선택을 취소했습니다.": "ファイルの選択を中止しました。",
    "리소스 목록을 확인했습니다.": "リソース一覧を確認しました。",
    "리소스 받기를 시작했습니다.": "リソースのダウンロードを開始しました。",
    "작업 취소를 요청했습니다.": "処理の中止を要求しました。",
    "ZIP 가져오기를 시작했습니다. 진행 상태를 확인해 주세요.": "ZIPの読み込みを開始しました。進行状況をご確認ください。",
    "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요.": "ZIPの準備ができました。「ファイル」アプリで保存してください。",
    "ZIP을 준비하고 있습니다. 완료되면 파일 앱에서 저장할 수 있습니다.": "ZIPを準備しています。完了後、「ファイル」アプリで保存できます。",
    "ZIP 작업을 마치지 못했습니다. 확인된 파일과 기존 보관 자료는 유지됩니다.": "ZIP処理を完了できませんでした。確認済みのファイルと既存の保存データは保持されます。",
    "ZIP 가져오기를 마쳤습니다.": "ZIPの読み込みが完了しました。",
    "원본 유지 (0)": "元の設定を維持 (0)",
    "서버 화면 언어": "サーバー画面の言語",
    "기기 언어": "端末の言語",
    "직접 입력": "直接入力",
    "배율": "倍率",
    "최대 크기": "最大サイズ",
    "현재 그래픽 값": "現在のグラフィック値",
    "서버 시작": "サーバー開始",
    "다시 시도": "再試行",
    "게임 시작": "ゲーム開始",
    "게임으로 돌아가기": "ゲームに戻る",
    "서버 메뉴 닫기": "サーバーメニューを閉じる",
    "언어 설정 저장": "言語設定を保存",
    "이 화면만 닫습니다. 서버는 계속 실행됩니다.": "この画面のみを閉じます。サーバーは動作を続けます。",
    "프리셋": "プリセット",
    "서버 화면 언어는 게임 언어와 별개입니다.": "サーバー画面の言語とゲームの言語は別の設定です。",
    "낮음 (10)": "低 (10)",
    "중간 (20)": "中 (20)",
    "높음 (30)": "高 (30)",
    "최고 (40)": "最高 (40)",
    "촬영용 (100)": "撮影用 (100)",
    "1배 (기본)": "1倍（初期値）",
    "2배": "2倍",
    "4096 px (기본)": "4096 px（初期値）",
    "직접 입력 값": "直接入力値",
    "서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "下の設定を保存すると、サーバー画面の言語も保存されます。",
    "서버 화면 언어를 저장하지 못했습니다. 다시 선택해 주세요.": "サーバー画面の言語を保存できませんでした。もう一度選択してください。",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요.": "画面の言語のみを変更します。ゲームの言語は別に選択してください。",
    "0.25배": "0.25倍",
    "0.5배": "0.5倍",
    "0.75배": "0.75倍",
    "1.25배": "1.25倍",
    "1.5배": "1.5倍",
    "감상 모드·게임 언어": "鑑賞モード・ゲーム言語",
    "끔 (0)": "オフ (0)",
    "원본 유지 (-1)": "元の設定を維持 (-1)",
    "앱을 열면 이 서버 메뉴가 먼저 표시됩니다. 서버가 준비되면 오른쪽 위의 ‘게임 시작’을 누르세요. 게임 중에는 화면 오른쪽 위 모서리를 한 손가락으로 2초간 누르면 이 메뉴를 다시 엽니다. Mac에서는 앱 메뉴의 ‘로컬 서버 설정…’ 또는 ⌘⇧,도 사용할 수 있습니다.": "アプリを開くと、最初にこのサーバーメニューが表示されます。サーバーの準備が完了したら、右上の「ゲーム開始」を押してください。ゲーム中は画面右上を指1本で2秒間長押しすると、このメニューを開けます。Macではアプリメニューの「ローカルサーバー設定…」または ⌘⇧, も使用できます。",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요. 서버 화면 언어는 아래 설정 저장으로 보관됩니다.": "画面の言語のみを変更します。ゲームの言語は別に選択してください。 下の設定を保存すると、サーバー画面の言語も保存されます。",
    "화면 언어만 바뀝니다. 게임 언어는 별도로 선택해 주세요. 서버 화면 언어는 선택하면 바로 적용되고 저장됩니다.": "画面の言語のみを変更します。ゲームの言語は別に選択してください。サーバー画面の言語は選択するとすぐに適用・保存されます。",
    "3D 렌더 배율 선택": "3D描画倍率を選択",
    "3D 렌더 배율 직접 입력 값": "3D描画倍率の直接入力値",
    "렌더 버퍼 최대 크기 선택": "描画バッファの最大サイズを選択",
    "렌더 버퍼 최대 크기 직접 입력 값": "描画バッファの最大サイズの直接入力値",
    "리소스 검증 진행률": "リソース検証の進捗",
    "게임 시작 전의 변경은 ‘게임 시작’ 때 적용됩니다. 게임 시작 후의 감상 모드·언어 변경은 다음 앱 실행부터 적용됩니다.": "ゲーム開始前の変更は「ゲーム開始」時に適用されます。ゲーム開始後の鑑賞モード・言語の変更は次回のアプリ起動時に適用されます。",
    "설정은 자동으로 저장됩니다. 게임 시작 전에 선택한 언어로 시작합니다. 게임을 시작한 뒤 변경한 언어는 앱을 다시 실행하면 적용됩니다. 번역이 없는 문구·이미지는 원본으로 표시합니다.": "設定は自動保存されます。ゲーム開始前に選択した言語で開始します。ゲーム開始後に変更した言語は、アプリの再起動後に適用されます。翻訳のない文章・画像は原文のまま表示されます。",
    "설정 저장": "設定を保存",
    "저장했습니다. 게임 시작 전이면 ‘게임 시작’ 때 적용됩니다. 이미 게임을 시작했다면 다음 앱 실행부터 적용됩니다.": "保存しました。ゲーム開始前なら「ゲーム開始」時に適用されます。すでにゲームを開始している場合は、次回のアプリ起動時に適用されます。",
    "진단 전체 복사": "診断をすべてコピー",
    "진단을 복사했습니다.": "診断をコピーしました。",
    "진단을 복사하지 못했습니다. 다시 시도해 주세요.": "診断をコピーできませんでした。もう一度お試しください。",
    "… 표시 한도로 나머지 진단은 생략했습니다.": "… 表示上限に達したため、残りの診断を省略しました。"
  }
};

  Object.assign(UI_TRANSLATIONS.ja, {"유저 관리": "ユーザー管理", "계정 목록 불러오기": "アカウント一覧を読み込む", "계정 ZIP에는 계정 진행·보유 항목·게임 설정을 보관합니다. 게임 리소스 ZIP과는 별개입니다.": "アカウントZIPには進行状況・所持品・ゲーム設定が含まれます。ゲームリソースZIPとは別です。", "계정 선택은 다음 서버 시작에 적용됩니다. 게임을 시작한 뒤 활성 계정을 복원하려면 앱을 완전히 종료하고 다시 열어 주세요.": "アカウント選択は次のサーバー起動時に反映されます。ゲーム開始後に使用中のアカウントを復元するには、アプリを完全に終了して開き直してください。", "계정 목록을 불러오면 관리할 수 있습니다.": "一覧を読み込むとアカウントを管理できます。", "관리할 계정": "管理するアカウント", "계정 없음": "アカウントなし", "다음 시작 계정으로 선택": "次回起動のアカウントに選択", "계정 ZIP 내보내기": "アカウントZIPを書き出す", "아래 이름으로 복제": "下の名前で複製", "이전 계정 목록": "前のアカウント一覧", "다음 계정 목록": "次のアカウント一覧", "계정 생성·복제": "アカウント作成・複製", "계정 종류": "アカウントの種類", "새 계정 이름": "新しいアカウント名", "새 계정 매니저 이름": "新規アカウントのマネージャー名", "새 계정 만들기": "アカウントを作成", "계정 백업 가져오기": "アカウントバックアップを取り込む", "계정 ZIP 선택·검사": "アカウントZIPを選択・検証", "선택한 계정에 덮어쓰기 · 기존 상태의 복구점 자동 생성": "選択中のアカウントを上書き・変更前の復元ポイントを自動作成", "덮어쓰지 않으면 ‘새 계정 이름’으로 가져옵니다. 선택한 ZIP은 검사만으로 계정을 바꾸지 않습니다.": "上書きしない場合は「新しいアカウント名」で取り込みます。ZIPの検証だけではアカウントは変更されません。", "검사한 계정 가져오기": "検証済みアカウントを取り込む", "이전 상태로 복원": "以前の状態に復元", "자동 복구점": "自動復元ポイント", "복구점 없음": "復元ポイントなし", "복원할 계정과 복구점의 계정이 같아야 합니다. 복원 직전 상태도 새 복구점으로 남깁니다.": "対象アカウントと復元ポイントのアカウントは一致する必要があります。復元直前の状態も新しい復元ポイントとして保存します。", "선택한 복구점으로 복원": "選択した復元ポイントへ復元", "이전 복구점 목록": "前の復元ポイント", "다음 복구점 목록": "次の復元ポイント", "계정 작업 진행률": "アカウント処理の進行状況", "현재 계정: ": "現在のアカウント: ", "다음 시작 · 일반: ": "次回起動・通常: ", " / 감상: ": " / 鑑賞: ", "서버 준비 검사": "サーバー準備の検査", "서버 준비 검사를 기다리고 있습니다.": "サーバー準備の検査を待っています。", "마지막 오류: ": "最後のエラー: ", "오류 기록을 저장할 수 없습니다.": "エラー記録を保存できません。", "저장된 최근 오류가 없습니다.": "保存された最近のエラーはありません。", "이전 실행의 검사 기록입니다.": "前回起動時の検査記録です。", "프로토콜": "プロトコル", "게임 목록": "ゲームカタログ", "마스터 파일": "マスターファイル", "저장 공간": "保存領域", "파일 서버": "ファイルサーバー", "게임 서버": "ゲームサーバー", "게임 리소스": "ゲームリソース", "계정": "アカウント", "검사": "検査", "준비 완료": "準備完了", "확인 필요": "確認が必要", "검사 전": "未検査", "중지됨": "停止", "계정 작업을 처리하고 있습니다.": "アカウント処理中です。", "ZIP과 같은 종류의 계정을 선택해 주세요.": "ZIPと同じ種類のアカウントを選択してください。", "계정 ZIP 검사 결과를 확인하지 못했습니다.": "アカウントZIPの検証結果を確認できませんでした。", "계정 ZIP을 검사했습니다. 가져올 이름과 대상을 확인해 주세요.": "アカウントZIPを検証しました。取り込み先と名前を確認してください。", "계정 목록을 불러왔습니다.": "アカウント一覧を読み込みました。", "다음 서버 시작에 선택한 계정을 적용합니다.": "次のサーバー起動時に選択したアカウントを使用します。", "계정 ZIP을 준비했습니다. 파일 앱에서 저장해 주세요.": "アカウントZIPを準備しました。ファイルアプリで保存してください。", "계정 작업을 마쳤습니다.": "アカウント処理が完了しました。", "게임을 완전히 종료하고 다시 연 뒤 게임 시작 전에 계정을 복원해 주세요.": "アプリを完全に終了して開き直し、ゲーム開始前にアカウントを復元してください。", "계정 작업을 마치지 못했습니다. 목록을 새로 불러와 확인해 주세요.": "アカウント処理を完了できませんでした。一覧を読み直して確認してください。", "이전 오류 기록 지우기": "保存されたエラー記録を消去"});
  Object.assign(UI_TRANSLATIONS.en, {"유저 관리": "User management", "계정 목록 불러오기": "Load accounts", "계정 ZIP에는 계정 진행·보유 항목·게임 설정을 보관합니다. 게임 리소스 ZIP과는 별개입니다.": "Account ZIPs contain progress, inventory and game settings. They are separate from game resource ZIPs.", "계정 선택은 다음 서버 시작에 적용됩니다. 게임을 시작한 뒤 활성 계정을 복원하려면 앱을 완전히 종료하고 다시 열어 주세요.": "Account selection applies at the next server start. To restore the active account after starting the game, fully close and reopen the app.", "계정 목록을 불러오면 관리할 수 있습니다.": "Load the list to manage accounts.", "관리할 계정": "Account to manage", "계정 없음": "No accounts", "다음 시작 계정으로 선택": "Use at next start", "계정 ZIP 내보내기": "Export account ZIP", "아래 이름으로 복제": "Clone with the name below", "이전 계정 목록": "Previous accounts", "다음 계정 목록": "Next accounts", "계정 생성·복제": "Create or clone an account", "계정 종류": "Account type", "새 계정 이름": "New account name", "새 계정 매니저 이름": "New account manager name", "새 계정 만들기": "Create account", "계정 백업 가져오기": "Import account backup", "계정 ZIP 선택·검사": "Choose and check account ZIP", "선택한 계정에 덮어쓰기 · 기존 상태의 복구점 자동 생성": "Replace selected account · automatically save a restore point", "덮어쓰지 않으면 ‘새 계정 이름’으로 가져옵니다. 선택한 ZIP은 검사만으로 계정을 바꾸지 않습니다.": "Without replacement, import uses the New account name. Checking a ZIP alone does not change an account.", "검사한 계정 가져오기": "Import checked account", "이전 상태로 복원": "Restore previous state", "자동 복구점": "Automatic restore point", "복구점 없음": "No restore points", "복원할 계정과 복구점의 계정이 같아야 합니다. 복원 직전 상태도 새 복구점으로 남깁니다.": "The account and restore point must match. The state before restoration is also saved as a new restore point.", "선택한 복구점으로 복원": "Restore selected point", "이전 복구점 목록": "Previous restore points", "다음 복구점 목록": "Next restore points", "계정 작업 진행률": "Account task progress", "현재 계정: ": "Active account: ", "다음 시작 · 일반: ": "Next start · Normal: ", " / 감상: ": " / Viewing: ", "서버 준비 검사": "Server readiness checks", "서버 준비 검사를 기다리고 있습니다.": "Waiting for server readiness checks.", "마지막 오류: ": "Last failure: ", "오류 기록을 저장할 수 없습니다.": "Error history cannot be saved.", "저장된 최근 오류가 없습니다.": "No recent failures are saved.", "이전 실행의 검사 기록입니다.": "These checks are from the previous run.", "프로토콜": "Protocol", "게임 목록": "Game catalog", "마스터 파일": "Master files", "저장 공간": "Storage", "파일 서버": "File server", "게임 서버": "Game server", "게임 리소스": "Game resources", "계정": "Account", "검사": "Check", "준비 완료": "Ready", "확인 필요": "Needs attention", "검사 전": "Not checked", "중지됨": "Stopped", "계정 작업을 처리하고 있습니다.": "Processing account task.", "ZIP과 같은 종류의 계정을 선택해 주세요.": "Choose an account with the same type as the ZIP.", "계정 ZIP 검사 결과를 확인하지 못했습니다.": "Could not read the account ZIP check result.", "계정 ZIP을 검사했습니다. 가져올 이름과 대상을 확인해 주세요.": "Account ZIP checked. Verify the target and name before importing.", "계정 목록을 불러왔습니다.": "Accounts loaded.", "다음 서버 시작에 선택한 계정을 적용합니다.": "The selected account will apply at the next server start.", "계정 ZIP을 준비했습니다. 파일 앱에서 저장해 주세요.": "Account ZIP prepared. Save it in the Files app.", "계정 작업을 마쳤습니다.": "Account task completed.", "게임을 완전히 종료하고 다시 연 뒤 게임 시작 전에 계정을 복원해 주세요.": "Fully close and reopen the app, then restore the account before starting the game.", "계정 작업을 마치지 못했습니다. 목록을 새로 불러와 확인해 주세요.": "Could not complete the account task. Reload the list and check again.", "이전 오류 기록 지우기": "Clear saved error history"});


  Object.assign(UI_TRANSLATIONS.ja, {"새 저장 슬롯 이름": "新しい保存スロット名", "매니저 이름 · 새 계정 생성 시": "マネージャー名・新規作成時のみ", "덮어쓰지 않으면 ‘새 저장 슬롯 이름’으로 가져옵니다. 선택한 ZIP은 검사만으로 계정을 바꾸지 않습니다.": "上書きしない場合は「新しい保存スロット名」で取り込みます。ZIPの検証だけではアカウントは変更されません。", "로컬 계정 이름은 저장 슬롯 이름입니다. 복제·가져오기는 게임 내 ID와 매니저 이름을 그대로 유지합니다.": "ローカルアカウント名は保存スロット名です。複製・取り込みではゲーム内IDとマネージャー名は変わりません。", "원본 저장 슬롯: ": "元の保存スロット: ", "계정 자료: ": "アカウントデータ: ", "게임 내 매니저: ": "ゲーム内マネージャー: ", "게임 리소스 파일은 포함하지 않습니다.": "ゲームリソースファイルは含まれません。", "카드": "カード", "아이템": "アイテム", "포토": "フォト"});
  Object.assign(UI_TRANSLATIONS.en, {"새 저장 슬롯 이름": "New save slot name", "매니저 이름 · 새 계정 생성 시": "Manager name · new accounts only", "덮어쓰지 않으면 ‘새 저장 슬롯 이름’으로 가져옵니다. 선택한 ZIP은 검사만으로 계정을 바꾸지 않습니다.": "Without replacement, import uses the New save slot name. Checking a ZIP alone does not change an account.", "로컬 계정 이름은 저장 슬롯 이름입니다. 복제·가져오기는 게임 내 ID와 매니저 이름을 그대로 유지합니다.": "Local account names identify save slots. Cloning or importing preserves the in-game ID and manager name.", "원본 저장 슬롯: ": "Original save slot: ", "계정 자료: ": "Account data: ", "게임 내 매니저: ": "In-game manager: ", "게임 리소스 파일은 포함하지 않습니다.": "Game resource files are not included.", "카드": "Cards", "아이템": "Items", "포토": "Photos"});

  Object.assign(UI_TRANSLATIONS.ja, {"진행 중인 파일 작업을 마친 후 다시 시도해 주세요.":"進行中のファイル操作が完了してから再試行してください。"});
  Object.assign(UI_TRANSLATIONS.en, {"진행 중인 파일 작업을 마친 후 다시 시도해 주세요.":"Finish the current file operation before trying again."});

  Object.assign(UI_TRANSLATIONS.ja, {"아이템 종류":"アイテムの種類"});
  Object.assign(UI_TRANSLATIONS.en, {"아이템 종류":"Item types"});

  Object.assign(UI_TRANSLATIONS.ja, {"게임 통신 자료를 확인했습니다.": "ゲームの通信データを確認しました。", "게임 목록 자료를 확인했습니다.": "ゲームカタログを確認しました。", "마스터 목록과 파일 크기를 확인했습니다.": "マスター一覧とファイルサイズを確認しました。", "이 기기에 저장할 수 있습니다.": "この端末に保存できます。", "저장 공간이 부족합니다. 파일을 정리해 주세요.": "空き容量が不足しています。ファイルを整理してください。", "파일 서버 응답을 확인했습니다.": "ファイルサーバーの応答を確認しました。", "게임 연결을 받을 준비가 되었습니다.": "ゲームからの接続を受け付けられます。", "게임 연결을 중지했습니다.": "ゲーム接続を停止しました。", "게임 리소스 목록이 없습니다.": "ゲームリソースの一覧がありません。", "필요한 파일을 인터넷으로 받을 수 있습니다.": "必要なファイルをインターネットから取得できます。", "오프라인용 파일이 모두 준비됐는지 확인해 주세요.": "オフライン用ファイルが揃っているか確認してください。", "선택한 계정을 확인했습니다.": "選択したアカウントを確認しました。", "계정을 다시 선택해 주세요.": "アカウントを選び直してください。", "저장소 접근 권한을 확인해 주세요.": "保存先へのアクセス権限を確認してください。", "같은 포트의 다른 서버를 종료해 주세요.": "同じポートを使う別のサーバーを終了してください。", "필요한 서버 자료가 없습니다.": "必要なサーバーデータがありません。", "서버 자료·설정의 형식을 확인해 주세요.": "サーバーデータと設定の形式を確認してください。", "저장 공간을 확보해 주세요.": "空き容量を確保してください。", "진단 기록을 확인해 주세요.": "診断記録を確認してください。", "게임 요청이 실패했습니다.": "ゲームリクエストが失敗しました。", "파일 요청이 실패했습니다.": "ファイルリクエストが失敗しました。", "서버를 시작하지 못했습니다.": "サーバーを起動できませんでした。", "서버 작업을 마치지 못했습니다.": "サーバー処理を完了できませんでした。"});
  Object.assign(UI_TRANSLATIONS.en, {"게임 통신 자료를 확인했습니다.": "Game protocol data checked.", "게임 목록 자료를 확인했습니다.": "Game catalog checked.", "마스터 목록과 파일 크기를 확인했습니다.": "Master catalog and file sizes checked.", "이 기기에 저장할 수 있습니다.": "Storage is writable.", "저장 공간이 부족합니다. 파일을 정리해 주세요.": "Storage is low. Free some space.", "파일 서버 응답을 확인했습니다.": "File server response checked.", "게임 연결을 받을 준비가 되었습니다.": "Ready to receive game connections.", "게임 연결을 중지했습니다.": "Game listener stopped.", "게임 리소스 목록이 없습니다.": "Game resource catalog is missing.", "필요한 파일을 인터넷으로 받을 수 있습니다.": "Missing files can be downloaded online.", "오프라인용 파일이 모두 준비됐는지 확인해 주세요.": "Check that all files needed offline are stored.", "선택한 계정을 확인했습니다.": "Selected account checked.", "계정을 다시 선택해 주세요.": "Select an account again.", "저장소 접근 권한을 확인해 주세요.": "Check storage access permissions.", "같은 포트의 다른 서버를 종료해 주세요.": "Close another server using the same port.", "필요한 서버 자료가 없습니다.": "Required server data is missing.", "서버 자료·설정의 형식을 확인해 주세요.": "Check the format of server data and settings.", "저장 공간을 확보해 주세요.": "Free storage space.", "진단 기록을 확인해 주세요.": "Check the diagnostic record.", "게임 요청이 실패했습니다.": "A game request failed.", "파일 요청이 실패했습니다.": "A file request failed.", "서버를 시작하지 못했습니다.": "The server could not start.", "서버 작업을 마치지 못했습니다.": "A server operation could not finish."});

  Object.assign(UI_TRANSLATIONS.ja, {"해당 모드의 다음 계정으로 선택": "このモードの次回アカウントに選択", "계정 선택은 해당 모드의 저장 슬롯을 바꿉니다. 사용할 일반·감상 모드도 위 설정에서 확인해 주세요.": "アカウント選択は指定モードの保存スロットを変更します。通常・鑑賞モードの設定も上で確認してください。", "게임 ID: ": "ゲームID: "});
  Object.assign(UI_TRANSLATIONS.en, {"해당 모드의 다음 계정으로 선택": "Use at next start in this mode", "계정 선택은 해당 모드의 저장 슬롯을 바꿉니다. 사용할 일반·감상 모드도 위 설정에서 확인해 주세요.": "Account selection changes the save slot for that mode. Check the normal/viewing mode setting above too.", "게임 ID: ": "Game ID: "});

  Object.assign(UI_TRANSLATIONS.ja, {"일본 공식 계정 가져오기": "日本公式アカウントの取り込み", "일본 공식 계정 가져오기 · 현재 작동하지 않음": "日本公式アカウントの取り込み · 現在利用不可", "현재 작동하지 않음": "現在利用不可", "일본 공식 계정 가져오기는 현재 작동하지 않습니다. 기존 일본 공식 계정의 인계 정보를 확인한 뒤, 별도 버튼으로 공식 인계 로그인과 데이터 내려받기를 진행합니다.": "日本公式アカウントの取り込みは現在利用できません。 既存の日本公式アカウントの引き継ぎ情報を確認後、別のボタンで公式の引き継ぎログインとデータ取得を行います。", "인계 ID·비밀번호는 앱의 보안 입력창에서만 입력합니다. 입력한 정보는 제출하거나 취소하면 지웁니다.": "引き継ぎIDとパスワードはアプリの安全な入力画面にのみ入力します。送信またはキャンセル時に入力内容を消去します。", "인계 정보 확인": "引き継ぎ情報を確認", "공식 인계 로그인·내려받기": "公式の引き継ぎログイン・データ取得", "공식 계정 작업 취소": "公式アカウント処理を中止", "공식 계정 작업 진행률": "公式アカウント処理の進行状況", "인계 정보를 확인해 주세요.": "引き継ぎ情報を確認してください。", "기존 일반 계정 덮어쓰기 · 위 ‘관리할 계정’에서 대상을 선택하세요": "既存の通常アカウントを上書き・上の「管理するアカウント」で対象を選択してください", "받은 데이터를 일반 계정으로 저장": "取得したデータを通常アカウントに保存", "기본값은 새 일반 계정으로 저장입니다. 덮어쓰기 전 상태는 복구점으로 보관합니다. 저장 후 위 유저 관리에서 일반 계정을 선택하고 감상 모드를 꺼 주세요.": "初期設定は新しい通常アカウントへの保存です。上書き前の状態は復元ポイントに保存します。保存後、上のユーザー管理で通常アカウントを選択し、鑑賞モードをオフにしてください。", "인계 정보 확인 중": "引き継ぎ情報を確認中", "공식 계정 확인 완료": "公式アカウントを確認済み", "공식 계정 데이터 받는 중": "公式アカウントのデータを取得中", "로컬 저장 준비 완료": "ローカル保存の準備完了", "일반 계정 저장 완료": "通常アカウントへの保存完了", "작업을 취소했습니다.": "処理をキャンセルしました。", "공식 계정 작업을 마치지 못했습니다. 상태를 확인해 주세요.": "公式アカウント処理を完了できませんでした。状態を確認してください。", "공식 계정 작업에 실패했습니다. 입력 정보와 연결 상태를 확인해 주세요.": "公式アカウント処理に失敗しました。入力情報と接続状態を確認してください。", "확인한 계정으로 공식 인계 로그인·내려받기를 진행할 수 있습니다.": "確認済みのアカウントで公式の引き継ぎログインとデータ取得を行えます。", "내려받기와 검증을 마쳤습니다. 저장할 로컬 계정을 확인해 주세요.": "取得と検証が完了しました。保存先のローカルアカウントを確認してください。", "일반 계정으로 저장했습니다. 유저 관리에서 계정과 사용할 모드를 선택해 주세요.": "通常アカウントに保存しました。ユーザー管理でアカウントと使用するモードを選択してください。", "덮어쓸 일반 계정을 위에서 선택해 주세요.": "上で上書き対象の通常アカウントを選択してください。", "덮어쓸 저장 슬롯: ": "上書き先の保存スロット: ", "새 일반 계정으로 저장합니다.": "新しい通常アカウントに保存します。", "매니저 레벨: ": "マネージャーレベル: ", "공식 계정 작업을 처리하고 있습니다.": "公式アカウント処理中です。", "공식 로그인 준비": "公式ログインを準備中", "공식 계정 확인": "公式アカウントを確認中", "공식 인계 로그인": "公式の引き継ぎログイン中", "로그인 인증": "ログインを認証中", "계정 데이터 검증": "アカウントデータを検証中", "로컬 저장 준비": "ローカル保存を準備中"});
  Object.assign(UI_TRANSLATIONS.en, {"일본 공식 계정 가져오기": "Import Japanese official account", "일본 공식 계정 가져오기 · 현재 작동하지 않음": "Import Japanese official account · Currently unavailable", "현재 작동하지 않음": "Currently unavailable", "일본 공식 계정 가져오기는 현재 작동하지 않습니다. 기존 일본 공식 계정의 인계 정보를 확인한 뒤, 별도 버튼으로 공식 인계 로그인과 데이터 내려받기를 진행합니다.": "Japanese official account import is currently unavailable. Check the transfer details for an existing Japanese official account, then use the separate button to perform the official transfer login and download data.", "인계 ID·비밀번호는 앱의 보안 입력창에서만 입력합니다. 입력한 정보는 제출하거나 취소하면 지웁니다.": "Enter transfer credentials only in the app’s secure prompt. The input is cleared when submitted or cancelled.", "인계 정보 확인": "Check transfer details", "공식 인계 로그인·내려받기": "Official transfer login and download", "공식 계정 작업 취소": "Cancel official account task", "공식 계정 작업 진행률": "Official account task progress", "인계 정보를 확인해 주세요.": "Check the transfer details first.", "기존 일반 계정 덮어쓰기 · 위 ‘관리할 계정’에서 대상을 선택하세요": "Replace an existing normal account · choose the target under Account to manage above", "받은 데이터를 일반 계정으로 저장": "Save downloaded data as a normal account", "기본값은 새 일반 계정으로 저장입니다. 덮어쓰기 전 상태는 복구점으로 보관합니다. 저장 후 위 유저 관리에서 일반 계정을 선택하고 감상 모드를 꺼 주세요.": "The default saves a new normal account. Replacing an account saves a restore point first. After saving, select the normal account in User management above and turn off Viewing mode.", "인계 정보 확인 중": "Checking transfer details", "공식 계정 확인 완료": "Official account verified", "공식 계정 데이터 받는 중": "Downloading official account data", "로컬 저장 준비 완료": "Ready to save locally", "일반 계정 저장 완료": "Normal account saved", "작업을 취소했습니다.": "Task cancelled.", "공식 계정 작업을 마치지 못했습니다. 상태를 확인해 주세요.": "Could not complete the official account task. Check its status.", "공식 계정 작업에 실패했습니다. 입력 정보와 연결 상태를 확인해 주세요.": "The official account task failed. Check the transfer details and connection.", "확인한 계정으로 공식 인계 로그인·내려받기를 진행할 수 있습니다.": "You can now perform the official transfer login and download for the verified account.", "내려받기와 검증을 마쳤습니다. 저장할 로컬 계정을 확인해 주세요.": "Download and validation completed. Check which local account to save.", "일반 계정으로 저장했습니다. 유저 관리에서 계정과 사용할 모드를 선택해 주세요.": "Saved as a normal account. Choose the account and mode in User management.", "덮어쓸 일반 계정을 위에서 선택해 주세요.": "Choose the normal account to replace above.", "덮어쓸 저장 슬롯: ": "Save slot to replace: ", "새 일반 계정으로 저장합니다.": "Save as a new normal account.", "매니저 레벨: ": "Manager level: ", "공식 계정 작업을 처리하고 있습니다.": "Processing official account task.", "공식 로그인 준비": "Preparing official login", "공식 계정 확인": "Verifying official account", "공식 인계 로그인": "Official transfer login", "로그인 인증": "Authenticating login", "계정 데이터 검증": "Validating account data", "로컬 저장 준비": "Preparing local storage"});

  Object.assign(UI_TRANSLATIONS.ja, {"인계 ID와 비밀번호 형식을 확인해 주세요.": "引き継ぎIDとパスワードの形式を確認してください。", "공식 서버에서 인계 정보를 확인하지 못했습니다. 입력 정보를 다시 확인해 주세요.": "公式サーバーで引き継ぎ情報を確認できませんでした。入力情報を確認してください。", "확인 정보가 만료되었습니다. 인계 정보를 다시 확인해 주세요.": "確認情報が期限切れです。引き継ぎ情報をもう一度確認してください。", "일본 공식 서버 점검 중입니다. 나중에 다시 시도해 주세요.": "日本公式サーバーはメンテナンス中です。後でもう一度お試しください。", "공식 서버 자료와 로컬 자료가 맞지 않습니다. 앱을 업데이트한 뒤 다시 시도해 주세요.": "公式サーバーとローカルのデータが一致しません。アプリを更新してから再試行してください。", "일본 공식 서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요.": "日本公式サーバーに接続できませんでした。接続状態を確認してください。"});
  Object.assign(UI_TRANSLATIONS.en, {"인계 ID와 비밀번호 형식을 확인해 주세요.": "Check the transfer ID and password format.", "공식 서버에서 인계 정보를 확인하지 못했습니다. 입력 정보를 다시 확인해 주세요.": "The official server could not verify the transfer details. Check the entered details.", "확인 정보가 만료되었습니다. 인계 정보를 다시 확인해 주세요.": "Verification has expired. Check the transfer details again.", "일본 공식 서버 점검 중입니다. 나중에 다시 시도해 주세요.": "The Japanese official server is under maintenance. Try again later.", "공식 서버 자료와 로컬 자료가 맞지 않습니다. 앱을 업데이트한 뒤 다시 시도해 주세요.": "Official and local data do not match. Update the app and try again.", "일본 공식 서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요.": "Could not connect to the Japanese official server. Check your connection."});

  Object.assign(UI_TRANSLATIONS.ja, {"저장 슬롯 이름을 슬래시·제어문자 없이 UTF-8 64바이트 이내로 입력해 주세요.": "保存スロット名はスラッシュ・制御文字なし、UTF-8で64バイト以内にしてください。"});
  Object.assign(UI_TRANSLATIONS.en, {"저장 슬롯 이름을 슬래시·제어문자 없이 UTF-8 64바이트 이내로 입력해 주세요.": "Enter a save slot name of up to 64 UTF-8 bytes without slashes or control characters."});

  Object.assign(UI_TRANSLATIONS.ja, {"일반 계정 저장 중": "通常アカウントに保存中", "대상 계정이 변경되었습니다. 계정 목록을 다시 확인해 주세요.": "対象アカウントが変更されました。一覧を確認し直してください。"});
  Object.assign(UI_TRANSLATIONS.en, {"일반 계정 저장 중": "Saving normal account", "대상 계정이 변경되었습니다. 계정 목록을 다시 확인해 주세요.": "The target account changed. Check the account list again."});

  Object.assign(UI_TRANSLATIONS.ja, {"계정 저장은 완료됐지만 서버를 다시 시작하지 못했습니다. ‘서버 시작’을 다시 누르고, 계속 실패하면 앱을 다시 열어 주세요.": "アカウントの保存は完了しましたが、サーバーを再起動できませんでした。「サーバー開始」を再試行し、失敗が続く場合はアプリを開き直してください。", "서버를 다시 시작하지 못했습니다. 서버 상태를 확인해 주세요.": "サーバーを再起動できませんでした。サーバーの状態を確認してください。", "계정 저장은 완료됐습니다. 임시 파일 정리가 남아 있습니다.": "アカウントの保存は完了しました。一時ファイルの削除が残っています。", "계정 저장은 완료됐습니다. 위 ‘계정 목록 불러오기’로 목록을 새로 확인해 주세요.": "アカウントの保存は完了しました。上の「アカウント一覧を読み込む」で一覧を更新してください。"});
  Object.assign(UI_TRANSLATIONS.en, {"계정 저장은 완료됐지만 서버를 다시 시작하지 못했습니다. ‘서버 시작’을 다시 누르고, 계속 실패하면 앱을 다시 열어 주세요.": "The account was saved, but the server could not restart. Select Start Server again; if it keeps failing, reopen the app.", "서버를 다시 시작하지 못했습니다. 서버 상태를 확인해 주세요.": "The server could not restart. Check its status.", "계정 저장은 완료됐습니다. 임시 파일 정리가 남아 있습니다.": "The account was saved. Temporary files still need cleanup.", "계정 저장은 완료됐습니다. 위 ‘계정 목록 불러오기’로 목록을 새로 확인해 주세요.": "The account was saved. Use Load accounts above to refresh the list."});

  Object.assign(UI_TRANSLATIONS.en, {"모시코이 이벤트 설정": "Moshikoi event settings", "지원 목록에서 이벤트와 기간을 설정합니다. 설정만 자동 저장하며 이벤트 시작·진행 초기화·보상 지급을 실행하지 않습니다.": "Choose supported events and their time windows. Changes only save settings; they do not start events, reset progress or grant rewards.", "처음 켜면 현재 기기 시각부터 30일을 제안합니다. 직접 바꿀 수 있으며 최대 366일입니다. 이 기간은 로컬 설정이며 원본 이벤트 기간이 아닙니다.": "Enabling an event proposes 30 days from the current device time. You can edit it, up to 366 days. This is a local setting, not the original event period.", "설정할 이벤트": "Event to configure", "지원 목록 없음": "No supported catalog", "다음 서버 시작에 이 이벤트 사용": "Use this event at the next server start", "시작 시각 · 기기 현지 시간": "Start · Device local time", "종료 시각 · 기기 현지 시간": "End · Device local time", "끄면 사용 목록에서만 제외합니다. 저장된 이벤트 진행은 유지합니다.": "Disabling only removes the event from the enabled list. Saved progress is preserved.", "현재 적용 이벤트: ": "Active events: ", "저장된 다음 이벤트: ": "Saved events for next start: ", "없음": "None", "이벤트 설정을 아직 불러오지 못했습니다.": "Event settings have not loaded yet.", "저장한 이벤트 설정은 다음 서버 시작에 적용됩니다. 게임을 이미 시작했다면 앱을 완전히 종료하고 다시 열어 주세요.": "Saved event settings apply at the next server start. If the game has started, fully close and reopen the app.", "지원 목록을 확인할 수 없어 이벤트 설정을 변경할 수 없습니다.": "The supported catalog is unavailable, so event settings cannot be changed.", "이벤트 설정 파일을 읽지 못했습니다. 자동으로 덮어쓰지 않습니다.": "The event settings file could not be read. It will not be overwritten automatically.", "현재 서버와 저장된 이벤트 설정이 같습니다.": "The running server and saved event settings match.", "다른 화면에서 이벤트 설정이 바뀌었습니다. 최신 상태를 확인한 뒤 다시 시도를 눌러 현재 입력을 저장해 주세요.": "Event settings changed in another window. Review the latest status, then choose Retry to save your current edits.", "현재 선택 이벤트 적용 기간: ": "Active window for selected event: "});
  Object.assign(UI_TRANSLATIONS.ja, {"모시코이 이벤트 설정": "もし恋イベント設定", "지원 목록에서 이벤트와 기간을 설정합니다. 설정만 자동 저장하며 이벤트 시작·진행 초기화·보상 지급을 실행하지 않습니다.": "対応リストからイベントと期間を設定します。設定のみ自動保存し、イベント開始・進行初期化・報酬付与は実行しません。", "처음 켜면 현재 기기 시각부터 30일을 제안합니다. 직접 바꿀 수 있으며 최대 366일입니다. 이 기간은 로컬 설정이며 원본 이벤트 기간이 아닙니다.": "初めて有効にすると端末の現在時刻から30日間を提案します。最大366日まで編集できます。これはローカル設定で、元の開催期間ではありません。", "설정할 이벤트": "設定するイベント", "지원 목록 없음": "対応リストなし", "다음 서버 시작에 이 이벤트 사용": "次回サーバー起動時にこのイベントを使用", "시작 시각 · 기기 현지 시간": "開始日時・端末の現地時刻", "종료 시각 · 기기 현지 시간": "終了日時・端末の現地時刻", "끄면 사용 목록에서만 제외합니다. 저장된 이벤트 진행은 유지합니다.": "無効にすると使用リストからのみ外れます。保存済みの進行状況は保持します。", "현재 적용 이벤트: ": "現在適用中のイベント: ", "저장된 다음 이벤트: ": "保存済みの次回イベント: ", "없음": "なし", "이벤트 설정을 아직 불러오지 못했습니다.": "イベント設定をまだ読み込めていません。", "저장한 이벤트 설정은 다음 서버 시작에 적용됩니다. 게임을 이미 시작했다면 앱을 완전히 종료하고 다시 열어 주세요.": "保存したイベント設定は次回のサーバー起動時に反映します。ゲーム開始後はアプリを完全に終了して開き直してください。", "지원 목록을 확인할 수 없어 이벤트 설정을 변경할 수 없습니다.": "対応リストを確認できないためイベント設定を変更できません。", "이벤트 설정 파일을 읽지 못했습니다. 자동으로 덮어쓰지 않습니다.": "イベント設定ファイルを読み込めません。自動で上書きしません。", "현재 서버와 저장된 이벤트 설정이 같습니다.": "現在のサーバーと保存済みイベント設定は一致しています。", "다른 화면에서 이벤트 설정이 바뀌었습니다. 최신 상태를 확인한 뒤 다시 시도를 눌러 현재 입력을 저장해 주세요.": "別の画面でイベント設定が変更されました。最新の状態を確認し、「再試行」で現在の入力を保存してください。", "현재 선택 이벤트 적용 기간: ": "選択中イベントの適用期間: "});

  Object.assign(UI_TRANSLATIONS.en, {"이벤트 설정을 저장하지 못했습니다. 저장 상태와 지원 목록을 확인해 주세요.": "Could not save event settings. Check the saved state and supported catalog."});
  Object.assign(UI_TRANSLATIONS.ja, {"이벤트 설정을 저장하지 못했습니다. 저장 상태와 지원 목록을 확인해 주세요.": "イベント設定を保存できません。保存状態と対応リストを確認してください。"});

  function resolveInterfaceLanguage(value, navigator = {}) {
    if (["ko", "ja", "en"].includes(value)) return value;
    const languages = Array.isArray(navigator.languages) ? navigator.languages : [];
    const preferred = languages[0] || navigator.language || "ko";
    const code = String(preferred).toLowerCase().split(/[-_]/)[0];
    return ["ko", "ja", "en"].includes(code) ? code : "en";
  }
  function translateUI(value, language) {
    const dictionary = UI_TRANSLATIONS[language];
    return typeof value === "string" && dictionary && Object.prototype.hasOwnProperty.call(dictionary, value) ? dictionary[value] : value;
  }
  Object.assign(UI_TRANSLATIONS.en, {"게임 홈 → 이벤트 → 사큐×마호": "Game Home → Event → Succu × Magic"});
  Object.assign(UI_TRANSLATIONS.ja, {"게임 홈 → 이벤트 → 사큐×마호": "ゲームホーム → イベント → サキュ×まほ"});
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  Object.assign(UI_TRANSLATIONS.en, {"MV를 MP4로 내보내기":"Export MV as MP4","게임에서 3D MV를 연 뒤 이 메뉴를 여세요. 현재 렌더 크기로 프레임과 음원을 내보냅니다.":"Open a 3D MV in the game, then open this menu. Frames and soundtrack use the current render size.","3D MV 준비 대기":"Waiting for a 3D MV","MP4 프레임 수":"MP4 frame rate","영상 비트레이트":"Video bitrate","영상 코덱":"Video codec","MP4 진행률":"MP4 progress","MP4 내보내기":"Export MP4","MP4 저장·공유":"Save / Share MP4","취소":"Cancel","음원 준비 중":"Preparing soundtrack","MP4 렌더링":"Rendering MP4","MP4 마무리 중":"Finalizing MP4","MP4 완료":"MP4 complete","MP4 실패":"MP4 failed","게임에서 3D MV를 연 뒤 이 메뉴를 여세요.":"Open a 3D MV in the game, then open this menu.","현재 렌더 크기로 프레임과 음원을 내보냅니다.":"Frames and soundtrack use the current render size.","MP4 기능을 사용할 수 없습니다.":"MP4 export is unavailable.","3D MV 재생 화면에서 다시 시도해 주세요.":"Try again from a playing 3D MV.","다른 MP4 작업을 마친 뒤 다시 시도해 주세요.":"Finish the current MP4 job first."});
  Object.assign(UI_TRANSLATIONS.ja, {"MV를 MP4로 내보내기":"MVをMP4に書き出す","게임에서 3D MV를 연 뒤 이 메뉴를 여세요. 현재 렌더 크기로 프레임과 음원을 내보냅니다.":"ゲームで3D MVを開いてから、このメニューを開いてください。現在の描画サイズでフレームと音源を書き出します。","3D MV 준비 대기":"3D MVの準備待ち","MP4 프레임 수":"MP4フレームレート","영상 비트레이트":"映像ビットレート","영상 코덱":"映像コーデック","MP4 진행률":"MP4進行状況","MP4 내보내기":"MP4を書き出す","MP4 저장·공유":"MP4を保存・共有","취소":"キャンセル","음원 준비 중":"音源を準備中","MP4 렌더링":"MP4レンダリング","MP4 마무리 중":"MP4を仕上げ中","MP4 완료":"MP4完了","MP4 실패":"MP4に失敗","게임에서 3D MV를 연 뒤 이 메뉴를 여세요.":"ゲームで3D MVを開いてから、このメニューを開いてください。","현재 렌더 크기로 프레임과 음원을 내보냅니다.":"現在の描画サイズでフレームと音源を書き出します。","MP4 기능을 사용할 수 없습니다.":"MP4書き出しを利用できません。","3D MV 재생 화면에서 다시 시도해 주세요.":"3D MVの再生画面で再試行してください。","다른 MP4 작업을 마친 뒤 다시 시도해 주세요.":"現在のMP4処理が完了してから再試行してください。"});
  Object.assign(UI_TRANSLATIONS.en, {"콘솔": "Console", "유저 관리": "User management", "콘텐츠": "Content", "그래픽": "Graphics", "설정 분류": "Settings categories", "서버 메뉴 안내": "Using the server menu", "서버 연결·자료 검사·진단": "Connections, data checks and diagnostics", "모두 활성화": "Enable all", "모두 비활성화": "Disable all", "모시코이 여러 이벤트 선택": "Select multiple Moshikoi events", "이벤트별 기간 조정": "Adjust individual event windows", "설정할 계정 종류": "Account mode to configure", "여러 이벤트를 한 번에 선택할 수 있습니다. 끄더라도 저장된 진행은 유지됩니다.": "Select several events at once. Disabling keeps saved progress.", "감상 계정은 처음에 지원되는 모시코이를 모두 활성화합니다. 원하는 이벤트만 남기거나 모두 끌 수 있습니다.": "Viewing accounts start with every supported Moshikoi event enabled. Keep only the events you want, or disable all.", "최신 설정에 선택한 변경을 합쳐 저장합니다.": "Merging your changes into the latest settings."});
  Object.assign(UI_TRANSLATIONS.ja, {"콘솔": "コンソール", "유저 관리": "ユーザー管理", "콘텐츠": "コンテンツ", "그래픽": "グラフィック", "설정 분류": "設定カテゴリ", "서버 메뉴 안내": "サーバーメニューの使い方", "서버 연결·자료 검사·진단": "接続・データ検査・診断", "모두 활성화": "すべて有効", "모두 비활성화": "すべて無効", "모시코이 여러 이벤트 선택": "もし恋イベントの複数選択", "이벤트별 기간 조정": "イベント別の期間設定", "설정할 계정 종류": "設定するアカウント種別", "여러 이벤트를 한 번에 선택할 수 있습니다. 끄더라도 저장된 진행은 유지됩니다.": "複数のイベントを一度に選べます。無効にしても保存済みの進行は保持します。", "감상 계정은 처음에 지원되는 모시코이를 모두 활성화합니다. 원하는 이벤트만 남기거나 모두 끌 수 있습니다.": "鑑賞アカウントは最初から対応するもし恋をすべて有効にします。必要なイベントのみ残したり、すべて無効にしたりできます。", "최신 설정에 선택한 변경을 합쳐 저장합니다.": "最新の設定に選択した変更を反映して保存します。"});
  Object.assign(UI_TRANSLATIONS.en, {"도움말": "Help", "감상 계정은 처음에 모든 이벤트가 켜집니다.": "Viewing accounts start with all events enabled.", "끄더라도 진행은 유지됩니다.": "Disabling keeps saved progress.", "일본 공식 계정 가져오기는 현재 작동하지 않습니다.": "Japanese official account import is currently unavailable.", "검사 후 가져오기를 눌러야 계정이 바뀝니다.": "The account changes only after you choose Import.", "현재 적용: ": "Active: ", "현재 적용: 대기": "Active: waiting", "다음 실행: ": "Next start: ", "다음 실행: 대기": "Next start: waiting"});
  Object.assign(UI_TRANSLATIONS.ja, {"도움말": "ヘルプ", "감상 계정은 처음에 모든 이벤트가 켜집니다.": "鑑賞アカウントは最初からすべてのイベントが有効です。", "끄더라도 진행은 유지됩니다.": "無効にしても進行は保持します。", "일본 공식 계정 가져오기는 현재 작동하지 않습니다.": "日本公式アカウントの取り込みは現在利用できません。", "검사 후 가져오기를 눌러야 계정이 바뀝니다.": "検査後に「取り込み」を押すまでアカウントは変更しません。", "현재 적용: ": "適用中: ", "현재 적용: 대기": "適用中: 待機", "다음 실행: ": "次回起動: ", "다음 실행: 대기": "次回起動: 待機"});
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const choice = (value, values) => values.includes(value);
  const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
  const identity = value => object(value) && value.schema === 1 && integer(value.revision);
  const validOptions = value => object(value) && typeof value.media_mode === "boolean" && typeof value.download_missing_resources === "boolean" && choice(value.language, ["ko", "ja", "en"]) && (value.interface_language === undefined || choice(value.interface_language, INTERFACE_LANGUAGES));
  const validPresentation = value => exact(value, ["schema", "revision", "custom_graphics", "quality", "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"]) && identity(value) && typeof value.custom_graphics === "boolean" && typeof value.expand_photography === "boolean" && choice(value.quality, [0, 10, 20, 30, 40, 100]) && choice(value.target_fps, [0, 30, 60, 90, 120]) && typeof value.render_scale === "number" && Number.isFinite(value.render_scale) && value.render_scale >= 0.25 && value.render_scale <= 2 && integer(value.max_buffer_pixel) && value.max_buffer_pixel >= 256 && value.max_buffer_pixel <= 4096 && value.max_buffer_pixel % 2 === 0 && choice(value.anti_aliasing, [-1, 0, 1, 2]) && choice(value.shadow_resolution, [0, 512, 1024, 2048, 4096]);
  const validPlayback = value => exact(value, ["schema", "revision", "wait_for_orientation"]) && identity(value) && typeof value.wait_for_orientation === "boolean";
  const validMedia = value => exact(value, ["schema", "revision", "hide_video_mv", "mv_sort", "outfit_sort"]) && identity(value) && typeof value.hide_video_mv === "boolean" && choice(value.mv_sort, ["recent", "old", "title", "id"]) && choice(value.outfit_sort, ["original", "recent", "old", "title", "id"]);
  const EVENT_WINDOW_LIMIT = 366 * 86400000;
  const validEvents = (value, media = false) => exact(value, ["schema", "revision", "love_events"]) && identity(value)
    && Array.isArray(value.love_events) && value.love_events.length <= 64
    && value.love_events.every((row, index, rows) => exact(row, ["event_id", "start_time_ms", "end_time_ms"])
      && typeof row.event_id === "string" && /^[A-Za-z0-9_-]{1,96}$/.test(row.event_id)
      && (index === 0 || rows[index-1].event_id < row.event_id)
      && integer(row.start_time_ms) && integer(row.end_time_ms)
      && (media ? row.start_time_ms === 0 && row.end_time_ms === 0
        : row.start_time_ms < row.end_time_ms && row.end_time_ms - row.start_time_ms <= EVENT_WINDOW_LIMIT));
  const plain = (value, limit = 1000) => typeof value === "string" ? value.slice(0, limit) : "";
  const count = value => integer(value) ? value : 0;
  const boundedJSON = (value, limit) => {
    try { const encoded = JSON.stringify(value); return typeof encoded === "string" && encoded.length <= limit; }
    catch (_) { return false; }
  };

  function utf8Length(value) {
    let bytes = 0;
    for (const point of value) {
      const code = point.codePointAt(0);
      if (code >= 0xD800 && code <= 0xDFFF) return Infinity;
      bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
    }
    return bytes;
  }
  function diagnosticSlice(value, byteLimit, wireLimit) {
    let text = "", bytes = 0, wire = 0;
    for (let point of value) {
      let code = point.codePointAt(0);
      if (code >= 0xD800 && code <= 0xDFFF) { point = "\uFFFD"; code = 0xFFFD; }
      const size = code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
      const escaped = code === 0x22 || code === 0x5C ? 2
        : code < 0x20 ? ([8, 9, 10, 12, 13].includes(code) ? 2 : 6) : size;
      if (bytes + size > byteLimit || wire + escaped > wireLimit) return {text, truncated: true};
      text += point; bytes += size; wire += escaped;
    }
    return {text, truncated: false};
  }
  function boundedDiagnostics(value, suffix) {
    const full = diagnosticSlice(value, MAX_DIAGNOSTIC_BYTES, MAX_DIAGNOSTIC_WIRE_BYTES);
    if (!full.truncated) return full.text;
    const marker = "\n" + suffix;
    const markerWire = utf8Length(JSON.stringify(marker)) - 2;
    return diagnosticSlice(value, MAX_DIAGNOSTIC_BYTES - utf8Length(marker), MAX_DIAGNOSTIC_WIRE_BYTES - markerWire).text + marker;
  }

  Object.assign(UI_TRANSLATIONS.en, {"일시 정지":"Pause","계속하기":"Resume","MP4 일시 정지":"MP4 paused","MP4 일시 정지 중…":"Pausing MP4…","앱으로 돌아오면 이어서 처리합니다.":"Processing resumes when you return to the app.","게임 화면이 준비되면 계속할 수 있습니다.":"Resume when the game surface is ready.","계속하기를 누르면 이어서 처리합니다.":"Choose Resume to continue."});
  Object.assign(UI_TRANSLATIONS.ja, {"일시 정지":"一時停止","계속하기":"再開","MP4 일시 정지":"MP4を一時停止中","MP4 일시 정지 중…":"MP4を一時停止しています…","앱으로 돌아오면 이어서 처리합니다.":"アプリに戻ると処理を再開します。","게임 화면이 준비되면 계속할 수 있습니다.":"ゲーム画面の準備ができたら再開できます。","계속하기를 누르면 이어서 처리합니다.":"再開を押すと処理を続けます。"});

  Object.assign(UI_TRANSLATIONS.en, {
    "MV를 모은 뒤 큐를 실행하세요.":"Add MVs, then run the queue.",
    "큐 실행":"Run queue","현재 MV 추가":"Add current MV","큐 일시 정지":"Pause queue","큐 계속하기":"Resume queue",
    "큐 실행 중":"Queue running","작업 목록":"Jobs","등록한 작업이 없습니다.":"No jobs added.","MP4 작업 목록":"MP4 jobs",
    "앱을 나가면 멈추고 돌아오면 이어집니다.":"Export pauses when you leave the app and resumes when you return.",
    "현재 MV 바로 내보내기":"Export current MV now","내보내는 중":"Exporting","완료":"Complete","실패":"Failed","중단됨 · 다시 시도 가능":"Interrupted · retry available",
    "명":"performers","저장·공유":"Save / Share","위로":"Move up","아래로":"Move down","목록에서 제거":"Remove from list",
    "파일·작업 삭제":"Delete file and job","삭제 확인":"Confirm deletion",
    "보관 중인 MP4와 작업을 삭제합니다. 외부에 저장한 파일은 유지됩니다.":"Delete the stored MP4 and its job. Files saved elsewhere are kept.",
    "MP4 작업을 처리하지 못했습니다. 다시 시도해 주세요.":"Couldn't process this MP4 job. Please try again."
  });
  Object.assign(UI_TRANSLATIONS.ja, {
    "MV를 모은 뒤 큐를 실행하세요.":"MVを追加してからキューを実行してください。",
    "큐 실행":"キューを実行","현재 MV 추가":"現在のMVを追加","큐 일시 정지":"キューを一時停止","큐 계속하기":"キューを再開",
    "큐 실행 중":"キューを実行中","작업 목록":"処理リスト","등록한 작업이 없습니다.":"登録された処理はありません。","MP4 작업 목록":"MP4処理リスト",
    "앱을 나가면 멈추고 돌아오면 이어집니다.":"アプリを離れると一時停止し、戻ると処理を再開します。",
    "현재 MV 바로 내보내기":"現在のMVをすぐに書き出す","내보내는 중":"書き出し中","완료":"完了","실패":"失敗","중단됨 · 다시 시도 가능":"中断 · 再試行できます",
    "명":"人","저장·공유":"保存・共有","위로":"上へ","아래로":"下へ","목록에서 제거":"リストから削除",
    "파일·작업 삭제":"ファイルと処理を削除","삭제 확인":"削除を確定",
    "보관 중인 MP4와 작업을 삭제합니다. 외부에 저장한 파일은 유지됩니다.":"保管中のMP4と処理を削除します。外部に保存したファイルは残ります。",
    "MP4 작업을 처리하지 못했습니다. 다시 시도해 주세요.":"MP4の処理に失敗しました。再試行してください。"
  });
  Object.assign(UI_TRANSLATIONS.en, {
    "출력 크기":"Output size","현재 렌더 크기":"Current render size","가로 (픽셀)":"Width (pixels)","세로 (픽셀)":"Height (pixels)",
    "권장값 자동 계산":"Automatic recommendation","비트레이트 (Mbps)":"Bitrate (Mbps)","권장 비트레이트":"Recommended bitrate",
    "MV가 준비되면 권장값을 표시합니다.":"The recommendation appears when the MV is ready.",
    "MP4 크기와 게임 렌더 품질은 별도입니다.":"MP4 size and game render quality are separate.",
    "비트레이트는 0.1~200 Mbps로 입력해 주세요.":"Enter a bitrate from 0.1 to 200 Mbps.",
    "가로·세로는 16~4096의 짝수 픽셀로 입력해 주세요.":"Enter an even width and height from 16 to 4096 pixels.",
    "MP4 설정을 저장하지 못했습니다. 값을 바꾸면 다시 저장합니다.":"MP4 settings could not be saved. Change a value to retry.",
    "MP4 설정을 불러오지 못했습니다.":"MP4 settings could not be loaded.","MP4 설정 확인 중…":"Checking MP4 settings…"
  });
  Object.assign(UI_TRANSLATIONS.ja, {
    "출력 크기":"出力サイズ","현재 렌더 크기":"現在の描画サイズ","가로 (픽셀)":"横（ピクセル）","세로 (픽셀)":"縦（ピクセル）",
    "권장값 자동 계산":"推奨値を自動計算","비트레이트 (Mbps)":"ビットレート（Mbps）","권장 비트레이트":"推奨ビットレート",
    "MV가 준비되면 권장값을 표시합니다.":"MVの準備ができると推奨値を表示します。",
    "MP4 크기와 게임 렌더 품질은 별도입니다.":"MP4サイズとゲームの描画品質は別です。",
    "비트레이트는 0.1~200 Mbps로 입력해 주세요.":"ビットレートは0.1〜200 Mbpsで入力してください。",
    "가로·세로는 16~4096의 짝수 픽셀로 입력해 주세요.":"横・縦は16〜4096の偶数ピクセルで入力してください。",
    "MP4 설정을 저장하지 못했습니다. 값을 바꾸면 다시 저장합니다.":"MP4設定を保存できませんでした。値を変更すると再試行します。",
    "MP4 설정을 불러오지 못했습니다.":"MP4設定を読み込めませんでした。","MP4 설정 확인 중…":"MP4設定を確認中…"
  });
  const MP4_OPTION_DEFAULTS = Object.freeze({schema:1,fps:60,video_codec:1,bitrate_mode:"recommended",video_bitrate:16000000,resolution_mode:"current",width:1920,height:1080});
  const mp4Dimension = value => integer(value) && value >= 16 && value <= 4096 && value % 2 === 0;
  function validMP4ExportOptions(value) {
    return exact(value,["schema","fps","video_codec","bitrate_mode","video_bitrate","resolution_mode","width","height"])
      && value.schema === 1 && choice(value.fps,[30,60]) && choice(value.video_codec,[1,2])
      && choice(value.bitrate_mode,["recommended","custom"]) && integer(value.video_bitrate) && value.video_bitrate >= 100000 && value.video_bitrate <= 200000000
      && choice(value.resolution_mode,["current","custom"]) && mp4Dimension(value.width) && mp4Dimension(value.height);
  }
  function recommendedMP4Bitrate(width,height,fps,codec) {
    if (!integer(width) || !integer(height) || width < 16 || height < 16 || width > 4096 || height > 4096 || !choice(fps,[30,60]) || !choice(codec,[1,2])) return null;
    width -= width % 2;height -= height % 2;
    return Math.max(250000,Math.min(200000000,Math.floor((width*height*fps*(codec === 1 ? 14 : 9)+500000)/1000000)*10000));
  }

  function validRequest(action, payload) {
    const mp4ID = value => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
    if (["mp4_queue_status","mp4_queue_run","mp4_queue_pause","mp4_queue_resume"].includes(action)) return exact(payload, []);
    if (["mp4_queue_cancel","mp4_queue_retry"].includes(action)) return exact(payload,["job_id"]) && mp4ID(payload.job_id);
    if (action === "mp4_queue_remove") return mp4ID(payload.job_id) && (exact(payload,["job_id"]) || (exact(payload,["job_id","delete_output"]) && payload.delete_output === true));
    if (action === "mp4_queue_move") return exact(payload,["job_id","position"]) && mp4ID(payload.job_id) && integer(payload.position) && payload.position <= 7;
    if (action === "mp4_save") return exact(payload,[]) || (exact(payload,["job_id"]) && mp4ID(payload.job_id));
    if (["mp4_status","mp4_pause","mp4_resume","mp4_cancel","mp4_save"].includes(action)) return exact(payload, []);
    if (action === "mp4_options") return exact(payload,[]);
    if (action === "mp4_options_save") return exact(payload,["options"]) && validMP4ExportOptions(payload.options);
    if (action === "mp4_start" || action === "mp4_enqueue") return (exact(payload,["fps","video_bitrate","video_codec"])
      || exact(payload,["fps","video_bitrate","video_codec","width","height"]) && ((payload.width === 0 && payload.height === 0) || mp4Dimension(payload.width) && mp4Dimension(payload.height)))
      && choice(payload.fps,[30,60]) && integer(payload.video_bitrate) && (payload.video_bitrate === 0 || payload.video_bitrate >= 100000 && payload.video_bitrate <= 200000000) && choice(payload.video_codec,[1,2]);
    if (["status", "official_status", "official_inspect"].includes(action)) return exact(payload, []);
    if (action === "events_status") return exact(payload, []) || (exact(payload, ["mode"]) && choice(payload.mode, ["normal", "media"]));
    if (action === "events_save") return (exact(payload, ["settings", "expected_revision"]) || (exact(payload, ["settings", "expected_revision", "mode"]) && choice(payload.mode, ["normal", "media"]))) && validEvents(payload.settings, payload.mode === "media")
      && integer(payload.expected_revision) && payload.settings.revision === payload.expected_revision;

    const profile = value => typeof value === "string" && value.trim() === value && utf8Length(value) >= 1
      && utf8Length(value) <= 64 && !/[\/\\\u0000-\u001f\u007f]/.test(value);
    const revision = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
    const mode = value => choice(value, ["normal", "media"]);
    const officialID = value => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
    if (["official_fetch","official_cancel"].includes(action)) return exact(payload,["job_id"]) && officialID(payload.job_id);
    if (action === "official_apply") return exact(payload,["job_id","profile","replace","expected_revision"])
      && officialID(payload.job_id) && profile(payload.profile) && typeof payload.replace === "boolean"
      && (payload.replace ? revision(payload.expected_revision) : payload.expected_revision === null);
    if (action === "accounts_status") return exact(payload, []) || exact(payload, ["offset", "restore_offset"])
      && integer(payload.offset) && integer(payload.restore_offset) && payload.offset <= 65535 && payload.restore_offset <= 65535;
    if (action === "accounts_create") return exact(payload, ["mode", "profile", "manager_name"]) && mode(payload.mode)
      && profile(payload.profile) && typeof payload.manager_name === "string" && payload.manager_name.trim().length > 0
      && payload.manager_name.length <= 10 && !/[\r\n\t]/.test(payload.manager_name);
    if (action === "accounts_clone") return exact(payload, ["mode", "source_profile", "profile", "expected_revision"])
      && mode(payload.mode) && profile(payload.profile) && profile(payload.source_profile) && revision(payload.expected_revision);
    if (action === "accounts_select") return exact(payload, ["mode", "profile", "expected_revision", "selection_revision"])
      && mode(payload.mode) && profile(payload.profile) && revision(payload.expected_revision) && revision(payload.selection_revision);
    if (action === "accounts_export") return exact(payload, ["mode", "profile", "expected_revision"])
      && mode(payload.mode) && profile(payload.profile) && revision(payload.expected_revision);
    if (action === "accounts_preview" || action === "diagnostics_clear") return exact(payload, []);
    if (action === "accounts_import") return exact(payload, ["token", "mode", "profile", "replace", "expected_revision"])
      && typeof payload.token === "string" && /^[0-9a-f]{32}$/.test(payload.token) && mode(payload.mode) && profile(payload.profile)
      && typeof payload.replace === "boolean" && (payload.replace ? revision(payload.expected_revision) : payload.expected_revision === null);
    if (action === "accounts_restore") return exact(payload, ["restore_id", "mode", "profile", "expected_revision"])
      && typeof payload.restore_id === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(payload.restore_id)
      && mode(payload.mode) && profile(payload.profile) && revision(payload.expected_revision);

    if (action === "launch_settings_barrier") return exact(payload, ["nonce", "ready"])
      && typeof payload.nonce === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(payload.nonce)
      && typeof payload.ready === "boolean";
    if (action === "save_interface_language") return exact(payload, ["interface_language"])
      && choice(payload.interface_language, INTERFACE_LANGUAGES);
    if (action === "diagnostics_copy") return exact(payload, ["text"]) && typeof payload.text === "string"
      && payload.text.length <= MAX_DIAGNOSTIC_BYTES && utf8Length(payload.text) <= MAX_DIAGNOSTIC_BYTES
      && utf8Length(JSON.stringify(payload)) <= MAX_DIAGNOSTIC_WIRE_BYTES + 16;
    if (action === "save_options") return exact(payload, ["media_mode", "download_missing_resources", "language", "interface_language"]) && validOptions(payload);
    if (action === "save_presentation") return exact(payload, ["settings"]) && validPresentation(payload.settings);
    if (action === "save_playback") return exact(payload, ["settings"]) && validPlayback(payload.settings);
    if (action === "save_media") return exact(payload, ["settings"]) && validMedia(payload.settings);
    if (action === "resources_cancel") return exact(payload, ["job_id"]) && typeof payload.job_id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(payload.job_id);
    if (action === "resources_download") return exact(payload, ["parallelism"]) && choice(payload.parallelism, [1, 2, 4, 8]);
    if (["resources_preview", "resources_import", "resources_export"].includes(action)) return exact(payload, []);
    return false;
  }

  function validImportProgress(value) {
    return object(value) && ["resource_import_progress","account_import_progress"].includes(value.event)
      && Number.isInteger(value.request_id) && value.request_id >= 1 && value.request_id <= MAX_ID
      && ["selecting", "preparing", "copying", "queued", "failed"].includes(value.stage)
      && Number.isSafeInteger(value.copied_bytes) && value.copied_bytes >= 0
      && Number.isSafeInteger(value.total_bytes) && value.total_bytes >= 0
      && (value.total_bytes === 0 || value.copied_bytes <= value.total_bytes);
  }

  // The only transport is the native handler. IDs are never reused in a page,
  // so a reply arriving after hide, timeout or a later request cannot own it.
  function createBridge(scope, timers = scope) {
    const pending = new Map();
    const listeners = new Set();
    let nextID = 1;
    let active = true;
    let disposed = false;

    function rejectPending(message) {
      for (const item of pending.values()) {
        timers.clearTimeout(item.timer);
        item.reject(new Error(message));
      }
      pending.clear();
    }
    function reply(id, envelope) {
      if (!active || disposed || !Number.isInteger(id) || id < 1 || id > MAX_ID) return;
      const item = pending.get(id);
      if (!item || !object(envelope) || envelope.id !== id || typeof envelope.ok !== "boolean" || !boundedJSON(envelope, 524288)) return;
      if (envelope.ok && !object(envelope.result)) return;
      pending.delete(id);
      timers.clearTimeout(item.timer);
      if (envelope.ok) item.resolve(envelope.result);
      else {
        const error = new Error(plain(envelope.error && envelope.error.message, 300) || "요청을 처리하지 못했습니다.");
        const code = envelope.error && envelope.error.code;
        if (typeof code === "string" && /^[a-z][a-z0-9_]{0,79}$/.test(code)) error.code = code;
        item.reject(error);
      }
    }
    function armTimeout(id, item) {
      timers.clearTimeout(item.timer);
      item.timer = timers.setTimeout(() => {
        if (pending.get(id) !== item) return;
        pending.delete(id);
        item.reject(new Error("응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요."));
      }, item.timeout);
    }
    function event(value) {
      if (!active || disposed || !object(value) || !boundedJSON(value, 524288)) return;
      if (["resource_import_progress","account_import_progress"].includes(value.event)) {
        const item = pending.get(value.request_id);
        const action = value.event === "account_import_progress" ? "accounts_preview" : "resources_import";
        if (!validImportProgress(value) || !item || item.action !== action) return;
        const order = {selecting: -1, preparing: 0, copying: 1, queued: 2, failed: 3};
        if (item.importStage !== null && (order[value.stage] < order[item.importStage] || value.copied_bytes < item.importCopied)) return;
        // Extend only this import's inactivity deadline when real work advances.
        // Repeated heartbeats and unrelated/stale IDs cannot keep it alive.
        if (item.importStage !== value.stage || value.copied_bytes > item.importCopied) armTimeout(value.request_id, item);
        item.importStage = value.stage; item.importCopied = value.copied_bytes;
      }
      for (const listener of listeners) listener(value);
    }
    scope.idolyServerReply = reply;
    scope.idolyServerEvent = event;
    return {
      request(action, payload = {}) {
        if (!validRequest(action, payload) || !boundedJSON(payload, action === "diagnostics_copy" ? MAX_DIAGNOSTIC_WIRE_BYTES + 16 : 16384)) return Promise.reject(new Error("허용되지 않은 설정 요청입니다."));
        if (!active || disposed) return Promise.reject(new Error("설정 화면이 닫혀 있습니다."));
        const handler = scope.webkit && scope.webkit.messageHandlers && scope.webkit.messageHandlers.idolyServer;
        if (!handler || typeof handler.postMessage !== "function") return Promise.reject(new Error("앱 안에서 설정 화면을 열어 주세요."));
        if (pending.size >= MAX_PENDING || nextID > MAX_ID) return Promise.reject(new Error("진행 중인 요청을 마친 후 다시 시도해 주세요."));
        const id = nextID++;
        return new Promise((resolve, reject) => {
          const timeout = (["resources_import", "resources_export"].includes(action) || (action.startsWith("accounts_") || action.startsWith("official_"))) ? 120000 : 20000;
          const item = {resolve, reject, timer: null, timeout, action, importStage: null, importCopied: -1};
          pending.set(id, item); armTimeout(id, item);
          try { handler.postMessage({id, action, ...payload}); }
          catch (_) {
            pending.delete(id);
            timers.clearTimeout(item.timer);
            reject(new Error("앱에 요청을 전달하지 못했습니다."));
          }
        });
      },
      subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
      suspend() { active = false; rejectPending("설정 화면이 숨겨졌습니다."); },
      resume() { if (!disposed) active = true; },
      dispose() {
        if (disposed) return;
        disposed = true;
        active = false;
        rejectPending("설정 화면이 닫혔습니다.");
        listeners.clear();
        if (scope.idolyServerReply === reply) delete scope.idolyServerReply;
        if (scope.idolyServerEvent === event) delete scope.idolyServerEvent;
      }
    };
  }

  function formatBytes(value) {
    const bytes = typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
    if (bytes < 1024) return Math.floor(bytes) + " B";
    const exponent = Math.min(3, Math.floor(Math.log(bytes) / Math.log(1024)));
    return (bytes / Math.pow(1024, exponent)).toFixed(1) + " " + ["B", "KB", "MB", "GB"][exponent];
  }

  function createSettingsApp(scope, document, timers = scope) {
    const bridge = createBridge(scope, timers);
    const elements = new Map();
    const el = id => {
      if (!elements.has(id)) elements.set(id, document.getElementById(id));
      return elements.get(id);
    };
    let interfaceChoice = "system";
    let interfaceDirty = false;
    let interfaceSelected = false;
    let interfaceVersion = 0;
    let interfaceOperation = null;
    let language = resolveInterfaceLanguage(interfaceChoice, scope.navigator);
    const t = value => translateUI(value, language);
    const text = (id, value, localize = true) => { el(id).textContent = localize ? t(value) : value; };
    const staticText = [];
    const staticAttributes = [];
    if (typeof document.createTreeWalker === "function" && document.body) {
      const walker = document.createTreeWalker(document.body, 4);
      let node;
      while ((node = walker.nextNode())) {
        const source = node.nodeValue.trim();
        const owner = node.parentElement;
        if (!source || !owner || ["SCRIPT", "STYLE"].includes(owner.tagName)) continue;
        const select = owner.tagName === "OPTION" ? owner.parentElement : null;
        if (select && ["language", "interface_language"].includes(select.id) && ["한국어", "日本語", "English"].includes(source)) continue;
        staticText.push({node, source, before: node.nodeValue.slice(0, node.nodeValue.indexOf(source)), after: node.nodeValue.slice(node.nodeValue.indexOf(source) + source.length)});
      }
      for (const node of document.querySelectorAll("[aria-label]")) staticAttributes.push({node, source: node.getAttribute("aria-label")});
    }
    const title = document.title;
    function applyInterfaceLanguage(value) {
      interfaceChoice = choice(value, INTERFACE_LANGUAGES) ? value : "system";
      language = resolveInterfaceLanguage(interfaceChoice, scope.navigator);
      el("interface_language").value = interfaceChoice;
      if (document.documentElement) document.documentElement.lang = language;
      if (typeof title === "string") document.title = t(title);
      for (const entry of staticText) entry.node.nodeValue = entry.before + t(entry.source) + entry.after;
      for (const entry of staticAttributes) entry.node.setAttribute("aria-label", t(entry.source));
      if (messageSource) text("message", messageSource);
      if (copyFeedbackSource) text("diagnostics-copy-feedback", copyFeedbackSource);
      for (const name of Object.keys(forms)) renderSaveFeedback(name);
      if (accountSnapshot) renderAccounts(accountSnapshot);
      renderAccountPreview(); accountFeedback(accountFeedbackSource,accountFeedbackDetail);
      if (snapshot) renderServerChecks(snapshot.runtime);
      renderOfficial(); renderEvents(false);
      renderMP4();
    }
    const categoryNames = ["console","server","users","content","graphics"];
    const panelDefaults = {diagnostics:false,options:true,accounts:false,official:false,events:false,graphics:true,playback:true,media:true,resources:false,mp4:true};
    const layoutKey = "idoly.settings.layout.v1";
    let selectedCategory = "console";
    function setAttribute(node,name,value) { if (typeof node.setAttribute === "function") node.setAttribute(name,String(value)); else node[name] = String(value); }
    function saveLayout() {
      try {
        const panels = {}; for (const key of Object.keys(panelDefaults)) panels[key] = el("panel-"+key).open === true;
        scope.localStorage.setItem(layoutKey,JSON.stringify({schema:1,category:selectedCategory,panels}));
      } catch (_) { /* Some container WebViews do not expose local storage. */ }
    }
    function selectCategory(key, focus = false) {
      if (!categoryNames.includes(key)) return;
      selectedCategory = key;
      for (const name of categoryNames) {
        const selected = name === key, button = el("category-"+name);
        setAttribute(button,"aria-selected",selected); button.tabIndex = selected ? 0 : -1;
        el("category-panel-"+name).hidden = !selected;
      }
      if (focus && typeof el("category-"+key).focus === "function") el("category-"+key).focus();
      saveLayout();
      if (key === "graphics") Promise.resolve().then(() => { loadMP4Options();mp4("status");mp4Queue("status"); });
    }
    function initializeLayout() {
      let stored = null;
      try { const raw = scope.localStorage.getItem(layoutKey); if (typeof raw === "string" && raw.length <= 4096) stored = JSON.parse(raw); } catch (_) {}
      const valid = object(stored) && stored.schema === 1;
      for (const [key,fallback] of Object.entries(panelDefaults)) {
        const panel = el("panel-"+key);
        panel.open = valid && object(stored.panels) && typeof stored.panels[key] === "boolean" ? stored.panels[key] : fallback;
        panel.addEventListener("toggle",saveLayout);
      }
      for (const key of categoryNames) {
        const button = el("category-"+key);
        button.addEventListener("click",() => selectCategory(key));
        button.addEventListener("keydown",event => {
          let index = categoryNames.indexOf(key);
          if (["ArrowRight","ArrowDown"].includes(event.key)) index = (index+1)%categoryNames.length;
          else if (["ArrowLeft","ArrowUp"].includes(event.key)) index = (index+categoryNames.length-1)%categoryNames.length;
          else if (event.key === "Home") index = 0;
          else if (event.key === "End") index = categoryNames.length-1;
          else return;
          event.preventDefault(); selectCategory(categoryNames[index],true);
        });
      }
      selectCategory(valid && categoryNames.includes(stored.category) ? stored.category : "console");
    }
    function syncPreset(key) {
      const presets = key === "render_scale" ? SCALE_PRESETS : BUFFER_PRESETS;
      const value = Number(el(key).value);
      el(key + "_preset").value = el(key).value.trim() && presets.includes(value) ? String(value) : "custom";
    }
    let eventMode = "normal", eventModeSelected = false, eventModeLoading = false, eventModeGeneration = 0;
    const forms = {
      options: {fields: ["media_mode", "download_missing_resources", "language"], valid: validOptions},
      presentation: {fields: ["custom_graphics", "quality", "target_fps", "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"], valid: validPresentation},
      playback: {fields: ["wait_for_orientation"], valid: validPlayback},
      media: {fields: ["hide_video_mv", "mv_sort", "outfit_sort"], valid: validMedia},
      events: {fields: [], valid: value => validEvents(value, eventMode === "media"), available: false, draft: null, intents: new Map(), intentVersions: new Map(), intentSequence: 0, rebaseAttempts: 0, rebaseNeeded: false}
    };
    let snapshot = null;
    let mp4Status = {phase:"idle",ready:false}, mp4Pending = false, mp4Mutating = false, mp4Feedback = "";
    let mp4QueueStatus = {available:false,running:false,phase:"idle",jobs:[]}, mp4QueuePending = false, mp4QueueFeedback = "", mp4QueueRowsKey = "";
    let mp4OptionBase = {...MP4_OPTION_DEFAULTS}, mp4OptionsLoaded = false, mp4OptionsLoading = false, mp4OptionsVersion = 0, mp4OptionsError = "";
    const mp4EditedOptions = new Set(), mp4SavingOptions = new Set();
    const mp4OptionFields = {"mp4-fps":"fps","mp4-codec":"video_codec","mp4-bitrate-mode":"bitrate_mode","mp4-bitrate":"video_bitrate","mp4-resolution-mode":"resolution_mode","mp4-width":"width","mp4-height":"height"};
    let visible = document.visibilityState !== "hidden";
    let disposed = false;
    let pollTimer = null;
    let refreshing = false;
    let mutationVersion = 0;
    let visibilityVersion = 0;
    let launchFlushing = false;
    let flushNonce = null;
    let flushGeneration = 0;
    let accountSnapshot = null, accountPreview = null, accountPending = false, accountProgress = null, accountRequested = false, historyPending = false;
    let officialJob = null, officialPending = false, officialFeedbackSource = "", officialWarnings = [];
    const officialBusy = () => Boolean(officialJob && officialJob.busy === true);
    let accountFeedbackSource = "", accountFeedbackDetail = "";
    let resourcePending = false;
    let importProgress = null;
    let latestImportRequestID = 0;
    let copyPending = false;
    let copyFeedbackSource = "";
    let job = null;
    const logs = [];
    let messageSource = "";
    let eventSnapshot = null, eventRows = [], eventCatalogKey = "";

    function mp4DraftOptions() {
      const value = {...mp4OptionBase,fps:Number(el("mp4-fps").value),video_codec:Number(el("mp4-codec").value),
        bitrate_mode:el("mp4-bitrate-mode").value,resolution_mode:el("mp4-resolution-mode").value};
      const bitrateText = el("mp4-bitrate").value.trim(), widthText = el("mp4-width").value.trim(), heightText = el("mp4-height").value.trim();
      const bitrate = /^\d+(?:\.\d{1,6})?$/.test(bitrateText) ? Math.round(Number(bitrateText)*1000000) : NaN;
      const width = /^\d+$/.test(widthText) ? Number(widthText) : NaN, height = /^\d+$/.test(heightText) ? Number(heightText) : NaN;
      const validBitrate = integer(bitrate) && bitrate >= 100000 && bitrate <= 200000000;
      if (validBitrate) value.video_bitrate = bitrate;
      if (mp4Dimension(width)) value.width = width;
      if (mp4Dimension(height)) value.height = height;
      const error = value.bitrate_mode === "custom" && !validBitrate ? "비트레이트는 0.1~200 Mbps로 입력해 주세요."
        : value.resolution_mode === "custom" && (!mp4Dimension(width) || !mp4Dimension(height)) ? "가로·세로는 16~4096의 짝수 픽셀로 입력해 주세요."
        : !validMP4ExportOptions(value) ? "입력값의 범위를 확인해 주세요. 유효한 값만 자동으로 저장합니다." : "";
      return {options:value,error,validBitrate,validWidth:mp4Dimension(width),validHeight:mp4Dimension(height)};
    }
    function applyMP4Options(options, preserveEdits = false) {
      mp4OptionBase = {...options};
      for (const [id,key] of Object.entries(mp4OptionFields)) {
        if (!preserveEdits || !mp4EditedOptions.has(key)) el(id).value = String(key === "video_bitrate" ? options[key]/1000000 : options[key]);
      }
    }
    function renderMP4Options() {
      const draft = mp4DraftOptions(), options = draft.options;
      el("mp4-dimensions").hidden = options.resolution_mode !== "custom";
      el("mp4-custom-bitrate").hidden = options.bitrate_mode !== "custom";
      setAttribute(el("mp4-bitrate"),"aria-invalid",options.bitrate_mode === "custom" && !draft.validBitrate);
      setAttribute(el("mp4-width"),"aria-invalid",options.resolution_mode === "custom" && !draft.validWidth);
      setAttribute(el("mp4-height"),"aria-invalid",options.resolution_mode === "custom" && !draft.validHeight);
      let width = options.resolution_mode === "custom" ? draft.validWidth && options.width : integer(mp4Status.source_width) ? mp4Status.source_width : mp4Status.width;
      let height = options.resolution_mode === "custom" ? draft.validHeight && options.height : integer(mp4Status.source_height) ? mp4Status.source_height : mp4Status.height;
      const bitrate = recommendedMP4Bitrate(width,height,options.fps,options.video_codec);
      if (bitrate !== null) {width -= width % 2;height -= height % 2;}
      text("mp4-recommendation",bitrate === null ? t("MV가 준비되면 권장값을 표시합니다.") : t("권장 비트레이트")+" · "+(bitrate/1000000).toFixed(2)+" Mbps · "+width+" × "+height,false);
      text("mp4-options-feedback",draft.error || mp4OptionsError || (!mp4OptionsLoaded ? "MP4 설정 확인 중…" : mp4SavingOptions.size ? "저장 중…" : ""));
      return !draft.error;
    }
    function saveMP4Options() {
      const draft = mp4DraftOptions();
      if (!mp4OptionsLoaded || draft.error || disposed || !visible) { renderMP4();return; }
      const version = mp4OptionsVersion, options = {...draft.options};
      mp4OptionBase = options;mp4SavingOptions.add(version);mp4OptionsError = "";renderMP4();
      bridge.request("mp4_options_save",{options}).then(result => {
        if (!object(result) || !validMP4ExportOptions(result.options)) throw new Error("mp4_options_invalid");
        if (version === mp4OptionsVersion) mp4OptionsError = "";
      }).catch(() => {
        if (!disposed && visible && version === mp4OptionsVersion) mp4OptionsError = "MP4 설정을 저장하지 못했습니다. 값을 바꾸면 다시 저장합니다.";
      }).finally(() => {mp4SavingOptions.delete(version);if (!disposed) renderMP4();});
    }
    async function loadMP4Options() {
      if (mp4OptionsLoaded || mp4OptionsLoading || disposed || !visible) return;
      mp4OptionsLoading = true;
      try {
        const result = await bridge.request("mp4_options");
        if (disposed) return;
        if (!object(result) || !validMP4ExportOptions(result.options)) throw new Error("mp4_options_invalid");
        applyMP4Options(result.options,true);mp4OptionsError = "";
      } catch (_) {if (!disposed && visible) mp4OptionsError = "MP4 설정을 불러오지 못했습니다.";}
      finally {
        // Hiding the page rejects bridge promises. Retry that unfinished read
        // when shown rather than treating in-memory defaults as loaded prefs.
        mp4OptionsLoading = false;mp4OptionsLoaded = visible;
        if (!disposed) {if (mp4EditedOptions.size) saveMP4Options();else renderMP4();}
      }
    }
    function mp4ExportPayload() {
      const draft = mp4DraftOptions();if (draft.error) {renderMP4();return null;}
      const options = draft.options;
      return {fps:options.fps,video_codec:options.video_codec,video_bitrate:options.bitrate_mode === "recommended" ? 0 : options.video_bitrate,
        width:options.resolution_mode === "current" ? 0 : options.width,height:options.resolution_mode === "current" ? 0 : options.height};
    }
    function renderMP4() {
      const validOptions = renderMP4Options();
      const phase = mp4Status.phase, paused = phase === "paused" || phase === "pausing", active = ["preparing_audio","rendering","finishing","cancelling","pausing","paused"].includes(phase);
      const queuedOutput = Boolean(mp4Status.export_id) && mp4QueueStatus.jobs.some(job => job.output_id === mp4Status.export_id);
      const queueOwnsScene = mp4QueueStatus.running === true || mp4QueueStatus.paused === true || Boolean(mp4QueueStatus.current_job_id);
      const label = {idle:"3D MV 준비 대기",preparing_audio:"음원 준비 중",rendering:"MP4 렌더링",finishing:"MP4 마무리 중",completed:"MP4 완료",cancelling:"취소 중",cancelled:"취소됨",failed:"MP4 실패",pausing:"MP4 일시 정지 중…",paused:"MP4 일시 정지"}[phase] || "3D MV 준비 대기";
      const frames = count(mp4Status.frames), total = count(mp4Status.total_frames);
      const geometry = integer(mp4Status.width) && integer(mp4Status.height) && mp4Status.width && mp4Status.height ? " · "+mp4Status.width+" × "+mp4Status.height : "";
      text("mp4-summary",t(label)+(total ? " · "+frames+" / "+total : "")+geometry,false);
      const pauseHint = mp4Status.pause_reason === "lifecycle_background" ? "앱으로 돌아오면 이어서 처리합니다."
        : mp4Status.pause_reason === "surface_unavailable" ? "게임 화면이 준비되면 계속할 수 있습니다." : "계속하기를 누르면 이어서 처리합니다.";
      text("mp4-feedback",mp4Feedback ? t(mp4Feedback) : paused ? t(pauseHint) : phase === "failed" ? plain(mp4Status.error_code,128) : "",false);
      el("mp4-progress").hidden = !active && phase !== "completed";
      el("mp4-progress").value = total ? Math.min(1,frames/total) : 0;
      el("mp4-fields").disabled = !mp4OptionsLoaded || mp4Mutating || active;
      el("mp4-start").disabled = !mp4OptionsLoaded || !validOptions || mp4Pending || active || queueOwnsScene || mp4Status.ready !== true || launchFlushing;
      el("mp4-cancel").disabled = mp4Pending || !active || phase === "cancelling";
      el("mp4-cancel").hidden = queuedOutput;
      el("mp4-pause").hidden = queuedOutput || !["preparing_audio","rendering"].includes(phase);
      el("mp4-pause").disabled = mp4Pending;
      el("mp4-resume").hidden = queuedOutput || phase !== "paused";
      el("mp4-resume").disabled = mp4Pending;
      el("mp4-save").hidden = queuedOutput || phase !== "completed";
      el("mp4-save").disabled = mp4Pending;
      renderMP4Queue();
    }
    function renderMP4Queue() {
      const q = mp4QueueStatus, jobs = q.jobs, pending = jobs.filter(job => job.state === "pending").length;
      const locked = mp4QueuePending || q.command_pending === true || launchFlushing;
      const paused = q.phase === "paused";
      text("mp4-queue-summary",jobs.length ? t(paused ? "큐 일시 정지" : q.running ? "큐 실행 중" : "작업 목록")+" · "+jobs.length+" / 8" : t("등록한 작업이 없습니다."),false);
      text("mp4-queue-feedback",mp4QueueFeedback ? t(mp4QueueFeedback) : q.error_code && q.error_code !== "none" ? plain(q.error_code,128) : "",false);
      el("mp4-enqueue").disabled = !mp4OptionsLoaded || Boolean(mp4DraftOptions().error) || locked || q.available !== true || q.running === true || jobs.length >= 8 || mp4Status.ready !== true;
      el("mp4-queue-run").disabled = locked || q.available !== true || q.can_run !== true || q.running === true || !pending;
      el("mp4-queue-pause").hidden = q.running !== true || paused;
      el("mp4-queue-pause").disabled = locked;
      el("mp4-queue-resume").hidden = !paused;
      el("mp4-queue-resume").disabled = locked;
      const rowsKey = JSON.stringify([jobs,locked,interfaceChoice]);
      if (rowsKey === mp4QueueRowsKey) return;
      mp4QueueRowsKey = rowsKey;
      const labels = {pending:"대기",running:"내보내는 중",paused:"일시 정지",completed:"완료",failed:"실패",cancelled:"취소됨",interrupted:"중단됨 · 다시 시도 가능"};
      const rows = jobs.map((job,index) => {
        const item = document.createElement("li"); item.className = "mp4-job";
        const title = document.createElement("h3"); title.className = "mp4-job-title";
        const titles = object(job.title_localizations) ? job.title_localizations : {};
        title.textContent = (index+1)+". "+(plain(titles[language] || job.title,192) || "MV "+(index+1));
        const info = document.createElement("p"); info.className = "hint";
        info.textContent = t(labels[job.state])+" · "+count(job.actor_count)+" "+t("명")+" · "+count(job.fps_num)+" fps · "+count(job.width)+" × "+count(job.height);
        const controls = document.createElement("div"); controls.className = "actions";
        const buttons = [];
        function button(label,action,payload) { const node = document.createElement("button"); node.type = "button"; node.className = "secondary"; node.textContent = t(label); node.disabled = locked; node.addEventListener("click",() => mp4Queue(action,payload)); buttons.push(node); }
        if (job.state === "completed") button("저장·공유","save",{job_id:job.job_id});
        if (["failed","cancelled","interrupted"].includes(job.state)) button("다시 시도","retry",{job_id:job.job_id});
        if (["pending","running","paused"].includes(job.state)) button("취소","cancel",{job_id:job.job_id});
        if (job.state === "pending") {
          if (index > 0) button("위로","move",{job_id:job.job_id,position:index-1});
          if (index+1 < jobs.length) button("아래로","move",{job_id:job.job_id,position:index+1});
        }
        if (job.state === "completed") {
          const remove = document.createElement("button"); remove.type = "button"; remove.className = "secondary danger";
          remove.textContent = t("파일·작업 삭제"); remove.disabled = locked;
          let confirmUntil = 0;
          remove.addEventListener("click",() => {
            if (Date.now() < confirmUntil) { mp4Queue("remove",{job_id:job.job_id,delete_output:true}); return; }
            confirmUntil = Date.now()+5000; remove.textContent = t("삭제 확인");
            error.textContent = t("보관 중인 MP4와 작업을 삭제합니다. 외부에 저장한 파일은 유지됩니다.");
          }); buttons.push(remove);
        } else if (!["running","paused"].includes(job.state)) button("목록에서 제거","remove",{job_id:job.job_id});
        controls.replaceChildren(...buttons);
        const error = document.createElement("p"); error.className = "hint";
        error.textContent = job.error_code && job.error_code !== "none" ? plain(job.error_code,128) : "";
        item.replaceChildren(title,info,controls,error); return item;
      });
      el("mp4-queue-jobs").replaceChildren(...rows);
    }
    async function mp4Queue(action,payload) {
      if (!visible || disposed || mp4QueuePending || launchFlushing) return;
      if (action === "status" && (selectedCategory !== "graphics" || !el("panel-mp4").open)) return;
      if (action !== "status" && mp4QueueStatus.command_pending === true) return;
      if (action === "enqueue") {payload = mp4ExportPayload();if (!payload) return;}
      const command = action === "enqueue" ? "mp4_enqueue" : action === "save" ? "mp4_save" : "mp4_queue_"+action;
      payload = payload || {};
      if (!validRequest(command,payload)) return;
      mp4QueuePending = true; renderMP4Queue(); const visibility = visibilityVersion;
      try {
        const result = await bridge.request(command,payload);
        if (!visible || disposed || visibility !== visibilityVersion) return;
        if (action !== "save") {
          const states = ["pending","running","paused","completed","failed","cancelled","interrupted"];
          if (!object(result) || !Array.isArray(result.jobs) || result.jobs.length > 8 || result.jobs.some(job => !object(job) || !/^[0-9a-f]{32}$/.test(job.job_id) || !states.includes(job.state))) throw new Error("mp4_unavailable");
          mp4QueueStatus = result;
        }
        mp4QueueFeedback = "";
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion && action !== "status") mp4QueueFeedback = "MP4 작업을 처리하지 못했습니다. 다시 시도해 주세요.";
      } finally { mp4QueuePending = false; if (!disposed) renderMP4(); }
    }
    async function mp4(action) {
      if (!visible || disposed || mp4Pending || launchFlushing) return;
      if (action === "status" && (selectedCategory !== "graphics" || !el("panel-mp4").open)) return;
      const payload = action === "start" ? mp4ExportPayload() : {};
      if (!payload) return;
      if (!validRequest("mp4_"+action,payload)) return;
      mp4Pending = true;mp4Mutating = action !== "status";renderMP4();const visibility = visibilityVersion;
      try {
        const result = await bridge.request("mp4_"+action,payload);
        if (!visible || disposed || visibility !== visibilityVersion) return;
        if (action !== "save") {
          if (!object(result) || !["idle","preparing_audio","rendering","finishing","completed","cancelling","cancelled","failed","pausing","paused"].includes(result.phase)) throw new Error("mp4_unavailable");
          mp4Status = result;
        }
        mp4Feedback = "";
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion && action !== "status")
          mp4Feedback = error.code === "mp4_scene_not_ready" ? "3D MV 재생 화면에서 다시 시도해 주세요." : error.code === "mp4_busy" ? "다른 MP4 작업을 마친 뒤 다시 시도해 주세요." : "MP4 기능을 사용할 수 없습니다.";
      } finally {
        mp4Pending = false;mp4Mutating = false;if (!disposed) renderMP4();
      }
    }

    function eventLocalTime(milliseconds) {
      const date = new Date(milliseconds);
      if (!Number.isFinite(date.getTime())) return "";
      return new Date(milliseconds - date.getTimezoneOffset() * 60000).toISOString().slice(0,16);
    }
    function eventTimeValue(value) { return value ? new Date(value).getTime() : NaN; }
    function eventTitle(row) {
      return object(row.titles) && typeof row.titles[language] === "string" ? plain(row.titles[language], 256) : plain(row.title,256) || row.id;
    }
    function mergedEventDraft(settings, intents) {
      const rows = new Map(settings.love_events.map(row => [row.event_id, {...row}]));
      for (const [id, value] of intents) { if (value === null) rows.delete(id); else rows.set(id, {...value}); }
      return {...settings,love_events:[...rows.values()].sort((a,b) => a.event_id < b.event_id ? -1 : a.event_id > b.event_id ? 1 : 0)};
    }
    function renderEvents(syncFields = false) {
      const form = forms.events, value = eventSnapshot;
      const rows = value && object(value.catalog) && value.catalog.available === true && Array.isArray(value.catalog.events)
        ? value.catalog.events.filter(row => object(row) && row.supported === true && typeof row.id === "string"
          && /^[A-Za-z0-9_-]{1,96}$/.test(row.id)).slice(0,64) : [];
      eventRows = rows;
      form.available = Boolean(value && form.valid(value.saved) && rows.length && value.invalid_settings_file !== true);
      const selector = el("events-choice"), chosen = selector.value;
      const key = JSON.stringify([language, rows.map(row => [row.id,eventTitle(row)])]);
      if (key !== eventCatalogKey) {
        eventCatalogKey = key;
        const options = rows.map(row => { const option = document.createElement("option"); option.value = row.id; option.textContent = eventTitle(row); return option; });
        if (!options.length) { const option = document.createElement("option"); option.value = ""; option.textContent = t("지원 목록 없음"); options.push(option); }
        selector.replaceChildren(...options);
        selector.value = rows.some(row => row.id === chosen) ? chosen : rows.length ? rows[0].id : "";
        const cards = rows.map(row => {
          const label = document.createElement("label"); label.className = "event-card";
          const input = document.createElement("input"); input.type = "checkbox"; input.value = row.id;
          input.addEventListener("change", () => editEventEnabled(row.id,input.checked));
          const title = document.createElement("span"); title.textContent = eventTitle(row);
          if (row.id === "love-extra-25-0426") {
            const caption = document.createElement("span"); caption.textContent = eventTitle(row);
            const entry = document.createElement("small"); entry.className = "event-entry";
            entry.textContent = t("게임 홈 → 이벤트 → 사큐×마호"); title.replaceChildren(caption,entry);
          }
          label.replaceChildren(input,title); label.eventInput = input;
          return label;
        });
        el("events-list").replaceChildren(...cards);
        syncFields = true;
      }
      const draft = form.draft || form.value;
      const selected = draft && Array.isArray(draft.love_events) ? draft.love_events.find(row => row.event_id === selector.value) : null;
      if (syncFields) {
        el("events-enabled").checked = Boolean(selected);
        el("events-start").value = selected && eventMode !== "media" ? eventLocalTime(selected.start_time_ms) : "";
        el("events-end").value = selected && eventMode !== "media" ? eventLocalTime(selected.end_time_ms) : "";
      }
      const disabled = launchFlushing || eventModeLoading || !form.available || !snapshot || !snapshot.running || snapshot.state !== "ready";
      el("events-fields").disabled = disabled;
      el("events-mode").value = eventMode;
      el("events-mode").disabled = launchFlushing || eventModeLoading;
      for (const card of Array.from(el("events-list").children || [])) {
        const input = card.eventInput; if (!input) continue;
        input.checked = Boolean(draft && draft.love_events.some(row => row.event_id === input.value));
        input.disabled = disabled;
      }
      el("events-period-editor").hidden = eventMode === "media";
      el("events-period-hint").hidden = eventMode === "media";
      el("events-media-policy").hidden = eventMode !== "media";
      const list = settings => form.valid(settings) && settings.love_events.length ? settings.love_events.map(row => {
        const match = rows.find(item => item.id === row.event_id); return match ? eventTitle(match) : row.event_id;
      }).join(", ") : t("없음");
      text("events-effective", value && form.valid(value.effective) ? t("현재 적용: ") + value.effective.love_events.length : t("현재 적용: 대기"), false);
      text("events-next", value && form.valid(value.saved) ? t("다음 실행: ") + value.saved.love_events.length : t("다음 실행: 대기"), false);
      setAttribute(el("events-effective"),"title",value && form.valid(value.effective) ? list(value.effective) : "");
      setAttribute(el("events-next"),"title",value && form.valid(value.saved) ? list(value.saved) : "");
      text("events-state", !form.available ? "지원 목록 없음" : value.restart_required === true ? "적용 대기" : "준비 완료");
      const detail = !value ? "이벤트 설정을 아직 불러오지 못했습니다." : value.invalid_settings_file === true ? "이벤트 설정 파일을 읽지 못했습니다. 자동으로 덮어쓰지 않습니다."
        : !form.available ? "지원 목록을 확인할 수 없어 이벤트 설정을 변경할 수 없습니다." : value.restart_required === true ? "저장한 이벤트 설정은 다음 서버 시작에 적용됩니다. 게임을 이미 시작했다면 앱을 완전히 종료하고 다시 열어 주세요." : "현재 서버와 저장된 이벤트 설정이 같습니다.";
      let message = t(detail);
      const active = value && form.valid(value.effective) ? value.effective.love_events.find(row => row.event_id === selector.value) : null;
      if (active && eventMode !== "media") message += "\n" + t("현재 선택 이벤트 적용 기간: ") + eventLocalTime(active.start_time_ms).replace("T"," ") + " – " + eventLocalTime(active.end_time_ms).replace("T"," ");
      text("events-detail", message, false);
    }
    function rememberEvent(id, row) {
      const form = forms.events;
      form.intents.set(id, row === null ? null : {...row});
      form.intentVersions.set(id,++form.intentSequence);
      form.draft = mergedEventDraft(form.draft, new Map([[id,row]]));
    }
    function defaultEventWindow() {
      if (eventMode === "media") return {start_time_ms:0,end_time_ms:0};
      const start = Math.floor(Date.now() / 60000) * 60000;
      return {start_time_ms:start,end_time_ms:start+30*86400000};
    }
    function editEventEnabled(id, enabled, delay = 180) {
      const form = forms.events;
      if (!form.available || launchFlushing || !form.value || !form.draft || !eventRows.some(row => row.id === id)) return;
      const current = form.draft.love_events.find(row => row.event_id === id);
      rememberEvent(id, enabled ? current || {event_id:id,...defaultEventWindow()} : null);
      renderEvents(true); markEdited("events", delay);
    }
    function editAllEvents(enabled) {
      const form = forms.events;
      if (!form.available || launchFlushing || !form.value || !form.draft) return;
      for (const row of eventRows) {
        const current = form.draft.love_events.find(entry => entry.event_id === row.id);
        rememberEvent(row.id, enabled ? current || {event_id:row.id,...defaultEventWindow()} : null);
      }
      renderEvents(true); markEdited("events", 0);
    }
    function editEvent() {
      const form = forms.events;
      if (!form.available || launchFlushing || !form.value || !form.draft) return;
      const id = el("events-choice").value;
      if (!eventRows.some(row => row.id === id)) return;
      let row = null;
      if (el("events-enabled").checked) {
        if (eventMode === "media") row = {event_id:id,start_time_ms:0,end_time_ms:0};
        else {
          if (!el("events-start").value && !el("events-end").value) {
            const initial = defaultEventWindow(); el("events-start").value = eventLocalTime(initial.start_time_ms); el("events-end").value = eventLocalTime(initial.end_time_ms);
          }
          row = {event_id:id,start_time_ms:eventTimeValue(el("events-start").value),end_time_ms:eventTimeValue(el("events-end").value)};
        }
      }
      rememberEvent(id,row); renderEvents(false); markEdited("events", 0);
    }
    async function refreshEventSettings() {
      const mode = eventMode, generation = eventModeGeneration;
      try {
        const value = await bridge.request("events_status",{mode});
        if (disposed || !visible || generation !== eventModeGeneration || mode !== eventMode) return;
        if (!object(value) || value.media_mode !== (mode === "media") || !validEvents(value.saved,mode === "media")) throw new Error("서버 상태 형식을 확인하지 못했습니다.");
        eventSnapshot = value; updateForm("events",value.saved,true);
      } catch (_) {
        forms.events.rebaseNeeded = false;
        if (!disposed && visible) saveFeedback("events","failed","설정을 저장하지 못했습니다. 다시 시도를 눌러 주세요.");
      }
    }
    async function switchEventMode(mode) {
      if (!["normal","media"].includes(mode) || launchFlushing || eventModeLoading) return;
      if (mode === eventMode) return;
      const generation = ++eventModeGeneration, form = forms.events;
      for (let attempt = 0; attempt < MAX_PENDING && (form.busy || form.dirty); attempt++) {
        const saved = form.busy ? await form.inflight : await save("events", true);
        if (!saved || disposed || !visible || generation !== eventModeGeneration) { el("events-mode").value = eventMode; return; }
      }
      if (form.busy || form.dirty) { el("events-mode").value = eventMode; return; }
      eventModeLoading = true; renderEvents(false);
      try {
        const result = await bridge.request("events_status", {mode});
        if (disposed || !visible || generation !== eventModeGeneration) return;
        if (!object(result) || result.media_mode !== (mode === "media") || !validEvents(result.saved,mode === "media")) throw new Error("서버 상태 형식을 확인하지 못했습니다.");
        eventMode = mode; eventModeSelected = true; eventSnapshot = result; eventCatalogKey = "";
        form.value = null; form.draft = null; form.dirty = false; form.intents.clear(); form.intentVersions.clear(); form.rebaseAttempts = 0;
        updateForm("events",result.saved);
      } catch (error) { if (visible && !disposed) message(error.message,true); }
      finally { eventModeLoading = false; if (!disposed) renderEvents(true); }
    }

    function message(value, error = false) {
      messageSource = plain(value, 500);
      text("message", messageSource);
      el("message").hidden = !value;
      el("message").dataset.error = String(error);
    }
    function updateCopyButton() {
      el("diagnostics-copy").disabled = copyPending || !el("diagnostics").textContent;
    }
    function copyFeedback(value, error = false) {
      copyFeedbackSource = value;
      text("diagnostics-copy-feedback", value);
      el("diagnostics-copy-feedback").hidden = !value;
      el("diagnostics-copy-feedback").dataset.error = String(error);
    }
    async function copyDiagnostics() {
      if (!visible || disposed || copyPending || !el("diagnostics").textContent) return;
      const value = el("diagnostics").textContent;
      copyPending = true; updateCopyButton(); copyFeedback("");
      try {
        const result = await bridge.request("diagnostics_copy", {text: value});
        if (!visible || disposed) return;
        if (result.copied === true) copyFeedback("진단을 복사했습니다.");
        else copyFeedback("진단을 복사하지 못했습니다. 다시 시도해 주세요.", true);
      } catch (_) {
        if (visible && !disposed) copyFeedback("진단을 복사하지 못했습니다. 다시 시도해 주세요.", true);
      } finally {
        copyPending = false;
        if (!disposed) updateCopyButton();
      }
    }
    function updateForm(name, settings, eventRebase = false) {
      const form = forms[name];
      if (!form.valid(settings)) {
        el(name + "-fields").disabled = launchFlushing || !form.value || !snapshot.running || snapshot.state !== "ready" || (name === "events" && !form.available);
        renderSaveFeedback(name);
        return;
      }
      if (name === "events" && form.value && settings.revision < form.value.revision) return;
      settings = name === "options" ? {interface_language: "system", ...settings} : settings;
      form.value = {...settings};
      if (name === "events") {
        const sync = !form.dirty && !form.busy;
        if (sync || (!form.busy && form.intents.size)) form.draft = mergedEventDraft(settings,form.intents);
        if (sync || (form.rebaseNeeded && eventRebase)) form.fingerprint = JSON.stringify(form.draft.love_events);
        const retry = eventRebase && form.rebaseNeeded && !form.busy && form.rebaseAttempts <= 2;
        if (eventRebase) form.rebaseNeeded = false;
        renderEvents(sync); renderSaveFeedback(name);
        if (retry && form.dirty) queueSave(name,180);
        return;
      }
      if (!form.dirty && !form.busy) {
        for (const key of form.fields) {
          const input = el(key);
          if (input.type === "checkbox") input.checked = settings[key];
          else input.value = String(settings[key]);
        }
      }
      if (name === "presentation" && !form.dirty && !form.busy) for (const key of ["render_scale", "max_buffer_pixel"]) syncPreset(key);
      if (!form.dirty && !form.busy) form.fingerprint = formFingerprint(name);
      el(name + "-fields").disabled = launchFlushing || !snapshot.running || snapshot.state !== "ready";
      renderSaveFeedback(name);
    }
    function settingsFromForm(name) {
      const form = forms[name];
      if (!form.value) throw new Error("설정을 먼저 불러와 주세요.");
      if (name === "events") {
        const value = {...form.draft,revision:form.value.revision};
        if (!form.available || !form.valid(value) || value.love_events.some(row => !eventRows.some(item => item.id === row.event_id))) throw new Error("설정 값의 범위를 확인해 주세요.");
        return value;
      }
      const value = name === "options" ? {interface_language: interfaceChoice} : {...form.value};
      for (const key of form.fields) {
        const input = el(key);
        value[key] = input.type === "checkbox" ? input.checked : typeof form.value[key] === "number" ? (input.value.trim() === "" ? NaN : Number(input.value)) : input.value;
      }
      if (!form.valid(value)) throw new Error("설정 값의 범위를 확인해 주세요.");
      return value;
    }
    function formFingerprint(name) {
      if (name === "events") return JSON.stringify(forms.events.draft && forms.events.draft.love_events);
      return JSON.stringify(forms[name].fields.map(key => el(key).type === "checkbox" ? el(key).checked : el(key).value));
    }
    function clearAutosave(name) {
      const form = forms[name];
      if (form.autosaveTimer !== null) timers.clearTimeout(form.autosaveTimer);
      form.autosaveTimer = null;
    }
    function renderSaveFeedback(name) {
      const form = forms[name];
      text(name + "-save-feedback", form.feedback || "변경하면 자동으로 저장됩니다.");
      el(name + "-save-feedback").dataset.state = form.saveState || "ready";
      el(name + "-save-retry").hidden = form.saveState !== "failed";
      el(name + "-save-retry").disabled = launchFlushing || Boolean(form.busy) || !snapshot || !snapshot.running || snapshot.state !== "ready" || (name === "events" && !form.available);
    }
    function saveFeedback(name, state, value) {
      forms[name].saveState = state; forms[name].feedback = value;
      renderSaveFeedback(name);
    }
    function queueSave(name, delay = 0) {
      const form = forms[name];
      clearAutosave(name);
      if (!form.dirty || !visible || disposed) return;
      saveFeedback(name, "pending", "변경 사항을 저장할 준비가 되었습니다.");
      if (delay > 0) form.autosaveTimer = timers.setTimeout(() => {
        form.autosaveTimer = null; save(name);
      }, delay);
      else save(name);
    }
    function markEdited(name, delay = null) {
      if (disposed || launchFlushing) return;
      if (name === "events" && !forms.events.available) return;
      const form = forms[name], fingerprint = formFingerprint(name);
      if (form.fingerprint !== fingerprint) {
        form.fingerprint = fingerprint; form.editRevision++; form.dirty = true; mutationVersion++;
      }
      if (form.dirty && delay !== null) queueSave(name, delay);
    }
    function stopPolling() {
      if (pollTimer !== null) timers.clearTimeout(pollTimer);
      pollTimer = null;
    }
    function schedulePoll() {
      stopPolling();
      if (!visible || disposed) return;
      pollTimer = timers.setTimeout(() => { pollTimer = null; refresh(); }, (job && ACTIVE_JOBS.has(job.state)) || (importProgress && importProgress.stage === "queued") || officialBusy() ? 1000 : 4000);
    }
    function observeImportProgress(value) {
      if (!validImportProgress(value)) return;
      latestImportRequestID = Math.max(latestImportRequestID, value.request_id);
      if (!importProgress || (importProgress.request_id === null
          ? value.request_id <= importProgress.previous_request_id
          : value.request_id !== importProgress.request_id)) return;
      const order = {selecting: 0, preparing: 1, copying: 2, queued: 3, completed: 4, failed: 4};
      if (order[value.stage] < order[importProgress.stage] || value.copied_bytes < importProgress.copied_bytes) return;
      const advanced = value.stage !== importProgress.stage || value.copied_bytes > importProgress.copied_bytes;
      importProgress = {...importProgress, request_id: value.request_id, stage: value.stage,
        copied_bytes: value.copied_bytes, total_bytes: value.total_bytes};
      if (advanced && messageSource === "응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요.") message("");
    }
    function renderResources(runtime) {
      const library = object(runtime.resource_library) ? runtime.resource_library : {};
      const latestJob = object(library.job) ? library.job : null;
      const currentImport = importProgress && latestJob && latestJob.action === "import" && typeof latestJob.job_id === "string" && latestJob.job_id !== importProgress.previous_job_id;
      job = importProgress ? (importProgress.result_job || (currentImport ? latestJob : null)) : latestJob;
      if (importProgress && importProgress.accepted && object(snapshot.resource_operation)
          && snapshot.resource_operation !== importProgress.previous_operation) {
        if (snapshot.resource_operation.accepted === false) importProgress.stage = "failed";
        else if (snapshot.resource_operation.ready === true && currentImport) importProgress.stage = "completed";
      }
      const importStage = importProgress && importProgress.stage;
      const copyingImport = ["selecting", "preparing", "copying"].includes(importStage);
      const waitingImport = importStage === "queued" && !currentImport && !importProgress.result_job;
      const archivePending = !["completed", "failed"].includes(importStage) && object(snapshot.resource_operation) && snapshot.resource_operation.accepted === true && snapshot.resource_operation.ready === false;
      const activeJob = Boolean(job && ACTIVE_JOBS.has(job.state));
      const busy = activeJob || archivePending || copyingImport || waitingImport;
      const ready = Boolean(snapshot && snapshot.running && snapshot.state === "ready");
      for (const action of ["preview", "download", "import", "export"]) el("resources-" + action).disabled = !ready || busy || resourcePending || accountPending || officialPending || officialBusy();
      el("parallelism").disabled = busy || resourcePending || !ready;
      el("resources-cancel").disabled = !ready || !activeJob || resourcePending || !/^[A-Za-z0-9_-]{1,64}$/.test(job.job_id || "");
      const states = {preparing: "준비", running: "진행 중", export_ready: "내보내기 준비", cancelling: "취소 중", completed: "완료", partial: "일부 완료", failed: "실패", cancelled: "취소됨"};
      if (copyingImport || waitingImport || (importProgress && !job && ["failed", "completed"].includes(importStage))) {
        const labels = {selecting: "ZIP 선택 대기", preparing: "ZIP 준비 중", copying: "ZIP 복사 중", queued: "ZIP 검증 준비", failed: "실패", completed: "완료"};
        text("resource-state", labels[importStage] || "확인 중");
        const total = importProgress.total_bytes || 0, copied = importProgress.copied_bytes || 0;
        const progress = el("resource-progress");
        progress.hidden = importStage === "selecting" || importStage === "failed";
        progress.max = Math.max(1, total);
        if (total > 0 && importStage === "copying") progress.value = Math.min(copied, total);
        else if (importStage === "completed") { progress.max = 1; progress.value = 1; }
        else progress.removeAttribute("value");
        text("resource-summary", {selecting: "파일 앱에서 ZIP을 선택해 주세요.", preparing: "선택한 ZIP을 준비하고 있습니다. 파일 제공자의 다운로드가 필요할 수 있습니다.", copying: "ZIP을 앱 보관 폴더로 복사하고 있습니다.", queued: "복사를 마쳤습니다. ZIP 목록과 내용을 검증하고 있습니다.", failed: "ZIP 가져오기를 마치지 못했습니다.", completed: "ZIP 가져오기를 마쳤습니다."}[importStage]);
        text("resource-detail", importStage === "copying" ? formatBytes(copied) + (total > 0 ? " / " + formatBytes(total) + " · " + Math.floor(100 * copied / total) + "%" : "") : "");
        return;
      }
      text("resource-state", importStage === "failed" ? "실패" : archivePending && !activeJob ? "ZIP 준비 중" : job ? states[job.state] || "확인 중" : "대기");
      el("resource-progress").hidden = !job;
      if (job && !(archivePending && !activeJob && !currentImport)) {
        const total = count(job.total_files);
        const checked = count(job.verified_files);
        el("resource-progress").max = Math.max(1, total);
        el("resource-progress").value = Math.min(checked, total);
        const action = {download: "받기", import: "가져오기", export: "내보내기"}[job.action] || "작업";
        text("resource-summary", t(action) + t(" · 검증 ") + checked + "/" + total + t("개 · ") + formatBytes(job.verified_bytes) + " / " + formatBytes(job.total_bytes) + t("\n수신 ") + formatBytes(job.received_bytes) + t(" · 재사용 ") + count(job.cache_hit_files) + t("개 · 가져옴 ") + count(job.imported_files) + t("개\n실패 ") + count(job.failed_files) + t("개 · 미보관 ") + count(job.missing_files) + t("개"));
        const phases = object(job.phase_active_files) ? job.phase_active_files : {};
        const phaseText = [["connecting", "연결"], ["receiving", "받기"], ["checking", "검증"], ["saving", "저장"], ["copying", "복사"]].map(([key, title]) => t(title) + " " + count(phases[key])).join(" · ");
        const parallel = choice(job.parallelism, [1, 2, 4, 8]) ? t("동시 ") + job.parallelism + t("개 · ") : "";
        const elapsed = typeof job.elapsed_seconds === "number" && Number.isFinite(job.elapsed_seconds) && job.elapsed_seconds >= 0 ? Math.floor(job.elapsed_seconds) : 0;
        text("resource-detail", parallel + t("평균 ") + formatBytes(job.average_bytes_per_second) + "/s · " + elapsed + t("초\n") + phaseText + (job.error_code ? t("\n오류: ") + plain(job.error_code, 80) : ""));
      } else {
        const catalog = object(library.catalogs) && object(library.catalogs.ios) ? library.catalogs.ios : null;
        text("resource-summary", archivePending ? "ZIP 작업을 준비하고 있습니다." : catalog ? t("포함 목록 ") + count(catalog.object_count) + t("개 · ") + formatBytes(catalog.total_bytes) : ready ? "목록·용량 확인을 누르면 전체 예상 용량을 표시합니다." : "서버가 준비되면 리소스를 관리할 수 있습니다.");
        text("resource-detail", "");
      }
    }


    function renderAccountPreview() {
      el("accounts-preview-detail").hidden = !accountPreview;
      if (!accountPreview) return;
      const archive = accountPreview.archive;
      const lines = [
        t(archive.mode === "media" ? "감상 모드" : "일반 모드"),
        t("원본 저장 슬롯: ") + plain(archive.profile,64),
        t("계정 자료: ") + formatBytes(archive.bytes)
      ];
      const inventory = object(archive.inventory) ? archive.inventory : {};
      for (const [key,label] of [["cards","카드"],["items","아이템 종류"],["photos","포토"]])
        if (Number.isSafeInteger(inventory[key]) && inventory[key] >= 0) lines.push(t(label) + ": " + inventory[key]);
      if (typeof archive.manager_name === "string") lines.push(t("게임 내 매니저: ") + plain(archive.manager_name,128));
      lines.push(t("게임 리소스 파일은 포함하지 않습니다."));
      text("accounts-preview-detail",lines.join("\n"),false);
    }
    function accountFeedback(source,detail="") {
      accountFeedbackSource=source; accountFeedbackDetail=detail;
      text("accounts-feedback",t(source)+detail,false);
    }
    function optionsFor(id, rows, empty) {
      const select = el(id), previous = select.value;
      const fingerprint = JSON.stringify(rows);
      if (select.dataset.optionsFingerprint !== fingerprint) {
        select.dataset.optionsFingerprint = fingerprint;
        const nodes = (rows.length ? rows : [{value:"", label:t(empty)}]).map(row => {
          const option = document.createElement("option");
          option.value = row.value; option.textContent = row.label; return option;
        });
        select.replaceChildren(...nodes);
      }
      select.value = rows.some(row => row.value === previous) ? previous : rows.length ? rows[0].value : "";
    }
    function selectedAccount() {
      if (!accountSnapshot) return null;
      return accountSnapshot.accounts.find(row => JSON.stringify([row.mode,row.profile]) === el("accounts-current").value) || null;
    }
    function selectedRestorePoint() {
      if (!accountSnapshot) return null;
      return accountSnapshot.restore_points.find(row => row.id === el("accounts-restore-point").value) || null;
    }
    function renderAccountControls() {
      const available = snapshot && snapshot.account_management_available === true;
      el("accounts-refresh").disabled = !available || accountPending || officialPending || officialBusy() || launchFlushing;
      el("accounts-fields").disabled = !available || !accountSnapshot || accountPending || officialPending || officialBusy() || launchFlushing;
      const current = selectedAccount(), point = selectedRestorePoint();
      const details = [];
      if (current) {
        if (typeof current.manager_name === "string") details.push(t("게임 내 매니저: ") + plain(current.manager_name,128));
        if (typeof current.public_id === "string") details.push(t("게임 ID: ") + plain(current.public_id,256));
        const inventory = object(current.inventory) ? current.inventory : {};
        for (const [key,label] of [["cards","카드"],["items","아이템 종류"],["photos","포토"]])
          if (Number.isSafeInteger(inventory[key]) && inventory[key] >= 0) details.push(t(label) + ": " + inventory[key]);
      }
      text("accounts-user-detail",details.join(" · "),false);
      for (const name of ["select","export","clone"]) el("accounts-"+name).disabled = !current || accountPending || officialPending || officialBusy() || launchFlushing;
      const fileBusy = resourcePending || officialPending || officialBusy() || Boolean(job && ACTIVE_JOBS.has(job.state)) || Boolean(importProgress && ["selecting","preparing","copying","queued"].includes(importProgress.stage));
      el("accounts-export").disabled = !current || accountPending || launchFlushing || fileBusy;
      el("accounts-preview").disabled = accountPending || launchFlushing || fileBusy;
      el("accounts-import").disabled = !accountPreview || accountPending || launchFlushing || fileBusy;
      el("accounts-restore").disabled = !current || !point || current.mode !== point.mode || current.profile !== point.profile || accountPending || officialPending || officialBusy() || launchFlushing;
      el("accounts-previous").disabled = !accountSnapshot || !accountSnapshot.offset || accountPending;
      el("accounts-next").disabled = !accountSnapshot || !Number.isInteger(accountSnapshot.next_offset) || accountPending;
      el("accounts-restore-previous").disabled = !accountSnapshot || !accountSnapshot.restore_offset || accountPending;
      el("accounts-restore-next").disabled = !accountSnapshot || !Number.isInteger(accountSnapshot.next_restore_offset) || accountPending;
      const progress = el("accounts-progress");
      progress.hidden = !accountPending;
      if (accountProgress && accountProgress.total_bytes > 0) {
        progress.max = accountProgress.total_bytes;
        progress.value = Math.min(accountProgress.copied_bytes, accountProgress.total_bytes);
      } else progress.removeAttribute("value");
    }
    function renderAccounts(value) {
      if (!object(value) || !Array.isArray(value.accounts) || !Array.isArray(value.restore_points)
          || !object(value.selected) || typeof value.selection_revision !== "string") return false;
      accountSnapshot = {...value,
        accounts:value.accounts.filter(row => object(row) && choice(row.mode,["normal","media"])
          && typeof row.profile === "string" && typeof row.revision === "string").slice(0,24),
        restore_points:value.restore_points.filter(row => object(row) && typeof row.id === "string"
          && choice(row.mode,["normal","media"]) && typeof row.profile === "string").slice(0,16)};
      optionsFor("accounts-current", accountSnapshot.accounts.map(row => ({value:JSON.stringify([row.mode,row.profile]),
        label:t(row.mode === "media" ? "감상 모드" : "일반 모드") + " · " + plain(row.profile,64)})), "계정 없음");
      optionsFor("accounts-restore-point", accountSnapshot.restore_points.map(row => ({value:row.id,
        label:t(row.mode === "media" ? "감상 모드" : "일반 모드") + " · " + plain(row.profile,64) + " · " + (Number.isSafeInteger(row.created_at) ? new Date(row.created_at).toLocaleString(language) : plain(row.created_at,64))})), "복구점 없음");
      const runtime = snapshot && object(snapshot.runtime) ? snapshot.runtime : {};
      const active = typeof runtime.profile === "string" ? t(runtime.media_mode ? "감상 모드" : "일반 모드") + " · " + runtime.profile : t("확인 중");
      text("accounts-summary", t("현재 계정: ") + active + "\n" + t("다음 시작 · 일반: ") + plain(value.selected.normal,64)
        + t(" / 감상: ") + plain(value.selected.media,64), false);
      renderAccountControls(); return true;
    }
    function renderServerChecks(runtime) {
      const checks = object(runtime.startup_checks) ? runtime.startup_checks : null;
      const history = object(runtime.durable_history) ? runtime.durable_history : null;
      const labels = {protocol:"프로토콜",catalog:"게임 목록",master:"마스터 파일",storage:"저장 공간",http:"파일 서버",grpc:"게임 서버",resources:"게임 리소스",account:"계정"};
      const states = {ready:"준비 완료",blocked:"확인 필요",missing:"없음",attention:"확인 필요",not_checked:"검사 전",stopped:"중지됨",checking:"확인 중",not_run:"검사 전"};
      const descriptions = {"descriptor_loaded": "게임 통신 자료를 확인했습니다.", "catalog_present": "게임 목록 자료를 확인했습니다.", "tag_and_pack_sizes_checked": "마스터 목록과 파일 크기를 확인했습니다.", "storage_writable": "이 기기에 저장할 수 있습니다.", "low_free_space": "저장 공간이 부족합니다. 파일을 정리해 주세요.", "http_json_ready": "파일 서버 응답을 확인했습니다.", "listener_started": "게임 연결을 받을 준비가 되었습니다.", "listener_stopped": "게임 연결을 중지했습니다.", "resource_catalog_missing": "게임 리소스 목록이 없습니다.", "on_demand_enabled": "필요한 파일을 인터넷으로 받을 수 있습니다.", "offline_cache_unverified": "오프라인용 파일이 모두 준비됐는지 확인해 주세요.", "selection_ready": "선택한 계정을 확인했습니다.", "selection_invalid": "계정을 다시 선택해 주세요.", "permission_denied": "저장소 접근 권한을 확인해 주세요.", "address_in_use": "같은 포트의 다른 서버를 종료해 주세요.", "missing_input": "필요한 서버 자료가 없습니다.", "invalid_input": "서버 자료·설정의 형식을 확인해 주세요.", "insufficient_space": "저장 공간을 확보해 주세요.", "internal_error": "진단 기록을 확인해 주세요."};
      const lines = checks && Array.isArray(checks.checks) ? checks.checks.slice(0,12).filter(object).map(row =>
        t(labels[row.id] || "검사") + " · " + t(states[row.state] || "확인 중") + (descriptions[row.code] ? " · " + t(descriptions[row.code]) : "")
        + (Number.isSafeInteger(row.free_bytes) && row.free_bytes >= 0 ? " · " + formatBytes(row.free_bytes) : "")) : [];
      if (checks && checks.scope === "previous_run") lines.unshift(t("이전 실행의 검사 기록입니다."));
      text("startup-checks", lines.length ? lines.join("\n") : t("서버 준비 검사를 기다리고 있습니다."), false);
      const failure = history && object(history.last_failure) ? history.last_failure : null;
      const failures = {rpc:"게임 요청이 실패했습니다.",http_failure:"파일 요청이 실패했습니다.",startup_failure:"서버를 시작하지 못했습니다."};
      const when = failure && typeof failure.timestamp === "string" && Number.isFinite(Date.parse(failure.timestamp)) ? new Date(failure.timestamp).toLocaleString(language) : "";
      text("history-summary", failure ? t("마지막 오류: ") + t(failures[failure.kind] || "서버 작업을 마치지 못했습니다.") + (when ? " · " + when : "")
        : history && history.available === false ? t("오류 기록을 저장할 수 없습니다.") : t("저장된 최근 오류가 없습니다."), false);
    }
    async function account(action, explicitPayload) {
      if (!visible || disposed || accountPending || officialPending || officialBusy() || !snapshot || snapshot.account_management_available !== true || launchFlushing) return;
      const current = selectedAccount(), point = selectedRestorePoint();
      if (["export","preview","import","restore"].includes(action) && (resourcePending || job && ACTIVE_JOBS.has(job.state))) {
        message("진행 중인 파일 작업을 마친 후 다시 시도해 주세요.",true); return;
      }
      let payload = explicitPayload || {};
      if (!explicitPayload) {
        if (["select","export"].includes(action)) {
          if (!current) return;
          payload = {mode:current.mode,profile:current.profile,expected_revision:current.revision};
          if (action === "select") payload.selection_revision = accountSnapshot.selection_revision;
        } else if (action === "create") payload = {mode:el("accounts-mode").value,profile:el("accounts-new-profile").value.trim(),manager_name:el("accounts-manager-name").value};
        else if (action === "clone") {
          if (!current) return;
          payload = {mode:current.mode,source_profile:current.profile,profile:el("accounts-new-profile").value.trim(),expected_revision:current.revision};
        } else if (action === "import") {
          if (!accountPreview) return;
          const replace = el("accounts-replace").checked;
          if (replace && (!current || current.mode !== accountPreview.archive.mode)) {
            message("ZIP과 같은 종류의 계정을 선택해 주세요.",true); return;
          }
          payload = {token:accountPreview.token,mode:accountPreview.archive.mode,
            profile:replace ? current.profile : el("accounts-new-profile").value.trim(),replace,
            expected_revision:replace ? current.revision : null};
        } else if (action === "restore") {
          if (!current || !point || current.mode !== point.mode || current.profile !== point.profile) return;
          payload = {restore_id:point.id,mode:current.mode,profile:current.profile,expected_revision:current.revision};
        }
      }
      accountPending = true; mutationVersion++;
      if (snapshot) renderResources(snapshot.runtime);
      const visibility = visibilityVersion;
      if (action === "preview") accountProgress = {stage:"selecting",copied_bytes:0,total_bytes:0};
      accountFeedback( action === "preview" ? "파일 앱에서 ZIP을 선택해 주세요." : "계정 작업을 처리하고 있습니다.");
      renderAccountControls();
      try {
        const result = await bridge.request("accounts_"+action,payload);
        if (!visible || disposed || visibility !== visibilityVersion) return;
        if (result.cancelled === true) return;
        if (object(result.status)) renderAccounts(result.status);
        if (action === "status" && object(result.status) && result.status.stale !== true) {
          officialWarnings = officialWarnings.filter(code => code !== "account_status_refresh_required");renderOfficial();
        }
        if (action === "preview") {
          if (typeof result.token !== "string" || !object(result.archive)) throw new Error("계정 ZIP 검사 결과를 확인하지 못했습니다.");
          accountPreview = {token:result.token,archive:result.archive};
          const original = plain(result.archive.profile,64);
          let prefix = ""; for (const character of original) {
            if (utf8Length(prefix+character+"-import") > 64) break;
            prefix += character;
          }
          el("accounts-new-profile").value = prefix + "-import";
          el("accounts-mode").value = result.archive.mode;
          el("accounts-replace").checked = false;
          renderAccountPreview();
          accountFeedback("계정 ZIP을 검사했습니다. 가져올 이름과 대상을 확인해 주세요.");
        } else {
          accountFeedback( action === "status" ? "계정 목록을 불러왔습니다." : action === "select"
            ? "다음 서버 시작에 선택한 계정을 적용합니다." : action === "export" ? "계정 ZIP을 준비했습니다. 파일 앱에서 저장해 주세요."
              : "계정 작업을 마쳤습니다.");
          if (action === "import") { accountPreview = null; el("accounts-preview-detail").hidden = true; }
        }
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion) {
          accountFeedback(error.message); message(error.message,true);
        }
      } finally {
        accountPending = false; accountProgress = null;
        if (!disposed) { renderAccountControls(); if (snapshot) renderResources(snapshot.runtime); }
        if (visible && !disposed) refresh();
      }
    }
    function officialFailure(code) {
      if (["transfer_id_invalid","transfer_password_invalid"].includes(code)) return "인계 ID와 비밀번호 형식을 확인해 주세요.";
      if (code === "transfer_rejected") return "공식 서버에서 인계 정보를 확인하지 못했습니다. 입력 정보를 다시 확인해 주세요.";
      if (["verification_expired","verification_closed","verification_consumed","verification_invalid","official_session_expired"].includes(code)) return "확인 정보가 만료되었습니다. 인계 정보를 다시 확인해 주세요.";
      if (code === "official_maintenance") return "일본 공식 서버 점검 중입니다. 나중에 다시 시도해 주세요.";
      if (["official_schema_unsupported","master_version_invalid","official_config_scope_mismatch","official_protocol_changed","official_catalog_changed","official_master_mismatch","official_catalog_reference_missing"].includes(code)) return "공식 서버 자료와 로컬 자료가 맞지 않습니다. 앱을 업데이트한 뒤 다시 시도해 주세요.";
      if (["official_rpc_failed","official_seed_failed","official_firebase_failed","official_transport_unavailable"].includes(code)) return "일본 공식 서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요.";
      if (["account_revision_conflict","account_target_exists","account_target_missing"].includes(code)) return "대상 계정이 변경되었습니다. 계정 목록을 다시 확인해 주세요.";
      if (code === "account_restart_required") return "게임을 완전히 종료하고 다시 연 뒤 게임 시작 전에 계정을 복원해 주세요.";
      return "공식 계정 작업에 실패했습니다. 입력 정보와 연결 상태를 확인해 주세요.";
    }
    function renderOfficial() {
      const job = officialJob || {}, state = job.state || "idle";
      const labels = {idle:"현재 작동하지 않음",checking:"인계 정보 확인 중",verified:"공식 계정 확인 완료",fetching:"공식 계정 데이터 받는 중",ready:"로컬 저장 준비 완료",completed:"일반 계정 저장 완료",failed:"실패",cancelled:"취소됨"};
      const stages = {applying:"일반 계정 저장 중",preparing:"공식 로그인 준비",checking:"인계 정보 확인 중",verifying:"공식 계정 확인",verified:"공식 계정 확인 완료",transferring:"공식 인계 로그인",firebase:"로그인 인증",login:"공식 인계 로그인",master:"계정 데이터 검증",account:"계정 데이터 검증",collected:"계정 데이터 검증",fetching:"공식 계정 데이터 받는 중",catalog_check:"계정 데이터 검증",staging:"로컬 저장 준비",ready:"로컬 저장 준비 완료",completed:"일반 계정 저장 완료",failed:"실패",cancelled:"취소됨"};
      text("official-state", labels[state] || "확인 중");
      const feedback = officialFeedbackSource || (job.busy === true ? stages[job.progress] || "공식 계정 작업을 처리하고 있습니다." : state === "verified" ? "확인한 계정으로 공식 인계 로그인·내려받기를 진행할 수 있습니다." : state === "ready" ? "내려받기와 검증을 마쳤습니다. 저장할 로컬 계정을 확인해 주세요." : state === "completed" ? "일반 계정으로 저장했습니다. 유저 관리에서 계정과 사용할 모드를 선택해 주세요." : state === "failed" ? officialFailure(job.error_code) : state === "cancelled" ? "작업을 취소했습니다." : stages[job.progress] || "일본 공식 계정 가져오기는 현재 작동하지 않습니다.");
      const notices = {account_temporary_cleanup_pending:"계정 저장은 완료됐습니다. 임시 파일 정리가 남아 있습니다.",account_status_refresh_required:"계정 저장은 완료됐습니다. 위 ‘계정 목록 불러오기’로 목록을 새로 확인해 주세요.",official_server_restart_required:"계정 저장은 완료됐지만 서버를 다시 시작하지 못했습니다. ‘서버 시작’을 다시 누르고, 계속 실패하면 앱을 다시 열어 주세요."};
      text("official-feedback",[t(feedback),...officialWarnings.filter(code => Object.prototype.hasOwnProperty.call(notices,code)).map(code => t(notices[code]))].join("\n"),false);
      const preview = object(job.preview) ? job.preview : null, lines = [];
      if (preview) {
        if (typeof preview.manager_name === "string") lines.push(t("게임 내 매니저: ")+plain(preview.manager_name,128));
        if (typeof preview.public_id === "string") lines.push(t("게임 ID: ")+plain(preview.public_id,256));
        if (Number.isSafeInteger(preview.manager_level)) lines.push(t("매니저 레벨: ")+preview.manager_level);
        const inventory = object(preview.inventory) ? preview.inventory : {};
        for (const [key,label] of [["cards","카드"],["items","아이템 종류"],["photos","포토"]])
          if (Number.isSafeInteger(inventory[key]) && inventory[key] >= 0) lines.push(t(label)+": "+inventory[key]);
      }
      text("official-preview",lines.join(" · "),false); el("official-preview").hidden = !lines.length;
      const resourceJob = snapshot && object(snapshot.runtime.resource_library) ? snapshot.runtime.resource_library.job : null;
      const fileBusy = resourcePending || Boolean(resourceJob && ACTIVE_JOBS.has(resourceJob.state)) || Boolean(importProgress && ["selecting","preparing","copying","queued"].includes(importProgress.stage));
      const blocked = officialPending || officialBusy() || accountPending || launchFlushing || fileBusy;
      el("official-inspect").disabled = !snapshot || snapshot.official_import_available !== true || blocked;
      el("official-fetch").disabled = blocked || state !== "verified";
      el("official-fields").disabled = blocked || state !== "ready";
      const target = selectedAccount(), replace = el("official-replace").checked;
      text("official-target",replace ? target && target.mode === "normal" ? t("덮어쓸 저장 슬롯: ")+target.profile : t("덮어쓸 일반 계정을 위에서 선택해 주세요.") : t("새 일반 계정으로 저장합니다."),false);
      el("official-apply").disabled = blocked || state !== "ready" || replace && (!target || target.mode !== "normal");
      el("official-cancel").disabled = officialPending || job.progress === "applying" || !job.job_id || !["checking","verified","fetching","ready"].includes(state);
      el("official-progress").hidden = !officialPending && !officialBusy();
      el("official-progress").removeAttribute("value");
    }
    async function official(action) {
      if (!visible || disposed || officialPending || !snapshot || snapshot.official_import_available !== true || launchFlushing) return;
      if (action !== "status" && action !== "cancel" && (accountPending || resourcePending || officialBusy())) return;
      const payload = {}, job = officialJob || {};
      if (["fetch","cancel","apply"].includes(action)) payload.job_id = job.job_id;
      if (action === "apply") {
        const replace = el("official-replace").checked, target = selectedAccount();
        if (replace && (!target || target.mode !== "normal")) { officialFeedbackSource = "덮어쓸 일반 계정을 위에서 선택해 주세요.";renderOfficial();return; }
        Object.assign(payload,{profile:replace ? target.profile : el("official-profile").value.trim(),replace,expected_revision:replace ? target.revision : null});
        if (!validRequest("official_apply",payload)) { officialFeedbackSource = "저장 슬롯 이름을 슬래시·제어문자 없이 UTF-8 64바이트 이내로 입력해 주세요.";renderOfficial();return; }
      }
      officialPending = true; mutationVersion++;
      if (action !== "status") officialFeedbackSource = "공식 계정 작업을 처리하고 있습니다.";
      const visibility = visibilityVersion; renderOfficial();renderAccountControls();renderResources(snapshot.runtime);
      try {
        const result = await bridge.request("official_"+action,payload);
        if (!visible || disposed || visibility !== visibilityVersion) return;
        if (result.action !== "official_"+action) throw new Error("공식 계정 작업을 마치지 못했습니다. 상태를 확인해 주세요.");
        if (result.cancelled === true) { officialFeedbackSource = "작업을 취소했습니다.";return; }
        if (!object(result.job) || typeof result.job.busy !== "boolean" || !choice(result.job.state,["idle","checking","verified","fetching","ready","completed","failed","cancelled"])
            || result.job.state !== "idle" && !(typeof result.job.job_id === "string" && /^[0-9a-f]{32}$/.test(result.job.job_id))) throw new Error("공식 계정 작업을 마치지 못했습니다. 상태를 확인해 주세요.");
        if (!officialJob || officialJob.job_id !== result.job.job_id) officialWarnings = [];
        officialJob = result.job; officialFeedbackSource = "";
        if (action === "apply") {
          const allowed = ["account_temporary_cleanup_pending","account_status_refresh_required","official_server_restart_required"];
          officialWarnings = Array.isArray(result.warning_codes) ? [...new Set(result.warning_codes.filter(code => allowed.includes(code)))] : [];
          if (result.status_refresh_required === true && !officialWarnings.includes("account_status_refresh_required")) officialWarnings.push("account_status_refresh_required");
        }
        if (object(result.status)) renderAccounts(result.status);
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion) officialFeedbackSource = officialFailure(error.code);
      } finally {
        officialPending = false;
        if (!disposed) {renderOfficial();renderAccountControls();if(snapshot)renderResources(snapshot.runtime);}
        if (action !== "status" && visible && !disposed) refresh();
      }
    }

    async function clearDiagnostics() {
      if (!visible || disposed || historyPending) return;
      historyPending = true; el("diagnostics-clear").disabled = true; mutationVersion++;
      try {
        const result = await bridge.request("diagnostics_clear");
        if (visible && !disposed) renderStatus(result);
      } catch (error) { if (visible && !disposed) message(error.message,true); }
      finally { historyPending = false; if (!disposed) el("diagnostics-clear").disabled = false; }
    }

    function renderDiagnostics(runtime) {
      const diagnostic = object(runtime.client_diagnostics) ? runtime.client_diagnostics : {};
      text("diagnostic-summary", plain(diagnostic.summary, 500) || t("게임 진단 대기 중"), false);
      const details = {
        server: {state: snapshot.state, running: snapshot.running, restart_required: snapshot.restart_required},
        native: object(snapshot.native) ? Object.fromEntries([
          "schema", "phase", "captured", "forwarded", "attempts", "hook_installed",
          "python_initialized", "launch_requested", "launch_prepared", "launcher_visible",
          "keyboard_lifecycle", "keyboard_ready", "unity_host", "late_startup_calls", "octo_budget",
          "game_hook_error", "error", "game_error", "client_data", "http_readiness", "resource_import_progress"
        ].filter(key => Object.prototype.hasOwnProperty.call(snapshot.native, key)).map(key => [key, snapshot.native[key]])) : null,
        official_import: object(snapshot.official_import) ? snapshot.official_import : null,
        startup_checks: runtime.startup_checks || null,
        durable_history: runtime.durable_history || null,
        http_requests: runtime.http_requests || null,
        resource_transfer: runtime.resource_transfer || null,
        asset_transfer: runtime.asset_transfer || null,
        game: diagnostic,
        presentation: object(runtime.presentation) ? runtime.presentation.client || null : null,
        playback: object(runtime.playback) ? runtime.playback.client || null : null,
        resource_operation: object(snapshot.resource_operation) ? {
          accepted: snapshot.resource_operation.accepted,
          ready: snapshot.resource_operation.ready,
          error: snapshot.resource_operation.error || null
        } : null
      };
      // Never interpolate server strings as markup, URLs or executable code.
      let detail = JSON.stringify(details, null, 2);
      const recent = (Array.isArray(runtime.logs) ? runtime.logs.filter(line => typeof line === "string").slice(-40).map(line => plain(line, 1000)) : []).concat(logs).slice(-50);
      if (recent.length) detail += "\n\n최근 기록\n" + recent.join("\n");
      text("diagnostics", boundedDiagnostics(detail, t("… 표시 한도로 나머지 진단은 생략했습니다.")), false);
      updateCopyButton();
    }
    function renderStatus(value) {
      if (!object(value) || !object(value.options)) return false;
      const runtime = object(value.runtime) ? value.runtime : {};
      snapshot = {...value, runtime};
      if (object(value.native) && Object.prototype.hasOwnProperty.call(value.native, "resource_import_progress")) {
        const nativeProgress = value.native.resource_import_progress;
        if (nativeProgress === null && !resourcePending && importProgress) {
          if (["selecting", "preparing", "copying"].includes(importProgress.stage)) importProgress = null;
          else if (importProgress.stage === "queued" && object(value.resource_operation)) {
            // A background transition can reject the initial archive reply and
            // miss its result event. Recover the terminal state from this poll.
            if (value.resource_operation.accepted === false) {
              importProgress.stage = "failed"; importProgress.accepted = false;
            } else if (value.resource_operation.ready === true) importProgress.stage = "completed";
          }
        } else observeImportProgress(nativeProgress);
      }
      if (validOptions(value.options)) {
        const configuredInterface = choice(value.options.interface_language, INTERFACE_LANGUAGES) ? value.options.interface_language : "system";
        // Once selected here, an older status/event/options-save reply cannot
        // take ownership of the visible interface language in this page.
        if (!interfaceSelected && !interfaceDirty && interfaceChoice !== configuredInterface) applyInterfaceLanguage(configuredInterface);
      }
      const titles = {idle: "대기", starting: "준비 중", ready: "실행 중", failed: "시작 실패", closed: "종료됨"};
      text("server-state", titles[value.state] || "확인 중");
      text("server-summary", value.state === "ready" && value.running ? "로컬 서버가 게임 연결을 기다리고 있습니다." : value.last_error ? plain(object(value.last_error) ? value.last_error.message || value.last_error.code : value.last_error, 300) : value.state === "starting" ? "서버와 데이터를 준비하고 있습니다." : "로컬 서버가 실행 중이 아닙니다.");
      el("restart-notice").hidden = value.restart_required !== true;
      updateForm("options", value.options);
      updateForm("presentation", object(runtime.presentation) ? runtime.presentation.settings : null);
      updateForm("playback", object(runtime.playback) ? runtime.playback.settings : null);
      updateForm("media", object(runtime.media_options) ? runtime.media_options.settings : null);
      const incomingEvents = object(runtime.event_settings) ? runtime.event_settings : null;
      if (!eventModeSelected && incomingEvents && typeof incomingEvents.media_mode === "boolean" && !forms.events.dirty && !forms.events.busy) {
        const mode = incomingEvents.media_mode ? "media" : "normal";
        if (mode !== eventMode && incomingEvents.media_mode === el("media_mode").checked) {
          eventMode = mode; eventCatalogKey = "";
          forms.events.value = null; forms.events.draft = null; forms.events.intents.clear(); forms.events.intentVersions.clear();
          forms.events.fingerprint = null; forms.events.rebaseAttempts = 0; forms.events.rebaseNeeded = false;
        }
      }
      const oldEventRevision = incomingEvents && object(incomingEvents.saved) && forms.events.value
        && incomingEvents.saved.revision < forms.events.value.revision;
      if (!oldEventRevision && (!incomingEvents || ((incomingEvents.media_mode === true ? "media" : "normal") === eventMode && !eventModeLoading))) {
        eventSnapshot = incomingEvents;
        renderEvents(false);
        updateForm("events", eventSnapshot && eventSnapshot.saved);
      }
      const effective = value.effective_options;
      text("effective-options", validOptions(effective) ? t("현재: ") + t(effective.media_mode ? "감상 모드" : "일반 모드") + " · " + LANGUAGES[effective.language] + t(" · 자동 받기 ") + t(effective.download_missing_resources ? "켜짐" : "꺼짐") : "현재 적용 값은 서버 준비 후 표시됩니다.");
      const graphics = object(runtime.presentation) && object(runtime.presentation.client) ? runtime.presentation.client : {};
      const graphicsLabels = {waiting: "적용 대기", applied: "게임 적용 확인", disabled: "원본 설정", unsupported: "미지원", waiting_for_scene: "장면 대기", init_failed: "초기화 실패"};
      text("graphics-state", graphicsLabels[graphics.status] || "대기");
      text("graphics-detail", graphics.status === "applied" ? "게임에서 현재 그래픽 설정을 확인했습니다. 화면 확장은 촬영 장면에서 확인해 주세요." : graphics.status === "waiting_for_scene" ? "설정이 저장되었습니다. 촬영·360 장면에서 적용 상태를 확인합니다." : "저장 확인과 게임 적용 확인은 다릅니다. 해당 장면에 들어가 적용 상태를 확인해 주세요.");
      const playback = object(runtime.playback) && object(runtime.playback.client) ? runtime.playback.client : {};
      text("playback-state", playback.applied === true ? "게임 적용 확인" : playback.supported === false ? "미지원" : "적용 대기");
      const media = object(runtime.media_options) ? runtime.media_options : {};
      const mediaChanged = validMedia(media.settings) && validMedia(media.effective_settings) && forms.media.fields.some(key => media.settings[key] !== media.effective_settings[key]);
      text("media-effective", mediaChanged ? "변경한 목록 설정은 다음 앱 실행부터 적용됩니다." : "목록 설정은 다음 앱 실행부터 적용됩니다.");
      if (object(value.official_import)) {
        const publicJob = value.official_import, previous = officialJob;
        if (!officialPending && previous && (previous.job_id !== publicJob.job_id || previous.state !== publicJob.state)) officialFeedbackSource = "";
        if (!officialPending && previous && previous.job_id !== publicJob.job_id) officialWarnings = [];
        if (!officialPending) officialJob = {...publicJob,...(previous && previous.job_id === publicJob.job_id && ["verified","ready","completed"].includes(publicJob.state) && object(previous.preview) ? {preview:previous.preview} : {})};
        if (!officialPending && publicJob.state !== "idle" && (publicJob.busy === true || !previous || previous.job_id !== publicJob.job_id || previous.state !== publicJob.state)) Promise.resolve().then(() => official("status"));
      }
      renderOfficial();
      renderResources(runtime);
      renderServerChecks(runtime);
      el("diagnostics-clear").disabled = historyPending || value.account_management_available !== true;
      if (!accountPending && object(value.accounts)) renderAccounts(value.accounts);
      renderAccountControls();
      if (value.account_management_available === true && !accountRequested) {
        Promise.resolve().then(() => {
          if (!accountPending && !officialPending && !officialBusy() && !accountRequested) { accountRequested = true; account("status"); }
        });
      }
      renderDiagnostics(runtime);
      for (const [name, form] of Object.entries(forms)) if (form.resumeQueued && value.running && value.state === "ready") {
        form.resumeQueued = false; queueSave(name);
      }
      return true;
    }
    async function refresh() {
      if (!visible || disposed || refreshing) return;
      refreshing = true;
      const version = mutationVersion;
      el("refresh").disabled = true;
      try {
        const result = await bridge.request("status");
        if (visible && !disposed && version === mutationVersion && !renderStatus(result)) message("서버 상태 형식을 확인하지 못했습니다.", true);
      } catch (error) {
        if (visible && !disposed && version === mutationVersion) message(error.message, true);
      } finally {
        refreshing = false;
        if (!disposed) el("refresh").disabled = false;
        if (visible && !disposed) {if (selectedCategory === "graphics") loadMP4Options();mp4("status");mp4Queue("status");}
        schedulePoll();
      }
    }
    function savedFormSettings(name, result) {
      const runtime = object(result.runtime) ? result.runtime : {};
      return name === "options" ? result.options : name === "presentation" ? runtime.presentation && runtime.presentation.settings
        : name === "playback" ? runtime.playback && runtime.playback.settings : name === "events" ? runtime.event_settings && runtime.event_settings.saved : runtime.media_options && runtime.media_options.settings;
    }
    function save(name, force = false) {
      const form = forms[name];
      clearAutosave(name);
      if (!visible || disposed || !snapshot || !snapshot.running || snapshot.state !== "ready") return Promise.resolve(false);
      if (form.busy) { form.queued = true; return form.inflight; }
      if (!form.dirty && !force) return Promise.resolve(true);
      let value;
      try { value = settingsFromForm(name); }
      catch (error) {
        saveFeedback(name, "invalid", "입력값의 범위를 확인해 주세요. 유효한 값만 자동으로 저장합니다.");
        if (force) message(error.message, true);
        return Promise.resolve(false);
      }
      const edited = form.editRevision, version = ++mutationVersion, visibility = visibilityVersion;
      const sentIntents = name === "events" ? new Map(form.intents) : null;
      const sentIntentVersions = name === "events" ? new Map(form.intentVersions) : null;
      form.busy = true; form.queued = false;
      saveFeedback(name, "saving", "저장 중…");
      const operation = (async () => {
        try {
          const result = await bridge.request(name === "events" ? "events_save" : "save_" + name,
            name === "options" ? value : name === "events" ? {settings:value,expected_revision:form.value.revision,...(eventMode === "media" ? {mode:"media"} : {})} : {settings: value});
          if (!visible || disposed || visibility !== visibilityVersion) return false;
          const settings = savedFormSettings(name, result);
          if (!form.valid(settings)) throw new Error("서버 상태 형식을 확인하지 못했습니다.");
          const latest = name === "events" && form.value && form.value.revision > settings.revision ? form.value : settings;
          form.value = {...latest};
          if (form.editRevision === edited) form.dirty = false;
          if (name === "events") {
            for (const id of sentIntents.keys()) if (form.intentVersions.get(id) === sentIntentVersions.get(id)) {
              form.intents.delete(id); form.intentVersions.delete(id);
            }
            form.draft = mergedEventDraft(latest,form.intents);
            form.dirty = form.intents.size > 0; form.rebaseAttempts = 0;
            form.fingerprint = JSON.stringify(form.draft.love_events);
          }
          // A status poll started during this write is older than its ACK.
          // Invalidate it while retaining the decision about newer local edits.
          const mayRender = version === mutationVersion;
          mutationVersion++;
          if (mayRender && latest === settings) renderStatus(result);
          else updateForm(name, latest);
          saveFeedback(name, form.dirty ? "pending" : "saved", form.dirty
            ? "변경 사항을 저장할 준비가 되었습니다." : "자동 저장했습니다.");
          return true;
        } catch (error) {
          if (visible && !disposed && visibility === visibilityVersion) {
            const conflict = name === "events" && error.code === "event_settings_revision_conflict";
            if (conflict && form.rebaseAttempts < 2) {
              form.rebaseAttempts++; form.rebaseNeeded = true;
              saveFeedback(name,"pending","최신 설정에 선택한 변경을 합쳐 저장합니다."); refreshEventSettings();
            } else saveFeedback(name, "failed", conflict ? "다른 화면에서 이벤트 설정이 바뀌었습니다. 최신 상태를 확인한 뒤 다시 시도를 눌러 현재 입력을 저장해 주세요." : "설정을 저장하지 못했습니다. 다시 시도를 눌러 주세요.");
            if (force) message(error.message, true);
          }
          return false;
        } finally {
          form.busy = false; form.inflight = null;
          if (!disposed) {
            if (snapshot) updateForm(name, form.value);
            if (form.queued && form.dirty && visible && !launchFlushing) queueSave(name);
            schedulePoll();
          }
        }
      })();
      form.inflight = operation;
      return operation;
    }
    function saveInterfaceLanguage(value) {
      interfaceOperation = persistInterfaceLanguage(value);
      return interfaceOperation;
    }
    async function persistInterfaceLanguage(value) {
      if (!visible || disposed || !choice(value, INTERFACE_LANGUAGES)) return;
      const version = ++interfaceVersion;
      const visibility = visibilityVersion;
      interfaceSelected = true;
      interfaceDirty = true;
      applyInterfaceLanguage(value);
      if (snapshot) renderStatus(snapshot);
      try {
        // This action contains no game preferences and is available even while
        // the server is idle, starting or failed. Native chrome changes on receipt.
        const result = await bridge.request("save_interface_language", {interface_language: value});
        if (!visible || disposed || visibility !== visibilityVersion || version !== interfaceVersion) return;
        const acknowledged = result.interface_language || (object(result.options) && result.options.interface_language);
        if (acknowledged !== value) throw new Error("서버 화면 언어를 저장하지 못했습니다. 다시 선택해 주세요.");
        interfaceDirty = false;
        if (snapshot) snapshot.options = {...snapshot.options, interface_language: value};
        if (forms.options.value) forms.options.value.interface_language = value;
        return true;
      } catch (_) {
        if (visible && !disposed && visibility === visibilityVersion && version === interfaceVersion)
          message("서버 화면 언어를 저장하지 못했습니다. 다시 선택해 주세요.", true);
        return false;
      } finally {
        if (!disposed) schedulePoll();
      }
    }
    function setFlushState(state) {
      if (document.documentElement && document.documentElement.dataset) document.documentElement.dataset.settingsFlush = state;
    }
    function updateFlushControls() {
      el("interface_language").disabled = launchFlushing;
      renderAccountControls(); renderOfficial();
      if (snapshot) for (const name of Object.keys(forms)) updateForm(name, forms[name].value);
    }
    function releaseSettingsFlush(nonce) {
      if (nonce !== flushNonce) return;
      flushGeneration++; flushNonce = null; launchFlushing = false;
      setFlushState("failed"); updateFlushControls();
      if (visible && !disposed) message("설정을 저장하지 못해 게임을 시작하지 않았습니다. 입력값과 저장 상태를 확인해 주세요.", true);
    }
    function flushSettings(nonce) {
      if (typeof nonce !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(nonce)
          || !visible || disposed || launchFlushing) return;
      for (const name of Object.keys(forms)) { markEdited(name); clearAutosave(name); }
      const generation = ++flushGeneration;
      flushNonce = nonce; launchFlushing = true; setFlushState("saving"); updateFlushControls();
      message("게임을 시작하기 전에 설정 저장을 확인하고 있습니다.");
      // Native evaluateJavaScript need not understand Promise return values on
      // iOS 13. Only this explicit nonce ACK can release the native launch gate.
      (async () => {
        let ready = false;
        try {
          if (!snapshot || !snapshot.running || snapshot.state !== "ready" || accountPending || officialPending || officialBusy()) throw new Error("not_ready");
          for (const name of Object.keys(forms)) {
            if (name === "events" && !forms.events.available) {
              if (forms.events.dirty || forms.events.busy) throw new Error("event_settings_unavailable");
              continue;
            }
            try { settingsFromForm(name); }
            catch (_) {
              saveFeedback(name, "invalid", "입력값의 범위를 확인해 주세요. 유효한 값만 자동으로 저장합니다.");
              throw new Error("invalid_settings");
            }
          }
          await Promise.all(Object.entries(forms).map(async ([name, form]) => {
            if (name === "events" && !form.available && !form.dirty && !form.inflight) return;
            if (form.inflight) await form.inflight;
            if (generation !== flushGeneration || !visible || disposed) throw new Error("flush_cancelled");
            if (form.dirty) {
              form.queued = false;
              if (!await save(name) || form.dirty) throw new Error("save_failed");
            }
          }));
          if (interfaceOperation) await interfaceOperation;
          if (generation !== flushGeneration || !visible || disposed) throw new Error("flush_cancelled");
          // One explicit launch attempt may retry a failed interface save once,
          // just as it flushes dirty game forms. Never create a background loop.
          if (interfaceDirty) await saveInterfaceLanguage(interfaceChoice);
          if (interfaceDirty || generation !== flushGeneration || !visible || disposed) throw new Error("flush_cancelled");
          ready = true; setFlushState("ready");
        } catch (_) {
          if (generation !== flushGeneration || disposed) return;
          setFlushState("failed");
          if (visible) message("설정을 저장하지 못해 게임을 시작하지 않았습니다. 입력값과 저장 상태를 확인해 주세요.", true);
        }
        if (generation !== flushGeneration || !visible || disposed) return;
        try {
          const result = await bridge.request("launch_settings_barrier", {nonce, ready});
          if (generation === flushGeneration && (!ready || result.launched !== true)) releaseSettingsFlush(nonce);
        } catch (_) {
          if (generation === flushGeneration) releaseSettingsFlush(nonce);
        }
      })();
    }
    scope.idolyServerFlushSettings = flushSettings;
    scope.idolyServerReleaseSettingsFlush = releaseSettingsFlush;
    async function resource(action) {
      if (!visible || disposed || resourcePending || accountPending || officialPending || officialBusy() || !snapshot || !snapshot.running || snapshot.state !== "ready") return;
      const payload = action === "cancel" ? {job_id: job && job.job_id} : action === "download" ? {parallelism: Number(el("parallelism").value)} : {};
      resourcePending = true; renderAccountControls();
      if (action === "import") importProgress = {stage: "selecting", request_id: null, copied_bytes: 0, total_bytes: 0, previous_job_id: job && job.job_id, previous_operation: snapshot.resource_operation, previous_request_id: latestImportRequestID, accepted: false};
      else if (action !== "cancel") importProgress = null;
      mutationVersion++;
      const visibility = visibilityVersion;
      if (snapshot) renderResources(snapshot.runtime);
      try {
        const result = await bridge.request("resources_" + action, payload);
        if (!visible || disposed || visibility !== visibilityVersion) return;
        if (action === "import" && importProgress) {
          if (result.cancelled === true) importProgress = null;
          else if (result.accepted === true) {
            importProgress.accepted = true;
            if (!["completed", "failed"].includes(importProgress.stage)) importProgress.stage = result.ready === true ? "completed" : "queued";
          }
        }
        message(action === "import" && importProgress && importProgress.stage === "completed" ? "ZIP 가져오기를 마쳤습니다." : result.cancelled === true ? "파일 선택을 취소했습니다." : {preview: "리소스 목록을 확인했습니다.", download: "리소스 받기를 시작했습니다.", cancel: "작업 취소를 요청했습니다.", import: "ZIP 가져오기를 시작했습니다. 진행 상태를 확인해 주세요.", export: result.ready === true ? "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요." : "ZIP을 준비하고 있습니다. 완료되면 파일 앱에서 저장할 수 있습니다."}[action]);
      } catch (error) {
        if (visible && !disposed && visibility === visibilityVersion) {
          if (action === "import" && importProgress
              && error.message !== "응답이 지연되었습니다. 새로고침 후 상태를 확인해 주세요.") {
            if (importProgress.stage === "selecting") importProgress = null;
            else { importProgress.stage = "failed"; importProgress.accepted = false; }
          }
          message(error.message, true);
        }
      } finally {
        resourcePending = false; if (!disposed) renderAccountControls();
        if (!disposed && snapshot) renderResources(snapshot.runtime);
        if (visible && !disposed) refresh();
      }
    }
    function onVisibility() {
      visible = document.visibilityState !== "hidden";
      mutationVersion++;
      visibilityVersion++;
      stopPolling();
      if (visible) { bridge.resume(); Promise.resolve().then(() => {refresh();if (selectedCategory === "graphics") loadMP4Options();}); }
      else {
        if (launchFlushing) releaseSettingsFlush(flushNonce);
        for (const [name, form] of Object.entries(forms)) {
          clearAutosave(name); form.resumeQueued = form.dirty && form.saveState !== "failed";
        }
        bridge.suspend();
      }
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      visible = false;
      stopPolling();
      for (const name of Object.keys(forms)) clearAutosave(name);
      flushGeneration++; flushNonce = null;
      if (scope.idolyServerFlushSettings === flushSettings) delete scope.idolyServerFlushSettings;
      if (scope.idolyServerReleaseSettingsFlush === releaseSettingsFlush) delete scope.idolyServerReleaseSettingsFlush;
      bridge.dispose();
      document.removeEventListener("visibilitychange", onVisibility);
      scope.removeEventListener("pagehide", dispose);
    }
    for (const [name, form] of Object.entries(forms)) {
      Object.assign(form, {dirty:false, busy:false, queued:false, inflight:null, autosaveTimer:null,
        editRevision:0, fingerprint:null, resumeQueued:false, saveState:"ready", feedback:"변경하면 자동으로 저장됩니다."});
      // Keep form submission as an explicit retry/Enter path. Ordinary changes
      // save from the real control events, so no Save button is needed.
      for (const kind of ["input", "change"]) el(name + "-form").addEventListener(kind, event => {
        if (!event.target || event.target === el(name + "-form")) markEdited(name);
      });
      el(name + "-form").addEventListener("submit", event => {
        event.preventDefault(); markEdited(name); save(name, true);
      });
      el(name + "-save-retry").addEventListener("click", () => { markEdited(name); save(name, true); });
      for (const key of form.fields) {
        const input = el(key), numeric = input.type === "number";
        input.addEventListener("input", () => {
          if (numeric && name === "presentation") syncPreset(key);
          markEdited(name, numeric ? 600 : null);
        });
        input.addEventListener("change", () => markEdited(name, 0));
        if (numeric) input.addEventListener("blur", () => markEdited(name, 0));
      }
    }
    el("events-mode").addEventListener("change", () => switchEventMode(el("events-mode").value));
    el("events-enable-all").addEventListener("click", () => editAllEvents(true));
    el("events-disable-all").addEventListener("click", () => editAllEvents(false));
    el("events-choice").addEventListener("change", () => renderEvents(true));
    el("events-enabled").addEventListener("change", editEvent);
    for (const id of ["events-start","events-end"]) el(id).addEventListener("change", editEvent);
    el("interface_language").addEventListener("change", () => saveInterfaceLanguage(el("interface_language").value));
    for (const key of ["render_scale", "max_buffer_pixel"]) {
      el(key + "_preset").addEventListener("change", () => {
        const value = el(key + "_preset").value;
        if (value !== "custom") { el(key).value = value; markEdited("presentation", 0); }
        else if (typeof el(key).focus === "function") el(key).focus();
      });
    }
    initializeLayout();
    applyMP4Options(MP4_OPTION_DEFAULTS);
    applyInterfaceLanguage(interfaceChoice);
    for (const [id,key] of Object.entries(mp4OptionFields)) {
      el(id).addEventListener(el(id).type === "number" ? "input" : "change",() => {
        mp4EditedOptions.add(key);mp4OptionsVersion++;mp4OptionsError = "";saveMP4Options();
      });
    }
    for (const action of ["start","pause","resume","cancel","save"]) el("mp4-"+action).addEventListener("click",() => mp4(action));
    for (const action of ["run","pause","resume"]) el("mp4-queue-"+action).addEventListener("click",() => mp4Queue(action));
    el("mp4-enqueue").addEventListener("click",() => mp4Queue("enqueue"));
    el("panel-mp4").addEventListener("toggle",() => { if (selectedCategory === "graphics" && el("panel-mp4").open) loadMP4Options();mp4("status");mp4Queue("status"); });
    updateCopyButton();
    el("diagnostics-copy").addEventListener("click", copyDiagnostics);
    el("diagnostics-clear").addEventListener("click", clearDiagnostics);
    el("accounts-refresh").addEventListener("click", () => account("status"));
    for (const action of ["create","clone","select","export","preview","import","restore"]) el("accounts-"+action).addEventListener("click", () => account(action));
    el("accounts-current").addEventListener("change", () => {renderAccountControls();renderOfficial();});
    for (const action of ["inspect","fetch","cancel","apply"]) el("official-"+action).addEventListener("click", () => official(action));
    el("official-replace").addEventListener("change",renderOfficial);
    el("accounts-restore-point").addEventListener("change", renderAccountControls);
    el("accounts-previous").addEventListener("click", () => account("status",{offset:Math.max(0,accountSnapshot.offset-24),restore_offset:accountSnapshot.restore_offset || 0}));
    el("accounts-next").addEventListener("click", () => account("status",{offset:accountSnapshot.next_offset,restore_offset:accountSnapshot.restore_offset || 0}));
    el("accounts-restore-previous").addEventListener("click", () => account("status",{offset:accountSnapshot.offset || 0,restore_offset:Math.max(0,accountSnapshot.restore_offset-16)}));
    el("accounts-restore-next").addEventListener("click", () => account("status",{offset:accountSnapshot.offset || 0,restore_offset:accountSnapshot.next_restore_offset}));
    el("refresh").addEventListener("click", () => { message(""); refresh(); });
    for (const action of ["preview", "download", "import", "export", "cancel"]) el("resources-" + action).addEventListener("click", () => resource(action));
    bridge.subscribe(event => {
      if (event.event === "account_import_progress" && accountPending) {
        accountProgress = event;
        accountFeedback( event.stage === "selecting" ? "파일 앱에서 ZIP을 선택해 주세요." : event.stage === "failed" ? "ZIP 가져오기를 마치지 못했습니다." : event.stage === "queued" ? "복사를 마쳤습니다. ZIP 목록과 내용을 검증하고 있습니다." : "ZIP을 앱 보관 폴더로 복사하고 있습니다.");
        if (event.stage === "copying") accountFeedback(accountFeedbackSource," " + formatBytes(event.copied_bytes) + (event.total_bytes ? " / " + formatBytes(event.total_bytes) : ""));
        renderAccountControls();
      }
      if (event.event === "resource_import_progress") {
        observeImportProgress(event);
        if (snapshot) renderResources(snapshot.runtime);
      }
      if (object(event.status) && ["ready", "status", "error", "closed"].includes(event.event)) renderStatus(event.status);
      if (event.event === "log" && typeof event.message === "string") {
        logs.push(plain(event.message, 1000));
        if (logs.length > 40) logs.shift();
        if (snapshot) renderDiagnostics(snapshot.runtime);
      }
      if (["resource_result", "resource_error"].includes(event.event)) {
        if (importProgress && (["queued", "completed"].includes(importProgress.stage)
            || (object(event.job) && event.job.action === "import" && typeof event.job.job_id === "string"
              && event.job.job_id !== importProgress.previous_job_id))) {
          if (event.accepted === false || event.event === "resource_error") importProgress.stage = "failed";
          else if (event.ready === true && !event.output_path) {
            importProgress.stage = "completed";
            if (object(event.job) && event.job.action === "import") importProgress.result_job = event.job;
          }
          if (snapshot) renderResources(snapshot.runtime);
        }
        if (event.accepted === false || event.event === "resource_error") message("ZIP 작업을 마치지 못했습니다. 확인된 파일과 기존 보관 자료는 유지됩니다.", true);
        else if (event.ready === true) message(event.output_path ? "ZIP을 준비했습니다. 파일 앱에서 저장해 주세요." : "ZIP 가져오기를 마쳤습니다.");
        else if (event.message) message(event.message);
        refresh();
      }
      if (pollTimer === null) schedulePoll();
    });
    document.addEventListener("visibilitychange", onVisibility);
    scope.addEventListener("pagehide", dispose);
    if (visible) refresh();
    else bridge.suspend();
    return {dispose};
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {createBridge, createSettingsApp, formatBytes, resolveInterfaceLanguage, translateUI,validMP4ExportOptions,recommendedMP4Bitrate};
  else if (root.document) createSettingsApp(root, root.document);
})(typeof window !== "undefined" ? window : globalThis);
