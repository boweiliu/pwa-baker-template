import AppKit
import ServiceManagement
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        VStack(spacing: 0) {
            StatusBanner()
            TabView {
                AppsTab().tabItem { Text("Apps") }
                ActivityTab().tabItem { Text("Activity") }
                AgentsTab().tabItem { Text("Agents") }
                SetupTab().tabItem { Text("Setup") }
            }
            .padding(12)
        }
    }
}

/// One line at the top that says whether baking works right now, and what to do if not.
struct StatusBanner: View {
    @EnvironmentObject var engine: EngineController

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol).foregroundStyle(color).font(.title2)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                if let detail = detail { Text(detail).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
            }
            Spacer()
            if engine.state == .oldDaemonInTheWay {
                Button("Turn Off the Old Baker") { engine.retireOldDaemon() }
            }
            if case .failed = engine.state {
                Button("Try Again") { engine.start() }
                Button("Open Log") { NSWorkspace.shared.open(engine.logURL) }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(color.opacity(0.08))
    }

    var problems: [Check] { engine.status?.checks.filter { $0.required && !$0.ok } ?? [] }

    var symbol: String {
        switch engine.state {
        case .running: return problems.isEmpty ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
        case .starting: return "hourglass"
        default: return "exclamationmark.octagon.fill"
        }
    }

    var color: Color {
        switch engine.state {
        case .running: return problems.isEmpty ? .green : .orange
        case .starting: return .secondary
        default: return .red
        }
    }

    var title: String {
        switch engine.state {
        case .running:
            if !problems.isEmpty { return "Needs setup before it can bake" }
            if let pending = engine.status?.pending, pending > 0 { return "Baking (\(pending) waiting)" }
            return "Ready to bake"
        case .starting: return "Starting"
        case .oldDaemonInTheWay: return "The old PWA baker is still running in the background"
        case .failed: return "Not running"
        }
    }

    var detail: String? {
        switch engine.state {
        case .running:
            if let first = problems.first { return "\(first.label): \(first.fix) (see Setup)" }
            return engine.status.map { "Agents can ask through \(($0.dropbox.path as NSString).abbreviatingWithTildeInPath)" }
        case .oldDaemonInTheWay:
            return "It uses the same connection as this app. Turning it off moves its start-up file aside; nothing else is removed."
        case .failed(let message): return message
        case .starting: return nil
        }
    }
}

// MARK: - Apps

struct AppsTab: View {
    @EnvironmentObject var engine: EngineController
    @State private var url = ""
    @State private var name = ""
    @State private var iconPath: String?
    @State private var currentJob: String?
    @State private var removing: BakedApp?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            GroupBox("Bake a new app") {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("Web address, like https://example.com", text: $url)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(bake)
                    TextField("Name (optional, the site's own name otherwise)", text: $name)
                        .textFieldStyle(.roundedBorder)
                    HStack {
                        Text(iconPath.map { "Icon: " + ($0 as NSString).lastPathComponent } ?? "Icon: the site's own")
                            .foregroundStyle(.secondary)
                        Button("Choose Picture...") { chooseIcon() }
                        if iconPath != nil { Button("Use the Site's") { iconPath = nil } }
                        Spacer()
                        Button("Bake", action: bake)
                            .keyboardShortcut(.defaultAction)
                            .disabled(url.trimmingCharacters(in: .whitespaces).isEmpty || engine.state != .running)
                    }
                    if let job = engine.job(currentJob) { JobLine(job: job) }
                    if let error = engine.lastActionError {
                        Text(error).foregroundStyle(.red).textSelection(.enabled)
                    }
                }
                .padding(6)
            }

            Text("Your web apps").font(.headline)
            if engine.apps.isEmpty {
                Text(engine.state == .running ? "None yet. Bake one above, or ask an agent to." : "")
                    .foregroundStyle(.secondary)
                Spacer()
            } else {
                List(engine.apps) { app in AppRow(app: app, onRemove: { removing = app }) }
                    .listStyle(.inset(alternatesRowBackgrounds: true))
            }
        }
        .padding(8)
        .confirmationDialog(
            "Remove \(removing?.name ?? "")?",
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } })
        ) {
            Button("Remove", role: .destructive) {
                if let app = removing { Task { await engine.uninstall(name: app.name) } }
                removing = nil
            }
        } message: {
            Text("Deletes the app, its Dock icon and its Desktop shortcut. Its sign-ins stay in Chromium.")
        }
    }

    func bake() {
        let address = url.trimmingCharacters(in: .whitespaces)
        guard !address.isEmpty else { return }
        let full = address.contains("://") ? address : "https://" + address
        Task {
            if let id = await engine.bake(url: full, name: name, iconPath: iconPath) {
                currentJob = id
                url = ""
                name = ""
                iconPath = nil
            }
        }
    }

    func chooseIcon() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg, .gif, .tiff, .icns, .ico, .bmp]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK { iconPath = panel.url?.path }
    }
}

