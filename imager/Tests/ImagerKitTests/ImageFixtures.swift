import CryptoKit
import Foundation
@testable import ImagerKit
import XCTest

/// Runs a program and returns what it printed; throws when it fails.
@discardableResult
func sh(_ path: String, _ args: [String]) throws -> String {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    let out = Pipe()
    p.standardOutput = out
    p.standardError = out
    try p.run()
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    let text = String(decoding: data, as: UTF8.self)
    guard p.terminationStatus == 0 else {
        throw NSError(domain: "run", code: Int(p.terminationStatus),
                      userInfo: [NSLocalizedDescriptionKey: "\(path) \(args.joined(separator: " ")): \(text)"])
    }
    return text
}

/// Bytes that look like nothing in particular, the same every time for the same seed.
func noise(_ count: Int, seed: UInt64) -> Data {
    var x = seed &* 0x9E37_79B9_7F4A_7C15 | 1
    var d = Data(count: count)
    d.withUnsafeMutableBytes { (b: UnsafeMutableRawBufferPointer) in
        for i in 0..<count {
            x ^= x << 13
            x ^= x >> 7
            x ^= x << 17
            b[i] = UInt8(truncatingIfNeeded: x)
        }
    }
    return d
}

func scratch(_ name: String) throws -> URL {
    let u = FileManager.default.temporaryDirectory.appendingPathComponent("sofa-imager-\(name)-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
    return u
}

/// A Windows image file made up for the tests, in Microsoft's format: a header, resources (random bytes standing in
/// for packed files), metadata resources, the resource table and the XML.
enum FakeWIM {
    struct Image {
        var name: String
        var major: Int
        var minor: Int
        var build: Int
        var arch: Int = 9
    }

    static let windows11 = [Image(name: "Windows 11 Home", major: 10, minor: 0, build: 26100),
                            Image(name: "Windows 11 Pro", major: 10, minor: 0, build: 26100)]
    static let windows10 = [Image(name: "Windows 10 Pro", major: 10, minor: 0, build: 19045)]
    static let windows7 = [Image(name: "Windows 7 Ultimate", major: 6, minor: 1, build: 7601)]

    /// - Parameters:
    ///   - resources: the sizes of the file resources.
    ///   - solid: also a solid group (two solid resources and three files inside them), as ESD files have.
    static func make(images: [Image], resources: [Int], seed: UInt64 = 1, solid: Bool = false) -> Data {
        var body = Data()
        var entries: [WIMFile.Entry] = []
        let start = Int64(WIMFile.headerSize)
        func hash(_ i: Int) -> Data { Data(Insecure.SHA1.hash(data: Data("r\(i)-\(seed)".utf8))) }
        for (i, n) in resources.enumerated() {
            let at = start + Int64(body.count)
            body.append(noise(n, seed: seed &+ UInt64(i) &+ 100))
            entries.append(.init(resource: .init(size: Int64(n), flags: WIMFile.Resource.flagCompressed, offset: at,
                                                 originalSize: Int64(n) * 2), part: 1, refCount: 1, hash: hash(i)))
        }
        if solid {
            var resourceEntries: [WIMFile.Entry] = []
            for k in 0..<2 {
                let at = start + Int64(body.count)
                body.append(noise(3000 + k * 1000, seed: seed &+ 900 &+ UInt64(k)))
                resourceEntries.append(.init(resource: .init(size: Int64(3000 + k * 1000),
                                                             flags: WIMFile.Resource.flagSolid | WIMFile.Resource.flagCompressed,
                                                             offset: at, originalSize: 0x1_0000_0000),
                                             part: 1, refCount: 1, hash: Data(count: 20)))
            }
            entries += resourceEntries
            for k in 0..<3 {
                entries.append(.init(resource: .init(size: 5000, flags: WIMFile.Resource.flagSolid, offset: Int64(k) * 5000,
                                                     originalSize: 5000), part: 1, refCount: 1, hash: hash(700 + k)))
            }
        }
        for (i, _) in images.enumerated() {
            let at = start + Int64(body.count)
            body.append(noise(777 + i, seed: seed &+ 500 &+ UInt64(i)))
            entries.append(.init(resource: .init(size: Int64(777 + i),
                                                 flags: WIMFile.Resource.flagMetadata | WIMFile.Resource.flagCompressed,
                                                 offset: at, originalSize: 4000), part: 1, refCount: 1, hash: hash(300 + i)))
        }
        let tableAt = start + Int64(body.count)
        var table = Data()
        for e in entries { table.append(e.bytes) }
        body.append(table)
        let xmlAt = start + Int64(body.count)
        var x = "<WIM><TOTALBYTES>\(tableAt)</TOTALBYTES>"
        for (i, im) in images.enumerated() {
            x += "<IMAGE INDEX=\"\(i + 1)\"><NAME>\(im.name)</NAME><DISPLAYNAME>\(im.name)</DISPLAYNAME>"
            x += "<WINDOWS><ARCH>\(im.arch)</ARCH><EDITIONID>Professional</EDITIONID><VERSION><MAJOR>\(im.major)</MAJOR>"
            x += "<MINOR>\(im.minor)</MINOR><BUILD>\(im.build)</BUILD><SPBUILD>1</SPBUILD></VERSION></WINDOWS></IMAGE>"
        }
        x += "</WIM>"
        var xml = Data([0xFF, 0xFE])
        for u in x.utf16 { xml.append(UInt8(u & 0xFF)); xml.append(UInt8(u >> 8)) }
        body.append(xml)

        var h = Data(count: WIMFile.headerSize)
        h.put(Array(WIMFile.magic), at: 0)
        h.put32(UInt32(WIMFile.headerSize), at: 8)
        h.put32(solid ? 0xE00 : 0x10D00, at: 0x0C)
        h.put32(0x0004_0002, at: 0x10)
        h.put32(32768, at: 0x14)
        h.replaceSubrange(0x18..<0x28, with: noise(16, seed: seed &+ 77))
        h.put16(1, at: 0x28)
        h.put16(1, at: 0x2A)
        h.put32(UInt32(images.count), at: 0x2C)
        h.replaceSubrange(0x30..<0x48, with: WIMFile.Resource(size: Int64(table.count), flags: 2, offset: tableAt,
                                                             originalSize: Int64(table.count)).bytes)
        h.replaceSubrange(0x48..<0x60, with: WIMFile.Resource(size: Int64(xml.count), flags: 0, offset: xmlAt,
                                                             originalSize: Int64(xml.count)).bytes)
        h.replaceSubrange(0x7C..<0x94, with: WIMFile.Resource(size: 40, flags: 0, offset: 0, originalSize: 40).bytes)
        return h + body
    }
}

/// Windows installer ISOs made up for the tests: the folders and files Microsoft's have, with made-up contents, put in
/// a UDF image by macOS's own `hdiutil makehybrid` (UDF 1.02, as Microsoft's are).
enum FakeWindowsISO {
    static let longNames = ["api-ms-win-downlevel-shlwapi-l1-1-0.dll", "Microsoft-Windows-Setup.Resources.mui",
                            "a name with spaces.txt", "ñandú.inf", "UPPER.TXT", "lower.txt", "MiXeD.Cab", "x.y.z.dat"]

    /// The folder it's made from (kept, to compare against).
    struct Made {
        let folder: URL
        let iso: URL
    }

    static func make(_ images: [FakeWIM.Image], resources: [Int] = [40_000, 120_000, 2_000, 65_536, 300_000],
                     uefi: Bool = true, efisysLoader: Bool = false, bios: Bool = true, extra: [String: Data] = [:],
                     solid: Bool = false) throws -> Made {
        let dir = try scratch("winiso")
        let tree = dir.appendingPathComponent("tree")
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
        if efisysLoader { try put("efi/microsoft/boot/efisys.bin", try efisys(loader: noise(98_765, seed: 17))) }
        try put("setup.exe", noise(90_000, seed: 18))
        try put("autorun.inf", Data("[AutoRun.Amd64]\r\nopen=setup.exe\r\n".utf8))
        try put("sources/boot.wim", noise(200_000, seed: 19))
        try put("sources/install.wim", FakeWIM.make(images: images, resources: resources, solid: solid))
        try put("sources/empty.dat", Data())
        for (i, n) in longNames.enumerated() { try put("sources/" + n, noise(1000 + i * 333, seed: 30 + UInt64(i))) }
        // A folder holding more entries than one cluster.
        for i in 0..<120 { try put("sources/en-us/many-files-in-one-folder-\(i).mui", noise(100 + i, seed: 200 + UInt64(i))) }
        try put("support/logging/deep/deeper/deepest.txt", Data("deep".utf8))
        for (p, d) in extra { try put(p, d) }
        let iso = dir.appendingPathComponent("win.iso")
        try sh("/usr/bin/hdiutil", ["makehybrid", "-quiet", "-iso", "-udf", "-udf-version", "1.02",
                                     "-udf-volume-name", "CCCOMA_X64FRE_EN-US_DV9", "-o", iso.path, tree.path])
        return Made(folder: tree, iso: iso)
    }

    /// A FAT12 floppy image like Windows' `efisys.bin`, holding EFI/BOOT/BOOTX64.EFI (made with macOS's newfs_msdos,
    /// filled through macOS's own FAT driver).
    static func efisys(loader: Data) throws -> Data {
        let dir = try scratch("efisys")
        defer { try? FileManager.default.removeItem(at: dir) }
        let img = dir.appendingPathComponent("efisys.bin")
        FileManager.default.createFile(atPath: img.path, contents: Data(count: 1_474_560))
        // Attached as a device first: newfs_msdos won't format a plain file on every macOS.
        let out = try sh("/usr/bin/hdiutil", ["attach", "-nomount", "-imagekey", "diskimage-class=CRawDiskImage", "-plist",
                                              img.path])
        let plist = try PropertyListSerialization.propertyList(from: Data(out.utf8), format: nil) as? [String: Any]
        let devs = ((plist?["system-entities"] as? [[String: Any]]) ?? []).compactMap { $0["dev-entry"] as? String }
        guard devs.count == 1, let dev = devs.first, dev.range(of: #"^/dev/disk[0-9]+$"#, options: .regularExpression) != nil
        else {
            for d in devs { _ = try? sh("/usr/bin/hdiutil", ["detach", "-force", d]) }
            throw NSError(domain: "efisys", code: 1, userInfo: [NSLocalizedDescriptionKey: "not one disk: \(out)"])
        }
        defer { _ = try? sh("/usr/bin/hdiutil", ["detach", "-force", dev]) }
        try sh("/sbin/newfs_msdos", ["-F", "12", "-f", "1440", "-v", "EFISECTOR", "/dev/r" + dev.dropFirst("/dev/".count)])
        let mount = dir.appendingPathComponent("m")
        try FileManager.default.createDirectory(at: mount, withIntermediateDirectories: true)
        try sh("/usr/sbin/diskutil", ["mount", "-mountPoint", mount.path, dev])
        try FileManager.default.createDirectory(at: mount.appendingPathComponent("EFI/BOOT"), withIntermediateDirectories: true)
        try loader.write(to: mount.appendingPathComponent("EFI/BOOT/BOOTX64.EFI"))
        try sh("/usr/sbin/diskutil", ["unmount", mount.path])
        try sh("/usr/bin/hdiutil", ["detach", dev])
        return try Data(contentsOf: img)
    }
}

/// A layout written into a sparse file of `size` bytes (a stand-in for the stick).
func writeLayout(_ layout: Layout, size: Int64, to url: URL) throws {
    FileManager.default.createFile(atPath: url.path, contents: nil)
    let h = try FileHandle(forWritingTo: url)
    defer { try? h.close() }
    try h.truncate(atOffset: UInt64(size))
    let src = LayoutSource(layout)
    var at: UInt64 = 0
    while let d = try src.next() {
        try h.seek(toOffset: at)
        try h.write(contentsOf: d)
        at += UInt64(d.count)
    }
}

/// Every file under `folder`, by path, with its bytes.
func files(in folder: URL) throws -> [String: Data] {
    var out: [String: Data] = [:]
    let base = folder.resolvingSymlinksInPath().path
    for case let f as URL in FileManager.default.enumerator(at: folder, includingPropertiesForKeys: [.isRegularFileKey])! {
        guard (try f.resourceValues(forKeys: [.isRegularFileKey])).isRegularFile == true else { continue }
        let p = f.resolvingSymlinksInPath().path
        let rel = String(p.dropFirst(base.count + 1))
        if rel.hasPrefix(".") || rel.contains("/.") { continue }          // macOS's own .fseventsd and the like
        out[rel] = try Data(contentsOf: f)
    }
    return out
}

/// Attaches a whole-disk image, mounts its FAT32 partition (macOS's own FAT driver) and gives the files on it.
func filesOnStick(_ image: URL) throws -> [String: Data] {
    let mount = try scratch("mnt")
    defer { try? FileManager.default.removeItem(at: mount) }
    let out = try sh("/usr/bin/hdiutil", ["attach", "-imagekey", "diskimage-class=CRawDiskImage", "-nobrowse", "-readonly",
                                           "-mountrandom", mount.path, "-plist", image.path])
    let plist = try PropertyListSerialization.propertyList(from: Data(out.utf8), format: nil) as? [String: Any]
    let entities = (plist?["system-entities"] as? [[String: Any]]) ?? []
    let dev = entities.compactMap { $0["dev-entry"] as? String }.filter { $0.range(of: #"^/dev/disk[0-9]+$"#, options: .regularExpression) != nil }.first
    defer { if let d = dev { _ = try? sh("/usr/bin/hdiutil", ["detach", "-force", d]) } }
    guard let mp = entities.compactMap({ $0["mount-point"] as? String }).first else {
        throw NSError(domain: "mount", code: 1, userInfo: [NSLocalizedDescriptionKey: "nothing mounted: \(out)"])
    }
    return try files(in: URL(fileURLWithPath: mp))
}
