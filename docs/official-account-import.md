# Official Japanese account import: protocol evidence and client contract

This feature uses the Japanese game's transfer ID and transfer password. They are not a Google/Apple password or a Firebase email/password login. The core client performs no local account/database mutation and never creates or recreates a game account.

## Evidence and remaining uncertainty

The original 6.1.1 descriptor is `data/protocol/idolypride-6.1.1.pb` (508,520 bytes; SHA-256 `c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad`). Its generated Go definitions at source pin `32096287ceed421b57a874cc38690068f665e8fb` establish these fields:

| Method | Request | Response used |
| --- | --- | --- |
| `Migration.MigratePassword` | `userId` string #1, `password` string #2 | `success` bool #1, `linkedUserId` string #2, `linkedUser` transaction.User #3, `onetimeToken` string #4 |
| `Migration.Execute` | `onetimeToken` string #1 | `token` string #1 |
| `Auth.Login` | `firebaseIDToken` string #1 | `gameAuthToken` string #1, `userPublic` #2, `requiredFirebaseReauthenticate` bool #3 |
| `Master.Get` | empty | `masterTag` #1, including its `version` string #1 |
| `User.Get` | empty | `user` #1, all other account fields, `userPublic` #999 |

`transaction.User` has `name` #1 and `managerLevel` #100, and **has no `id` field**. The preview therefore uses `linkedUserId` as its ID. The login and account responses expose `UserPublic.serverUserId` #1 and `publicUserId` #2. The client checks the inspection ID against the login identity, then requires both IDs to match exactly in `User.Get`. Preview name/level can change while the official account is in use and are not used as identity credentials.

The descriptor alone does not identify the consumer of `Execute.token`. Independent public compatibility implementations document and implement `MigratePassword → Execute → Firebase custom-token exchange → Auth.Login → Master.Get → User.Get`:

