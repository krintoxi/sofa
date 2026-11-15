import Foundation

public enum FATError: Error, Equatable, CustomStringConvertible {
    case notFAT
    case damaged(String)
    case tooSmall(need: Int64, have: Int64)
    case fileTooBig(String, Int64)
    case badName(String)
    case sectorSize(Int)

    public var description: String {
        switch self {
        case .notFAT: return "It isn't a FAT file system."
        case .damaged(let why): return "The FAT image is damaged: \(why)."
        case .tooSmall(let need, let have):
            return "The stick holds \(ByteSize.text(have)); this needs \(ByteSize.text(need))."
        case .fileTooBig(let name, let n): return "\(name) is \(ByteSize.text(n)), more than a FAT32 file can hold (4 GB)."
        case .badName(let n): return "A file is named “\(DiskPolicy.printable(n))”, which FAT32 can't hold."
        case .sectorSize(let n): return "Its sectors are \(n) bytes; a Windows stick is made on 512-byte sectors."
        }
    }
}

/// Reads files from a small FAT12 or FAT16 image: the UEFI boot image inside a Windows ISO (`efisys.bin`), which for
/// Windows 7 is the only place its UEFI loader (`EFI/BOOT/BOOTX64.EFI`) is kept outside a WIM.
public struct FATImage {
    let file: RandomAccess
    let bytesPerSector: Int64
    let sectorsPerCluster: Int64
    let firstFAT: Int64
    let rootStart: Int64
    let rootEntries: Int
    let dataStart: Int64
    let fatBits: Int
    let clusterCount: Int64

    public init(_ file: RandomAccess) throws {
        self.file = file
        guard file.size >= 512 else { throw FATError.notFAT }
        let b = try file.read(at: 0, count: 512)
        let bps = Int64(b.le16(11))
        let spc = Int64(b.byte(13))
        let reserved = Int64(b.le16(14))
        let fats = Int64(b.byte(16))
        let roots = Int(b.le16(17))
        let total16 = Int64(b.le16(19))
        let fatSize = Int64(b.le16(22))
        let total32 = Int64(b.le32(32))
        guard [512, 1024, 2048, 4096].contains(bps), spc > 0, spc & (spc - 1) == 0, reserved > 0, fats > 0,
              fatSize > 0, b.byte(510) == 0x55, b.byte(511) == 0xAA else {
            throw FATError.notFAT
        }
        bytesPerSector = bps
        sectorsPerCluster = spc
        firstFAT = reserved * bps
        rootStart = (reserved + fats * fatSize) * bps
        rootEntries = roots
        let rootSectors = (Int64(roots) * 32 + bps - 1) / bps
        dataStart = rootStart + rootSectors * bps
        let total = total16 != 0 ? total16 : total32
        clusterCount = (total - reserved - fats * fatSize - rootSectors) / spc
        fatBits = clusterCount < 4085 ? 12 : 16
        guard clusterCount > 0, Int64(file.size) >= dataStart else { throw FATError.damaged("its sizes don't add up") }
    }

    var clusterBytes: Int64 { bytesPerSector * sectorsPerCluster }

    func next(_ cluster: Int64) throws -> Int64 {
        if fatBits == 12 {
            let at = firstFAT + cluster + cluster / 2
            let v = Int64(try file.le16(at))
            let e = cluster & 1 == 0 ? v & 0xFFF : v >> 4
            return e >= 0xFF8 ? -1 : e
        }
        let e = Int64(try file.le16(firstFAT + cluster * 2))
        return e >= 0xFFF8 ? -1 : e
    }

    struct Found {
        var cluster: Int64
        var size: Int64
        var isDirectory: Bool
    }

