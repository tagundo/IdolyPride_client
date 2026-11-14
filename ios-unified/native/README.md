# Embedded iOS server framework

`IdolyEmbeddedServer.framework` contains the UIKit controller and built-in
CPython bridge. It requires the separately packaged iOS Python 3.13 framework
and signed native stdlib frameworks. It never loads the macOS server app.

The device build has a required load dependency on the existing presentation
dylib. Presentation's early font gateways initialize first; this framework then
validates the original Unity UUID, `startUnity:` RVA/prefix, and exact Objective-C
ABI before replacing that one method implementation. The replacement defers
Unity startup without blocking UIKit. A persistent native worker initializes
isolated CPython, installs/starts the server, and forwards the original method
on the main queue exactly once after both listeners report ready.

Python is never finalized during gameplay. Commands and foreground recovery run
on the same worker, with its GIL released while idle. Three-finger long press
opens a temporary local WKWebView; it accepts messages only from the main frame
of the bundled settings page. Closing it releases the WebView and message handler.

```sh
# Linux: portable C state/origin policies and Mach-O admission fixtures only.
python3 -B ios-unified/native/build_native.py --portable-tests
python3 -B -m unittest discover -s ios-unified/native/tests -p 'test_*.py'

# macOS/Xcode, actual device framework.
python3 -B ios-unified/native/build_native.py \
  --sdk iphoneos --arch arm64 \
  --python-framework /runtime/Python.xcframework/ios-arm64/Python.framework \
  --presentation-library /inputs/IdolyPresentation.dylib \
  --output /fresh/IdolyEmbeddedServer.framework

# Explicit fake-Unity simulator probe; never a device release component.
python3 -B ios-unified/native/build_native.py \
  --sdk iphonesimulator --arch arm64 --smoke-simulator \
  --python-framework /runtime/Python.xcframework/ios-arm64_x86_64-simulator/Python.framework \
  --output /fresh-simulator/IdolyEmbeddedServer.framework
```

`IdolyEmbeddedServerStatusJSON`, `IdolyEmbeddedServerRetry`, and
`IdolyEmbeddedServerCommand` are exported for the independent UIKit probe.
`IdolyEmbeddedServerCryptoSelfTest` checks fixed NIST encrypt/decrypt fixtures
through the actual Python buffer/CommonCrypto callback on the native worker.
The simulator option deliberately omits the real-game RVA/UUID check and
presentation dependency. Its success cannot prove phone gameplay, performance,
or PlayCover compatibility. Apple SDK compilation, streaming cancellation,
foreground behavior, Files pickers, and actual device play need native validation.
