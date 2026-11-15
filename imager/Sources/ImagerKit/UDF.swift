import Foundation

/// A file or folder in a UDF file system (what Windows ISOs use: Microsoft's own images carry their files in UDF only,
/// with an ISO 9660 part that holds nothing but a note saying so).
public final class UDFNode {
    public let name: String
    public let isDirectory: Bool
    public let size: Int64
    /// Where its bytes are in the ISO.
    public let extents: [ExtentRandomAccess.Extent]
    public let modified: Date?
    /// A small file kept inside its own entry rather than in extents of its own.
    public let embedded: Data?
    public internal(set) var children: [UDFNode] = []

    init(name: String, isDirectory: Bool, size: Int64, extents: [ExtentRandomAccess.Extent], modified: Date?,
         embedded: Data? = nil) {
        self.name = name
        self.isDirectory = isDirectory
        self.size = size
        self.extents = extents
        self.modified = modified
        self.embedded = embedded
    }

    /// The file's bytes, read from `iso` (the image this node was read from).
    public func contents(in iso: RandomAccess) -> RandomAccess {
        if let e = embedded { return DataRandomAccess(e.prefix(Int(size))) }
        return ExtentRandomAccess(base: iso, extents: extents, size: size)
    }

    /// A child by name, ignoring case (Windows doesn't care, and ISOs differ: "sources" or "SOURCES").
    public func child(_ name: String) -> UDFNode? {
        children.first { $0.name.compare(name, options: .caseInsensitive) == .orderedSame }
    }

    /// A descendant by path ("efi/boot/bootx64.efi"), ignoring case.
    public func find(_ path: String) -> UDFNode? {
        var node: UDFNode? = self
        for part in path.split(separator: "/") where !part.isEmpty { node = node?.child(String(part)) }
        return node
    }

    /// Every file under this folder with its path from here, folders first in each folder ("sources/boot.wim").
    public func walk(_ prefix: String = "", _ body: (String, UDFNode) throws -> Void) rethrows {
        for c in children {
            let path = prefix.isEmpty ? c.name : prefix + "/" + c.name
            try body(path, c)
            if c.isDirectory { try c.walk(path, body) }
        }
    }

    public var totalFileBytes: Int64 {
        var n: Int64 = 0
        walk { _, c in if !c.isDirectory { n += c.size } }
        return n
    }
}

public enum UDFError: Error, Equatable, CustomStringConvertible {
    case notUDF
    case badDescriptor(String)
    case unsupported(String)

    public var description: String {
        switch self {
        case .notUDF: return "It has no UDF file system."
        case .badDescriptor(let what): return "Its UDF file system is damaged (\(what))."
        case .unsupported(let what): return "Its UDF file system uses something Sofa Box Imager doesn't read yet (\(what))."
        }
    }
}

/// Reads a UDF file system (ECMA-167 / OSTA UDF 1.02 to 2.01, type 1 partition maps): the volume descriptors, the file
/// set, then every directory. Nothing is read from the files themselves; `UDFNode.extents` says where they are.
public enum UDFReader {
    static let sector: Int64 = 2048
    /// More nodes than any Windows ISO has (about 1,000): a loop in a damaged image stops here.
    static let nodeLimit = 200_000

    public struct Volume {
        public let name: String
        public let root: UDFNode
        public let blockSize: Int64
    }

    /// Whether the image says it's UDF: "NSR02" or "NSR03" in its volume recognition sequence.
    public static func isUDF(_ file: RandomAccess) -> Bool {
        for i in 0..<16 {
            let at = 32768 + Int64(i) * sector
            guard let d = try? file.read(at: at, count: 6) else { return false }
            let id = String(decoding: d.slice(1, 5), as: UTF8.self)
            if id == "NSR02" || id == "NSR03" { return true }
            if id != "BEA01" && id != "CD001" && id != "CDW02" && id != "BOOT2" && id != "TEA01" { return false }
        }
        return false
    }

