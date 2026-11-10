import Foundation
@testable import ImagerKit
@testable import ImagerMac
import XCTest

/// The whole write, end to end, on a RAM disk the test attached itself: the same `WriteJob` the app runs, with two
/// differences only. The disk is opened directly (a disk image's device belongs to the user, so `authopen` isn't
/// needed), and the policy is told to accept this one RAM disk, which it otherwise refuses as a disk image.
final class WriteJobTests: XCTestCase {
    /// The policy, except that this RAM disk's being a disk image (and not saying where it is) is let through.
    private func allowOnly(_ ram: TestDisk) -> (DiskDescription, DiskSnapshot) -> [DiskRefusal] {
        { d, snap in
            guard d.bsdName == ram.bsd, d.model == "Disk Image", d.sizeBytes == ram.size else { return [.diskImage] }
            return snap.refusals(for: d, needs: TestCard.size).filter { $0 != .diskImage && $0 != .unknownLocation }
        }
    }

    func testWritesChecksAndEjectsARAMDisk() throws {
        let ram = try TestDisk(ramMegabytes: 64)
        defer { ram.detach() }
        // Something on it to unmount first, as an owner's card would have.
        try shell("/usr/sbin/diskutil", ["eraseDisk", "FAT32", "OLDCARD", "MBRFormat", ram.device])
        XCTAssertFalse(DiskList.mounts(on: ram.bsd).isEmpty)
        let confirmed = try XCTUnwrap(DiskList.snapshot().disk(ram.bsd))

        let card = TestCard.card()
        let job = WriteJob(card: card, disk: confirmed, opener: DirectOpener()) { try FileSource(url: card.url) }
        job.vet = allowOnly(ram)
        var stages: [String] = []
        var lastVerified: Int64 = 0
        try job.run { s in
            switch s {
            case .writing(let p):
                if stages.last != "\(p.phase)" { stages.append("\(p.phase)") }
                if p.phase == .verifying { lastVerified = p.done }
            default:
                stages.append("\(s)")
            }
        }
        XCTAssertEqual(stages, ["checking", "unmounting", "waitingForPassword", "writing", "finishing", "verifying",
                                "ejecting", "done"])
        XCTAssertEqual(lastVerified, TestCard.size)
        // Ejecting a disk image detaches it.
        let gone = Date().addingTimeInterval(10)
        while ram.exists && Date() < gone { usleep(100_000) }
        XCTAssertFalse(ram.exists, "\(ram.device) is still there after the eject")
    }

    /// The pipeline on the raw device, read back independently of the writer.
    func testWhatsOnTheDiskIsTheCard() throws {
        let ram = try TestDisk(ramMegabytes: 16)
        defer { ram.detach() }
        let fd = try DirectOpener().open(rawPath: ram.raw)
        defer { close(fd) }
        _ = fcntl(fd, F_NOCACHE, 1)
        let card = TestCard.card("multiblock.img.xz")
        try CardPipeline.run(source: try FileSource(url: card.url), device: FileDescriptorDevice(fd: fd), card: card,
                             diskSize: ram.size, sectorBytes: 512)
        XCTAssertEqual(try sha256(of: ram.raw, bytes: TestCard.size), TestCard.sha)
    }

    func testRefusesADiskThatChanged() throws {
        let ram = try TestDisk(ramMegabytes: 16)
        defer { ram.detach() }
        var confirmed = try XCTUnwrap(DiskList.snapshot().disk(ram.bsd))
        confirmed.appearanceTime = (confirmed.appearanceTime ?? 0) - 1       // as if it were another card
        let card = TestCard.card()
        let job = WriteJob(card: card, disk: confirmed, opener: DirectOpener()) { try FileSource(url: card.url) }
        job.vet = allowOnly(ram)
        XCTAssertThrowsError(try job.run { _ in }) { XCTAssertEqual($0 as? DiskOpError, .notTheSameDisk) }
    }

    func testThePolicyStopsItBeforeAnythingHappens() throws {
        let ram = try TestDisk(ramMegabytes: 64)
        defer { ram.detach() }
        try shell("/usr/sbin/diskutil", ["eraseDisk", "FAT32", "KEEPME", "MBRFormat", ram.device])
        let confirmed = try XCTUnwrap(DiskList.snapshot().disk(ram.bsd))
        let card = TestCard.card()
        // The real policy: a disk image is refused, and nothing is unmounted, opened or written.
        let job = WriteJob(card: card, disk: confirmed, opener: DirectOpener()) { try FileSource(url: card.url) }
        var stages: [WriteJob.Stage] = []
        XCTAssertThrowsError(try job.run { stages.append($0) }) {
            guard case .refused(let why)? = $0 as? JobError else { return XCTFail("\($0)") }
            XCTAssertTrue(why.contains(.diskImage))
        }
        XCTAssertEqual(stages, [.checking])
        XCTAssertTrue(DiskList.snapshot().disk(ram.bsd)?.volumes.contains { $0.name == "KEEPME" } ?? false)
    }

    /// If the device that opens isn't the disk confirmed (its number taken by another disk in between), the opened
    /// disk's own size gives it away and nothing is written.
    func testRefusesWhenTheOpenedDiskIsntTheConfirmedOne() throws {
        let ram = try TestDisk(ramMegabytes: 16)
        defer { ram.detach() }
        let other = try TestDisk(ramMegabytes: 32)
        defer { other.detach() }
        let confirmed = try XCTUnwrap(DiskList.snapshot().disk(ram.bsd))
        struct WrongOpener: DiskOpener {
            let path: String
            func open(rawPath: String) throws -> Int32 { try DirectOpener().open(rawPath: path) }
        }
        let card = TestCard.card()
        let job = WriteJob(card: card, disk: confirmed, opener: WrongOpener(path: other.raw)) { try FileSource(url: card.url) }
        job.vet = allowOnly(ram)
        XCTAssertThrowsError(try job.run { _ in }) { XCTAssertEqual($0 as? DiskOpError, .notTheSameDisk) }
        // Nothing reached the other disk.
        XCTAssertEqual(try sha256(of: other.raw, bytes: 1 << 20), try sha256(of: "/dev/zero", bytes: 1 << 20))
    }
}
