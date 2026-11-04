import AppKit
import ServiceManagement
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        EngineController.shared.start()
        // Agents can only reach the Mac while PWA Baker runs, so start at login unless the
        // user has turned that off.
        let defaults = UserDefaults.standard
        if !defaults.bool(forKey: "loginItemOffered") {
            defaults.set(true, forKey: "loginItemOffered")
            try? SMAppService.mainApp.register()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationWillTerminate(_ notification: Notification) {
        EngineController.shared.stop()
    }
}

struct PWABakerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @ObservedObject private var engine = EngineController.shared

    var body: some Scene {
        Window("PWA Baker", id: "main") {
            ContentView()
                .environmentObject(engine)
                .frame(minWidth: 640, minHeight: 520)
        }
        .defaultSize(width: 720, height: 600)

        MenuBarExtra("PWA Baker", systemImage: "macwindow.badge.plus") {
            MenuBarContent()
                .environmentObject(engine)
        }
    }
}

struct MenuBarContent: View {
    @EnvironmentObject var engine: EngineController
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Text(statusLine)
        if let running = engine.jobs.first(where: { !$0.isFinished }) {
            Text("\(running.title): \(running.progress ?? running.status)")
        }
        Divider()
        Button("Open PWA Baker") {
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
        Button("Bake the Address on the Clipboard") {
            guard let text = NSPasteboard.general.string(forType: .string)?.trimmingCharacters(in: .whitespacesAndNewlines),
                  text.hasPrefix("http://") || text.hasPrefix("https://")
            else {
                engine.lastActionError = "The clipboard does not hold a web address."
                openWindow(id: "main")
                NSApp.activate(ignoringOtherApps: true)
                return
            }
            Task { _ = await engine.bake(url: text, name: "", iconPath: nil) }
        }
        Divider()
        Button("Quit PWA Baker") { NSApp.terminate(nil) }
    }

    var statusLine: String {
        switch engine.state {
        case .running:
            if let status = engine.status, !status.ready { return "Needs setup" }
            let count = engine.apps.count
            return "Ready, \(count) app\(count == 1 ? "" : "s")"
        case .starting: return "Starting"
        case .oldDaemonInTheWay: return "The old baker is in the way"
        case .failed: return "Not running"
        }
    }
}
