#import <Foundation/Foundation.h>
#import "../IdolyLocalHTTP.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void Require(BOOL condition, const char *message) {
    if (!condition) { fprintf(stderr, "FAIL_LOCAL_HTTP: %s\n", message); exit(1); }
}
static NSDictionary *WorkerRequest(NSUInteger port, NSTimeInterval timeout) {
    __block NSDictionary *value;
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        @autoreleasepool { value = IDLocalHTTPReadiness(port, timeout); }
        dispatch_semaphore_signal(done);
    });
    // The real app keeps its main run loop active while the worker performs
    // this request. Do the same here: a cold NSURLSession may schedule initial
    // Foundation work on main before its private delegate queue can respond.
    // The request remains on the worker, with the same absolute fixture bound.
    NSTimeInterval deadline = NSProcessInfo.processInfo.systemUptime + 12;
    while (dispatch_semaphore_wait(done, DISPATCH_TIME_NOW) != 0) {
        Require(NSProcessInfo.processInfo.systemUptime < deadline, "worker_request_exceeded_deadline");
        [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode
            beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    }
    Require(value != nil && [value[@"worker_main_thread"] isEqual:@NO], "request_did_not_run_on_worker");
    return value;
}
static void ValidShape(NSDictionary *value) {
    NSSet *expected = [NSSet setWithArray:@[@"schema", @"ok", @"transport", @"url", @"http_status",
        @"error_code", @"body_is_json", @"received_bytes", @"worker_main_thread", @"ns_error_domain", @"ns_error_code"]];
    Require([[NSSet setWithArray:value.allKeys] isEqualToSet:expected], "diagnostic_fields_not_fixed");
    Require([value[@"schema"] isEqual:@1] && [value[@"transport"] isEqual:@"NSURLSession"]
        && [value[@"received_bytes"] unsignedIntegerValue] <= 16384, "diagnostic_shape_or_body_bound_invalid");
    Require([@[@"none", @"connection", @"timeout", @"http_status", @"invalid_json", @"response_too_large",
        @"redirect", @"main_thread", @"invalid_port", @"transport"] containsObject:value[@"error_code"]],
        "unbounded_error_code");
    Require(value[@"ns_error_domain"] == NSNull.null || [@[@"NSURLErrorDomain", @"NSPOSIXErrorDomain",
        @"NSCocoaErrorDomain", @"NSOSStatusErrorDomain", @"Other"] containsObject:value[@"ns_error_domain"]],
        "unbounded_error_domain");
    Require(value[@"ns_error_code"] == NSNull.null || [value[@"ns_error_code"] isKindOfClass:NSNumber.class],
        "error_code_not_numeric");
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        Require(NSThread.isMainThread && argc >= 3, "fixture_arguments_invalid");
        char *end = NULL;
        unsigned long port = strtoul(argv[2], &end, 10);
        Require(argv[2][0] && end && !*end && port >= 1 && port <= 65535, "fixture_port_invalid");
        NSDictionary *result;
        if (!strcmp(argv[1], "--validation")) {
            Require(argc == 3, "fixture_validation_arguments_invalid");
            NSDictionary *main = IDLocalHTTPReadiness(port, 1);
            ValidShape(main);
            Require([main[@"error_code"] isEqual:@"main_thread"] && [main[@"received_bytes"] isEqual:@0],
                "main_thread_call_not_rejected");
            for (NSNumber *invalidPort in @[@0, @65536]) {
                NSDictionary *invalid = WorkerRequest(invalidPort.unsignedIntegerValue, 1);
                ValidShape(invalid);
                Require([invalid[@"error_code"] isEqual:@"invalid_port"] && invalid[@"url"] == NSNull.null,
                    "invalid_port_not_rejected");
            }
            NSDictionary *invalidTimeout = WorkerRequest(port, NAN);
            ValidShape(invalidTimeout);
            Require([invalidTimeout[@"error_code"] isEqual:@"transport"], "nonfinite_timeout_not_rejected");
            result = @{@"status":@"PASS", @"actual_macos_foundation_execution":@YES,
                @"main_thread_rejected":@YES, @"invalid_ports_rejected":@YES, @"invalid_timeout_rejected":@YES};
        } else {
            Require(argc == 4 && !strcmp(argv[1], "--request"), "fixture_request_arguments_invalid");
            NSTimeInterval timeout = strtod(argv[3], &end);
            Require(argv[3][0] && end && !*end && isfinite(timeout) && timeout > 0 && timeout <= 10,
                "fixture_timeout_invalid");
            NSTimeInterval started = NSProcessInfo.processInfo.systemUptime;
            NSDictionary *readiness = WorkerRequest(port, timeout);
            NSTimeInterval elapsed = NSProcessInfo.processInfo.systemUptime - started;
            ValidShape(readiness);
            Require([readiness[@"url"] isEqual:[NSString stringWithFormat:@"http://127.0.0.1:%lu/client/playback", port]],
                "request_url_not_fixed_loopback");
            Require(elapsed <= timeout + 2, "request_did_not_obey_bounded_deadline");
            result = @{@"status":@"PASS", @"actual_macos_foundation_execution":@YES,
                @"readiness":readiness, @"elapsed_seconds":@(elapsed)};
        }
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
        Require(json != nil, "fixture_json_failed");
        fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout);
    }
    return 0;
}