- [solis-server authentication sequence](https://github.com/vertesan/solis-server/blob/9b67c06939403d7035e1795745f791340a775868/docs/auth.md), and that pin's migration execution handler/integration test.
- [Archive Bridge collection sequence](https://github.com/Nagisa0803/archive-bridge/blob/4058a254d2dd546e78e946c566692296d6a251f3/src/archive_bridge/collector.py#L37) and [Firebase transport](https://github.com/Nagisa0803/archive-bridge/blob/4058a254d2dd546e78e946c566692296d6a251f3/src/archive_bridge/transport.py#L210). Its stated CI validation uses synthetic accounts, not official authentication.

Those references support the compatibility sequence; they do not prove the original 6.1.1 native call order or the official service's exact session invalidation, link mutation, token lifetime, or password retention policy. The original native `Execute.token` consumer and those server-side effects were not independently captured. The feature must not describe transfer execution as a read-only operation or promise that another device stays signed in. No official account authentication was performed while implementing or testing this change.

The existing local `official_session.py` separately supports an already saved PlayCover Firebase identity. It demonstrates seed/System.Check/Auth.Login/Master.Get handling but does not implement transfer-password authentication. The new feature does not fall back to that identity or to Firebase email/password authentication.

## Anonymous master compatibility preflight

The native import coordinator first pins the bytes and matching version in
`original-master/master-tag.json` (bounded to 16 MiB) and
`master-json/!version.txt` (4 KiB). Those two SHA-256 values and the expected
version remain only in the RAM job. Before `inspect` can send a seed request or
transfer credentials, `OfficialAccountClient.preflight_master_version` sends
only an empty `Master.Get` with `x-app-version=6.1.1` through the existing fixed,
verified TLS transport. It neither obtains a seed nor sends an auth token,
transfer ID, password, Firebase key, device ID or account request. A mismatching,
unavailable, malformed, cancelled or timed-out response stops the operation;
there is no retry, downgrade, data download or version-gate bypass.

After the user confirms collection, the coordinator checks the same local
file pins, repeats the anonymous query, then checks the pins again before
calling `fetch`. The verification ticket has not been consumed and
`Migration.Execute` has not run at that boundary. It also rechecks those local
pins before staging. The authenticated post-transfer master/version and
account-reference checks below remain mandatory: an anonymous response is not
proof that a later authenticated reply, or a service updated in between,
will return the same version. An error from that later check must not be
presented as a guarantee that no official transfer occurred.

The account-free audit at source `39bd` observed public master version
`6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11`,
while the existing runtime data is pinned to
`961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60`.
An unchanged official reply therefore blocks this old bundle before
credential inspection/transfer. This anonymous observation does not establish
what every authenticated account will receive. Updating the complete master,
translations and compatibility proofs is a separate task; this safeguard does
not update or relax any production data pin. No real transfer, Firebase sign-in
or official account login was performed to implement or test it.

Remote-only synthetic tests cover the anonymous header/request boundary,
known version mismatch, unavailable/invalid replies, deadlines, cancellation,
expiry, concurrent use, byte changes to either pinned local file, preservation
of normal/viewing account tables, and the retained authenticated mismatch gate.

## Explicit two-step API

`OfficialAccountClient(schema, platform="ios" | "android", transport=None, config=None)` validates the actual descriptor field numbers/types and a public, per-platform configuration. With no usable configuration it fails closed before network construction. `official_account_config.load_public_config(platform)` owns extraction/provenance; injected synthetic configuration is used in unit tests. The client requires the Japanese project's ID/number, bundle identity, platform-specific Google app ID, and supported application version. The bundled loader includes the public API keys and original signer/project configuration extracted from the SHA-pinned original apps. These are public app settings, separate from account passwords and tokens.

1. `inspect(user_id, password, cancel=None, progress=None)` obtains a seed, checks server availability, then calls only `Migration.MigratePassword`. The preview requires a successful response, matching ID, usable ticket and named/leveled user. It returns a `Verification` containing a RAM-only ticket and metadata, plus a safe name/level/ID preview. It does not call `Migration.Execute`.
2. The host must obtain the user's explicit confirmation before calling `fetch(verification, ...)`. `fetch` consumes that exact client's ticket before its first Execute attempt. It then exchanges the returned custom token using Firebase, verifies identity through the fixed lookup endpoint, checks the service, logs in and reads the master/account responses. `Auth.Create`, `Auth.Recreate`, refresh, transfer-password changes, and gameplay mutation are never fallback operations.
3. `CollectedAccount` contains exact `user_get` and `master_get` protobuf bytes, master version, public/server IDs and platform. It contains no authentication reply, token, password, or RPC metadata. The host validates master compatibility and creates a new local account through the account manager's durable import path; fetching alone does not change an existing local account.

A ticket lasts at most 600 seconds using a monotonic deadline (the displayed timestamps use Unix seconds). Another inspection forgets the previous ticket. Failed, cancelled, or successful fetches close it. An expired ticket is also erased. A lost Execute response cannot be retried using the same ticket; the client cannot establish whether the official service processed it. Concurrent fetches cannot issue Execute twice. `Verification.close()`, `OfficialAccountClient.forget()/close()` and `CollectedAccount.close()` release their held secrets/private raw bytes. Python objects may have temporary copies; this is memory-only retention, not a guarantee of forensic erasure.

Before returning, the client also rejects a literal copy of a long ticket/seed/custom token/ID token/refresh token/game token obtained during this fetch if it appears in the raw account or master response. The compact comparison set stays in RAM and is cleared on every outcome. This gate does not retain the password across inspection and fetch, does not scan against an unavailable password, and does not establish that arbitrary original server fields cannot coincidentally contain private text. Its guarantee is that this code never exports its authentication requests/responses/metadata and rejects observed long-token reflection, while preserving the remaining original account protobuf bytes.

Application input bounds are 1–64 ASCII letters/digits/underscore/hyphen for the transfer ID and 1–128 printable ASCII characters without leading/trailing whitespace for the password. These are bounded input handling rules, **not a claim that the official password policy is 8–16 characters**. The descriptor does not establish that current policy. Passwords are not cached for a second request.

## Identity, transport and failure boundaries

Custom-token JWT claims must use RS256, the fixed IdentityToolkit audience, a project-scoped IAM service-account issuer/subject, a nonempty UID and current bounded timestamps. The Firebase ID token must have the Japanese project audience/issuer, the same UID, the custom sign-in provider, and no tenant switch. An optional sign-in `localId` must match; modern responses that omit it remain supported. The authoritative HTTPS lookup must return exactly one enabled user with that UID. Local JWT parsing validates claims/scopes; it does not claim cryptographic signature verification. Firebase's verified TLS token exchange and lookup validate the tokens with the service.

The fixed-host transport owns TLS certificate and hostname verification, HTTP/2, application/gRPC failure detection, response bounds and cancellation deadlines. Environment proxies, redirects, arbitrary endpoints and automatic retries are excluded by that layer. The client rejects maintenance/before-release and review/alternate-host responses. The 6.1.1 `System.Check` response has no standalone forced-update field: an update/application rejection stops at the transport boundary rather than being inferred from an undocumented number. Reauthentication requests also stop the workflow.

Progress is a fixed stage from exported `STAGES`; failures are fixed credential-free `OfficialAccountError.code` values from `ERROR_CODES`. An exact finite `TRANSPORT_ERROR_CODES` allowlist preserves useful TLS, deadline, HTTP, gRPC/application, framing and incomplete-response distinctions. Arbitrary transport codes/messages fall back to a fixed operation-level failure. Remote bodies, raw exceptions, credentials and authentication metadata do not enter progress/error messages. Cancellation is checked before and after each transport boundary, and in-flight results are discarded after cancellation. The transport may finish or time out a request already sent before cancellation; this is especially relevant to Execute.

`tests/test_official_account.py` uses the original descriptor and synthetic transports exclusively. It covers the separated sequence, unknown protobuf preservation, identity/project/UID checks, maintenance, reauthentication, cancellation, token expiry, one-shot failure semantics, concurrent execution prevention, platform headers and redacted representations/errors. Those tests provide offline contract coverage; they are not evidence of successful live official authentication or complete recovery of every account/media domain. Photo bytes and independent histories are not obtained by a complete `User.Get` protobuf alone.

## Original app configuration proof

[Internal extraction run](https://github.com/tagundo/IdolyPride_client/actions/runs/43815222197) at `92ba3ab395d8aed25d049211cc33a5241533ded6` verified the exact original iOS/Android archive SHA pins, both original Android APK hashes/signers, and their app/project scopes. The 1,383-byte ZIP artifact `14201399992` was independently read back with full SHA-256 `5e8a2bf5a628e565a1425bbe0936ccae6fc37185d669e307c87cfbef8016c7f9`; it contains one 3,117-byte public configuration/provenance JSON. No official authentication occurred. The ARM64 split legitimately has an empty version name inherited from the validated 6.1.1 base. `official_account_config.py` bundles these public settings; its contract test reconstructs the exact JSON digest.

## Durable local application and scope

The native coordinator stages the complete, exact User.Get reply as an ordinary NORMAL account archive with eight account tables (format 2). The seven existing tables retain their exact data; the additional local Love progress table starts empty for an official snapshot. Strictly verified format 1 archives remain importable. It does not synthesize progress, merge paid balances between platforms, change viewing mode, or select a different account automatically. The local master version and referenced catalog IDs must match before applying. Local settings, earning clocks and retry receipts that the official reply does not contain start empty. Existing-account replacement requires the displayed revision and a durable restore point; it invalidates only the target profile's local sessions. Newly imported User.Get data outranks a stale captured User.Get fixture.

Verification and downloaded previews expire after ten minutes. Daemon expiry only releases RAM/private temporary copies and never starts a network operation. A consumed import receipt cannot be replayed after a successful commit, including when cleanup fails. Recognized SQL commit success stays success across later ordinary I/O errors in connection release, temporary-file cleanup, status refresh or iOS server restart; the UI gives fixed follow-up notices instead of inviting a repeated official transfer.

This imports the fields returned by User.Get, not every official endpoint or independent history. Photo image bytes, separate match/history domains and unimplemented game actions are not reconstructed by that protobuf. Other legacy capture-backed routes retain their existing replay behavior; a new local slot remains the default. The official service must still accept the supported client/version, and live transfer authentication has not been verified with a real account. Public releases remain on hold.

Public/server user IDs remain part of the imported game identity in the local account. Transfer passwords and authentication tokens are not archived. Native credential entry is cleared on submission or cancellation; RAM release is not a forensic-zeroization guarantee.
