#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import "../IdolyKeyboardLifecycle.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void Require(BOOL condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL_KEYBOARD_LIFECYCLE: %s\n", message); exit(1); }
}

@interface IDFixtureKeyboard : NSObject
@property (nonatomic, strong) NSObject *field;
+ (void)Initialize;
+ (instancetype)Instance;
+ (void)Destroy;
@end
static IDFixtureKeyboard *keyboard;
static id readerOverride;
static BOOL readerReturnsNil, unrelatedFailure;
static NSUInteger originalCalls, allocations, destroyCalls;
@implementation IDFixtureKeyboard
- (instancetype)init {
    self = [super init];
    if (self) { allocations += 1; _field = [NSObject new]; }
    return self;
}
+ (void)Initialize {
    originalCalls += 1;
    if (unrelatedFailure) [NSException raise:@"IDUnrelatedFailure" format:@"Unrelated fixture failure"];
    if (self != IDFixtureKeyboard.class) [NSException raise:@"IDWrongReceiver" format:@"Unexpected receiver"];
    if (keyboard) [NSException raise:@"IDAlreadyCreatedKeyboard" format:@"Initialize called after creating keyboard"];
    keyboard = [self new];
}
+ (instancetype)Instance {
    if (!keyboard) keyboard = [self new];
    return keyboard;
}
+ (void)Destroy { destroyCalls += 1; keyboard = nil; }
@end

@interface IDInvalidKeyboard : NSObject
+ (id)Initialize;
@end
@implementation IDInvalidKeyboard
+ (id)Initialize { return nil; }
@end
@interface IDInheritedKeyboard : IDFixtureKeyboard @end
@implementation IDInheritedKeyboard @end

