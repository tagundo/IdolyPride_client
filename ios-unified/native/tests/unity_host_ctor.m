#import "../IdolyUnityHost.h"
#import <objc/runtime.h>
#include <stdlib.h>
#include <string.h>

static unsigned constructorCalls, readyCalls;
static BOOL constructorInstalled;
static NSString *constructorError;

@interface IDUnityHostFixtureConstructor : NSObject
+ (NSDictionary *)fixtureInfo;
@end
@implementation IDUnityHostFixtureConstructor
+ (NSDictionary *)fixtureInfo {
    return @{@"constructor_calls":@(constructorCalls), @"ready_calls":@(readyCalls),
        @"installed":@(constructorInstalled), @"error":constructorError ?: NSNull.null};
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

__attribute__((constructor))
static void InstallBeforeExecutableMain(void) {
    @autoreleasepool {
        ++constructorCalls;
        NSString *error = nil;
        constructorInstalled = IDUnityHostInstall(ReadyFromFixtureDylib, &error);
        constructorError = error;
    }
}
