#if canImport(XCTest)
    import A2UISpike
    import Foundation
    import XCTest

/// W3 exposes `@objc(SevnA2UISpikeHost)` (an `NSObject` subclass) with
/// `@objc(evalJSON:) func evalJSON(_ json: String) -> String`.
/// Each call takes `{"op","messages"|"label"|"entries"}` and returns
/// `hierarchy`, `controls`, `data_model`, `log`, `action`, and `on_secret`.
/// `hierarchy` names the SwiftUI controls it walked (`TextField`, `SecureField`, …).
final class RenderTests: XCTestCase {
    private let formText = "ada@example.com"
    private let formDate = "2026-10-17"

    func testFormRendersAndSubmits() throws {
        guard let host = loadHost() else { return }
        let payload = try loadPayload("p1-form")
        let messages = messageList(payload, includeUpdate: false)
        let choice = try choiceValue(messages)
        let rendered = eval(host, ["op": "render", "messages": messages])
        let hierarchy = stringField(rendered, "hierarchy")
        XCTAssertTrue(hierarchy.contains("TextField"), hierarchy)
        XCTAssertTrue(
            hierarchy.contains("ChoicePicker") || hierarchy.contains("Picker")
                || hierarchy.contains("Select"),
            hierarchy
        )
        XCTAssertTrue(
            hierarchy.contains("DatePicker") || hierarchy.contains("DateTimeInput"),
            hierarchy
        )
        XCTAssertTrue(hierarchy.contains("Submit"), hierarchy)
        let acted = eval(
            host,
            [
                "op": "act",
                "label": "Submit",
                "entries": [
                    ["role": "textField", "value": formText],
                    ["role": "picker", "value": choice],
                    ["role": "datePicker", "value": formDate],
                ],
            ]
        )
        guard let action = assertAction(acted["action"], surface: surfaceId(messages)) else {
            return
        }
        let data = jsonText(action["data"])
        XCTAssertTrue(data.contains(formText), data)
        XCTAssertTrue(data.contains(formDate), data)
        XCTAssertTrue(data.contains(choice), data)
    }

    func testSecretFieldUsesSecureFieldAndKeepsValueOutOfDataModel() throws {
        guard let host = loadHost() else { return }
        let payload = try loadPayload("p3-secret")
        let messages = messageList(payload, includeUpdate: true)
        let field = try secretProps(messages)
        let canary = "canary-\(UUID().uuidString)"
        XCTAssertFalse(jsonText(payload).contains(canary))
        let rendered = eval(host, ["op": "render", "messages": messages])
        let hierarchy = stringField(rendered, "hierarchy")
        XCTAssertTrue(hierarchy.contains("SecureField"), hierarchy)
        XCTAssertTrue(hierarchy.contains(field.label), hierarchy)
        XCTAssertTrue(hierarchy.contains(field.help), hierarchy)
        XCTAssertTrue(hierarchy.contains(field.link), hierarchy)
        let acted = eval(
            host,
            [
                "op": "act",
                "label": "Save securely",
                "entries": [["role": "secureField", "value": canary]],
            ]
        )
        guard let action = assertAction(acted["action"], surface: surfaceId(messages)) else {
            return
        }
        let data = action["data"] as? [String: Any] ?? [:]
        XCTAssertEqual(data["secret_submitted"] as? Bool, true)
        XCTAssertEqual(data["name"] as? String, field.name)
        XCTAssertEqual(Set(data.keys), Set(["secret_submitted", "name"]))
        let secret = acted["on_secret"] as? [String: Any]
        XCTAssertEqual(secret?["name"] as? String, field.name)
        XCTAssertEqual(secret?["value"] as? String, canary)
        let log = stringField(acted, "log")
        XCTAssertTrue(log.contains("«redacted»"), log)
        XCTAssertFalse(stringField(acted, "hierarchy").contains(canary))
        XCTAssertFalse(jsonText(acted["data_model"]).contains(canary))
        XCTAssertFalse(jsonText(acted["action"]).contains(canary))
        XCTAssertFalse(log.contains(canary))
    }

