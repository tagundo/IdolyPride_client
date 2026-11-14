#import "IdolyKeyboardLifecycle.h"
#import <objc/runtime.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

static pthread_mutex_t lifecycleLock = PTHREAD_MUTEX_INITIALIZER;
static Class expectedKeyboardClass;
static IDKeyboardSingletonReader singletonReader;
static Method initializeMethod;
static _Atomic(IMP) originalInitialize;
static _Atomic(BOOL) installed;
static _Atomic(unsigned long long) initializeCalls, originalInitializeCalls, reusedExistingCalls;

static BOOL fail(NSError **error, NSInteger code, NSString *message) {
    if (error) *error = [NSError errorWithDomain:@"IdolyKeyboardLifecycle" code:code
        userInfo:@{NSLocalizedDescriptionKey:message}];
    return NO;
}

static BOOL argumentType(Method method, unsigned index, const char *expected) {
    char *value = method_copyArgumentType(method, index);
    BOOL matches = value && !strcmp(value, expected);
    free(value); return matches;
}

static BOOL supportedInitialize(Method method) {
    if (!method || method_getNumberOfArguments(method) != 2) return NO;
    char *value = method_copyReturnType(method);
    BOOL returnsVoid = value && !strcmp(value, "v");
    free(value);
    const char *encoding = method_getTypeEncoding(method);
    return returnsVoid && encoding && !strcmp(encoding, "v16@0:8")
        && argumentType(method, 0, "@") && argumentType(method, 1, ":");
}

static Method ownInitializeMethod(Class keyboardClass) {
    unsigned count = 0;
    Method *methods = class_copyMethodList(object_getClass(keyboardClass), &count);
    Method found = NULL;
    SEL selector = sel_registerName("Initialize");
    for (unsigned index = 0; index < count; index++) {
        if (method_getName(methods[index]) == selector) { found = methods[index]; break; }
    }
    free(methods);
    return found;
}

static void initializePreservingExisting(id receiver, SEL selector) {
    // The acquire load publishes the immutable class/reader selected before
    // installing this IMP. Later calls never change that pair or the original.
    IMP original = atomic_load_explicit(&originalInitialize, memory_order_acquire);
    atomic_fetch_add_explicit(&initializeCalls, 1, memory_order_relaxed);
    if (NSThread.isMainThread && receiver == expectedKeyboardClass) {
        // ARC keeps a live object returned by the caller's read-only reader
        // alive during this check. Do not invoke +Instance: it creates state.
        id existing = singletonReader();
        if (existing && object_getClass(existing) == expectedKeyboardClass) {
            atomic_fetch_add_explicit(&reusedExistingCalls, 1, memory_order_relaxed);
            return;
        }
    }
    atomic_fetch_add_explicit(&originalInitializeCalls, 1, memory_order_relaxed);
    // Preserve the original receiver, selector, void ABI and exceptions. An
    // unknown class, off-main call or invalid singleton is never accepted as a
    // successful reuse. There is deliberately no reset, Destroy call or catch.
    ((void (*)(id, SEL))original)(receiver, selector);
}

BOOL IDKeyboardLifecycleInstall(Class keyboardClass, IDKeyboardSingletonReader reader, NSError **error) {
    if (error) *error = nil;
    if (!NSThread.isMainThread) return fail(error, 1, @"Keyboard lifecycle installation requires the main thread.");
    if (!keyboardClass || !object_isClass(keyboardClass) || class_isMetaClass(keyboardClass) || !reader)
        return fail(error, 2, @"An audited keyboard class and read-only singleton reader are required.");
    pthread_mutex_lock(&lifecycleLock);
    if (atomic_load_explicit(&installed, memory_order_acquire)) {
        BOOL same = keyboardClass == expectedKeyboardClass && reader == singletonReader;
        BOOL current = method_getImplementation(initializeMethod) == (IMP)initializePreservingExisting;
        pthread_mutex_unlock(&lifecycleLock);
        if (!same) return fail(error, 3, @"Keyboard lifecycle is already fixed to another class or reader.");
        if (!current) return fail(error, 4, @"Keyboard Initialize changed after lifecycle installation.");
        return YES;
    }
    Method method = ownInitializeMethod(keyboardClass);
    if (!supportedInitialize(method)) {
        pthread_mutex_unlock(&lifecycleLock);
        return fail(error, 5, @"Keyboard +Initialize must have the audited v16@0:8 ABI on its own class.");
    }
    IMP original = method_getImplementation(method);
    if (!original || original == (IMP)initializePreservingExisting) {
        pthread_mutex_unlock(&lifecycleLock);
        return fail(error, 6, @"Keyboard Initialize has no supported original implementation.");
    }
    expectedKeyboardClass = keyboardClass;
    singletonReader = reader;
    initializeMethod = method;
    atomic_store_explicit(&originalInitialize, original, memory_order_release);
    IMP previous = method_setImplementation(method, (IMP)initializePreservingExisting);
    if (previous != original) {
        // A competing swizzler changed the method between inspection and swap.
        // Leave that implementation in place instead of silently chaining it.
        method_setImplementation(method, previous);
        pthread_mutex_unlock(&lifecycleLock);
        return fail(error, 7, @"Keyboard Initialize changed while installing its lifecycle hook.");
    }
    atomic_store_explicit(&installed, YES, memory_order_release);
    pthread_mutex_unlock(&lifecycleLock);
    return YES;
}

NSDictionary *IDKeyboardLifecycleInfo(void) {
    pthread_mutex_lock(&lifecycleLock);
    BOOL active = atomic_load_explicit(&installed, memory_order_acquire)
        && method_getImplementation(initializeMethod) == (IMP)initializePreservingExisting;
    NSDictionary *info = @{@"installed":@(active), @"strategy":@"reuse-existing",
        @"initialize_calls":@(atomic_load_explicit(&initializeCalls, memory_order_relaxed)),
        @"original_initialize_calls":@(atomic_load_explicit(&originalInitializeCalls, memory_order_relaxed)),
        @"reused_existing_calls":@(atomic_load_explicit(&reusedExistingCalls, memory_order_relaxed))};
    pthread_mutex_unlock(&lifecycleLock);
    return info;
}
