import SwiftUI

// macOS native styling helpers. No Pop Art colors.
struct CodePopTheme {
    // Use system accent where possible; only define subtle semantic helpers.
    static let ok = Color.green
    static let warning = Color.orange
    static let error = Color.red

    static func statusColor(_ status: String) -> Color {
        switch status.lowercased() {
        case "ok", "indexed", "online", "healthy":
            return ok
        case "indexing", "busy", "degraded":
            return warning
        case "error", "offline":
            return error
        default:
            return Color.secondary
        }
    }
}
