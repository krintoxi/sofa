import Foundation
@testable import ImagerKit
import XCTest

/// The test disks macOS's own tools make: Windows-like ISOs and two others by `hdiutil makehybrid` (UDF 1.02, as
/// Microsoft's are, and ISO 9660), and a FAT12 `efisys.bin` by `newfs_msdos`. They're made once, on a Mac, by
/// `scripts/disk-fixtures.sh`, and committed under `Fixtures/disks` as skeletons: each disk exactly as the tool wrote
/// it, with the contents of the files the tests make themselves zeroed, so it packs small, and a map of where those
/// contents go (`disks.json`). The map is found by looking for each file's bytes in the disk, not with our UDF reader.
/// Put back, a disk's SHA-256 must be the one recorded when it was made: every system's tests read exactly the bytes
/// macOS's tools wrote. On the Mac, `DiskFixtureTests` also makes them afresh and checks they read the same.
enum DiskFixture {
    struct Entry: Codable, Equatable {
        var size: Int
        var sha256: String
        var ranges: [Piece]
    }

    /// Bytes put back at `offset`: a file of the disk's folder ("tree:" and its path) or the Windows 7 boot image's
    /// loader ("efisys-loader").
    struct Piece: Codable, Equatable {
        var offset: Int
        var length: Int
        var source: String
    }

    static func manifest(in folder: URL? = nil) throws -> [String: Entry] {
        let data = try folder.map { try Data(contentsOf: $0.appendingPathComponent("disks.json")) }
            ?? Fixture.data("disks/disks.json")
        return try JSONDecoder().decode([String: Entry].self, from: data)
    }

    /// The disk called `name`, its skeleton filled from `tree` (the folder it was made from).
    static func bytes(_ name: String, tree: URL?, from folder: URL? = nil) throws -> Data {
        guard let entry = try manifest(in: folder)[name] else { throw failure("no test disk called \(name)") }
        let packed = try folder.map { try Data(contentsOf: $0.appendingPathComponent(name + ".skel.xz")) }
            ?? Fixture.data("disks/\(name).skel.xz")
        var disk = Data()
        let unpacker = try XZUnpacker()
        try unpacker.feed(packed) { disk.append(contentsOf: $0) }
        try unpacker.finish { disk.append(contentsOf: $0) }
        guard disk.count == entry.size else { throw failure("\(name): \(disk.count) bytes, not \(entry.size)") }
        // Looked up as Swift strings, which match a name however its accents are encoded: macOS lists "ñ" as "n" and a
        // combining tilde, Linux keeps it as it was made.
        let treeFiles = try tree.map { try files(in: $0) } ?? [:]
        for p in entry.ranges {
            let content = try source(p.source, treeFiles: treeFiles)
            guard content.count == p.length else { throw failure("\(name): \(p.source) is \(content.count) bytes, not \(p.length)") }
            disk.replaceSubrange(p.offset..<p.offset + p.length, with: content)
        }
        guard sha256(disk) == entry.sha256 else {
            throw failure("\(name): put back, it isn't the disk macOS made (its folder's files changed?)")
        }
        return disk
    }

    /// The same, as a file (for `FileRandomAccess`).
    static func file(_ name: String, tree: URL?) throws -> URL {
        let url = try scratch("disk").appendingPathComponent(name + ".img")
        try bytes(name, tree: tree).write(to: url)
        return url
    }

    static func source(_ s: String, treeFiles: [String: Data]) throws -> Data {
        if s == "efisys-loader" { return FakeWindowsISO.efisysLoader }
        if s.hasPrefix("tree:"), let d = treeFiles[String(s.dropFirst(5))] { return d }
        throw failure("can't make \(s)")
    }

    /// A skeleton of `disk`: each of `contents` that's 64 bytes or more and found exactly once in it is zeroed, and
    /// its place recorded.
    static func skeleton(of disk: Data, contents: [(source: String, data: Data)]) -> (Data, [Piece]) {
        var bones = disk
        var pieces: [Piece] = []
        for c in contents where c.data.count >= 64 {
            guard let hit = disk.range(of: c.data),
                  disk.range(of: c.data, in: hit.upperBound..<disk.endIndex) == nil else { continue }
            pieces.append(Piece(offset: hit.lowerBound, length: c.data.count, source: c.source))
            bones.replaceSubrange(hit, with: Data(count: c.data.count))
        }
        return (bones, pieces.sorted { $0.offset < $1.offset })
    }