    public static func read(_ file: RandomAccess) throws -> Volume {
        guard isUDF(file) else { throw UDFError.notUDF }
        // Anchor at sector 256 (the end of the image keeps another; 256 is where every writer puts one).
        let avdp = try descriptor(file, at: 256 * sector, expect: 2)
        let mainLength = Int64(avdp.le32(16))
        let mainLocation = Int64(avdp.le32(20))
        var partitionStart: Int64?
        var blockSize: Int64 = sector
        var fsd: (block: Int64, partition: Int)?
        var volumeName = ""
        var partitionMaps: [Int] = []          // partition reference number -> partition number
        var partitionNumber = 0
        let count = max(1, min(64, mainLength / sector))
        for i in 0..<count {
            let at = (mainLocation + i) * sector
            let d = try file.read(at: at, count: Int(sector))
            guard tagOK(d) else { break }
            switch d.le16(0) {
            case 1:                                       // primary volume descriptor
                volumeName = dstring(d.slice(24, 32))
            case 5:                                       // partition descriptor
                partitionNumber = Int(d.le16(22))
                partitionStart = Int64(d.le32(188))
            case 6:                                       // logical volume descriptor
                blockSize = Int64(d.le32(212))
                fsd = (Int64(d.le32(252)), Int(d.le16(256)))
                let mapsLength = Int(d.le32(264))
                let maps = Int(d.le32(268))
                var o = 440
                for _ in 0..<maps where o + 2 <= 440 + mapsLength && o + 2 <= d.count {
                    let type = d.byte(o)
                    let len = Int(d.byte(o + 1))
                    guard len > 0 else { break }
                    if type == 1 {
                        partitionMaps.append(Int(d.le16(o + 4)))
                    } else {
                        throw UDFError.unsupported("a type \(type) partition map (UDF 2.50 metadata or a virtual partition)")
                    }
                    o += len
                }
            case 8:                                       // terminating descriptor
                break
            default:
                continue
            }
            if d.le16(0) == 8 { break }
        }
        guard let start = partitionStart, let set = fsd else { throw UDFError.badDescriptor("no partition or file set") }
        guard blockSize == sector else { throw UDFError.unsupported("\(blockSize)-byte blocks") }
        if !partitionMaps.isEmpty, set.partition < partitionMaps.count, partitionMaps[set.partition] != partitionNumber {
            throw UDFError.unsupported("more than one partition")
        }
        let ctx = Context(file: file, partitionStart: start)
        let fileSet = try descriptor(file, at: ctx.offset(set.block), expect: 256)
        let rootBlock = Int64(fileSet.le32(404))
        let rootEntry = try ctx.entry(at: rootBlock)
        let root = UDFNode(name: "", isDirectory: true, size: rootEntry.size, extents: rootEntry.extents,
                           modified: rootEntry.modified)
        var seen: Set<Int64> = [rootBlock]
        var nodes = 0
        try ctx.fill(root, entry: rootEntry, seen: &seen, nodes: &nodes, depth: 0)
        return Volume(name: volumeName, root: root, blockSize: blockSize)
    }

    struct Entry {
        var isDirectory: Bool
        var size: Int64
        var extents: [ExtentRandomAccess.Extent]
        var embedded: Data?
        var modified: Date?
    }

    final class Context {
        let file: RandomAccess
        let partitionStart: Int64

        init(file: RandomAccess, partitionStart: Int64) {
            self.file = file
            self.partitionStart = partitionStart
        }

        func offset(_ block: Int64) -> Int64 { (partitionStart + block) * UDFReader.sector }

        /// A File Entry (261) or Extended File Entry (266).
        func entry(at block: Int64) throws -> Entry {
            let d = try UDFReader.descriptor(file, at: offset(block), expect: nil)
            let tag = d.le16(0)
            guard tag == 261 || tag == 266 else { throw UDFError.badDescriptor("tag \(tag) where a file entry should be") }
            let fileType = d.byte(16 + 11)
            let flags = d.le16(16 + 18)
            let size = Int64(bitPattern: d.le64(56))
            let ext = tag == 266
            let modified = UDFReader.timestamp(d.slice(ext ? 92 : 84, 12))
            let eaLength = Int(d.le32(ext ? 208 : 168))
            let adLength = Int(d.le32(ext ? 212 : 172))
            let adStart = (ext ? 216 : 176) + eaLength
            guard adStart + adLength <= d.count else { throw UDFError.badDescriptor("allocation descriptors past the entry") }
            var e = Entry(isDirectory: fileType == 4, size: size, extents: [], embedded: nil, modified: modified)
            let adType = flags & 7
            if adType == 3 {
                e.embedded = d.slice(adStart, adLength)
                return e
            }
            var ads = d.slice(adStart, adLength)
            var type = adType
            var hops = 0
            while true {
                let width = type == 0 ? 8 : (type == 1 ? 16 : 20)
                guard type <= 2 else { throw UDFError.unsupported("allocation descriptors of type \(type)") }
                var o = 0
                var next: Int64?
                while o + width <= ads.count {
                    let raw = ads.le32(o)
                    let length = Int64(raw & 0x3FFF_FFFF)
                    let kind = raw >> 30
                    if length == 0 { break }
                    let location: Int64
                    switch type {
                    case 0: location = Int64(ads.le32(o + 4))
                    case 1: location = Int64(ads.le32(o + 4))
                    default: location = Int64(ads.le32(o + 12))
                    }
                    if kind == 3 {
                        next = location
                        break
                    }
                    e.extents.append(ExtentRandomAccess.Extent(offset: kind == 0 ? offset(location) : nil, length: length))
                    o += width
                }
                guard let n = next else { break }
                hops += 1
                guard hops < 10_000 else { throw UDFError.badDescriptor("a loop in a file's extents") }
                // An Allocation Extent Descriptor (258) continues the list.
                let aed = try UDFReader.descriptor(file, at: offset(n), expect: 258)
                let l = Int(aed.le32(20))
                guard 24 + l <= aed.count else { throw UDFError.badDescriptor("an allocation extent past its block") }
                ads = aed.slice(24, l)
                type = adType
            }
            return e
        }

