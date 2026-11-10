import Foundation
@testable import ImagerKit
import XCTest

/// The write-and-verify engine on a plain file standing in for a disk.
final class CardWriterTests: XCTestCase {
    let diskSize: Int64 = 4 << 20
    let mb: Int64 = 1 << 20

    private func run(_ card: Card, disk: TempDisk, device: BlockDevice? = nil, sector: Int = 512,
                     cancelAfter: Int64? = nil, endTimeout: Double = 10) throws {
        var written: Int64 = 0
        try CardPipeline.run(source: try FileSource(url: card.url),
                             device: device ?? FileDescriptorDevice(fd: disk.fd), card: card, diskSize: disk.size,
                             sectorBytes: sector, endTimeout: endTimeout,
                             progress: { p in if p.phase == .writing { written = p.done } },
                             isCancelled: { cancelAfter.map { written >= $0 } ?? false })
    }

    private func card(on disk: TempDisk) -> Data { disk.contents().prefix(Int(Fixture.cardSize)) }

    func testWritesAndChecksTheCard() throws {
        for file in ["multiblock.img.xz", "multistream.img.xz"] {
            let disk = try TempDisk(size: diskSize)
            try run(Fixture.card(file), disk: disk)
            let all = disk.contents()
            XCTAssertEqual(sha256(all.prefix(Int(Fixture.cardSize))), Fixture.cardSHA256, file)
            // Exactly as far as the card reaches: nothing after its last sector is touched, but the disk's last
            // megabyte (where an old GPT keeps its backup), which is blanked.
            XCTAssertTrue(all[Int(Fixture.cardSize)..<Int(3 * mb)].allSatisfy { $0 == 0xEE }, file)
            XCTAssertTrue(all.suffix(from: Int(3 * mb)).allSatisfy { $0 == 0 }, file)
        }
    }

    func testOnlyAlignedWritesTheFirstMegabyteLastAndNothingPastTheCard() throws {
        let disk = try TempDisk(size: diskSize)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        try run(Fixture.card(), disk: disk, device: rec, sector: 4096)
        let w = rec.writes
        // First: the old partition table blanked, then the last megabyte (an old GPT's backup).
        XCTAssertEqual(w[0], .init(offset: 0, length: 1 << 20, allZero: true))
        XCTAssertEqual(w[1], .init(offset: 3 * mb, length: 1 << 20, allZero: true))
        XCTAssertEqual(w.filter { $0.offset == 3 * mb }.count, 1)
        // Last: the real first megabyte, after everything else.
        XCTAssertEqual(w.last?.offset, 0)
        XCTAssertEqual(w.last?.allZero, false)
        XCTAssertEqual(w.filter { $0.offset == 0 }.count, 2)
        for x in w {
            XCTAssertEqual(x.offset % 4096, 0)
            XCTAssertEqual(x.length % 4096, 0)
            XCTAssertLessThanOrEqual(x.length, 1 << 20)
            XCTAssertEqual(x.offset % (1 << 20), 0)
        }
        // The card is 2,100,736 bytes: 2 MiB plus 3,584, padded to one 4096-byte sector.
        let end = w.filter { $0.offset != 3 * mb }.map { $0.offset + Int64($0.length) }.max()!
        XCTAssertEqual(end, (2 << 20) + 4096)
        XCTAssertGreaterThanOrEqual(rec.syncs, 3)
        XCTAssertEqual(sha256(card(on: disk)), Fixture.cardSHA256)
        XCTAssertTrue(disk.contents()[Int(Fixture.cardSize)..<Int(end)].allSatisfy { $0 == 0 })
    }

    func testADownloadThatIsntTheCardLeavesItBlank() throws {
        let disk = try TempDisk(size: diskSize)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        let wrong = Fixture.card(sha: String(repeating: "0", count: 64))
        XCTAssertThrowsError(try run(wrong, disk: disk, device: rec)) {
            XCTAssertEqual($0 as? WriteError, .downloadMismatch)
        }
        // The real first megabyte was never written; the first megabyte is zeros.
        XCTAssertFalse(rec.writes.contains { $0.offset == 0 && !$0.allZero })
        XCTAssertTrue(disk.contents().prefix(1 << 20).allSatisfy { $0 == 0 })
    }

    func testMoreDataThanTheListSaysStopsBeforeWritingIt() throws {
        let disk = try TempDisk(size: diskSize)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        let short = Fixture.card(size: 1 << 20)
        XCTAssertThrowsError(try run(short, disk: disk, device: rec)) {
            XCTAssertEqual($0 as? WriteError, .tooMuchData(expected: 1 << 20))
        }
        XCTAssertTrue(rec.writes.allSatisfy { $0.offset + Int64($0.length) <= 1 << 20 || $0.offset == 3 * mb })
        XCTAssertTrue(disk.contents()[Int(mb)..<Int(3 * mb)].allSatisfy { $0 == 0xEE })
    }

