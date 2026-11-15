#import "IdolyEmbeddedServer.h"
#import "IdolyNativeUI.h"
#import "IdolyMacMenu.h"
#include "CornerPolicy.h"
#import <UIKit/UIKit.h>
#import <WebKit/WebKit.h>
#import <objc/runtime.h>
#include <stdatomic.h>

static atomic_bool settingsVisible;
static UIWindow *launcherWindow;
static UIWindow *failureWindow;
static __weak UIWindow *previousGameWindow;
static __weak UIWindow *previousFailureWindow;
static NSString *pendingFailure;
static BOOL serverReady;
static BOOL gameStartAvailable;
static BOOL serverBusy;
static BOOL serverAttempted;
static NSString *serverReadyStatus;
static NSString *interfaceLanguage = @"system";
static NSInteger interfaceLanguageIndex = -1;
static const NSUInteger maxJSON = 65536;
static const NSUInteger maxDiagnosticCopy = 32768;

static NSInteger resolvedInterfaceLanguage(void) {
    NSString *language = [interfaceLanguage isEqualToString:@"system"]
        ? NSLocale.preferredLanguages.firstObject.lowercaseString : interfaceLanguage;
    if ([language hasPrefix:@"ko"]) return 0;
    if ([language hasPrefix:@"ja"]) return 1;
    return 2;
}
static NSString *localized(NSString *source) {
    if (interfaceLanguageIndex < 0) interfaceLanguageIndex = resolvedInterfaceLanguage();
    if (interfaceLanguageIndex == 0 || !source) return source;
    static NSDictionary<NSString *, NSArray<NSString *> *> *catalog;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ catalog = @{
        @"아이프라 서버":@[@"アイプラサーバー", @"Idoly Server"],
        @"아이프라 서버 설정":@[@"サーバー設定", @"Server Settings"],
        @"로컬 서버 설정…":@[@"ローカルサーバー設定…", @"Local Server Settings…"],
        @"서버":@[@"サーバー", @"Server"],
        @"서버 오류":@[@"サーバーエラー", @"Server error"],
        @"Python 서버 초기화에 실패했습니다.":@[@"Pythonサーバーの初期化に失敗しました。", @"The Python server could not be initialized."],
        @"Python 초기화 실패":@[@"Pythonの初期化に失敗しました", @"Python initialization failed"],
        @"서버 실행 중 · 게임 데이터 준비 실패":@[@"サーバー稼働中 · ゲームデータの準備に失敗", @"Server Running · Game Data Preparation Failed"],
        @"로컬 리소스 대기 설정을 준비하지 못했습니다.":@[@"ローカルリソースの待機設定を準備できませんでした。", @"The local resource wait settings could not be prepared."],
        @"서버 실행 중 · 게임 연결 준비 실패":@[@"サーバー稼働中 · ゲーム接続の準備に失敗", @"Server Running · Game Connection Preparation Failed"],
        @"로컬 리소스 대기 설정을 적용하지 못했습니다.":@[@"ローカルリソースの待機設定を適用できませんでした。", @"The local resource wait settings could not be applied."],
        @"서버 연결을 확인하고 있습니다…":@[@"サーバー接続を確認しています…", @"Checking the server connection…"],
        @"게임 언어 데이터를 선택하지 못했습니다.":@[@"ゲームの言語データを選択できませんでした。", @"The game language data could not be selected."],
        @"서버 시작":@[@"サーバー開始", @"Start Server"],
        @"게임 시작":@[@"ゲーム開始", @"Start Game"],
        @"게임으로 돌아가기":@[@"ゲームに戻る", @"Return to Game"],
        @"서버 실행 중":@[@"サーバー稼働中", @"Server Running"],
        @"서버 준비 중":@[@"サーバー準備中", @"Starting Server"],
        @"다시 시도":@[@"再試行", @"Retry"],
        @"앱·게임 준비 실패":@[@"アプリ・ゲームの準備に失敗", @"App or Game Preparation Failed"],
        @"서버가 준비되었습니다.":@[@"サーバーの準備ができました。", @"The server is ready."],
        @"서버를 준비하고 있습니다…":@[@"サーバーを準備しています…", @"Preparing the server…"],
        @"서버가 실행 중이 아닙니다. ‘서버 시작’을 눌러 주세요.":@[@"サーバーは停止中です。「サーバー開始」を押してください。", @"The server is stopped. Select Start Server."],
        @"서버를 시작하지 못했습니다":@[@"サーバーを開始できませんでした", @"The server could not start"],
        @"서버 연결 보호를 준비하지 못했습니다. 앱을 다시 실행해 주세요.":@[@"サーバー接続の保護を準備できませんでした。アプリを起動し直してください。", @"The server connection protection could not be prepared. Please reopen the app."],
        @"서버 시작 실패":@[@"サーバーの開始に失敗しました", @"Server startup failed"],
        @"서버 연결 확인 실패":@[@"サーバー接続を確認できませんでした", @"Server connection check failed"],
        @"내장 리소스 서버에 연결하지 못했습니다. 진단에서 HTTP 연결 상태를 확인해 주세요.":@[@"内蔵リソースサーバーに接続できませんでした。診断でHTTP接続の状態を確認してください。", @"The embedded resource server could not be reached. Check the HTTP connection status in Diagnostics."],
        @"게임 시작을 준비하고 있습니다…":@[@"ゲームの開始を準備しています…", @"Preparing to start the game…"],
        @"게임 데이터와 선택한 언어를 준비하고 있습니다…":@[@"ゲームデータと選択した言語を準備しています…", @"Preparing game data and the selected language…"],
        @"게임 시작 준비 실패":@[@"ゲームの開始準備に失敗しました", @"Game preparation failed"],
        @"게임 시작을 준비하지 못했습니다. 다시 시도해 주세요.":@[@"ゲームの開始を準備できませんでした。再試行してください。", @"The game could not be prepared. Please retry."],
        @"서버 연결을 확인하지 못했습니다. 다시 시도해 주세요.":@[@"サーバー接続を確認できませんでした。再試行してください。", @"The server connection could not be verified. Please retry."],
        @"게임 버전을 확인할 수 없습니다":@[@"ゲームのバージョンを確認できません", @"The game version could not be verified"],
        @"이 게임의 Unity 초기화 진입점을 확인하지 못했습니다. 서버는 독립적으로 시작합니다.":@[@"このゲームのUnity初期化処理を確認できませんでした。サーバーは単独で開始します。", @"This game's Unity initialization entry could not be verified. The server will start independently."],
        @"Unity 시작 진입점을 연결하지 못했습니다.":@[@"Unityの開始処理に接続できませんでした。", @"The Unity startup entry could not be connected."],
        @"이 게임의 Unity 키보드 진입점을 확인하지 못했습니다. 서버는 독립적으로 시작합니다.":@[@"このゲームのUnityキーボード処理を確認できませんでした。サーバーは単独で開始します。", @"This game's Unity keyboard entry could not be verified. The server will start independently."],
        @"Unity 키보드 초기화 보호를 연결하지 못했습니다.":@[@"Unityキーボードの初期化保護を設定できませんでした。", @"The Unity keyboard initialization guard could not be connected."],
        @"게임 언어 데이터가 준비되지 않았습니다.":@[@"ゲームの言語データが準備されていません。", @"The game language data is not ready."],
        @"이 게임의 언어 데이터 진입점을 확인하지 못했습니다.":@[@"このゲームの言語データ設定処理を確認できませんでした。", @"This game's language data entry could not be verified."],
        @"게임 데이터 컨트롤러를 확인하지 못했습니다.":@[@"ゲームデータコントローラーを確認できませんでした。", @"The game data controller could not be verified."],
        @"Python 경로 설정에 실패했습니다.":@[@"Pythonのパスを設定できませんでした。", @"The Python paths could not be configured."],
        @"다른 Python 인터프리터가 이미 실행 중입니다.":@[@"別のPythonインタープリターがすでに動作しています。", @"Another Python interpreter is already running."],
        @"iOS 서버 모듈을 등록하지 못했습니다.":@[@"iOSサーバーモジュールを登録できませんでした。", @"The iOS server module could not be registered."],
        @"Python 경로의 문자를 변환하지 못했습니다.":@[@"Pythonのパスの文字を変換できませんでした。", @"The Python path characters could not be converted."],
        @"Python 검색 경로를 준비하지 못했습니다.":@[@"Pythonの検索パスを準備できませんでした。", @"The Python search paths could not be prepared."],
        @"Python 서버가 준비되지 않았습니다.":@[@"Pythonサーバーの準備ができていません。", @"The Python server is not ready."],
        @"로컬 서버가 준비 완료 상태를 보고하지 않았습니다.":@[@"ローカルサーバーが準備完了を報告しませんでした。", @"The local server did not report a ready state."],
        @"서버 응답이 64 KiB를 초과했습니다.":@[@"サーバーの応答が64 KiBを超えました。", @"The server response exceeded 64 KiB."],
        @"서버가 준비되지 않았습니다.":@[@"サーバーの準備ができていません。", @"The server is not ready."],
        @"서버가 준비되지 않았습니다. 서버 시작 버튼을 눌러 주세요.":@[@"サーバーの準備ができていません。「サーバー開始」を押してください。", @"The server is not ready. Select Start Server."],
        @"서버와 게임의 언어 데이터가 일치하지 않습니다.":@[@"サーバーとゲームの言語データが一致しません。", @"The server and game language data do not match."],
        @"게임 시작 경로와 언어 데이터를 확인하지 못했습니다. 앱을 완전히 종료한 뒤 다시 실행해 주세요.":@[@"ゲームの開始処理と言語データを確認できませんでした。アプリを完全に終了してから、もう一度起動してください。", @"The game startup path and language data could not be verified. Fully quit the app, then open it again."],
        @"이 게임의 초기 시작 경로를 확인하지 못했습니다. 서버는 독립적으로 시작합니다.":@[@"このゲームの初期起動処理を確認できませんでした。サーバーは単独で開始します。", @"This game's initial startup path could not be verified. The server will start independently."],
        @"설정 요청 형식이 올바르지 않습니다.":@[@"設定リクエストの形式が正しくありません。", @"The settings request format is invalid."],
        @"서버 응답이 너무 큽니다.":@[@"サーバーの応答が大きすぎます。", @"The server response is too large."],
        @"로컬 서버 연결을 복구하지 못했습니다. 게임을 다시 열어 주세요.":@[@"ローカルサーバーへの接続を復旧できませんでした。ゲームを開き直してください。", @"The local server connection could not be restored. Please reopen the game."],
        @"준비가 끝나면 오른쪽 위의 ‘게임 시작’을 누르세요. 게임 중에는 화면 오른쪽 위 모서리를 한 손가락으로 2초간 누르면 서버 메뉴가 다시 열립니다.":@[@"準備ができたら右上の「ゲーム開始」を押してください。ゲーム中は画面右上の隅を指1本で2秒間押すと、サーバーメニューを再び開けます。", @"When ready, select Start Game at the top right. During play, hold the screen's upper-right corner with one finger for 2 seconds to reopen this menu."],
        @"이 메뉴를 닫아도 서버는 계속 실행됩니다.":@[@"このメニューを閉じてもサーバーは動作し続けます。", @"Closing this menu keeps the server running."],
        @"요청이 너무 큽니다.":@[@"リクエストが大きすぎます。", @"The request is too large."],
        @"진단 내용을 복사하지 못했습니다.":@[@"診断情報をコピーできませんでした。", @"The diagnostic text could not be copied."],
        @"허용되지 않은 서버 요청입니다.":@[@"許可されていないサーバーリクエストです。", @"This server request is not allowed."],
        @"이미 파일을 선택하고 있습니다.":@[@"すでにファイルを選択中です。", @"A file selection is already open."],
        @"파일 선택을 취소했습니다.":@[@"ファイル選択をキャンセルしました。", @"File selection was cancelled."],
        @"ZIP 파일을 선택해 주세요.":@[@"ZIPファイルを選択してください。", @"Please select a ZIP file."],
        @"ZIP 파일을 앱 보관 폴더로 가져오지 못했습니다.":@[@"ZIPファイルをアプリの保存先に取り込めませんでした。", @"The ZIP file could not be imported into app storage."]
    }; });
    NSArray<NSString *> *row = catalog[source];
    return row ? row[(NSUInteger)interfaceLanguageIndex - 1] : source;
}
static void refreshFailureAlert(void);