    static func failure(_ s: String) -> NSError {
        NSError(domain: "DiskFixture", code: 1, userInfo: [NSLocalizedDescriptionKey: s])
    }
}

/// Windows installer ISOs made up for the tests: the folders and files Microsoft's have, with made-up contents (made
/// here, the same every time), in the UDF image macOS's own `hdiutil makehybrid` made of that folder.
enum FakeWindowsISO {
    static let longNames = ["api-ms-win-downlevel-shlwapi-l1-1-0.dll", "Microsoft-Windows-Setup.Resources.mui",
                            "a name with spaces.txt", "ñandú.inf", "UPPER.TXT", "lower.txt", "MiXeD.Cab", "x.y.z.dat"]
    static let volumeName = "CCCOMA_X64FRE_EN-US_DV9"
    /// The UEFI loader inside Windows 7's boot image.
    static let efisysLoader = noise(98_765, seed: 17)

    enum Variant: String, CaseIterable {
        case eleven = "win11", ten = "win10", seven = "win7", arm64 = "win11-arm64", elevenWithUnattend = "win11-unattend"
    }

    /// The folder it's made from (kept, to compare against) and the ISO.
    struct Made {
        let folder: URL
        let iso: URL
    }

    /// The committed ISO (see `DiskFixture`), with its folder.
    static func make(_ v: Variant) throws -> Made {
        let tree = try tree(v, efisys: { try efisys() })
        return Made(folder: tree, iso: try DiskFixture.file(v.rawValue, tree: tree))
    }

    /// Made afresh by macOS's hdiutil (and, for Windows 7, newfs_msdos): only on a Mac.
    static func makeFresh(_ v: Variant, efisys: Data? = nil) throws -> Made {
        let tree = try tree(v, efisys: { try efisys ?? efisysAfresh() })
        let iso = tree.deletingLastPathComponent().appendingPathComponent("win.iso")
        try sh("/usr/bin/hdiutil", ["makehybrid", "-quiet", "-iso", "-udf", "-udf-version", "1.02",
                                     "-udf-volume-name", volumeName, "-o", iso.path, tree.path])
        return Made(folder: tree, iso: iso)
    }

    static func tree(_ v: Variant, efisys: () throws -> Data) throws -> URL {
        switch v {
        case .eleven: return try build(FakeWIM.windows11, efisys: efisys)
        case .ten: return try build(FakeWIM.windows10, efisys: efisys)
        case .seven: return try build(FakeWIM.windows7, uefi: false, efisysLoader: true, efisys: efisys)
        case .arm64:
            var arm = FakeWIM.windows11
            arm[0].arch = 12
            arm[1].arch = 12
            return try build(arm, extra: ["efi/boot/bootaa64.efi": noise(1000, seed: 5)], efisys: efisys)
        case .elevenWithUnattend:
            return try build(FakeWIM.windows11, extra: ["autounattend.xml": Data("<unattend/>".utf8)], efisys: efisys)
        }
    }

    private static func build(_ images: [FakeWIM.Image], resources: [Int] = [40_000, 120_000, 2_000, 65_536, 300_000],
                              uefi: Bool = true, efisysLoader: Bool = false, bios: Bool = true,
                              extra: [String: Data] = [:], efisys: () throws -> Data) throws -> URL {
        let tree = try scratch("winiso").appendingPathComponent("tree")
        func put(_ path: String, _ data: Data) throws {
            let u = tree.appendingPathComponent(path)
            try FileManager.default.createDirectory(at: u.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: u)
        }
        if bios {
            try put("bootmgr", noise(400_000, seed: 11))
            try put("boot/bcd", noise(16_384, seed: 12))
            try put("boot/boot.sdi", noise(3_170_304 / 64, seed: 13))
        }
        try put("bootmgr.efi", noise(2_000_000 / 16, seed: 14))
        if uefi { try put("efi/boot/bootx64.efi", noise(150_000, seed: 15)) }
        try put("efi/microsoft/boot/bcd", noise(16_384, seed: 16))
        if efisysLoader { try put("efi/microsoft/boot/efisys.bin", try efisys()) }
        try put("setup.exe", noise(90_000, seed: 18))
        try put("autorun.inf", Data("[AutoRun.Amd64]\r\nopen=setup.exe\r\n".utf8))
        try put("sources/boot.wim", noise(200_000, seed: 19))
        try put("sources/install.wim", FakeWIM.make(images: images, resources: resources))
        try put("sources/empty.dat", Data())
        for (i, n) in longNames.enumerated() { try put("sources/" + n, noise(1000 + i * 333, seed: 30 + UInt64(i))) }
        // A folder holding more entries than one cluster.
        for i in 0..<120 { try put("sources/en-us/many-files-in-one-folder-\(i).mui", noise(100 + i, seed: 200 + UInt64(i))) }
        try put("support/logging/deep/deeper/deepest.txt", Data("deep".utf8))
        for (p, d) in extra { try put(p, d) }
        return tree
    }

