import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// The other systems Sofa Box Imager writes: a short list we keep, each fetched from its project's own download site and
/// checked against that project's own list of SHA-256 sums, read fresh over HTTPS every time. Nothing here names a
/// version: each entry finds its project's newest release itself, so the list doesn't go stale between our updates.
public struct CatalogEntry: Identifiable, Equatable {
    public enum Medium: Equatable {
        case stick          // a USB stick for a PC
        case sdCard         // an SD card for a Raspberry Pi
    }

    /// How the newest release, its address and its SHA-256 are found, from the project's own sites only.
    public enum Source: Equatable {
        /// Ubuntu: the newest supported LTS in `changelogs.ubuntu.com/meta-release-lts`, then its folder's SHA256SUMS.
        case ubuntuLTS(flavour: String)
        /// A folder whose SHA256SUMS (or sha256sum.txt) names the file: Debian's `current`.
        case sums(folder: URL, sumsFile: String, pattern: String)
        /// Linux Mint: the newest numbered folder under `stable/`, then its sha256sum.txt (the address Mint's own
        /// download pages give for checking).
        case mint(root: URL, edition: String)
        /// Fedora: `fedoraproject.org/releases.json`, which carries each image's address, SHA-256 and size.
        case fedora(variant: String, arch: String)
        /// Raspberry Pi OS: Raspberry Pi's own list (the one their imager reads), by the entry's name.
        case raspberryPi(name: String, group: String?)
    }

    public let id: String
    public let name: String
    public let summary: String
    public let medium: Medium
    public let source: Source
    /// Where the project's own download page is, for the window's "from" line.
    public let home: URL
}

public enum Catalog {
    /// The list, in the order it's shown.
    public static let entries: [CatalogEntry] = [
        CatalogEntry(id: "ubuntu", name: "Ubuntu Desktop", summary: "The newest long-term support release, for a PC (x86-64).",
                     medium: .stick, source: .ubuntuLTS(flavour: "desktop"), home: URL(string: "https://ubuntu.com/download/desktop")!),
        CatalogEntry(id: "debian", name: "Debian", summary: "The stable release's installer (netinst), for a PC (x86-64).",
                     medium: .stick,
                     source: .sums(folder: URL(string: "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/")!,
                                   sumsFile: "SHA256SUMS", pattern: #"^debian-[0-9.]+-amd64-netinst\.iso$"#),
                     home: URL(string: "https://www.debian.org/distrib/")!),
        CatalogEntry(id: "fedora", name: "Fedora Workstation", summary: "The newest release, live, for a PC (x86-64).",
                     medium: .stick, source: .fedora(variant: "Workstation", arch: "x86_64"),
                     home: URL(string: "https://fedoraproject.org/workstation/download")!),
        CatalogEntry(id: "mint", name: "Linux Mint Cinnamon", summary: "The newest release, live, for a PC (x86-64).",
                     medium: .stick, source: .mint(root: URL(string: "https://mirrors.kernel.org/linuxmint/stable/")!, edition: "cinnamon"),
                     home: URL(string: "https://www.linuxmint.com/download.php")!),
        CatalogEntry(id: "raspios", name: "Raspberry Pi OS (64-bit)", summary: "With the desktop, for a Raspberry Pi 3, 4 or 5.",
                     medium: .sdCard, source: .raspberryPi(name: "Raspberry Pi OS (64-bit)", group: nil),
                     home: URL(string: "https://www.raspberrypi.com/software/operating-systems/")!),
        CatalogEntry(id: "raspios-lite", name: "Raspberry Pi OS Lite (64-bit)", summary: "No desktop, for a Raspberry Pi 3, 4 or 5.",
                     medium: .sdCard, source: .raspberryPi(name: "Raspberry Pi OS Lite (64-bit)", group: "Raspberry Pi OS (other)"),
                     home: URL(string: "https://www.raspberrypi.com/software/operating-systems/")!),
    ]

    public static let ubuntuMeta = URL(string: "https://changelogs.ubuntu.com/meta-release-lts")!
    public static let ubuntuReleases = URL(string: "https://releases.ubuntu.com/")!
    public static let fedoraReleases = URL(string: "https://fedoraproject.org/releases.json")!
    public static let raspberryPiList = URL(string: "https://downloads.raspberrypi.com/os_list_imagingutility_v4.json")!

    /// The first entry for `id`.
    public static func entry(_ id: String) -> CatalogEntry? { entries.first { $0.id == id } }
}

public enum CatalogError: Error, Equatable, CustomStringConvertible {
    case notFound(String)
    case notHTTPS(String)
    case noSize(String)

