import Foundation

/// Bytes that can be read anywhere: an image file on this Mac, a file inside an ISO, a part of either. Everything that
/// reads an ISO, a WIM or a FAT image reads through this, so the tests can hand them plain `Data`.
public protocol RandomAccess: AnyObject {
    var size: Int64 { get }
    /// Exactly `count` bytes from `offset`, or throws (reading past the end throws).
    func read(at offset: Int64, count: Int) throws -> Data
}

public enum ReadError: Error, Equatable, CustomStringConvertible {
    case pastTheEnd(offset: Int64, count: Int, size: Int64)
    case io(offset: Int64, code: Int32)
    case cantOpen(String)

    public var description: String {
        switch self {
        case .pastTheEnd(let o, let c, let s):
            return "The file ends early: \(c) bytes at \(o) were asked for, and it holds \(s)."
        case .io(let o, let code): return "The file couldn't be read at \(ByteSize.text(o)) (\(String(cString: strerror(code))))."
        case .cantOpen(let path): return "The file couldn't be opened: \(path)"
        }
    }
}

extension RandomAccess {
    public func u8(_ at: Int64) throws -> UInt8 { try read(at: at, count: 1)[0] }
    public func le16(_ at: Int64) throws -> UInt16 { try read(at: at, count: 2).le16(0) }
    public func le32(_ at: Int64) throws -> UInt32 { try read(at: at, count: 4).le32(0) }
    public func le64(_ at: Int64) throws -> UInt64 { try read(at: at, count: 8).le64(0) }
}

/// A file read with `pread`: nothing is cached, nothing is mapped.
public final class FileRandomAccess: RandomAccess {
    public let url: URL
    public let size: Int64
    private let fd: Int32

    public init(url: URL) throws {
        self.url = url
        fd = open(url.path, O_RDONLY)
        guard fd >= 0 else { throw ReadError.cantOpen(url.path) }
        var st = stat()
        guard fstat(fd, &st) == 0 else {
            close(fd)
            throw ReadError.cantOpen(url.path)
        }
        size = Int64(st.st_size)
    }

    deinit { close(fd) }

    public func read(at offset: Int64, count: Int) throws -> Data {
        guard offset >= 0, count >= 0, offset + Int64(count) <= size else {
            throw ReadError.pastTheEnd(offset: offset, count: count, size: size)
        }
        var out = Data(count: count)
        try out.withUnsafeMutableBytes { (buf: UnsafeMutableRawBufferPointer) in
            var done = 0
            while done < count {
                let n = pread(fd, buf.baseAddress! + done, count - done, off_t(offset) + off_t(done))
                if n < 0 {
                    if errno == EINTR { continue }
                    throw ReadError.io(offset: offset + Int64(done), code: errno)
                }
                if n == 0 { throw ReadError.pastTheEnd(offset: offset, count: count, size: size) }
                done += n
            }
        }
        return out
    }
}

/// Bytes already in memory (tests, and small files built by the Imager itself).
public final class DataRandomAccess: RandomAccess {
    public let data: Data
    public var size: Int64 { Int64(data.count) }

    public init(_ data: Data) { self.data = data }

    public func read(at offset: Int64, count: Int) throws -> Data {
        guard offset >= 0, count >= 0, offset + Int64(count) <= size else {
            throw ReadError.pastTheEnd(offset: offset, count: count, size: size)
        }
        let start = data.startIndex + Int(offset)
        return data.subdata(in: start..<start + count)
    }
}

/// A file made of runs of another (a file in an ISO is a list of extents): offsets here are the file's own.
public final class ExtentRandomAccess: RandomAccess {
    public struct Extent: Equatable {
        /// Where the run starts in `base`; nil for a run that's all zeros (UDF's "allocated, not recorded").
        public var offset: Int64?
        public var length: Int64
        public init(offset: Int64?, length: Int64) {
            self.offset = offset
            self.length = length
        }
    }

    public let base: RandomAccess
    public let extents: [Extent]
    public let size: Int64
    private let starts: [Int64]

    public init(base: RandomAccess, extents: [Extent], size: Int64? = nil) {
        self.base = base
        self.extents = extents
        var s: [Int64] = []
        var at: Int64 = 0
        for e in extents {
            s.append(at)
            at += e.length
        }
        starts = s
        self.size = min(size ?? at, at)
    }