    /// Windows' `efisys.bin`, the committed one: a FAT12 floppy image holding EFI/BOOT/BOOTX64.EFI.
    static func efisys() throws -> Data { try DiskFixture.bytes("efisys", tree: nil) }

    /// The same made afresh with macOS's newfs_msdos, filled through macOS's own FAT driver: only on a Mac.
    static func efisysAfresh() throws -> Data {
        let dir = try scratch("efisys")
        defer { try? FileManager.default.removeItem(at: dir) }
        let img = dir.appendingPathComponent("efisys.bin")
        FileManager.default.createFile(atPath: img.path, contents: Data(count: 1_474_560))
        // Attached as a device first: newfs_msdos won't format a plain file on every macOS.
        let out = try sh("/usr/bin/hdiutil", ["attach", "-nomount", "-imagekey", "diskimage-class=CRawDiskImage", "-plist",
                                              img.path])
        let plist = try PropertyListSerialization.propertyList(from: Data(out.utf8), format: nil) as? [String: Any]
        let devs = ((plist?["system-entities"] as? [[String: Any]]) ?? []).compactMap { $0["dev-entry"] as? String }
        guard devs.count == 1, let dev = devs.first, dev.wholeMatch(#"/dev/disk[0-9]+"#) else {
            for d in devs { _ = try? sh("/usr/bin/hdiutil", ["detach", "-force", d]) }
            throw DiskFixture.failure("not one disk: \(out)")
        }
        defer { _ = try? sh("/usr/bin/hdiutil", ["detach", "-force", dev]) }
        try sh("/sbin/newfs_msdos", ["-F", "12", "-f", "1440", "-v", "EFISECTOR", "/dev/r" + dev.dropFirst("/dev/".count)])
        let mount = dir.appendingPathComponent("m")
        try FileManager.default.createDirectory(at: mount, withIntermediateDirectories: true)
        try sh("/usr/sbin/diskutil", ["mount", "-mountPoint", mount.path, dev])
        try FileManager.default.createDirectory(at: mount.appendingPathComponent("EFI/BOOT"), withIntermediateDirectories: true)
        try efisysLoader.write(to: mount.appendingPathComponent("EFI/BOOT/BOOTX64.EFI"))
        try sh("/usr/sbin/diskutil", ["unmount", mount.path])
        try sh("/usr/bin/hdiutil", ["detach", dev])
        return try Data(contentsOf: img)
    }
}

/// The other two disks: a UDF ISO with a `sources/install.wim` that isn't one, and a plain ISO 9660 with no partition
/// table (a DVD's).
enum OtherDisks {
    static func notWindowsTree() throws -> URL {
        let t = try scratch("notwin").appendingPathComponent("t")
        try FileManager.default.createDirectory(at: t.appendingPathComponent("sources"), withIntermediateDirectories: true)
        try Data("x".utf8).write(to: t.appendingPathComponent("sources/install.wim"))
        return t
    }

    static func plainTree() throws -> URL {
        let t = try scratch("iso").appendingPathComponent("t")
        try FileManager.default.createDirectory(at: t.appendingPathComponent("boot"), withIntermediateDirectories: true)
        try noise(50_000, seed: 4).write(to: t.appendingPathComponent("boot/vmlinuz"))
        return t
    }

    static let notWindowsArgs = ["makehybrid", "-quiet", "-iso", "-udf"]
    static let plainArgs = ["makehybrid", "-quiet", "-iso"]
}

