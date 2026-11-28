#ifndef IDOLY_UNITY_HOST_FOUNDATION_UIKIT_H
#define IDOLY_UNITY_HOST_FOUNDATION_UIKIT_H
#import <Foundation/Foundation.h>
typedef NSUInteger UIInterfaceOrientationMask;
enum { UIInterfaceOrientationMaskAllButUpsideDown = 26 };
@interface UIViewController : NSObject @end
enum { UIWindowLevelNormal = 0 };
@interface UIWindow : NSObject
@property(nonatomic, strong) UIViewController *rootViewController;
@property(nonatomic) double windowLevel;
@property(nonatomic) BOOL hidden;
- (void)makeKeyAndVisible;
@end
@interface UIApplication : NSObject
@property(nonatomic, strong) id delegate;
@end
@protocol UIUserActivityRestoring <NSObject> @end
@protocol UIApplicationDelegate <NSObject>
@optional
@property(nonatomic, strong) UIWindow *window;
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options;
- (BOOL)application:(UIApplication *)application openURL:(NSURL *)url options:(NSDictionary *)options;
- (BOOL)application:(UIApplication *)application continueUserActivity:(NSUserActivity *)activity
    restorationHandler:(void (^)(NSArray<id<UIUserActivityRestoring>> *))restorationHandler;
- (void)applicationWillResignActive:(UIApplication *)application;
- (void)applicationDidEnterBackground:(UIApplication *)application;
- (void)applicationWillEnterForeground:(UIApplication *)application;
- (void)applicationDidBecomeActive:(UIApplication *)application;
- (void)applicationWillTerminate:(UIApplication *)application;
- (void)applicationDidReceiveMemoryWarning:(UIApplication *)application;
- (UIInterfaceOrientationMask)application:(UIApplication *)application
    supportedInterfaceOrientationsForWindow:(UIWindow *)window;
@end
#endif