static BOOL gameWindowCandidate(UIWindow *window) {
    // Ignore our independent windows and UIKit keyboard/alert windows. Unity's
    // game window is normal-level, including under PlayCover.
    return window != failureWindow && window != launcherWindow
        && window.windowLevel <= UIWindowLevelNormal + 0.5;
}
static UIWindow *gameWindow(void) {
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows)
            if (gameWindowCandidate(window) && window.isKeyWindow && !window.hidden) return window;
    }
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows)
            if (gameWindowCandidate(window) && !window.hidden && window.rootViewController) return window;
    }
    // Unity 6.1.1 uses a classic UIApplicationDelegate and may have no scenes.
    for (UIWindow *window in UIApplication.sharedApplication.windows)
        if (gameWindowCandidate(window) && window.isKeyWindow && !window.hidden) return window;
    for (UIWindow *window in UIApplication.sharedApplication.windows)
        if (gameWindowCandidate(window) && !window.hidden && window.rootViewController) return window;
    return nil;
}
static UIWindowScene *windowScene(void) {
    UIWindowScene *gameScene = gameWindow().windowScene;
    if (gameScene) return gameScene;
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes)
        if ([scene isKindOfClass:UIWindowScene.class] && scene.activationState == UISceneActivationStateForegroundActive)
            return (UIWindowScene *)scene;
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes)
        if ([scene isKindOfClass:UIWindowScene.class] && scene.activationState != UISceneActivationStateUnattached)
            return (UIWindowScene *)scene;
    return nil;
}
static UIViewController *presenter(void) {
    UIViewController *controller = gameWindow().rootViewController;
    while (controller.presentedViewController && !controller.presentedViewController.isBeingDismissed)
        controller = controller.presentedViewController;
    return controller;
}
static NSString *encode(id object) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:object options:0 error:NULL];
    return data && data.length <= maxJSON ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : nil;
}

