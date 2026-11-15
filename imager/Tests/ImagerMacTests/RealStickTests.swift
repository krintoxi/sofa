import Foundation
@testable import ImagerKit
@testable import ImagerMac
import XCTest

/// A real stick, written to a disk image through the raw device by the app's own `WriteJob`, and left behind to start
/// in a virtual PC (QEMU, UEFI and BIOS): everything the app does except the password prompt and a real stick. It
/// only runs when asked, with the image file to leave behind and one thing to write:
///
///     SOFA_IMAGER_STICK_OUT=<file> [SOFA_IMAGER_STICK_GB=16] swift test --filter RealStickTests, and one of
///       SOFA_IMAGER_WINDOWS_ISO=<Windows ISO> [SOFA_IMAGER_WIN11_SKIP_CHECKS=1] [SOFA_IMAGER_WIN11_ACCOUNT=<name>]
///       SOFA_IMAGER_SYSTEM=<a Linux list entry: ubuntu, debian, fedora, mint, raspios, raspios-lite>
///       SOFA_IMAGER_OWN_IMAGE=<an .iso, .img or .img.xz>
final class RealStickTests: XCTestCase {
    func testWriteARealStick() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let out = env["SOFA_IMAGER_STICK_OUT"], !out.isEmpty else { throw XCTSkip("set SOFA_IMAGER_STICK_OUT to run it") }
        let gb = Int(env["SOFA_IMAGER_STICK_GB"] ?? "") ?? 16
        let image = URL(fileURLWithPath: out)
        try? FileManager.default.removeItem(at: image)
        // A stick's size as they're sold: decimal gigabytes, in whole megabytes here.
        let disk = try TestDisk(sparseFile: image, megabytes: gb * 1_000_000_000 >> 20)
        defer { disk.detach() }
        let confirmed = try XCTUnwrap(DiskList.snapshot().disk(disk.bsd))

        let job: WriteJob
        if let iso = env["SOFA_IMAGER_WINDOWS_ISO"], !iso.isEmpty {
            let url = URL(fileURLWithPath: iso)
            let media = try WindowsMedia.detect(try FileRandomAccess(url: url))
            let options = WindowsOptions(skipHardwareChecks: env["SOFA_IMAGER_WIN11_SKIP_CHECKS"] == "1",
                                         localAccount: env["SOFA_IMAGER_WIN11_ACCOUNT"].flatMap { $0.isEmpty ? nil : $0 })
            job = .windows(iso: url, media: media, options: options, disk: confirmed, opener: DirectOpener())
        } else if let id = env["SOFA_IMAGER_SYSTEM"], let entry = Catalog.entry(id) {
            let card = try await CatalogResolver.resolve(entry, with: URLSessionFetcher(userAgent: "SofaBoxImager-tests"))
            print("RealStickTests: \(card.name) from \(card.url.absoluteString), sha256 \(card.extractSHA256)")
            job = WriteJob(card: card, disk: confirmed, opener: DirectOpener()) {
                HTTPSource(url: card.url, expectedSize: card.downloadSize, userAgent: "SofaBoxImager-tests")
            }
        } else if let own = env["SOFA_IMAGER_OWN_IMAGE"], !own.isEmpty {
            let url = URL(fileURLWithPath: own)
            let f = try FileRandomAccess(url: url)
            let kind = try ImageInspector.inspect(f, name: url.lastPathComponent)
            XCTAssertTrue(kind.writtenWhole, kind.summary)
            var bytes = f.size
            if case .packedImage(let n) = kind { bytes = n }
            job = .image(url, kind: kind, bytes: bytes, disk: confirmed, opener: DirectOpener())
        } else {
            throw XCTSkip("set SOFA_IMAGER_WINDOWS_ISO, SOFA_IMAGER_SYSTEM or SOFA_IMAGER_OWN_IMAGE")
        }
        // The policy, except that this disk image's being a disk image is let through.
        let needs = job.needs
        job.vet = { d, snap in
            guard d.bsdName == disk.bsd, d.model == "Disk Image", d.sizeBytes == disk.size else { return [.diskImage] }
            return snap.refusals(for: d, needs: needs).filter { $0 != .diskImage && $0 != .unknownLocation }
        }
        let start = Date()
        var marks: [String] = []
        var last = ""
        try job.run { s in
            var name = "\(s)"
            if case .writing(let p) = s { name = "\(p.phase)" }
            if name != last {
                last = name
                marks.append("\(name) at \(Int(Date().timeIntervalSince(start)))s")
            }
        }
        print("RealStickTests: \(job.title) on a \(gb) GB stick (\(image.path)): " + marks.joined(separator: ", ")
              + ", read back as sha256 \(job.writtenSHA256 ?? "?") in \(Int(Date().timeIntervalSince(start)))s")
    }
}
