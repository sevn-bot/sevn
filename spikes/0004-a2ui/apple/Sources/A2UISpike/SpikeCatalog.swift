import A2UICore
import A2UISwiftUI
import BasicCatalogSwiftUI
import JSONSchema

enum SpikeNames {
    static let secret = "sevn_SecretField"
    static let approval = "sevn_ApprovalCard"
    static let assist = "sevn_AssistCard"
    static let table = "Table"

    /// Swift's payload validator rejects `.` in component names (UAX #31). Payloads keep
    /// the dotted sevn names; the processor sees these aliases.
    static let aliases = [
        "sevn.SecretField": secret,
        "sevn.ApprovalCard": approval,
        "sevn.AssistCard": assist,
    ]
}

@MainActor
enum SpikeCatalog {
    static func make(session: SpikeSession) -> Catalog<ComponentImplementation> {
        let base = BasicCatalogImplementation.makeCatalog(version: .v09)
        return Catalog(
            id: base.id,
            protocolVersion: .v09,
            components: Array(base.components.values) + sevnComponents(session: session),
            functions: Array(base.functions.values),
            themeSchema: base.themeSchema
        )
    }

    private static func sevnComponents(session: SpikeSession) -> [ComponentImplementation] {
        [
            ComponentImplementation(name: SpikeNames.secret, schema: objectSchema()) { node in
                SecretFieldView(node: node, session: session)
            },
            ComponentImplementation(name: SpikeNames.approval, schema: objectSchema()) { node in
                ApprovalCardView(node: node, session: session)
            },
            ComponentImplementation(name: SpikeNames.assist, schema: objectSchema()) { node in
                AssistCardView(node: node, session: session)
            },
            ComponentImplementation(name: SpikeNames.table, schema: tableSchema()) { node in
                SpikeTableView(node: node, session: session)
            },
        ]
    }

    private static func objectSchema() -> Schema {
        schema(
            """
            {"type":"object","additionalProperties":true}
            """
        )
    }

    private static func tableSchema() -> Schema {
        schema(
            """
            {
              "type": "object",
              "additionalProperties": true,
              "properties": {
                "rows": { "$ref": "#/$defs/DynamicValue" }
              },
              "$defs": {
                "DynamicValue": { "type": "object", "additionalProperties": true }
              }
            }
            """
        )
    }

    private static func schema(_ source: String) -> Schema {
        do {
            return try Schema(instance: source)
        } catch {
            fatalError("sevn catalog schema failed: \(error)")
        }
    }
}
