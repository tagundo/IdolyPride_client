#ifndef IDOLY_OCTO_BUDGET_POLICY_H
#define IDOLY_OCTO_BUDGET_POLICY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

_Static_assert(sizeof(float) == 4, "The audited IL2CPP Single ABI requires four-byte float");

enum { IDOctoCacheWaitSeconds = 300, IDOctoBudgetSeconds = 330 };

typedef struct {
    void *(*domain_get)(void);
    const void **(*domain_get_assemblies)(const void *, size_t *);
    const void *(*assembly_get_image)(const void *);
    const char *(*image_get_name)(const void *);
    void *(*class_from_name)(const void *, const char *, const char *);
    const void *(*class_get_image)(const void *);
    const char *(*class_get_name)(const void *);
    const char *(*class_get_namespace)(const void *);
    void *(*class_get_field_from_name)(void *, const char *);
    void *(*field_get_parent)(const void *);
    const char *(*field_get_name)(const void *);
    const void *(*field_get_type)(const void *);
    uint32_t (*field_get_flags)(const void *);
    size_t (*field_get_offset)(const void *);
    void *(*class_from_type)(const void *);
    int32_t (*class_value_size)(void *, uint32_t *);
    void (*runtime_class_init)(void *);
    void (*field_static_get_value)(const void *, void *);
    void (*field_static_set_value)(const void *, void *);
    void *(*thread_current)(void);
} IDOctoBudgetAPIs;

typedef enum {
    IDOctoBudgetConfigured,
    IDOctoBudgetAlreadyConfigured,
    IDOctoBudgetUnattested,
    IDOctoBudgetWrongThread,
    IDOctoBudgetIncompleteAPIs,
    IDOctoBudgetRuntimeUnavailable,
    IDOctoBudgetInvalidAssemblies,
    IDOctoBudgetImageMismatch,
    IDOctoBudgetClassMismatch,
    IDOctoBudgetFieldMismatch,
    IDOctoBudgetFieldNotStatic,
    IDOctoBudgetTypeMismatch,
    IDOctoBudgetUnexpectedValue,
    IDOctoBudgetReadbackMismatch
} IDOctoBudgetCode;

typedef struct {
    IDOctoBudgetCode code;
    float original_seconds;
    float effective_seconds;
    bool has_values;
} IDOctoBudgetResult;

static inline const char *IDOctoBudgetCodeName(IDOctoBudgetCode code) {
    switch (code) {
        case IDOctoBudgetConfigured: return "configured";
        case IDOctoBudgetAlreadyConfigured: return "already_configured";
        case IDOctoBudgetUnattested: return "unattested_loopback";
        case IDOctoBudgetWrongThread: return "wrong_thread";
        case IDOctoBudgetIncompleteAPIs: return "incomplete_apis";
        case IDOctoBudgetRuntimeUnavailable: return "runtime_unavailable";
        case IDOctoBudgetInvalidAssemblies: return "invalid_assemblies";
        case IDOctoBudgetImageMismatch: return "image_mismatch";
        case IDOctoBudgetClassMismatch: return "class_mismatch";
        case IDOctoBudgetFieldMismatch: return "field_mismatch";
        case IDOctoBudgetFieldNotStatic: return "field_not_static";
        case IDOctoBudgetTypeMismatch: return "type_mismatch";
        case IDOctoBudgetUnexpectedValue: return "unexpected_value";
        case IDOctoBudgetReadbackMismatch: return "readback_mismatch";
    }
    return "invalid_result";
}

static inline bool IDOctoBudgetSucceeded(IDOctoBudgetResult result) {
    return result.code == IDOctoBudgetConfigured || result.code == IDOctoBudgetAlreadyConfigured;
}

static inline bool IDOctoBudgetAPIsComplete(const IDOctoBudgetAPIs *a) {
    return a && a->domain_get && a->domain_get_assemblies && a->assembly_get_image
        && a->image_get_name && a->class_from_name && a->class_get_image
        && a->class_get_name && a->class_get_namespace && a->class_get_field_from_name
        && a->field_get_parent && a->field_get_name && a->field_get_type
        && a->field_get_flags && a->field_get_offset && a->class_from_type
        && a->class_value_size && a->runtime_class_init && a->field_static_get_value
        && a->field_static_set_value && a->thread_current;
}

static inline bool IDOctoBudgetString(const char *actual, const char *expected) {
    return actual && strcmp(actual, expected) == 0;
}

