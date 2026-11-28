#import "../IdolyUnityHost.h"
#import <objc/runtime.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>

static unsigned constructorCalls, readyCalls;
static BOOL constructorInstalled;
static BOOL sigpipeDefaultBeforeInstall, sigpipeIgnoredAfterInstall, otherSignalsPreserved;
static NSString *constructorError;

@interface IDUnityHostFixtureConstructor : NSObject
+ (NSDictionary *)fixtureInfo;
@end
@implementation IDUnityHostFixtureConstructor
+ (NSDictionary *)fixtureInfo {
    return @{@"constructor_calls":@(constructorCalls), @"ready_calls":@(readyCalls),
        @"installed":@(constructorInstalled),
        @"sigpipe_default_before_install":@(sigpipeDefaultBeforeInstall),
        @"sigpipe_ignored_after_install":@(sigpipeIgnoredAfterInstall),
        @"other_signal_handlers_preserved":@(otherSignalsPreserved),
        @"error":constructorError ?: NSNull.null};
}
@end

static void ReadyFromFixtureDylib(void) {
    ++readyCalls;
    Class observer = objc_getClass("IDUnityHostFixtureObserver");
    SEL selector = sel_registerName("hostReady");
    Method method = observer ? class_getClassMethod(observer, selector) : NULL;
    char *type = method ? method_copyReturnType(method) : NULL;
    BOOL valid = method && type && !strcmp(type, "v") && method_getNumberOfArguments(method) == 2;
    free(type);
    if (!valid) abort();
    ((void (*)(id, SEL))method_getImplementation(method))((id)observer, selector);
}

static BOOL SameSignalAction(const struct sigaction *left, const struct sigaction *right) {
    if (left->sa_handler != right->sa_handler || left->sa_flags != right->sa_flags) return NO;
    for (int number = 1; number < NSIG; ++number)
        if (sigismember(&left->sa_mask, number) != sigismember(&right->sa_mask, number)) return NO;
    return YES;
}

__attribute__((constructor))
static void InstallBeforeExecutableMain(void) {
    @autoreleasepool {
        ++constructorCalls;
        struct sigaction firstBefore, secondBefore, firstAfter, secondAfter, pipeAction;
        BOOL snapshots = sigaction(SIGUSR1, NULL, &firstBefore) == 0
            && sigaction(SIGUSR2, NULL, &secondBefore) == 0;
        BOOL reset = signal(SIGPIPE, SIG_DFL) != SIG_ERR;
        sigpipeDefaultBeforeInstall = reset && sigaction(SIGPIPE, NULL, &pipeAction) == 0
            && pipeAction.sa_handler == SIG_DFL;
        if (!snapshots || !sigpipeDefaultBeforeInstall) {
            constructorError = @"fixture_sigpipe_default_setup_failed";
            return;
        }
        NSString *error = nil;
        constructorInstalled = IDUnityHostInstall(ReadyFromFixtureDylib, &error);
        constructorError = error;
        sigpipeIgnoredAfterInstall = sigaction(SIGPIPE, NULL, &pipeAction) == 0
            && pipeAction.sa_handler == SIG_IGN;
        otherSignalsPreserved = sigaction(SIGUSR1, NULL, &firstAfter) == 0
            && sigaction(SIGUSR2, NULL, &secondAfter) == 0
            && SameSignalAction(&firstBefore, &firstAfter) && SameSignalAction(&secondBefore, &secondAfter);
        if (!sigpipeIgnoredAfterInstall || !otherSignalsPreserved)
            constructorError = @"fixture_sigpipe_install_verification_failed";
    }
}