        func contents(_ e: Entry) throws -> Data {
            if let d = e.embedded { return d.prefix(Int(e.size)) }
            let ra = ExtentRandomAccess(base: file, extents: e.extents, size: e.size)
            guard e.size <= 64 << 20 else { throw UDFError.badDescriptor("a directory of \(e.size) bytes") }
            return try ra.read(at: 0, count: Int(e.size))
        }

        func fill(_ dir: UDFNode, entry: Entry, seen: inout Set<Int64>, nodes: inout Int, depth: Int) throws {
            guard depth < 64 else { throw UDFError.badDescriptor("folders nested too deep") }
            let data = try contents(entry)
            var o = 0
            while o + 38 <= data.count {
                let fid = data.slice(o, min(data.count - o, 2048))
                guard fid.le16(0) == 257 else { throw UDFError.badDescriptor("a damaged directory entry") }
                let characteristics = fid.byte(18)
                let nameLength = Int(fid.byte(19))
                let block = Int64(fid.le32(24))
                let iuLength = Int(fid.le16(36))
                let total = (38 + iuLength + nameLength + 3) & ~3
                guard total <= fid.count else { throw UDFError.badDescriptor("a directory entry past its folder") }
                let isParent = characteristics & 0x08 != 0
                let isDeleted = characteristics & 0x04 != 0
                if !isParent && !isDeleted && nameLength > 0 {
                    let name = UDFReader.dstringRaw(fid.slice(38 + iuLength, nameLength))
                    nodes += 1
                    guard nodes < UDFReader.nodeLimit else { throw UDFError.badDescriptor("too many files") }
                    guard !name.isEmpty, !name.contains("/"), name != ".", name != ".." else {
                        throw UDFError.badDescriptor("a file named “\(DiskPolicy.printable(name))”")
                    }
                    let e = try self.entry(at: block)
                    let node = UDFNode(name: name, isDirectory: e.isDirectory, size: e.isDirectory ? 0 : e.size,
                                       extents: e.extents, modified: e.modified,
                                       embedded: e.isDirectory ? nil : e.embedded)
                    dir.children.append(node)
                    if e.isDirectory {
                        guard seen.insert(block).inserted else { throw UDFError.badDescriptor("a folder inside itself") }
                        try fill(node, entry: e, seen: &seen, nodes: &nodes, depth: depth + 1)
                    }
                }
                o += total
            }
        }
    }

    /// A descriptor at `offset`: its tag's checksum must add up, and its identifier be `expect` (when given).
    static func descriptor(_ file: RandomAccess, at offset: Int64, expect: UInt16?) throws -> Data {
        let d = try file.read(at: offset, count: Int(sector))
        guard tagOK(d) else { throw UDFError.badDescriptor("a tag that doesn't add up at \(offset)") }
        if let e = expect, d.le16(0) != e { throw UDFError.badDescriptor("tag \(d.le16(0)) where \(e) belongs") }
        return d
    }

    static func tagOK(_ d: Data) -> Bool {
        guard d.count >= 16 else { return false }
        var sum: UInt8 = 0
        for i in 0..<16 where i != 4 { sum &+= d.byte(i) }
        return sum == d.byte(4) && d.le16(0) != 0
    }

    /// A fixed-length d-string: its last byte says how many bytes are used.
    static func dstring(_ d: Data) -> String {
        guard d.count > 1 else { return "" }
        let used = min(Int(d.byte(d.count - 1)), d.count - 1)
        return dstringRaw(d.prefix(used)).trimmingCharacters(in: .whitespaces)
    }

    /// OSTA compressed Unicode: 8 (one byte a character) or 16 (UTF-16, big-endian).
    static func dstringRaw(_ d: Data) -> String {
        guard let id = d.first else { return "" }
        let body = d.dropFirst()
        switch id {
        case 8, 254:
            return String(body.map { Character(Unicode.Scalar($0)) })
        case 16, 255:
            var units: [UInt16] = []
            var i = body.startIndex
            while i + 1 < body.endIndex {
                units.append(UInt16(body[i]) << 8 | UInt16(body[i + 1]))
                i += 2
            }
            return String(decoding: units, as: UTF16.self)
        default:
            return ""
        }
    }

    /// ECMA-167 timestamp (12 bytes): a time zone, then year, month, day, hour, minute, second.
    static func timestamp(_ d: Data) -> Date? {
        let tz = d.le16(0)
        let year = Int(Int16(bitPattern: d.le16(2)))
        guard year >= 1980, year < 2200 else { return nil }
        var c = DateComponents()
        c.year = year
        c.month = Int(d.byte(4))
        c.day = Int(d.byte(5))
        c.hour = Int(d.byte(6))
        c.minute = Int(d.byte(7))
        c.second = Int(d.byte(8))
        // Type 1 (local time) carries its offset from UTC in minutes, as a 12-bit signed number.
        var offset = 0
        if tz >> 12 == 1 {
            var m = Int(tz & 0x0FFF)
            if m == 0x801 { m = 0 }                      // "not specified"
            if m > 0x7FF { m -= 0x1000 }
            offset = m
        }
        c.timeZone = TimeZone(secondsFromGMT: offset * 60)
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(secondsFromGMT: 0)!
        return cal.date(from: c)
    }
}
