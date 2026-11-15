import Foundation

/// A Windows image file (`install.wim`, `install.esd`, `boot.wim`): its header, its table of resources and its XML,
/// read as Microsoft's "Windows Imaging File Format" paper describes them. Enough to say what's inside, and to split one
/// into `.swm` parts that each fit FAT32's 4 GB limit, copying every resource byte for byte (nothing is unpacked).
public struct WIMFile {
    public static let headerSize = 208
    public static let magic = Data("MSWIM\0\0\0".utf8)
    public static let flagSpanned: UInt32 = 0x0000_0008
    public static let entrySize = 50

    /// A resource header: where a resource is in the file, how big it is there, its flags, and its size unpacked.
    public struct Resource: Equatable {
        public var size: Int64                 // in the file (56 bits)
        public var flags: UInt8
        public var offset: Int64
        public var originalSize: Int64

        public static let flagFree: UInt8 = 0x01
        public static let flagMetadata: UInt8 = 0x02
        public static let flagCompressed: UInt8 = 0x04
        public static let flagSpanned: UInt8 = 0x08
        public static let flagSolid: UInt8 = 0x10

        init(_ d: Data, at o: Int) {
            size = Int64(d.le64(o) & 0x00FF_FFFF_FFFF_FFFF)
            flags = d.byte(o + 7)
            offset = Int64(bitPattern: d.le64(o + 8))
            originalSize = Int64(bitPattern: d.le64(o + 16))
        }

        public init(size: Int64, flags: UInt8, offset: Int64, originalSize: Int64) {
            self.size = size
            self.flags = flags
            self.offset = offset
            self.originalSize = originalSize
        }

        var bytes: Data {
            var d = Data(count: 24)
            d.put64(UInt64(size) & 0x00FF_FFFF_FFFF_FFFF | UInt64(flags) << 56, at: 0)
            d.put64(UInt64(bitPattern: offset), at: 8)
            d.put64(UInt64(bitPattern: originalSize), at: 16)
            return d
        }

        static let empty = Resource(size: 0, flags: 0, offset: 0, originalSize: 0)
    }

    /// One entry of the resource table: a resource, the part it's in, how many times it's used, its SHA-1.
    public struct Entry: Equatable {
        public var resource: Resource
        public var part: UInt16
        public var refCount: UInt32
        public var hash: Data

        public var isMetadata: Bool { resource.flags & Resource.flagMetadata != 0 }
        public var isSolid: Bool { resource.flags & Resource.flagSolid != 0 }
        /// In a solid table, the entry that describes a solid resource itself (rather than a file inside one).
        public var isSolidResource: Bool { isSolid && resource.originalSize == 0x1_0000_0000 }

        var bytes: Data {
            var d = resource.bytes
            var tail = Data(count: 26)
            tail.put16(part, at: 0)
            tail.put32(refCount, at: 2)
            tail.replaceSubrange(6..<26, with: hash.prefix(20))
            d.append(tail)
            return d
        }
    }

    /// One Windows inside, from the XML.
    public struct Image: Equatable {
        public var index: Int
        public var name: String
        public var displayName: String
        public var edition: String
        /// 0 x86, 9 x64 (amd64), 12 ARM64.
        public var arch: Int?
        public var major: Int?
        public var minor: Int?
        public var build: Int?
        public var servicePackBuild: Int?
    }

    public let header: Data
    public let flags: UInt32
    public let version: UInt32
    public let guid: Data
    public let part: UInt16
    public let totalParts: UInt16
    public let imageCount: UInt32
    public let table: Resource
    public let xml: Resource
    public let bootMetadata: Resource
    public let bootIndex: UInt32
    public let integrity: Resource
    public let entries: [Entry]
    public let xmlData: Data
    public let images: [Image]

    /// An ESD-style image, whose files are packed together in big solid resources (LZMS).
    public var hasSolidResources: Bool { entries.contains { $0.isSolid } || version == 0xE00 }