    public func read(at offset: Int64, count: Int) throws -> Data {
        guard offset >= 0, count >= 0, offset + Int64(count) <= size else {
            throw ReadError.pastTheEnd(offset: offset, count: count, size: size)
        }
        var out = Data()
        out.reserveCapacity(count)
        var at = offset
        var left = Int64(count)
        // The first extent holding `at`.
        var i = max(0, (starts.lastIndex { $0 <= at }) ?? 0)
        while left > 0 && i < extents.count {
            let e = extents[i]
            let inside = at - starts[i]
            let n = min(left, e.length - inside)
            if n > 0 {
                if let o = e.offset {
                    out.append(try base.read(at: o + inside, count: Int(n)))
                } else {
                    out.append(Data(count: Int(n)))
                }
                at += n
                left -= n
            }
            i += 1
        }
        guard left == 0 else { throw ReadError.pastTheEnd(offset: offset, count: count, size: size) }
        return out
    }

    /// The runs of `base` that hold `length` bytes from `offset` of this file (to copy without reading through).
    public func runs(from offset: Int64, length: Int64) -> [Extent] {
        var out: [Extent] = []
        var at = offset
        var left = length
        for (i, e) in extents.enumerated() where left > 0 {
            let start = starts[i]
            guard at < start + e.length else { continue }
            let inside = at - start
            let n = min(left, e.length - inside)
            out.append(Extent(offset: e.offset.map { $0 + inside }, length: n))
            at += n
            left -= n
        }
        return out
    }
}

/// A disk's bytes, described rather than held: runs of literal bytes, zeros and copies from files. The Windows stick
/// is one of these (a FAT32 file system laid over the ISO's files), streamed to the disk without ever being built.
public struct Layout {
    public enum Piece {
        case bytes(Data)
        case zeros(Int64)
        case copy(RandomAccess, offset: Int64, length: Int64)

        public var length: Int64 {
            switch self {
            case .bytes(let d): return Int64(d.count)
            case .zeros(let n): return n
            case .copy(_, _, let n): return n
            }
        }
    }

    public private(set) var pieces: [Piece] = []
    public private(set) var length: Int64 = 0
    /// Where each piece starts (for reading anywhere without walking every piece).
    private var starts: [Int64] = []

    public init() {}

    /// Adds a piece. A copy that carries straight on from the last one (the same file, the next byte) and zeros after
    /// zeros join the piece before, so a layout of many small runs stays a few big ones; another layout is taken in
    /// piece by piece.
    public mutating func append(_ p: Piece) {
        guard p.length > 0 else { return }
        if case .copy(let f, let o, let n) = p, let inner = f as? LayoutFile {
            for q in inner.layout.slice(from: o, length: n) { append(q) }
            return
        }
        if let last = pieces.last {
            switch (last, p) {
            case (.zeros(let a), .zeros(let b)):
                pieces[pieces.count - 1] = .zeros(a + b)
                length += b
                return
            case (.copy(let f1, let o1, let l1), .copy(let f2, let o2, let l2)) where f1 === f2 && o1 + l1 == o2:
                pieces[pieces.count - 1] = .copy(f1, offset: o1, length: l1 + l2)
                length += l2
                return
            default:
                break
            }
        }
        starts.append(length)
        pieces.append(p)
        length += p.length
    }

    public mutating func append(_ d: Data) { append(.bytes(d)) }

    /// The pieces covering `length` bytes from `offset`.
    func slice(from offset: Int64, length want: Int64) -> [Piece] {
        var out: [Piece] = []
        var at = offset
        var left = want
        guard var i = index(holding: at) else { return [] }
        while left > 0 && i < pieces.count {
            let p = pieces[i]
            let inside = at - starts[i]
            let n = min(left, p.length - inside)
            switch p {
            case .bytes(let d): out.append(.bytes(d.subdata(in: d.startIndex + Int(inside)..<d.startIndex + Int(inside + n))))
            case .zeros: out.append(.zeros(n))
            case .copy(let f, let o, _): out.append(.copy(f, offset: o + inside, length: n))
            }
            at += n
            left -= n
            i += 1
        }
        return out
    }

    private func index(holding offset: Int64) -> Int? {
        guard offset >= 0, offset < length else { return nil }
        var lo = 0
        var hi = starts.count - 1
        while lo < hi {
            let mid = (lo + hi + 1) / 2
            if starts[mid] <= offset { lo = mid } else { hi = mid - 1 }
        }
        return lo
    }

    /// Zeros up to `offset` (which must not be behind the end).
    public mutating func pad(to offset: Int64) {
        precondition(offset >= length, "a layout only grows: \(offset) is behind \(length)")
        append(.zeros(offset - length))
    }

