// SPDX-License-Identifier: AGPL-3.0-or-later
#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT NSString * const IDMP4SaveStateDidChangeNotification;
// Main-thread state, including asynchronous source preparation.
BOOL IDMP4CanCloseSettings(void);
void IDMP4SetInterfaceLanguage(NSString *language);
void IDMP4InstallLifecycle(void);
void IDMP4HandleRequest(NSDictionary *request, UIViewController *presenter,
                       UIWindow * _Nullable gameWindow, void (^reply)(NSString *));
NS_ASSUME_NONNULL_END