    func testLessDataThanTheListSays() throws {
        let disk = try TempDisk(size: diskSize)
        let long = Fixture.card(size: Fixture.cardSize + 512)
        XCTAssertThrowsError(try run(long, disk: disk)) {
            XCTAssertEqual($0 as? WriteError, .tooLittleData(got: Fixture.cardSize, expected: Fixture.cardSize + 512))
        }
        XCTAssertTrue(disk.contents().prefix(1 << 20).allSatisfy { $0 == 0 })
    }

    func testACardThatReadsBackWrongIsCaughtAndBlanked() throws {
        let disk = try TempDisk(size: diskSize)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        rec.corruptReadAt = 1_500_000
        XCTAssertThrowsError(try run(Fixture.card(), disk: disk, device: rec)) {
            XCTAssertEqual($0 as? WriteError, .verifyMismatch)
        }
        XCTAssertTrue(disk.contents().prefix(1 << 20).allSatisfy { $0 == 0 })
    }

    func testStoppingLeavesItBlank() throws {
        let disk = try TempDisk(size: diskSize)
        XCTAssertThrowsError(try run(Fixture.card(), disk: disk, cancelAfter: 1 << 20)) {
            XCTAssertEqual($0 as? WriteError, .cancelled)
        }
        XCTAssertTrue(disk.contents().prefix(1 << 20).allSatisfy { $0 == 0 })
    }

    func testACardTooBigForTheDiskWritesNothing() throws {
        let disk = try TempDisk(size: 2 << 20)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        XCTAssertThrowsError(try run(Fixture.card(), disk: disk, device: rec)) {
            XCTAssertEqual($0 as? WriteError, .cardTooBig(card: Fixture.cardSize, disk: 2 << 20))
        }
        XCTAssertEqual(rec.writes, [])
        XCTAssertTrue(disk.contents().allSatisfy { $0 == 0xEE })
    }

    func testAWriteErrorStopsIt() throws {
        let disk = try TempDisk(size: diskSize)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        rec.failWriteAt = 2 << 20
        XCTAssertThrowsError(try run(Fixture.card(), disk: disk, device: rec)) {
            guard case .io(let op, let offset, let code)? = $0 as? WriteError else { return XCTFail("\($0)") }
            XCTAssertEqual(op, "writing")
            XCTAssertEqual(offset, 2 << 20)
            XCTAssertEqual(code, EIO)
        }
    }

    /// A counterfeit card that claims more room than it has may never answer a write to its end.
    func testACardThatNeverAnswersAtItsEndIsNamed() throws {
        let disk = try TempDisk(size: diskSize)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        rec.hangWriteAt = 3 * mb
        defer { rec.release() }
        let start = Date()
        XCTAssertThrowsError(try run(Fixture.card(), disk: disk, device: rec, endTimeout: 0.3)) {
            XCTAssertEqual($0 as? WriteError, .cardNotAnswering)
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 5)
        // The first megabyte was blanked, and nothing was written after the card stopped answering.
        XCTAssertEqual(rec.writes, [.init(offset: 0, length: 1 << 20, allZero: true)])
        XCTAssertTrue(disk.contents().prefix(1 << 20).allSatisfy { $0 == 0 })
        XCTAssertTrue(disk.contents().suffix(from: 1 << 20).allSatisfy { $0 == 0xEE })
    }

    func testACardThatReachesIntoTheLastMegabyteStillChecks() throws {
        // A disk barely bigger than the card: the card's tail lies in the megabyte that was blanked first.
        let disk = try TempDisk(size: 3 * mb)
        try run(Fixture.card(), disk: disk)
        XCTAssertEqual(sha256(card(on: disk)), Fixture.cardSHA256)
        XCTAssertTrue(disk.contents().suffix(from: Int(Fixture.cardSize)).allSatisfy { $0 == 0 })
    }

    func testADiskOfOneMegabyteHasNoSeparateEnd() throws {
        let disk = try TempDisk(size: mb)
        let rec = RecordingDevice(FileDescriptorDevice(fd: disk.fd))
        XCTAssertThrowsError(try run(Fixture.card(size: 1024), disk: disk, device: rec))     // too much data
        XCTAssertTrue(rec.writes.allSatisfy { $0.offset == 0 })
    }

    func testMessagesAreSaid() {
        let all: [WriteError] = [.cancelled, .cardTooBig(card: 1, disk: 1), .tooMuchData(expected: 1),
                                 .tooLittleData(got: 1, expected: 2), .downloadMismatch, .verifyMismatch,
                                 .cardNotAnswering,
                                 .io(operation: "writing", offset: 0, code: EIO)]
        for e in all { XCTAssertFalse(e.description.isEmpty) }
    }
}
