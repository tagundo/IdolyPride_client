#import "IdolyClientData.h"
#import <objc/runtime.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

NSString * const IDClientDataBundleIdentifier = @"local.idoly.client-data";
static const char clientDataIdentifier[] = "local.idoly.client-data";
static pthread_mutex_t selectionLock = PTHREAD_MUTEX_INITIALIZER;
static NSBundle *selectedBundle;
static NSString *selectedPath, *selectedLanguage;
static id selectedFramework;
static BOOL committed, nativeRegistration, loadSucceeded, fixedFallback;
static _Atomic(IMP) originalIdentifierLookup;
#ifdef IDOLY_CLIENT_DATA_TESTING
static BOOL forceFallback;
void IDClientDataForceFixedFallbackForTests(void) { forceFallback = YES; }
#endif

static BOOL fail(NSError **error, NSInteger code, NSString *message) {
    if (error) *error = [NSError errorWithDomain:@"IdolyClientData" code:code
        userInfo:@{NSLocalizedDescriptionKey:message}];
    return NO;
}
static BOOL directoryWithoutLink(NSURL *url) {
    // A trailing slash makes POSIX lstat follow a directory symlink. Strip only
    // that suffix, preserving raw path components for the pre-resolution guard.
    NSString *path = url.path;
    while (path.length > 1 && [path hasSuffix:@"/"]) path = [path substringToIndex:path.length - 1];
    struct stat info;
    return url.isFileURL && lstat(path.fileSystemRepresentation, &info) == 0
        && S_ISDIR(info.st_mode) && !S_ISLNK(info.st_mode);
}
static BOOL matchingBundle(NSBundle *bundle, NSString *path) {
    return [bundle.bundleIdentifier isEqualToString:IDClientDataBundleIdentifier]
        && [bundle.bundlePath.stringByResolvingSymlinksInPath isEqualToString:path];
}
static BOOL argumentType(Method method, unsigned index, const char *expected) {
    char *value = method_copyArgumentType(method, index);
    BOOL matches = value && !strcmp(value, expected);
    free(value); return matches;
}
static BOOL returnType(Method method, const char *expected) {
    char *value = method_copyReturnType(method);
    BOOL matches = value && !strcmp(value, expected);
    free(value); return matches;
}
static NSBundle *fixedIdentifierLookup(id self, SEL selector, NSString *identifier) {
    if ([identifier isKindOfClass:NSString.class]
            && [identifier isEqualToString:IDClientDataBundleIdentifier]) {
        pthread_mutex_lock(&selectionLock);
        NSBundle *bundle = selectedBundle;
        pthread_mutex_unlock(&selectionLock);
        if (bundle) return bundle;
    }
    IMP original = atomic_load(&originalIdentifierLookup);
    return original ? ((NSBundle *(*)(id, SEL, NSString *))original)(self, selector, identifier) : nil;
}
static BOOL installFixedLookup(NSError **error) {
    if (fixedFallback) return YES;
    Method method = class_getClassMethod(NSBundle.class, @selector(bundleWithIdentifier:));
    if (!method || method_getNumberOfArguments(method) != 3 || !returnType(method, "@")
            || !argumentType(method, 0, "@") || !argumentType(method, 1, ":") || !argumentType(method, 2, "@"))
        return fail(error, 9, @"NSBundle lookup signature is unsupported.");
    // Only the fixed identifier above is special. Every other identifier keeps
    // the original Foundation implementation and arguments unchanged.
    atomic_store(&originalIdentifierLookup, method_getImplementation(method));
    IMP previous = method_setImplementation(method, (IMP)fixedIdentifierLookup);
    atomic_store(&originalIdentifierLookup, previous);
    pthread_mutex_lock(&selectionLock); fixedFallback = YES; pthread_mutex_unlock(&selectionLock);
    return YES;
}

