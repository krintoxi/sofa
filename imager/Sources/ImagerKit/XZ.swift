import Foundation

public enum XZError: Error, Equatable, CustomStringConvertible {
    case corrupt
    case truncated
    case badPadding
    case cannotStart
    /// A real xz file, packed with something we don't unpack: a filter other than LZMA2, an unknown check, a dictionary
    /// over `XZUnpacker.largestDictionary`.
    case unsupported(String)

    public var description: String {
        switch self {
        case .corrupt: return "The downloaded card is damaged (its xz data doesn't unpack)."
        case .truncated: return "The downloaded card ends early."
        case .badPadding: return "The downloaded card has bytes after its end that shouldn't be there."
        case .cannotStart: return "macOS couldn't start unpacking the card."
        case .unsupported(let what): return "The downloaded card is packed in a way Sofa Box Imager doesn't unpack (\(what))."
        }
    }
}

/// What the writer needs from an xz unpacker: Apple's (`XZDecoder`, on the Mac) and ours (`XZUnpacker`) both do this.
public protocol XZUnpacking: AnyObject {
    var streams: Int { get }
    var packedBytes: Int64 { get }
    var unpackedBytes: Int64 { get }
    func feed(_ input: UnsafeRawBufferPointer, output: (UnsafeRawBufferPointer) throws -> Void) throws
    func finish(output: (UnsafeRawBufferPointer) throws -> Void) throws
}

extension XZUnpacking {
    public func feed(_ data: Data, output: (UnsafeRawBufferPointer) throws -> Void) throws {
        try data.withUnsafeBytes { try feed($0, output: output) }
    }
}

/// The unpacker the writer uses. On the Mac it stays Apple's Compression framework, which has unpacked every card so far,
/// until ours has been timed against it on real cards; on Windows and Linux it's ours.
#if canImport(Compression)
typealias WriterXZDecoder = XZDecoder
#else
typealias WriterXZDecoder = XZUnpacker
#endif

/// Unpacks an `.xz` file as it streams in, written here from the xz file format (1.2.1) and the LZMA specification so that
/// Windows and Linux need nothing from the system. It reads what `xz` writes: one or more streams, each of any number of
/// blocks, zero padding between streams in multiples of four bytes, LZMA2 data, and a CRC32, CRC64 or SHA-256 check on
/// every block. Every check, every block's sizes and every stream's index and footer are checked; anything that doesn't
/// add up stops with `.corrupt`, and a file that ends early with `.truncated`.
///
/// The packed bytes are kept until a whole piece has arrived (a header, an LZMA2 chunk of at most 64 KiB, the index), and
/// each piece is decoded from that buffer with every read checked against its end, so damaged data can't read past what
/// arrived. Unpacked bytes are handed on a chunk at a time (at most 2 MiB).
public final class XZUnpacker: XZUnpacking {
    public private(set) var streams = 0
    public private(set) var packedBytes: Int64 = 0
    public private(set) var unpackedBytes: Int64 = 0

    /// The largest LZMA2 dictionary we make room for. xz's own presets go up to 64 MiB.
    public static let largestDictionary = 1 << 30

    private enum Phase { case streamHeader, blockOrIndex, chunks, blockEnd, index, footer, between }
    private var phase = Phase.streamHeader
    private var buffer: [UInt8] = []
    private var at = 0

    // The stream being read.
    private var streamFlags: (UInt8, UInt8) = (0, 0)
    private var checkType = 0
    private var checkSize = 0
    private var records: [(unpadded: UInt64, uncompressed: UInt64)] = []
    private var indexSize = 0
    private var padding = 0

    // The block being read.
    private var headerSize = 0
    private var declaredPacked: UInt64?
    private var declaredUnpacked: UInt64?
    private var blockPacked: UInt64 = 0
    private var blockUnpacked: UInt64 = 0
    private var check = BlockCheck(type: 0)
    private let lzma = LZMA2Decoder()

    /// Bytes each check type takes, by the type's number (0 to 15). We check types 0 (none), 1, 4 and 10.
    private static let checkSizes = [0, 4, 4, 4, 8, 8, 8, 16, 16, 16, 32, 32, 32, 64, 64, 64]

    public init() throws {}

