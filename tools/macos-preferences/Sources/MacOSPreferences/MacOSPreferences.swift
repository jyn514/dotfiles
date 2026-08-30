import AppKit
import Carbon.HIToolbox
import Foundation

enum PolicyError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self { case .message(let text): text }
    }
}

private struct AnyCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}

private func rejectUnknownKeys<T: CodingKey>(
    _ decoder: Decoder,
    allowed: Set<T>
) throws {
    let container = try decoder.container(keyedBy: AnyCodingKey.self)
    let allowedNames = Set(allowed.map(\.stringValue))
    let unknown = container.allKeys.map(\.stringValue).filter { !allowedNames.contains($0) }
    if !unknown.isEmpty {
        throw PolicyError.message("unknown keys: \(unknown.sorted().joined(separator: ", "))")
    }
}

struct Policy: Decodable {
    let version: Int
    let domains: [String: Domain]

    enum CodingKeys: String, CodingKey, CaseIterable { case version, domains }

    init(from decoder: Decoder) throws {
        try rejectUnknownKeys(decoder, allowed: Set(CodingKeys.allCases))
        let values = try decoder.container(keyedBy: CodingKeys.self)
        version = try values.decode(Int.self, forKey: .version)
        guard version == 1 else { throw PolicyError.message("unsupported policy version \(version)") }
        domains = try values.decode([String: Domain].self, forKey: .domains)
    }
}

struct Domain: Decodable {
    let preferences: [String: Literal]
    let shortcuts: [String: Shortcut]

    enum CodingKeys: String, CodingKey, CaseIterable { case preferences, shortcuts }

    init(from decoder: Decoder) throws {
        try rejectUnknownKeys(decoder, allowed: Set(CodingKeys.allCases))
        let values = try decoder.container(keyedBy: CodingKeys.self)
        preferences = try values.decodeIfPresent([String: Literal].self, forKey: .preferences) ?? [:]
        shortcuts = try values.decodeIfPresent([String: Shortcut].self, forKey: .shortcuts) ?? [:]
        guard !preferences.isEmpty || !shortcuts.isEmpty else {
            throw PolicyError.message("domain contains no preferences")
        }
        let overlap = Set(preferences.keys).intersection(shortcuts.keys)
        guard overlap.isEmpty else {
            throw PolicyError.message("keys appear as both preferences and shortcuts: \(overlap.sorted().joined(separator: ", "))")
        }
    }
}

enum Literal: Decodable, Equatable {
    case boolean(Bool)
    case integer(Int)
    case string(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if let decoded = try? value.decode(Bool.self) { self = .boolean(decoded) }
        else if let decoded = try? value.decode(Int.self) { self = .integer(decoded) }
        else if let decoded = try? value.decode(String.self) { self = .string(decoded) }
        else { throw PolicyError.message("preference values must be booleans, integers, or strings") }
    }

    var preferenceValue: PreferenceValue {
        switch self {
        case .boolean(let value): return .boolean(value)
        case .integer(let value): return .integer(value)
        case .string(let value):
            if value.hasPrefix("~/") {
                return .string(FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent(String(value.dropFirst(2))).path + (value.hasSuffix("/") ? "/" : ""))
            }
            return .string(value)
        }
    }
}

struct Shortcut: Decodable {
    let key: Key
    let modifiers: Set<Modifier>

    enum CodingKeys: String, CodingKey, CaseIterable { case key, modifiers }

    init(from decoder: Decoder) throws {
        try rejectUnknownKeys(decoder, allowed: Set(CodingKeys.allCases))
        let values = try decoder.container(keyedBy: CodingKeys.self)
        key = try values.decode(Key.self, forKey: .key)
        let decoded = try values.decode([Modifier].self, forKey: .modifiers)
        guard !decoded.isEmpty else { throw PolicyError.message("shortcut modifiers may not be empty") }
        guard Set(decoded).count == decoded.count else { throw PolicyError.message("shortcut modifiers must be unique") }
        modifiers = Set(decoded)
    }

    var preferenceValue: PreferenceValue {
        .shortcut(keyCode: key.keyCode, modifierFlags: modifiers.reduce(0) { $0 | $1.flag })
    }
}

enum Key: String, Decodable {
    case c, h, i, j, k, l, m, u
    case comma, delete, equal, minus, `return`
    case leftArrow = "left-arrow"
    case rightArrow = "right-arrow"

    var keyCode: Int {
        switch self {
        case .c: Int(kVK_ANSI_C)
        case .h: Int(kVK_ANSI_H)
        case .i: Int(kVK_ANSI_I)
        case .j: Int(kVK_ANSI_J)
        case .k: Int(kVK_ANSI_K)
        case .l: Int(kVK_ANSI_L)
        case .m: Int(kVK_ANSI_M)
        case .u: Int(kVK_ANSI_U)
        case .comma: Int(kVK_ANSI_Comma)
        case .delete: Int(kVK_Delete)
        case .equal: Int(kVK_ANSI_Equal)
        case .minus: Int(kVK_ANSI_Minus)
        case .return: Int(kVK_Return)
        case .leftArrow: Int(kVK_LeftArrow)
        case .rightArrow: Int(kVK_RightArrow)
        }
    }
}

enum Modifier: String, Decodable {
    case command, control, option, shift

