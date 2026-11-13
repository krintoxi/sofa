import Foundation

/// Where Sofa Box Imager reads its list of cards: the same list Raspberry Pi Imager can open
/// (`tools/sofa-box-imager-list.py` builds it beside the newest card on every release).
public enum CardListSource {
    public static let defaultURL = URL(string:
        "https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.rpi-imager-manifest")!
    /// The list is a few kilobytes; anything much bigger isn't ours.
    public static let largestList = 1 << 20
}

/// What the Sofa Box OS is for: a Raspberry Pi (an SD card, as always) or a PC (a USB stick it starts from and runs
/// from). The list says which entries are for which by their `devices` tags; the words the window uses come from here.
public enum CardTarget: String, CaseIterable, Identifiable, Sendable {
    case raspberryPi
    case pc
    /// A PC, from a DVD it starts from: the live DVD's file (`.iso`), burned rather than written.
    case dvd

    public var id: String { rawValue }
    /// The list's device tags for it (Raspberry Pi OS Lite 64-bit's own for the Pi; ours for a PC and its DVD).
    public var tags: Set<String> {
        switch self {
        case .raspberryPi: return ["pi5-64bit", "pi4-64bit", "pi3-64bit"]
        case .pc: return ["sofa-box-pc-x86_64"]
        case .dvd: return ["sofa-box-pc-dvd"]
        }
    }
    /// "For a Raspberry Pi" / "For a PC" / "On a DVD", on the switch at the top of the window.
    public var choice: String {
        switch self {
        case .raspberryPi: return "For a Raspberry Pi"
        case .pc: return "For a PC"
        case .dvd: return "On a DVD"
        }
    }
    /// What's written: "SD card" / "USB stick" / "DVD"; and the one word for it in sentences: "card" / "stick" / "disc".
    public var medium: String {
        switch self {
        case .raspberryPi: return "SD card"
        case .pc: return "USB stick"
        case .dvd: return "DVD"
        }
    }
    public var word: String {
        switch self {
        case .raspberryPi: return "card"
        case .pc: return "stick"
        case .dvd: return "disc"
        }
    }
    /// The machine it goes in: "Pi" / "PC".
    public var machine: String { self == .raspberryPi ? "Pi" : "PC" }
    /// The SF Symbol drawn for it.
    public var symbol: String {
        switch self {
        case .raspberryPi: return "sdcard"
        case .pc: return "externaldrive"
        case .dvd: return "opticaldiscdrive"
        }
    }
    /// Burned onto a disc (the `.iso` as it is), not written to a disk.
    public var burns: Bool { self == .dvd }
    /// `--for pi` / `--for pc` / `--for dvd` on the command line.
    public static func named(_ text: String) -> CardTarget? {
        switch text.lowercased() {
        case "pi", "raspberrypi", "raspberry-pi", "sd": return .raspberryPi
        case "pc", "usb", "x86_64", "x86-64": return .pc
        case "dvd", "disc", "iso": return .dvd
        default: return nil
        }
    }
}

/// One card Sofa Box Imager can write: a Sofa Box OS version.
public struct Card: Equatable, Identifiable, Hashable {
    public let name: String
    public let summary: String
    /// The packed card (`.img.xz`).
    public let url: URL
    /// The packed card's size (`image_download_size`).
    public let downloadSize: Int64
    /// The unpacked card's size and SHA-256 (`extract_size`, `extract_sha256`): every byte written is checked against them.
    public let extractSize: Int64
    public let extractSHA256: String
    /// YYYY-MM-DD, or "" when the list doesn't say.
    public let releaseDate: String
    public let website: URL?
    /// Not tried on a real box yet: a version newer than the stable one, or the rolling card rebuilt from main
    /// ("newest build (testing)").
    public var isTesting: Bool { name.lowercased().contains("(testing)") }
    public var id: String { url.absoluteString + "#" + extractSHA256 }
}

