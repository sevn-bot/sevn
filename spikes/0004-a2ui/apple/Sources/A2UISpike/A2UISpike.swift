import Foundation

/// ObjC name `SevnA2UISpikeHost`. The Swift type is referenced by the tests, which keeps
/// the class linked into the test bundle.
@objc(SevnA2UISpikeHost)
public final class A2UISpike: NSObject {
    private let box = EngineBox()

    @objc(evalJSON:)
    public func evalJSON(_ json: String) -> NSString {
        let box = self.box
        let text: String
        if Thread.isMainThread {
            text = MainActor.assumeIsolated {
                box.eval(json)
            }
        } else {
            text = DispatchQueue.main.sync {
                MainActor.assumeIsolated {
                    box.eval(json)
                }
            }
        }
        return text as NSString
    }

    @MainActor
    public static func writeScreenshots(payloadDirectory: URL, outputDirectory: URL) throws {
        let host = A2UISpike()
        let engine = SpikeEngine()
        engine.shotDirectory = outputDirectory
        host.box.engine = engine
        let names = [
            "p1-form.json",
            "p2-table-update.json",
            "p3-secret.json",
            "p4-approval.json",
            "p5-assist.json",
        ]
        for name in names {
            let file = payloadDirectory.appendingPathComponent(name)
            let data = try Data(contentsOf: file)
            let parsed = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
            var messages = parsed["messages"] as? [Any] ?? []
            if let update = parsed["update"] as? [Any] {
                messages.append(contentsOf: update)
            }
            let command: [String: Any] = ["op": "render", "messages": messages]
            let body = try JSONSerialization.data(withJSONObject: command)
            _ = host.evalJSON(String(data: body, encoding: .utf8) ?? "{}")
        }
    }

}

private final class EngineBox: @unchecked Sendable {
    var engine: SpikeEngine?

    @MainActor
    func eval(_ json: String) -> String {
        if engine == nil {
            engine = SpikeEngine()
        }
        return engine?.eval(json) ?? "{}"
    }
}
