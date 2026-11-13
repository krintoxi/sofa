import CryptoKit
import DiscRecording
import Foundation
import ImagerKit

/// The Mac's DVD burners and the discs in them, from DiscRecording (macOS's own; the drives Finder and Disk Utility
/// burn with). Reads only.
public enum BurnerList {
    public static func snapshot() -> [Burner] {
        guard let devices = DRDevice.devices() as? [DRDevice] else { return [] }
        return devices.map { d in
            burner(info: d.info() ?? [:], status: d.status() ?? [:], path: d.ioRegistryEntryPath() ?? "")
        }
    }

    /// One drive, from DiscRecording's own dictionaries (`-[DRDevice info]`, `-[DRDevice status]`).
    public static func burner(info: [AnyHashable: Any], status: [AnyHashable: Any], path: String) -> Burner {
        let vendor = (info[DRDeviceVendorNameKey] as? String ?? "").trimmingCharacters(in: .whitespaces)
        let product = (info[DRDeviceProductNameKey] as? String ?? "").trimmingCharacters(in: .whitespaces)
        let name = [vendor, product].filter { !$0.isEmpty }.joined(separator: " ")
        let caps = info[DRDeviceWriteCapabilitiesKey] as? [AnyHashable: Any] ?? [:]
        let can: (String) -> Bool = { (caps[$0] as? NSNumber)?.boolValue ?? false }
        let writesDVD = can(DRDeviceCanWriteDVDRKey) || can(DRDeviceCanWriteDVDPlusRKey) || can(DRDeviceCanWriteDVDRWKey)
            || can(DRDeviceCanWriteDVDPlusRWKey)
        var disc: Burner.Disc?
        if status[DRDeviceMediaStateKey] as? String == DRDeviceMediaStateMediaPresent,
           let media = status[DRDeviceMediaInfoKey] as? [AnyHashable: Any] {
            let type = media[DRDeviceMediaTypeKey] as? String ?? ""
            let blocks = (media[DRDeviceMediaBlocksFreeKey] as? NSNumber)?.int64Value ?? 0
            disc = Burner.Disc(type: words(type), isDVD: media[DRDeviceMediaClassKey] as? String == DRDeviceMediaClassDVD,
                               isBlank: (media[DRDeviceMediaIsBlankKey] as? NSNumber)?.boolValue ?? false,
                               freeBytes: blocks * 2048)
        }
        return Burner(id: path, name: name.isEmpty ? "DVD burner" : name, writesDVD: writesDVD, disc: disc)
    }

    /// DiscRecording's media type, as it's printed on the disc.
    static func words(_ type: String) -> String {
        let names: [String: String] = [
            DRDeviceMediaTypeDVDR: "DVD-R", DRDeviceMediaTypeDVDPlusR: "DVD+R", DRDeviceMediaTypeDVDRW: "DVD-RW",
            DRDeviceMediaTypeDVDPlusRW: "DVD+RW", DRDeviceMediaTypeDVDRDualLayer: "DVD-R DL",
            DRDeviceMediaTypeDVDPlusRDoubleLayer: "DVD+R DL", DRDeviceMediaTypeDVDRAM: "DVD-RAM",
            DRDeviceMediaTypeDVDROM: "DVD-ROM", DRDeviceMediaTypeCDR: "CD-R", DRDeviceMediaTypeCDRW: "CD-RW",
            DRDeviceMediaTypeCDROM: "CD",
        ]
        return names[type] ?? (type.isEmpty ? "disc" : type)
    }
}

/// One DVD burned, start to finish:
///
/// 1. Look at the burner again: it must be the one chosen, with a blank DVD big enough in it.
/// 2. Download the disc's file (the list's `.iso`) to Sofa Box Imager's cache, and check its size and SHA-256 against
///    the list; one already there and right isn't downloaded again.
/// 3. Burn it with macOS's own `hdiutil burn` (that drive only, the file as it is, no partition map added), which reads
///    the disc back and checks it against the file, then ejects it.
public final class BurnJob: @unchecked Sendable {     // its state is behind `lock`
    public enum Stage: Equatable {
        case checking
        case downloading(done: Int64, total: Int64)
        case checkingDownload
        case burning(Double?)
        case verifying(Double?)
        case done
    }

    public let card: Card
    public let burner: Burner
    private let makeSource: () throws -> PackedSource
    /// The burner as it is now (DiscRecording in the app; tests give their own).
    var find: (String) -> Burner? = { id in BurnerList.snapshot().first { $0.id == id } }
    /// macOS's hdiutil (tests: a stand-in, SOFA_IMAGER_HDIUTIL).
    var hdiutil = URL(fileURLWithPath: ProcessInfo.processInfo.environment["SOFA_IMAGER_HDIUTIL"] ?? "/usr/bin/hdiutil")
    let cache: URL
    private let lock = NSLock()
    private var cancelled = false
    private var source: PackedSource?
    private var process: Process?

    public init(card: Card, burner: Burner, cache: URL = BurnJob.defaultCache, source: @escaping () throws -> PackedSource) {
        self.card = card
        self.burner = burner
        self.cache = cache
        makeSource = source
    }

