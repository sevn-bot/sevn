import A2UICore
import A2UISwiftUI
import OrderedJSON
import SwiftUI

@MainActor
final class SpikeSession {
    weak var engine: SpikeEngine?
    var surfaceID = ""
}

struct SecretFieldView: View {
    let node: Node
    let session: SpikeSession
    @State private var secret = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(node.string(for: "label") ?? "")
            Text(node.string(for: "help") ?? "")
                .font(.footnote)
                .foregroundStyle(.secondary)
            Text(node.string(for: "link") ?? "")
                .font(.footnote)
            SecureField("Secret", text: $secret)
            Button("Save securely") {
                session.engine?.submitSecret(node: node, value: secret, surfaceID: session.surfaceID)
            }
        }
        .padding(8)
    }
}

struct ApprovalCardView: View {
    let node: Node
    let session: SpikeSession

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(node.string(for: "title") ?? "")
            HStack {
                Button("Approve") {
                    session.engine?.emit(
                        surfaceID: session.surfaceID, action: "approve", data: [:], redact: false)
                }
                Button("Deny") {
                    session.engine?.emit(
                        surfaceID: session.surfaceID, action: "deny", data: [:], redact: false)
                }
            }
        }
        .padding(8)
    }
}

struct AssistCardView: View {
    let node: Node
    let session: SpikeSession

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(node.string(for: "prompt") ?? "")
            Button("Open Computer panel") {
                session.engine?.emit(
                    surfaceID: session.surfaceID,
                    action: "Open Computer panel",
                    data: [:],
                    redact: false
                )
            }
        }
        .padding(8)
    }
}

struct SpikeTableView: View {
    let node: Node
    let session: SpikeSession

    var body: some View {
        let rows = session.engine?.tableRows(node: node, surfaceID: session.surfaceID) ?? []
        VStack(alignment: .leading, spacing: 4) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(spacing: 12) {
                    ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                        Text(cell)
                    }
                }
            }
        }
        .padding(8)
    }
}

struct SpikeScreen: View {
    let models: [SurfaceViewModel]
    let catalog: Catalog<ComponentImplementation>
    let unsupported: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ForEach(models, id: \.surfaceID) { model in
                Surface(viewModel: model, catalog: catalog)
            }
            ForEach(unsupported, id: \.self) { name in
                Text("Unsupported: \(name)")
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.white)
    }
}
