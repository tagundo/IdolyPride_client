#ifndef IDOLY_OCTO_BUDGET_FIXTURE_H
#define IDOLY_OCTO_BUDGET_FIXTURE_H

// Deliberately independent of Foundation and the real game. Each translation
// unit gets a private fake runtime; this header is never a device dependency.
#include "../OctoBudgetPolicy.h"

typedef struct {
    bool initialized;
    unsigned initializations, reads, writes, writes_before_initialization;
    float value, last_snapshot, default_value;
    bool thread_missing, domain_missing, assemblies_missing, assembly_null;
    bool image_null, duplicate_octo, octo_image_wrong, system_image_wrong;
    bool class_missing, class_image_wrong, class_name_wrong, class_namespace_wrong;
    bool field_missing, field_parent_wrong, field_name_wrong, field_type_missing;
    bool type_class_wrong, single_class_missing, single_image_wrong;
    bool single_name_wrong, single_namespace_wrong, write_dropped;
    uint32_t field_flags, alignment;
    size_t field_offset, assembly_count;
    int32_t value_size;
} IDOctoBudgetFixtureData;

static IDOctoBudgetFixtureData id_octo_fixture;
static unsigned char id_octo_domain, id_octo_thread, id_octo_assembly;
static unsigned char id_octo_system_assembly, id_octo_image, id_octo_system_image;
static unsigned char id_octo_class, id_octo_single_class, id_octo_wrong_class;
static unsigned char id_octo_field, id_octo_type;
static const void *id_octo_assemblies[3];
static inline void IDOctoFixtureInitialize(void *klass);

