import A2UICore
import A2UISwiftUI
import Foundation
import OrderedJSON
import SwiftUI
#if os(macOS)
    import AppKit
#else
    import UIKit
#endif

@MainActor
final class SpikeEngine: ActionHandling, @unchecked Sendable {
    let session: SpikeSession
    let catalog: Catalog<ComponentImplementation>
    private var processor: MessageProcessor
    private var unsupported: [String] = []
    private var logLines: [String] = []
    private var lastAction: [String: Any]?
    private var lastSecret: [String: String]?
    private var lastError = ""
    var shotDirectory: URL?

    init() {
        let session = SpikeSession()
        let catalog = SpikeCatalog.make(session: session)
        self.session = session
        self.catalog = catalog
        self.processor = MessageProcessor(catalog: catalog, actionHandler: nil)
        session.engine = self
        self.processor = MessageProcessor(catalog: catalog, actionHandler: self)
    }

    func eval(_ json: String) -> String {
        guard
            let data = json.data(using: .utf8),
            let command = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return encode(response())
        }
        let op = command["op"] as? String ?? ""
        switch op {
        case "render":
            render(command["messages"] as? [Any] ?? [], reset: true)
        case "update":
            render(command["messages"] as? [Any] ?? [], reset: false)
        case "act":
            act(label: command["label"] as? String ?? "", entries: command["entries"] as? [Any] ?? [])
        default:
            lastError = "unknown op \(op)"
        }
        snapshotIfNeeded()
        return encode(response())
    }

    func emit(surfaceID: String, action: String, data: [String: Any], redact: Bool) {
        lastAction = ["surface_id": surfaceID, "action": action, "data": data]
        logLines.append(redact ? "\(action) «redacted»" : "\(action) \(jsonText(data))")
    }

    func submitSecret(node: Node, value: String, surfaceID: String) {
        let name = node.string(for: "name") ?? ""
        lastSecret = ["name": name, "value": value]
        emit(
            surfaceID: surfaceID,
            action: "save",
            data: ["secret_submitted": true, "name": name],
            redact: true
        )
    }

    func tableRows(node: Node, surfaceID: String) -> [[String]] {
        guard let surface = processor.surfaceGroupModel.surfacesMap[surfaceID] else { return [] }
        return Self.cells(of: rows(node: node, surface: surface))
    }

    nonisolated func handle(action: ResolvedAction, from surfaceID: String) {
        MainActor.assumeIsolated {
            self.record(action: action, surfaceID: surfaceID)
        }
    }

    nonisolated func handle(error: RendererError, from _: String) {
        let message = String(describing: error)
        MainActor.assumeIsolated {
            self.lastError = message
        }
    }

    private func record(action: ResolvedAction, surfaceID: String) {
        guard case .event(let name, let context, _) = action.identity else { return }
        var data: [String: Any] = [:]
        for (key, value) in context ?? [:] {
            data[key] = Self.foundation(value)
        }
        emit(surfaceID: surfaceID, action: name, data: data, redact: false)
    }

    private func render(_ messages: [Any], reset: Bool) {
        if reset {
            unsupported = []
            logLines = []
            lastAction = nil
            lastSecret = nil
            lastError = ""
            processor = MessageProcessor(catalog: catalog, actionHandler: self)
        }
        guard JSONSerialization.isValidJSONObject(messages),
            let data = try? JSONSerialization.data(withJSONObject: messages),
            let payload = try? JSONValue.parse(data)
        else {
            lastError = "messages are not JSON"
            return
        }
        let rewritten = rewrite(payload)
        do {
            try processor.processMessages(rewritten)
        } catch {
            lastError = String(describing: error)
        }
        if let surface = processor.surfaceGroupModel.surfacesMap.values.first {
            session.surfaceID = surface.surfaceID
        }
    }

    private func act(label: String, entries: [Any]) {
        apply(entries)
        if let match = findCustom(label: label) {
            performCustom(match, entries: entries)
            return
        }
        guard let button = findButton(label: label) else {
            lastError = "no control labeled \(label)"
            return
        }
        button.action?.callAsFunction()
    }

    private func apply(_ entries: [Any]) {
        for case let entry as [String: Any] in entries {
            let role = entry["role"] as? String ?? ""
            let value = entry["value"] as? String ?? ""
            guard role != "secureField" else { continue }
            guard let target = component(matching: role) else { continue }
            let surface = target.surface
            guard let path = target.model.properties["value"]?["path"]?.stringValue else { continue }
            let current = surface.dataModel.get(path)
            if current?.arrayValue != nil {
                surface.dataModel.set(path, value: .array([.string(value)]))
            } else {
                surface.dataModel.set(path, value: .string(value))
            }
        }
    }

    private func performCustom(_ match: ComponentMatch, entries: [Any]) {
        switch match.model.type {
        case SpikeNames.secret:
            let value = secretEntry(entries)
            let name = match.model.properties["name"]?.stringValue ?? ""
            lastSecret = ["name": name, "value": value]
            emit(
                surfaceID: match.surface.surfaceID,
                action: "save",
                data: ["secret_submitted": true, "name": name],
                redact: true
            )
        case SpikeNames.approval:
            let action = labelKey(match.label)
            emit(surfaceID: match.surface.surfaceID, action: action, data: [:], redact: false)
        case SpikeNames.assist:
            emit(
                surfaceID: match.surface.surfaceID,
                action: "Open Computer panel",
                data: [:],
                redact: false
            )
        default:
            break
        }
    }

    private func labelKey(_ label: String) -> String {
        switch label {
        case "Approve": "approve"
        case "Deny": "deny"
        default: label
        }
    }

    private func secretEntry(_ entries: [Any]) -> String {
        for case let entry as [String: Any] in entries where entry["role"] as? String == "secureField" {
            return entry["value"] as? String ?? ""
        }
        return ""
    }

    private struct ComponentMatch {
        var model: ComponentModel
        var surface: SurfaceViewModel
        var label: String
    }

    private struct ButtonMatch {
        var action: ResolvedAction?
    }

    private func findCustom(label: String) -> ComponentMatch? {
        for surface in processor.surfaceGroupModel.surfacesMap.values {
            for model in surface.componentsModel.components.values {
                let labels = controlLabels(model)
                if labels.contains(label) {
                    return ComponentMatch(model: model, surface: surface, label: label)
                }
            }
        }
        return nil
    }

    private func controlLabels(_ model: ComponentModel) -> [String] {
        switch model.type {
        case SpikeNames.secret: ["Save securely"]
        case SpikeNames.approval: ["Approve", "Deny"]
        case SpikeNames.assist: ["Open Computer panel"]
        default: []
        }
    }

    private func findButton(label: String) -> ButtonMatch? {
        for surface in processor.surfaceGroupModel.surfacesMap.values {
            guard let root = surface.rootNode else { continue }
            if let node = button(label: label, in: root) {
                return ButtonMatch(action: node.action(for: "action"))
            }
        }
        return nil
    }

    private func button(label: String, in node: Node) -> Node? {
        if node.type == "Button", buttonLabel(node) == label { return node }
        for child in childNodes(node) {
            if let found = button(label: label, in: child) { return found }
        }
        return nil
    }

    private func buttonLabel(_ node: Node) -> String {
        guard let child = node.child(for: "child") else { return "" }
        return child.string(for: "text") ?? ""
    }

    private struct ComponentTarget {
        var model: ComponentModel
        var surface: SurfaceViewModel
    }

    private func component(matching role: String) -> ComponentTarget? {
        let types: [String]
        switch role {
        case "textField": types = ["TextField"]
        case "picker": types = ["ChoicePicker", "Select"]
        case "datePicker": types = ["DateTimeInput"]
        default: return nil
        }
        for surface in processor.surfaceGroupModel.surfacesMap.values {
            for model in surface.componentsModel.components.values where types.contains(model.type) {
                return ComponentTarget(model: model, surface: surface)
            }
        }
        return nil
    }

    private func rewrite(_ payload: JSONValue) -> JSONValue {
        guard case .array(let messages) = payload else { return payload }
        let rewritten: [JSONValue] = messages.map { message in
            guard case .object(var object) = message,
                case .object(var update) = object["updateComponents"],
                case .array(let components) = update["components"]
            else { return message }
            var kept: [JSONValue] = []
            for component in components {
                guard case .object(var componentObject) = component else {
                    kept.append(component)
                    continue
                }
                let name = componentObject["component"]?.stringValue ?? ""
                if let alias = SpikeNames.aliases[name] {
                    componentObject["component"] = .string(alias)
                    kept.append(.object(componentObject))
                } else if name.contains(".") {
                    if !unsupported.contains(name) { unsupported.append(name) }
                } else {
                    kept.append(component)
                }
            }
            update["components"] = .array(kept)
            object["updateComponents"] = .object(update)
            return .object(object)
        }
        return .array(rewritten)
    }

    private func response() -> [String: Any] {
        var hierarchy: [String] = []
        var controls: [[String: Any]] = []
        var model: JSONValue = .object([:])
        let surfaces = processor.surfaceGroupModel.surfacesMap.values.sorted {
            $0.surfaceID < $1.surfaceID
        }
        for surface in surfaces {
            model = surface.dataModel.data
            if let root = surface.rootNode {
                walk(root, surface: surface, hierarchy: &hierarchy, controls: &controls)
            }
        }
        for name in unsupported {
            hierarchy.append("Unsupported: \(name)")
        }
        if !lastError.isEmpty {
            hierarchy.append(lastError)
        }
        var body: [String: Any] = [
            "hierarchy": hierarchy.joined(separator: "\n"),
            "controls": controls,
            "data_model": Self.foundation(model),
            "log": logLines.joined(separator: "\n"),
        ]
        body["action"] = lastAction ?? NSNull()
        if let lastSecret {
            body["on_secret"] = lastSecret
        } else {
            body["on_secret"] = NSNull()
        }
        return body
    }

    private func walk(
        _ node: Node,
        surface: SurfaceViewModel,
        hierarchy: inout [String],
        controls: inout [[String: Any]]
    ) {
        switch node.type {
        case "TextField":
            hierarchy.append("TextField")
            append(node.string(for: "label"), to: &hierarchy)
        case "ChoicePicker", "Select":
            hierarchy.append("ChoicePicker")
            append(node.string(for: "label"), to: &hierarchy)
        case "DateTimeInput":
            hierarchy.append("DateTimeInput")
            hierarchy.append("DatePicker")
            append(node.string(for: "label"), to: &hierarchy)
        case "Text":
            append(node.string(for: "text"), to: &hierarchy)
        case "Button":
            append(buttonLabel(node), to: &hierarchy)
        case SpikeNames.secret:
            hierarchy.append("SecureField")
            append(node.string(for: "label"), to: &hierarchy)
            append(node.string(for: "help"), to: &hierarchy)
            append(node.string(for: "link"), to: &hierarchy)
            hierarchy.append("Save securely")
        case SpikeNames.approval:
            append(node.string(for: "title"), to: &hierarchy)
            hierarchy.append("Approve")
            hierarchy.append("Deny")
        case SpikeNames.assist:
            append(node.string(for: "prompt"), to: &hierarchy)
            hierarchy.append("Open Computer panel")
        case SpikeNames.table:
            hierarchy.append("Table")
            let table = rows(node: node, surface: surface)
            for row in Self.cells(of: table) {
                for cell in row where !cell.isEmpty {
                    hierarchy.append(cell)
                }
            }
            controls.append([
                "role": "table",
                "id": node.id,
                "rows": table.count,
            ])
        default:
            break
        }
        for child in childNodes(node) {
            walk(child, surface: surface, hierarchy: &hierarchy, controls: &controls)
        }
    }

    private func rows(node: Node, surface: SurfaceViewModel) -> [JSONValue] {
        if let binding = node.dataBinding(for: "rows") as DataBinding<JSONValue>?,
            let values = binding.value?.arrayValue
        {
            return values
        }
        if let path = surface.componentsModel.get(node.id)?.properties["rows"]?["path"]?.stringValue,
            let values = surface.dataModel.get(path)?.arrayValue
        {
            return values
        }
        return []
    }

    private func childNodes(_ node: Node) -> [Node] {
        let listed = node.children(for: "children")
        if !listed.isEmpty { return listed }
        if let child = node.child(for: "child") { return [child] }
        return node.allChildNodes
    }

    private func append(_ text: String?, to hierarchy: inout [String]) {
        guard let text, !text.isEmpty else { return }
        hierarchy.append(text)
    }

    private static func cells(of rows: [JSONValue]) -> [[String]] {
        rows.map { row in
            guard let object = row.objectValue else { return Self.strings(row) }
            return object.values.flatMap { Self.strings($0) }
        }
    }

    private static func strings(_ value: JSONValue) -> [String] {
        switch value {
        case .string(let text): [text]
        case .integer(let number): [String(number)]
        case .number(let number):
            if let exact = Int(exactly: number) { [String(exact)] } else { [String(number)] }
        case .array(let items): items.flatMap { strings($0) }
        case .object(let object): object.values.flatMap { strings($0) }
        case .boolean, .null: []
        }
    }

    private static func foundation(_ value: JSONValue) -> Any {
        switch value {
        case .string(let text): text
        case .integer(let number): number
        case .number(let number): number
        case .boolean(let flag): flag
        case .null: NSNull()
        case .array(let items): items.map { foundation($0) }
        case .object(let object):
            object.reduce(into: [String: Any]()) { result, pair in
                result[pair.key] = foundation(pair.value)
            }
        }
    }

    private func encode(_ body: [String: Any]) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: body),
            let text = String(data: data, encoding: .utf8)
        else { return "{}" }
        return text
    }

    private func jsonText(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value),
            let data = try? JSONSerialization.data(withJSONObject: value),
            let text = String(data: data, encoding: .utf8)
        else { return "" }
        return text
    }

    private func snapshotIfNeeded() {
        let directory = shotDirectory ?? ProcessInfo.processInfo.environment["SEVN_SPIKE_SHOTS"].map {
            URL(fileURLWithPath: $0, isDirectory: true)
        }
        guard let directory else { return }
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let surfaces = processor.surfaceGroupModel.surfacesMap.values.sorted {
            $0.surfaceID < $1.surfaceID
        }
        for surface in surfaces {
            let screen = SpikeScreen(
                models: [surface],
                catalog: catalog,
                unsupported: unsupported
            )
            .frame(width: shotSize.width, height: shotSize.height, alignment: .top)
            guard let data = png(of: screen), !data.isEmpty else {
                fputs("shot empty \(surface.surfaceID)\n", stderr)
                continue
            }
            let name = "\(platformName)-\(surface.surfaceID).png"
            let url = directory.appendingPathComponent(name)
            do {
                try data.write(to: url)
                fputs("shot \(url.path) \(data.count)\n", stderr)
            } catch {
                let fallback = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
                    .appendingPathComponent(name)
                try? data.write(to: fallback)
                fputs("shot fallback \(fallback.path) \(error)\n", stderr)
            }
        }
    }

    private var shotSize: CGSize {
        #if os(iOS)
            CGSize(width: 390, height: 844)
        #else
            CGSize(width: 900, height: 700)
        #endif
    }

    private var platformName: String {
        #if os(iOS)
            "ios"
        #else
            "macos"
        #endif
    }

    private func png<Content: View>(of view: Content) -> Data? {
        let size = shotSize
        let root = view.frame(width: size.width, height: size.height)
        #if os(macOS)
            let hosting = NSHostingView(rootView: root)
            hosting.frame = NSRect(origin: .zero, size: size)
            let window = NSWindow(
                contentRect: NSRect(origin: .zero, size: size),
                styleMask: [.borderless],
                backing: .buffered,
                defer: false
            )
            window.contentView = hosting
            window.setFrameOrigin(NSPoint(x: -10_000, y: -10_000))
            window.makeKeyAndOrderFront(nil)
            hosting.layoutSubtreeIfNeeded()
            RunLoop.current.run(until: Date().addingTimeInterval(0.15))
            guard let rep = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else { return nil }
            hosting.cacheDisplay(in: hosting.bounds, to: rep)
            window.orderOut(nil)
            return rep.representation(using: .png, properties: [:])
        #else
            let controller = UIHostingController(rootView: root)
            controller.view.backgroundColor = .white
            let window = (UIApplication.shared.delegate as? NSObject)?.value(forKey: "window") as? UIWindow
            if let window {
                window.rootViewController = controller
                controller.view.frame = window.bounds
                controller.view.setNeedsLayout()
                controller.view.layoutIfNeeded()
                RunLoop.current.run(until: Date().addingTimeInterval(0.2))
                let format = UIGraphicsImageRendererFormat()
                format.scale = 2
                let renderer = UIGraphicsImageRenderer(bounds: window.bounds, format: format)
                let image = renderer.image { _ in
                    window.drawHierarchy(in: window.bounds, afterScreenUpdates: false)
                }
                return image.pngData()
            }
            controller.view.bounds = CGRect(origin: .zero, size: size)
            controller.view.setNeedsLayout()
            controller.view.layoutIfNeeded()
            let format = UIGraphicsImageRendererFormat()
            format.scale = 2
            let renderer = UIGraphicsImageRenderer(bounds: controller.view.bounds, format: format)
            let image = renderer.image { context in
                controller.view.layer.render(in: context.cgContext)
            }
            return image.pngData()
        #endif
    }
}
