import Foundation

/// A DVD burner on the Mac, and the disc in it (On a DVD). Found by `BurnerList` (ImagerMac, DiscRecording); burned by
/// `BurnJob` with macOS's own `hdiutil burn`, which checks the disc against the file after burning.
public struct Burner: Equatable, Hashable, Sendable, Identifiable {
    /// IOKit's path to the drive: what `hdiutil burn -device` takes, and which drive this is.
    public var id: String
    /// "HL-DT-ST DVDRW GX40N", "Apple SuperDrive".
    public var name: String
    public var writesDVD: Bool
    public var disc: Disc?

    public struct Disc: Equatable, Hashable, Sendable {
        /// "DVD-R", "DVD+R", "DVD-RW", "CD-R"...
        public var type: String
        public var isDVD: Bool
        public var isBlank: Bool
        public var freeBytes: Int64

        public init(type: String, isDVD: Bool, isBlank: Bool, freeBytes: Int64) {
            self.type = type
            self.isDVD = isDVD
            self.isBlank = isBlank
            self.freeBytes = freeBytes
        }
    }

    public init(id: String, name: String, writesDVD: Bool, disc: Disc?) {
        self.id = id
        self.name = name
        self.writesDVD = writesDVD
        self.disc = disc
    }

    /// Why it can't burn Sofa Box OS now, in words; nil when it can. A disc that isn't blank is never offered: a DVD-RW
    /// with something on it is erased by its owner first, in Finder or Disk Utility, never by Sofa Box Imager.
    public func refusal(needs: Int64) -> String? {
        if !writesDVD { return "It doesn't burn DVDs." }
        guard let d = disc else { return "No disc in it: put a blank DVD in (DVD-R or DVD+R)." }
        if !d.isDVD { return "The disc in it is a \(d.type), not a DVD." }
        if !d.isBlank { return "The \(d.type) in it isn't blank." }
        if d.freeBytes < needs {
            return "The \(d.type) in it holds \(ByteSize.text(d.freeBytes)); Sofa Box OS needs \(ByteSize.text(needs))."
        }
        return nil
    }

    /// "Blank DVD-R in it · 4.7 GB", or why it can't be used.
    public func subtitle(needs: Int64) -> String {
        if let why = refusal(needs: needs) { return why }
        guard let d = disc else { return "" }
        return "Blank \(d.type) in it · \(ByteSize.text(d.freeBytes))"
    }
}

/// `hdiutil burn -puppetstrings`, line by line: "PERCENT:12.5" (or -1 while it can't say) and "MESSAGE:…".
public enum BurnOutput: Equatable {
    case percent(Double?)
    case message(String)
    case other(String)

    public static func parse(_ line: String) -> BurnOutput {
        let l = line.trimmingCharacters(in: .whitespacesAndNewlines)
        if l.hasPrefix("PERCENT:") {
            let v = Double(l.dropFirst("PERCENT:".count).trimmingCharacters(in: .whitespaces))
            guard let v, v >= 0 else { return .percent(nil) }
            return .percent(min(v, 100) / 100)
        }
        if l.hasPrefix("MESSAGE:") { return .message(String(l.dropFirst("MESSAGE:".count)).trimmingCharacters(in: .whitespaces)) }
        return .other(l)
    }

    /// The disc being read back and checked, by hdiutil's own words for it.
    public static func isVerifying(_ message: String) -> Bool {
        message.lowercased().contains("verif")
    }
}

public enum BurnError: Error, Equatable, CustomStringConvertible {
    case refused(String)
    case gone
    case download(String)
    case wrongDownload
    case burn(String)
    case cancelled

    public var description: String {
        switch self {
        case .refused(let why): return "Nothing was burned: \(why)"
        case .gone: return "Nothing was burned: the DVD burner isn't there any more."
        case .download(let why): return "Nothing was burned: the download didn't finish (\(why))."
        case .wrongDownload: return "Nothing was burned: the download isn't the one the list names (its SHA-256 or size is different)."
        case .burn(let why): return "The DVD wasn't burned: \(why)"
        case .cancelled: return "Stopped. A DVD stopped while it burned can't be used again."
        }
    }
}