BOOL IDClientDataSelectBundle(NSURL *bundleURL, NSURL *allowedRootURL,
                            id auditedUnityFramework, NSError **error) {
    if (error) *error = nil;
    if (!NSThread.isMainThread) return fail(error, 1, @"Client data selection requires the main thread.");
    if (![bundleURL isKindOfClass:NSURL.class] || ![allowedRootURL isKindOfClass:NSURL.class]
            || !bundleURL.isFileURL || !allowedRootURL.isFileURL)
        return fail(error, 2, @"Client data requires owned file URLs.");
    // Check caller-supplied final nodes before URL normalization can remove
    // path components. System-owned ancestor aliases are outside this root.
    if (!directoryWithoutLink(allowedRootURL) || !directoryWithoutLink(bundleURL))
        return fail(error, 3, @"Client data root and bundle must be non-symlink directories.");
    NSURL *root = allowedRootURL.URLByStandardizingPath.URLByResolvingSymlinksInPath;
    NSURL *url = bundleURL.URLByStandardizingPath.URLByResolvingSymlinksInPath;
    NSString *leaf = url.lastPathComponent;
    if (![@[@"ja.bundle", @"ko.bundle", @"en.bundle"] containsObject:leaf]
            || ![url.URLByDeletingLastPathComponent.path isEqualToString:root.path]
            || !directoryWithoutLink(root) || !directoryWithoutLink(url))
        return fail(error, 3, @"Client bundle must be a direct, non-symlink language directory under its owned root.");
    NSURL *dataURL = [url URLByAppendingPathComponent:@"Data" isDirectory:YES];
    NSURL *infoURL = [url URLByAppendingPathComponent:@"Info.plist"];
    struct stat info;
    if (!directoryWithoutLink(dataURL) || lstat(infoURL.fileSystemRepresentation, &info) != 0
            || !S_ISREG(info.st_mode) || S_ISLNK(info.st_mode) || info.st_size < 1 || info.st_size > 65536)
        return fail(error, 4, @"Client bundle Data/Info.plist is missing, linked or invalid.");
    NSData *raw = [NSData dataWithContentsOfURL:infoURL options:0 error:NULL];
    id plist = raw && raw.length <= 65536 ? [NSPropertyListSerialization propertyListWithData:raw
        options:NSPropertyListImmutable format:NULL error:NULL] : nil;
    if (![plist isKindOfClass:NSDictionary.class]
            || ![plist[@"CFBundleIdentifier"] isEqual:IDClientDataBundleIdentifier]
            || ![plist[@"CFBundlePackageType"] isEqual:@"BNDL"]
            || ![plist[@"IdolyClientLanguage"] isEqual:leaf.stringByDeletingPathExtension]
            || plist[@"CFBundleExecutable"] || plist[@"NSPrincipalClass"])
        return fail(error, 5, @"Client data must be the fixed resource-only bundle.");
    NSString *path = url.path.stringByResolvingSymlinksInPath;
    NSString *rootPath = root.path.stringByResolvingSymlinksInPath;
    if (![path.stringByDeletingLastPathComponent isEqualToString:rootPath])
        return fail(error, 3, @"Client bundle escapes its owned root.");
    if (committed) {
        if ([path isEqualToString:selectedPath] && auditedUnityFramework == selectedFramework) return YES;
        return fail(error, 6, @"Client data is fixed for this app launch.");
    }
    SEL selector = sel_registerName("setDataBundleId:");
    Method setter = auditedUnityFramework ? class_getInstanceMethod(object_getClass(auditedUnityFramework), selector) : NULL;
    if (!setter || method_getNumberOfArguments(setter) != 3 || !returnType(setter, "v")
            || !argumentType(setter, 0, "@") || !argumentType(setter, 1, ":") || !argumentType(setter, 2, "r*"))
        return fail(error, 7, @"Audited Unity setDataBundleId: signature is unsupported.");
    NSBundle *bundle = [NSBundle bundleWithURL:url];
    if (!matchingBundle(bundle, path)) return fail(error, 8, @"Foundation could not open the prepared resource bundle.");
    NSError *loadError = nil;
    BOOL loaded = [bundle loadAndReturnError:&loadError];
    (void)loadError; // Resource-only bundles may not have executable code to load.
    BOOL registered = matchingBundle([NSBundle bundleWithIdentifier:IDClientDataBundleIdentifier], path);
    BOOL needsFallback = !registered;
#ifdef IDOLY_CLIENT_DATA_TESTING
    needsFallback = needsFallback || forceFallback;
#endif
    pthread_mutex_lock(&selectionLock);
    selectedBundle = bundle;
    pthread_mutex_unlock(&selectionLock);
    if (needsFallback && !installFixedLookup(error)) {
        pthread_mutex_lock(&selectionLock); selectedBundle = nil; pthread_mutex_unlock(&selectionLock);
        return NO;
    }
    if (!matchingBundle([NSBundle bundleWithIdentifier:IDClientDataBundleIdentifier], path)) {
        pthread_mutex_lock(&selectionLock); selectedBundle = nil; pthread_mutex_unlock(&selectionLock);
        return fail(error, 10, @"Selected client bundle did not resolve through its identifier.");
    }
    @try {
        // Static bytes outlive Unity's stored const-char pointer. The caller
        // validated this method's original image and instruction prefix.
        ((void (*)(id, SEL, const char *))method_getImplementation(setter))
            (auditedUnityFramework, selector, clientDataIdentifier);
    } @catch (NSException *exception) {
        (void)exception;
        pthread_mutex_lock(&selectionLock); selectedBundle = nil; pthread_mutex_unlock(&selectionLock);
        return fail(error, 11, @"Unity rejected the selected client data bundle.");
    }
    pthread_mutex_lock(&selectionLock);
    selectedPath = path; selectedLanguage = leaf.stringByDeletingPathExtension;
    selectedFramework = auditedUnityFramework; committed = YES;
    nativeRegistration = registered; loadSucceeded = loaded;
    pthread_mutex_unlock(&selectionLock);
    return YES;
}

NSDictionary *IDClientDataSelectionInfo(void) {
    pthread_mutex_lock(&selectionLock);
    NSDictionary *info = @{@"selected":@(committed), @"bundle_identifier":IDClientDataBundleIdentifier,
        @"language":selectedLanguage ?: (id)NSNull.null, @"native_registration":@(nativeRegistration),
        @"resource_bundle_load_succeeded":@(loadSucceeded), @"fixed_identifier_fallback":@(fixedFallback)};
    pthread_mutex_unlock(&selectionLock);
    return info;
}
