#if canImport(XCTest)
    import Foundation
    import XCTest

    /// Skips unless `SEVN_RUN_MARKED=1`. The message is `green after <wave>`.
    func redGate(_ wave: String) throws {
        let marked = ProcessInfo.processInfo.environment["SEVN_RUN_MARKED"] == "1"
        if !marked {
            throw XCTSkip("green after \(wave)")
        }
    }
#endif
