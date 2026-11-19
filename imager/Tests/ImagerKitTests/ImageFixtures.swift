import Foundation
@testable import ImagerKit
import XCTest

/// Tools only macOS has. A test that needs one to make or read its test disk is skipped elsewhere (and runs on the Mac).
let macOSOnlyTools: Set<String> = ["/usr/bin/hdiutil", "/sbin/newfs_msdos", "/usr/sbin/diskutil", "/usr/bin/xcrun"]

/// Runs a program and returns what it printed; throws when it fails.
@discardableResult
func sh(_ path: String, _ args: [String]) throws -> String {
    #if !os(macOS)
    if macOSOnlyTools.contains(path) {
        throw XCTSkip("needs macOS's \(URL(fileURLWithPath: path).lastPathComponent) to make or read its test disk")
    }
    #endif
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

/// A file's path the way this system's own programs take it (on Windows `C:\...`; elsewhere `path`, as before).
func native(_ url: URL) -> String {
    #if os(Windows)
    return url.withUnsafeFileSystemRepresentation { $0.map { String(cString: $0) } } ?? url.path
    #else
    return url.path
    #endif
}

#if os(Windows)
/// Where a program is, looked for in each folder of the search path (there's no `/usr/bin/env` to ask).
func onPath(_ program: String) throws -> String {
    let env = ProcessInfo.processInfo.environment
    let path = env.first { $0.key.uppercased() == "PATH" }?.value ?? ""
    for folder in path.split(separator: ";") {
        let candidate = URL(fileURLWithPath: String(folder)).appendingPathComponent(program)
        if FileManager.default.fileExists(atPath: native(candidate)) { return native(candidate) }
    }
    throw NSError(domain: "run", code: 127, userInfo: [NSLocalizedDescriptionKey: "\(program) isn't on the search path"])
}
#endif

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
        func hash(_ i: Int) -> Data {                       // made up: 20 bytes, like the SHA-1 a WIM keeps
            var h = SHA256Hasher()
            h.update(data: Data("r\(i)-\(seed)".utf8))
            return Data(h.finalize().prefix(20))
        }
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