    public func feed(_ input: UnsafeRawBufferPointer, output: (UnsafeRawBufferPointer) throws -> Void) throws {
        guard input.count > 0 else { return }
        packedBytes += Int64(input.count)
        buffer.append(contentsOf: input)
        try buffer.withUnsafeBufferPointer { b in
            while try step(b, output) {}
        }
        if at == buffer.count {
            buffer.removeAll(keepingCapacity: true)
            at = 0
        } else if at >= 1 << 20 {
            buffer.removeFirst(at)
            at = 0
        }
    }

    /// The input has ended: the last stream must be complete, and the padding after it whole words.
    public func finish(output: (UnsafeRawBufferPointer) throws -> Void) throws {
        guard phase == .between else { throw XZError.truncated }
        guard padding % 4 == 0 else { throw XZError.badPadding }
    }

    /// One piece of the file, if all of it has arrived. False when it needs more input.
    private func step(_ b: UnsafeBufferPointer<UInt8>, _ output: (UnsafeRawBufferPointer) throws -> Void) throws -> Bool {
        let avail = b.count - at
        switch phase {
        case .streamHeader:
            guard avail >= 12 else { return false }
            let h = UnsafeBufferPointer(rebasing: b[at..<at + 12])
            guard h[0] == 0xFD, h[1] == 0x37, h[2] == 0x7A, h[3] == 0x58, h[4] == 0x5A, h[5] == 0,
                  CRC32.update(0, UnsafeBufferPointer(rebasing: h[6..<8])) == le32(h, 8) else { throw XZError.corrupt }
            guard h[6] == 0, h[7] & 0xF0 == 0 else { throw XZError.unsupported("stream flags \(h[6]), \(h[7])") }
            checkType = Int(h[7])
            guard [0, 1, 4, 10].contains(checkType) else { throw XZError.unsupported("check type \(checkType)") }
            checkSize = XZUnpacker.checkSizes[checkType]
            streamFlags = (h[6], h[7])
            records.removeAll()
            at += 12
            phase = .blockOrIndex

        case .blockOrIndex:
            guard avail >= 1 else { return false }
            if b[at] == 0 {
                phase = .index
                return true
            }
            let size = (Int(b[at]) + 1) * 4
            guard avail >= size else { return false }
            try startBlock(UnsafeBufferPointer(rebasing: b[at..<at + size]))
            at += size
            phase = .chunks

        case .chunks:
            guard avail >= 1 else { return false }
            let control = b[at]
            if control == 0 {
                at += 1
                blockPacked += 1
                if let d = declaredPacked, blockPacked > d { throw XZError.corrupt }
                phase = .blockEnd
                return true
            }
            let head: Int
            if control == 1 || control == 2 {
                head = 3
            } else if control >= 0x80 {
                head = control >= 0xC0 ? 6 : 5
            } else {
                throw XZError.corrupt
            }
            guard avail >= head else { return false }
            let unpacked: Int, packed: Int
            if control < 0x80 {
                unpacked = (Int(b[at + 1]) << 8 | Int(b[at + 2])) + 1
                packed = unpacked
            } else {
                unpacked = (Int(control & 0x1F) << 16 | Int(b[at + 1]) << 8 | Int(b[at + 2])) + 1
                packed = (Int(b[at + 3]) << 8 | Int(b[at + 4])) + 1
            }
            guard avail >= head + packed else { return false }
            blockPacked += UInt64(head + packed)
            if let d = declaredPacked, blockPacked > d { throw XZError.corrupt }
            if let d = declaredUnpacked, blockUnpacked + UInt64(unpacked) > d { throw XZError.corrupt }
            let pieces = try lzma.chunk(control: control, props: control >= 0xC0 ? b[at + 5] : nil,
                                        data: b.baseAddress! + at + head, packed: packed, unpacked: unpacked)
            at += head + packed
            try emit(pieces.0, output)
            if let second = pieces.1 { try emit(second, output) }

        case .blockEnd:
            let pad = Int((4 - (UInt64(headerSize) + blockPacked) % 4) % 4)
            guard avail >= pad + checkSize else { return false }
            for i in 0..<pad where b[at + i] != 0 { throw XZError.corrupt }
            guard check.matches(UnsafeBufferPointer(rebasing: b[at + pad..<at + pad + checkSize])) else {
                throw XZError.corrupt
            }
            if let d = declaredPacked, d != blockPacked { throw XZError.corrupt }
            if let d = declaredUnpacked, d != blockUnpacked { throw XZError.corrupt }
            records.append((UInt64(headerSize) + blockPacked + UInt64(checkSize), blockUnpacked))
            at += pad + checkSize
            phase = .blockOrIndex

        case .index:
            guard let used = try parseIndex(UnsafeBufferPointer(rebasing: b[at...])) else { return false }
            indexSize = used
            at += used
            phase = .footer

        case .footer:
            guard avail >= 12 else { return false }
            let f = UnsafeBufferPointer(rebasing: b[at..<at + 12])
            guard CRC32.update(0, UnsafeBufferPointer(rebasing: f[4..<10])) == le32(f, 0),
                  (Int(le32(f, 4)) + 1) * 4 == indexSize,
                  f[8] == streamFlags.0, f[9] == streamFlags.1, f[10] == 0x59, f[11] == 0x5A else { throw XZError.corrupt }
            at += 12
            streams += 1
            padding = 0
            phase = .between

        case .between:
            while at < b.count && b[at] == 0 {
                padding += 1
                at += 1
            }
            if at == b.count { return false }
            guard padding % 4 == 0 else { throw XZError.badPadding }
            phase = .streamHeader
        }
        return true
    }