    /// Entries of a folder (the root when `cluster` is nil), long names read where they're given.
    func list(_ cluster: Int64?) throws -> [(String, Found)] {
        var raw = Data()
        if let c = cluster {
            var cl = c
            var hops = 0
            while cl >= 2 && cl < clusterCount + 2 {
                raw.append(try file.read(at: dataStart + (cl - 2) * clusterBytes, count: Int(clusterBytes)))
                cl = try next(cl)
                hops += 1
                if hops > 65536 { throw FATError.damaged("a loop in a folder") }
            }
        } else {
            raw = try file.read(at: rootStart, count: rootEntries * 32)
        }
        var out: [(String, Found)] = []
        var long: [UInt16] = []
        var o = 0
        while o + 32 <= raw.count {
            let e = raw.slice(o, 32)
            o += 32
            let first = e.byte(0)
            if first == 0 { break }
            if first == 0xE5 { long = []; continue }
            let attr = e.byte(11)
            if attr == 0x0F {
                var part: [UInt16] = []
                for k in [1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30] { part.append(e.le16(k)) }
                long = part + long
                continue
            }
            if attr & 0x08 != 0 { long = []; continue }               // the volume's label
            var name: String
            let units = long.prefix { $0 != 0 && $0 != 0xFFFF }
            if !units.isEmpty {
                name = String(decoding: Array(units), as: UTF16.self)
            } else {
                let base = String(decoding: e.slice(0, 8), as: UTF8.self).trimmingCharacters(in: .whitespaces)
                let ext = String(decoding: e.slice(8, 3), as: UTF8.self).trimmingCharacters(in: .whitespaces)
                name = ext.isEmpty ? base : base + "." + ext
            }
            long = []
            if name == "." || name == ".." { continue }
            let cl = Int64(e.le16(26)) | (fatBits == 32 ? Int64(e.le16(20)) << 16 : 0)
            out.append((name, Found(cluster: cl, size: Int64(e.le32(28)), isDirectory: attr & 0x10 != 0)))
        }
        return out
    }

    /// A file's bytes by path ("EFI/BOOT/BOOTX64.EFI"), ignoring case; nil when it isn't there.
    public func file(_ path: String) throws -> RandomAccess? {
        var cluster: Int64? = nil
        let parts = path.split(separator: "/").map(String.init)
        for (i, part) in parts.enumerated() {
            guard let hit = try list(cluster).first(where: { $0.0.compare(part, options: .caseInsensitive) == .orderedSame })
            else { return nil }
            if i == parts.count - 1 {
                guard !hit.1.isDirectory else { return nil }
                var extents: [ExtentRandomAccess.Extent] = []
                var cl = hit.1.cluster
                var left = hit.1.size
                while left > 0 && cl >= 2 {
                    let n = min(left, clusterBytes)
                    extents.append(ExtentRandomAccess.Extent(offset: dataStart + (cl - 2) * clusterBytes, length: n))
                    left -= n
                    cl = try next(cl)
                }
                guard left == 0 else { throw FATError.damaged("\(path) ends early") }
                return ExtentRandomAccess(base: file, extents: extents, size: hit.1.size)
            }
            guard hit.1.isDirectory else { return nil }
            cluster = hit.1.cluster
        }
        return nil
    }
}

/// A file or folder to put on a FAT32 stick.
public final class FATItem {
    public let name: String
    public let isDirectory: Bool
    public let contents: RandomAccess?
    public let modified: Date?
    public internal(set) var children: [FATItem] = []

    public static func folder(_ name: String, modified: Date? = nil, _ children: [FATItem] = []) -> FATItem {
        let f = FATItem(name: name, isDirectory: true, contents: nil, modified: modified)
        f.children = children
        return f
    }

    public static func file(_ name: String, _ contents: RandomAccess, modified: Date? = nil) -> FATItem {
        FATItem(name: name, isDirectory: false, contents: contents, modified: modified)
    }

    init(name: String, isDirectory: Bool, contents: RandomAccess?, modified: Date?) {
        self.name = name
        self.isDirectory = isDirectory
        self.contents = contents
        self.modified = modified
    }

    public func add(_ item: FATItem) { children.append(item) }

    public func child(_ name: String) -> FATItem? {
        children.first { $0.name.compare(name, options: .caseInsensitive) == .orderedSame }
    }

    var size: Int64 { contents?.size ?? 0 }
}

/// A whole stick, laid out but not written: an MBR with one active FAT32 partition from the first megabyte to the end of
/// the disk, the FAT32 file system with every file in it in one unbroken run of clusters, and the boot code that starts
/// a BIOS PC from it (`BootCode`). UEFI PCs need nothing more than the FAT32 partition and `EFI/BOOT/BOOTX64.EFI`.
///
/// The layout ends with the last file's last cluster: what lies beyond is free space, and isn't written.
public struct FAT32Stick {
    public static let partitionStart: Int64 = 2048            // sectors: the first megabyte
    public static let sector: Int64 = 512
    public static let maxFile: Int64 = 0xFFFF_FFFF