/// The list as Sofa Box Imager shows it: the newest version first, then anything else at the top level (a testing
/// build), then the "earlier versions" group.
public struct CardList: Equatable {
    public let newest: Card?
    public let others: [Card]
    public let earlierTitle: String
    public let earlier: [Card]
    /// Entries left out, and why (shown nowhere but logged, so a bad list can be put right).
    public let skipped: [String]

    public var all: [Card] { (newest.map { [$0] } ?? []) + others + earlier }
}

public enum CardListError: Error, Equatable, CustomStringConvertible {
    case notJSON
    case noCards
    case noneFor(CardTarget)
    case tooBig

    public var description: String {
        switch self {
        case .notJSON: return "The list of cards isn't a list Sofa Box Imager can read."
        case .noCards: return "The list of cards has no Sofa Box OS card in it."
        case .noneFor(let t):
            return t == .dvd ? "The list has no Sofa Box OS DVD yet." : "The list has no Sofa Box OS for a \(t.machine) yet."
        case .tooBig: return "The list of cards is far bigger than it should be."
        }
    }
}

/// Reads the list (Raspberry Pi Imager's OS-list JSON). Strict about every field it relies on: an entry with a missing or
/// odd size or SHA-256 is left out rather than written unchecked.
public enum CardListParser {
    /// The boards a Sofa Box card is for (Raspberry Pi OS Lite 64-bit's own tags). An entry for other boards is left out.
    public static let boardTags: Set<String> = CardTarget.raspberryPi.tags

    private struct RawList: Decodable {
        let os_list: [RawEntry]
    }

    /// Every field read on its own: one odd field leaves that entry out (below), never the whole list.
    private struct RawEntry: Decodable {
        var name: String?
        var description: String?
        var url: String?
        var extract_size: Int64?
        var extract_sha256: String?
        var image_download_size: Int64?
        var release_date: String?
        var website: String?
        var devices: [String]?
        var subitems: [RawEntry]?
        var subitems_url: String?

        enum Key: String, CodingKey {
            case name, description, url, extract_size, extract_sha256, image_download_size, release_date, website,
                 devices, subitems, subitems_url
        }

        init(from decoder: Decoder) throws {
            guard let c = try? decoder.container(keyedBy: Key.self) else { return }
            name = try? c.decodeIfPresent(String.self, forKey: .name)
            description = try? c.decodeIfPresent(String.self, forKey: .description)
            url = try? c.decodeIfPresent(String.self, forKey: .url)
            extract_size = try? c.decodeIfPresent(Int64.self, forKey: .extract_size)
            extract_sha256 = try? c.decodeIfPresent(String.self, forKey: .extract_sha256)
            image_download_size = try? c.decodeIfPresent(Int64.self, forKey: .image_download_size)
            release_date = try? c.decodeIfPresent(String.self, forKey: .release_date)
            website = try? c.decodeIfPresent(String.self, forKey: .website)
            devices = try? c.decodeIfPresent([String].self, forKey: .devices)
            subitems = try? c.decodeIfPresent([RawEntry].self, forKey: .subitems)
            subitems_url = try? c.decodeIfPresent(String.self, forKey: .subitems_url)
        }
    }