struct AppRow: View {
    let app: BakedApp
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(nsImage: NSWorkspace.shared.icon(forFile: app.path))
                .resizable()
                .frame(width: 32, height: 32)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(app.name).font(.body.weight(.medium))
                    if app.running == true {
                        Text("open").font(.caption).foregroundStyle(.green)
                    }
                }
                Text(app.url ?? "").font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            }
            Spacer()
            Button("Open") { NSWorkspace.shared.open(URL(fileURLWithPath: app.path)) }
            Menu {
                Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: app.path)]) }
                if let url = app.url {
                    Button("Copy Address") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(url, forType: .string)
                    }
                }
                Divider()
                Button("Remove...", role: .destructive, action: onRemove)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .frame(width: 32)
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Activity

struct JobLine: View {
    let job: Job

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            switch job.status {
            case "done": Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
            case "failed": Image(systemName: "xmark.octagon.fill").foregroundStyle(.red)
            case "running": ProgressView().controlSize(.small)
            default: Image(systemName: "clock").foregroundStyle(.secondary)
            }
            Text(line).foregroundStyle(job.status == "failed" ? Color.red : Color.primary).textSelection(.enabled)
        }
    }

    var line: String {
        switch job.status {
        case "done":
            var parts = [job.message ?? "Done"]
            if let closed = job.result?.closed_apps, !closed.isEmpty {
                parts.append("closed and reopened \(closed.joined(separator: ", "))")
            }
            if let note = job.result?.icon_note { parts.append(note) }
            return parts.joined(separator: "; ")
        case "failed": return job.message ?? job.error ?? "Failed"
        default: return job.progress ?? "Waiting"
        }
    }
}

struct ActivityTab: View {
    @EnvironmentObject var engine: EngineController
    @State private var selected: Job?

    var body: some View {
        if engine.jobs.isEmpty {
            VStack {
                Spacer()
                Text("Nothing yet. Bakes you start here and requests from agents show up in this list.")
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .frame(maxWidth: .infinity)
        } else {
            List(engine.jobs) { job in
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(job.title).font(.body.weight(.medium))
                        Spacer()
                        Text(when(job)).font(.caption).foregroundStyle(.secondary)
                    }
                    Text(job.sourceLabel).font(.caption).foregroundStyle(.secondary)
                    JobLine(job: job).font(.callout)
                    DisclosureGroup("What was asked") {
                        Text(job.request?.pretty ?? "")
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if let log = job.result?.log_tail, !log.isEmpty {
                            Text("Installer output").font(.caption.weight(.medium)).padding(.top, 4)
                            Text(log)
                                .font(.system(.caption2, design: .monospaced))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .font(.caption)
                }
                .padding(.vertical, 4)
            }
            .listStyle(.inset(alternatesRowBackgrounds: true))
        }
    }

    func when(_ job: Job) -> String {
        guard let created = job.created_at else { return "" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: Date(timeIntervalSince1970: created), relativeTo: Date())
    }
}

// MARK: - Agents

struct AgentsTab: View {
    @EnvironmentObject var engine: EngineController
    @State private var copied: String?

    var body: some View {
        Form {
            Section("Shared folder (recommended)") {
                Toggle("Take requests from the shared folder", isOn: setting(\.dropbox_enabled, "dropbox_enabled"))
                LabeledContent("Folder") {
                    HStack {
                        Text(folderPath).textSelection(.enabled)
                        Button("Show in Finder") {
                            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: engine.status?.dropbox.path ?? "")])
                        }
                    }
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("To let a Studio agent bake apps on this Mac:")
                    Text("1. In a Studio chat, ask it to bake web apps on your Mac with PWA Baker.")
                    Text("2. Studio asks you to share this folder with it. Approve, with syncing on.")
                    Text("3. Its requests then show up under Activity. No link or password to paste.")
                }
                .foregroundStyle(.secondary)
                Button(copied == "instructions" ? "Copied" : "Copy Instructions for an Agent") {
                    copy(agentInstructions, as: "instructions")
                }
                if let error = engine.status?.dropbox.error {
                    Text(error).foregroundStyle(.red).textSelection(.enabled)
                }
            }

