import CryptoKit
import Foundation

/// Somewhere a card can be written: a raw disk (`/dev/rdiskN`) in the app, a plain file in tests.
public protocol BlockDevice: AnyObject {
    /// Writes all of `buffer` at `offset`, or throws.
    func write(_ buffer: UnsafeRawBufferPointer, at offset: Int64) throws
    /// Fills all of `buffer` from `offset`, or throws.
    func read(into buffer: UnsafeMutableRawBufferPointer, at offset: Int64) throws
    /// Everything written so far is on the card, not in a cache.
    func synchronize() throws
}

public enum WriteError: Error, Equatable, CustomStringConvertible {
    case cancelled
    case cardTooBig(card: Int64, disk: Int64)
    case tooMuchData(expected: Int64)
    case tooLittleData(got: Int64, expected: Int64)
    case downloadMismatch
    case verifyMismatch
    case cardNotAnswering
    case io(operation: String, offset: Int64, code: Int32)

    public var description: String {
        switch self {
        case .cancelled:
            return "Stopped. The card is blank now: write it again, or erase it in Disk Utility."
        case .cardTooBig(let card, let disk):
            return "Sofa Box OS needs \(ByteSize.text(card)) and the card holds \(ByteSize.text(disk))."
        case .tooMuchData:
            return "The download unpacked to more than the list says. Nothing past that was written; the card is blank."
        case .tooLittleData(let got, let expected):
            return "The download unpacked to \(ByteSize.text(got)), not \(ByteSize.text(expected)). The card is blank."
        case .downloadMismatch:
            return "The download isn't the card the list describes (its SHA-256 differs). The card is left blank so it can't start half right."
        case .verifyMismatch:
            return "Reading the card back gave different bytes from the ones written: the card may be failing or fake. It's left blank; try another card."
        case .cardNotAnswering:
            return "The card stopped answering when its last megabyte was written. Cards that claim more room than they have do this: try another card. Take this one out before writing again."
        case .io(let op, let offset, let code):
            let what = String(cString: strerror(code))
            return "The card stopped \(op) at \(ByteSize.text(offset)) (\(what)). It may have been removed, or be failing."
        }
    }
}

public struct WriteProgress: Equatable {
    public enum Phase: Equatable { case writing, finishing, verifying }
    public var phase: Phase
    public var done: Int64
    public var total: Int64
    public var fraction: Double { total > 0 ? min(1, Double(done) / Double(total)) : 0 }
}

/// Writes one card: unpacked bytes in, aligned 1 MiB writes out, then every byte read back and checked.
///
/// - Its first megabyte (the partition table and the start of the boot partition) is blanked before anything else and
///   written last, only once everything else is on the card and the download's SHA-256 matched the list. A card that
///   is stopped, pulled out or wrong is left without a partition table: it can't start a Pi half-written, and macOS
///   doesn't try to mount it.
/// - The disk's last megabyte is blanked at the start too: a card that once had a GPT keeps a backup of it there, which
///   would outlive the new card and confuse the box's first-start resize. A counterfeit card that claims more room
///   than it has may never answer that write, so it has a time limit and says so.
/// - Apart from that last megabyte, nothing is ever written past the card's own size (`extract_size`, rounded up to
///   the disk's sector), and nothing at all past the disk's.
public final class CardWriter {
    public static let blockBytes = 1 << 20
    static let alignment = 16384                         // a page on Apple silicon, four on Intel
    /// How long the write to the disk's last megabyte may take.
    public static let endTimeout: Double = 30

    private let device: BlockDevice
    private let expectedSize: Int64
    private let expectedSHA256: String
    private let diskSize: Int64
    private let sectorBytes: Int
    private let progress: (WriteProgress) -> Void
    private let isCancelled: () -> Bool
    private let endTimeout: Double

    private let buffer: UnsafeMutableRawPointer
    private var filled = 0
    private var offset: Int64 = 0                         // where `buffer` goes on the disk
    private var firstBlock: Data?
    private var received: Int64 = 0
    private var hasher = SHA256()
    private var started = false
    private var unresponsive = false

    public init(device: BlockDevice, expectedSize: Int64, expectedSHA256: String, diskSize: Int64, sectorBytes: Int,
                endTimeout: Double = CardWriter.endTimeout,
                progress: @escaping (WriteProgress) -> Void = { _ in }, isCancelled: @escaping () -> Bool = { false }) {
        self.endTimeout = endTimeout
        self.device = device
        self.expectedSize = expectedSize
        self.expectedSHA256 = expectedSHA256.lowercased()
        self.diskSize = diskSize
        self.sectorBytes = max(512, sectorBytes)
        self.progress = progress
        self.isCancelled = isCancelled
        buffer = .allocate(byteCount: CardWriter.blockBytes, alignment: CardWriter.alignment)
    }

