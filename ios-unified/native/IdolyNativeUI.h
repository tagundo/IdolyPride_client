#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
// Launcher/window lifecycle is owned by the main thread.
void IDNativeShowLauncher(void);
void IDNativeSetServerReady(BOOL ready, NSString * _Nullable status);
void IDNativeHideLauncher(void);
BOOL IDNativeLauncherVisible(void);
void IDNativeInstallSettings(void);
void IDNativeEvent(NSString *json);
void IDNativeStartupFailure(NSString *message);
void IDNativeDismissFailure(void);
NSString * _Nullable IDNativeDataDirectory(void);
NS_ASSUME_NONNULL_END
