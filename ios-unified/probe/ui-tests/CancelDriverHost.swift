import UIKit

// A separate standard test host. The UI test never launches this app or Probe.
@main
final class CancelDriverHost: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        let controller = UIViewController()
        controller.view.backgroundColor = .systemBackground
        window.rootViewController = controller
        self.window = window
        window.makeKeyAndVisible()
        return true
    }
}