@interface IDSettingsController : UIViewController <WKScriptMessageHandler, WKNavigationDelegate, UIDocumentPickerDelegate, UIAdaptivePresentationControllerDelegate>
@property (nonatomic,strong) WKWebView *web;
@property (nonatomic,strong) NSURL *page;
@property (nonatomic,copy) NSDictionary *pendingImport;
@property (nonatomic) BOOL pendingExport;
@property (nonatomic,copy) NSString *lastExportPath;
@property (nonatomic) BOOL launcherMode;
@property (nonatomic,strong) UIStackView *nativeHeader;
@property (nonatomic,strong) UIStackView *actionRow;
@property (nonatomic,strong) UILabel *nativeTitle;
@property (nonatomic,strong) UILabel *launcherStatus;
@property (nonatomic,strong) UILabel *launcherHint;
@property (nonatomic,strong) NSLayoutConstraint *headerTopConstraint;
@property (nonatomic,strong) NSLayoutConstraint *headerLeadingConstraint;
@property (nonatomic,strong) NSLayoutConstraint *headerTrailingConstraint;
@property (nonatomic,strong) NSLayoutConstraint *actionHeightConstraint;
@property (nonatomic,strong) NSLayoutConstraint *webTopConstraint;
@property (nonatomic) CGSize lastLayoutSize;
@property (nonatomic,strong) UIButton *serverStartButton;
@property (nonatomic,strong) UIButton *gameStartButton;
@property (nonatomic,strong) UIButton *returnButton;
- (void)event:(NSString *)json;
- (void)releaseWeb;
- (void)exportPath:(NSString *)path;
- (void)retireExport;
- (void)closeSettings;
- (void)startGame;
- (void)startServer;
- (void)updateServerReady;
- (void)updateLocalizedText;
- (void)updateCompactLayout;
- (UIButton *)headerButton:(NSString *)identifier action:(SEL)action primary:(BOOL)primary;
- (void)dispatchRequest:(NSDictionary *)request;
- (void)sendRequest:(NSDictionary *)request;
- (void)sendReply:(NSNumber *)identifier json:(NSString *)json;
- (void)localFailure:(NSNumber *)identifier message:(NSString *)message;
@end
static __weak IDSettingsController *settingsController;
static __weak IDSettingsController *launcherController;