static id ReadSingleton(void) { return readerReturnsNil ? nil : (readerOverride ?: keyboard); }
static id OtherReader(void) { return keyboard; }
static void ChangedInitialize(id receiver, SEL selector) { (void)receiver; (void)selector; }
static BOOL Reject(Class _Nullable keyboardClass, IDKeyboardSingletonReader _Nullable reader, NSInteger code) {
    NSError *error = nil;
    return !IDKeyboardLifecycleInstall(keyboardClass, reader, &error)
        && [error.domain isEqualToString:@"IdolyKeyboardLifecycle"] && error.code == code;
}
static BOOL Raised(NSString *name, void (^action)(void)) {
    @try { action(); }
    @catch (NSException *exception) { return [exception.name isEqualToString:name]; }
    return NO;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        Require(NSThread.isMainThread, "fixture_not_on_main");
        BOOL warm = argc == 2 && !strcmp(argv[1], "--warm");
        Require(argc == 2 && (warm || !strcmp(argv[1], "--cold")), "unsupported_fixture_arguments");
        Require(Reject(Nil, ReadSingleton, 2), "nil_class_accepted");
        Require(Reject(IDFixtureKeyboard.class, NULL, 2), "nil_reader_accepted");
        Require(Reject(object_getClass(IDFixtureKeyboard.class), ReadSingleton, 2), "metaclass_accepted");
        Require(Reject(IDInvalidKeyboard.class, ReadSingleton, 5), "invalid_abi_accepted");
        Require(Reject(IDInheritedKeyboard.class, ReadSingleton, 5), "inherited_method_mutated");
        __block BOOL offMainRejected = NO;
        dispatch_semaphore_t done = dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            offMainRejected = Reject(IDFixtureKeyboard.class, ReadSingleton, 1);
            dispatch_semaphore_signal(done);
        });
        Require(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5*NSEC_PER_SEC)) == 0
            && offMainRejected, "off_main_install_not_rejected");
        Require([IDKeyboardLifecycleInfo()[@"installed"] isEqual:@NO], "invalid_install_committed");

        Method getter = class_getClassMethod(IDFixtureKeyboard.class, @selector(Instance));
        IMP originalGetter = method_getImplementation(getter);
        IDFixtureKeyboard *before = warm ? [IDFixtureKeyboard Instance] : nil;
        NSObject *beforeField = before.field;
        Require(allocations == (warm ? 1U : 0U), "fixture_precreation_failed");
        NSError *error = nil;
        Require(IDKeyboardLifecycleInstall(IDFixtureKeyboard.class, ReadSingleton, &error) && !error,
            "valid_install_failed");
        Require(IDKeyboardLifecycleInstall(IDFixtureKeyboard.class, ReadSingleton, &error) && !error,
            "same_install_not_idempotent");
        Require(Reject(IDFixtureKeyboard.class, OtherReader, 3), "different_reader_accepted");
        Require(Reject(IDInheritedKeyboard.class, ReadSingleton, 3), "different_class_accepted");
        [IDFixtureKeyboard Initialize];
        IDFixtureKeyboard *first = [IDFixtureKeyboard Instance];
        NSObject *field = first.field;
        Require(first && field && allocations == 1 && originalCalls == (warm ? 0U : 1U),
            "initialization_did_not_follow_cold_or_warm_path");
        Require(!warm || (first == before && field == beforeField), "warm_object_or_field_replaced");
        [IDFixtureKeyboard Initialize];
        Require([IDFixtureKeyboard Instance] == first && first.field == field && allocations == 1,
            "repeated_initialize_did_not_preserve_object_and_field");
        Require(method_getImplementation(getter) == originalGetter, "public_getter_changed");

        readerOverride = [NSObject new];
        Require(Raised(@"IDAlreadyCreatedKeyboard", ^{ [IDFixtureKeyboard Initialize]; }),
            "foreign_singleton_silently_reused_or_original_assertion_suppressed");
        readerOverride = nil;
        Method initialize = class_getClassMethod(IDFixtureKeyboard.class, @selector(Initialize));
        IMP wrapper = method_getImplementation(initialize);
        Require(Raised(@"IDWrongReceiver", ^{
            ((void (*)(id, SEL))wrapper)(NSObject.class, @selector(Initialize));
        }), "other_receiver_silently_reused");
        readerReturnsNil = YES; unrelatedFailure = YES;
        Require(Raised(@"IDUnrelatedFailure", ^{ [IDFixtureKeyboard Initialize]; }),
            "unrelated_original_exception_suppressed");
        readerReturnsNil = NO; unrelatedFailure = NO;
        Require([IDFixtureKeyboard Instance] == first && first.field == field
            && allocations == 1 && destroyCalls == 0, "original_singleton_lifecycle_mutated");

        method_setImplementation(initialize, (IMP)ChangedInitialize);
        Require(Reject(IDFixtureKeyboard.class, ReadSingleton, 4)
            && method_getImplementation(initialize) == (IMP)ChangedInitialize,
            "unknown_changed_method_overwritten");
        Require([IDKeyboardLifecycleInfo()[@"installed"] isEqual:@NO], "changed_method_reported_active");
        method_setImplementation(initialize, wrapper);
        Require(IDKeyboardLifecycleInstall(IDFixtureKeyboard.class, ReadSingleton, &error),
            "same_restored_hook_not_idempotent");
        NSDictionary *lifecycle = IDKeyboardLifecycleInfo();
        Require([lifecycle[@"installed"] isEqual:@YES] && [lifecycle[@"strategy"] isEqual:@"reuse-existing"]
            && [lifecycle[@"initialize_calls"] unsignedIntegerValue] == 5
            && [lifecycle[@"original_initialize_calls"] unsignedIntegerValue] == (warm ? 3U : 4U)
            && [lifecycle[@"reused_existing_calls"] unsignedIntegerValue] == (warm ? 2U : 1U)
            && originalCalls == (warm ? 3U : 4U), "lifecycle_counters_invalid");
        NSDictionary *result = @{@"status":@"PASS", @"mode":warm ? @"warm" : @"cold",
            @"actual_macos_foundation_execution":@YES, @"iOS_Unity_or_PlayCover_execution":@NO,
            @"cold_or_warm_path_verified":@YES, @"singleton_and_field_preserved":@YES,
            @"original_getter_unchanged":@YES, @"invalid_abi_rejected":@YES,
            @"off_main_install_rejected":@YES, @"idempotent_install_verified":@YES,
            @"changed_method_rejected":@YES, @"foreign_singleton_not_reused":@YES,
            @"other_receiver_not_reused":@YES, @"unrelated_exception_propagated":@YES,
            @"no_destroy_or_reset":@YES, @"lifecycle":lifecycle};
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
        Require(json != nil, "fixture_json_failed");
        fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout);
    }
    return 0;
}
