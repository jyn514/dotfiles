import AppKit
import Carbon.HIToolbox
import Foundation

private struct MemoryPreferences: PreferenceReading {
    var values: [String: [String: PreferenceValue]]

    func value(domain: String, key: String) -> PreferenceValue? {
        values[domain]?[key]
    }
}

private enum TestFailure: Error, CustomStringConvertible {
    case assertion(String)
    var description: String { switch self { case .assertion(let message): message } }
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    guard condition() else { throw TestFailure.assertion(message) }
}

@main
private struct Tests {
    static func main() throws {
        let policyPath = CommandLine.arguments[1]
        let data = try Data(contentsOf: URL(fileURLWithPath: policyPath))
        let policy = try JSONDecoder().decode(Policy.self, from: data)
        let initial = plan(policy: policy, store: MemoryPreferences(values: [:]))

        let screenshot = try initial.first {
            $0.domain == "com.apple.screencapture" && $0.key == "location"
        }.unwrap("missing screenshot location")
        try expect(
            screenshot.desired == .string(
                FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Documents").path + "/"
            ),
            "screenshot path was not expanded"
        )

        let leftHalf = try initial.first {
            $0.domain == "com.knollsoft.Rectangle" && $0.key == "leftHalf"
        }.unwrap("missing Rectangle leftHalf shortcut")
        try expect(
            leftHalf.desired == .shortcut(
                keyCode: Int(kVK_ANSI_H),
                modifierFlags: NSEvent.ModifierFlags([.shift, .command]).rawValue
            ),
            "Rectangle shortcut was not translated semantically"
        )

        var matching: [String: [String: PreferenceValue]] = [:]
        for change in initial { matching[change.domain, default: [:]][change.key] = change.desired }
        try expect(
            plan(policy: policy, store: MemoryPreferences(values: matching)).isEmpty,
            "matching preferences were reported as drift"
        )

        matching["com.theron.UnnaturalScrollWheels"]?["ScrollLines"] = .integer(9)
        let drift = plan(policy: policy, store: MemoryPreferences(values: matching))
        try expect(drift.count == 1, "one changed value did not produce one drift entry")
        try expect(drift.first?.key == "ScrollLines", "wrong drift key")
        try expect(drift.first?.current == .integer(9), "wrong current drift value")
        try expect(drift.first?.desired == .integer(1), "wrong desired drift value")
    }
}

private extension Optional {
    func unwrap(_ message: String) throws -> Wrapped {
        guard let value = self else { throw TestFailure.assertion(message) }
        return value
    }
}