    func testIncrementalUpdateAppliesRow() throws {
        guard let host = loadHost() else { return }
        let payload = try loadPayload("p2-table-update")
        let initial = messageList(payload, includeUpdate: false)
        let update = payload["update"] as? [Any] ?? []
        XCTAssertFalse(update.isEmpty, "p2 update must be a non-empty message list")
        let beforeModel = dataModel(initial)
        let afterModel = dataModel(initial + update)
        XCTAssertFalse(grownLists(beforeModel, afterModel).isEmpty)
        let changes = changedLeaves(beforeModel, afterModel)
        XCTAssertFalse(changes.isEmpty, "p2 update must change an existing value")
        let rendered = eval(host, ["op": "render", "messages": initial])
        let beforeTable = tableControl(rendered)
        XCTAssertNotNil(beforeTable?.id)
        XCTAssertGreaterThan(beforeTable?.rows ?? 0, 0)
        XCTAssertTrue(stringField(rendered, "hierarchy").contains("Table"))
        let updated = eval(host, ["op": "update", "messages": update])
        let afterTable = tableControl(updated)
        XCTAssertEqual(afterTable?.id, beforeTable?.id)
        XCTAssertGreaterThan(afterTable?.rows ?? 0, beforeTable?.rows ?? 0)
        let hierarchy = stringField(updated, "hierarchy")
        let remaining = Set(leaves(afterModel).values)
        for change in changes {
            XCTAssertTrue(hierarchy.contains(change.next), hierarchy)
            if !remaining.contains(change.previous) {
                XCTAssertFalse(hierarchy.contains(change.previous), hierarchy)
            }
        }
    }

    func testUnknownComponentFallback() throws {
        guard let host = loadHost() else { return }
        let messages: [Any] = [
            [
                "version": "v0.9",
                "createSurface": [
                    "surfaceId": "unknown-surface",
                    "catalogId": "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json",
                ],
            ],
            [
                "version": "v0.9",
                "updateComponents": [
                    "surfaceId": "unknown-surface",
                    "components": [
                        ["id": "root", "component": "Column", "children": ["ok", "bad"]],
                        ["id": "ok", "component": "Text", "text": "Still here"],
                        ["id": "bad", "component": "sevn.NotRegistered", "text": "nope"],
                    ],
                ],
            ],
        ]
        let rendered = eval(host, ["op": "render", "messages": messages])
        let hierarchy = stringField(rendered, "hierarchy")
        XCTAssertTrue(hierarchy.contains("Unsupported: sevn.NotRegistered"), hierarchy)
        XCTAssertTrue(hierarchy.contains("Still here"), hierarchy)
    }

    func testApprovalEmitsDistinctActions() throws {
        guard let host = loadHost() else { return }
        let payload = try loadPayload("p4-approval")
        let messages = messageList(payload, includeUpdate: true)
        _ = eval(host, ["op": "render", "messages": messages])
        let approve = eval(host, ["op": "act", "label": "Approve", "entries": []])
        let deny = eval(host, ["op": "act", "label": "Deny", "entries": []])
        guard
            let approveAction = assertAction(approve["action"], surface: surfaceId(messages)),
            let denyAction = assertAction(deny["action"], surface: surfaceId(messages))
        else { return }
        XCTAssertEqual(approveAction["action"] as? String, "approve")
        XCTAssertEqual(denyAction["action"] as? String, "deny")
    }

    func testAssistEmitsOpenComputerPanel() throws {
        guard let host = loadHost() else { return }
        let payload = try loadPayload("p5-assist")
        let messages = messageList(payload, includeUpdate: true)
        let rendered = eval(host, ["op": "render", "messages": messages])
        XCTAssertTrue(stringField(rendered, "hierarchy").contains("Open Computer panel"))
        let acted = eval(host, ["op": "act", "label": "Open Computer panel", "entries": []])
        guard let action = assertAction(acted["action"], surface: surfaceId(messages)) else {
            return
        }
        XCTAssertEqual(action["action"] as? String, "Open Computer panel")
    }
}

private struct TableSnapshot {
    var id: String
    var rows: Int
}

private struct LeafChange {
    var previous: String
    var next: String
}

private struct SecretProps {
    var name: String
    var label: String
    var help: String
    var link: String
}

private func loadHost() -> NSObject? {
    _ = A2UISpike.self
    let names = ["SevnA2UISpikeHost", "A2UISpike.SevnA2UISpikeHost"]
    for name in names {
        guard let cls = NSClassFromString(name) as? NSObject.Type else { continue }
        let host = cls.init()
        if host.responds(to: NSSelectorFromString("evalJSON:")) {
            return host
        }
    }
    XCTFail(
        "SevnA2UISpikeHost is not loaded; W3 must add @objc(SevnA2UISpikeHost) with evalJSON:"
    )
    return nil
}

