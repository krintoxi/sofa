import CryptoKit
import Foundation
@testable import ImagerKit
import XCTest

/// The test card inside the fixtures: 2,100,736 bytes (two whole megabytes and seven sectors, so the last write is a
/// padded part-block). `multiblock.img.xz` is one stream of 9 blocks, made by `xz -T0 -6 --block-size=256KiB` (the
/// box's own card is `xz -T0 -6`); `multistream.img.xz` is two streams with 12 and 8 zero bytes of padding.
enum Fixture {
    static let cardSize: Int64 = 2_100_736
    static let cardSHA256 = "6a0e28085d2736a1bd2b43b52ee40d6190a69d058ab8eed95044ef0d2c111077"

    static func url(_ name: String) -> URL {
        Bundle.module.url(forResource: "Fixtures/" + name, withExtension: nil)!
    }

    static func data(_ name: String) -> Data { try! Data(contentsOf: url(name)) }

    static func card(_ file: String = "multiblock.img.xz", size: Int64 = cardSize, sha: String = cardSHA256) -> Card {
        Card(name: "Sofa Box OS test", summary: "", url: url(file),
             downloadSize: Int64(data(file).count), extractSize: size, extractSHA256: sha,
             releaseDate: "2026-11-10", website: nil)
    }
}

func sha256(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }

/// A plain file standing in for a disk, filled with 0xEE so untouched bytes show.
final class TempDisk {
    let url: URL
    let fd: Int32
    let size: Int64

    init(size: Int64) throws {
        url = FileManager.default.temporaryDirectory.appendingPathComponent("sofa-imager-test-\(UUID().uuidString).img")
        FileManager.default.createFile(atPath: url.path, contents: Data(repeating: 0xEE, count: Int(size)))
        fd = open(url.path, O_RDWR)
        self.size = size
        if fd < 0 { throw POSIXError(.ENOENT) }
    }

    func contents() -> Data { try! Data(contentsOf: url) }

    deinit {
        close(fd)
        try? FileManager.default.removeItem(at: url)
    }
}

/// A disk that records every write, and can fail, hang or lie on cue.
final class RecordingDevice: BlockDevice {
    struct Write: Equatable {
        let offset: Int64
        let length: Int
        let allZero: Bool
    }

    let inner: BlockDevice
    private let lock = NSLock()
    private var _writes: [Write] = []
    /// A write at exactly this offset fails.
    var failWriteAt: Int64?
    /// A write at exactly this offset never returns (until `release()`), as a counterfeit card's can.
    var hangWriteAt: Int64?
    var corruptReadAt: Int64?
    var syncs = 0
    private let hung = DispatchSemaphore(value: 0)

    init(_ inner: BlockDevice) { self.inner = inner }

    var writes: [Write] {
        lock.lock(); defer { lock.unlock() }
        return _writes
    }

    /// Lets a hung write go, so its thread ends with the test.
    func release() { hung.signal() }

    func write(_ buffer: UnsafeRawBufferPointer, at offset: Int64) throws {
        if offset == failWriteAt { throw WriteError.io(operation: "writing", offset: offset, code: EIO) }
        if offset == hangWriteAt {
            hung.wait()
            return
        }
        lock.lock()
        _writes.append(Write(offset: offset, length: buffer.count, allZero: buffer.allSatisfy { $0 == 0 }))
        lock.unlock()
        try inner.write(buffer, at: offset)
    }

    func read(into buffer: UnsafeMutableRawBufferPointer, at offset: Int64) throws {
        try inner.read(into: buffer, at: offset)
        if let c = corruptReadAt, c >= offset, c < offset + Int64(buffer.count) {
            buffer[Int(c - offset)] ^= 0x01
        }
    }

    func synchronize() throws {
        syncs += 1
        try inner.synchronize()
    }
}