    deinit { buffer.deallocate() }

    /// How far the card reaches on the disk: its size rounded up to a whole sector.
    var writtenLength: Int64 {
        let s = Int64(sectorBytes)
        return (expectedSize + s - 1) / s * s
    }

    /// Blanks the first megabyte (the old partition table goes, so macOS lets go of the old volumes) and the last (an
    /// old GPT's backup copy).
    public func begin() throws {
        guard expectedSize > 0, writtenLength <= diskSize else {
            throw WriteError.cardTooBig(card: expectedSize, disk: diskSize)
        }
        let n = Int(min(Int64(CardWriter.blockBytes), diskSize))
        memset(buffer, 0, n)
        try device.write(UnsafeRawBufferPointer(start: buffer, count: n), at: 0)
        try device.synchronize()
        started = true
        try blankEnd()
        progress(WriteProgress(phase: .writing, done: 0, total: expectedSize))
    }

    /// The write to the end, on its own thread with its own buffer: if the card never answers, that thread is left
    /// behind (it can't be stopped) and the write ends with `.cardNotAnswering`.
    private final class EndWrite: @unchecked Sendable {
        let device: BlockDevice
        let zeros: UnsafeMutableRawPointer
        let done = DispatchSemaphore(value: 0)
        var failure: Error?

        init(device: BlockDevice) {
            self.device = device
            zeros = .allocate(byteCount: CardWriter.blockBytes, alignment: CardWriter.alignment)
            memset(zeros, 0, CardWriter.blockBytes)
        }

        deinit { zeros.deallocate() }
    }

    private func blankEnd() throws {
        let block = Int64(CardWriter.blockBytes)
        let at = diskSize - block
        // Only where it's a megabyte of its own, on a sector boundary. (Where the card reaches into it, the card's
        // own bytes are written over it afterwards.)
        guard at >= block, at % Int64(sectorBytes) == 0 else { return }
        let end = EndWrite(device: device)
        Thread.detachNewThread {
            do {
                try end.device.write(UnsafeRawBufferPointer(start: end.zeros, count: CardWriter.blockBytes), at: at)
            } catch {
                end.failure = error
            }
            end.done.signal()
        }
        if end.done.wait(timeout: .now() + endTimeout) == .timedOut {
            unresponsive = true
            throw WriteError.cardNotAnswering
        }
        if let e = end.failure { throw e }
    }

    /// The next unpacked bytes of the card, in order.
    public func write(_ chunk: UnsafeRawBufferPointer) throws {
        precondition(started, "begin() first")
        guard received + Int64(chunk.count) <= expectedSize else { throw WriteError.tooMuchData(expected: expectedSize) }
        hasher.update(bufferPointer: chunk)
        received += Int64(chunk.count)
        var src = chunk.baseAddress!
        var left = chunk.count
        while left > 0 {
            let n = min(left, CardWriter.blockBytes - filled)
            memcpy(buffer + filled, src, n)
            filled += n
            src += n
            left -= n
            if filled == CardWriter.blockBytes { try flush(length: filled) }
        }
    }

    private func flush(length: Int) throws {
        if isCancelled() { throw WriteError.cancelled }
        precondition(offset + Int64(length) <= writtenLength && offset + Int64(length) <= diskSize)
        if offset == 0 {
            firstBlock = Data(bytes: buffer, count: length)        // written last, in finish()
        } else {
            try device.write(UnsafeRawBufferPointer(start: buffer, count: length), at: offset)
        }
        offset += Int64(length)
        filled = 0
        progress(WriteProgress(phase: .writing, done: received, total: expectedSize))
    }

    /// All bytes are in: writes the rest, checks the download against the list, then writes the first megabyte and
    /// makes sure it's all on the card.
    public func finish() throws {
        guard received == expectedSize else { throw WriteError.tooLittleData(got: received, expected: expectedSize) }
        if filled > 0 {
            // The last part, padded with zeros to a whole sector.
            let padded = Int((Int64(filled) + Int64(sectorBytes) - 1) / Int64(sectorBytes)) * sectorBytes
            memset(buffer + filled, 0, padded - filled)
            try flush(length: padded)
        }
        progress(WriteProgress(phase: .finishing, done: received, total: expectedSize))
        let got = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard got == expectedSHA256 else { throw WriteError.downloadMismatch }
        try device.synchronize()
        if let first = firstBlock {
            first.copyBytes(to: buffer.assumingMemoryBound(to: UInt8.self), count: first.count)
            try device.write(UnsafeRawBufferPointer(start: buffer, count: first.count), at: 0)
        }
        try device.synchronize()
    }