    private func emit(_ piece: UnsafeRawBufferPointer, _ output: (UnsafeRawBufferPointer) throws -> Void) throws {
        check.update(piece)
        blockUnpacked += UInt64(piece.count)
        unpackedBytes += Int64(piece.count)
        try output(piece)
    }

    private func startBlock(_ h: UnsafeBufferPointer<UInt8>) throws {
        let body = UnsafeBufferPointer(rebasing: h[0..<h.count - 4])
        guard CRC32.update(0, body) == le32(h, h.count - 4) else { throw XZError.corrupt }
        let flags = h[1]
        guard flags & 0x3C == 0 else { throw XZError.unsupported("block flags \(flags)") }
        var i = 2
        declaredPacked = nil
        declaredUnpacked = nil
        if flags & 0x40 != 0 {
            guard let v = try XZUnpacker.vli(body, &i), v > 0 else { throw XZError.corrupt }
            declaredPacked = v
        }
        if flags & 0x80 != 0 {
            guard let v = try XZUnpacker.vli(body, &i) else { throw XZError.corrupt }
            declaredUnpacked = v
        }
        let filters = Int(flags & 3) + 1
        var dictionary: UInt8?
        for n in 0..<filters {
            guard let id = try XZUnpacker.vli(body, &i), let size = try XZUnpacker.vli(body, &i),
                  size <= UInt64(body.count - i) else { throw XZError.corrupt }
            guard id == 0x21 else { throw XZError.unsupported("filter 0x" + String(id, radix: 16)) }
            guard n == filters - 1, size == 1 else { throw XZError.corrupt }
            dictionary = body[i]
            i += Int(size)
        }
        guard let dict = dictionary else { throw XZError.corrupt }
        while i < body.count {
            guard body[i] == 0 else { throw XZError.corrupt }
            i += 1
        }
        try lzma.startBlock(dictionary: dict)
        headerSize = h.count
        blockPacked = 0
        blockUnpacked = 0
        check = BlockCheck(type: checkType)
    }

    /// The stream's index, once all of it has arrived: how many bytes it takes, or nil while it's incomplete. Every record
    /// must be the block just read.
    private func parseIndex(_ p: UnsafeBufferPointer<UInt8>) throws -> Int? {
        guard p.count >= 1 else { return nil }
        guard p[0] == 0 else { throw XZError.corrupt }
        var i = 1
        guard let count = try XZUnpacker.vli(p, &i) else { return nil }
        guard count == UInt64(records.count) else { throw XZError.corrupt }
        for r in records {
            guard let unpadded = try XZUnpacker.vli(p, &i), let uncompressed = try XZUnpacker.vli(p, &i) else { return nil }
            guard unpadded == r.unpadded, uncompressed == r.uncompressed else { throw XZError.corrupt }
        }
        while i % 4 != 0 {
            guard i < p.count else { return nil }
            guard p[i] == 0 else { throw XZError.corrupt }
            i += 1
        }
        guard i + 4 <= p.count else { return nil }
        guard CRC32.update(0, UnsafeBufferPointer(rebasing: p[0..<i])) == le32(p, i) else { throw XZError.corrupt }
        return i + 4
    }

