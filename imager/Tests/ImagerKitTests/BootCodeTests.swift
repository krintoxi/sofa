import Foundation
@testable import ImagerKit
import XCTest

/// The boot code's bytes are the sources' (`imager/boot/*.S`, assembled again here with clang: Xcode's on the Mac, the
/// Swift toolchain's elsewhere), and fit where they go.
final class BootCodeTests: XCTestCase {
    static let boot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("../../boot")
        .standardizedFileURL

    /// The `.text` section of a 32-bit ELF object.
    static func text(ofELF d: Data) throws -> Data {
        guard d.count > 52, d.prefix(4) == Data([0x7F, 0x45, 0x4C, 0x46]), d.byte(4) == 1 else {
            throw NSError(domain: "elf", code: 1)
        }
        let shoff = Int(d.le32(0x20))
        let shentsize = Int(d.le16(0x2E))
        let shnum = Int(d.le16(0x30))
        let shstrndx = Int(d.le16(0x32))
        func section(_ i: Int) -> (name: Int, offset: Int, size: Int) {
            let o = shoff + i * shentsize
            return (Int(d.le32(o)), Int(d.le32(o + 16)), Int(d.le32(o + 20)))
        }
        let names = section(shstrndx)
        for i in 0..<shnum {
            let s = section(i)
            var end = names.offset + s.name
            while d.byte(end) != 0 { end += 1 }
            if String(decoding: d.slice(names.offset + s.name, end - names.offset - s.name), as: UTF8.self) == ".text" {
                return d.slice(s.offset, s.size)
            }
        }
        throw NSError(domain: "elf", code: 2)
    }

    private func assemble(_ name: String) throws -> Data {
        let out = try scratch("asm").appendingPathComponent(name + ".o")
        do {
            #if os(macOS)
            let clang = ("/usr/bin/xcrun", ["clang"])
            #else
            let clang = ("/usr/bin/env", ["clang"])
            #endif
            try sh(clang.0, clang.1 + ["-c", "-target", "i386-unknown-none-elf",
                                       Self.boot.appendingPathComponent(name + ".S").path, "-o", out.path])
        } catch {
            throw XCTSkip("clang can't assemble for i386 here: \(error)")
        }
        return try Self.text(ofELF: try Data(contentsOf: out))
    }

    func testTheMBRIsItsSource() throws {
        XCTAssertEqual(Array(try assemble("mbr")), BootCode.mbrCode)
    }

    func testTheBootSectorIsItsSource() throws {
        XCTAssertEqual(Array(try assemble("fat32")), BootCode.fat32Code)
    }

    func testTheyFitWhereTheyGo() {
        // The MBR's code stops before the disk signature (440) and the partition table (446).
        XCTAssertLessThanOrEqual(BootCode.mbrCode.count, 440)
        // The boot sector is one sector: a short jump over the BPB, our code, the two numbers, 55 AA.
        let b = BootCode.fat32Code
        XCTAssertEqual(b.count, 512)
        XCTAssertEqual(Array(b[0..<3]), [0xEB, 0x58, 0x90])
        XCTAssertTrue(b[3..<0x5A].allSatisfy { $0 == 0 }, "the BPB is the Imager's to fill")
        XCTAssertTrue(b[BootCode.loaderSectorOffset..<BootCode.loaderSectorOffset + 6].allSatisfy { $0 == 0 })
        XCTAssertEqual(Array(b[510...]), [0x55, 0xAA])
    }

    func testThePartitionTableAndBPB() {
        let m = BootCode.mbr(diskSignature: 0x1234_5678, partitionStart: 2048, partitionSectors: 31_000_000)
        XCTAssertEqual(m.count, 512)
        XCTAssertEqual(m.le32(440), 0x1234_5678)
        XCTAssertEqual(m.byte(446), 0x80)
        XCTAssertEqual(m.slice(447, 3), Data([32, 33, 0]), "LBA 2048 is head 32, sector 33, cylinder 0")
        XCTAssertEqual(m.byte(450), 0x0C)
        XCTAssertEqual(m.slice(451, 3), Data([0xFE, 0xFF, 0xFF]), "past CHS: 1023/254/63")
        XCTAssertTrue(m.slice(462, 48).allSatisfy { $0 == 0 }, "one partition only")
        let v = BootCode.fat32BootSector(totalSectors: 31_000_000, sectorsPerCluster: 64, reservedSectors: 1234,
                                         fatSectors: 3780, hiddenSectors: 2048, volumeID: 0xCAFE_F00D,
                                         label: Array("WINDOWS 11".utf8), loader: (sector: 9000, count: 900))
        XCTAssertEqual(v.slice(3, 8), Data("MSWIN4.1".utf8))
        XCTAssertEqual(v.le16(11), 512)
        XCTAssertEqual(v.byte(13), 64)
        XCTAssertEqual(v.le16(14), 1234)
        XCTAssertEqual(v.byte(16), 2)
        XCTAssertEqual(v.le32(28), 2048)
        XCTAssertEqual(v.le32(32), 31_000_000)
        XCTAssertEqual(v.le32(36), 3780)
        XCTAssertEqual(v.le32(44), 2)
        XCTAssertEqual(v.byte(66), 0x29)
        XCTAssertEqual(v.le32(67), 0xCAFE_F00D)
        XCTAssertEqual(v.slice(71, 11), Data("WINDOWS 11 ".utf8))
        XCTAssertEqual(v.le32(BootCode.loaderSectorOffset), 9000)
        XCTAssertEqual(v.le16(BootCode.loaderCountOffset), 900)
        XCTAssertEqual(v.slice(0x5A, 100), Data(BootCode.fat32Code[0x5A..<0x5A + 100]), "the code is untouched")
    }
}