static inline IDOctoBudgetFixtureData *IDOctoBudgetFixtureState(void) {
    return &id_octo_fixture;
}
static inline void IDOctoBudgetFixtureReset(void) {
    memset(&id_octo_fixture, 0, sizeof id_octo_fixture);
    id_octo_fixture.default_value = 10.0f;
    id_octo_fixture.field_flags = 0x11u;
    id_octo_fixture.field_offset = 0x94u;
    id_octo_fixture.assembly_count = 2;
    id_octo_fixture.value_size = (int32_t)sizeof(float);
    id_octo_fixture.alignment = sizeof(float);
}
static inline float IDOctoBudgetFixtureSnapshot(void) {
    // Model the SDK's direct static read: normal managed access first ensures
    // its cctor, without going through our field getter/setter API callbacks.
    IDOctoFixtureInitialize(&id_octo_class);
    id_octo_fixture.last_snapshot = id_octo_fixture.value;
    return id_octo_fixture.last_snapshot;
}
static inline void *IDOctoFixtureDomain(void) {
    return id_octo_fixture.domain_missing ? NULL : &id_octo_domain;
}
static inline const void **IDOctoFixtureAssemblies(const void *domain, size_t *count) {
    if (domain != &id_octo_domain || !count) return NULL;
    *count = id_octo_fixture.assembly_count;
    id_octo_assemblies[0] = id_octo_fixture.assembly_null ? NULL : &id_octo_assembly;
    id_octo_assemblies[1] = &id_octo_system_assembly;
    id_octo_assemblies[2] = &id_octo_assembly;
    return id_octo_fixture.assemblies_missing ? NULL : id_octo_assemblies;
}
static inline const void *IDOctoFixtureImage(const void *assembly) {
    if (id_octo_fixture.image_null) return NULL;
    if (assembly == &id_octo_assembly) return &id_octo_image;
    if (assembly == &id_octo_system_assembly) return &id_octo_system_image;
    return NULL;
}
static inline const char *IDOctoFixtureImageName(const void *image) {
    if (image == &id_octo_image)
        return id_octo_fixture.octo_image_wrong ? "Other.dll" : "Octo.dll";
    if (image == &id_octo_system_image)
        return id_octo_fixture.duplicate_octo ? "Octo.dll"
            : (id_octo_fixture.system_image_wrong ? "Other.dll" : "mscorlib.dll");
    return NULL;
}
static inline void *IDOctoFixtureClass(const void *image, const char *ns, const char *name) {
    if (!ns || !name) return NULL;
    if (image == &id_octo_image && !strcmp(ns, "Octo") && !strcmp(name, "OctoManager"))
        return id_octo_fixture.class_missing ? NULL : &id_octo_class;
    if (image == &id_octo_system_image && !strcmp(ns, "System") && !strcmp(name, "Single"))
        return id_octo_fixture.single_class_missing ? NULL : &id_octo_single_class;
    return NULL;
}
static inline const void *IDOctoFixtureClassImage(const void *klass) {
    if (klass == &id_octo_class)
        return id_octo_fixture.class_image_wrong ? &id_octo_system_image : &id_octo_image;
    if (klass == &id_octo_single_class)
        return id_octo_fixture.single_image_wrong ? &id_octo_image : &id_octo_system_image;
    return NULL;
}
static inline const char *IDOctoFixtureClassName(const void *klass) {
    if (klass == &id_octo_class)
        return id_octo_fixture.class_name_wrong ? "OtherManager" : "OctoManager";
    if (klass == &id_octo_single_class)
        return id_octo_fixture.single_name_wrong ? "Double" : "Single";
    return NULL;
}
static inline const char *IDOctoFixtureClassNamespace(const void *klass) {
    if (klass == &id_octo_class)
        return id_octo_fixture.class_namespace_wrong ? "Other" : "Octo";
    if (klass == &id_octo_single_class)
        return id_octo_fixture.single_namespace_wrong ? "Other" : "System";
    return NULL;
}
static inline void *IDOctoFixtureField(void *klass, const char *name) {
    if (klass != &id_octo_class || !name
            || strcmp(name, "<DownloadStallTimeout>k__BackingField")) return NULL;
    return id_octo_fixture.field_missing ? NULL : &id_octo_field;
}
static inline void *IDOctoFixtureFieldParent(const void *field) {
    return field != &id_octo_field ? NULL
        : (id_octo_fixture.field_parent_wrong ? &id_octo_wrong_class : &id_octo_class);
}
static inline const char *IDOctoFixtureFieldName(const void *field) {
    return field != &id_octo_field ? NULL : (id_octo_fixture.field_name_wrong
        ? "OtherField" : "<DownloadStallTimeout>k__BackingField");
}
static inline const void *IDOctoFixtureFieldType(const void *field) {
    return field != &id_octo_field || id_octo_fixture.field_type_missing ? NULL : &id_octo_type;
}
static inline uint32_t IDOctoFixtureFieldFlags(const void *field) {
    return field == &id_octo_field ? id_octo_fixture.field_flags : 0;
}
static inline size_t IDOctoFixtureFieldOffset(const void *field) {
    return field == &id_octo_field ? id_octo_fixture.field_offset : (size_t)-1;
}
static inline void *IDOctoFixtureClassFromType(const void *type) {
    return type != &id_octo_type ? NULL
        : (id_octo_fixture.type_class_wrong ? &id_octo_wrong_class : &id_octo_single_class);
}
static inline int32_t IDOctoFixtureValueSize(void *klass, uint32_t *alignment) {
    if (klass != &id_octo_single_class || !alignment) return -1;
    *alignment = id_octo_fixture.alignment;
    return id_octo_fixture.value_size;
}
static inline void IDOctoFixtureInitialize(void *klass) {
    if (klass == &id_octo_class && !id_octo_fixture.initialized) {
        id_octo_fixture.initialized = true;
        id_octo_fixture.initializations += 1;
        id_octo_fixture.value = id_octo_fixture.default_value;
    }
}
static inline void IDOctoFixtureRead(const void *field, void *value) {
    if (field == &id_octo_field && value) {
        id_octo_fixture.reads += 1;
        memcpy(value, &id_octo_fixture.value, sizeof(float));
    }
}
static inline void IDOctoFixtureWrite(const void *field, void *value) {
    if (field == &id_octo_field && value) {
        id_octo_fixture.writes += 1;
        if (!id_octo_fixture.initialized) id_octo_fixture.writes_before_initialization += 1;
        if (!id_octo_fixture.write_dropped) memcpy(&id_octo_fixture.value, value, sizeof(float));
    }
}
static inline void *IDOctoFixtureThread(void) {
    return id_octo_fixture.thread_missing ? NULL : &id_octo_thread;
}
static inline IDOctoBudgetAPIs IDOctoBudgetFixtureAPIs(void) {
    IDOctoBudgetAPIs apis = {
        IDOctoFixtureDomain, IDOctoFixtureAssemblies, IDOctoFixtureImage,
        IDOctoFixtureImageName, IDOctoFixtureClass, IDOctoFixtureClassImage,
        IDOctoFixtureClassName, IDOctoFixtureClassNamespace, IDOctoFixtureField,
        IDOctoFixtureFieldParent, IDOctoFixtureFieldName, IDOctoFixtureFieldType,
        IDOctoFixtureFieldFlags, IDOctoFixtureFieldOffset, IDOctoFixtureClassFromType,
        IDOctoFixtureValueSize, IDOctoFixtureInitialize, IDOctoFixtureRead,
        IDOctoFixtureWrite, IDOctoFixtureThread
    };
    return apis;
}

#endif
