#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
// Inspection/retry/command entry points also used by the independent UIKit probe.
FOUNDATION_EXPORT __attribute__((visibility("default"))) NSString *IdolyEmbeddedServerStatusJSON(void);
FOUNDATION_EXPORT __attribute__((visibility("default"))) void IdolyEmbeddedServerRetry(void);
// Completion always runs on the main queue; Python never runs on that queue.
FOUNDATION_EXPORT __attribute__((visibility("default"))) void IdolyEmbeddedServerCommand(NSString *request,
                                                  void (^completion)(NSString *reply));
// Fixed NIST fixtures only; no executable source or caller-provided crypto data.
FOUNDATION_EXPORT __attribute__((visibility("default"))) void IdolyEmbeddedServerCryptoSelfTest(void (^completion)(NSString *reply));
NS_ASSUME_NONNULL_END
