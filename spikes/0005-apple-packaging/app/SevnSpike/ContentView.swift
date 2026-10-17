import SwiftUI

struct ContentView: View {
    @State private var statusText = "Status: —"

    var body: some View {
        VStack(spacing: 16) {
            Text("SevnSpike")
                .font(.title)
            Text(statusText)
            HStack(spacing: 12) {
                Button("Start") { start() }
                Button("Stop") { stop() }
                Button("Status") { refresh() }
            }
        }
        .padding(24)
        .frame(minWidth: 320, minHeight: 160)
        .task { refresh() }
    }

    private func start() {
        let code = HostService.register()
        statusText = code == 0 ? "Start requested" : "Start failed"
        refresh()
    }

    private func stop() {
        let code = HostService.unregister()
        statusText = code == 0 ? "Stop requested" : "Stop failed"
        refresh()
    }

    private func refresh() {
        Task {
            let code = await HostService.healthStatus()
            statusText = code == 200 ? "Status: ok" : "Status: down"
        }
    }
}
