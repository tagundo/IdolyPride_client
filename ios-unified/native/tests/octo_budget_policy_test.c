#include "OctoBudgetFixture.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static void Reject(IDOctoBudgetCode code) {
    IDOctoBudgetAPIs apis = IDOctoBudgetFixtureAPIs();
    IDOctoBudgetResult result = IDOctoBudgetApply(&apis, true, true);
    assert(result.code == code && !IDOctoBudgetSucceeded(result));
    assert(id_octo_fixture.writes == 0);
}

#define REJECT(member, value, code) do { \
    IDOctoBudgetFixtureReset(); id_octo_fixture.member = (value); Reject(code); \
} while (0)
#define MISSING(member) do { \
    IDOctoBudgetFixtureReset(); apis = IDOctoBudgetFixtureAPIs(); apis.member = NULL; \
    assert(!IDOctoBudgetAPIsComplete(&apis)); \
    result = IDOctoBudgetApply(&apis, true, true); \
    assert(result.code == IDOctoBudgetIncompleteAPIs && id_octo_fixture.writes == 0); \
} while (0)

int main(void) {
    IDOctoBudgetFixtureReset();
    IDOctoBudgetAPIs apis = IDOctoBudgetFixtureAPIs();
    assert(IDOctoBudgetAPIsComplete(&apis));
    IDOctoBudgetResult result = IDOctoBudgetApply(&apis, true, true);
    assert(result.code == IDOctoBudgetConfigured && IDOctoBudgetSucceeded(result));
    assert(result.has_values && result.original_seconds == 10.0f && result.effective_seconds == 330.0f);
    assert(id_octo_fixture.initialized && id_octo_fixture.initializations == 1);
    assert(id_octo_fixture.reads == 2 && id_octo_fixture.writes == 1);
    assert(id_octo_fixture.writes_before_initialization == 0);
    assert(IDOctoBudgetFixtureSnapshot() == 330.0f && id_octo_fixture.last_snapshot == 330.0f);
    result = IDOctoBudgetApply(&apis, true, true);
    assert(result.code == IDOctoBudgetAlreadyConfigured && IDOctoBudgetSucceeded(result));
    assert(id_octo_fixture.initializations == 1 && id_octo_fixture.writes == 1);
    IDOctoFixtureInitialize(&id_octo_class);
    assert(IDOctoBudgetFixtureSnapshot() == 330.0f);

    IDOctoBudgetFixtureReset();
    assert(IDOctoBudgetFixtureSnapshot() == 10.0f);
    assert(id_octo_fixture.initializations == 1 && id_octo_fixture.reads == 0
        && id_octo_fixture.writes == 0);
    IDOctoBudgetFixtureReset();
    result = IDOctoBudgetApply(&apis, false, true);
    assert(result.code == IDOctoBudgetUnattested && id_octo_fixture.writes == 0);
    result = IDOctoBudgetApply(&apis, true, false);
    assert(result.code == IDOctoBudgetWrongThread && id_octo_fixture.writes == 0);
    result = IDOctoBudgetApply(NULL, true, true);
    assert(result.code == IDOctoBudgetIncompleteAPIs && !IDOctoBudgetAPIsComplete(NULL));

    MISSING(domain_get); MISSING(domain_get_assemblies); MISSING(assembly_get_image);
    MISSING(image_get_name); MISSING(class_from_name); MISSING(class_get_image);
    MISSING(class_get_name); MISSING(class_get_namespace); MISSING(class_get_field_from_name);
    MISSING(field_get_parent); MISSING(field_get_name); MISSING(field_get_type);
    MISSING(field_get_flags); MISSING(field_get_offset); MISSING(class_from_type);
    MISSING(class_value_size); MISSING(runtime_class_init); MISSING(field_static_get_value);
    MISSING(field_static_set_value); MISSING(thread_current);

    REJECT(thread_missing, true, IDOctoBudgetRuntimeUnavailable);
    REJECT(domain_missing, true, IDOctoBudgetRuntimeUnavailable);
    REJECT(assemblies_missing, true, IDOctoBudgetInvalidAssemblies);
    REJECT(assembly_count, 0, IDOctoBudgetInvalidAssemblies);
    REJECT(assembly_count, 4097, IDOctoBudgetInvalidAssemblies);
    REJECT(assembly_null, true, IDOctoBudgetInvalidAssemblies);
    REJECT(image_null, true, IDOctoBudgetInvalidAssemblies);
    REJECT(duplicate_octo, true, IDOctoBudgetImageMismatch);
    REJECT(assembly_count, 3, IDOctoBudgetImageMismatch);
    REJECT(octo_image_wrong, true, IDOctoBudgetImageMismatch);
    REJECT(system_image_wrong, true, IDOctoBudgetImageMismatch);
    REJECT(class_missing, true, IDOctoBudgetClassMismatch);
    REJECT(class_image_wrong, true, IDOctoBudgetClassMismatch);
    REJECT(class_name_wrong, true, IDOctoBudgetClassMismatch);
    REJECT(class_namespace_wrong, true, IDOctoBudgetClassMismatch);
    REJECT(field_missing, true, IDOctoBudgetFieldMismatch);
    REJECT(field_parent_wrong, true, IDOctoBudgetFieldMismatch);
    REJECT(field_name_wrong, true, IDOctoBudgetFieldMismatch);
    REJECT(field_flags, 0, IDOctoBudgetFieldNotStatic);
    REJECT(field_flags, 0x50u, IDOctoBudgetFieldNotStatic);
    REJECT(field_offset, (size_t)-1, IDOctoBudgetFieldNotStatic);
    REJECT(field_offset, 3, IDOctoBudgetFieldNotStatic);
    REJECT(field_type_missing, true, IDOctoBudgetTypeMismatch);
    REJECT(type_class_wrong, true, IDOctoBudgetTypeMismatch);
    REJECT(single_class_missing, true, IDOctoBudgetTypeMismatch);
    REJECT(single_image_wrong, true, IDOctoBudgetTypeMismatch);
    REJECT(single_name_wrong, true, IDOctoBudgetTypeMismatch);
    REJECT(single_namespace_wrong, true, IDOctoBudgetTypeMismatch);
    REJECT(value_size, 8, IDOctoBudgetTypeMismatch);
    REJECT(alignment, 8, IDOctoBudgetTypeMismatch);
    REJECT(default_value, 0, IDOctoBudgetUnexpectedValue);
    REJECT(default_value, 11.0f, IDOctoBudgetUnexpectedValue);
    REJECT(default_value, NAN, IDOctoBudgetUnexpectedValue);
    REJECT(default_value, INFINITY, IDOctoBudgetUnexpectedValue);
    IDOctoBudgetFixtureReset(); id_octo_fixture.default_value = 330.0f;
    apis = IDOctoBudgetFixtureAPIs();
    result = IDOctoBudgetApply(&apis, true, true);
    assert(result.code == IDOctoBudgetAlreadyConfigured && id_octo_fixture.writes == 0);

    IDOctoBudgetFixtureReset(); id_octo_fixture.write_dropped = true;
    result = IDOctoBudgetApply(&apis, true, true);
    assert(result.code == IDOctoBudgetReadbackMismatch && !IDOctoBudgetSucceeded(result));
    assert(!result.has_values && result.original_seconds == 10.0f && result.effective_seconds == 10.0f);
    assert(id_octo_fixture.initializations == 1 && id_octo_fixture.writes == 1);
    assert(id_octo_fixture.writes_before_initialization == 0);
    for (int code = IDOctoBudgetConfigured; code <= IDOctoBudgetReadbackMismatch; ++code)
        assert(strcmp(IDOctoBudgetCodeName((IDOctoBudgetCode)code), "invalid_result"));
    puts("PASS: Octo named static-field budget policy; initializer precedes write and snapshot sees 330");
    return 0;
}
