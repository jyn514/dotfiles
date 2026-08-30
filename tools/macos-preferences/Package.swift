// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "macos-preferences",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "macos-preferences", targets: ["MacOSPreferences"]),
    ],
    targets: [
        .executableTarget(name: "MacOSPreferences"),
    ]
)