    /// xz's variable-length integers: seven bits a byte, low first, at most nine bytes, no needless zero bytes. Nil if
    /// the buffer ends inside one.
    static func vli(_ p: UnsafeBufferPointer<UInt8>, _ i: inout Int) throws -> UInt64? {
        var value: UInt64 = 0
        var j = i
        for k in 0..<9 {
            guard j < p.count else { return nil }
            let byte = p[j]
            j += 1
            value |= UInt64(byte & 0x7F) << UInt64(7 * k)
            if byte & 0x80 == 0 {
                guard k == 0 || byte != 0 else { throw XZError.corrupt }
                i = j
                return value
            }
        }
        throw XZError.corrupt
    }
}

@inline(__always) private func le32(_ p: UnsafeBufferPointer<UInt8>, _ i: Int) -> UInt32 {
    UInt32(p[i]) | UInt32(p[i + 1]) << 8 | UInt32(p[i + 2]) << 16 | UInt32(p[i + 3]) << 24
}

private struct BlockCheck {
    let type: Int
    var crc32: UInt32 = 0
    var crc64: UInt64 = 0
    var sha: SHA256Hasher?

    init(type: Int) {
        self.type = type
        if type == 10 { sha = SHA256Hasher() }
    }

    mutating func update(_ p: UnsafeRawBufferPointer) {
        switch type {
        case 1: crc32 = CRC32.update(crc32, p)
        case 4: crc64 = CRC64.update(crc64, p)
        case 10: sha!.update(bufferPointer: p)
        default: break
        }
    }

    func matches(_ stored: UnsafeBufferPointer<UInt8>) -> Bool {
        switch type {
        case 0: return true
        case 1: return le32(stored, 0) == crc32
        case 4: return UInt64(le32(stored, 0)) | UInt64(le32(stored, 4)) << 32 == crc64
        case 10: return Array(stored) == sha!.finalize()
        default: return false
        }
    }
}

/// CRC-32 as xz (and zip) use it: polynomial 0xEDB88320, reflected.
enum CRC32 {
    static let table: [UInt32] = (0..<256).map { i in
        var c = UInt32(i)
        for _ in 0..<8 { c = c & 1 != 0 ? 0xEDB8_8320 ^ (c >> 1) : c >> 1 }
        return c
    }

    static func update(_ crc: UInt32, _ p: UnsafeRawBufferPointer) -> UInt32 {
        var c = ~crc
        table.withUnsafeBufferPointer { t in
            for byte in p { c = t[Int((c ^ UInt32(byte)) & 0xFF)] ^ (c >> 8) }
        }
        return ~c
    }

    static func update(_ crc: UInt32, _ p: UnsafeBufferPointer<UInt8>) -> UInt32 { update(crc, UnsafeRawBufferPointer(p)) }
}

/// CRC-64 as xz uses it: ECMA-182's polynomial, reflected (0xC96C5795D7870F42). Eight bytes at a time (slicing by 8).
enum CRC64 {
    static let tables: [UInt64] = {
        var t = [UInt64](repeating: 0, count: 8 * 256)
        for i in 0..<256 {
            var c = UInt64(i)
            for _ in 0..<8 { c = c & 1 != 0 ? 0xC96C_5795_D787_0F42 ^ (c >> 1) : c >> 1 }
            t[i] = c
        }
        for k in 1..<8 {
            for i in 0..<256 { t[k * 256 + i] = t[(k - 1) * 256 + i] >> 8 ^ t[Int(t[(k - 1) * 256 + i] & 0xFF)] }
        }
        return t
    }()

    static func update(_ crc: UInt64, _ p: UnsafeRawBufferPointer) -> UInt64 {
        guard var q = p.baseAddress, p.count > 0 else { return crc }
        var n = p.count
        var c = ~crc
        tables.withUnsafeBufferPointer { t in
            while n >= 8 {
                c ^= UInt64(littleEndian: q.loadUnaligned(as: UInt64.self))
                c = t[7 * 256 + Int(c & 0xFF)] ^ t[6 * 256 + Int((c >> 8) & 0xFF)]
                    ^ t[5 * 256 + Int((c >> 16) & 0xFF)] ^ t[4 * 256 + Int((c >> 24) & 0xFF)]
                    ^ t[3 * 256 + Int((c >> 32) & 0xFF)] ^ t[2 * 256 + Int((c >> 40) & 0xFF)]
                    ^ t[256 + Int((c >> 48) & 0xFF)] ^ t[Int(c >> 56)]
                q += 8
                n -= 8
            }
            while n > 0 {
                c = t[Int((c ^ UInt64(q.load(as: UInt8.self))) & 0xFF)] ^ (c >> 8)
                q += 1
                n -= 1
            }
        }
        return ~c
    }
}