    public static func looksLikeWIM(_ head: Data) -> Bool { head.count >= 8 && head.prefix(8) == magic }

    public init(_ file: RandomAccess) throws {
        guard file.size >= Int64(WIMFile.headerSize) else { throw WIMError.notAWIM }
        let h = try file.read(at: 0, count: WIMFile.headerSize)
        guard WIMFile.looksLikeWIM(h), h.le32(8) == UInt32(WIMFile.headerSize) else { throw WIMError.notAWIM }
        header = h
        version = h.le32(0x0C)
        flags = h.le32(0x10)
        guid = h.slice(0x18, 16)
        part = h.le16(0x28)
        totalParts = h.le16(0x2A)
        imageCount = h.le32(0x2C)
        table = Resource(h, at: 0x30)
        xml = Resource(h, at: 0x48)
        bootMetadata = Resource(h, at: 0x60)
        bootIndex = h.le32(0x78)
        integrity = Resource(h, at: 0x7C)
        guard table.flags & Resource.flagCompressed == 0, xml.flags & Resource.flagCompressed == 0 else {
            throw WIMError.unsupported("a compressed resource table or XML")
        }
        guard table.offset >= 0, table.size >= 0, table.offset + table.size <= file.size, table.size % 50 == 0,
              table.size <= 256 << 20 else {
            throw WIMError.damaged("its resource table is outside the file")
        }
        guard xml.offset >= 0, xml.size >= 0, xml.offset + xml.size <= file.size, xml.size <= 64 << 20 else {
            throw WIMError.damaged("its XML is outside the file")
        }
        let t = try file.read(at: table.offset, count: Int(table.size))
        var list: [Entry] = []
        list.reserveCapacity(Int(table.size) / 50)
        var o = 0
        while o + 50 <= t.count {
            list.append(Entry(resource: Resource(t, at: o), part: t.le16(o + 24), refCount: t.le32(o + 26),
                              hash: t.slice(o + 30, 20)))
            o += 50
        }
        entries = list
        xmlData = try file.read(at: xml.offset, count: Int(xml.size))
        images = WIMFile.parseImages(xmlData)
    }

    /// The XML is UTF-16 (little-endian, with a byte-order mark).
    static func parseImages(_ data: Data) -> [Image] {
        var d = data
        if d.count >= 2, d.byte(0) == 0xFF, d.byte(1) == 0xFE { d = d.dropFirst(2) }
        var units: [UInt16] = []
        units.reserveCapacity(d.count / 2)
        var i = d.startIndex
        while i + 1 < d.endIndex {
            units.append(UInt16(d[i]) | UInt16(d[i + 1]) << 8)
            i += 2
        }
        let text = String(decoding: units, as: UTF16.self)
        let reader = ImageXML()
        LiteXML.read(text, into: reader)
        return reader.images
    }

    final class ImageXML: LiteXML.Reader {
        var images: [Image] = []
        private var path: [String] = []
        private var text = ""
        private var current: Image?

        func start(_ name: String, attributes: [String: String]) {
            path.append(name.uppercased())
            text = ""
            if path == ["WIM", "IMAGE"] {
                current = Image(index: Int(attributes["INDEX"] ?? "") ?? images.count + 1, name: "", displayName: "",
                                edition: "", arch: nil, major: nil, minor: nil, build: nil, servicePackBuild: nil)
            }
        }

        func text(_ string: String) { text += string }

        func end(_ name: String) {
            let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if var c = current {
                switch path.dropFirst(2).joined(separator: "/") {
                case "NAME": c.name = value
                case "DISPLAYNAME": c.displayName = value
                case "WINDOWS/EDITIONID": c.edition = value
                case "WINDOWS/ARCH": c.arch = Int(value)
                case "WINDOWS/VERSION/MAJOR": c.major = Int(value)
                case "WINDOWS/VERSION/MINOR": c.minor = Int(value)
                case "WINDOWS/VERSION/BUILD": c.build = Int(value)
                case "WINDOWS/VERSION/SPBUILD": c.servicePackBuild = Int(value)
                default: break
                }
                current = c
                if path == ["WIM", "IMAGE"] {
                    images.append(c)
                    current = nil
                }
            }
            path.removeLast()
            text = ""
        }
    }
}

