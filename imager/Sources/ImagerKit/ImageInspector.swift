import Foundation

/// What an image file is, and so how it can go on a stick. Read from the file's first sectors only (and, for a
/// Windows ISO, its UDF folders and its WIM's header and XML).
public enum ImageKind: Equatable {
    /// An ISO that's also a disk (an "isohybrid": a partition table in its first sectors, as every Linux ISO has now):
    /// written to the stick whole, byte for byte.
    case hybridISO(partitions: PartitionTable)
    /// A disk image (`.img`): a partition table, or a boot sector, and no ISO 9660. Written whole.
    case diskImage(partitions: PartitionTable)
    /// A packed disk image (`.img.xz`, as Raspberry Pi OS comes): unpacked as it's written. `unpacked` is its size.
    case packedImage(unpacked: Int64)
    /// Microsoft's Windows installer (UDF, BOOTMGR, `sources/install.wim`...): not written whole (it would start
    /// nothing from a stick) but rebuilt as a FAT32 stick by `WindowsStick`.
    case windows(WindowsMedia)
    /// An ISO with no partition table that isn't Windows: it starts a PC from a DVD only, so it's refused for a stick.
    case discOnly
    /// Not an image Sofa Box Imager knows.
    case unknown

    public enum PartitionTable: String, Equatable {
        case mbr, gpt, bootSector
    }

    /// Whether it's written to the stick as it is (or unpacked as it is).
    public var writtenWhole: Bool {
        switch self {
        case .hybridISO, .diskImage, .packedImage: return true
        default: return false
        }
    }

    /// In the owner's words.
    public var summary: String {
        switch self {
        case .hybridISO(let p):
            return "An ISO that's also a disk (\(p == .gpt ? "GPT" : "MBR")): written to the stick whole."
        case .diskImage(let p):
            return p == .bootSector ? "A disk image with a boot sector: written whole."
                : "A disk image (\(p == .gpt ? "GPT" : "MBR")): written whole."
        case .packedImage(let n): return "A packed disk image (.xz, \(ByteSize.text(n)) unpacked): unpacked as it's written."
        case .windows(let w): return w.summary
        case .discOnly:
            return "An ISO with no partition table: it starts a PC from a DVD only, not from a stick written with it."
        case .unknown:
            return "Not a disk image Sofa Box Imager knows: no partition table, no boot sector, no ISO 9660 or UDF."
        }
    }
}

public enum ImageInspector {
    /// Looks at a file. Throws only when it can't be read; a file that isn't an image is `.unknown`.
    public static func inspect(_ file: RandomAccess, name: String = "") throws -> ImageKind {
        let head = try file.read(at: 0, count: Int(min(file.size, 65536)))
        if head.count >= 6, head.prefix(6) == Data([0xFD, 0x37, 0x7A, 0x58, 0x5A, 0x00]) {
            return .packedImage(unpacked: try XZIndex.unpackedSize(file))
        }
        let table = partitionTable(head)
        let iso = hasISO9660(file) || UDFReader.isUDF(file)
        if iso {
            if let t = table, t != .bootSector { return .hybridISO(partitions: t) }
            if UDFReader.isUDF(file), let w = try? WindowsMedia.detect(file) { return .windows(w) }
            return .discOnly
        }
        if let t = table { return .diskImage(partitions: t) }
        return .unknown
    }

    /// MBR (55 AA and at least one partition), GPT ("EFI PART" at sector 1), or a bare boot sector (55 AA only).
    public static func partitionTable(_ head: Data) -> ImageKind.PartitionTable? {
        guard head.count >= 512 else { return nil }
        if head.count >= 520, head.slice(512, 8) == Data("EFI PART".utf8) { return .gpt }
        guard head.byte(510) == 0x55, head.byte(511) == 0xAA else { return nil }
        for i in 0..<4 {
            let e = head.slice(446 + i * 16, 16)
            let status = e.byte(0)
            let type = e.byte(4)
            let sectors = e.le32(12)
            // An isohybrid's first partition may be of type 0 ("empty"), marked active, spanning the ISO.
            if sectors > 0, status == 0 || status == 0x80, type != 0 || status == 0x80 { return type == 0xEE ? .gpt : .mbr }
        }
        return .bootSector
    }

    /// "CD001" in the primary volume descriptor at 32 KB.
    public static func hasISO9660(_ file: RandomAccess) -> Bool {
        guard let d = try? file.read(at: 32768, count: 8) else { return false }
        return d.byte(0) == 1 && d.slice(1, 5) == Data("CD001".utf8)
    }
}

/// The size of a packed `.xz` file once unpacked, from the index each xz stream ends with (no unpacking).
public enum XZIndex {
    public static func unpackedSize(_ file: RandomAccess) throws -> Int64 {
        var end = file.size
        var total: Int64 = 0
        var streams = 0
        while end > 0 {
            // Stream padding (zeros, in fours) between streams.
            while end >= 4, try file.read(at: end - 4, count: 4) == Data(count: 4) { end -= 4 }
            guard end >= 24 else { throw XZError.corrupt }
            let footer = try file.read(at: end - 12, count: 12)
            guard footer.slice(10, 2) == Data("YZ".utf8) else { throw XZError.corrupt }
            let backward = (Int64(footer.le32(4)) + 1) * 4
            let indexStart = end - 12 - backward
            guard indexStart >= 12 else { throw XZError.corrupt }
            let index = try file.read(at: indexStart, count: Int(backward))
            guard index.byte(0) == 0 else { throw XZError.corrupt }
            var o = 1
            func vli() throws -> Int64 {
                var v: Int64 = 0
                var shift: Int64 = 0
                while true {
                    guard o < index.count, shift < 63 else { throw XZError.corrupt }
                    let b = index.byte(o)
                    o += 1
                    v |= Int64(b & 0x7F) << shift
                    if b & 0x80 == 0 { return v }
                    shift += 7
                }
            }
            let records = try vli()
            var unpadded: Int64 = 0
            for _ in 0..<records {
                let u = try vli()
                unpadded += (u + 3) / 4 * 4
                total += try vli()
            }
            // The stream: its 12-byte header, its blocks, the index and the footer.
            let start = indexStart - unpadded - 12
            guard start >= 0 else { throw XZError.corrupt }
            let header = try file.read(at: start, count: 6)
            guard header == Data([0xFD, 0x37, 0x7A, 0x58, 0x5A, 0x00]) else { throw XZError.corrupt }
            end = start
            streams += 1
            guard streams < 10_000 else { throw XZError.corrupt }
        }
        return total
    }
}
