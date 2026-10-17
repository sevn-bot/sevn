import A2UISpike
import Foundation
#if os(iOS)
    import UIKit
#endif

func spikePayloads() -> URL {
    URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("payloads")
}

func spikeScreens() -> URL {
    if let override = ProcessInfo.processInfo.environment["SEVN_SPIKE_SHOTS"], !override.isEmpty {
        return URL(fileURLWithPath: override, isDirectory: true)
    }
    return URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("screens")
}

@MainActor
func writeSpikeScreens() {
    do {
        try A2UISpike.writeScreenshots(
            payloadDirectory: spikePayloads(),
            outputDirectory: spikeScreens()
        )
        exit(0)
    } catch {
        fputs("screenshots failed: \(error)\n", stderr)
        exit(1)
    }
}

#if os(iOS)
    @objc(ShotDelegate)
    final class ShotDelegate: UIResponder, UIApplicationDelegate {
        @objc var window: UIWindow?

        func application(
            _ application: UIApplication,
            didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
        ) -> Bool {
            let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 390, height: 844))
            window.backgroundColor = .white
            window.rootViewController = UIViewController()
            window.makeKeyAndVisible()
            self.window = window
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    writeSpikeScreens()
                }
            }
            return true
        }
    }

    UIApplicationMain(
        CommandLine.argc,
        CommandLine.unsafeArgv,
        nil,
        NSStringFromClass(ShotDelegate.self)
    )
#else
    writeSpikeScreens()
#endif
