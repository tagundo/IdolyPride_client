#import "IdolyOctoBudget.h"
#include "OctoBudgetPolicy.h"
#include <math.h>

#if IDOLY_SMOKE_SIMULATOR
// The device object has no reference to this simulator-only fixture provider.
extern BOOL IDOctoBudgetSmokeAPIs(IDOctoBudgetAPIs *)
    __attribute__((weak_import, visibility("default")));
#else
#include "OctoBudgetProfile.h"
#include <dlfcn.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <mach/vm_prot.h>
#endif

@interface IDOctoBudgetState : NSObject @end
@implementation IDOctoBudgetState @end

static IDOctoBudgetAPIs budgetAPIs;
static BOOL budgetPrepared, budgetConfigured, budgetHasValues;
static float budgetOriginal, budgetEffective;
static NSString *budgetStatus = @"idle", *budgetError;

static BOOL budgetFailure(NSString *code, NSString **error) {
    @synchronized (IDOctoBudgetState.class) {
        budgetStatus = @"failed";
        budgetError = code;
        budgetConfigured = NO;
    }
    if (error) *error = code;
    return NO;
}

#if !IDOLY_SMOKE_SIMULATOR
static void *budgetUnityHandle;

static BOOL budgetOriginalImage(const struct mach_header *base,
                                uintptr_t *textStart, uintptr_t *textEnd) {
    if (!base || base->magic != MH_MAGIC_64 || base->cputype != CPU_TYPE_ARM64
            || base->filetype != MH_DYLIB || base->ncmds > 4096
            || base->sizeofcmds > 1024 * 1024) return NO;
    const struct mach_header_64 *header = (const struct mach_header_64 *)base;
    const unsigned char *commands = (const unsigned char *)(header + 1);
    size_t offset = 0;
    BOOL uuid = NO, text = NO;
    for (uint32_t i = 0; i < header->ncmds; ++i) {
        if (offset > header->sizeofcmds || header->sizeofcmds - offset < sizeof(struct load_command)) return NO;
        const struct load_command *command = (const struct load_command *)(commands + offset);
        if (command->cmdsize < sizeof *command || command->cmdsize > header->sizeofcmds - offset) return NO;
        if (command->cmd == LC_UUID) {
            if (uuid || command->cmdsize != sizeof(struct uuid_command)
                    || memcmp(((const struct uuid_command *)command)->uuid,
                              IDOctoBudgetUnityUUID, sizeof IDOctoBudgetUnityUUID)) return NO;
            uuid = YES;
        }
        if (command->cmd == LC_SEGMENT_64) {
            if (command->cmdsize < sizeof(struct segment_command_64)) return NO;
            const struct segment_command_64 *segment = (const struct segment_command_64 *)command;
            if (!memcmp(segment->segname, "__TEXT\0", 7)) {
                if (text || segment->vmaddr || segment->fileoff
                        || !(segment->initprot & VM_PROT_EXECUTE)
                        || segment->vmsize > UINTPTR_MAX - (uintptr_t)base) return NO;
                *textStart = (uintptr_t)base;
                *textEnd = *textStart + (uintptr_t)segment->vmsize;
                text = YES;
            }
        }
        offset += command->cmdsize;
    }
    return uuid && text && offset == header->sizeofcmds;
}

static BOOL budgetResolveOriginalAPIs(IDOctoBudgetAPIs *apis) {
    static const char suffix[] = "/UnityFramework.framework/UnityFramework";
    const struct mach_header *header = NULL;
    const char *path = NULL;
    uintptr_t textStart = 0, textEnd = 0;
    uint32_t count = _dyld_image_count();
    for (uint32_t i = 0; i < count; ++i) {
        const char *candidate = _dyld_get_image_name(i);
        if (!candidate) continue;
        size_t length = strlen(candidate);
        if (length < sizeof suffix - 1 || strcmp(candidate + length - (sizeof suffix - 1), suffix)) continue;
        if (header) return NO;
        header = _dyld_get_image_header(i);
        path = candidate;
    }
    if (!header || !budgetOriginalImage(header, &textStart, &textEnd)) return NO;
    void *handle = dlopen(path, RTLD_NOW | RTLD_NOLOAD);
    if (!handle) return NO;
    void *addresses[IDOctoBudgetExportCount] = {0};
    for (size_t i = 0; i < IDOctoBudgetExportCount; ++i) {
        const IDOctoBudgetExport *entry = &IDOctoBudgetExports[i];
        Dl_info owner;
        void *address = dlsym(handle, entry->name);
        if (!address || !dladdr(address, &owner) || owner.dli_fbase != header
                || !owner.dli_fname || strcmp(owner.dli_fname, path)
                || entry->rva > UINTPTR_MAX - (uintptr_t)header
                || (uintptr_t)address != (uintptr_t)header + entry->rva
                || (uintptr_t)address < textStart || textEnd < sizeof entry->prefix
                || (uintptr_t)address > textEnd - sizeof entry->prefix
                || memcmp(address, entry->prefix, sizeof entry->prefix)) {
            dlclose(handle);
            return NO;
        }
        addresses[i] = address;
    }
    _Static_assert(IDOctoBudgetExportCount == 20, "The complete typed API table must be attested");
#define ID_BIND(member, index) apis->member = (__typeof__(apis->member))addresses[index]
    ID_BIND(domain_get, 0);
    ID_BIND(domain_get_assemblies, 1);
    ID_BIND(assembly_get_image, 2);
    ID_BIND(image_get_name, 3);
    ID_BIND(class_from_name, 4);
    ID_BIND(class_get_image, 5);
    ID_BIND(class_get_name, 6);
    ID_BIND(class_get_namespace, 7);
    ID_BIND(class_get_field_from_name, 8);
    ID_BIND(field_get_parent, 9);
    ID_BIND(field_get_name, 10);
    ID_BIND(field_get_type, 11);
    ID_BIND(field_get_flags, 12);
    ID_BIND(field_get_offset, 13);
    ID_BIND(class_from_type, 14);
    ID_BIND(class_value_size, 15);
    ID_BIND(runtime_class_init, 16);
    ID_BIND(field_static_get_value, 17);
    ID_BIND(field_static_set_value, 18);
    ID_BIND(thread_current, 19);
#undef ID_BIND
    if (!IDOctoBudgetAPIsComplete(apis)) { dlclose(handle); return NO; }
    budgetUnityHandle = handle; // Keep the attested image resident with its table.
    return YES;
}
#endif

