import Foundation
@testable import ImagerKit
import XCTest
#if canImport(CryptoKit)
import CryptoKit
#endif

/// Our SHA-256 (used on Windows and Linux): FIPS 180-4's own examples, every way of feeding it, and on the Mac the same
/// digests as Apple's CryptoKit for every length.
final class SHA256Tests: XCTestCase {
    private func ours(_ bytes: [UInt8]) -> String { SHA256Hasher.hex(Data(bytes)) }

    func testTheStandardsExamples() {
        XCTAssertEqual(ours([]), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        XCTAssertEqual(ours(Array("abc".utf8)), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        XCTAssertEqual(ours(Array("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq".utf8)),
                       "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1")
        XCTAssertEqual(ours([UInt8](repeating: UInt8(ascii: "a"), count: 1_000_000)),
                       "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")
    }

    func testAnyPiecesGiveTheSameDigest() {
        let bytes = (0..<5000).map { UInt8(truncatingIfNeeded: $0 &* 31 &+ ($0 >> 7)) }
        let whole = ours(bytes)
        for piece in [1, 3, 63, 64, 65, 127, 1000, 4999] {
            var h = SHA256Hasher()
            var i = 0
            while i < bytes.count {
                let n = min(piece, bytes.count - i)
                bytes[i..<i + n].withUnsafeBytes { h.update(bufferPointer: $0) }
                i += n
            }
            XCTAssertEqual(SHA256Hasher.hex(h.finalize()), whole, "pieces of \(piece)")
        }
    }

    func testFinishingLeavesTheHasherAsItWas() {
        var h = SHA256Hasher()
        h.update(data: Data("ab".utf8))
        let first = SHA256Hasher.hex(h.finalize())
        XCTAssertEqual(SHA256Hasher.hex(h.finalize()), first)
        h.update(data: Data("c".utf8))
        XCTAssertEqual(SHA256Hasher.hex(h.finalize()), ours(Array("abc".utf8)))
    }

    #if canImport(CryptoKit)
    func testTheSameAsCryptoKitAtEveryLength() {
        var bytes = [UInt8]()
        var x: UInt32 = 2_463_534_242
        for n in 0...1100 {
            XCTAssertEqual(ours(bytes), CryptoKit.SHA256.hash(data: Data(bytes)).map { String(format: "%02x", $0) }.joined(),
                           "\(n) bytes")
            x ^= x << 13; x ^= x >> 17; x ^= x << 5
            bytes.append(UInt8(truncatingIfNeeded: x))
        }
    }
    #endif
}