@implementation IDSettingsController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.title = localized(self.launcherMode ? @"아이프라 서버" : @"아이프라 서버 설정");
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    [self.navigationController setNavigationBarHidden:YES animated:NO];
    _serverStartButton = [self headerButton:@"idoly.server-start" action:@selector(startServer) primary:NO];
    if (self.launcherMode) {
        _gameStartButton = [self headerButton:@"idoly.game-start" action:@selector(startGame) primary:YES];
        _gameStartButton.enabled = NO;
    } else {
        _returnButton = [self headerButton:@"idoly.server-close" action:@selector(closeSettings) primary:YES];
    }
    _page = [NSBundle.mainBundle.bundleURL URLByAppendingPathComponent:@"LocalServer/settings/index.html"];
    WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
    configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    [configuration.userContentController addScriptMessageHandler:self name:@"idolyServer"];
    _web = [[WKWebView alloc] initWithFrame:self.view.bounds configuration:configuration];
    _web.translatesAutoresizingMaskIntoConstraints = NO;
    _web.navigationDelegate = self; [self.view addSubview:_web];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    _nativeTitle = [UILabel new];
    _nativeTitle.numberOfLines = 0;
    _nativeTitle.accessibilityIdentifier = @"idoly.native-title";
    _nativeTitle.accessibilityTraits |= UIAccessibilityTraitHeader;
    _actionRow = [[UIStackView alloc] initWithArrangedSubviews:@[_serverStartButton, _gameStartButton ?: _returnButton]];
    _actionRow.axis = UILayoutConstraintAxisHorizontal;
    _actionRow.distribution = UIStackViewDistributionFillEqually;
    _actionRow.alignment = UIStackViewAlignmentFill;
    _actionRow.accessibilityIdentifier = @"idoly.native-actions";
    _actionHeightConstraint = [_actionRow.heightAnchor constraintEqualToConstant:44];
    _launcherStatus = [UILabel new];
    _launcherStatus.numberOfLines = 0;
    _launcherStatus.accessibilityIdentifier = @"idoly.server-status";
    _launcherStatus.accessibilityTraits |= UIAccessibilityTraitUpdatesFrequently;
    _launcherHint = [UILabel new];
    _launcherHint.textColor = UIColor.secondaryLabelColor; _launcherHint.numberOfLines = 0;
    _launcherHint.accessibilityIdentifier = @"idoly.server-hint";
    for (UILabel *label in @[_nativeTitle, _launcherStatus, _launcherHint]) {
        label.adjustsFontForContentSizeCategory = YES;
        [label setContentCompressionResistancePriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical];
    }
    _nativeHeader = [[UIStackView alloc] initWithArrangedSubviews:@[_nativeTitle, _actionRow, _launcherStatus, _launcherHint]];
    _nativeHeader.axis = UILayoutConstraintAxisVertical;
    _nativeHeader.translatesAutoresizingMaskIntoConstraints = NO;
    _nativeHeader.accessibilityIdentifier = @"idoly.native-header";
    [self.view addSubview:_nativeHeader];
    _headerTopConstraint = [_nativeHeader.topAnchor constraintEqualToAnchor:safe.topAnchor constant:12];
    _headerLeadingConstraint = [_nativeHeader.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16];
    _headerTrailingConstraint = [_nativeHeader.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16];
    _webTopConstraint = [_web.topAnchor constraintEqualToAnchor:_nativeHeader.bottomAnchor constant:12];
    [NSLayoutConstraint activateConstraints:@[
        _headerTopConstraint,
        _headerLeadingConstraint,
        _headerTrailingConstraint,
        _actionHeightConstraint,
        _webTopConstraint,
        [_web.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor],
        [_web.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [_web.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor]]];
    [self updateLocalizedText];
    [self updateCompactLayout];
    [_web loadFileURL:_page allowingReadAccessToURL:_page.URLByDeletingLastPathComponent];
}
- (UIButton *)headerButton:(NSString *)identifier action:(SEL)action primary:(BOOL)primary {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
    button.accessibilityIdentifier = identifier;
    button.titleLabel.numberOfLines = 0;
    button.titleLabel.lineBreakMode = NSLineBreakByWordWrapping;
    button.titleLabel.textAlignment = NSTextAlignmentCenter;
    button.titleLabel.adjustsFontForContentSizeCategory = YES;
    button.backgroundColor = primary ? UIColor.systemBlueColor : UIColor.secondarySystemBackgroundColor;
    [button setTitleColor:primary ? UIColor.whiteColor : UIColor.systemBlueColor forState:UIControlStateNormal];
    [button setTitleColor:UIColor.secondaryLabelColor forState:UIControlStateDisabled];
    [button addTarget:self action:action forControlEvents:UIControlEventTouchUpInside];
    return button;
}
- (void)updateServerReady {
    _gameStartButton.enabled = serverReady && !serverBusy && gameStartAvailable;
    _serverStartButton.enabled = !serverReady && !serverBusy;
    [_serverStartButton setTitle:localized(serverReady ? @"서버 실행 중" : serverBusy ? @"서버 준비 중"
        : serverAttempted ? @"다시 시도" : @"서버 시작") forState:UIControlStateNormal];
    _serverStartButton.alpha = _serverStartButton.enabled ? 1.0 : 0.65;
    _gameStartButton.alpha = _gameStartButton.enabled ? 1.0 : 0.65;
    _launcherStatus.text = localized(serverReadyStatus.length ? serverReadyStatus
        : (serverReady ? @"서버가 준비되었습니다." : serverBusy ? @"서버를 준비하고 있습니다…"
            : @"서버가 실행 중이 아닙니다. ‘서버 시작’을 눌러 주세요."));
    BOOL healthyStatus = serverReady && (!serverReadyStatus.length || [serverReadyStatus isEqualToString:@"서버 실행 중"]
        || [serverReadyStatus isEqualToString:@"서버가 준비되었습니다."]);
    _launcherStatus.textColor = healthyStatus ? UIColor.systemGreenColor : UIColor.labelColor;
    _lastLayoutSize = CGSizeMake(-1, -1);
    [self updateCompactLayout];
}
- (void)updateLocalizedText {
    [_gameStartButton setTitle:localized(@"게임 시작") forState:UIControlStateNormal];
    [_returnButton setTitle:localized(@"게임으로 돌아가기") forState:UIControlStateNormal];
    _launcherHint.text = localized(self.launcherMode
        ? @"준비가 끝나면 오른쪽 위의 ‘게임 시작’을 누르세요. 게임 중에는 화면 오른쪽 위 모서리를 한 손가락으로 2초간 누르면 서버 메뉴가 다시 열립니다."
        : @"이 메뉴를 닫아도 서버는 계속 실행됩니다.");
    [self updateServerReady];
}
- (void)updateCompactLayout {
    CGSize size = self.view.bounds.size;
    if (CGSizeEqualToSize(size, _lastLayoutSize)) return;
    _lastLayoutSize = size;
    // Match the web's clamp(16px, 1.05vmax, 64px). The complete native header,
    // including its row height, grows with virtual PlayCover game coordinates.
    // This runs only on UIKit layout/state/language events, never game frames.
    CGFloat base = MIN(64.0, MAX(16.0, MAX(size.width, size.height) * 0.0105));
    CGFloat scale = base / 16.0;
    BOOL compact = size.height < 540 * scale;
    _nativeTitle.hidden = compact;
    _launcherHint.hidden = compact;
    _nativeHeader.spacing = 6 * scale;
    _actionRow.spacing = 12 * scale;
    _headerTopConstraint.constant = (compact ? 6 : 12) * scale;
    _headerLeadingConstraint.constant = 16 * scale;
    _headerTrailingConstraint.constant = -16 * scale;
    _webTopConstraint.constant = (compact ? 6 : 12) * scale;
    _nativeTitle.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleTitle2]
        scaledFontForFont:[UIFont systemFontOfSize:22 * scale weight:UIFontWeightBold]];
    _launcherStatus.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline]
        scaledFontForFont:[UIFont systemFontOfSize:17 * scale weight:UIFontWeightSemibold]];
    _launcherHint.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleFootnote]
        scaledFontForFont:[UIFont systemFontOfSize:13 * scale]];
    UIFont *buttonFont = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline]
        scaledFontForFont:[UIFont systemFontOfSize:17 * scale weight:UIFontWeightSemibold]];
    CGFloat usableWidth = MAX(1, size.width - self.view.safeAreaInsets.left - self.view.safeAreaInsets.right - 32 * scale);
    CGFloat textWidth = MAX(1, (usableWidth - _actionRow.spacing) / 2 - 32 * scale);
    CGFloat rowHeight = 44 * scale;
    for (UIButton *button in @[_serverStartButton, _gameStartButton ?: _returnButton]) {
        button.titleLabel.font = buttonFont;
        button.contentEdgeInsets = UIEdgeInsetsMake(10 * scale, 16 * scale, 10 * scale, 16 * scale);
        NSString *titleText = [button titleForState:UIControlStateNormal] ?: @"";
        CGRect title = [titleText boundingRectWithSize:CGSizeMake(textWidth, CGFLOAT_MAX)
            options:NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading
            attributes:@{NSFontAttributeName:buttonFont} context:nil];
        rowHeight = MAX(rowHeight, ceil(title.size.height) + 20 * scale);
    }
    _actionHeightConstraint.constant = rowHeight;
    self.title = localized(self.launcherMode ? @"아이프라 서버" : @"아이프라 서버 설정");
    _nativeTitle.text = self.title;
}
- (void)viewWillAppear:(BOOL)animated {
    [super viewWillAppear:animated];
    [self.navigationController setNavigationBarHidden:YES animated:NO];
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    [self updateCompactLayout];
}
- (void)viewSafeAreaInsetsDidChange {
    [super viewSafeAreaInsetsDidChange];
    if (!self.isViewLoaded || !_nativeHeader) return;
    _lastLayoutSize = CGSizeMake(-1, -1);
    [self updateCompactLayout];
}
- (void)traitCollectionDidChange:(UITraitCollection *)previousTraitCollection {
    [super traitCollectionDidChange:previousTraitCollection];
    if (!self.isViewLoaded || !_nativeHeader) return;
    if (![previousTraitCollection.preferredContentSizeCategory isEqualToString:self.traitCollection.preferredContentSizeCategory]) {
        _lastLayoutSize = CGSizeMake(-1, -1);
        [self updateCompactLayout];
    }
}
- (void)startServer {
    if (serverReady || serverBusy) return;
    IDNativeDismissFailure();
    IdolyEmbeddedServerRetry();
}
- (void)startGame {
    if (self.launcherMode && serverReady && !serverBusy && gameStartAvailable) IdolyEmbeddedServerLaunchGame();
}
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; atomic_store(&settingsVisible, true); }
- (void)viewWillDisappear:(BOOL)animated { [super viewWillDisappear:animated]; atomic_store(&settingsVisible, false); }
- (void)viewDidDisappear:(BOOL)animated {
    [super viewDidDisappear:animated];
    if (self.isBeingDismissed || self.navigationController.isBeingDismissed) [self releaseWeb];
}
- (void)releaseWeb {
    atomic_store(&settingsVisible, false);
    [_web.configuration.userContentController removeScriptMessageHandlerForName:@"idolyServer"];
    [_web stopLoading]; _web.navigationDelegate = nil;
    [_web removeFromSuperview]; _web = nil;
    if (settingsController == self) settingsController = nil;
}
- (void)presentationControllerDidDismiss:(UIPresentationController *)presentationController {
    (void)presentationController; [self releaseWeb];
}
- (void)closeSettings {
    if (self.launcherMode) return; // Unity starts only through the explicit button.
    [self releaseWeb];
    [self dismissViewControllerAnimated:YES completion:nil];
}
- (void)dealloc { [_web.configuration.userContentController removeScriptMessageHandlerForName:@"idolyServer"]; }
- (void)webView:(WKWebView *)web decidePolicyForNavigationAction:(WKNavigationAction *)action
    decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    (void)web;
    BOOL local = action.request.URL.isFileURL
        && [action.request.URL.URLByStandardizingPath.path isEqualToString:_page.URLByStandardizingPath.path];
    decisionHandler(local ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
}
- (void)sendReply:(NSNumber *)identifier json:(NSString *)json {
    // An initial page request may finish before viewDidAppear. The retained
    // web view owns that reply; releaseWeb clears it when the menu is closed.
    if (!_web) return;
    NSData *bytes = [json dataUsingEncoding:NSUTF8StringEncoding];
    id value = bytes && bytes.length <= maxJSON ? [NSJSONSerialization JSONObjectWithData:bytes options:NSJSONReadingMutableContainers error:NULL] : nil;
    if ([value isKindOfClass:NSDictionary.class] && [value[@"error"] isKindOfClass:NSMutableDictionary.class]
            && [value[@"error"][@"message"] isKindOfClass:NSString.class])
        value[@"error"][@"message"] = localized(value[@"error"][@"message"]);
    NSString *array = value ? encode(@[identifier, value]) : nil;
    if (array) [_web evaluateJavaScript:[@"window.idolyServerReply.apply(null," stringByAppendingFormat:@"%@)",array] completionHandler:nil];
}
- (void)localFailure:(NSNumber *)identifier message:(NSString *)message {
    [self sendReply:identifier json:encode(@{@"id":identifier, @"ok":@NO,
        @"error":@{@"code":@"native_files", @"message":localized(message)}})];
}
- (void)dispatchRequest:(NSDictionary *)request {
    if ([request[@"action"] isEqual:@"diagnostics_copy"]) {
        // Explicit click in the trusted bundled page only. This action stays
        // available when Python/server startup is not ready or has failed.
        NSNumber *identifier = request[@"id"];
        NSString *text = request[@"text"];
        if (request.count != 3 || ![text isKindOfClass:NSString.class]) {
            [self localFailure:identifier message:@"허용되지 않은 서버 요청입니다."]; return;
        }
        NSData *bytes = text.length <= maxDiagnosticCopy ? [text dataUsingEncoding:NSUTF8StringEncoding] : nil;
        if (!bytes || bytes.length > maxDiagnosticCopy) {
            [self localFailure:identifier message:@"요청이 너무 큽니다."]; return;
        }
        NSCAssert(NSThread.isMainThread, @"Explicit clipboard actions belong to the main thread");
        @try { UIPasteboard.generalPasteboard.string = text; }
        @catch (NSException *exception) {
            (void)exception; [self localFailure:identifier message:@"진단 내용을 복사하지 못했습니다."]; return;
        }
        [self sendReply:identifier json:encode(@{@"id":identifier, @"ok":@YES, @"result":@{@"copied":@YES}})];
        return;
    }
    if (![request[@"action"] isEqual:@"resources_export"]) { [self sendRequest:request]; return; }
    // A completed export may outlive its closed settings page. Before the next
    // explicit export, retire only our own completed temporary ZIP namespace.
    // Never touch .part files or race an active host archive operation.
    NSString *statusRequest = encode(@{@"id":request[@"id"], @"action":@"status"});
    __weak typeof(self) weakSelf = self;
    IdolyEmbeddedServerCommand(statusRequest, ^(NSString *reply) {
        NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *envelope = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
        NSDictionary *status = [envelope isKindOfClass:NSDictionary.class] && [envelope[@"result"] isKindOfClass:NSDictionary.class] ? envelope[@"result"] : nil;
        NSDictionary *operation = [status[@"resource_operation"] isKindOfClass:NSDictionary.class] ? status[@"resource_operation"] : nil;
        BOOL active = [operation[@"accepted"] isEqual:@YES] && ![operation[@"ready"] isEqual:@YES];
        if (!status || active) { [weakSelf sendRequest:request]; return; }
        NSString *root = [IDNativeDataDirectory() stringByAppendingPathComponent:@"tmp/exports"];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
            NSURL *directory = root ? [NSURL fileURLWithPath:root isDirectory:YES] : nil;
            NSArray<NSURL *> *files = directory ? [NSFileManager.defaultManager contentsOfDirectoryAtURL:directory
                includingPropertiesForKeys:@[NSURLIsRegularFileKey,NSURLIsSymbolicLinkKey] options:0 error:NULL] : nil;
            NSRegularExpression *name = [NSRegularExpression regularExpressionWithPattern:@"^IdolyPride-Resources-ios-[0-9a-f]{32}\\.zip$" options:0 error:NULL];
            if (files.count <= 32) for (NSURL *url in files) {
                NSString *leaf = url.lastPathComponent; NSNumber *regular = nil, *link = nil;
                [url getResourceValue:&regular forKey:NSURLIsRegularFileKey error:NULL];
                [url getResourceValue:&link forKey:NSURLIsSymbolicLinkKey error:NULL];
                if (regular.boolValue && !link.boolValue && [name numberOfMatchesInString:leaf options:0 range:NSMakeRange(0,leaf.length)] == 1)
                    [NSFileManager.defaultManager removeItemAtURL:url error:NULL];
            }
            dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf sendRequest:request]; });
        });
    });
}
- (void)sendRequest:(NSDictionary *)request {
    NSNumber *identifier = request[@"id"];
    NSString *raw = encode(request);
    if (!raw) { [self localFailure:identifier message:@"요청이 너무 큽니다."]; return; }
    if ([request[@"action"] isEqual:@"resources_export"]) _pendingExport = YES;
    __weak typeof(self) weakSelf = self;
    IdolyEmbeddedServerCommand(raw, ^(NSString *reply) {
        IDSettingsController *strongSelf = weakSelf;
        if (!strongSelf) return;
        [strongSelf sendReply:identifier json:reply];
        if ([request[@"action"] isEqual:@"resources_export"]) {
            NSData *bytes = [reply dataUsingEncoding:NSUTF8StringEncoding];
            NSDictionary *value = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
            NSString *path = [value isKindOfClass:NSDictionary.class] && [value[@"ok"] isEqual:@YES]
                && [value[@"result"] isKindOfClass:NSDictionary.class] ? value[@"result"][@"output_path"] : nil;
            if ([value[@"result"] isKindOfClass:NSDictionary.class] && [value[@"result"][@"ready"] isEqual:@YES])
                [strongSelf exportPath:path];
            else if (![value[@"ok"] isEqual:@YES]) strongSelf.pendingExport = NO;
        }
    });
}
- (void)exportPath:(NSString *)path {
    if (!_pendingExport || ![path isKindOfClass:NSString.class] || [path isEqual:_lastExportPath]) return;
    NSString *root = [IDNativeDataDirectory() stringByAppendingPathComponent:@"tmp/exports"];
    NSURL *url = [NSURL fileURLWithPath:path]; NSNumber *regular = nil, *symlink = nil;
    [url getResourceValue:&regular forKey:NSURLIsRegularFileKey error:NULL];
    [url getResourceValue:&symlink forKey:NSURLIsSymbolicLinkKey error:NULL];
    NSString *resolvedRoot = root.stringByResolvingSymlinksInPath;
    BOOL inside = root && regular.boolValue && !symlink.boolValue && [url.pathExtension.lowercaseString isEqual:@"zip"]
        && [url.URLByResolvingSymlinksInPath.path hasPrefix:[resolvedRoot stringByAppendingString:@"/"]];
    if (inside && atomic_load(&settingsVisible) && !self.presentedViewController) {
        _pendingExport = NO; _lastExportPath = path;
        UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
            initWithURL:url inMode:UIDocumentPickerModeExportToService];
        picker.delegate = self; [self presentViewController:picker animated:YES completion:nil];
    }
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    (void)controller;
    // Main frame plus exact trusted on-disk page, checked on every message.
    if (!message.frameInfo.isMainFrame || !_web.URL.isFileURL
        || ![_web.URL.URLByStandardizingPath.path isEqual:_page.URLByStandardizingPath.path]
        || ![message.frameInfo.request.URL.URLByStandardizingPath.path isEqual:_page.URLByStandardizingPath.path]
        || ![message.body isKindOfClass:NSDictionary.class]) return;
    NSDictionary *request = message.body; NSNumber *identifier = request[@"id"]; NSString *action = request[@"action"];
    if (![identifier isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)identifier) == CFBooleanGetTypeID()
        || identifier.doubleValue != identifier.longLongValue || identifier.longLongValue < 1 || identifier.longLongValue > INT32_MAX
        || ![action isKindOfClass:NSString.class]) return;
    // Validate the clipboard payload itself, before JSON expansion or Python
    // gating; escaped text can exceed the ordinary host-envelope byte budget.
    if ([action isEqual:@"diagnostics_copy"]) { [self dispatchRequest:request]; return; }
    if (!encode(request)) { [self localFailure:identifier message:@"요청이 너무 큽니다."]; return; }
    NSSet *actions = [NSSet setWithArray:@[@"status",@"save_interface_language",@"save_options",@"save_presentation",@"save_playback",@"save_media",
        @"resources_preview",@"resources_download",@"resources_cancel",@"resources_import",@"resources_export"]];
    if (![actions containsObject:action] || request[@"path"] || request[@"output_path"]) {
        [self localFailure:identifier message:@"허용되지 않은 서버 요청입니다."]; return;
    }
    if ([action isEqual:@"resources_import"]) {
        if (_pendingImport) { [self localFailure:identifier message:@"이미 파일을 선택하고 있습니다."]; return; }
        _pendingImport = request;
        UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc]
            initWithDocumentTypes:@[@"public.zip-archive"] inMode:UIDocumentPickerModeOpen];
        picker.allowsMultipleSelection = NO; picker.delegate = self;
        [self presentViewController:picker animated:YES completion:nil];
    } else [self dispatchRequest:request];
}
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller {
    (void)controller;
    if (_pendingImport) [self localFailure:_pendingImport[@"id"] message:@"파일 선택을 취소했습니다."];
    _pendingImport = nil;
    [self retireExport];
}
- (void)retireExport {
    NSString *path = _lastExportPath; _lastExportPath = nil;
    NSString *root = [IDNativeDataDirectory() stringByAppendingPathComponent:@"tmp/exports"];
    if (!path || !root || ![path.stringByResolvingSymlinksInPath hasPrefix:[root.stringByResolvingSymlinksInPath stringByAppendingString:@"/"]]) return;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
        [NSFileManager.defaultManager removeItemAtPath:path error:NULL];
    });
}
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    (void)controller;
    NSDictionary *request = _pendingImport; _pendingImport = nil;
    if (!request) { [self retireExport]; return; } // Export picker completion.
    NSURL *source = urls.count == 1 ? urls[0] : nil;
    NSString *data = IDNativeDataDirectory();
    if (!source.isFileURL || !data || ![source.pathExtension.lowercaseString isEqual:@"zip"]) {
        [self localFailure:request[@"id"] message:@"ZIP 파일을 선택해 주세요."]; return;
    }
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
        BOOL scoped = [source startAccessingSecurityScopedResource];
        NSURL *directory = [NSURL fileURLWithPath:[data stringByAppendingPathComponent:@"imports"] isDirectory:YES];
        NSURL *destination = [directory URLByAppendingPathComponent:[NSUUID.UUID.UUIDString stringByAppendingString:@".zip"]];
        __block NSError *failure = nil;
        [NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:YES
            attributes:@{NSFilePosixPermissions:@0700} error:&failure];
        if (!failure) {
            NSFileCoordinator *coordinator = [NSFileCoordinator new];
            NSError *coordinationError = nil;
            __block NSError *copyError = nil;
            [coordinator coordinateReadingItemAtURL:source options:0 error:&coordinationError byAccessor:^(NSURL *readURL) {
                NSInputStream *in = [NSInputStream inputStreamWithURL:readURL];
                NSOutputStream *out = [NSOutputStream outputStreamWithURL:destination append:NO];
                [in open]; [out open]; uint8_t buffer[65536]; NSInteger size;
                while ((size = [in read:buffer maxLength:sizeof buffer]) > 0) {
                    if (!weakSelf) { copyError = [NSError errorWithDomain:NSCocoaErrorDomain code:NSUserCancelledError userInfo:nil]; break; }
                    NSInteger used = 0;
                    while (used < size) {
                        NSInteger n = [out write:buffer+used maxLength:(NSUInteger)(size-used)];
                        if (n <= 0) { copyError = out.streamError ?: [NSError errorWithDomain:@"IdolyImport" code:1 userInfo:nil]; break; }
                        used += n;
                    }
                    if (copyError) break;
                }
                if (size < 0) copyError = in.streamError ?: [NSError errorWithDomain:@"IdolyImport" code:2 userInfo:nil];
                [in close]; [out close];
            }];
            // Keep accessor errors separate from the NSError** ARC writeback.
            failure = coordinationError ?: copyError;
        }
        if (scoped) [source stopAccessingSecurityScopedResource];
        if (failure) [NSFileManager.defaultManager removeItemAtURL:destination error:NULL];
        dispatch_async(dispatch_get_main_queue(), ^{
            IDSettingsController *strongSelf = weakSelf;
            if (!strongSelf) {
                dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0), ^{
                    [NSFileManager.defaultManager removeItemAtURL:destination error:NULL];
                });
                return;
            }
            if (failure) [strongSelf localFailure:request[@"id"] message:@"ZIP 파일을 앱 보관 폴더로 가져오지 못했습니다."];
            else { NSMutableDictionary *approved = request.mutableCopy; approved[@"path"] = destination.path; [strongSelf dispatchRequest:approved]; }
        });
    });
}
- (void)event:(NSString *)json {
    if (!_web || !atomic_load(&settingsVisible)) return;
    NSData *bytes = [json dataUsingEncoding:NSUTF8StringEncoding];
    id object = bytes && bytes.length <= maxJSON ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
    NSString *array = object ? encode(@[object]) : nil;
    if (array) [_web evaluateJavaScript:[@"window.idolyServerEvent.apply(null," stringByAppendingFormat:@"%@)",array] completionHandler:nil];
    if ([object isKindOfClass:NSDictionary.class] && [object[@"event"] isEqual:@"resource_result"]
        && [object[@"ready"] isEqual:@YES]) [self exportPath:object[@"output_path"]];
}
@end

