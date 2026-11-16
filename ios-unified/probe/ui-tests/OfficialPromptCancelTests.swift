import Foundation
import XCTest

final class OfficialPromptCancelTests: XCTestCase {
    override func setUp() {
        super.setUp()
        continueAfterFailure = false
        executionTimeAllowance = 300
    }

    @MainActor
    func testCancelExistingProbePrompt() throws {
        FileHandle.standardOutput.write(Data("IDOLY_CANCEL_UITEST_WAITING_FOR_PROBE\n".utf8))
        // Attach to an independently started Probe. In particular, never call
        // launch(), activate(), terminate(), or a platform/default alert action.
        let probe = XCUIApplication(bundleIdentifier: "game.qualiarts.idolypride.iosprobe")
        let foreground = probe.wait(for: .runningForeground, timeout: 60)
        XCTAssertTrue(foreground, "The independently started Probe must be in the foreground")
        FileHandle.standardOutput.write(Data("IDOLY_CANCEL_UITEST_PROBE_FOREGROUND\n".utf8))

        // Native sets these identifiers only after filling fixed synthetic data.
        // The public Cancel gate runs before independent first-cold ZIP/account work.
        let transferID = "idoly-official-probe-transfer-id"
        let passwordID = "idoly-official-probe-transfer-password"
        let alert = probe.alerts.containing(.textField, identifier: transferID).firstMatch
        FileHandle.standardOutput.write(Data("IDOLY_CANCEL_UITEST_WAITING_FOR_PROMPT\n".utf8))
        XCTAssertTrue(alert.waitForExistence(timeout: 180), "Expected the prepared native transfer prompt")
        FileHandle.standardOutput.write(Data("IDOLY_CANCEL_UITEST_PROMPT_FOUND\n".utf8))
        let singleAlert = probe.alerts.count == 1
        let idField = alert.textFields.matching(identifier: transferID).firstMatch
        let passwordField = alert.secureTextFields.matching(identifier: passwordID).firstMatch
        let twoTypedFields = alert.textFields.count == 1 && alert.secureTextFields.count == 1
        let securePasswordField = passwordField.exists
        // Never read the secure field's value, type credentials, or serialize inputs.
        let syntheticID = idField.exists && (idField.value as? String) == "ProbeNeverSubmit_ID"
        let buttons = alert.buttons.allElementsBoundByIndex
        let cancelTitles: Set<String> = ["취소", "Cancel", "キャンセル"]
        let cancels = buttons.filter { cancelTitles.contains($0.label) }
        let iosTitles: Set<String> = ["iOS 계정 확인", "iOSアカウントを確認", "Check iOS account"]
        let androidTitles: Set<String> = ["Android 계정 확인", "Androidアカウントを確認", "Check Android account"]
        let threeActions = buttons.count == 3
        let platformActions = buttons.filter { iosTitles.contains($0.label) }.count == 1
            && buttons.filter { androidTitles.contains($0.label) }.count == 1
        let exactCancel = cancels.count == 1
        XCTAssertTrue(singleAlert)
        XCTAssertTrue(twoTypedFields)
        XCTAssertTrue(securePasswordField)
        XCTAssertTrue(syntheticID)
        XCTAssertTrue(threeActions)
        XCTAssertTrue(platformActions)
        XCTAssertTrue(exactCancel)
        let cancel = cancels[0]
        let hittable = cancel.isEnabled && cancel.isHittable
        XCTAssertTrue(hittable, "The exact Cancel action must be enabled and hittable")
        FileHandle.standardOutput.write(Data("IDOLY_CANCEL_UITEST_BEFORE_CANCEL_TAP\n".utf8))
        cancel.tap() // The sole UI input performed by this test.
        FileHandle.standardOutput.write(Data("IDOLY_CANCEL_UITEST_AFTER_CANCEL_TAP\n".utf8))
        let disappeared = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: alert)
        let dismissed = XCTWaiter.wait(for: [disappeared], timeout: 10) == .completed
        XCTAssertTrue(dismissed, "The native prompt must disappear after the real Cancel tap")
        FileHandle.standardOutput.write(Data("IDOLY_CANCEL_UITEST_PROMPT_DISMISSED\n".utf8))
        XCTAssertEqual(probe.state, .runningForeground)

        // Additional native gates independently require the cancelled Web ACK,
        // cleared fields, no official job, and unchanged account/runtime data.
        // This attachment records only fixed scope and observed scalar flags.
        let evidence: [String: Any] = [
            "schema": 1,
            "scope": "existing-probe-public-xctest",
            "probe_running_foreground": foreground,
            "single_alert": singleAlert,
            "two_typed_fields": twoTypedFields,
            "secure_password_field": securePasswordField,
            "synthetic_id_present": syntheticID,
            "three_actions": threeActions,
            "platform_actions_present": platformActions,
            "exact_cancel_action_present": exactCancel,
            "cancel_button_hittable": hittable,
            "cancel_tapped": true,
            "prompt_dismissed": dismissed,
            "credential_submission_performed": false
        ]
        let data = try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "IdolyOfficialPromptCancelEvidence.json"
        attachment.lifetime = .keepAlways
        add(attachment)
        print("IDOLY_OFFICIAL_PROMPT_CANCEL_UI_TEST_PASS")
    }
}