public enum WIMError: Error, Equatable, CustomStringConvertible {
    case notAWIM
    case damaged(String)
    case unsupported(String)
    case resourceTooBig(Int64)

    public var description: String {
        switch self {
        case .notAWIM: return "It isn't a Windows image (.wim) file."
        case .damaged(let why): return "The Windows image is damaged: \(why)."
        case .unsupported(let why): return "The Windows image has something Sofa Box Imager can't split: \(why)."
        case .resourceTooBig(let n):
            return "One piece of the Windows image is \(ByteSize.text(n)), too big for any FAT32 file: it can't be split to fit."
        }
    }
}

/// Splits a WIM into parts (`install.swm`, `install2.swm`, …) that Windows Setup reads as one, the way Microsoft's
/// `DISM /Split-Image` does: every part has the same GUID, its own number and the count of parts, the resources that
/// fall in it with a table of just those, and the XML; the first part also holds the images' metadata. Resources are
/// copied whole and unchanged, so every SHA-1 in the tables still holds. Nothing is written: each part is a `Layout`.
public enum WIMSplitter {
    /// DISM's own documented size for FAT32 (`/FileSize:3800`, in MB): under FAT32's 4 GB limit with room to spare.
    public static let defaultPartBytes: Int64 = 3800 << 20

    public struct Part {
        public var name: String
        public var layout: Layout
        /// The entries of this part's table (tests read them back).
        public var entries: [WIMFile.Entry]
    }

    /// The parts' file names: "install.swm", "install2.swm", "install3.swm"…
    public static func partName(_ base: String, _ n: Int) -> String { n == 1 ? "\(base).swm" : "\(base)\(n).swm" }

