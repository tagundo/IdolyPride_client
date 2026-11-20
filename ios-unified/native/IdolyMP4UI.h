// SPDX-License-Identifier: AGPL-3.0-or-later
#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
void IDMP4SetInterfaceLanguage(NSString *language);
void IDMP4InstallLifecycle(void);
void IDMP4HandleRequest(NSDictionary *request, UIViewController *presenter,
                       UIWindow * _Nullable gameWindow, void (^reply)(NSString *));
NS_ASSUME_NONNULL_END
