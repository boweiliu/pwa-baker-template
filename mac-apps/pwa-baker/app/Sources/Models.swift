import Foundation

/// What the engine's /status, /apps and /jobs routes return (engine/pwa_baker/server.py).

struct Check: Codable, Identifiable {
    let id: String
    let label: String
    let ok: Bool
    let detail: String
    let fix: String
    let required: Bool
}

struct EngineSettings: Codable {
    var port: Int
    var dropbox_dir: String
    var dropbox_enabled: Bool
    var add_to_dock: Bool
    var desktop_alias: Bool
    var close_open_apps: Bool
}

struct DropboxInfo: Codable {
    let path: String
    let exists: Bool
    let error: String?
}

struct TunnelInfo: Codable {
    let available: Bool
    let running: Bool
    let url: String?
    let error: String?
}

struct EngineStatus: Codable {
    let version: String
    let ready: Bool
    let checks: [Check]
    let settings: EngineSettings
    let dropbox: DropboxInfo
    let tunnel: TunnelInfo
    let pending: Int
    let apps_dir: String
}

struct BakedApp: Codable, Identifiable {
    var id: String { path }
    let name: String
    let path: String
    let app_id: String?
    let url: String?
    let modified: Double?
    let running: Bool?
}

struct JobResult: Codable {
    let app_path: String?
    let name: String?
    let icon_note: String?
    let icon_source: String?
    let closed_apps: [String]?
    let reopened_apps: [String]?
    let removed: [String]?
    let seconds: Double?
    let log_tail: String?
}

struct Job: Codable, Identifiable {
    let id: String
    let source: String
    let action: String
    let params: [String: JSONValue]?
    let request: JSONValue?
    let status: String
    let progress: String?
    let message: String?
    let error: String?
    let created_at: Double?
    let finished_at: Double?
    let result: JobResult?

    var isFinished: Bool { status == "done" || status == "failed" }

    var title: String {
        let name = params?["name"]?.stringValue ?? result?.name
        if action == "uninstall" { return "Remove \(name ?? "an app")" }
        if let name = name { return "Bake \(name)" }
        if let url = params?["url"]?.stringValue, let host = URL(string: url)?.host { return "Bake \(host)" }
        return "Bake"
    }

    var sourceLabel: String {
        switch source {
        case "folder": return "Agent, through the shared folder"
        case "network": return "Agent, through the public link"
        default: return "You"
        }
    }
}

/// Any JSON value, so the raw request an agent sent can be shown exactly as it was written.
enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    var stringValue: String? {
        if case .string(let v) = self { return v }
        return nil
    }

    var pretty: String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        guard let data = try? encoder.encode(self) else { return "" }
        return String(decoding: data, as: UTF8.self)
    }
}
