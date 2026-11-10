# Public UIKit scene control on a Mac

The manual `uikit-host-control.yml` workflow builds this ordinary UIKit application
with Xcode's Mac Catalyst destination, then ad-hoc signs it with the standard App
Sandbox entitlement and opens it normally. It uses public `UIApplicationDelegate`,
`UIWindowSceneDelegate`, `UIWindow` and `UILabel` APIs. It does not use PlayCover,
the game, a local server, private check-in calls, security changes or SDK patches.

The workflow first repeats the existing Metal/UI host probe. It verifies the
compiled ARM64 Mach-O platform is `MACCATALYST`, preserves Xcode's processed
Info.plist and signing entitlements, and checks a visible label and stable PID in
three fresh AX observations. Screenshots and bounded own-process logs are saved.

The result answers whether this host can display a standard scene-based UIKit
Mac Catalyst app. Success does not prove that PlayCover's converted iOS app or
Unity lifecycle works. Failure is a platform check-in observation only if the
actual log contains the same scene/check-in error; a build or metadata failure
must be resolved separately. A same-source iOS/PlayCover control can follow this
result without changing this standard baseline.

Official references:

- [Apple: create a Mac version of an iPad app](https://developer.apple.com/documentation/uikit/creating-a-mac-version-of-your-ipad-app)
- [Apple: Mac Catalyst](https://developer.apple.com/documentation/uikit/mac-catalyst)
- [Apple: UIApplicationSceneManifest](https://developer.apple.com/documentation/bundleresources/information-property-list/uiapplicationscenemanifest)
- [Swift compiler's ARM64 macabi driver checks](https://github.com/swiftlang/swift/blob/fc628a8bfbf8481519235cfc5bcae5a58288c61b/test/Driver/macabi-environment.swift)
