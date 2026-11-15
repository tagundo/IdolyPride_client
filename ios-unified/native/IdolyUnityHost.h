#ifndef IDOLY_UNITY_HOST_H
#define IDOLY_UNITY_HOST_H
#import <Foundation/Foundation.h>

typedef void (*IDUnityHostReadyCallback)(void);
__attribute__((visibility("default")))
BOOL IDUnityHostInstall(IDUnityHostReadyCallback callback, NSString **error);
__attribute__((visibility("default")))
BOOL IDUnityHostIsLaunching(void);
__attribute__((visibility("default")))
BOOL IDUnityHostStartGame(NSString *verifiedExpectedBundleRoot, NSString **error);
__attribute__((visibility("default")))
NSDictionary *IDUnityHostInfo(void);

#if IDOLY_SMOKE_SIMULATOR
// Registration occurs in fixture main, after the framework constructor installs
// interception and before fake Unity's original run-main entry is invoked.
typedef struct {
    int (*application_main)(int, char **, NSString *, NSString *);
    BOOL (*pre_runtime)(void);
    unsigned (*run_count)(id);
    const char *(*cached_bundle_root)(void);
    id (*app_controller)(id);
    void (*before_host_ready)(id application, id hostDelegate);
} IDUnityHostSmokeHooks;
__attribute__((visibility("default")))
BOOL IDUnityHostRegisterSmokeHooks(const IDUnityHostSmokeHooks *hooks);
#endif
#endif