private func eval(_ host: NSObject, _ command: [String: Any]) -> [String: Any] {
    guard JSONSerialization.isValidJSONObject(command) else {
        XCTFail("command is not JSON")
        return [:]
    }
    guard
        let data = try? JSONSerialization.data(withJSONObject: command),
        let json = String(data: data, encoding: .utf8)
    else {
        XCTFail("could not encode command")
        return [:]
    }
    let selector = NSSelectorFromString("evalJSON:")
    guard host.responds(to: selector), let result = host.perform(selector, with: json) else {
        XCTFail("evalJSON: returned nothing")
        return [:]
    }
    let value = result.takeUnretainedValue()
    let text = value as? String ?? String(describing: value)
    guard
        let body = text.data(using: .utf8),
        let parsed = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
    else {
        XCTFail("evalJSON: returned \(text)")
        return [:]
    }
    return parsed
}

private func spikeRoot() -> URL {
    URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
}

private func loadPayload(_ name: String) throws -> [String: Any] {
    let url = spikeRoot().appendingPathComponent("payloads/\(name).json")
    let data = try Data(contentsOf: url)
    let parsed = try JSONSerialization.jsonObject(with: data)
    guard let object = parsed as? [String: Any] else {
        XCTFail("\(name) must be a JSON object")
        return [:]
    }
    return object
}

private func messageList(_ payload: [String: Any], includeUpdate: Bool) -> [Any] {
    var messages = payload["messages"] as? [Any] ?? []
    if includeUpdate, let update = payload["update"] as? [Any] {
        messages.append(contentsOf: update)
    }
    return messages
}

private func surfaceId(_ messages: [Any]) -> String {
    for case let message as [String: Any] in messages {
        guard let create = message["createSurface"] as? [String: Any] else { continue }
        if let id = create["surfaceId"] as? String, !id.isEmpty {
            return id
        }
    }
    return ""
}

private func components(_ messages: [Any]) -> [[String: Any]] {
    var found: [[String: Any]] = []
    for case let message as [String: Any] in messages {
        guard
            let update = message["updateComponents"] as? [String: Any],
            let comps = update["components"] as? [Any]
        else { continue }
        found.append(contentsOf: comps.compactMap { $0 as? [String: Any] })
    }
    return found
}

private func choiceValue(_ messages: [Any]) throws -> String {
    for component in components(messages) {
        let kind = component["component"] as? String
        guard kind == "ChoicePicker" || kind == "Select" else { continue }
        guard
            let options = component["options"] as? [Any],
            let first = options.first as? [String: Any],
            let value = first["value"] as? String,
            !value.isEmpty
        else { continue }
        return value
    }
    XCTFail("p1 choice must include a string option value")
    throw CocoaError(.fileReadCorruptFile)
}

private func secretProps(_ messages: [Any]) throws -> SecretProps {
    for component in components(messages) where component["component"] as? String == "sevn.SecretField" {
        if let name = component["name"] as? String, !name.isEmpty,
            let label = component["label"] as? String, !label.isEmpty,
            let help = component["help"] as? String, !help.isEmpty,
            let link = component["link"] as? String, !link.isEmpty
        {
            return SecretProps(name: name, label: label, help: help, link: link)
        }
    }
    XCTFail("sevn.SecretField needs string name, label, help, and link")
    throw CocoaError(.fileReadCorruptFile)
}

private func assertAction(_ value: Any?, surface: String) -> [String: Any]? {
    guard let action = value as? [String: Any] else {
        XCTFail("action must be an object, got \(jsonText(value))")
        return nil
    }
    XCTAssertEqual(Set(action.keys), Set(["surface_id", "action", "data"]))
    XCTAssertEqual(action["surface_id"] as? String, surface)
    XCTAssertFalse((action["action"] as? String ?? "").isEmpty)
    XCTAssertNotNil(action["data"] as? [String: Any])
    return action
}

private func stringField(_ object: [String: Any], _ key: String) -> String {
    object[key] as? String ?? ""
}

private func jsonText(_ value: Any?) -> String {
    guard let value, JSONSerialization.isValidJSONObject(value) || value is String else {
        return String(describing: value)
    }
    if let text = value as? String {
        return text
    }
    guard
        let data = try? JSONSerialization.data(withJSONObject: value),
        let text = String(data: data, encoding: .utf8)
    else {
        return String(describing: value)
    }
    return text
}

