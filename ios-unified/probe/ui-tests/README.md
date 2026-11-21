# Public Cancel UI test

This project builds a separate dummy host and standard XCTest UI runner. The
single UI test attaches to `game.qualiarts.idolypride.iosprobe`; it never launches,
activates, terminates, installs, or resets Probe. Use only the disposable Simulator
owned by the smoke harness. No official credentials or official login is used.

The native Probe sets `idoly-official-probe-transfer-id` and
`idoly-official-probe-transfer-password` on its two fields after filling fixed
synthetic inputs. XCTest reads only the known ID canary, never the password value.
It requires a single alert, one ordinary field, one secure field, iOS/Android
platform actions, and exactly one Cancel label (`취소`, `Cancel`, or `キャンセル`).
The sole UI input is a public XCTest `tap()` on that hittable Cancel button.

Build once with `xcodebuild -project IdolyProbeCancelUITests.xcodeproj -scheme
IdolyProbeCancelUITests -configuration Debug -destination id=<UDID>
-derivedDataPath <build-dir> CODE_SIGNING_ALLOWED=NO build-for-testing`. Then run
`xcodebuild -xctestrun <build-dir>/Build/Products/<generated>.xctestrun -destination
id=<UDID> -resultBundlePath <result>.xcresult -parallel-testing-enabled NO
-only-testing:IdolyProbeCancelUITests/OfficialPromptCancelTests/testCancelExistingProbePrompt
test-without-building` against the same Simulator. Do not request test retries.
Start the runner first and wait for its method-entry stdout marker
`IDOLY_CANCEL_UITEST_WAITING_FOR_PROBE` before independently launching Probe.
This ensures runner startup has finished before Probe enters the foreground.
It waits up to 60 seconds for Probe foreground,
then 180 seconds for the prepared prompt. The public Cancel gate runs after
menu diagnostics and before independent ZIP/account smoke gates.
Prompt disappearance after Cancel has a separate 10-second bound.

Primary evidence is the exact test's success in the standard `.xcresult` with one
test and zero failures. `IdolyOfficialPromptCancelEvidence.json` is a supplemental
attachment containing only fixed scope and observed boolean conditions. The log
marker alone is not proof. Existing native gates separately require the correlated
Web cancellation reply, cleared fields, prompt detachment, no official job, and
unchanged account/runtime data. This test does not claim official authentication
or actual game-play validation.
