import Foundation
@testable import ImagerKit
import XCTest

/// What a file is, from its first sectors: an ISO that's also a disk, a disk image, a packed one, Windows, or an ISO
/// that only starts from a DVD.
final class ImageInspectorTests: XCTestCase {
    /// An ISO 9660 image made by macOS's own hdiutil (no partition table: a DVD's ISO).
    static let plainISO: Data = {
        let dir = try! scratch("iso")
        try! FileManager.default.createDirectory(at: dir.appendingPathComponent("t/boot"), withIntermediateDirectories: true)
        try! noise(50_000, seed: 4).write(to: dir.appendingPathComponent("t/boot/vmlinuz"))
        let iso = dir.appendingPathComponent("plain.iso")
        try! sh("/usr/bin/hdiutil", ["makehybrid", "-quiet", "-iso", "-o", iso.path, dir.appendingPathComponent("t").path])
        return try! Data(contentsOf: iso)
    }()

    private func mbr(_ entries: [(status: UInt8, type: UInt8, start: UInt32, sectors: UInt32)]) -> Data {
        var d = Data(count: 512)
        for (i, e) in entries.enumerated() {
            d[446 + i * 16] = e.status
            d[446 + i * 16 + 4] = e.type
            d.put32(e.start, at: 446 + i * 16 + 8)
            d.put32(e.sectors, at: 446 + i * 16 + 12)
        }
        d[510] = 0x55
        d[511] = 0xAA
        return d
    }

    func testAnISOWithAPartitionTableIsWrittenWhole() throws {
        // As xorriso makes them: an active partition of type 0 spanning the ISO, and the EFI partition.
        var d = Self.plainISO
        d.replaceSubrange(0..<512, with: mbr([(0x80, 0x00, 0, UInt32(d.count / 512)), (0, 0xEF, 64, 1000)]))
        let kind = try ImageInspector.inspect(DataRandomAccess(d))
        XCTAssertEqual(kind, .hybridISO(partitions: .mbr))
        XCTAssertTrue(kind.writtenWhole)
        // With a GPT too (Fedora's and Ubuntu's are).
        var g = d
        g.replaceSubrange(512..<520, with: Data("EFI PART".utf8))
        XCTAssertEqual(try ImageInspector.inspect(DataRandomAccess(g)), .hybridISO(partitions: .gpt))
    }

    func testAnISOWithoutOneOnlyStartsFromADVD() throws {
        let kind = try ImageInspector.inspect(DataRandomAccess(Self.plainISO))
        XCTAssertEqual(kind, .discOnly)
        XCTAssertFalse(kind.writtenWhole)
    }

    func testDiskImages() throws {
        var d = mbr([(0x00, 0x0C, 8192, 100_000), (0, 0x83, 108_192, 900_000)])
        d.append(Data(count: 1 << 20))
        XCTAssertEqual(try ImageInspector.inspect(DataRandomAccess(d)), .diskImage(partitions: .mbr))
        var protective = mbr([(0x00, 0xEE, 1, 0xFFFF_FFFF)])
        protective.append(Data("EFI PART".utf8))
        protective.append(Data(count: 1 << 16))
        XCTAssertEqual(try ImageInspector.inspect(DataRandomAccess(protective)), .diskImage(partitions: .gpt))
        var sector = Data(count: 512)
        sector[510] = 0x55
        sector[511] = 0xAA
        sector.append(Data(count: 4096))
        XCTAssertEqual(try ImageInspector.inspect(DataRandomAccess(sector)), .diskImage(partitions: .bootSector))
    }

    func testAnythingElseIsntWritten() throws {
        let kind = try ImageInspector.inspect(DataRandomAccess(noise(200_000, seed: 8)))
        XCTAssertEqual(kind, .unknown)
        XCTAssertFalse(kind.writtenWhole)
    }

    func testAPackedImageKnowsItsUnpackedSize() throws {
        for name in ["multiblock.img.xz", "multistream.img.xz"] {
            let f = try FileRandomAccess(url: Fixture.url(name))
            XCTAssertEqual(try ImageInspector.inspect(f, name: name), .packedImage(unpacked: Fixture.cardSize), name)
            XCTAssertEqual(try XZIndex.unpackedSize(f), Fixture.cardSize)
        }
        var damaged = Fixture.data("multiblock.img.xz")
        damaged[damaged.count - 1] ^= 0xFF
        XCTAssertThrowsError(try XZIndex.unpackedSize(DataRandomAccess(damaged)))
    }

    func testWindowsIsntWrittenWhole() throws {
        let made = try FakeWindowsISO.make(FakeWIM.windows10)
        let kind = try ImageInspector.inspect(try FileRandomAccess(url: made.iso))
        guard case .windows(let w) = kind else { return XCTFail("\(kind)") }
        XCTAssertEqual(w.version, .ten)
        XCTAssertFalse(kind.writtenWhole)
    }
}