private func tableControl(_ response: [String: Any]) -> TableSnapshot? {
    guard let controls = response["controls"] as? [[String: Any]] else { return nil }
    for control in controls where control["role"] as? String == "table" {
        guard let id = fieldString(control["id"]), let rows = fieldInt(control["rows"]) else {
            continue
        }
        return TableSnapshot(id: id, rows: rows)
    }
    return nil
}

private func fieldString(_ value: Any?) -> String? {
    if let text = value as? String, !text.isEmpty { return text }
    if let number = value as? NSNumber { return number.stringValue }
    return nil
}

private func fieldInt(_ value: Any?) -> Int? {
    if let number = value as? NSNumber, jsonBool(number) == nil { return number.intValue }
    if let text = value as? String { return Int(text) }
    return nil
}

private func jsonBool(_ value: Any) -> Bool? {
    guard CFGetTypeID(value as CFTypeRef) == CFBooleanGetTypeID() else { return nil }
    return (value as? Bool) ?? (value as? NSNumber)?.boolValue
}

private func dataModel(_ messages: [Any]) -> Any {
    var model: Any = [String: Any]()
    for case let message as [String: Any] in messages {
        guard let update = message["updateDataModel"] as? [String: Any] else { continue }
        let path = update["path"] as? String ?? "/"
        model = setPointer(model, path, update["value"] ?? NSNull())
    }
    return model
}

private func setPointer(_ root: Any, _ pointer: String, _ value: Any) -> Any {
    if pointer.isEmpty || pointer == "/" {
        return value
    }
    var parts = pointer.split(separator: "/").map {
        String($0).replacingOccurrences(of: "~1", with: "/").replacingOccurrences(of: "~0", with: "~")
    }
    let last = parts.removeLast()
    var cursor: [String: Any] = root as? [String: Any] ?? [:]
    return write(&cursor, parts, last, value)
}

private func write(
    _ node: inout [String: Any], _ parts: [String], _ last: String, _ value: Any
) -> [String: Any] {
    if parts.isEmpty {
        node[last] = value
        return node
    }
    let head = parts[0]
    var child = node[head] as? [String: Any] ?? [:]
    node[head] = write(&child, Array(parts.dropFirst()), last, value)
    return node
}

private func listLengths(_ node: Any, _ path: String = "") -> [String: Int] {
    if let object = node as? [String: Any] {
        var found: [String: Int] = [:]
        for (key, value) in object {
            found.merge(listLengths(value, "\(path)/\(key)"), uniquingKeysWith: { _, next in next })
        }
        return found
    }
    if let list = node as? [Any] {
        var found = [path.isEmpty ? "/" : path: list.count]
        for (index, value) in list.enumerated() {
            found.merge(listLengths(value, "\(path)/\(index)"), uniquingKeysWith: { _, next in next })
        }
        return found
    }
    return [:]
}

private func grownLists(_ before: Any, _ after: Any) -> [String] {
    let previous = listLengths(before)
    return listLengths(after).compactMap { path, length in
        let prior = previous[path] ?? 0
        return prior >= 1 && length >= prior + 1 ? path : nil
    }
}

private func leaves(_ node: Any, _ path: String = "") -> [String: String] {
    if let object = node as? [String: Any] {
        var found: [String: String] = [:]
        for (key, value) in object {
            found.merge(leaves(value, "\(path)/\(key)"), uniquingKeysWith: { _, next in next })
        }
        return found
    }
    if let list = node as? [Any] {
        var found: [String: String] = [:]
        for (index, value) in list.enumerated() {
            found.merge(leaves(value, "\(path)/\(index)"), uniquingKeysWith: { _, next in next })
        }
        return found
    }
    if let text = leafString(node) {
        return [path: text]
    }
    return [:]
}

private func changedLeaves(_ before: Any, _ after: Any) -> [LeafChange] {
    let nextLeaves = leaves(after)
    return leaves(before).compactMap { path, previous in
        guard let next = nextLeaves[path], next != previous else { return nil }
        return LeafChange(previous: previous, next: next)
    }
}

private func leafString(_ value: Any) -> String? {
    if value is NSNull { return nil }
    if let text = value as? String { return text }
    if let number = value as? NSNumber {
        if jsonBool(number) != nil { return nil }
        return number.stringValue
    }
    return nil
}
#endif
