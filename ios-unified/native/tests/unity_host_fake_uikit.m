#import "UnityHostFoundationUIKit.h"
// The fixture dylib owns these classes; it has no reverse executable symbols.
static __weak UIWindow *fixtureKeyWindow;
static unsigned fixtureWindowCreations;
@implementation UIViewController @end
@implementation UIWindow
- (instancetype)init {
    if ((self = [super init])) ++fixtureWindowCreations;
    return self;
}
- (void)makeKeyAndVisible { self.hidden = NO; fixtureKeyWindow = self; }
+ (UIWindow *)fixtureKeyWindow { return fixtureKeyWindow; }
+ (unsigned)fixtureWindowCreations { return fixtureWindowCreations; }
@end
@implementation UIApplication @end