// No runtime structure offsets or executable writes are used. The wrapper must
// attest every API address to the original Unity image before supplying this table.
static inline IDOctoBudgetResult IDOctoBudgetApply(const IDOctoBudgetAPIs *a,
                                                   bool loopback_attested,
                                                   bool main_thread) {
    IDOctoBudgetResult result = { IDOctoBudgetIncompleteAPIs, 0, 0, false };
#define ID_OCTO_FAIL(value) do { result.code = (value); return result; } while (0)
    if (!loopback_attested) ID_OCTO_FAIL(IDOctoBudgetUnattested);
    if (!main_thread) ID_OCTO_FAIL(IDOctoBudgetWrongThread);
    if (!IDOctoBudgetAPIsComplete(a)) return result;
    if (!a->thread_current()) ID_OCTO_FAIL(IDOctoBudgetRuntimeUnavailable);
    void *domain = a->domain_get();
    if (!domain) ID_OCTO_FAIL(IDOctoBudgetRuntimeUnavailable);
    size_t count = 0;
    const void **assemblies = a->domain_get_assemblies(domain, &count);
    if (!assemblies || !count || count > 4096) ID_OCTO_FAIL(IDOctoBudgetInvalidAssemblies);
    const void *octo_image = NULL, *system_image = NULL;
    for (size_t i = 0; i < count; ++i) {
        if (!assemblies[i]) ID_OCTO_FAIL(IDOctoBudgetInvalidAssemblies);
        const void *image = a->assembly_get_image(assemblies[i]);
        if (!image) ID_OCTO_FAIL(IDOctoBudgetInvalidAssemblies);
        const char *name = a->image_get_name(image);
        if (IDOctoBudgetString(name, "Octo.dll")) {
            if (octo_image) ID_OCTO_FAIL(IDOctoBudgetImageMismatch);
            octo_image = image;
        }
        if (IDOctoBudgetString(name, "mscorlib.dll")) {
            if (system_image) ID_OCTO_FAIL(IDOctoBudgetImageMismatch);
            system_image = image;
        }
    }
    if (!octo_image || !system_image) ID_OCTO_FAIL(IDOctoBudgetImageMismatch);
    void *klass = a->class_from_name(octo_image, "Octo", "OctoManager");
    if (!klass || a->class_get_image(klass) != octo_image
            || !IDOctoBudgetString(a->class_get_name(klass), "OctoManager")
            || !IDOctoBudgetString(a->class_get_namespace(klass), "Octo"))
        ID_OCTO_FAIL(IDOctoBudgetClassMismatch);
    static const char field_name[] = "<DownloadStallTimeout>k__BackingField";
    void *field = a->class_get_field_from_name(klass, field_name);
    if (!field || a->field_get_parent(field) != klass
            || !IDOctoBudgetString(a->field_get_name(field), field_name))
        ID_OCTO_FAIL(IDOctoBudgetFieldMismatch);
    uint32_t flags = a->field_get_flags(field);
    size_t offset = a->field_get_offset(field);
    // Literal and thread-static fields are not writable process-wide settings.
    if (!(flags & 0x10u) || (flags & 0x40u) || offset > 65536 || offset % sizeof(float))
        ID_OCTO_FAIL(IDOctoBudgetFieldNotStatic);
    const void *field_type = a->field_get_type(field);
    void *value_class = field_type ? a->class_from_type(field_type) : NULL;
    void *single_class = a->class_from_name(system_image, "System", "Single");
    uint32_t alignment = 0;
    if (!value_class || !single_class || value_class != single_class
            || a->class_get_image(value_class) != system_image
            || !IDOctoBudgetString(a->class_get_name(value_class), "Single")
            || !IDOctoBudgetString(a->class_get_namespace(value_class), "System")
            || a->class_value_size(value_class, &alignment) != (int32_t)sizeof(float)
            || alignment != sizeof(float)) ID_OCTO_FAIL(IDOctoBudgetTypeMismatch);
    // The original cctor writes 10 seconds. It must complete before our write.
    a->runtime_class_init(klass);
    a->field_static_get_value(field, &result.original_seconds);
    if (result.original_seconds != 10.0f
            && result.original_seconds != (float)IDOctoBudgetSeconds)
        ID_OCTO_FAIL(IDOctoBudgetUnexpectedValue);
    result.effective_seconds = result.original_seconds;
    result.has_values = true;
    if (result.original_seconds == (float)IDOctoBudgetSeconds) {
        result.code = IDOctoBudgetAlreadyConfigured;
        return result;
    }
    float seconds = (float)IDOctoBudgetSeconds;
    a->field_static_set_value(field, &seconds);
    a->field_static_get_value(field, &result.effective_seconds);
    if (result.effective_seconds != seconds) {
        result.has_values = false;
        ID_OCTO_FAIL(IDOctoBudgetReadbackMismatch);
    }
    result.code = IDOctoBudgetConfigured;
    return result;
#undef ID_OCTO_FAIL
}

#endif
