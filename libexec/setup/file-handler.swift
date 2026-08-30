import AppKit
import Darwin
import UniformTypeIdentifiers

if CommandLine.arguments.dropFirst().first == "--filter-source-utis" {
    while let input = readLine() {
        let identifier = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if let type = UTType(identifier), type.conforms(to: .sourceCode) {
            print(identifier)
        }
    }
    exit(EXIT_SUCCESS)
}

if CommandLine.arguments.dropFirst().first == "--extension-utis" {
    while let input = readLine() {
        let extensionName = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if let type = UTType(filenameExtension: extensionName) {
            print("\(extensionName)\t\(type.identifier)")
        }
    }
    exit(EXIT_SUCCESS)
}

if CommandLine.arguments.dropFirst().first == "--file-defaults" {
    while let input = readLine() {
        let path = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let file = URL(fileURLWithPath: path)
        let application = NSWorkspace.shared.urlForApplication(toOpen: file)
        let bundleID = application.flatMap { Bundle(url: $0)?.bundleIdentifier } ?? ""
        print("\(path)\t\(bundleID)")
    }
    exit(EXIT_SUCCESS)
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        guard let command = Bundle.main.object(
            forInfoDictionaryKey: "JynCommand"
        ) as? [String] else {
            sender.reply(toOpenOrPrint: .failure)
            return
        }
        for filename in filenames {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = command + [filename]
            try? process.run()
        }
        sender.reply(toOpenOrPrint: .success)
        sender.terminate(nil)
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
