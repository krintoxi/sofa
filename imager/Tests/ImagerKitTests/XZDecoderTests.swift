import Foundation
@testable import ImagerKit
import XCTest

/// macOS's Compression framework on the xz files `xz -T0` makes: many blocks, and several streams with padding.
final class XZDecoderTests: XCTestCase {
    private func unpack(_ packed: Data, chunk: Int = 65536) throws -> (Data, XZDecoder) {
        let dec = try XZDecoder()
        var out = Data()
        var i = 0
        while i < packed.count {
            let piece = packed.subdata(in: i..<min(packed.count, i + chunk))
            try dec.feed(piece) { out.append(contentsOf: $0) }
            i += chunk
        }
        try dec.finish { out.append(contentsOf: $0) }
        return (out, dec)
    }

    func testManyBlocksInOneStream() throws {
        let (out, dec) = try unpack(Fixture.data("multiblock.img.xz"))
        XCTAssertEqual(Int64(out.count), Fixture.cardSize)
        XCTAssertEqual(sha256(out), Fixture.cardSHA256)
        XCTAssertEqual(dec.streams, 1)
        XCTAssertEqual(dec.unpackedBytes, Fixture.cardSize)
    }

    func testSeveralStreamsWithPadding() throws {
        let (out, dec) = try unpack(Fixture.data("multistream.img.xz"))
        XCTAssertEqual(sha256(out), Fixture.cardSHA256)
        XCTAssertEqual(dec.streams, 2)
    }

    func testAnyChunkSize() throws {
        let packed = Fixture.data("multistream.img.xz")
        for chunk in [1, 3, 4093, 1 << 20, packed.count] {
            let (out, _) = try unpack(packed, chunk: chunk)
            XCTAssertEqual(sha256(out), Fixture.cardSHA256, "chunk \(chunk)")
        }
    }

    func testStreamsBackToBackWithoutPadding() throws {
        let one = Fixture.data("multiblock.img.xz")
        let (out, dec) = try unpack(one + one)
        XCTAssertEqual(Int64(out.count), 2 * Fixture.cardSize)
        XCTAssertEqual(dec.streams, 2)
    }

    func testPaddingMustBeWholeWords() throws {
        let one = Fixture.data("multiblock.img.xz")
        XCTAssertNoThrow(try unpack(one + Data(count: 4)))
        XCTAssertThrowsError(try unpack(one + Data(count: 3))) { XCTAssertEqual($0 as? XZError, .badPadding) }
        XCTAssertThrowsError(try unpack(one + Data(count: 3) + one)) { XCTAssertEqual($0 as? XZError, .badPadding) }
    }

    func testDamageIsCaught() throws {
        var packed = Fixture.data("multiblock.img.xz")
        packed[packed.count / 2] ^= 0x40
        XCTAssertThrowsError(try unpack(packed)) { XCTAssertEqual($0 as? XZError, .corrupt) }
        var footer = Fixture.data("multiblock.img.xz")
        footer[footer.count - 14] ^= 0x01                            // the stream's index, after all the data
        XCTAssertThrowsError(try unpack(footer))
    }

    func testAShortDownloadIsCaught() throws {
        let packed = Fixture.data("multiblock.img.xz")
        for cut in [1, 100, packed.count / 2, packed.count - 1] {
            XCTAssertThrowsError(try unpack(packed.prefix(cut)), "cut at \(cut)")
        }
        XCTAssertThrowsError(try unpack(Data())) { XCTAssertEqual($0 as? XZError, .truncated) }
    }

    func testGarbageAfterTheEndIsCaught() throws {
        let one = Fixture.data("multiblock.img.xz")
        XCTAssertThrowsError(try unpack(one + Data("junk".utf8)))
        XCTAssertThrowsError(try unpack(Data("not an xz file at all".utf8)))
    }
}