/// The files on a stick image, by path. Read by our own FAT32 reader for the tests (`FAT32ReadBack`); on the Mac also by
/// macOS's own FAT driver, which mounts the image, and the two must agree exactly.
func filesOnStick(_ image: URL) throws -> [String: Data] {
    let ours = try FAT32ReadBack.files(in: try Data(contentsOf: image))
    #if os(macOS)
    let macOS = try filesOnStickByMacOS(image)
    guard macOS == ours else {
        let onlyMac = Set(macOS.keys).subtracting(ours.keys).sorted()
        let onlyOurs = Set(ours.keys).subtracting(macOS.keys).sorted()
        let differ = Set(macOS.keys).intersection(ours.keys).filter { macOS[$0] != ours[$0] }.sorted()
        throw DiskFixture.failure("macOS and our FAT32 reader disagree: only macOS \(onlyMac), only ours \(onlyOurs), "
                                  + "different \(differ)")
    }
    return macOS
    #else
    return ours
    #endif
}

/// Attaches a whole-disk image, mounts its FAT32 partition (macOS's own FAT driver) and gives the files on it.
func filesOnStickByMacOS(_ image: URL) throws -> [String: Data] {
    let mount = try scratch("mnt")
    defer { try? FileManager.default.removeItem(at: mount) }
    let out = try sh("/usr/bin/hdiutil", ["attach", "-imagekey", "diskimage-class=CRawDiskImage", "-nobrowse", "-readonly",
                                           "-mountrandom", mount.path, "-plist", image.path])
    let plist = try PropertyListSerialization.propertyList(from: Data(out.utf8), format: nil) as? [String: Any]
    let entities = (plist?["system-entities"] as? [[String: Any]]) ?? []
    let dev = entities.compactMap { $0["dev-entry"] as? String }.filter { $0.wholeMatch(#"/dev/disk[0-9]+"#) }.first
    defer { if let d = dev { _ = try? sh("/usr/bin/hdiutil", ["detach", "-force", d]) } }
    guard let mp = entities.compactMap({ $0["mount-point"] as? String }).first else {
        throw DiskFixture.failure("nothing mounted: \(out)")
    }
    return try files(in: URL(fileURLWithPath: mp))
}

/// A FAT32 reader for the tests only, written apart from the code that makes the stick (`FAT32Stick`): the MBR's first
/// partition, the boot sector's numbers, cluster chains in the FAT, folders with long names (their checksums checked)
/// or short ones (with Windows' lower-case flags). On the Mac every read is checked against macOS's own FAT driver.
enum FAT32ReadBack {
    static func files(in disk: Data) throws -> [String: Data] {
        func bad(_ s: String) -> NSError { DiskFixture.failure("FAT32 read-back: " + s) }
        guard disk.count >= 1024, disk.byte(510) == 0x55, disk.byte(511) == 0xAA else { throw bad("no MBR") }
        let part = Int(disk.le32(454)) * 512
        guard part + 512 <= disk.count, disk.slice(part + 82, 8) == Data("FAT32   ".utf8) else { throw bad("no FAT32 boot sector") }
        let sector = Int(disk.le16(part + 11))
        let perCluster = Int(disk.byte(part + 13))
        let reserved = Int(disk.le16(part + 14))
        let fats = Int(disk.byte(part + 16))
        let fatSectors = Int(disk.le32(part + 36))
        let rootCluster = Int(disk.le32(part + 44))
        guard sector == 512, perCluster > 0, fats > 0 else { throw bad("odd numbers in the boot sector") }
        let fat = part + reserved * sector
        let data = fat + fats * fatSectors * sector
        let clusterBytes = sector * perCluster

        func chain(_ first: Int) throws -> [Int] {
            var out: [Int] = []
            var c = first
            while c >= 2 && c < 0x0FFF_FFF8 {
                guard out.count < 1 << 20, fat + c * 4 + 4 <= disk.count else { throw bad("a chain runs off or round") }
                out.append(c)
                c = Int(disk.le32(fat + c * 4) & 0x0FFF_FFFF)
            }
            return out
        }
        func read(_ first: Int, size: Int?) throws -> Data {
            var d = Data()
            for c in try chain(first) {
                let at = data + (c - 2) * clusterBytes
                guard at + clusterBytes <= disk.count else { throw bad("cluster \(c) is past the disk") }
                d.append(disk.slice(at, clusterBytes))
                if let s = size, d.count >= s { break }
            }
            if let s = size {
                guard d.count >= s else { throw bad("a file is longer than its clusters") }
                return d.prefix(s)
            }
            return d
        }
        func checksum(_ short: Data) -> UInt8 {
            var sum: UInt8 = 0
            for b in short { sum = ((sum & 1) << 7) &+ (sum >> 1) &+ b }
            return sum
        }

        var out: [String: Data] = [:]
        func walk(_ cluster: Int, _ prefix: String) throws {
            let d = try read(cluster, size: nil)
            var long: [Int: [UInt16]] = [:]
            var longSum: UInt8?
            var i = 0
            while i + 32 <= d.count {
                let e = d.slice(i, 32)
                i += 32
                let first = e.byte(0)
                if first == 0 { break }
                let attr = e.byte(11)
                if first == 0xE5 {
                    long = [:]
                    continue
                }
                if attr == 0x0F {
                    var u: [UInt16] = []
                    for o in [1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30] { u.append(e.le16(o)) }
                    long[Int(first & 0x1F)] = u
                    longSum = e.byte(13)
                    continue
                }
                if attr & 0x08 != 0 {
                    long = [:]
                    continue
                }
                let short = e.slice(0, 11)
                var name: String
                if !long.isEmpty {
                    guard longSum == checksum(short) else { throw bad("a long name doesn't belong to its short name") }
                    var all: [UInt16] = []
                    for k in long.keys.sorted() { all += long[k]! }
                    if let z = all.firstIndex(of: 0) { all = Array(all[..<z]) }
                    name = String(decoding: all.filter { $0 != 0xFFFF }, as: UTF16.self)
                } else {
                    var base = String(decoding: short.prefix(8), as: UTF8.self).trimmingCharacters(in: .whitespaces)
                    var ext = String(decoding: short.suffix(3), as: UTF8.self).trimmingCharacters(in: .whitespaces)
                    if e.byte(12) & 0x08 != 0 { base = base.lowercased() }
                    if e.byte(12) & 0x10 != 0 { ext = ext.lowercased() }
                    name = ext.isEmpty ? base : base + "." + ext
                }
                long = [:]
                if name == "." || name == ".." { continue }
                let c = Int(e.le16(20)) << 16 | Int(e.le16(26))
                let size = Int(e.le32(28))
                let path = prefix.isEmpty ? name : prefix + "/" + name
                if attr & 0x10 != 0 {
                    try walk(c, path)
                } else {
                    out[path] = size == 0 ? Data() : try read(c, size: size)
                }
            }
        }
        try walk(rootCluster, "")
        return out
    }
}

/// The committed disks against ones made afresh, and the maker itself.
final class DiskFixtureTests: XCTestCase {
    /// Every committed disk puts back to the SHA-256 macOS's tools gave it (on every system).
    func testEveryCommittedDiskPutsBackWhole() throws {
        let manifest = try DiskFixture.manifest()
        XCTAssertEqual(Set(manifest.keys), Set(FakeWindowsISO.Variant.allCases.map(\.rawValue) + ["efisys", "not-windows", "plain-iso"]))
        for v in FakeWindowsISO.Variant.allCases { XCTAssertNoThrow(try FakeWindowsISO.make(v), v.rawValue) }
        XCTAssertNoThrow(try DiskFixture.bytes("efisys", tree: nil))
        XCTAssertNoThrow(try DiskFixture.bytes("not-windows", tree: try OtherDisks.notWindowsTree()))
        XCTAssertNoThrow(try DiskFixture.bytes("plain-iso", tree: try OtherDisks.plainTree()))
        // A file of the folder that changed can't pass for the disk.
        let tree = try FakeWindowsISO.tree(.eleven, efisys: { try FakeWindowsISO.efisys() })
        try noise(400_000, seed: 99).write(to: tree.appendingPathComponent("bootmgr"))
        XCTAssertThrowsError(try DiskFixture.bytes(FakeWindowsISO.Variant.eleven.rawValue, tree: tree))
    }

    /// On the Mac: hdiutil and newfs_msdos today make disks our readers read exactly as they read the committed ones,
    /// so the committed disks haven't drifted from what macOS makes.
    func testAFreshDiskReadsLikeTheCommittedOne() throws {
        func udfFiles(_ url: URL) throws -> (String, [String: Data]) {
            let iso = try FileRandomAccess(url: url)
            let volume = try UDFReader.read(iso)
            var read: [String: Data] = [:]
            try volume.root.walk { path, node in
                if !node.isDirectory { read[path] = try node.contents(in: iso).read(at: 0, count: Int(node.size)) }
            }
            return (volume.name, read)
        }
        let freshEfisys = try FakeWindowsISO.efisysAfresh()
        for v in [FakeWindowsISO.Variant.eleven, .seven] {
            let committed = try udfFiles(try FakeWindowsISO.make(v).iso)
            let fresh = try udfFiles(try FakeWindowsISO.makeFresh(v, efisys: freshEfisys).iso)
            XCTAssertEqual(committed.0, fresh.0, v.rawValue)
            XCTAssertEqual(Set(committed.1.keys), Set(fresh.1.keys), v.rawValue)
            for (k, d) in committed.1 where k != "efi/microsoft/boot/efisys.bin" { XCTAssertEqual(fresh.1[k], d, k) }
        }
        for efisys in [try FakeWindowsISO.efisys(), freshEfisys] {
            let loader = try XCTUnwrap(try FATImage(DataRandomAccess(efisys)).file("efi/boot/bootx64.efi"))
            XCTAssertEqual(try loader.read(at: 0, count: Int(loader.size)), FakeWindowsISO.efisysLoader)
        }
    }

    /// Remakes the committed disks (`scripts/disk-fixtures.sh`): on a Mac, when asked.
    func testMakeTheDiskFixtures() throws {
        guard let path = ProcessInfo.processInfo.environment["SOFA_IMAGER_MAKE_DISK_FIXTURES"] else {
            throw XCTSkip("set SOFA_IMAGER_MAKE_DISK_FIXTURES to a folder to make the test disks again (on a Mac)")
        }
        let out = URL(fileURLWithPath: path)
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        var manifest: [String: DiskFixture.Entry] = [:]
        func add(_ name: String, _ disk: Data, contents: [(source: String, data: Data)]) throws {
            let (bones, pieces) = DiskFixture.skeleton(of: disk, contents: contents)
            let raw = out.appendingPathComponent(name + ".skel")
            try bones.write(to: raw)
            try sh("/usr/bin/env", ["xz", "-9e", "-T1", "--check=crc64", "--force", raw.path])
            manifest[name] = DiskFixture.Entry(size: disk.count, sha256: sha256(disk), ranges: pieces)
        }
        func treeContents(_ tree: URL) throws -> [(source: String, data: Data)] {
            try files(in: tree).sorted { $0.key < $1.key }
                .map { ("tree:" + $0.key.precomposedStringWithCanonicalMapping, $0.value) }
        }

        let efisys = try FakeWindowsISO.efisysAfresh()
        try add("efisys", efisys, contents: [("efisys-loader", FakeWindowsISO.efisysLoader)])
        for v in FakeWindowsISO.Variant.allCases {
            let made = try FakeWindowsISO.makeFresh(v, efisys: efisys)
            try add(v.rawValue, try Data(contentsOf: made.iso), contents: try treeContents(made.folder))
        }
        let notWindows = try OtherDisks.notWindowsTree(), plain = try OtherDisks.plainTree()
        for (name, tree, args) in [("not-windows", notWindows, OtherDisks.notWindowsArgs),
                                   ("plain-iso", plain, OtherDisks.plainArgs)] {
            let iso = tree.deletingLastPathComponent().appendingPathComponent(name + ".iso")
            try sh("/usr/bin/hdiutil", args + ["-o", iso.path, tree.path])
            try add(name, try Data(contentsOf: iso), contents: try treeContents(tree))
        }
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try enc.encode(manifest).write(to: out.appendingPathComponent("disks.json"))

        // What was written puts back whole, from a fresh folder made the way the tests make it.
        for v in FakeWindowsISO.Variant.allCases {
            let tree = try FakeWindowsISO.tree(v, efisys: { efisys })
            XCTAssertNoThrow(try DiskFixture.bytes(v.rawValue, tree: tree, from: out), v.rawValue)
        }
        XCTAssertEqual(try DiskFixture.bytes("efisys", tree: nil, from: out), efisys)
        for (name, piece) in manifest.sorted(by: { $0.key < $1.key }) {
            let packed = try FileManager.default.attributesOfItem(atPath: out.appendingPathComponent(name + ".skel.xz").path)[.size]
            print("disk fixture \(name): \(piece.size) bytes, \(piece.ranges.count) files put back, \(packed ?? 0) bytes packed")
        }
    }
}
