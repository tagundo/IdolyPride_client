# Resource reuse and stalled-download diagnostics

The game gateway and the server's resource library use the same selected
storage root. Android files are under `octo-cache`; iOS and PlayCover files
are under `octo-cache-ios`. Select their parent directory in the Mac app.
Verified stored objects are served over loopback HTTP before any upstream
download is attempted. The game may still show its download screen while
copying those bytes into its own cache.

## Original preservation catalog

The bulk preservation library must use the original platform catalog. A game
session can use translated resources or a locally advanced Japanese revision.
The factory now reuses the active game manifest only when its platform and
revision match the original archive; the existing complete identity checks
remain in place. Otherwise the library loads the original catalog lazily.
The game keeps its translated manifest and bundled translation source.

## Diagnosing a stalled client download

The loopback-only endpoint `http://127.0.0.1:8080/diagnostics/runtime` exposes
`runtime.resource_transfer`. Compare observations immediately before a client
download and after it stalls:

- `session_served_bytes` measures resource bytes sent from the server to the game.
- `session_received_bytes` measures new bytes fetched by the server from the CDN.
- `session_verified_files` counts successful new upstream downloads in this
  server session; it is not the number of files already stored on disk.
- The bounded request diagnostics retain active requests and the last failed
  request, including its safe resource identity and HTTP result. Later
  successful requests do not erase the last failure.

The Mac app displays these observations using its existing status polling.
Request diagnostics contain no HTTP headers, authentication keys, tokens or
raw query strings, and do not change the HTTP response or cache decision.

One reported v0.3.24 session had sent 4,118,226,035 resource bytes to the game
and fetched zero new CDN bytes. This confirms cache reuse during that session;
the cumulative snapshot does not identify which bytes were sent during its
offline full-download attempt or establish that every catalog file is stored.

Server integration checks exercise predownloaded files through actual local
HTTP manifest, HEAD, range and full-object requests with upstream access
forbidden, including translated and revision-pinned sessions. They do not
establish the cause of a physical PlayCover client's stalled progress.
No client reachability hook is part of this change: the inspected Android
`CanReach` caller runs after a failed HTTP operation, and a causal iOS admission
block was not established.
