import CryptoKit
import DiscRecording
import Foundation
@testable import ImagerKit
@testable import ImagerMac
import XCTest

/// On a DVD, without a DVD burner: DiscRecording's dictionaries as a drive gives them, and the whole job with a
/// stand-in for hdiutil (it prints what `hdiutil burn -puppetstrings` prints, and keeps what it was asked).
final class BurnTests: XCTestCase {
    var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("sofa-burn-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    func testADriveAsDiscRecordingSaysIt() {
        let info: [AnyHashable: Any] = [
            DRDeviceVendorNameKey: "HL-DT-ST ", DRDeviceProductNameKey: "DVDRW  GX40N",
            DRDeviceWriteCapabilitiesKey: [DRDeviceCanWriteDVDRKey: NSNumber(value: true), DRDeviceCanWriteCDRKey: NSNumber(value: true)],
        ]
        let blank: [AnyHashable: Any] = [
            DRDeviceMediaStateKey: DRDeviceMediaStateMediaPresent,
            DRDeviceMediaInfoKey: [DRDeviceMediaClassKey: DRDeviceMediaClassDVD, DRDeviceMediaTypeKey: DRDeviceMediaTypeDVDR,
                                   DRDeviceMediaIsBlankKey: NSNumber(value: true), DRDeviceMediaBlocksFreeKey: NSNumber(value: 2_295_104)],
        ]
        let b = BurnerList.burner(info: info, status: blank, path: "IOService:/a/IODVDServices")
        XCTAssertEqual(b, Burner(id: "IOService:/a/IODVDServices", name: "HL-DT-ST DVDRW  GX40N", writesDVD: true,
                                 disc: .init(type: "DVD-R", isDVD: true, isBlank: true, freeBytes: 2_295_104 * 2048)))
        XCTAssertNil(b.refusal(needs: 1_500_000_000))
        let empty = BurnerList.burner(info: info, status: [DRDeviceMediaStateKey: DRDeviceMediaStateNone], path: "p")
        XCTAssertNil(empty.disc)
        let cdOnly = BurnerList.burner(info: [DRDeviceWriteCapabilitiesKey: [DRDeviceCanWriteCDRKey: NSNumber(value: true)]],
                                       status: [:], path: "p")
        XCTAssertFalse(cdOnly.writesDVD)
        XCTAssertEqual(cdOnly.name, "DVD burner")
        XCTAssertEqual(BurnerList.words(DRDeviceMediaTypeDVDPlusR), "DVD+R")
        XCTAssertNotNil(BurnerList.snapshot())             // (this Mac's: usually none, and that's fine)
    }

    // MARK: the job

    struct Disc {
        let card: Card
        let bytes: Data
    }

    func disc(size: Int = 3 << 20, sha: String? = nil) throws -> Disc {
        let bytes = Data((0..<size).map { UInt8(truncatingIfNeeded: $0 &* 31 &+ 7) })
        let file = dir.appendingPathComponent("sofa-box-os-9.9.9-pc-dvd.iso")
        try bytes.write(to: file)
        let real = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let card = Card(name: "Sofa Box OS 9.9.9 on a DVD (testing)", summary: "", url: file, downloadSize: Int64(size),
                        extractSize: Int64(size), extractSHA256: sha ?? real, releaseDate: "", website: nil)
        return Disc(card: card, bytes: bytes)
    }

    let ready = Burner(id: "IOService:/a/IODVDServices", name: "HL-DT-ST DVDRW GX40N", writesDVD: true,
                       disc: .init(type: "DVD-R", isDVD: true, isBlank: true, freeBytes: 4_700_372_992))

