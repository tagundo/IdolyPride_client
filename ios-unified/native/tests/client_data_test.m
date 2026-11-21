#import <Foundation/Foundation.h>
#import "../IdolyClientData.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void Require(BOOL condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL_CLIENT_DATA: %s\n", message); exit(1); }
}
@interface IDFixtureUnity : NSObject
@property (nonatomic) const char *receivedIdentifier;
@property (nonatomic) NSUInteger setterCalls;
- (void)setDataBundleId:(const char *)identifier;
@end
@implementation IDFixtureUnity
- (void)setDataBundleId:(const char *)identifier {
    self.receivedIdentifier = identifier; self.setterCalls += 1;
}
@end
@interface IDInvalidUnity : NSObject
- (void)setDataBundleId:(id)identifier;
@end
@implementation IDInvalidUnity
- (void)setDataBundleId:(id)identifier { (void)identifier; }
@end

static void WriteInfo(NSURL *bundle, NSDictionary *changes) {
    NSMutableDictionary *info = [@{@"CFBundleIdentifier":IDClientDataBundleIdentifier,
        @"CFBundlePackageType":@"BNDL", @"CFBundleVersion":@"1",
        @"IdolyClientLanguage":bundle.lastPathComponent.stringByDeletingPathExtension} mutableCopy];
    [info addEntriesFromDictionary:changes];
    NSData *raw = [NSPropertyListSerialization dataWithPropertyList:info
        format:NSPropertyListXMLFormat_v1_0 options:0 error:NULL];
    Require(raw && [raw writeToURL:[bundle URLByAppendingPathComponent:@"Info.plist"]
        options:NSDataWritingAtomic error:NULL], "fixture_info_write_failed");
}
static NSURL *MakeBundle(NSURL *root, NSString *language) {
    NSURL *bundle = [root URLByAppendingPathComponent:[language stringByAppendingString:@".bundle"] isDirectory:YES];
    NSURL *data = [bundle URLByAppendingPathComponent:@"Data" isDirectory:YES];
    Require([NSFileManager.defaultManager createDirectoryAtURL:data withIntermediateDirectories:YES
        attributes:nil error:NULL], "fixture_directory_failed");
    WriteInfo(bundle, @{});
    Require([language writeToURL:[data URLByAppendingPathComponent:@"fixture.txt"] atomically:YES
        encoding:NSUTF8StringEncoding error:NULL], "fixture_data_write_failed");
    return bundle;
}
static BOOL SamePath(NSString *left, NSString *right) {
    return [left.stringByResolvingSymlinksInPath isEqualToString:right.stringByResolvingSymlinksInPath];
}
static BOOL Reject(NSURL *bundle, NSURL *root, id unity, NSInteger code) {
    NSError *error = nil;
    BOOL accepted = IDClientDataSelectBundle(bundle, root, unity, &error);
    return !accepted && [error.domain isEqualToString:@"IdolyClientData"] && error.code == code;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        Require(NSThread.isMainThread, "fixture_not_on_main");
        BOOL forced = argc == 2 && !strcmp(argv[1], "--force-fallback");
        Require(argc == 1 || forced, "unsupported_fixture_arguments");
        if (forced) IDClientDataForceFixedFallbackForTests();
        NSURL *temporary = [[NSURL fileURLWithPath:NSTemporaryDirectory() isDirectory:YES]
            URLByAppendingPathComponent:[@"idoly-client-data-test-" stringByAppendingString:NSUUID.UUID.UUIDString]
            isDirectory:YES];
        NSURL *root = [temporary URLByAppendingPathComponent:@"client-data" isDirectory:YES];
        NSURL *ko = MakeBundle(root, @"ko"), *ja = MakeBundle(root, @"ja"), *en = MakeBundle(root, @"en");
        IDFixtureUnity *unity = [IDFixtureUnity new];
        Require(Reject(ko, temporary, unity, 3), "outside_owned_root_accepted");
        NSURL *outside = MakeBundle([temporary URLByAppendingPathComponent:@"outside" isDirectory:YES], @"ko");
        Require(Reject(outside, root, unity, 3), "sibling_root_accepted");
        NSURL *badLeaf = MakeBundle(root, @"arbitrary");
        Require(Reject(badLeaf, root, unity, 3), "non_language_leaf_accepted");
        NSURL *rootLink = [temporary URLByAppendingPathComponent:@"root-link"];
        Require([NSFileManager.defaultManager createSymbolicLinkAtURL:rootLink withDestinationURL:root error:NULL],
            "fixture_root_symlink_failed");
        Require(Reject([rootLink URLByAppendingPathComponent:@"ko.bundle"], rootLink, unity, 3), "linked_root_accepted");
        NSURL *directoryRootLink = [NSURL fileURLWithPath:rootLink.path isDirectory:YES];
        Require(Reject([directoryRootLink URLByAppendingPathComponent:@"ko.bundle"], directoryRootLink, unity, 3),
            "trailing_slash_linked_root_accepted");
        NSURL *savedJa = [root URLByAppendingPathComponent:@"saved-ja.bundle"];
        Require([NSFileManager.defaultManager moveItemAtURL:ja toURL:savedJa error:NULL], "fixture_bundle_move_failed");
        Require([NSFileManager.defaultManager createSymbolicLinkAtURL:ja withDestinationURL:savedJa error:NULL],
            "fixture_bundle_symlink_failed");
        Require(Reject(ja, root, unity, 3), "linked_bundle_accepted");
        Require([NSFileManager.defaultManager removeItemAtURL:ja error:NULL]
            && [NSFileManager.defaultManager moveItemAtURL:savedJa toURL:ja error:NULL], "fixture_bundle_restore_failed");
        NSURL *enData = [en URLByAppendingPathComponent:@"Data"];
        NSURL *savedData = [root URLByAppendingPathComponent:@"saved-data"];
        Require([NSFileManager.defaultManager moveItemAtURL:enData toURL:savedData error:NULL], "fixture_data_move_failed");
        Require([NSFileManager.defaultManager createSymbolicLinkAtURL:enData withDestinationURL:savedData error:NULL],
            "fixture_data_symlink_failed");
        Require(Reject(en, root, unity, 4), "linked_data_accepted");
        Require([NSFileManager.defaultManager removeItemAtURL:enData error:NULL]
            && [NSFileManager.defaultManager moveItemAtURL:savedData toURL:enData error:NULL], "fixture_data_restore_failed");
        NSURL *enInfo = [en URLByAppendingPathComponent:@"Info.plist"];
        NSURL *savedInfo = [root URLByAppendingPathComponent:@"saved-info.plist"];
        Require([NSFileManager.defaultManager moveItemAtURL:enInfo toURL:savedInfo error:NULL], "fixture_info_move_failed");
        Require([NSFileManager.defaultManager createSymbolicLinkAtURL:enInfo withDestinationURL:savedInfo error:NULL],
            "fixture_info_symlink_failed");
        Require(Reject(en, root, unity, 4), "linked_info_accepted");
        Require([NSFileManager.defaultManager removeItemAtURL:enInfo error:NULL]
            && [NSFileManager.defaultManager moveItemAtURL:savedInfo toURL:enInfo error:NULL], "fixture_info_restore_failed");
        WriteInfo(en, @{@"CFBundleIdentifier":@"not.our.identifier"});
        Require(Reject(en, root, unity, 5), "wrong_identifier_accepted");
        WriteInfo(en, @{@"IdolyClientLanguage":@"ko"});
        Require(Reject(en, root, unity, 5), "wrong_language_accepted");
        WriteInfo(en, @{@"CFBundleExecutable":@"untrusted"});
        Require(Reject(en, root, unity, 5), "executable_bundle_accepted");
        WriteInfo(en, @{});
        Require(Reject(ko, root, [IDInvalidUnity new], 7), "wrong_setter_type_accepted");
        __block BOOL offMainRejected = NO;
        dispatch_semaphore_t done = dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            offMainRejected = Reject(ko, root, unity, 1); dispatch_semaphore_signal(done);
        });
        Require(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5*NSEC_PER_SEC)) == 0
            && offMainRejected, "off_main_call_not_rejected");
        Require([IDClientDataSelectionInfo()[@"selected"] isEqual:@NO], "invalid_fixture_committed_selection");

        NSBundle *foundationBefore = [NSBundle bundleWithIdentifier:@"com.apple.Foundation"];
        NSBundle *unknownBefore = [NSBundle bundleWithIdentifier:@"local.idoly.client-data.not-ours"];
        Require(foundationBefore != nil, "foundation_fixture_bundle_missing");
        NSBundle *resource = [NSBundle bundleWithURL:ko];
        Require(resource && SamePath(resource.bundlePath, ko.path), "resource_only_ns_bundle_creation_failed");
        BOOL beforeLoad = SamePath([NSBundle bundleWithIdentifier:IDClientDataBundleIdentifier].bundlePath, ko.path);
        BOOL nativeLoad = [resource loadAndReturnError:NULL];
        BOOL afterLoad = SamePath([NSBundle bundleWithIdentifier:IDClientDataBundleIdentifier].bundlePath, ko.path);
        NSError *error = nil;
        // Model iOS /var versus /private/var: only a trusted ancestor is an
        // alias, while the owned root/bundle leaf nodes remain real directories.
        NSURL *ancestorAlias = [temporary URLByAppendingPathComponent:@"ancestor-alias"];
        Require([NSFileManager.defaultManager createSymbolicLinkAtURL:ancestorAlias
            withDestinationURL:temporary error:NULL], "fixture_ancestor_alias_failed");
        NSURL *rawAliasRoot = [ancestorAlias URLByAppendingPathComponent:@"client-data" isDirectory:YES];
        Require(IDClientDataSelectBundle(ko.URLByResolvingSymlinksInPath, rawAliasRoot, unity, &error),
            "canonical_bundle_with_raw_ancestor_alias_root_rejected");
        Require(unity.setterCalls == 1 && unity.receivedIdentifier
            && !strcmp(unity.receivedIdentifier, IDClientDataBundleIdentifier.UTF8String), "typed_setter_not_called_once");
        NSBundle *selected = [NSBundle bundleWithIdentifier:[NSString stringWithUTF8String:unity.receivedIdentifier]];
        Require(SamePath(selected.bundlePath, ko.path), "unity_identifier_resolved_wrong_data_path");
        NSString *marker = [NSString stringWithContentsOfURL:[[selected.bundleURL URLByAppendingPathComponent:@"Data"]
            URLByAppendingPathComponent:@"fixture.txt"] encoding:NSUTF8StringEncoding error:NULL];
        Require([marker isEqualToString:@"ko"], "unity_data_marker_not_selected_language");
        Require([NSBundle bundleWithIdentifier:@"com.apple.Foundation"] == foundationBefore
            && [NSBundle bundleWithIdentifier:@"local.idoly.client-data.not-ours"] == unknownBefore,
            "unrelated_identifier_lookup_changed");
        Require(IDClientDataSelectBundle(ko, root, unity, &error) && unity.setterCalls == 1, "same_selection_not_idempotent");
        Require(Reject(ja, root, unity, 6), "language_changed_after_data_selection");
        NSDictionary *selection = IDClientDataSelectionInfo();
        Require([selection[@"selected"] isEqual:@YES] && [selection[@"language"] isEqual:@"ko"], "selection_info_invalid");
        if (forced) Require([selection[@"fixed_identifier_fallback"] isEqual:@YES], "forced_fallback_not_exercised");
        Require([NSFileManager.defaultManager removeItemAtURL:temporary error:NULL], "owned_fixture_cleanup_failed");
        NSDictionary *result = @{@"status":@"PASS", @"actual_macos_foundation_execution":@YES,
            @"forced_registration_failure":@(forced), @"native_lookup_before_load":@(beforeLoad),
            @"native_resource_bundle_load":@(nativeLoad), @"native_lookup_after_load":@(afterLoad),
            @"fixed_identifier_scope_verified":@YES, @"typed_unity_setter_verified":@YES,
            @"invalid_paths_and_metadata_rejected":@YES, @"symlinks_rejected":@YES,
            @"ancestor_alias_root_accepted":@YES,
            @"off_main_rejected":@YES, @"different_language_after_selection_rejected":@YES,
            @"selection":selection, @"iOS_Unity_or_PlayCover_execution":@NO};
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
        Require(json != nil, "fixture_json_failed");
        fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout);
    }
    return 0;
}