void IDNativeShowLauncher(void) {
    NSCAssert(NSThread.isMainThread, @"Launcher UI belongs to the main thread");
    if (launcherWindow) {
        if (!failureWindow) [launcherWindow makeKeyAndVisible];
        return;
    }
    previousGameWindow = gameWindow();
    UIWindowScene *scene = windowScene();
    CGRect initialFrame = previousGameWindow ? previousGameWindow.bounds : UIScreen.mainScreen.bounds;
    launcherWindow = scene ? [[UIWindow alloc] initWithWindowScene:scene]
        : [[UIWindow alloc] initWithFrame:initialFrame];
    launcherWindow.windowLevel = UIWindowLevelNormal + 1;
    IDSettingsController *settings = [IDSettingsController new];
    settings.launcherMode = YES;
    launcherController = settings; settingsController = settings;
    launcherWindow.rootViewController = [[UINavigationController alloc] initWithRootViewController:settings];
    [launcherWindow makeKeyAndVisible];
}
void IDNativeSetInterfaceLanguage(NSString *language) {
    NSCAssert(NSThread.isMainThread, @"Interface language belongs to the main thread");
    if (![language isKindOfClass:NSString.class] || ![@[@"system", @"ko", @"ja", @"en"] containsObject:language])
        language = @"system";
    NSInteger previous = interfaceLanguageIndex;
    interfaceLanguage = [language copy];
    interfaceLanguageIndex = resolvedInterfaceLanguage();
    IDMacSetSettingsMenuTitle(localized(@"로컬 서버 설정…"));
    if (previous == interfaceLanguageIndex) return;
    [launcherController updateLocalizedText];
    if (settingsController != launcherController)
    [settingsController updateLocalizedText];
    refreshFailureAlert();
}
void IDNativeSetGameStartAvailable(BOOL available) {
    NSCAssert(NSThread.isMainThread, @"Game startup state belongs to main thread");
    gameStartAvailable = available;
    [settingsController updateServerReady];
}
void IDNativeSetServerReady(BOOL ready, NSString *status) {
    IDNativeSetServerState(ready, NO, status);
}
void IDNativeSetServerState(BOOL ready, BOOL busy, NSString *status) {
    NSCAssert(NSThread.isMainThread, @"Launcher status belongs to the main thread");
    serverReady = ready; serverBusy = busy;
    serverAttempted = serverAttempted || ready || busy;
    serverReadyStatus = [status copy];
    [settingsController updateServerReady];
}
void IDNativeHideLauncher(void) {
    NSCAssert(NSThread.isMainThread, @"Launcher UI belongs to the main thread");
    [launcherController releaseWeb];
    [launcherWindow.rootViewController dismissViewControllerAnimated:NO completion:nil];
    launcherWindow.hidden = YES; launcherWindow.rootViewController = nil;
    launcherController = nil; launcherWindow = nil;
    UIWindow *restore = previousGameWindow; previousGameWindow = nil;
    // Embedded Unity may replace the startup placeholder while this launcher
    // is visible. Never make a hidden, released or controller-less window key.
    if (!restore || !gameWindowCandidate(restore) || restore.hidden || !restore.rootViewController)
        restore = gameWindow();
    if (restore && gameWindowCandidate(restore) && !restore.hidden && restore.rootViewController)
        [restore makeKeyWindow];
}
BOOL IDNativeLauncherVisible(void) {
    NSCAssert(NSThread.isMainThread, @"Launcher inspection belongs to the main thread");
    return launcherWindow && !launcherWindow.hidden && launcherWindow.rootViewController != nil;
}