/// Where each LZMA probability lives in one array (the LZMA specification's layout, counted in 16-bit probabilities).
private enum Probs {
    static let isMatch = 0              // 12 states x 16 positions
    static let isRep = 192
    static let isRepG0 = 204
    static let isRepG1 = 216
    static let isRepG2 = 228
    static let isRep0Long = 240         // 12 x 16
    static let posSlot = 432            // 4 x 64
    static let specPos = 688            // 115
    static let align = 803              // 16
    static let length = 819             // choice, choice 2, 16 x 8 low, 16 x 8 middle, 256 high: 514
    static let repLength = 1333
    static let literal = 1847           // 0x300 for each of up to 16 literal contexts (lc + lp <= 4 in LZMA2)
    static let count = literal + 0x300 * 16
}

/// LZMA2: chunks of LZMA data or stored bytes, sharing one dictionary within a block.
final class LZMA2Decoder {
    private var buf: UnsafeMutablePointer<UInt8>?
    private var bufSize = 0
    private var dictSize = 0
    private var pos = 0
    /// Bytes since the dictionary was last reset: where positions (for `pb` and `lp`) are counted from.
    private var total = 0
    private var needDictReset = true
    private var needProps = true
    private var lc = 0, lp = 0, pb = 0
    private var state = 0
    private var rep0: UInt32 = 0, rep1: UInt32 = 0, rep2: UInt32 = 0, rep3: UInt32 = 0
    private let probs = UnsafeMutablePointer<UInt16>.allocate(capacity: Probs.count)

    deinit {
        buf?.deallocate()
        probs.deallocate()
    }

    func startBlock(dictionary p: UInt8) throws {
        guard p & 0xC0 == 0, p <= 40 else { throw XZError.corrupt }
        let bits = Int(p)
        let size = bits == 40 ? Int(UInt32.max) : (2 | (bits & 1)) << (bits / 2 + 11)
        guard size <= XZUnpacker.largestDictionary else {
            throw XZError.unsupported("a \(size >> 20) MiB dictionary")
        }
        dictSize = size
        // A chunk (at most 2 MiB) stays whole in the buffer until it's handed on.
        let want = max(size, 2 << 20)
        if want != bufSize {
            buf?.deallocate()
            buf = .allocate(capacity: want)
            bufSize = want
        }
        needDictReset = true
        needProps = true
        pos = 0
        total = 0
    }

    /// One chunk, all of it in `data`. Returns where its unpacked bytes are: one piece, or two when they wrap round the
    /// end of the buffer.
    func chunk(control: UInt8, props: UInt8?, data: UnsafePointer<UInt8>, packed: Int, unpacked: Int) throws
        -> (UnsafeRawBufferPointer, UnsafeRawBufferPointer?) {
        guard let buf = buf else { throw XZError.corrupt }
        if control == 1 || control >= 0xE0 {
            needProps = true
            needDictReset = false
            pos = 0
            total = 0
        } else if needDictReset {
            throw XZError.corrupt
        }
        let start = pos
        if control >= 0x80 {
            if let p = props {
                try setProps(p)
                needProps = false
                resetState()
            } else if needProps {
                throw XZError.corrupt
            } else if control >= 0xA0 {
                resetState()
            }
            try decode(data, packed: packed, unpacked: unpacked)
        } else {
            var left = unpacked, src = data
            while left > 0 {
                let k = min(left, bufSize - pos)
                (buf + pos).update(from: src, count: k)
                pos += k
                if pos == bufSize { pos = 0 }
                src += k
                left -= k
            }
            total += unpacked
        }
        let first = min(unpacked, bufSize - start)
        return (UnsafeRawBufferPointer(start: buf + start, count: first),
                unpacked > first ? UnsafeRawBufferPointer(start: buf, count: unpacked - first) : nil)
    }

    private func setProps(_ d: UInt8) throws {
        guard d < 9 * 5 * 5 else { throw XZError.corrupt }
        let v = Int(d)
        lc = v % 9
        lp = (v / 9) % 5
        pb = v / 45
        guard lc + lp <= 4 else { throw XZError.corrupt }
    }