    public let layout: Layout
    public let clusterBytes: Int64
    public let clusters: Int64
    public let usedClusters: Int64
    /// Where the BIOS loader file (BOOTMGR) starts on the disk, in sectors from the partition, and how many it takes.
    public let loader: (sector: Int64, count: Int64)?
    public let volumeID: UInt32

    /// The smallest disk the items fit on (with the cluster size a disk that size gets).
    public static func needs(_ root: FATItem) -> Int64 {
        let c: Int64 = 32768
        var data: Int64 = c                                          // the root folder
        var count: Int64 = 0
        func walk(_ f: FATItem) {
            for x in f.children {
                count += 1
                if x.isDirectory {
                    data += max(1, (Int64(x.children.count * 3 + 2) * 32 + c - 1) / c) * c
                    walk(x)
                } else {
                    data += (x.size + c - 1) / c * c
                }
            }
        }
        walk(root)
        data += (Int64(root.children.count) * 3 * 32 + c - 1) / c * c
        let clustersNeeded = data / c + 2
        let fat = (clustersNeeded * 4 + 511) / 512 * 512
        return (partitionStart * sector) + 2 * fat + (2 << 20) + data + (16 << 20)
    }

    /// - Parameters:
    ///   - diskBytes: the whole stick's size; `sectorBytes` its sector (512 only).
    ///   - label: the volume's name (up to 11 characters, A–Z, 0–9 and a few others).
    ///   - loaderPath: the file a BIOS PC starts (Windows' `bootmgr`); nil for none (the stick then starts on UEFI only).
    ///   - seed: makes the volume serial number and disk signature (the same seed gives the same stick, byte for byte).
    public init(root: FATItem, diskBytes: Int64, sectorBytes: Int = 512, label: String, loaderPath: String?,
                seed: UInt32) throws {
        guard sectorBytes == 512 else { throw FATError.sectorSize(sectorBytes) }
        let S = FAT32Stick.sector
        let totalSectors = diskBytes / S
        let partSectors = min(totalSectors - FAT32Stick.partitionStart, 0xFFFF_FFFF)
        guard partSectors > 8192 else { throw FATError.tooSmall(need: FAT32Stick.needs(root), have: diskBytes) }

        // The biggest cluster (up to 32 KB) that still leaves FAT32's minimum count of clusters, with room to spare.
        var spc: Int64 = 64
        while spc > 1 && partSectors / spc < 70_000 { spc /= 2 }
        guard partSectors / spc >= 66_000 else { throw FATError.tooSmall(need: 64 << 20, have: diskBytes) }
        let clusterBytes = spc * S

        // Reserved sectors are chosen so the data (cluster 2) begins on a megabyte boundary: flash likes it.
        var reserved: Int64 = 32
        var fatSectors: Int64 = 0
        for _ in 0..<4 {
            let clusterGuess = (partSectors - reserved - 2 * fatSectors) / spc
            fatSectors = ((clusterGuess + 2) * 4 + S - 1) / S
            let dataAt = (reserved + 2 * fatSectors + 2047) / 2048 * 2048
            reserved = max(32, dataAt - 2 * fatSectors)
        }
        let dataSector = reserved + 2 * fatSectors
        let clusters = (partSectors - dataSector) / spc
        guard clusters >= 65_525, (clusters + 2) * 4 <= fatSectors * S else {
            throw FATError.tooSmall(need: FAT32Stick.needs(root), have: diskBytes)
        }

        // Clusters: the root folder, then every folder (breadth first), then every file, BOOTMGR first.
        var next: Int64 = 2
        var plan = Plan()
        func allocate(_ bytes: Int64) -> (first: Int64, count: Int64) {
            let n = max(1, (bytes + clusterBytes - 1) / clusterBytes)
            defer { next += n }
            return (next, n)
        }
        // Folder entries first, so each folder's size is known.
        var folders: [(FATItem, FATItem?)] = [(root, nil)]
        var i = 0
        while i < folders.count {
            for c in folders[i].0.children where c.isDirectory { folders.append((c, folders[i].0)) }
            i += 1
        }
        var entries: [ObjectIdentifier: [DirEntry]] = [:]
        for (f, parent) in folders {
            entries[ObjectIdentifier(f)] = try FAT32Stick.directoryEntries(f, isRoot: parent == nil, label: label)
        }
        for (f, _) in folders {
            let n = entries[ObjectIdentifier(f)]!.reduce(0) { $0 + $1.slots } * 32
            plan.folders[ObjectIdentifier(f)] = allocate(Int64(n))
        }
        var files: [(String, FATItem)] = []
        func collect(_ f: FATItem, _ path: String) {
            for c in f.children {
                let p = path.isEmpty ? c.name : path + "/" + c.name
                if c.isDirectory { collect(c, p) } else { files.append((p, c)) }
            }
        }
        collect(root, "")
        if let lp = loaderPath, let k = files.firstIndex(where: { $0.0.compare(lp, options: .caseInsensitive) == .orderedSame }) {
            files.insert(files.remove(at: k), at: 0)
        }
        for (p, f) in files {
            guard f.size <= FAT32Stick.maxFile else { throw FATError.fileTooBig(p, f.size) }
            if f.size > 0 { plan.files[ObjectIdentifier(f)] = allocate(f.size) }
        }
        let usedClusters = next - 2
        guard next - 2 <= clusters else { throw FATError.tooSmall(need: FAT32Stick.needs(root), have: diskBytes) }

        var loader: (sector: Int64, count: Int64)?
        if let lp = loaderPath, let hit = files.first(where: { $0.0.compare(lp, options: .caseInsensitive) == .orderedSame }),
           let at = plan.files[ObjectIdentifier(hit.1)] {
            loader = (dataSector + (at.first - 2) * spc, (hit.1.size + S - 1) / S)
        }
        let volumeID = seed == 0 ? 0x5B0F_A5E1 : seed

        // Lay it out.
        var out = Layout()
        out.append(BootCode.mbr(diskSignature: volumeID ^ 0x50FA_B0C5, partitionStart: UInt32(FAT32Stick.partitionStart),
                                partitionSectors: UInt32(partSectors)))
        out.pad(to: FAT32Stick.partitionStart * S)
        let vbr = BootCode.fat32BootSector(totalSectors: UInt32(partSectors), sectorsPerCluster: UInt8(spc),
                                           reservedSectors: UInt16(reserved), fatSectors: UInt32(fatSectors),
                                           hiddenSectors: UInt32(FAT32Stick.partitionStart), volumeID: volumeID,
                                           label: FAT32Stick.labelBytes(label), loader: loader)
        let free = clusters - usedClusters
        let info = FAT32Stick.fsInfo(free: UInt32(free), nextFree: UInt32(next))
        let base = FAT32Stick.partitionStart * S
        out.append(vbr)
        out.append(info)
        out.pad(to: base + 6 * S)
        out.append(vbr)
        out.append(info)
        out.pad(to: base + reserved * S)
        // The two FATs: a chain for each folder and file, everything else free.
        var fat = Data(count: Int((next) * 4))
        fat.put32(0x0FFF_FFF8, at: 0)
        fat.put32(0x0FFF_FFFF, at: 4)
        for run in plan.folders.values.map({ $0 }) + plan.files.values.map({ $0 }) {
            for k in 0..<run.count {
                let c = run.first + k
                fat.put32(k == run.count - 1 ? 0x0FFF_FFFF : UInt32(c + 1), at: Int(c * 4))
            }
        }
        for _ in 0..<2 {
            out.append(fat)
            out.append(.zeros(fatSectors * S - Int64(fat.count)))
        }
        // Data, cluster by cluster in allocation order.
        let order = (plan.folders.map { ($0.value.first, Either.folder($0.key)) }
                     + plan.files.map { ($0.value.first, Either.file($0.key)) }).sorted { $0.0 < $1.0 }
        var byID: [ObjectIdentifier: FATItem] = [:]
        for (f, _) in folders { byID[ObjectIdentifier(f)] = f }
        for (_, f) in files { byID[ObjectIdentifier(f)] = f }
        let parentOf: [ObjectIdentifier: FATItem?] = Dictionary(uniqueKeysWithValues: folders.map { (ObjectIdentifier($0.0), $0.1) })
        for (first, what) in order {
            out.pad(to: base + (dataSector + (first - 2) * spc) * S)
            switch what {
            case .folder(let id):
                let f = byID[id]!
                let parent = parentOf[id] ?? nil
                let me = plan.folders[id]!.first
                let up: Int64 = parent.map { $0 === root ? 0 : plan.folders[ObjectIdentifier($0)]!.first } ?? 0
                var d = Data()
                for e in entries[id]! {
                    let cluster: Int64
                    switch e.target {
                    case .dot: cluster = me
                    case .dotdot: cluster = up
                    case .label: cluster = 0
                    case .item(let item):
                        cluster = item.isDirectory ? plan.folders[ObjectIdentifier(item)]!.first
                            : (plan.files[ObjectIdentifier(item)]?.first ?? 0)
                    }
                    d.append(e.bytes(cluster: UInt32(cluster)))
                }
                let run = plan.folders[id]!
                d.append(Data(count: Int(run.count * clusterBytes) - d.count))
                out.append(d)
                _ = f
            case .file(let id):
                let f = byID[id]!
                out.append(file: f.contents!, roundedTo: clusterBytes)
            }
        }
        // To the end of the last cluster (a stick with no files ends after its root folder).
        layout = out
        self.clusterBytes = clusterBytes
        self.clusters = clusters
        self.usedClusters = usedClusters
        self.loader = loader
        self.volumeID = volumeID
    }

