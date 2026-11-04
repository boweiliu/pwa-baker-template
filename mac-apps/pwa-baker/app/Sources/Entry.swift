import AppKit
import SwiftUI

/// The binary is the app, and also the icon painter the engine's installer calls:
///   PWABaker --render-icon <out.png> <name>   a letter icon for a site with none
///   PWABaker --render-app-icon <dir>          PWA Baker's own iconset (used by build.sh)
@main
@MainActor
enum Entry {
    static func main() {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--render-icon"), args.count > i + 2 {
            exit(IconRenderer.renderLetterIcon(to: args[i + 1], name: args[i + 2]) ? 0 : 1)
        }
        if let i = args.firstIndex(of: "--render-app-icon"), args.count > i + 1 {
            exit(IconRenderer.renderAppIconSet(into: args[i + 1]) ? 0 : 1)
        }
        PWABakerApp.main()
    }
}
