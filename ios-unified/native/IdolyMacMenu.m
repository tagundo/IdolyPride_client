#import "IdolyMacMenu.h"
#import <TargetConditionals.h>
#import <objc/runtime.h>

static NSString *IDMacSettingsMenuTitle;

#if !TARGET_OS_SIMULATOR
// These are public AppKit selectors with their exact Objective-C ABI. Keeping
// the declarations local lets the same source compile for the real iOS SDK;
// NSApplication/NSMenu/NSMenuItem are looked up only when present at runtime.
@protocol IDMacApplicationObject <NSObject>
- (id)mainMenu;
@end
@protocol IDMacApplicationClass <NSObject>
+ (id<IDMacApplicationObject>)sharedApplication;
@end
@protocol IDMacMenuObject <NSObject>
- (NSInteger)numberOfItems;
- (id)itemAtIndex:(NSInteger)index;
- (NSInteger)indexOfItem:(id)item;
- (void)insertItem:(id)item atIndex:(NSInteger)index;
@end
@protocol IDMacMenuItemObject <NSObject>
- (instancetype)initWithTitle:(NSString *)title action:(SEL)action keyEquivalent:(NSString *)key;
- (id)submenu;
- (id)menu;
- (id)target;
- (void)setTarget:(id)target;
- (SEL)action;
- (void)setAction:(SEL)action;
- (void)setKeyEquivalentModifierMask:(NSUInteger)mask;
- (void)setTitle:(NSString *)title;
@end

static const char IDMacSettingsMenuKey;
static const NSInteger IDMacMaximumMenuItems = 512;
static __weak id<IDMacMenuItemObject> IDMacInstalledSettingsItem;

static BOOL IDMacUsableMenu(id menu, Class menuClass) {
    return menu && [menu isKindOfClass:menuClass]
        && [menu respondsToSelector:@selector(numberOfItems)]
        && [menu respondsToSelector:@selector(itemAtIndex:)]
        && [menu respondsToSelector:@selector(indexOfItem:)]
        && [menu respondsToSelector:@selector(insertItem:atIndex:)];
}

static BOOL IDMacUsableItem(id item, Class itemClass) {
    return item && [item isKindOfClass:itemClass]
        && [item respondsToSelector:@selector(menu)]
        && [item respondsToSelector:@selector(target)]
        && [item respondsToSelector:@selector(setTarget:)]
        && [item respondsToSelector:@selector(action)]
        && [item respondsToSelector:@selector(setAction:)]
        && [item respondsToSelector:@selector(setKeyEquivalentModifierMask:)]
        && [item respondsToSelector:@selector(setTitle:)];
}
#endif

void IDMacSetSettingsMenuTitle(NSString *title) {
    if (!NSThread.isMainThread || ![title isKindOfClass:NSString.class]
            || !title.length || title.length > 128) return;
    IDMacSettingsMenuTitle = [title copy];
#if !TARGET_OS_SIMULATOR
    @try {
        id<IDMacMenuItemObject> item = IDMacInstalledSettingsItem;
        if ([item respondsToSelector:@selector(setTitle:)]) [item setTitle:IDMacSettingsMenuTitle];
    } @catch (NSException *exception) { (void)exception; }
#endif
}

BOOL IDMacInstallSettingsMenu(id target, SEL action) {
#if TARGET_OS_SIMULATOR
    // A UIKit Simulator process may expose AppKit classes while its host
    // application is still being initialized. Never query or create NSApp
    // there. PlayCover uses the device binary (this branch is compiled out).
    (void)target;
    (void)action;
    return NO;
#else
    if (!NSThread.isMainThread || !target || !action || ![target respondsToSelector:action]) return NO;
    Class<IDMacApplicationClass> applicationClass = (Class<IDMacApplicationClass>)NSClassFromString(@"NSApplication");
    Class menuClass = NSClassFromString(@"NSMenu");
    Class itemClass = NSClassFromString(@"NSMenuItem");
    if (!applicationClass || !menuClass || !itemClass
        || ![applicationClass respondsToSelector:@selector(sharedApplication)]
        || ![itemClass instancesRespondToSelector:@selector(initWithTitle:action:keyEquivalent:)]) return NO;
    @try {
        id<IDMacApplicationObject> application = [applicationClass sharedApplication];
        if (![application respondsToSelector:@selector(mainMenu)]) return NO;
        id<IDMacMenuObject> main = [application mainMenu];
        if (!IDMacUsableMenu(main, menuClass)) return NO;
        NSInteger mainCount = [main numberOfItems];
        if (mainCount < 1 || mainCount > IDMacMaximumMenuItems) return NO;
        id first = [main itemAtIndex:0];
        if (![first respondsToSelector:@selector(submenu)]) return NO;
        id<IDMacMenuObject> menu = [(id<IDMacMenuItemObject>)first submenu];
        if (!IDMacUsableMenu(menu, menuClass)) return NO;
        NSInteger count = [menu numberOfItems];
        if (count < 0 || count > IDMacMaximumMenuItems) return NO;

        id<IDMacMenuItemObject> item = objc_getAssociatedObject(menu, &IDMacSettingsMenuKey);
        if (IDMacUsableItem(item, itemClass)) {
            NSInteger index = [menu indexOfItem:item];
            if (index >= 0 && index < count && [menu itemAtIndex:index] == item) {
                if ([item target] != target) [item setTarget:target];
                if (!sel_isEqual([item action], action)) [item setAction:action];
                [item setTitle:IDMacSettingsMenuTitle ?: @"로컬 서버 설정…"];
                IDMacInstalledSettingsItem = item;
                return YES;
            }
            // Reuse our item after a menu rebuild removed it. An item moved to
            // another menu cannot be inserted twice; leave that menu alone.
            if ([item menu] != nil) item = nil;
        } else {
            item = nil;
        }
        if (count == IDMacMaximumMenuItems) return NO;
        if (!item) {
            // AppKit compares charactersIgnoringModifiers, which preserves
            // Shift: the physical Shift-comma key produces the character '<'.
            item = [(id<IDMacMenuItemObject>)[itemClass alloc]
                initWithTitle:IDMacSettingsMenuTitle ?: @"로컬 서버 설정…" action:action keyEquivalent:@"<"];
            if (!IDMacUsableItem(item, itemClass)) return NO;
        }
        [item setTarget:target];
        [item setAction:action];
        [item setTitle:IDMacSettingsMenuTitle ?: @"로컬 서버 설정…"];
        // NSEventModifierFlagCommand | NSEventModifierFlagShift, both NSUInteger.
        [item setKeyEquivalentModifierMask:((NSUInteger)1 << 20) | ((NSUInteger)1 << 17)];
        NSInteger index = count;
        if (count) {
            id last = [menu itemAtIndex:count - 1];
            if ([last respondsToSelector:@selector(action)]
                && sel_isEqual([(id<IDMacMenuItemObject>)last action], sel_registerName("terminate:"))) index = count - 1;
        }
        // Mark before insertion: the Mac integration observes menu rebuild
        // notifications, and our own insertion must not create a duplicate.
        objc_setAssociatedObject(menu, &IDMacSettingsMenuKey, item, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        [menu insertItem:item atIndex:index];
        IDMacInstalledSettingsItem = item;
        return YES;
    } @catch (NSException *exception) {
        // A PlayCover/menu lifecycle mismatch must not terminate the game.
        (void)exception;
        return NO;
    }
#endif
}