    var flag: UInt {
        switch self {
        case .command: NSEvent.ModifierFlags.command.rawValue
        case .control: NSEvent.ModifierFlags.control.rawValue
        case .option: NSEvent.ModifierFlags.option.rawValue
        case .shift: NSEvent.ModifierFlags.shift.rawValue
        }
    }
}

enum PreferenceValue: Equatable, CustomStringConvertible {
    case boolean(Bool)
    case integer(Int)
    case string(String)
    case shortcut(keyCode: Int, modifierFlags: UInt)

    init?(object: Any?) {
        guard let object else { return nil }
        if CFGetTypeID(object as CFTypeRef) == CFBooleanGetTypeID() {
            self = .boolean((object as! NSNumber).boolValue)
        } else if let number = object as? NSNumber {
            self = .integer(number.intValue)
        } else if let string = object as? String {
            self = .string(string)
        } else if let dictionary = object as? [String: Any],
                  let keyCode = dictionary["keyCode"] as? NSNumber,
                  let flags = dictionary["modifierFlags"] as? NSNumber,
                  dictionary.count == 2 {
            self = .shortcut(keyCode: keyCode.intValue, modifierFlags: flags.uintValue)
        } else {
            return nil
        }
    }

    var object: Any {
        switch self {
        case .boolean(let value): value
        case .integer(let value): value
        case .string(let value): value
        case .shortcut(let keyCode, let modifierFlags):
            ["keyCode": keyCode, "modifierFlags": modifierFlags]
        }
    }

    var description: String {
        switch self {
        case .boolean(let value): String(value)
        case .integer(let value): String(value)
        case .string(let value): String(reflecting: value)
        case .shortcut(let keyCode, let modifierFlags):
            "shortcut(keyCode: \(keyCode), modifierFlags: \(modifierFlags))"
        }
    }
}

struct Change: Equatable {
    let domain: String
    let key: String
    let current: PreferenceValue?
    let desired: PreferenceValue
}

protocol PreferenceReading {
    func value(domain: String, key: String) -> PreferenceValue?
}

func plan(policy: Policy, store: PreferenceReading) -> [Change] {
    policy.domains.sorted(by: { $0.key < $1.key }).flatMap { domainName, domain in
        let desired = domain.preferences.mapValues(\.preferenceValue)
            .merging(domain.shortcuts.mapValues(\.preferenceValue)) { first, _ in first }
        return desired.sorted(by: { $0.key < $1.key }).compactMap { key, value in
            let current = store.value(domain: domainName, key: key)
            return current == value ? nil : Change(domain: domainName, key: key, current: current, desired: value)
        }
    }
}

struct SystemPreferences: PreferenceReading {
    func value(domain: String, key: String) -> PreferenceValue? {
        PreferenceValue(object: CFPreferencesCopyAppValue(key as CFString, domain as CFString))
    }

    func write(_ change: Change) {
        CFPreferencesSetAppValue(change.key as CFString, change.desired.object as CFPropertyList, change.domain as CFString)
    }

    func synchronize(domain: String) throws {
        guard CFPreferencesAppSynchronize(domain as CFString) else {
            throw PolicyError.message("could not synchronize \(domain)")
        }
    }
}

private func loadPolicy(path: String) throws -> Policy {
    let data = try Data(contentsOf: URL(fileURLWithPath: path))
    do { return try JSONDecoder().decode(Policy.self, from: data) }
    catch let error as PolicyError { throw error }
    catch { throw PolicyError.message("invalid policy: \(error)") }
}

private func runningApplicationDomains(in changes: [Change]) -> [String] {
    let applicationDomains = Set(changes.map(\.domain)).subtracting(["com.apple.screencapture"])
    return applicationDomains.filter {
        !NSRunningApplication.runningApplications(withBundleIdentifier: $0).isEmpty
    }.sorted()
}

private func printChanges(_ changes: [Change]) {
    for change in changes {
        print("\(change.domain) \(change.key): \(change.current?.description ?? "<unset>") -> \(change.desired)")
    }
}

private func writeError(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

private func run() throws -> Int32 {
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard arguments.count == 2, ["check", "plan", "apply"].contains(arguments[0]) else {
        throw PolicyError.message("usage: macos-preferences (check|plan|apply) POLICY.json")
    }
    let command = arguments[0]
    let policy = try loadPolicy(path: arguments[1])
    let store = SystemPreferences()
    let changes = plan(policy: policy, store: store)

    if command == "check" {
        if changes.isEmpty { print("preferences match policy") }
        else { writeError("\(changes.count) preference(s) differ") }
        return changes.isEmpty ? 0 : 1
    }
    if command == "plan" {
        printChanges(changes)
        return 0
    }

    let running = runningApplicationDomains(in: changes)
    guard running.isEmpty else {
        throw PolicyError.message("quit these applications before applying: \(running.joined(separator: ", "))")
    }
    for change in changes { store.write(change) }
    for domain in Set(changes.map(\.domain)).sorted() { try store.synchronize(domain: domain) }
    print("applied \(changes.count) preference(s)")
    return 0
}

#if !TESTING
@main
private struct Application {
    static func main() {
        do { exit(try run()) }
        catch {
            writeError("macos-preferences: \(error)")
            exit(2)
        }
    }
}
#endif