    enum Either { case folder(ObjectIdentifier), file(ObjectIdentifier) }

    struct Plan {
        var folders: [ObjectIdentifier: (first: Int64, count: Int64)] = [:]
        var files: [ObjectIdentifier: (first: Int64, count: Int64)] = [:]
    }

    // MARK: folder entries

    struct DirEntry {
        enum Target { case dot, dotdot, label, item(FATItem) }
        var target: Target
        var short: [UInt8]                     // 11 bytes
        var long: String?
        var attr: UInt8
        var size: UInt32
        var date: (UInt16, UInt16)             // DOS date, time

        var slots: Int { 1 + (long.map { ($0.utf16.count + 12) / 13 } ?? 0) }

        func bytes(cluster: UInt32) -> Data {
            var out = Data()
            if let name = long {
                let units = Array(name.utf16)
                let n = (units.count + 12) / 13
                let sum = FAT32Stick.checksum(short)
                for k in stride(from: n, through: 1, by: -1) {
                    var e = Data(count: 32)
                    e[0] = UInt8(k) | (k == n ? 0x40 : 0)
                    e[11] = 0x0F
                    e[13] = sum
                    let slots = [1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30]
                    for (j, at) in slots.enumerated() {
                        let idx = (k - 1) * 13 + j
                        let v: UInt16 = idx < units.count ? units[idx] : (idx == units.count ? 0x0000 : 0xFFFF)
                        e.put16(v, at: at)
                    }
                    out.append(e)
                }
            }
            var e = Data(count: 32)
            e.put(short, at: 0)
            e[11] = attr
            e.put16(date.1, at: 14)              // created
            e.put16(date.0, at: 16)
            e.put16(date.0, at: 18)              // last opened
            e.put16(UInt16(cluster >> 16), at: 20)
            e.put16(date.1, at: 22)              // written
            e.put16(date.0, at: 24)
            e.put16(UInt16(cluster & 0xFFFF), at: 26)
            e.put32(size, at: 28)
            out.append(e)
            return out
        }
    }