    private func resetState() {
        state = 0
        rep0 = 0; rep1 = 0; rep2 = 0; rep3 = 0
        probs.update(repeating: 1024, count: Probs.literal + (0x300 << (lc + lp)))
    }

    private func decode(_ data: UnsafePointer<UInt8>, packed: Int, unpacked: Int) throws {
        guard packed >= 5, data[0] == 0, let buf = buf else { throw XZError.corrupt }
        var rc = RangeDecoder(data + 1, end: data + packed)
        guard rc.code != rc.range else { throw XZError.corrupt }
        let bufSize = self.bufSize, dictSize = self.dictSize, lc = self.lc
        let pbMask = (1 << pb) - 1, lpMask = (1 << lp) - 1
        let p = probs
        var pos = self.pos, total = self.total, state = self.state
        var rep0 = self.rep0, rep1 = self.rep1, rep2 = self.rep2, rep3 = self.rep3
        var left = unpacked

        while left > 0 {
            if rc.overrun { throw XZError.corrupt }
            let posState = total & pbMask
            let full = min(total, dictSize)
            if rc.bit(p + Probs.isMatch + (state << 4) + posState) == 0 {
                let prev = total > 0 ? Int(buf[(pos == 0 ? bufSize : pos) - 1]) : 0
                let lit = p + Probs.literal + 0x300 * (((total & lpMask) << lc) + (prev >> (8 - lc)))
                var symbol = 1
                if state >= 7 {
                    guard Int(rep0) < full else { throw XZError.corrupt }
                    var at = pos - Int(rep0) - 1
                    if at < 0 { at += bufSize }
                    var match = Int(buf[at])
                    repeat {
                        let matchBit = (match >> 7) & 1
                        match <<= 1
                        let bit = rc.bit(lit + ((1 + matchBit) << 8) + symbol)
                        symbol = (symbol << 1) | bit
                        if matchBit != bit { break }
                    } while symbol < 0x100
                }
                while symbol < 0x100 { symbol = (symbol << 1) | rc.bit(lit + symbol) }
                buf[pos] = UInt8(truncatingIfNeeded: symbol)
                pos += 1
                if pos == bufSize { pos = 0 }
                total += 1
                left -= 1
                state = state < 4 ? 0 : (state < 10 ? state - 3 : state - 6)
                continue
            }

            let len: Int
            if rc.bit(p + Probs.isRep + state) != 0 {
                if rc.bit(p + Probs.isRepG0 + state) == 0 {
                    if rc.bit(p + Probs.isRep0Long + (state << 4) + posState) == 0 {
                        // A single byte from rep0.
                        guard Int(rep0) < full else { throw XZError.corrupt }
                        state = state < 7 ? 9 : 11
                        var at = pos - Int(rep0) - 1
                        if at < 0 { at += bufSize }
                        buf[pos] = buf[at]
                        pos += 1
                        if pos == bufSize { pos = 0 }
                        total += 1
                        left -= 1
                        continue
                    }
                } else {
                    let dist: UInt32
                    if rc.bit(p + Probs.isRepG1 + state) == 0 {
                        dist = rep1
                    } else {
                        if rc.bit(p + Probs.isRepG2 + state) == 0 {
                            dist = rep2
                        } else {
                            dist = rep3
                            rep3 = rep2
                        }
                        rep2 = rep1
                    }
                    rep1 = rep0
                    rep0 = dist
                }
                len = rc.length(p + Probs.repLength, posState)
                state = state < 7 ? 8 : 11
            } else {
                rep3 = rep2
                rep2 = rep1
                rep1 = rep0
                len = rc.length(p + Probs.length, posState)
                state = state < 7 ? 7 : 10
                rep0 = rc.distance(p, len)
                // The end marker: LZMA2 knows each chunk's size and never has one.
                if rep0 == UInt32.max { throw XZError.corrupt }
            }

            let n = len + 2
            let dist = Int(rep0) + 1
            guard dist <= full, n <= left else { throw XZError.corrupt }
            var src = pos - dist
            if src < 0 { src += bufSize }
            if dist == 1 && pos + n <= bufSize {
                // A run of one byte (most of a disk image's empty space).
                (buf + pos).update(repeating: buf[src], count: n)
                pos += n
                if pos == bufSize { pos = 0 }
            } else if pos + n <= bufSize && src + n <= bufSize && (pos + n <= src || src + n <= pos) {
                // Neither end wraps and the two don't overlap.
                (buf + pos).update(from: buf + src, count: n)
                pos += n
                if pos == bufSize { pos = 0 }
            } else {
                for _ in 0..<n {
                    buf[pos] = buf[src]
                    pos += 1
                    if pos == bufSize { pos = 0 }
                    src += 1
                    if src == bufSize { src = 0 }
                }
            }
            total += n
            left -= n
        }
        guard !rc.overrun, rc.at == rc.end, rc.code == 0 else { throw XZError.corrupt }
        self.pos = pos
        self.total = total
        self.state = state
        self.rep0 = rep0; self.rep1 = rep1; self.rep2 = rep2; self.rep3 = rep3
    }
}

