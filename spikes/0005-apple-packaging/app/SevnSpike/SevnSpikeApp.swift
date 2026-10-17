import SwiftUI

@main
enum SpikeEntrypoint {
    static func main() {
        let args = CommandLine.arguments
        if args.contains("--register") {
            exit(HostService.register())
        }
        if args.contains("--unregister") {
            exit(HostService.unregister())
        }
        SevnSpikeApp.main()
    }
}

struct SevnSpikeApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