    /// Reads every byte of the card back and checks it against the list's SHA-256.
    public func verify() throws {
        var h = SHA256()
        var at: Int64 = 0
        let total = writtenLength
        while at < total {
            if isCancelled() { throw WriteError.cancelled }
            let n = Int(min(Int64(CardWriter.blockBytes), total - at))
            try device.read(into: UnsafeMutableRawBufferPointer(start: buffer, count: n), at: at)
            let useful = Int(min(Int64(n), expectedSize - at))
            if useful > 0 { h.update(bufferPointer: UnsafeRawBufferPointer(start: buffer, count: useful)) }
            at += Int64(n)
            progress(WriteProgress(phase: .verifying, done: min(at, expectedSize), total: expectedSize))
        }
        let got = h.finalize().map { String(format: "%02x", $0) }.joined()
        guard got == expectedSHA256 else { throw WriteError.verifyMismatch }
    }

    /// After a failure: blanks the first megabyte again, so a half-written or wrong card can't start. Best effort.
    public func spoil() {
        // A card that stopped answering already has a blank first megabyte, and another write would only hang too.
        guard started, !unresponsive else { return }
        let n = Int(min(Int64(CardWriter.blockBytes), diskSize))
        memset(buffer, 0, n)
        try? device.write(UnsafeRawBufferPointer(start: buffer, count: n), at: 0)
        try? device.synchronize()
    }
}

/// The whole write, from the packed download to a checked card. Used by the app (on a raw disk) and by the tests (on
/// plain files and RAM disks), so they run the same code.
public enum CardPipeline {
    public static func run(source: PackedSource, device: BlockDevice, card: Card, diskSize: Int64, sectorBytes: Int,
                           endTimeout: Double = CardWriter.endTimeout,
                           progress: @escaping (WriteProgress) -> Void = { _ in },
                           isCancelled: @escaping () -> Bool = { false }) throws {
        let writer = CardWriter(device: device, expectedSize: card.extractSize, expectedSHA256: card.extractSHA256,
                                diskSize: diskSize, sectorBytes: sectorBytes, endTimeout: endTimeout,
                                progress: progress, isCancelled: isCancelled)
        do {
            try writer.begin()
            let decoder = try XZDecoder()
            while let packed = try source.next() {
                if isCancelled() { throw WriteError.cancelled }
                try decoder.feed(packed) { try writer.write($0) }
            }
            try decoder.finish { try writer.write($0) }
            try writer.finish()
            try writer.verify()
        } catch {
            source.cancel()
            writer.spoil()
            throw error
        }
    }
}

/// A plain file standing in for a disk (tests), or any descriptor (the app's raw disk, through `ImagerMac`).
public final class FileDescriptorDevice: BlockDevice {
    public let fd: Int32
    private let extraSync: ((Int32) -> Void)?

    /// - Parameter extraSync: run after fsync, e.g. to ask the card reader to flush its own cache.
    public init(fd: Int32, extraSync: ((Int32) -> Void)? = nil) {
        self.fd = fd
        self.extraSync = extraSync
    }

    public func write(_ buffer: UnsafeRawBufferPointer, at offset: Int64) throws {
        var done = 0
        while done < buffer.count {
            let n = pwrite(fd, buffer.baseAddress! + done, buffer.count - done, off_t(offset) + off_t(done))
            if n < 0 {
                if errno == EINTR { continue }
                throw WriteError.io(operation: "writing", offset: offset + Int64(done), code: errno)
            }
            if n == 0 { throw WriteError.io(operation: "writing", offset: offset + Int64(done), code: EIO) }
            done += n
        }
    }

    public func read(into buffer: UnsafeMutableRawBufferPointer, at offset: Int64) throws {
        var done = 0
        while done < buffer.count {
            let n = pread(fd, buffer.baseAddress! + done, buffer.count - done, off_t(offset) + off_t(done))
            if n < 0 {
                if errno == EINTR { continue }
                throw WriteError.io(operation: "reading back", offset: offset + Int64(done), code: errno)
            }
            if n == 0 { throw WriteError.io(operation: "reading back", offset: offset + Int64(done), code: EIO) }
            done += n
        }
    }

    public func synchronize() throws {
        if fsync(fd) != 0 && errno != ENOTSUP && errno != EINVAL {
            throw WriteError.io(operation: "finishing", offset: 0, code: errno)
        }
        extraSync?(fd)
    }
}
