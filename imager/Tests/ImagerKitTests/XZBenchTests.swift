import Foundation
@testable import ImagerKit
import XCTest
#if canImport(CryptoKit)
import CryptoKit
#endif

/// When asked: each xz unpacker and each SHA-256 on a real card, with how long each took. Both unpackers must give the
/// same bytes, and both hashes the same digest (and the list's, if given). Best in a release build:
///
///     SOFA_IMAGER_XZ_BENCH=/path/to/sofa-box-os.img.xz SOFA_IMAGER_XZ_SHA=<its unpacked SHA-256> \
///       swift test -c release -Xswiftc -enable-testing --filter XZBenchTests
final class XZBenchTests: XCTestCase {
    func testEachUnpackerAndHashOnARealCard() throws {
        let env = ProcessInfo.processInfo.environment
        guard let path = env["SOFA_IMAGER_XZ_BENCH"] else { throw XCTSkip("set SOFA_IMAGER_XZ_BENCH to a .img.xz to run it") }
        let want = env["SOFA_IMAGER_XZ_SHA"]?.lowercased()
        var digests: [String: String] = [:]
        for u in XZDecoderTests.unpackers {
            let file = try FileHandle(forReadingFrom: URL(fileURLWithPath: path))
            defer { try? file.close() }
            let dec = try u.make()
            var ours = SHA256Hasher()
            #if canImport(CryptoKit)
            var apple = CryptoKit.SHA256()
            #endif
            var hashing: UInt64 = 0, appleHashing: UInt64 = 0
            let start = DispatchTime.now().uptimeNanoseconds
            func take(_ piece: UnsafeRawBufferPointer) {
                let a = DispatchTime.now().uptimeNanoseconds
                ours.update(bufferPointer: piece)
                let b = DispatchTime.now().uptimeNanoseconds
                hashing += b - a
                #if canImport(CryptoKit)
                apple.update(bufferPointer: piece)
                appleHashing += DispatchTime.now().uptimeNanoseconds - b
                #endif
            }
            while let packed = try file.read(upToCount: 1 << 20), !packed.isEmpty {
                try dec.feed(packed, output: take)
            }
            try dec.finish(output: take)
            let total = DispatchTime.now().uptimeNanoseconds - start
            let unpacking = total - hashing - appleHashing
            let gb = Double(dec.unpackedBytes) / 1e9
            func rate(_ ns: UInt64) -> String { String(format: "%.0f MB/s (%.1f s)", gb * 1000 / (Double(ns) / 1e9), Double(ns) / 1e9) }
            let digest = SHA256Hasher.hex(ours.finalize())
            print("xz bench: \(u.name) unpacker: \(rate(unpacking)) for \(dec.unpackedBytes) bytes; our SHA-256 \(rate(hashing))")
            #if canImport(CryptoKit)
            print("xz bench: Apple's SHA-256 \(rate(appleHashing))")
            XCTAssertEqual(apple.finalize().map { String(format: "%02x", $0) }.joined(), digest, "the two SHA-256s")
            #endif
            digests[u.name] = digest
            if let w = want { XCTAssertEqual(digest, w, "\(u.name) unpacker against the list") }
        }
        XCTAssertEqual(Set(digests.values).count, 1, "the unpackers disagree: \(digests)")
    }
}