    public static func split(_ file: RandomAccess, wim: WIMFile, base: String = "install",
                             partBytes: Int64 = defaultPartBytes) throws -> [Part] {
        guard wim.totalParts <= 1 else { throw WIMError.unsupported("it's already a part of a split image") }
        // A unit is what must stay in one part: a plain resource, or a solid resource with the files inside it.
        struct Unit {
            var entries: [Int]          // indexes into wim.entries
            var resource: WIMFile.Resource?   // what's copied (nil: nothing, a file with no bytes)
            var bytes: Int64 { resource?.size ?? 0 }
        }
        var metadata: [Int] = []
        var units: [Unit] = []
        var i = 0
        let all = wim.entries
        while i < all.count {
            let e = all[i]
            if e.isSolid {
                // Solid resources come first in a run, then the files inside them.
                var u = Unit(entries: [], resource: nil)
                var resources: [WIMFile.Resource] = []
                while i < all.count, all[i].isSolidResource {
                    u.entries.append(i)
                    resources.append(all[i].resource)
                    i += 1
                }
                while i < all.count, all[i].isSolid, !all[i].isSolidResource {
                    u.entries.append(i)
                    i += 1
                }
                guard !resources.isEmpty else { throw WIMError.unsupported("a solid file outside any solid resource") }
                let start = resources.map(\.offset).min()!
                let end = resources.map { $0.offset + $0.size }.max()!
                u.resource = WIMFile.Resource(size: end - start, flags: 0, offset: start, originalSize: 0)
                units.append(u)
                continue
            }
            if e.isMetadata {
                metadata.append(i)
            } else if e.resource.flags & WIMFile.Resource.flagFree == 0 {
                units.append(Unit(entries: [i], resource: e.resource.size > 0 ? e.resource : nil))
            }
            i += 1
        }
        for u in units {
            if let r = u.resource, r.offset < 0 || r.offset + r.size > file.size {
                throw WIMError.damaged("a resource reaches past the end of the file")
            }
        }
        // Files in the order they're in the file, as DISM keeps them.
        units.sort { ($0.resource?.offset ?? -1) < ($1.resource?.offset ?? -1) }
        let xmlBytes = Int64(wim.xmlData.count)
        let fixed = Int64(WIMFile.headerSize) + xmlBytes
        let metaBytes = metadata.reduce(Int64(0)) { $0 + all[$1].resource.size + Int64(WIMFile.entrySize) }
        guard fixed + metaBytes < partBytes else { throw WIMError.resourceTooBig(metaBytes) }

        // Fill parts in order; a unit that doesn't fit starts the next part.
        var plan: [[Int]] = [[]]                       // unit indexes per part
        var used = fixed + metaBytes
        for (k, u) in units.enumerated() {
            let need = u.bytes + Int64(u.entries.count * WIMFile.entrySize)
            if fixed + need > partBytes { throw WIMError.resourceTooBig(u.bytes) }
            if used + need > partBytes {                // a fresh part always has room: fixed + need fits
                plan.append([])
                used = fixed
            }
            plan[plan.count - 1].append(k)
            used += need
        }
        let total = plan.count
        guard total <= Int(UInt16.max) else { throw WIMError.unsupported("too many parts") }

        var parts: [Part] = []
        for (p, unitIndexes) in plan.enumerated() {
            let number = UInt16(p + 1)
            var layout = Layout()
            layout.append(Data(count: WIMFile.headerSize))       // replaced below
            var table: [WIMFile.Entry] = []
            var bootMeta = WIMFile.Resource.empty
            if number == 1 {
                for (n, m) in metadata.enumerated() {
                    var e = all[m]
                    let at = layout.length
                    layout.append(.copy(file, offset: e.resource.offset, length: e.resource.size))
                    e.resource.offset = at
                    e.part = 1
                    table.append(e)
                    if wim.bootIndex != 0, n + 1 == Int(wim.bootIndex) { bootMeta = e.resource }
                }
            }
            for k in unitIndexes {
                let u = units[k]
                let at = layout.length
                if let r = u.resource { layout.append(.copy(file, offset: r.offset, length: r.size)) }
                for idx in u.entries {
                    var e = all[idx]
                    e.part = number
                    // Plain resources and solid resources move; files inside a solid resource keep their place in it.
                    if !e.isSolid || e.isSolidResource, let r = u.resource {
                        e.resource.offset = at + (e.resource.offset - r.offset)
                    }
                    table.append(e)
                }
            }
            let tableAt = layout.length
            var tableData = Data()
            for e in table { tableData.append(e.bytes) }
            layout.append(tableData)
            let xmlAt = layout.length
            layout.append(wim.xmlData)

            var h = wim.header
            h.put32(wim.flags | WIMFile.flagSpanned, at: 0x10)
            h.put16(number, at: 0x28)
            h.put16(UInt16(total), at: 0x2A)
            var t = wim.table
            t.offset = tableAt
            t.size = Int64(tableData.count)
            t.originalSize = Int64(tableData.count)
            h.replaceSubrange(0x30..<0x48, with: t.bytes)
            var x = wim.xml
            x.offset = xmlAt
            x.size = xmlBytes
            x.originalSize = xmlBytes
            h.replaceSubrange(0x48..<0x60, with: x.bytes)
            h.replaceSubrange(0x60..<0x78, with: bootMeta.bytes)
            h.replaceSubrange(0x7C..<0x94, with: WIMFile.Resource.empty.bytes)   // no integrity table in the parts
            var final = Layout()
            final.append(h)
            for piece in layout.pieces.dropFirst() { final.append(piece) }
            parts.append(Part(name: partName(base, p + 1), layout: final, entries: table))
        }
        return parts
    }
}

/// A layout read as a file (a split part, which the FAT32 builder copies like any other file).
public final class LayoutFile: RandomAccess {
    public let layout: Layout
    public var size: Int64 { layout.length }
    public init(_ layout: Layout) { self.layout = layout }
    public func read(at offset: Int64, count: Int) throws -> Data { try layout.read(at: offset, count: count) }
}
