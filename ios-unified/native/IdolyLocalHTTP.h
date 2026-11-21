#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

// Synchronous, worker-thread only. Requests only the fixed numerical-loopback
// playback endpoint, with an overall deadline clamped to ten seconds. Never
// call while holding the Python GIL. No cache, cookies, credentials or redirects.
// The result contains fixed diagnostic fields, never response text or headers.
NSDictionary *IDLocalHTTPReadiness(NSUInteger port, NSTimeInterval timeout);

NS_ASSUME_NONNULL_END
