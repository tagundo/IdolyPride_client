#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

// Return the audited singleton without creating, replacing or clearing it.
// The caller guarantees a live object (or nil), with lifecycle changes on the
// main thread. Reading an arbitrary or dangling object address is unsupported.
typedef id _Nullable (*IDKeyboardSingletonReader)(void);

// Main-thread only. The caller must first pin the class, original IMP/image and
// singleton storage to its audited Unity build. This helper checks the method
// ABI and only reuses an already-created instance of that exact class. Nil and
// unexpected states retain the original Initialize implementation's behavior.
BOOL IDKeyboardLifecycleInstall(Class _Nullable keyboardClass, IDKeyboardSingletonReader _Nullable reader,
                                NSError * _Nullable * _Nullable error);
NSDictionary *IDKeyboardLifecycleInfo(void);

NS_ASSUME_NONNULL_END
