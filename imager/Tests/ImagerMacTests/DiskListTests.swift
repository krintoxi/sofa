import Foundation
@testable import ImagerKit
@testable import ImagerMac
import XCTest

/// DiskArbitration and IOKit on the Mac running the tests: what it says about the real disks, read-only.
final class DiskListTests: XCTestCase {
    func testTheStartupDiskIsFoundAndNeverOffered() throws {
        let snap = DiskList.snapshot()
        XCTAssertFalse(snap.disks.isEmpty)
        XCTAssertFalse(snap.startupDisks.isEmpty, "no disk holds /")
        for bsd in snap.startupDisks {
            guard let d = snap.disk(bsd) else { continue }
            let why = snap.refusals(for: d, needs: 5_226_102_784)
            XCTAssertTrue(why.contains(.startupDisk), "\(bsd): \(why)")
        }
        // The disk "/" is mounted from is among them.
        var fs = statfs()
        XCTAssertEqual(statfs("/", &fs), 0)
        let from = withUnsafePointer(to: &fs.f_mntfromname) {
            $0.withMemoryRebound(to: CChar.self, capacity: Int(MAXPATHLEN)) { String(cString: $0) }
        }
        let rootDevice = String(from.dropFirst("/dev/".count))
        XCTAssertFalse(DiskList.wholeDisks(holding: rootDevice).isDisjoint(with: snap.startupDisks))
    }

    func testNothingOfferedBreaksARule() {
        let snap = DiskList.snapshot()
        let (offered, refused) = snap.sorted(needs: 5_226_102_784)
        for d in offered {
            XCTAssertFalse(snap.startupDisks.contains(d.bsdName))
            XCTAssertNotEqual(d.model, "Disk Image")
            XCTAssertNotEqual(d.isInternal, nil)
            XCTAssertTrue(d.sizeBytes <= DiskPolicy.largestDisk)
        }
        XCTAssertEqual(offered.count + refused.count, snap.disks.count)
        // Every refused disk says why, in words.
        for (_, why) in refused { XCTAssertFalse(why.isEmpty) }
    }

    func testEveryDiskDescribesItself() {
        for d in DiskList.snapshot().disks {
            XCTAssertTrue(d.isWhole, d.bsdName)
            XCTAssertTrue(d.bsdName.hasPrefix("disk"))
            XCTAssertFalse(d.ioClassChain.isEmpty, d.bsdName)
        }
    }

    func testARAMDiskIsSeenAsADiskImageAndRefused() throws {
        let ram = try TestDisk(ramMegabytes: 16)
        defer { ram.detach() }
        let snap = DiskList.snapshot()
        let d = try XCTUnwrap(snap.disk(ram.bsd))
        XCTAssertEqual(d.sizeBytes, 16 << 20)
        XCTAssertEqual(d.isInternal, nil)                       // what makes a naive filter offer it
        XCTAssertTrue(d.isRemovable || d.isEjectable)
        let why = snap.refusals(for: d, needs: 1 << 20)
        XCTAssertTrue(why.contains(.diskImage), "\(why)")
        XCTAssertFalse(snap.sorted(needs: 1 << 20).offered.contains { $0.bsdName == ram.bsd })
    }

    func testTheVolumesOnADiskAreFound() throws {
        let ram = try TestDisk(ramMegabytes: 64)
        defer { ram.detach() }
        try shell("/usr/sbin/diskutil", ["eraseDisk", "FAT32", "SOFATEST", "MBRFormat", ram.device])
        let d = try XCTUnwrap(DiskList.snapshot().disk(ram.bsd))
        XCTAssertTrue(d.volumes.contains { $0.name == "SOFATEST" && $0.mountPoint.hasPrefix("/Volumes/") }, "\(d.volumes)")
        XCTAssertFalse(DiskList.mounts(on: ram.bsd).isEmpty)
        try DiskArbitrationOps.unmountEverything(on: ram.bsd)
        XCTAssertTrue(DiskList.mounts(on: ram.bsd).isEmpty)
        XCTAssertTrue(DiskList.snapshot().disk(ram.bsd)?.volumes.isEmpty ?? false)
    }

    func testMountsAreRefusedWhileWriting() throws {
        let ram = try TestDisk(ramMegabytes: 64)
        defer { ram.detach() }
        try shell("/usr/sbin/diskutil", ["eraseDisk", "FAT32", "SOFATEST", "MBRFormat", ram.device])
        try DiskArbitrationOps.unmountEverything(on: ram.bsd)
        let blocker = try XCTUnwrap(MountBlocker(blocking: ram.bsd))
        XCTAssertThrowsError(try shell("/usr/sbin/diskutil", ["mountDisk", ram.device]))
        XCTAssertTrue(DiskList.mounts(on: ram.bsd).isEmpty)
        blocker.stop()
        try shell("/usr/sbin/diskutil", ["mountDisk", ram.device])
        XCTAssertFalse(DiskList.mounts(on: ram.bsd).isEmpty)
    }

    /// Without the owner there to type a password, authopen opens nothing (and shows nothing).
    func testAuthopenWithoutAPasswordOpensNothing() throws {
        let ram = try TestDisk(ramMegabytes: 16)
        defer { ram.detach() }
        let opener = AuthOpener(interactive: false)
        XCTAssertThrowsError(try opener.open(rawPath: ram.raw)) {
            XCTAssertEqual($0 as? DiskOpError, .passwordCancelled)
        }
    }
}