    /// Everything in `file`, then zeros up to a multiple of `unit`.
    public mutating func append(file: RandomAccess, roundedTo unit: Int64) {
        append(.copy(file, offset: 0, length: file.size))
        let r = file.size % unit
        if r != 0 { append(.zeros(unit - r)) }
    }

    /// Reads `count` bytes at `offset` of the layout (the tests check a layout this way, and the stream uses it).
    public func read(at offset: Int64, count: Int) throws -> Data {
        guard offset >= 0, count >= 0, offset + Int64(count) <= length else {
            throw ReadError.pastTheEnd(offset: offset, count: count, size: length)
        }
        var out = Data()
        out.reserveCapacity(count)
        for p in slice(from: offset, length: Int64(count)) {
            switch p {
            case .bytes(let d): out.append(d)
            case .zeros(let n): out.append(Data(count: Int(n)))
            case .copy(let f, let o, let n): out.append(try f.read(at: o, count: Int(n)))
            }
        }
        return out
    }
}

/// A layout as a stream of bytes for `CardWriter` (one megabyte at a time).
public final class LayoutSource: PackedSource {
    private let pieces: [Layout.Piece]
    private var index = 0
    private var inside: Int64 = 0
    private var cancelled = false
    private let chunk: Int

    public init(_ layout: Layout, chunk: Int = CardWriter.blockBytes) {
        pieces = layout.pieces
        self.chunk = chunk
    }

    public func next() throws -> Data? {
        if cancelled { throw WriteError.cancelled }
        var out = Data()
        out.reserveCapacity(chunk)
        while out.count < chunk && index < pieces.count {
            let p = pieces[index]
            let n = Int(min(Int64(chunk - out.count), p.length - inside))
            switch p {
            case .bytes(let d): out.append(d.subdata(in: d.startIndex + Int(inside)..<d.startIndex + Int(inside) + n))
            case .zeros: out.append(Data(count: n))
            case .copy(let f, let o, _): out.append(try f.read(at: o + inside, count: n))
            }
            inside += Int64(n)
            if inside == p.length {
                index += 1
                inside = 0
            }
        }
        return out.isEmpty ? nil : out
    }

    public func cancel() { cancelled = true }
}

/// A whole file as a stream, one megabyte at a time, read with `pread` (an image written as it is).
public final class RandomAccessSource: PackedSource {
    private let file: RandomAccess
    private var at: Int64 = 0
    private var cancelled = false

    public init(_ file: RandomAccess) { self.file = file }

    public func next() throws -> Data? {
        if cancelled { throw WriteError.cancelled }
        guard at < file.size else { return nil }
        let n = Int(min(Int64(CardWriter.blockBytes), file.size - at))
        let d = try file.read(at: at, count: n)
        at += Int64(n)
        return d
    }

    public func cancel() { cancelled = true }
}

extension Data {
    func le16(_ i: Int) -> UInt16 {
        let b = startIndex + i
        return UInt16(self[b]) | UInt16(self[b + 1]) << 8
    }

    func le32(_ i: Int) -> UInt32 {
        let b = startIndex + i
        return UInt32(self[b]) | UInt32(self[b + 1]) << 8 | UInt32(self[b + 2]) << 16 | UInt32(self[b + 3]) << 24
    }

    func le64(_ i: Int) -> UInt64 { UInt64(le32(i)) | UInt64(le32(i + 4)) << 32 }

    func be16(_ i: Int) -> UInt16 {
        let b = startIndex + i
        return UInt16(self[b]) << 8 | UInt16(self[b + 1])
    }

    func byte(_ i: Int) -> UInt8 { self[startIndex + i] }

    func slice(_ i: Int, _ n: Int) -> Data { subdata(in: startIndex + i..<startIndex + i + n) }

    mutating func put16(_ v: UInt16, at i: Int) {
        let b = startIndex + i
        self[b] = UInt8(v & 0xFF)
        self[b + 1] = UInt8(v >> 8)
    }

    mutating func put32(_ v: UInt32, at i: Int) {
        for k in 0..<4 { self[startIndex + i + k] = UInt8((v >> (8 * UInt32(k))) & 0xFF) }
    }

    mutating func put64(_ v: UInt64, at i: Int) {
        for k in 0..<8 { self[startIndex + i + k] = UInt8((v >> (8 * UInt64(k))) & 0xFF) }
    }

    mutating func put(_ bytes: [UInt8], at i: Int) {
        for (k, b) in bytes.enumerated() { self[startIndex + i + k] = b }
    }

    static func le32(_ v: UInt32) -> Data {
        var d = Data(count: 4)
        d.put32(v, at: 0)
        return d
    }
}