BOOL IDOctoBudgetPrepare(NSString **error) {
    if (error) *error = nil;
    if (!NSThread.isMainThread) return budgetFailure(@"wrong_thread", error);
    @synchronized (IDOctoBudgetState.class) {
        if (budgetPrepared) return YES;
    }
    IDOctoBudgetAPIs candidate = {0};
#if IDOLY_SMOKE_SIMULATOR
    BOOL valid = IDOctoBudgetSmokeAPIs && IDOctoBudgetSmokeAPIs(&candidate)
        && IDOctoBudgetAPIsComplete(&candidate);
#else
    BOOL valid = budgetResolveOriginalAPIs(&candidate);
#endif
    if (!valid) return budgetFailure(@"api_origin_mismatch", error);
    @synchronized (IDOctoBudgetState.class) {
        budgetAPIs = candidate;
        budgetPrepared = YES;
        budgetConfigured = NO;
        budgetStatus = @"prepared";
        budgetError = nil;
    }
    return YES;
}

BOOL IDOctoBudgetConfigure(BOOL unifiedLoopbackAttested, NSString **error) {
    if (error) *error = nil;
    if (!unifiedLoopbackAttested) return budgetFailure(@"unattested_loopback", error);
    if (!NSThread.isMainThread) return budgetFailure(@"wrong_thread", error);
    IDOctoBudgetAPIs apis;
    @synchronized (IDOctoBudgetState.class) {
        if (!budgetPrepared) return budgetFailure(@"not_prepared", error);
        apis = budgetAPIs;
    }
    IDOctoBudgetResult result = IDOctoBudgetApply(&apis, true, true);
    @synchronized (IDOctoBudgetState.class) {
        if (result.has_values && isfinite(result.original_seconds) && isfinite(result.effective_seconds)) {
            if (!budgetHasValues) budgetOriginal = result.original_seconds;
            budgetEffective = result.effective_seconds;
            budgetHasValues = YES;
        }
        budgetConfigured = IDOctoBudgetSucceeded(result);
        budgetStatus = budgetConfigured ? @"configured" : @"failed";
        budgetError = budgetConfigured ? nil : [NSString stringWithUTF8String:IDOctoBudgetCodeName(result.code)];
        if (error) *error = budgetError;
    }
    return IDOctoBudgetSucceeded(result);
}

NSDictionary *IDOctoBudgetInfo(void) {
    @synchronized (IDOctoBudgetState.class) {
        return @{@"schema": @1, @"status": budgetStatus, @"prepared": @(budgetPrepared),
                 @"configured": @(budgetConfigured),
                 @"original_seconds": budgetHasValues ? @(budgetOriginal) : NSNull.null,
                 @"effective_seconds": budgetHasValues ? @(budgetEffective) : NSNull.null,
                 @"cache_wait_seconds": @(IDOctoCacheWaitSeconds), @"scope": @"unified-loopback",
                 @"error": budgetError ?: NSNull.null};
    }
}

NSString *IDOctoBudgetLastDiagnostic(void) {
    NSDictionary *info = IDOctoBudgetInfo();
    return [NSString stringWithFormat:@"status=%@ error=%@ original=%@ effective=%@",
            info[@"status"], info[@"error"], info[@"original_seconds"], info[@"effective_seconds"]];
}