    static func checksum(_ short: [UInt8]) -> UInt8 {
        var sum: UInt8 = 0
        for b in short { sum = ((sum & 1) << 7) &+ (sum >> 1) &+ b }
        return sum
    }

    static func dosDate(_ d: Date?) -> (UInt16, UInt16) {
        guard let d else { return (0x5B6E, 0) }            // 2025-11-14
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(secondsFromGMT: 0)!
        let c = cal.dateComponents([.year, .month, .day, .hour, .minute, .second], from: d)
        // One part at a time: older compilers time out on the whole expression.
        let year: Int = max(1980, min(2107, c.year ?? 1980)) - 1980
        let month: Int = c.month ?? 1
        let day: Int = c.day ?? 1
        let hour: Int = c.hour ?? 0
        let minute: Int = c.minute ?? 0
        let second: Int = c.second ?? 0
        let date: Int = (year << 9) | (month << 5) | day
        let time: Int = (hour << 11) | (minute << 5) | (second / 2)
        return (UInt16(date), UInt16(time))
    }

    static let shortChars: Set<UInt8> = Set(Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'()-@^_`{}~".utf8))

    /// The name as an 8.3 short name when it is one exactly (upper case, valid characters), else nil.
    static func exactShort(_ name: String) -> [UInt8]? {
        let parts = name.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count <= 2 else { return nil }
        let base = Array(parts[0].utf8)
        let ext = parts.count == 2 ? Array(parts[1].utf8) : []
        guard !base.isEmpty, base.count <= 8, ext.count <= 3, parts.count == 1 || !ext.isEmpty,
              (base + ext).allSatisfy({ shortChars.contains($0) }) else { return nil }
        return base + Array(repeating: 0x20, count: 8 - base.count) + ext + Array(repeating: 0x20, count: 3 - ext.count)
    }

    /// A short name for a long one ("api-ms-win-core.dll" -> "API-MS~1DLL"), unique in its folder.
    static func shortName(for name: String, taken: inout Set<[UInt8]>) -> [UInt8] {
        if let exact = exactShort(name.uppercased()), !taken.contains(exact) {
            taken.insert(exact)
            return exact
        }
        let upper = name.uppercased()
        let dot = upper.lastIndex(of: ".")
        let baseText = dot.map { String(upper[..<$0]) } ?? upper
        let extText = dot.map { String(upper[upper.index(after: $0)...]) } ?? ""
        func clean(_ s: String) -> [UInt8] {
            s.unicodeScalars.compactMap { u -> UInt8? in
                if u == " " || u == "." { return nil }
                guard u.isASCII else { return UInt8(ascii: "_") }
                let b = UInt8(u.value)
                return shortChars.contains(b) ? b : UInt8(ascii: "_")
            }
        }
        let base = clean(baseText)
        let ext = Array(clean(extText).prefix(3))
        for n in 1..<1_000_000 {
            let tail = Array("~\(n)".utf8)
            let keep = max(1, min(base.count, 8 - tail.count))
            let b = Array(base.prefix(keep)) + tail
            let s = b + Array(repeating: 0x20, count: 8 - b.count) + ext + Array(repeating: 0x20, count: 3 - ext.count)
            if !taken.contains(s) {
                taken.insert(s)
                return s
            }
        }
        return Array(repeating: UInt8(ascii: "_"), count: 11)
    }

    static func directoryEntries(_ f: FATItem, isRoot: Bool, label: String) throws -> [DirEntry] {
        var out: [DirEntry] = []
        var taken: Set<[UInt8]> = []
        let date = dosDate(f.modified)
        if isRoot {
            out.append(DirEntry(target: .label, short: labelBytes(label), long: nil, attr: 0x08, size: 0, date: date))
        } else {
            out.append(DirEntry(target: .dot, short: Array(".          ".utf8), long: nil, attr: 0x10, size: 0, date: date))
            out.append(DirEntry(target: .dotdot, short: Array("..         ".utf8), long: nil, attr: 0x10, size: 0, date: date))
        }
        var names: Set<String> = []
        for c in f.children {
            guard !c.name.isEmpty, c.name.utf16.count <= 255, c.name != ".", c.name != "..",
                  !c.name.contains(where: { "\\/:*?\"<>|".contains($0) || $0.asciiValue.map { $0 < 0x20 } == true }) else {
                throw FATError.badName(c.name)
            }
            guard names.insert(c.name.uppercased()).inserted else { throw FATError.badName(c.name) }
            guard c.size <= FAT32Stick.maxFile else { throw FATError.fileTooBig(c.name, c.size) }
            let short = shortName(for: c.name, taken: &taken)
            let needsLong = exactShort(c.name) != short
            out.append(DirEntry(target: .item(c), short: short, long: needsLong ? c.name : nil,
                                attr: c.isDirectory ? 0x10 : 0x20, size: c.isDirectory ? 0 : UInt32(c.size),
                                date: dosDate(c.modified)))
        }
        return out
    }

    static func labelBytes(_ label: String) -> [UInt8] {
        let s = label.uppercased().utf8.map { shortChars.contains($0) || $0 == 0x20 ? $0 : UInt8(ascii: "_") }
        let b = Array(s.prefix(11))
        return b + Array(repeating: 0x20, count: 11 - b.count)
    }

    static func fsInfo(free: UInt32, nextFree: UInt32) -> Data {
        var d = Data(count: 512)
        d.put32(0x4161_5252, at: 0)
        d.put32(0x6141_7272, at: 484)
        d.put32(free, at: 488)
        d.put32(nextFree, at: 492)
        d.put32(0xAA55_0000, at: 508)
        return d
    }
}
