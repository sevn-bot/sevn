// swift-tools-version: 6.1

import PackageDescription

// v0.9.1 and the v1.0 candidate are both on this revision. See ../PINS.md.
// Linked from the library target when the SwiftUI surface lands (W3).

let package = Package(
    name: "A2UISpike",
    platforms: [
        .macOS(.v14),
        .iOS(.v16),
    ],
    products: [
        .library(name: "A2UISpike", targets: ["A2UISpike"]),
    ],
    dependencies: [
        .package(
            url: "https://github.com/a2ui-project/a2ui.git",
            revision: "d1ba35c41f279d59e438ca029660ea62e0dc8f71"
        ),
    ],
    targets: [
        .target(name: "A2UISpike"),
        .testTarget(name: "A2UISpikeTests", dependencies: ["A2UISpike"]),
    ]
)
