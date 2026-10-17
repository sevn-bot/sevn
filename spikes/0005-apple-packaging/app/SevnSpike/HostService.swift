import Darwin
import Foundation
import ServiceManagement

enum HostService {
    static let plistName = "com.sevn.spike.host.plist"

    // SMErrors.h: kSMErrorJobNotFound, kSMErrorAlreadyRegistered.
    private static let jobNotFound = 6
    private static let alreadyRegistered = 12

    static func register() -> Int32 {
        let service = SMAppService.agent(plistName: plistName)
        if service.status == .enabled {
            _ = unregister()
        }
        do {
            try service.register()
        } catch {
            let nsError = error as NSError
            if nsError.code != alreadyRegistered {
                fputs(
                    "register failed: \(nsError.domain) \(nsError.code) \(nsError.localizedDescription)\n",
                    stderr
                )
                return 1
            }
        }
        if service.status == .requiresApproval {
            fputs("register: launch agent requires approval in System Settings\n", stderr)
            return 1
        }
        return 0
    }

    static func unregister() -> Int32 {
        let service = SMAppService.agent(plistName: plistName)
        do {
            try service.unregister()
        } catch {
            let nsError = error as NSError
            if nsError.code != jobNotFound {
                fputs(
                    "unregister failed: \(nsError.domain) \(nsError.code) \(nsError.localizedDescription)\n",
                    stderr
                )
                return 1
            }
        }
        return 0
    }

    static func port() -> Int? {
        let url = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Library/LaunchAgents", isDirectory: true)
            .appendingPathComponent(plistName)
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        var format = PropertyListSerialization.PropertyListFormat.xml
        guard
            let plist = try? PropertyListSerialization.propertyList(
                from: data,
                options: [],
                format: &format
            ) as? [String: Any],
            let env = plist["EnvironmentVariables"] as? [String: Any]
        else {
            return nil
        }
        let port: Int? = if let raw = env["SEVN_SPIKE_PORT"] as? String {
            Int(raw)
        } else if let raw = env["SEVN_SPIKE_PORT"] as? Int {
            raw
        } else {
            nil
        }
        guard let port, (1...65535).contains(port) else {
            return nil
        }
        return port
    }

    static func healthStatus() async -> Int? {
        guard let port = port(), let url = URL(string: "http://127.0.0.1:\(port)/health") else {
            return nil
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode
        } catch {
            return nil
        }
    }
}
