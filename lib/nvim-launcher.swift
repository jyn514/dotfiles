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

final class AppDelegate: NSObject, NSApplicationDelegate {
    func application(_ sender: NSApplication, openFiles filenames: [String]) {
        for filename in filenames {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = ["hx-hax", filename]
            try? process.run()
        }
        sender.reply(toOpenOrPrint: .success)
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