/// LZMA's range decoder, over one chunk's bytes. Reading past the end gives zeros and sets `overrun`.
private struct RangeDecoder {
    var range: UInt32 = 0xFFFF_FFFF
    var code: UInt32 = 0
    var at: UnsafePointer<UInt8>
    let end: UnsafePointer<UInt8>
    var overrun = false

    /// `start` is just after the chunk's first byte, which must be zero.
    init(_ start: UnsafePointer<UInt8>, end: UnsafePointer<UInt8>) {
        at = start
        self.end = end
        for _ in 0..<4 { code = (code << 8) | UInt32(next()) }
    }

    @inline(__always) private mutating func next() -> UInt8 {
        if at < end {
            let b = at.pointee
            at += 1
            return b
        }
        overrun = true
        return 0
    }

    @inline(__always) private mutating func normalize() {
        if range < 1 << 24 {
            range <<= 8
            code = (code << 8) | UInt32(next())
        }
    }

    @inline(__always) mutating func bit(_ prob: UnsafeMutablePointer<UInt16>) -> Int {
        let v = UInt32(prob.pointee)
        let bound = (range >> 11) &* v
        let result: Int
        if code < bound {
            range = bound
            prob.pointee = UInt16(truncatingIfNeeded: v + ((2048 - v) >> 5))
            result = 0
        } else {
            range &-= bound
            code &-= bound
            prob.pointee = UInt16(truncatingIfNeeded: v - (v >> 5))
            result = 1
        }
        normalize()
        return result
    }

    @inline(__always) mutating func tree(_ probs: UnsafeMutablePointer<UInt16>, bits: Int) -> Int {
        var m = 1
        for _ in 0..<bits { m = (m << 1) | bit(probs + m) }
        return m - (1 << bits)
    }

    @inline(__always) mutating func reverseTree(_ probs: UnsafeMutablePointer<UInt16>, bits: Int) -> Int {
        var m = 1, symbol = 0
        for i in 0..<bits {
            let b = bit(probs + m)
            m = (m << 1) | b
            symbol |= b << i
        }
        return symbol
    }

    mutating func direct(_ count: Int) -> UInt32 {
        var result: UInt32 = 0
        for _ in 0..<count {
            range >>= 1
            code &-= range
            let t = 0 &- (code >> 31)
            code &+= range & t
            normalize()
            result = (result << 1) &+ (t &+ 1)
        }
        return result
    }

    /// A match length less two: 0 to 271.
    @inline(__always) mutating func length(_ probs: UnsafeMutablePointer<UInt16>, _ posState: Int) -> Int {
        if bit(probs) == 0 { return tree(probs + 2 + (posState << 3), bits: 3) }
        if bit(probs + 1) == 0 { return 8 + tree(probs + 130 + (posState << 3), bits: 3) }
        return 16 + tree(probs + 258, bits: 8)
    }

    /// A match distance less one.
    @inline(__always) mutating func distance(_ p: UnsafeMutablePointer<UInt16>, _ len: Int) -> UInt32 {
        let slot = tree(p + Probs.posSlot + (min(len, 3) << 6), bits: 6)
        if slot < 4 { return UInt32(slot) }
        let directBits = (slot >> 1) - 1
        var dist = UInt32((2 | (slot & 1)) << directBits)
        if slot < 14 {
            dist &+= UInt32(reverseTree(p + Probs.specPos + Int(dist) - slot, bits: directBits))
        } else {
            dist &+= direct(directBits - 4) << 4
            dist &+= UInt32(reverseTree(p + Probs.align, bits: 4))
        }
        return dist
    }
}
