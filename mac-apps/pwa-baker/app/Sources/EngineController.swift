import AppKit
import Foundation

/// Runs the bundled python engine as a child process and talks to it over its local API.
/// The window and the menu bar both read from the one shared instance.
@MainActor
final class EngineController: ObservableObject {
    static let shared = EngineController()

    enum State: Equatable {
        case starting
        case running
        case oldDaemonInTheWay
        case failed(String)
    }

    @Published var state: State = .starting
    @Published var status: EngineStatus?
    @Published var apps: [BakedApp] = []
    @Published var jobs: [Job] = []
    @Published var lastActionError: String?

    let port = 7247
    let oldDaemonLabel = "local.pwa-baker.daemon"
    private var process: Process?
    private var restarts: [Date] = []
    private var pollTask: Task<Void, Never>?
    private var stopping = false

    var home: URL { FileManager.default.homeDirectoryForCurrentUser }
    var configURL: URL { home.appendingPathComponent(".config/pwa-baker/config.json") }
    var logURL: URL { home.appendingPathComponent("Library/Logs/pwa-baker/engine.log") }
    var oldDaemonPlist: URL { home.appendingPathComponent("Library/LaunchAgents/\(oldDaemonLabel).plist") }
    var base: URL { URL(string: "http://127.0.0.1:\(port)")! }

    var token: String? {
        guard let data = try? Data(contentsOf: configURL),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return obj["token"] as? String
    }

    // MARK: - engine process

    func start() {
        stopping = false
        Task {
            if let info = await health() {
                if info["app"] as? String == "PWA Baker" {
                    // Our engine from an earlier run (it exits soon after its app does); wait it out.
                    try? await Task.sleep(nanoseconds: 3_000_000_000)
                    if await health() != nil {
                        state = .running
                        startPolling()
                        return
                    }
                } else {
                    state = .oldDaemonInTheWay
                    startPolling()
                    return
                }
            }
            launch()
        }
    }

    func stop() {
        stopping = true
        pollTask?.cancel()
        process?.terminate()
    }

    static func findPython() -> String? {
        let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private func launch() {
        guard let python = Self.findPython() else {
            state = .failed("No python3 found. Install the Xcode command line tools: xcode-select --install")
            return
        }
        guard let engineDir = Bundle.main.resourceURL?.appendingPathComponent("engine") else {
            state = .failed("The app is missing its engine; reinstall PWA Baker.")
            return
        }
        try? FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: python)
        proc.arguments = ["-m", "pwa_baker", "serve", "--port", String(port),
                          "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = engineDir.path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PWA_BAKER_ICON_RENDERER"] = Bundle.main.executablePath ?? ""
        proc.environment = env
        if let log = try? FileHandle(forWritingTo: logURL) {
            log.seekToEndOfFile()
            proc.standardOutput = log
            proc.standardError = log
        }
        proc.terminationHandler = { finished in
            let code = finished.terminationStatus
            Task { @MainActor in EngineController.shared.engineExited(code: code) }
        }
        do {
            try proc.run()
            process = proc
            state = .starting
            startPolling()
        } catch {
            state = .failed("Could not start the engine: \(error.localizedDescription)")
        }
    }

    private func engineExited(code: Int32) {
        process = nil
        if stopping { return }
        let now = Date()
        restarts = restarts.filter { now.timeIntervalSince($0) < 60 } + [now]
        if restarts.count > 4 {
            state = .failed("The engine keeps stopping (exit \(code)). The log has the details.")
            return
        }
        state = .starting
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            EngineController.shared.start()
        }
    }

    /// The 585 launchd daemon holds the same port; unload it and move its plist aside.
    func retireOldDaemon() {
        let uid = getuid()
        let bootout = Process()
        bootout.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        bootout.arguments = ["bootout", "gui/\(uid)/\(oldDaemonLabel)"]
        try? bootout.run()
        bootout.waitUntilExit()
        if FileManager.default.fileExists(atPath: oldDaemonPlist.path) {
            let aside = oldDaemonPlist.deletingLastPathComponent()
                .appendingPathComponent("\(oldDaemonLabel).plist.retired-by-pwa-baker-app")
            try? FileManager.default.removeItem(at: aside)
            try? FileManager.default.moveItem(at: oldDaemonPlist, to: aside)
        }
        state = .starting
        Task {
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            start()
        }
    }

    // MARK: - polling

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    func refresh() async {
        if state == .oldDaemonInTheWay {
            if await health() == nil { launch() }
            return
        }
        guard let health = await health(), health["app"] as? String == "PWA Baker" else {
            if process == nil, case .running = state { state = .starting }
            return
        }
        if let s: EngineStatus = await get("/status") {
            status = s
            if state != .running { state = .running }
        }
        if let a: AppsReply = await get("/apps") { apps = a.apps }
        if let j: JobsReply = await get("/jobs") { jobs = j.jobs }
    }

    // MARK: - API

    struct AppsReply: Codable { let apps: [BakedApp] }
    struct JobsReply: Codable { let jobs: [Job] }
    struct JobReply: Codable { let ok: Bool; let job: Job?; let error: String?; let message: String? }

    private func health() async -> [String: Any]? {
        var req = URLRequest(url: base.appendingPathComponent("health"))
        req.timeoutInterval = 2
        guard let (data, _) = try? await URLSession.shared.data(for: req) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    private func request(_ path: String, body: [String: Any]? = nil) -> URLRequest {
        var req = URLRequest(url: base.appendingPathComponent(String(path.dropFirst())))
        req.timeoutInterval = 10
        if let token = token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body = body {
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        return req
    }

    private func get<T: Decodable>(_ path: String) async -> T? {
        guard let (data, _) = try? await URLSession.shared.data(for: request(path)) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    @discardableResult
    private func post(_ path: String, _ body: [String: Any]) async -> Data? {
        do {
            let (data, _) = try await URLSession.shared.data(for: request(path, body: body))
            return data
        } catch {
            lastActionError = "PWA Baker's engine did not answer: \(error.localizedDescription)"
            return nil
        }
    }

    /// Queue a bake and return its job id (the Activity tab follows its progress).
    func bake(url: String, name: String, iconPath: String?) async -> String? {
        var body: [String: Any] = ["url": url, "wait": false]
        if !name.trimmingCharacters(in: .whitespaces).isEmpty { body["name"] = name }
        if let icon = iconPath { body["icon"] = icon }
        guard let data = await post("/bake", body),
              let reply = try? JSONDecoder().decode(JobReply.self, from: data)
        else { return nil }
        if let job = reply.job {
            lastActionError = nil
            await refresh()
            return job.id
        }
        lastActionError = reply.message ?? reply.error ?? "The bake was refused."
        return nil
    }

    func uninstall(name: String) async {
        await post("/uninstall", ["name": name, "wait": false])
        await refresh()
    }

    func setSetting(_ key: String, _ value: Bool) async {
        await post("/settings", [key: value])
        await refresh()
    }

    func setTunnel(_ enabled: Bool) async {
        await post("/tunnel", ["enabled": enabled])
        await refresh()
    }

    func job(_ id: String?) -> Job? {
        guard let id = id else { return nil }
        return jobs.first { $0.id == id }
    }
}