    public var description: String {
        switch self {
        case .notFound(let what): return "Couldn't find \(what) on the project's own site."
        case .notHTTPS(let url): return "The project's list points at an address that isn't https (\(url)), so it isn't used."
        case .noSize(let url): return "The download's size couldn't be found (\(url))."
        }
    }
}

/// The network, as the resolver sees it: the app passes URLSession, the tests a table of answers.
public protocol CatalogFetcher {
    func text(_ url: URL) async throws -> String
    /// The length of the file at `url` (an HTTP HEAD, following redirects).
    func length(_ url: URL) async throws -> Int64
}

/// Turns a catalog entry into a `Card` the writer knows: the file's address on the project's site, its size, and the
/// SHA-256 from the project's own list. A raw ISO is "unpacked" as it is (its size and SHA-256 are the download's).
public enum CatalogResolver {
    public static func resolve(_ e: CatalogEntry, with net: CatalogFetcher) async throws -> Card {
        switch e.source {
        case .ubuntuLTS(let flavour):
            let lts = try UbuntuMeta.newestLTS(try await net.text(Catalog.ubuntuMeta))
            let short = lts.split(separator: ".").prefix(2).joined(separator: ".")   // 26.04.1 -> 26.04
            let folder = Catalog.ubuntuReleases.appendingPathComponent(short + "/")
            let sums = SumsFile.parse(try await net.text(folder.appendingPathComponent("SHA256SUMS")))
            let pattern = "^ubuntu-" + NSRegularExpression.escapedPattern(for: short) + #"(\.[0-9]+)?-"# + flavour + #"-amd64\.iso$"#
            guard let (file, sha) = SumsFile.newest(sums, matching: pattern) else {
                throw CatalogError.notFound("Ubuntu \(short)'s \(flavour) ISO")
            }
            let url = folder.appendingPathComponent(file)
            let size = try await net.length(url)
            return card("Ubuntu Desktop " + version(from: file, fallback: lts) + " LTS", e, url: url, size: size, sha: sha)
        case .sums(let folder, let sumsFile, let pattern):
            let sums = SumsFile.parse(try await net.text(folder.appendingPathComponent(sumsFile)))
            guard let (file, sha) = SumsFile.newest(sums, matching: pattern) else { throw CatalogError.notFound(e.name) }
            let url = folder.appendingPathComponent(file)
            let size = try await net.length(url)
            return card(e.name + " " + version(from: file, fallback: ""), e, url: url, size: size, sha: sha)
        case .mint(let root, let edition):
            guard let newest = DirectoryIndex.newestVersion(try await net.text(root)) else {
                throw CatalogError.notFound("Linux Mint's newest release")
            }
            let folder = root.appendingPathComponent(newest + "/")
            let sums = SumsFile.parse(try await net.text(folder.appendingPathComponent("sha256sum.txt")))
            let file = "linuxmint-\(newest)-\(edition)-64bit.iso"
            guard let sha = sums[file] else { throw CatalogError.notFound(file) }
            let url = folder.appendingPathComponent(file)
            let size = try await net.length(url)
            return card("Linux Mint \(newest) Cinnamon", e, url: url, size: size, sha: sha)
        case .fedora(let variant, let arch):
            guard let r = FedoraReleases.newest(try await net.text(Catalog.fedoraReleases), variant: variant, arch: arch) else {
                throw CatalogError.notFound("Fedora \(variant)'s newest release")
            }
            guard r.url.scheme == "https" else { throw CatalogError.notHTTPS(r.url.absoluteString) }
            return card("Fedora \(variant) \(r.version)", e, url: r.url, size: r.size, sha: r.sha256)
        case .raspberryPi(let name, let group):
            let data = Data(try await net.text(Catalog.raspberryPiList).utf8)
            guard let c = try RaspberryPiList.find(data, name: name, group: group) else {
                throw CatalogError.notFound(name)
            }
            return Card(name: c.name + (c.releaseDate.isEmpty ? "" : " (\(c.releaseDate))"), summary: e.summary, url: c.url,
                        downloadSize: c.downloadSize, extractSize: c.extractSize, extractSHA256: c.extractSHA256,
                        releaseDate: c.releaseDate, website: e.home)
        }
    }