            Section("Public link (for agents that cannot use the folder)") {
                Toggle("Public link", isOn: Binding(
                    get: { engine.status?.tunnel.running ?? false },
                    set: { value in Task { await engine.setTunnel(value) } }
                ))
                .disabled(!(engine.status?.tunnel.available ?? false))
                if !(engine.status?.tunnel.available ?? true) {
                    Text("Needs cloudflared. Install it with: brew install cloudflared").foregroundStyle(.secondary).textSelection(.enabled)
                }
                if let tunnel = engine.status?.tunnel, tunnel.running {
                    LabeledContent("Link") {
                        HStack {
                            Text(tunnel.url ?? "Connecting...").textSelection(.enabled)
                            if let url = tunnel.url {
                                Button(copied == "url" ? "Copied" : "Copy") { copy(url, as: "url") }
                            }
                        }
                    }
                    LabeledContent("Password") {
                        Button(copied == "token" ? "Copied" : "Copy") { copy(engine.token ?? "", as: "token") }
                    }
                    Text("Anyone with both can bake apps on this Mac. The link changes each time you turn it on.")
                        .foregroundStyle(.secondary)
                }
                if let error = engine.status?.tunnel.error { Text(error).foregroundStyle(.red) }
            }
        }
        .formStyle(.grouped)
    }

    var folderPath: String { ((engine.status?.dropbox.path ?? "~/PWA Baker") as NSString).abbreviatingWithTildeInPath }

    var agentInstructions: String {
        """
        PWA Baker runs on my Mac and turns web addresses into Chromium web apps. To use it, ask Studio for \
        write access to \(folderPath) on my Mac, with syncing on. Then write requests/<id>.json in that \
        folder containing {"url": "https://...", "name": "optional name"} and read results/<id>.json for \
        the answer. The folder's README.md has the details.
        """
    }

    func copy(_ text: String, as label: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        copied = label
    }

    func setting(_ key: KeyPath<EngineSettings, Bool>, _ name: String) -> Binding<Bool> {
        Binding(
            get: { engine.status?.settings[keyPath: key] ?? false },
            set: { value in Task { await engine.setSetting(name, value) } }
        )
    }
}

// MARK: - Setup

struct SetupTab: View {
    @EnvironmentObject var engine: EngineController
    @State private var openAtLogin = SMAppService.mainApp.status == .enabled

    var body: some View {
        Form {
            Section("What baking needs") {
                ForEach(engine.status?.checks ?? []) { check in
                    HStack(alignment: .firstTextBaseline) {
                        Image(systemName: check.ok ? "checkmark.circle.fill" : (check.required ? "xmark.circle.fill" : "minus.circle"))
                            .foregroundStyle(check.ok ? Color.green : (check.required ? Color.red : Color.secondary))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(check.label)
                            Text(check.ok ? check.detail : check.fix)
                                .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }
                }
            }
            Section("When baking") {
                Toggle("Add new apps to the Dock", isOn: setting(\.add_to_dock, "add_to_dock"))
                Toggle("Put a shortcut on the Desktop", isOn: setting(\.desktop_alias, "desktop_alias"))
                Toggle("Close open web apps for a moment, then reopen them", isOn: setting(\.close_open_apps, "close_open_apps"))
                Text("Chromium has to be closed while an app is added. With this off, a bake fails while Chromium is open.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("PWA Baker") {
                Toggle("Open at login", isOn: Binding(
                    get: { openAtLogin },
                    set: { value in
                        if value { try? SMAppService.mainApp.register() } else { try? SMAppService.mainApp.unregister() }
                        openAtLogin = SMAppService.mainApp.status == .enabled
                    }
                ))
                Text("Agents can only reach this Mac while PWA Baker is running. Closing the window keeps it running in the menu bar.")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Text("Version \(engine.status?.version ?? "?")").foregroundStyle(.secondary)
                    Spacer()
                    Button("Open Log") { NSWorkspace.shared.open(engine.logURL) }
                }
            }
        }
        .formStyle(.grouped)
    }

    func setting(_ key: KeyPath<EngineSettings, Bool>, _ name: String) -> Binding<Bool> {
        Binding(
            get: { engine.status?.settings[keyPath: key] ?? false },
            set: { value in Task { await engine.setSetting(name, value) } }
        )
    }
}
