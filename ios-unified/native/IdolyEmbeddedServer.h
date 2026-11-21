#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
// Inspection/retry/command entry points also used by the independent UIKit probe.
FOUNDATION_EXPORT __attribute__((visibility("default"))) NSString *IdolyEmbeddedServerStatusJSON(void);
FOUNDATION_EXPORT __attribute__((visibility("default"))) void IdolyEmbeddedServerRetry(void);
// The launcher calls this only after the user presses Game Start. Readiness
// alone never starts Unity; premature/duplicate requests are ignored.
FOUNDATION_EXPORT __attribute__((visibility("default"))) void IdolyEmbeddedServerLaunchGame(void);
// Completion always runs on the main queue; Python never runs on that queue.
FOUNDATION_EXPORT __attribute__((visibility("default"))) void IdolyEmbeddedServerCommand(NSString *request,
                                                  void (^completion)(NSString *reply));
// Fixed NIST fixtures only; no executable source or caller-provided crypto data.
FOUNDATION_EXPORT __attribute__((visibility("default"))) void IdolyEmbeddedServerCryptoSelfTest(void (^completion)(NSString *reply));
// Trusted bundled settings/native overlay only. Never forwarded to HTTP/Python commands.
FOUNDATION_EXPORT void IdolyEmbeddedServerMP4Command(NSString *request, void (^completion)(NSString *reply));
FOUNDATION_EXPORT void IdolyEmbeddedServerMP4Export(void (^completion)(NSURL * _Nullable file, NSString * _Nullable error));
// A queue job ID is resolved natively to a completed, owned library output.
// Callers never select an output filename or filesystem path.
FOUNDATION_EXPORT void IdolyEmbeddedServerMP4ExportJob(NSString * _Nullable jobID,
    void (^completion)(NSURL * _Nullable file, NSString * _Nullable error));
// Synchronous native-only pause request before Unity's original lifecycle runs.
// Returning to the foreground never overrides an explicit user pause.
FOUNDATION_EXPORT void IdolyEmbeddedServerMP4SetLifecycleActive(BOOL active);
// Fresh native snapshot only; safe during a lifecycle notification on main.
// No interpreter work, Unity calls, or visible progress view is required.
FOUNDATION_EXPORT BOOL IdolyEmbeddedServerMP4IsFinishing(void);
NS_ASSUME_NONNULL_END