    public static var defaultCache: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("SofaBoxImager")
    }

    public func cancel() {
        lock.lock()
        cancelled = true
        let s = source
        let p = process
        lock.unlock()
        s?.cancel()
        if let p, p.isRunning { p.terminate() }
    }

    private var isCancelled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancelled
    }

    /// Runs the whole job on the calling thread (not the main one). `stage` is called on that thread.
    public func run(stage: @escaping (Stage) -> Void) throws {
        stage(.checking)
        guard let now = find(burner.id) else { throw BurnError.gone }
        if let why = now.refusal(needs: card.extractSize) { throw BurnError.refused(why) }
        let awake = SleepGuard(reason: "Burning a Sofa Box OS DVD")
        defer { awake.release() }
        let file = try download(stage)
        if isCancelled { throw BurnError.cancelled }
        guard find(burner.id) != nil else { throw BurnError.gone }
        try burn(file, stage)
        stage(.done)
    }

    /// The file, in the cache: the one there when it's right, or downloaded and checked.
    func download(_ stage: (Stage) -> Void) throws -> URL {
        try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
        let name = card.url.lastPathComponent
        let file = cache.appendingPathComponent(name)
        // only the disc being burned is kept (they're 1.5 GB each)
        for old in (try? FileManager.default.contentsOfDirectory(at: cache, includingPropertiesForKeys: nil)) ?? []
        where old.lastPathComponent != name && old.pathExtension.lowercased() == "iso" {
            try? FileManager.default.removeItem(at: old)
        }
        if let size = (try? FileManager.default.attributesOfItem(atPath: file.path))?[.size] as? Int64, size == card.extractSize {
            stage(.checkingDownload)
            if try Self.sha256(of: file, cancelled: { self.isCancelled }) == card.extractSHA256.lowercased() { return file }
        }
        try? FileManager.default.removeItem(at: file)
        let partial = file.appendingPathExtension("part")
        try? FileManager.default.removeItem(at: partial)
        FileManager.default.createFile(atPath: partial.path, contents: nil)
        let out = try FileHandle(forWritingTo: partial)
        defer { try? out.close() }
        let src: PackedSource
        do { src = try makeSource() } catch { throw BurnError.download(plainWords(error)) }
        lock.lock()
        source = src
        lock.unlock()
        var hasher = SHA256()
        var got: Int64 = 0
        var last = Date.distantPast
        while true {
            if isCancelled { throw BurnError.cancelled }
            let chunk: Data?
            do { chunk = try src.next() } catch {
                if isCancelled { throw BurnError.cancelled }
                throw BurnError.download(plainWords(error))
            }
            guard let data = chunk else { break }
            try out.write(contentsOf: data)
            hasher.update(data: data)
            got += Int64(data.count)
            if got > card.extractSize { throw BurnError.wrongDownload }
            if Date().timeIntervalSince(last) > 0.1 {
                stage(.downloading(done: got, total: card.extractSize))
                last = Date()
            }
        }
        stage(.downloading(done: got, total: card.extractSize))
        stage(.checkingDownload)
        let sha = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard got == card.extractSize, sha == card.extractSHA256.lowercased() else {
            try? FileManager.default.removeItem(at: partial)
            throw BurnError.wrongDownload
        }
        try out.close()
        try FileManager.default.moveItem(at: partial, to: file)
        return file
    }

    /// `hdiutil burn` on the chosen drive, followed by its -puppetstrings lines.
    func burn(_ file: URL, _ stage: @escaping (Stage) -> Void) throws {
        let p = Process()
        p.executableURL = hdiutil
        p.arguments = Self.burnArguments(file: file, device: burner.id)
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        lock.lock()
        if cancelled { lock.unlock(); throw BurnError.cancelled }
        process = p
        lock.unlock()
        try p.run()
        var verifying = false
        var said: [String] = []
        var buffer = Data()
        let handle = pipe.fileHandleForReading
        while true {
            let data = handle.availableData
            if data.isEmpty { break }
            buffer.append(data)
            while let nl = buffer.firstIndex(of: 0x0A) {
                let line = String(decoding: buffer[buffer.startIndex..<nl], as: UTF8.self)
                buffer.removeSubrange(buffer.startIndex...nl)
                switch BurnOutput.parse(line) {
                case .percent(let f): stage(verifying ? .verifying(f) : .burning(f))
                case .message(let m):
                    said.append(m)
                    if BurnOutput.isVerifying(m) { verifying = true; stage(.verifying(nil)) }
                case .other(let o): if !o.isEmpty { said.append(o) }
                }
            }
        }
        p.waitUntilExit()
        if isCancelled { throw BurnError.cancelled }
        guard p.terminationStatus == 0 else {
            throw BurnError.burn(said.suffix(3).joined(separator: " ").isEmpty ? "hdiutil stopped (\(p.terminationStatus))."
                                 : said.suffix(3).joined(separator: " "))
        }
    }

    /// That drive only; the file burned as it is (it has its own partition map, for a USB stick); read back and checked
    /// against the file; then out of the drive.
    public static func burnArguments(file: URL, device: String) -> [String] {
        ["burn", file.path, "-device", device, "-noaddpmap", "-nooptimizeimage", "-verifyburn", "-eject", "-puppetstrings"]
    }

    static func sha256(of file: URL, cancelled: () -> Bool) throws -> String {
        let h = try FileHandle(forReadingFrom: file)
        defer { try? h.close() }
        var hasher = SHA256()
        while let data = try h.read(upToCount: 4 << 20), !data.isEmpty {
            if cancelled() { throw BurnError.cancelled }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}