    /// A stand-in for hdiutil: says what hdiutil burn says, keeps its arguments, and exits with CODE.
    func fakeHdiutil(exit code: Int = 0) throws -> URL {
        let script = dir.appendingPathComponent("hdiutil")
        try """
        #!/bin/sh
        printf '%s\\n' "$@" > "\(dir.path)/args"
        echo "MESSAGE:Preparing data for burn"
        echo "PERCENT:-1.000000"
        echo "PERCENT:25.000000"
        echo "PERCENT:100.000000"
        echo "MESSAGE:Verifying burn…"
        echo "PERCENT:50.000000"
        \(code == 0 ? "echo 'MESSAGE:Burn completed successfully'" : "echo 'hdiutil: burn failed - Media is not writable.'")
        exit \(code)
        """.write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        return script
    }

    func job(_ d: Disc, burner: Burner? = nil, hdiutil: URL, sources: Counter) -> BurnJob {
        let j = BurnJob(card: d.card, burner: ready, cache: dir.appendingPathComponent("cache")) {
            sources.n += 1
            return try FileSource(url: d.card.url)
        }
        let now = burner
        j.find = { _ in now }
        j.hdiutil = hdiutil
        return j
    }

    final class Counter: @unchecked Sendable { var n = 0 }

    func testDownloadedCheckedBurnedAndCheckedAgain() throws {
        let d = try disc()
        let sources = Counter()
        var stages: [BurnJob.Stage] = []
        try job(d, burner: ready, hdiutil: try fakeHdiutil(), sources: sources).run { stages.append($0) }
        XCTAssertEqual(stages.first, .checking)
        XCTAssertTrue(stages.contains(.checkingDownload))
        XCTAssertTrue(stages.contains(.burning(0.25)))
        XCTAssertTrue(stages.contains(.verifying(nil)))
        XCTAssertTrue(stages.contains(.verifying(0.5)))
        XCTAssertEqual(stages.last, .done)
        let kept = dir.appendingPathComponent("cache/sofa-box-os-9.9.9-pc-dvd.iso")
        XCTAssertEqual(try Data(contentsOf: kept), d.bytes)
        let args = try String(contentsOf: dir.appendingPathComponent("args"), encoding: .utf8).split(separator: "\n").map(String.init)
        XCTAssertEqual(args, ["burn", kept.path, "-device", "IOService:/a/IODVDServices", "-noaddpmap", "-nooptimizeimage",
                              "-verifyburn", "-eject", "-puppetstrings"])
        // Another DVD of the same version: the file already there is checked, not downloaded again
        try job(d, burner: ready, hdiutil: try fakeHdiutil(), sources: sources).run { _ in }
        XCTAssertEqual(sources.n, 1)
    }

    func testADownloadThatIsntTheListsIsNeverBurned() throws {
        let d = try disc(sha: String(repeating: "00", count: 32))
        XCTAssertThrowsError(try job(d, burner: ready, hdiutil: try fakeHdiutil(), sources: Counter()).run { _ in }) { e in
            XCTAssertEqual(e as? BurnError, .wrongDownload)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("args").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("cache/sofa-box-os-9.9.9-pc-dvd.iso").path))
    }

    func testNoBurnerNoDiscOrAFailedBurnSaySo() throws {
        let d = try disc()
        XCTAssertThrowsError(try job(d, burner: nil, hdiutil: try fakeHdiutil(), sources: Counter()).run { _ in }) { e in
            XCTAssertEqual(e as? BurnError, .gone)
        }
        var empty = ready
        empty.disc = nil
        XCTAssertThrowsError(try job(d, burner: empty, hdiutil: try fakeHdiutil(), sources: Counter()).run { _ in }) { e in
            XCTAssertEqual((e as? BurnError)?.description, "Nothing was burned: No disc in it: put a blank DVD in (DVD-R or DVD+R).")
        }
        XCTAssertThrowsError(try job(d, burner: ready, hdiutil: try fakeHdiutil(exit: 1), sources: Counter()).run { _ in }) { e in
            guard case .burn(let why)? = e as? BurnError else { return XCTFail("\(e)") }
            XCTAssertTrue(why.contains("Media is not writable"), why)
        }
    }
}
