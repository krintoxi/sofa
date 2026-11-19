import Foundation
@testable import ImagerKit
import XCTest

/// Reading and writing a file at a place, the part of the core each system does its own way (`FileIO`).
final class FileIOTests: XCTestCase {
    /// A place past 4 GB is the place asked for, not the same place 4 GB lower (where a 32-bit offset would land), and
    /// the file's length is counted in 64 bits. The file is as long as a small card but holds two markers and nothing else.
    func testAPlacePastFourGigabytes() throws {
        let dir = try scratch("big")
        defer { try? FileManager.default.removeItem(at: dir) }
        let url = dir.appendingPathComponent("big.img")
        let four: Int64 = 1 << 32
        let low = Data("the low marker".utf8)
        let high = Data("the high one!!".utf8)
        try (Data(count: 4096) + low).write(to: url)
        let h = try FileHandle(forWritingTo: url)
        try h.truncate(atOffset: UInt64(four + 8192))
        try h.close()

        let file = try FileRandomAccess(url: url)
        XCTAssertEqual(file.size, four + 8192)
        XCTAssertEqual(try file.read(at: 4096, count: low.count), low)
        XCTAssertEqual(try file.read(at: four + 4096, count: low.count), Data(count: low.count))

        let fd = FileIO.openFile(url, writing: true)
        XCTAssertGreaterThanOrEqual(fd, 0)
        defer { FileIO.closeFile(fd) }
        let device = FileDescriptorDevice(fd: fd)
        try high.withUnsafeBytes { try device.write($0, at: four + 4096) }
        try device.synchronize()
        var back = [UInt8](repeating: 0, count: high.count)
        try back.withUnsafeMutableBytes { try device.read(into: $0, at: four + 4096) }
        XCTAssertEqual(Data(back), high)
        try back.withUnsafeMutableBytes { try device.read(into: $0, at: 4096) }
        XCTAssertEqual(Data(back), low, "the write past 4 GB landed 4 GB lower")
        XCTAssertEqual(try file.read(at: four + 4096, count: high.count), high)
        XCTAssertEqual(FileIO.size(fd), four + 8192)

        // At the file's end a read gets nothing, and says so without an error.
        var one: UInt8 = 0
        let end = FileIO.read(fd, into: &one, count: 1, at: four + 8192)
        XCTAssertEqual(end.count, 0)
        XCTAssertEqual(end.code, 0)
    }

    func testAFileThatIsntThere() throws {
        let nowhere = try scratch("none").appendingPathComponent("not-here.img")
        XCTAssertLessThan(FileIO.openFile(nowhere), 0)
        XCTAssertThrowsError(try FileRandomAccess(url: nowhere)) {
            XCTAssertEqual($0 as? ReadError, .cantOpen(nowhere.path))
        }
    }

    /// Bytes go in and come out as they are: line ends and a Ctrl-Z among them (Windows' text mode would change both).
    func testBytesAreLeftAsTheyAre() throws {
        let disk = try TempDisk(size: 4096)
        let bytes = Data([0x0D, 0x0A, 0x0A, 0x1A, 0x00, 0x0D, 0xFF, 0x0A])
        let device = FileDescriptorDevice(fd: disk.fd)
        try bytes.withUnsafeBytes { try device.write($0, at: 512) }
        try device.synchronize()
        XCTAssertEqual(disk.contents().subdata(in: 512..<512 + bytes.count), bytes)
        XCTAssertEqual(disk.contents().count, 4096)
        XCTAssertEqual(try FileRandomAccess(url: disk.url).read(at: 512, count: bytes.count), bytes)
    }
}
