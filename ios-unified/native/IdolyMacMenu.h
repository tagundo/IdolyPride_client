#import <Foundation/Foundation.h>

// Install an entry in an already available Mac application menu. No AppKit
// symbols are linked by the iOS framework. Returns NO on iPhone/iPad, when a
// menu is not ready, for an invalid action, or when called off the main thread.
// The caller keeps target alive; NSMenuItem's action target is not retained.
FOUNDATION_EXPORT BOOL IDMacInstallSettingsMenu(id _Nullable target, SEL _Nullable action);