    static func card(_ name: String, _ e: CatalogEntry, url: URL, size: Int64, sha: String) -> Card {
        Card(name: name.trimmingCharacters(in: .whitespaces), summary: e.summary, url: url, downloadSize: size,
             extractSize: size, extractSHA256: sha.lowercased(), releaseDate: "", website: e.home)
    }

    /// "ubuntu-26.04.1-desktop-amd64.iso" -> "26.04.1"; "debian-13.7.0-amd64-netinst.iso" -> "13.7.0".
    static func version(from file: String, fallback: String) -> String {
        guard let r = file.range(of: #"[0-9]+(\.[0-9]+)+"#, options: .regularExpression) else { return fallback }
        return String(file[r])
    }
}

/// SHA256SUMS files, in the three shapes projects publish: "HASH  name", "HASH *name", "SHA256 (name) = HASH".
public enum SumsFile {
    public static func parse(_ text: String) -> [String: String] {
        var out: [String: String] = [:]
        for raw in text.split(whereSeparator: \.isNewline) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("SHA256 (") {
                guard let close = line.range(of: ") = ") else { continue }
                let name = String(line[line.index(line.startIndex, offsetBy: 8)..<close.lowerBound])
                let hash = String(line[close.upperBound...]).lowercased()
                if isHash(hash) { out[name] = hash }
                continue
            }
            let parts = line.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: true)
            guard parts.count == 2 else { continue }
            let hash = parts[0].lowercased()
            var name = parts[1].trimmingCharacters(in: .whitespaces)
            if name.hasPrefix("*") { name.removeFirst() }
            if isHash(hash), !name.isEmpty, !name.contains("/") { out[name] = hash }
        }
        return out
    }

    static func isHash(_ s: String) -> Bool { s.count == 64 && s.allSatisfy { $0.isHexDigit } }

    /// The file matching `pattern` with the highest version in its name.
    public static func newest(_ sums: [String: String], matching pattern: String) -> (String, String)? {
        let hits = sums.keys.filter { $0.wholeMatch(pattern) }
        guard let best = hits.max(by: { VersionOrder.less(numbers($0), numbers($1)) }) else { return nil }
        return (best, sums[best]!)
    }

    static func numbers(_ s: String) -> [Int] {
        guard let r = s.range(of: #"[0-9]+(\.[0-9]+)*"#, options: .regularExpression) else { return [] }
        return s[r].split(separator: ".").compactMap { Int($0) }
    }
}

enum VersionOrder {
    static func less(_ a: [Int], _ b: [Int]) -> Bool {
        for i in 0..<max(a.count, b.count) {
            let x = i < a.count ? a[i] : 0
            let y = i < b.count ? b[i] : 0
            if x != y { return x < y }
        }
        return false
    }
}

/// Ubuntu's meta-release-lts: blocks of "Dist:", "Version: 26.04.1 LTS", "Supported: 1".
public enum UbuntuMeta {
    public static func newestLTS(_ text: String) throws -> String {
        var best: [Int] = []
        var bestText = ""
        for block in text.components(separatedBy: "\n\n") {
            var version = ""
            var supported = false
            for line in block.split(whereSeparator: \.isNewline) {
                if line.hasPrefix("Version:") { version = line.dropFirst(8).trimmingCharacters(in: .whitespaces) }
                if line.hasPrefix("Supported:") { supported = line.dropFirst(10).trimmingCharacters(in: .whitespaces) == "1" }
            }
            let v = version.replacingOccurrences(of: " LTS", with: "")
            let n = v.split(separator: ".").compactMap { Int($0) }
            if supported, n.count >= 2, VersionOrder.less(best, n) {
                best = n
                bestText = v
            }
        }
        guard !bestText.isEmpty else { throw CatalogError.notFound("Ubuntu's newest LTS release") }
        return bestText
    }
}

/// A web server's folder listing: the highest numbered folder ("22.3/").
public enum DirectoryIndex {
    public static func newestVersion(_ html: String) -> String? {
        let re = try! NSRegularExpression(pattern: #"href="([0-9]+(?:\.[0-9]+)*)/""#)
        let ns = html as NSString
        let found = re.matches(in: html, range: NSRange(location: 0, length: ns.length)).map { ns.substring(with: $0.range(at: 1)) }
        return found.max { VersionOrder.less($0.split(separator: ".").compactMap { Int($0) }, $1.split(separator: ".").compactMap { Int($0) }) }
    }
}

/// Fedora's releases.json: one entry per image, with "version", "arch", "variant", "link", "sha256", "size".
public enum FedoraReleases {
    public struct Release: Equatable {
        public var version: String
        public var url: URL
        public var sha256: String
        public var size: Int64
    }

