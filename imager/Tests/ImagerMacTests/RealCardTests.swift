import Foundation
@testable import ImagerKit
@testable import ImagerMac
import XCTest

/// The newest real card from a real list, downloaded from GitHub and written to a disk image the size of a small SD
/// card, then read back and checked against the list's SHA-256: everything the app does except the password prompt
/// and real hardware. About 1.4 GB down and 5.3 GB written, so it only runs when asked:
///
///     SOFA_IMAGER_REAL_LIST=<list file or URL> [SOFA_IMAGER_SCRATCH=<folder with 6 GB free>] \
///         swift test --filter RealCardTests
final class RealCardTests: XCTestCase {
    private func newestCard() throws -> Card {
        guard let given = ProcessInfo.processInfo.environment["SOFA_IMAGER_REAL_LIST"], !given.isEmpty else {
            throw XCTSkip("set SOFA_IMAGER_REAL_LIST to run it")
        }
        let listURL = given.contains("://") ? URL(string: given)! : URL(fileURLWithPath: given)
        let list = try CardListParser.parse(try Data(contentsOf: listURL))
        let card = try XCTUnwrap(list.newest)
        XCTAssertEqual(card.url.scheme, "https")
        return card
    }

    /// GitHub sends a release download on to another host. A download that drops has to carry on there, from the
    /// byte it stopped at: the first 64 MB with a drop in the middle must be the same bytes as without one.
    func testCarriesOnAfterADropFromGitHub() throws {
        let card = try newestCard()
        let want = 64 << 20
        func first(dropAt: Int?) throws -> (Data, Int) {
            let s = HTTPSource(url: card.url, expectedSize: card.downloadSize, userAgent: "SofaBoxImager-tests",
                               retryDelay: 0.2)
            defer { s.cancel() }
            var out = Data()
            var dropped = false
            while out.count < want, let d = try s.next() {
                out.append(d)
                if let at = dropAt, !dropped, out.count >= at {
                    dropped = true
                    s.dropConnection()
                }
            }
            return (out.prefix(want), s.resumes)
        }
        let (whole, none) = try first(dropAt: nil)
        let (resumed, once) = try first(dropAt: 4 << 20)
        XCTAssertEqual(whole.count, want)
        XCTAssertEqual(none, 0)
        XCTAssertEqual(once, 1)
        XCTAssertEqual(sha256(resumed), sha256(whole))
    }

    func testTheNewestCardWritesAndChecks() throws {
        let card = try newestCard()

        // A sparse file a little bigger than the card, attached as a disk without mounting.
        let folder = URL(fileURLWithPath: ProcessInfo.processInfo.environment["SOFA_IMAGER_SCRATCH"]
                         ?? NSTemporaryDirectory())
        let image = folder.appendingPathComponent("sofa-imager-real-\(UUID().uuidString).img")
        let mb = Int((card.extractSize >> 20) + 64)
        defer { try? FileManager.default.removeItem(at: image) }
        let disk = try TestDisk(sparseFile: image, megabytes: mb)
        defer { disk.detach() }
        let confirmed = try XCTUnwrap(DiskList.snapshot().disk(disk.bsd))

        let job = WriteJob(card: card, disk: confirmed, opener: DirectOpener()) {
            HTTPSource(url: card.url, expectedSize: card.downloadSize, userAgent: "SofaBoxImager-tests")
        }
        job.vet = { d, snap in
            guard d.bsdName == disk.bsd, d.model == "Disk Image", d.sizeBytes == disk.size else { return [.diskImage] }
            return snap.refusals(for: d, needs: card.extractSize).filter { $0 != .diskImage && $0 != .unknownLocation }
        }
        let start = Date()
        var lastPhase: WriteProgress.Phase?
        var marks: [String] = []
        try job.run { s in
            if case .writing(let p) = s, p.phase != lastPhase {
                lastPhase = p.phase
                marks.append("\(p.phase) at \(Int(Date().timeIntervalSince(start)))s")
            }
        }
        print("RealCardTests: \(card.name), \(card.extractSize) bytes, checked against \(card.extractSHA256): "
              + marks.joined(separator: ", ") + ", done at \(Int(Date().timeIntervalSince(start)))s")
    }
}
