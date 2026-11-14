#import <Foundation/Foundation.h>
void IDNativeInstallSettings(void);
void IDNativeEvent(NSString *json);
void IDNativeStartupFailure(NSString *message);
void IDNativeDismissFailure(void);
NSString *IDNativeDataDirectory(void);
