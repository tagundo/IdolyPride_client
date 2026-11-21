#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT NSString * const IDClientDataBundleIdentifier;

// Main-thread only, once before Unity initializes its cached data path. The
// caller audits the Unity image/IMP prefixes and prepares a complete Data tree
// off-main. allowedRootURL is the caller's own Application Support/client-data.
BOOL IDClientDataSelectBundle(NSURL *bundleURL, NSURL *allowedRootURL,
                            id auditedUnityFramework, NSError * _Nullable * _Nullable error);
NSDictionary *IDClientDataSelectionInfo(void);

#ifdef IDOLY_CLIENT_DATA_TESTING
// Host-fixture-only injection of a failed native registration. Not compiled
// into the shipping framework; verifies the narrowly scoped fallback branch.
void IDClientDataForceFixedFallbackForTests(void);
#endif
NS_ASSUME_NONNULL_END
