#import <Foundation/Foundation.h>
#import <dispatch/dispatch.h>
#import "../IdolyOctoBudget.h"
#include "OctoBudgetFixture.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#if !IDOLY_SMOKE_SIMULATOR
#error The fake managed runtime must only compile in the explicit smoke build.
#endif

static BOOL providerIncomplete;
BOOL IDOctoBudgetSmokeAPIs(IDOctoBudgetAPIs *apis) {
    if (!apis) return NO;
    *apis = IDOctoBudgetFixtureAPIs();
    if (providerIncomplete) apis->field_static_set_value = NULL;
    return YES;
}
static void Require(BOOL condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL_OCTO_BUDGET: %s\n", message); exit(1); }
}
int main(void) {
    @autoreleasepool {
        Require(NSThread.isMainThread, "fixture_not_on_main_thread");
        IDOctoBudgetFixtureReset();
        NSString *error = nil;
        NSDictionary *idle = IDOctoBudgetInfo();
        Require([idle[@"schema"] isEqual:@1] && [idle[@"status"] isEqual:@"idle"]
            && [idle[@"prepared"] isEqual:@NO] && [idle[@"configured"] isEqual:@NO]
            && idle[@"original_seconds"] == NSNull.null && idle[@"effective_seconds"] == NSNull.null
            && [idle[@"cache_wait_seconds"] isEqual:@300] && [idle[@"scope"] isEqual:@"unified-loopback"]
            && idle[@"error"] == NSNull.null, "invalid_idle_info");
        Require(!IDOctoBudgetConfigure(YES, &error) && [error isEqual:@"not_prepared"],
            "unprepared_configuration_accepted");
        Require(!IDOctoBudgetConfigure(NO, &error) && [error isEqual:@"unattested_loopback"]
            && id_octo_fixture.writes == 0, "unattested_configuration_accepted");
        __block BOOL wrongThreadRejected = NO;
        dispatch_semaphore_t done = dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            NSString *threadError = nil;
            wrongThreadRejected = !IDOctoBudgetPrepare(&threadError)
                && [threadError isEqual:@"wrong_thread"];
            dispatch_semaphore_signal(done);
        });
        Require(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5*NSEC_PER_SEC)) == 0
            && wrongThreadRejected, "wrong_thread_not_rejected");
        providerIncomplete = YES;
        Require(!IDOctoBudgetPrepare(&error) && [error isEqual:@"api_origin_mismatch"]
            && id_octo_fixture.writes == 0, "incomplete_api_table_accepted");
        providerIncomplete = NO;
        Require(IDOctoBudgetPrepare(&error) && !error, "smoke_prepare_failed");
        Require(!id_octo_fixture.initialized && id_octo_fixture.writes == 0,
            "prepare_touched_managed_runtime");
        NSDictionary *prepared = IDOctoBudgetInfo();
        Require([prepared[@"schema"] isEqual:@1] && [prepared[@"status"] isEqual:@"prepared"]
            && [prepared[@"prepared"] isEqual:@YES] && [prepared[@"configured"] isEqual:@NO]
            && prepared[@"original_seconds"] == NSNull.null && prepared[@"effective_seconds"] == NSNull.null
            && [prepared[@"cache_wait_seconds"] isEqual:@300]
            && [prepared[@"scope"] isEqual:@"unified-loopback"] && prepared[@"error"] == NSNull.null,
            "invalid_prepared_info");
        id_octo_fixture.class_name_wrong = true;
        Require(!IDOctoBudgetConfigure(YES, &error) && [error isEqual:@"class_mismatch"]
            && id_octo_fixture.writes == 0, "invalid_identity_accepted");
        IDOctoBudgetFixtureReset(); id_octo_fixture.value_size = 8;
        Require(!IDOctoBudgetConfigure(YES, &error) && [error isEqual:@"type_mismatch"]
            && id_octo_fixture.writes == 0, "invalid_type_accepted");
        IDOctoBudgetFixtureReset(); id_octo_fixture.field_flags = 0;
        Require(!IDOctoBudgetConfigure(YES, &error) && [error isEqual:@"field_not_static"]
            && id_octo_fixture.writes == 0, "nonstatic_field_accepted");
        IDOctoBudgetFixtureReset(); id_octo_fixture.default_value = 11;
        Require(!IDOctoBudgetConfigure(YES, &error) && [error isEqual:@"unexpected_value"]
            && id_octo_fixture.writes == 0, "unexpected_default_accepted");
        const float invalidNumbers[] = {NAN, INFINITY};
        for (size_t i = 0; i < sizeof invalidNumbers / sizeof invalidNumbers[0]; ++i) {
            IDOctoBudgetFixtureReset(); id_octo_fixture.default_value = invalidNumbers[i];
            Require(!IDOctoBudgetConfigure(YES, &error) && [error isEqual:@"unexpected_value"]
                && id_octo_fixture.writes == 0, "nonfinite_default_accepted");
            NSDictionary *failureInfo = IDOctoBudgetInfo();
            Require(failureInfo[@"original_seconds"] == NSNull.null
                && failureInfo[@"effective_seconds"] == NSNull.null
                && [NSJSONSerialization isValidJSONObject:failureInfo]
                && [NSJSONSerialization dataWithJSONObject:failureInfo options:0 error:NULL] != nil,
                "nonfinite_failure_info_not_json_serializable");
        }
        IDOctoBudgetFixtureReset(); id_octo_fixture.write_dropped = true;
        Require(!IDOctoBudgetConfigure(YES, &error) && [error isEqual:@"readback_mismatch"]
            && id_octo_fixture.writes == 1, "readback_failure_accepted");
        IDOctoBudgetFixtureReset();
        Require(IDOctoBudgetFixtureSnapshot() == 10.0f && id_octo_fixture.initializations == 1
            && id_octo_fixture.reads == 0 && id_octo_fixture.writes == 0,
            "original_cctor_snapshot_not_ten");
        IDOctoBudgetFixtureReset();
        Require(IDOctoBudgetConfigure(YES, &error) && !error, "configure_failed");
        Require(id_octo_fixture.initialized && id_octo_fixture.initializations == 1
            && id_octo_fixture.writes == 1 && id_octo_fixture.writes_before_initialization == 0,
            "cctor_did_not_precede_single_write");
        Require(IDOctoBudgetFixtureSnapshot() == 330.0f, "watchdog_snapshot_missed_budget");
        Require(IDOctoBudgetConfigure(YES, &error) && !error
            && id_octo_fixture.initializations == 1 && id_octo_fixture.writes == 1,
            "repeat_configuration_not_idempotent");
        NSDictionary *info = IDOctoBudgetInfo();
        Require([info[@"configured"] isEqual:@YES] && [info[@"original_seconds"] isEqual:@10]
            && [info[@"effective_seconds"] isEqual:@330] && [info[@"cache_wait_seconds"] isEqual:@300]
            && [info[@"scope"] isEqual:@"unified-loopback"], "invalid_configuration_info");
        NSDictionary *checks = @{@"prepare_without_managed_access":@YES,
            @"initialization_before_write":@YES, @"first_snapshot_330":@YES,
            @"idempotent_configuration":@YES, @"unattested_rejected":@YES,
            @"wrong_thread_rejected":@YES, @"incomplete_api_rejected":@YES,
            @"invalid_identity_rejected":@YES, @"invalid_type_rejected":@YES,
            @"nonstatic_rejected":@YES, @"unexpected_default_rejected":@YES,
            @"readback_failure_rejected":@YES};
        NSDictionary *result = @{@"schema":@1, @"status":@"PASS", @"actual_macos_foundation_execution":@YES,
            @"actual_iOS_Unity_execution":@NO, @"initialized":@(id_octo_fixture.initialized),
            @"initializations":@(id_octo_fixture.initializations), @"reads":@(id_octo_fixture.reads),
            @"writes":@(id_octo_fixture.writes), @"value":@(id_octo_fixture.value),
            @"last_snapshot":@(id_octo_fixture.last_snapshot), @"budget":info,
            @"original_seconds":@10, @"effective_seconds":@330, @"cache_wait_seconds":@300,
            @"scope":@"unified-loopback", @"checks":checks};
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
        Require(json != nil, "fixture_json_failed");
        fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout);
    }
    return 0;
}
