import CryptoKit
import Foundation
@testable import ImagerKit
@testable import ImagerMac
import XCTest

/// A disk the test makes itself and nothing else: a RAM disk (`hdiutil attach -nomount ram://`) or a sparse disk
/// image. Before anything touches it, it checks with DiskArbitration that the device it got really is a disk image of
/// exactly the size it asked for. Tests never write any other disk.
final class TestDisk {
    let bsd: String
    let size: Int64
    private var attached = true

    var device: String { "/dev/" + bsd }
    var raw: String { "/dev/r" + bsd }

    /// A RAM disk of `megabytes` MiB.
    convenience init(ramMegabytes megabytes: Int) throws {
        try self.init(attaching: "ram://\(megabytes * 2048)", size: Int64(megabytes) << 20)
    }

    /// A plain file of `megabytes` MiB that takes no room until it's written (a sparse file), attached as a disk.
    /// The caller removes the file.
    convenience init(sparseFile url: URL, megabytes: Int) throws {
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else { throw POSIXError(.EACCES) }
        let h = try FileHandle(forWritingTo: url)
        try h.truncate(atOffset: UInt64(megabytes) << 20)
        try h.close()
        try self.init(attaching: url.path, size: Int64(megabytes) << 20,
                      options: ["-imagekey", "diskimage-class=CRawDiskImage"])
    }

    /// - Parameter options: more arguments for `hdiutil attach` (a plain file needs to be told it's a raw image).
    init(attaching target: String, size: Int64, options: [String] = []) throws {
        // -plist on stdout (hdiutil's warnings go to stderr): the device is read from hdiutil's own answer.
        let out: String
        do {
            out = try shell("/usr/bin/hdiutil", ["attach", "-nomount", "-plist"] + options + [target], stderr: false)
        } catch {
            throw XCTSkip("hdiutil can't attach a disk image here: \(error)")
        }
        let plist = try? PropertyListSerialization.propertyList(from: Data(out.utf8), format: nil) as? [String: Any]
        let devs = ((plist?["system-entities"] as? [[String: Any]]) ?? []).compactMap { $0["dev-entry"] as? String }
        guard let dev = devs.first(where: { $0.range(of: #"^/dev/disk[0-9]+$"#, options: .regularExpression) != nil }) else {
            // Something may have attached without saying where: detach whatever it named.
            for d in devs { _ = try? shell("/usr/bin/hdiutil", ["detach", "-force", d]) }
            throw XCTSkip("hdiutil said: \(out)")
        }
        bsd = String(dev.dropFirst("/dev/".count))
        self.size = size
        guard let d = DiskList.snapshot().disk(bsd), d.model == "Disk Image", d.sizeBytes == size,
              d.ioClassChain.contains(where: { $0.contains("HDIX") }) else {
            _ = try? shell("/usr/bin/hdiutil", ["detach", "-force", dev])
            attached = false
            XCTFail("\(dev) isn't the disk image just attached; not touching it")
            throw XCTSkip("not our disk")
        }
    }

    func detach() {
        guard attached else { return }
        attached = false
        _ = try? shell("/usr/bin/hdiutil", ["detach", "-force", device])
    }

    var exists: Bool { FileManager.default.fileExists(atPath: device) }

    deinit { detach() }
}

@discardableResult
func shell(_ tool: String, _ args: [String], stderr: Bool = true) throws -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: tool)
    p.arguments = args
    let pipe = Pipe()
    let errPipe = Pipe()
    p.standardOutput = pipe
    p.standardError = stderr ? pipe : errPipe
    try p.run()
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    let err = stderr ? Data() : errPipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    let text = String(decoding: data, as: UTF8.self)
    if p.terminationStatus != 0 {
        throw NSError(domain: tool, code: Int(p.terminationStatus),
                      userInfo: [NSLocalizedDescriptionKey: text + String(decoding: err, as: UTF8.self)])
    }
    return text
}

/// Opens a disk image the test attached itself (its device nodes belong to the user, so no password is needed).
/// Test-only: the app has no opener but `AuthOpener`.
struct DirectOpener: DiskOpener {
    func open(rawPath: String) throws -> Int32 {
        let fd = Darwin.open(rawPath, O_RDWR)
        if fd < 0 { throw DiskOpError.openFailed(errno) }
        return fd
    }
}

/// The fixtures live with ImagerKit's tests.
func fixture(_ name: String) -> URL {
    URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .appendingPathComponent("../ImagerKitTests/Fixtures/\(name)").standardizedFileURL
}

enum TestCard {
    static let size: Int64 = 2_100_736
    static let sha = "6a0e28085d2736a1bd2b43b52ee40d6190a69d058ab8eed95044ef0d2c111077"

    static func card(_ file: String = "multistream.img.xz") -> Card {
        let url = fixture(file)
        let packed = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int64) ?? 0
        return Card(name: "Sofa Box OS test", summary: "", url: url, downloadSize: packed, extractSize: size,
                    extractSHA256: sha, releaseDate: "2026-11-10", website: nil)
    }
}

func sha256(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }

func sha256(of path: String, bytes: Int64) throws -> String {
    let fd = open(path, O_RDONLY)
    guard fd >= 0 else { throw POSIXError(.ENOENT) }
    defer { close(fd) }
    var h = SHA256()
    var left = bytes
    var buf = [UInt8](repeating: 0, count: 1 << 20)
    var at: off_t = 0
    while left > 0 {
        // Raw devices read whole sectors.
        let n = pread(fd, &buf, buf.count, at)
        guard n > 0 else { throw POSIXError(.EIO) }
        let use = Int(min(Int64(n), left))
        h.update(data: buf[0..<use])
        left -= Int64(use)
        at += off_t(n)
    }
    return h.finalize().map { String(format: "%02x", $0) }.joined()
}