@interface IDGestureTarget : NSObject <UIGestureRecognizerDelegate>
@property (nonatomic) BOOL attachQueued;
- (void)open:(UILongPressGestureRecognizer *)gesture;
- (void)openMenu:(id)sender;
- (void)openSettings;
- (void)attach;
- (void)scheduleAttach;
@end
@implementation IDGestureTarget
- (void)open:(UILongPressGestureRecognizer *)gesture {
    if (gesture.state == UIGestureRecognizerStateBegan) [self openSettings];
}
- (void)openMenu:(id)sender {
    (void)sender;
    if (NSThread.isMainThread) [self openSettings];
    else dispatch_async(dispatch_get_main_queue(), ^{ [self openSettings]; });
}
- (void)openSettings {
    NSCAssert(NSThread.isMainThread, @"Server settings belong to the main thread");
    if (failureWindow) return;
    if (IDNativeLauncherVisible()) { [launcherWindow makeKeyAndVisible]; return; }
    if (settingsController) return;
    UIViewController *parent = presenter(); if (!parent) return;
    IDSettingsController *settings = [IDSettingsController new]; settingsController = settings;
    UINavigationController *navigation = [[UINavigationController alloc] initWithRootViewController:settings];
    navigation.modalPresentationStyle = UIModalPresentationFullScreen;
    [parent presentViewController:navigation animated:YES completion:nil];
    navigation.presentationController.delegate = settings;
}
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)gesture shouldReceiveTouch:(UITouch *)touch {
    if (settingsController || launcherWindow || failureWindow) return NO;
    UIWindow *window = [gesture.view isKindOfClass:UIWindow.class] ? (UIWindow *)gesture.view : nil;
    if (!window || window != gameWindow() || touch.window != window || window.hidden) return NO;
    // Resolve the safe area at touch-down. There is no resize/frame observer.
    CGRect safe = UIEdgeInsetsInsetRect(window.bounds, window.safeAreaInsets);
    CGPoint point = [touch locationInView:window];
    return IDCornerContainsPoint(safe.origin.x, safe.origin.y, safe.size.width, safe.size.height, point.x, point.y);
}
- (void)attach {
    // The Mac menu can be created/replaced independently of the Unity window.
    // This is event-driven; it adds no overlay or per-frame polling.
    IDMacSetSettingsMenuTitle(localized(@"로컬 서버 설정…"));
    IDMacInstallSettingsMenu(self, @selector(openMenu:));
    UIWindow *window = gameWindow(); if (!window || !window.rootViewController) return;
    static const void *key = &key;
    if (objc_getAssociatedObject(window,key)) return;
    UILongPressGestureRecognizer *gesture = [[UILongPressGestureRecognizer alloc] initWithTarget:self action:@selector(open:)];
    gesture.name = @"idoly.server-menu-corner";
    gesture.numberOfTouchesRequired = 1; gesture.minimumPressDuration = 2.0;
    gesture.allowableMovement = 12.0; gesture.delegate = self;
    // Short taps and normal drags go straight to Unity. Only a recognized hold
    // cancels its underlying touch, avoiding a stuck game control after opening.
    gesture.delaysTouchesBegan = NO; gesture.delaysTouchesEnded = NO;
    gesture.cancelsTouchesInView = YES;
    [window addGestureRecognizer:gesture]; objc_setAssociatedObject(window,key,gesture,OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}
- (void)scheduleAttach {
    if (_attachQueued) return;
    _attachQueued = YES;
    dispatch_async(dispatch_get_main_queue(), ^{ self.attachQueued = NO; [self attach]; });
}
@end
void IDNativeInstallSettings(void) {
    static IDGestureTarget *target; static dispatch_once_t once;
    dispatch_once(&once, ^{
        target = [IDGestureTarget new];
        for (NSString *name in @[UIApplicationDidBecomeActiveNotification, UIWindowDidBecomeKeyNotification,
                @"NSApplicationDidFinishLaunchingNotification", @"NSApplicationDidBecomeActiveNotification",
                @"NSMenuDidAddItemNotification", @"NSMenuDidRemoveItemNotification"])
            [NSNotificationCenter.defaultCenter addObserverForName:name object:nil queue:NSOperationQueue.mainQueue
                usingBlock:^(NSNotification *note) { (void)note; [target scheduleAttach]; if (pendingFailure) IDNativeStartupFailure(pendingFailure); }];
        [target attach];
        [target scheduleAttach];
    });
}
void IDNativeEvent(NSString *json) {
    if (!atomic_load(&settingsVisible)) return;
    dispatch_async(dispatch_get_main_queue(), ^{ [settingsController event:json]; });
}
static UIAlertController *makeFailureAlert(NSString *message) {
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:localized(@"앱·게임 준비 실패")
        message:localized(message) preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:localized(@"다시 시도") style:UIAlertActionStyleDefault handler:^(UIAlertAction *action) {
        (void)action; IDNativeDismissFailure(); IdolyEmbeddedServerRetry();
    }]];
    return alert;
}
static void refreshFailureAlert(void) {
    UIViewController *root = failureWindow.rootViewController;
    if (!root || !pendingFailure) return;
    void (^show)(void) = ^{
        if (failureWindow.rootViewController == root && pendingFailure && !root.presentedViewController)
            [root presentViewController:makeFailureAlert(pendingFailure) animated:NO completion:nil];
    };
    if (root.presentedViewController) [root dismissViewControllerAnimated:NO completion:show];
    else show();
}
void IDNativeStartupFailure(NSString *message) {
    NSCAssert(NSThread.isMainThread, @"Startup UI belongs to main thread");
    pendingFailure = message;
    if (failureWindow) return;
    UIWindowScene *scene = launcherWindow.windowScene ?: windowScene();
    previousFailureWindow = launcherWindow ?: gameWindow();
    failureWindow = scene ? [[UIWindow alloc] initWithWindowScene:scene]
        : [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    failureWindow.windowLevel = UIWindowLevelAlert + 1; failureWindow.rootViewController = [UIViewController new];
    failureWindow.rootViewController.view.backgroundColor = UIColor.systemBackgroundColor;
    [failureWindow makeKeyAndVisible];
    [failureWindow.rootViewController presentViewController:makeFailureAlert(message) animated:YES completion:nil];
}
void IDNativeDismissFailure(void) {
    NSCAssert(NSThread.isMainThread, @"Startup UI belongs to the main thread");
    pendingFailure = nil; failureWindow.hidden = YES; failureWindow.rootViewController = nil; failureWindow = nil;
    [previousFailureWindow makeKeyWindow]; previousFailureWindow = nil;
}
