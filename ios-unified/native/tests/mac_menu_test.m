#import <AppKit/AppKit.h>
#import "../IdolyMacMenu.h"
#include <stdio.h>
#include <stdlib.h>

static void Require(BOOL condition, const char *code) {
    if (!condition) {
        fprintf(stderr, "FAIL_MAC_SETTINGS_MENU: %s\n", code);
        exit(1);
    }
}

@interface IDMacMenuTestTarget : NSObject
@property(nonatomic) NSUInteger calls;
@property(nonatomic) BOOL callbacksOnMain;
- (void)openServerSettings:(id)sender;
@end

@implementation IDMacMenuTestTarget
- (instancetype)init {
    if ((self = [super init])) _callbacksOnMain = YES;
    return self;
}
- (void)openServerSettings:(id)sender {
    (void)sender;
    self.calls += 1;
    self.callbacksOnMain = self.callbacksOnMain && NSThread.isMainThread;
}
@end

static NSMenu *InstallApplicationMenu(void) {
    NSMenu *main = [[NSMenu alloc] initWithTitle:@"Test main menu"];
    NSMenu *application = [[NSMenu alloc] initWithTitle:@"Test application menu"];
    NSMenuItem *root = [[NSMenuItem alloc] initWithTitle:@"Test application" action:NULL keyEquivalent:@""];
    root.submenu = application;
    [main addItem:root];
    [application addItem:[[NSMenuItem alloc] initWithTitle:@"About test" action:NULL keyEquivalent:@""]];
    NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"Quit test" action:@selector(terminate:) keyEquivalent:@"q"];
    quit.target = NSApp;
    [application addItem:quit];
    NSApp.mainMenu = main;
    return application;
}

static NSMenuItem *FindSettings(NSMenu *menu, SEL action) {
    NSMenuItem *found = nil;
    NSUInteger count = 0;
    for (NSMenuItem *item in menu.itemArray) {
        if (item.action == action) { found = item; ++count; }
    }
    Require(count == 1, "one_settings_item_required");
    return found;
}

int main(void) {
    @autoreleasepool {
        Require(NSThread.isMainThread, "test_must_run_on_main_thread");
        [NSApplication sharedApplication];
        NSMenu *previous = NSApp.mainMenu;
        IDMacMenuTestTarget *target = [IDMacMenuTestTarget new];
        SEL action = @selector(openServerSettings:);

        NSMenu *application = InstallApplicationMenu();
        NSInteger before = application.numberOfItems;
        Require(IDMacInstallSettingsMenu(target, action), "first_install_failed");
        Require(application.numberOfItems == before + 1, "first_install_count_differs");
        Require(IDMacInstallSettingsMenu(target, action), "repeat_install_failed");
        Require(application.numberOfItems == before + 1, "duplicate_install_added_an_item");
        NSMenuItem *item = FindSettings(application, action);
        Require([item.title isEqualToString:@"로컬 서버 설정…"], "menu_title_differs");
        Require([item.keyEquivalent isEqualToString:@"<"], "menu_key_equivalent_differs");
        Require(item.keyEquivalentModifierMask == (NSEventModifierFlagCommand | NSEventModifierFlagShift),
                "menu_modifier_mask_differs");
        Require(item.target == target, "menu_target_differs");
        NSInteger index = [application indexOfItem:item];
        Require(index >= 0 && index == application.numberOfItems - 2
                && [application itemAtIndex:index + 1].action == @selector(terminate:),
                "menu_must_precede_last_quit_item");
        [application removeItem:item];
        Require(IDMacInstallSettingsMenu(target, action), "removed_item_reinstall_failed");
        Require(IDMacInstallSettingsMenu(target, action), "removed_item_repeat_install_failed");
        Require(application.numberOfItems == before + 1 && FindSettings(application, action) == item,
                "removed_item_must_be_reused_without_duplicates");
        Require([NSApp sendAction:item.action to:item.target from:item], "native_menu_action_not_dispatched");
        Require(target.calls == 1 && target.callbacksOnMain, "native_menu_action_must_call_main_once");

        // Require real AppKit matching and synchronous dispatch of the shifted
        // comma character. This is still separate from physical PlayCover input.
        NSUInteger beforeKey = target.calls;
        NSEvent *key = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
            modifierFlags:(NSEventModifierFlagCommand | NSEventModifierFlagShift)
            timestamp:0 windowNumber:0 context:nil characters:@"<" charactersIgnoringModifiers:@"<"
            isARepeat:NO keyCode:43];
        BOOL shiftedCommaHandled = key ? [application performKeyEquivalent:key] : NO;
        BOOL keyCreated = key != nil;
        NSUInteger keyCallbackDelta = target.calls - beforeKey;
        Require(keyCreated && shiftedCommaHandled && keyCallbackDelta == 1 && target.callbacksOnMain,
                "shift_comma_key_dispatch_failed");

        NSMenu *replacement = InstallApplicationMenu();
        Require(replacement != application, "test_main_menu_not_replaced");
        before = replacement.numberOfItems;
        Require(IDMacInstallSettingsMenu(target, action), "replacement_install_failed");
        Require(IDMacInstallSettingsMenu(target, action), "replacement_repeat_install_failed");
        Require(replacement.numberOfItems == before + 1, "replacement_menu_not_idempotent");
        NSMenuItem *replacementItem = FindSettings(replacement, action);
        Require(replacementItem.target == target, "replacement_target_differs");
        NSUInteger beforeReplacementAction = target.calls;
        Require([NSApp sendAction:replacementItem.action to:replacementItem.target from:replacementItem],
                "replacement_action_not_dispatched");
        Require(target.calls == beforeReplacementAction + 1 && target.callbacksOnMain,
                "replacement_action_must_call_main_once");

        __block BOOL offMainAccepted = YES;
        dispatch_semaphore_t complete = dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            offMainAccepted = IDMacInstallSettingsMenu(target, action);
            dispatch_semaphore_signal(complete);
        });
        Require(dispatch_semaphore_wait(complete, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC)) == 0,
                "off_main_guard_blocked_on_main_thread");
        Require(!offMainAccepted, "off_main_install_must_be_rejected");
        Require(replacement.numberOfItems == before + 1, "off_main_install_changed_the_menu");

        NSApp.mainMenu = previous;
        NSDictionary *result = @{@"status": @"PASS", @"actual_macos_appkit_execution": @YES,
            @"menu_install": @YES, @"idempotence": @YES, @"before_quit": @YES,
            @"removed_item_reattachment": @YES,
            @"target_action_dispatch": @YES, @"callbacks_on_main_thread": @YES,
            @"main_menu_replacement": @YES, @"off_main_rejected": @YES,
            @"shortcut_metadata_verified": @YES,
            @"shortcut_dispatch_verified": @YES,
            @"synthetic_shift_comma_event_created": @(keyCreated),
            @"synthetic_shift_comma_key_event_handled": @(shiftedCommaHandled),
            @"synthetic_shift_comma_callback_count": @(keyCallbackDelta),
            @"physical_PlayCover_key_event_tested": @NO,
            @"windows_or_simulators_created": @NO};
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
        Require(json != nil, "test_result_json_failed");
        fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout);
    }
    return 0;
}