    /// - Parameter allowLocalFiles: a list the owner opened from a file on this Mac (for testing) may point at
    ///   `file://` cards; a list from the network must point at `https://`.
    /// - Parameter target: the entries for a Raspberry Pi (the default: an entry that names no devices counts as one, as
    ///   lists before the PC's did), for a PC (only an entry that names a PC's tag), or its DVD (only the DVD's).
    public static func parse(_ data: Data, for target: CardTarget = .raspberryPi, allowLocalFiles: Bool = false) throws -> CardList {
        guard data.count <= CardListSource.largestList else { throw CardListError.tooBig }
        let raw: RawList
        do {
            raw = try JSONDecoder().decode(RawList.self, from: data)
        } catch {
            throw CardListError.notJSON
        }
        var skipped: [String] = []
        var top: [Card] = []
        var earlier: [Card] = []
        var earlierTitle = ""
        for entry in raw.os_list {
            if let subs = entry.subitems {
                // One level of groups, as the list builder writes ("Sofa Box OS: earlier versions").
                var found = false
                for sub in subs {
                    switch card(sub, for: target, allowLocalFiles: allowLocalFiles) {
                    case .success(let c): earlier.append(c); found = true
                    case .failure(let why): skipped.append(why.text)
                    }
                }
                if found, earlierTitle.isEmpty { earlierTitle = entry.name ?? "Earlier versions" }
            } else if entry.subitems_url != nil {
                skipped.append("\(entry.name ?? "?"): a group in another list (not followed)")
            } else {
                switch card(entry, for: target, allowLocalFiles: allowLocalFiles) {
                case .success(let c): top.append(c)
                case .failure(let why): skipped.append(why.text)
                }
            }
        }
        // The version to offer is the first entry that isn't a testing one: the stable version once one is marked,
        // the newest until then.
        let newestIndex = top.firstIndex { !$0.isTesting } ?? (top.isEmpty ? nil : 0)
        let newest = newestIndex.map { top[$0] }
        var others = top
        if let i = newestIndex { others.remove(at: i) }
        guard newest != nil || !earlier.isEmpty else {
            throw target == .raspberryPi ? CardListError.noCards : CardListError.noneFor(target)
        }
        return CardList(newest: newest, others: others,
                        earlierTitle: earlierTitle.isEmpty ? "Earlier versions" : earlierTitle,
                        earlier: earlier, skipped: skipped)
    }

    private struct Skip: Error { let text: String }

    private static func card(_ e: RawEntry, for target: CardTarget, allowLocalFiles: Bool) -> Result<Card, Skip> {
        let name = (e.name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        func skip(_ why: String) -> Result<Card, Skip> { .failure(Skip(text: "\(name.isEmpty ? "?" : name): \(why)")) }
        guard !name.isEmpty else { return skip("no name") }
        guard let s = e.url, let url = URL(string: s) else { return skip("no card address") }
        let scheme = url.scheme?.lowercased() ?? ""
        guard scheme == "https" || (allowLocalFiles && scheme == "file") else {
            return skip("the card's address isn't https")
        }
        // A card or a stick: a packed image (.img.xz). A DVD: the disc's own file (.iso), downloaded as it is.
        if target.burns {
            guard url.path.lowercased().hasSuffix(".iso") else { return skip("not a disc's .iso") }
        } else {
            guard url.path.lowercased().hasSuffix(".img.xz") else { return skip("not an .img.xz card") }
        }
        guard let extract = e.extract_size, extract > 0, extract % 512 == 0 else {
            return skip("no unpacked size, or not whole 512-byte sectors")
        }
        guard let download = e.image_download_size, download > 0,
              target.burns ? download == extract : download < extract else {
            return skip("no download size")
        }
        guard let sha = e.extract_sha256, sha.count == 64,
              sha.allSatisfy({ ("0"..."9").contains($0) || ("a"..."f").contains($0) }) else {
            return skip("no SHA-256 to check the card against")
        }
        let devices = e.devices ?? []
        switch target {
        case .raspberryPi:
            if !devices.isEmpty, target.tags.isDisjoint(with: devices) { return skip("not for a Raspberry Pi 3, 4 or 5") }
        case .pc:
            if target.tags.isDisjoint(with: devices) { return skip("not for a PC") }
        case .dvd:
            if target.tags.isDisjoint(with: devices) { return skip("not a DVD") }
        }
        let date = e.release_date ?? ""
        let day = date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil ? date : ""
        let website = e.website.flatMap { URL(string: $0) }.flatMap { $0.scheme == "https" ? $0 : nil }
        return .success(Card(name: name, summary: e.description ?? "", url: url, downloadSize: download,
                             extractSize: extract, extractSHA256: sha, releaseDate: day, website: website))
    }
}