    public static func newest(_ json: String, variant: String, arch: String) -> Release? {
        guard let list = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [[String: Any]] else { return nil }
        var best: (Int, Release)?
        for e in list {
            guard e["variant"] as? String == variant, e["arch"] as? String == arch,
                  let v = e["version"] as? String, let n = Int(v),             // "45", never "45 Beta"
                  let link = e["link"] as? String, link.hasSuffix(".iso"), let url = URL(string: link),
                  let sha = (e["sha256"] as? String)?.lowercased(), SumsFile.isHash(sha) else { continue }
            let size = (e["size"] as? String).flatMap { Int64($0) } ?? (e["size"] as? NSNumber)?.int64Value ?? 0
            guard size > 0 else { continue }
            if best == nil || n > best!.0 { best = (n, Release(version: v, url: url, sha256: sha, size: size)) }
        }
        return best?.1
    }
}

/// Raspberry Pi's own list (Raspberry Pi Imager's JSON): an entry by name, at the top or in a named group.
public enum RaspberryPiList {
    public static func find(_ data: Data, name: String, group: String?) throws -> Card? {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let list = root["os_list"] as? [[String: Any]] else { throw CardListError.notJSON }
        var pool = list
        if let g = group {
            pool = (list.first { $0["name"] as? String == g }?["subitems"] as? [[String: Any]]) ?? []
        }
        guard let hit = pool.first(where: { $0["name"] as? String == name }) else { return nil }
        let one = try JSONSerialization.data(withJSONObject: ["os_list": [hit]])
        return try CardListParser.parse(one, for: .raspberryPi).newest
    }
}

/// The real network: HTTPS only, the Imager's own User-Agent, nothing cached.
public struct URLSessionFetcher: CatalogFetcher {
    public var userAgent: String

    public init(userAgent: String = "SofaBoxImager") { self.userAgent = userAgent }

    func request(_ url: URL, method: String) throws -> URLRequest {
        guard url.scheme == "https" else { throw CatalogError.notHTTPS(url.absoluteString) }
        var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        r.httpMethod = method
        r.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        r.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        return r
    }

    public func text(_ url: URL) async throws -> String {
        let (data, resp) = try await URLSession.shared.data(for: try request(url, method: "GET"))
        if let code = (resp as? HTTPURLResponse)?.statusCode, code != 200 { throw DownloadError.http(code) }
        guard data.count <= 8 << 20 else { throw CardListError.tooBig }
        return String(decoding: data, as: UTF8.self)
    }

    public func length(_ url: URL) async throws -> Int64 {
        let (_, resp) = try await URLSession.shared.data(for: try request(url, method: "HEAD"))
        guard let http = resp as? HTTPURLResponse else { throw CatalogError.noSize(url.absoluteString) }
        if http.statusCode != 200 { throw DownloadError.http(http.statusCode) }
        guard http.url?.scheme == "https" else { throw CatalogError.notHTTPS(http.url?.absoluteString ?? "") }
        guard http.expectedContentLength > 0 else { throw CatalogError.noSize(url.absoluteString) }
        return http.expectedContentLength
    }
}

extension String {
    /// True when the regular expression `pattern` matches all of the string, and only then. (Foundation's `$` also
    /// matches before a final newline on Linux but not on the Mac; asking for the whole string decides the same on both.)
    func wholeMatch(_ pattern: String) -> Bool {
        range(of: pattern, options: .regularExpression) == startIndex..<endIndex
    }
}
