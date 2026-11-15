import Foundation
@testable import ImagerKit
import XCTest

/// Both xz unpackers on what `xz` makes: ours (`XZUnpacker`, used on Windows and Linux) everywhere, and on the Mac also
/// Apple's Compression framework (`XZDecoder`), which the Mac app still uses. Every test is run on each.
final class XZDecoderTests: XCTestCase {
    static var unpackers: [(name: String, make: () throws -> XZUnpacking)] {
        var list: [(name: String, make: () throws -> XZUnpacking)] = [("ours", { try XZUnpacker() })]
        #if canImport(Compression)
        list.append(("Apple's", { try XZDecoder() }))
        #endif
        return list
    }

    /// The input `scripts/xz-fixtures.py` packs into every `mixed-*.xz`, and the one in `random-first.xz`.
    static let mixedSize = 643_072
    static let mixedSHA256 = "0009ce4a5229dee45c0eeb0bf821d670e79dcffaa051aac86cba9b80ebf6b217"
    static let randomFirstSize = 806_912
    static let randomFirstSHA256 = "e4db573771ad9548047c01ca835d3a39a3dcbb73dc6a21f67c9a561bf6592021"

    private func unpack(_ packed: Data, chunk: Int = 65536, with make: () throws -> XZUnpacking) throws
        -> (Data, XZUnpacking) {
        let dec = try make()
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

    private func each(_ body: (String, () throws -> XZUnpacking) throws -> Void) rethrows {
        for u in XZDecoderTests.unpackers { try body(u.name, u.make) }
    }

    func testManyBlocksInOneStream() throws {
        try each { name, make in
            let (out, dec) = try unpack(Fixture.data("multiblock.img.xz"), with: make)
            XCTAssertEqual(Int64(out.count), Fixture.cardSize, name)
            XCTAssertEqual(sha256(out), Fixture.cardSHA256, name)
            XCTAssertEqual(dec.streams, 1, name)
            XCTAssertEqual(dec.unpackedBytes, Fixture.cardSize, name)
        }
    }

    func testSeveralStreamsWithPadding() throws {
        try each { name, make in
            let (out, dec) = try unpack(Fixture.data("multistream.img.xz"), with: make)
            XCTAssertEqual(sha256(out), Fixture.cardSHA256, name)
            XCTAssertEqual(dec.streams, 2, name)
        }
    }

    func testAnyChunkSize() throws {
        let packed = Fixture.data("multistream.img.xz")
        try each { name, make in
            for chunk in [1, 3, 4093, 1 << 20, packed.count] {
                let (out, _) = try unpack(packed, chunk: chunk, with: make)
                XCTAssertEqual(sha256(out), Fixture.cardSHA256, "\(name), chunk \(chunk)")
            }
        }
    }

    func testStreamsBackToBackWithoutPadding() throws {
        let one = Fixture.data("multiblock.img.xz")
        try each { name, make in
            let (out, dec) = try unpack(one + one, with: make)
            XCTAssertEqual(Int64(out.count), 2 * Fixture.cardSize, name)
            XCTAssertEqual(dec.streams, 2, name)
        }
    }

    func testPaddingMustBeWholeWords() throws {
        let one = Fixture.data("multiblock.img.xz")
        try each { name, make in
            XCTAssertNoThrow(try unpack(one + Data(count: 4), with: make), name)
            XCTAssertThrowsError(try unpack(one + Data(count: 3), with: make), name) {
                XCTAssertEqual($0 as? XZError, .badPadding, name)
            }
            XCTAssertThrowsError(try unpack(one + Data(count: 3) + one, with: make), name) {
                XCTAssertEqual($0 as? XZError, .badPadding, name)
            }
        }
    }

    func testDamageIsCaught() throws {
        try each { name, make in
            var packed = Fixture.data("multiblock.img.xz")
            packed[packed.count / 2] ^= 0x40
            XCTAssertThrowsError(try unpack(packed, with: make), name) { XCTAssertEqual($0 as? XZError, .corrupt, name) }
            var footer = Fixture.data("multiblock.img.xz")
            footer[footer.count - 14] ^= 0x01                            // the stream's index, after all the data
            XCTAssertThrowsError(try unpack(footer, with: make), name)
        }
    }

    func testAShortDownloadIsCaught() throws {
        let packed = Fixture.data("multiblock.img.xz")
        try each { name, make in
            for cut in [1, 100, packed.count / 2, packed.count - 1] {
                XCTAssertThrowsError(try unpack(packed.prefix(cut), with: make), "\(name), cut at \(cut)")
            }
            XCTAssertThrowsError(try unpack(Data(), with: make), name) { XCTAssertEqual($0 as? XZError, .truncated, name) }
        }
    }

    func testGarbageAfterTheEndIsCaught() throws {
        let one = Fixture.data("multiblock.img.xz")
        try each { name, make in
            XCTAssertThrowsError(try unpack(one + Data("junk".utf8), with: make), name)
            XCTAssertThrowsError(try unpack(Data("not an xz file at all".utf8), with: make), name)
        }
    }

    // MARK: Every option xz has (scripts/xz-fixtures.py)

    func testEveryCheckAndSetting() throws {
        let files = ["mixed-crc32.xz", "mixed-nocheck.xz", "mixed-sha256.xz", "mixed-lc1lp3pb4.xz", "mixed-dict4k.xz",
                     "mixed-blocks.xz", "mixed-9e.xz"]
        try each { name, make in
            for f in files {
                let (out, dec) = try unpack(Fixture.data(f), chunk: 7919, with: make)
                XCTAssertEqual(out.count, XZDecoderTests.mixedSize, "\(name), \(f)")
                XCTAssertEqual(sha256(out), XZDecoderTests.mixedSHA256, "\(name), \(f)")
                XCTAssertEqual(dec.streams, 1, "\(name), \(f)")
            }
        }
    }

    func testStoredChunksWithAndWithoutADictionaryReset() throws {
        try each { name, make in
            for chunk in [1, 65536 + 3, 1 << 20] {
                let (out, _) = try unpack(Fixture.data("random-first.xz"), chunk: chunk, with: make)
                XCTAssertEqual(out.count, XZDecoderTests.randomFirstSize, "\(name), chunk \(chunk)")
                XCTAssertEqual(sha256(out), XZDecoderTests.randomFirstSHA256, "\(name), chunk \(chunk)")
            }
        }
    }

    func testStreamsWithDifferentChecks() throws {
        let joined = Fixture.data("mixed-sha256.xz") + Data(count: 8) + Fixture.data("mixed-crc32.xz")
            + Fixture.data("mixed-nocheck.xz") + Fixture.data("multiblock.img.xz")
        try each { name, make in
            let (out, dec) = try unpack(joined, chunk: 100_003, with: make)
            XCTAssertEqual(dec.streams, 4, name)
            XCTAssertEqual(sha256(out.prefix(XZDecoderTests.mixedSize)), XZDecoderTests.mixedSHA256, name)
            XCTAssertEqual(sha256(out.suffix(Int(Fixture.cardSize))), Fixture.cardSHA256, name)
        }
    }

    /// A filter before LZMA2 (here x86 branch conversion): ours says what it doesn't unpack rather than guess.
    func testAFilterWeDontUnpackIsNamed() throws {
        XCTAssertThrowsError(try unpack(Fixture.data("mixed-x86.xz"), with: { try XZUnpacker() })) {
            XCTAssertEqual($0 as? XZError, .unsupported("filter 0x4"))
        }
    }

    /// Damage anywhere in a file, one bit at a time, at a spread of places: never a crash, and never different bytes
    /// without an error. Some damage changes nothing (a block of zeros reads the same with another `lc`, and `xz` would
    /// take it too); a file with no check can't tell. (Only for ours: these are the paths it wrote itself.)
    func testDamageAnywhereIsCaught() throws {
        for f in ["mixed-crc32.xz", "mixed-nocheck.xz", "random-first.xz", "mixed-blocks.xz"] {
            let good = Fixture.data(f)
            let want = f == "random-first.xz" ? XZDecoderTests.randomFirstSHA256 : XZDecoderTests.mixedSHA256
            var places = Array(stride(from: 0, to: good.count, by: max(1, good.count / 89)))
            places += Array(0..<min(48, good.count)) + Array(max(0, good.count - 24)..<good.count)
            for at in places {
                for flip: UInt8 in [0x01, 0x80] {
                    var bad = good
                    bad[at] ^= flip
                    if let (out, _) = try? unpack(bad, chunk: 4096, with: { try XZUnpacker() }), f != "mixed-nocheck.xz" {
                        XCTAssertEqual(sha256(out), want, "\(f): byte \(at) ^ \(flip) unpacked to other bytes without an error")
                    }
                }
            }
        }
    }

    func testBlockHeadersAndIndexesAreReadExactly() throws {
        var i = 0
        let buf: [UInt8] = [0x80, 0x01]
        XCTAssertEqual(try buf.withUnsafeBufferPointer { try XZUnpacker.vli($0, &i) }, 128)
        XCTAssertEqual(i, 2)
        i = 0
        XCTAssertNil(try [UInt8]([0x80]).withUnsafeBufferPointer { try XZUnpacker.vli($0, &i) })
        i = 0
        XCTAssertThrowsError(try [UInt8]([0x80, 0x00]).withUnsafeBufferPointer { try XZUnpacker.vli($0, &i) })
        i = 0
        XCTAssertThrowsError(try [UInt8](repeating: 0xFF, count: 10).withUnsafeBufferPointer { try XZUnpacker.vli($0, &i) })
    }

    func testCRCs() {
        let text = Array("123456789".utf8)
        text.withUnsafeBytes {
            XCTAssertEqual(CRC32.update(0, $0), 0xCBF4_3926)
            XCTAssertEqual(CRC64.update(0, $0), 0x995D_C9BB_DF19_39FA)
        }
        // Eight at a time and one at a time agree, at every length and start.
        let bytes = (0..<300).map { UInt8(truncatingIfNeeded: $0 &* 7 &+ 3) }
        bytes.withUnsafeBytes { all in
            for start in 0..<9 {
                for n in [0, 1, 7, 8, 9, 63, 64, 65, 200] where start + n <= all.count {
                    let slice = UnsafeRawBufferPointer(rebasing: all[start..<start + n])
                    var one: UInt64 = 0
                    for k in 0..<n { one = CRC64.update(one, UnsafeRawBufferPointer(rebasing: slice[k..<k + 1])) }
                    XCTAssertEqual(CRC64.update(0, slice), one, "start \(start), \(n) bytes")
                }
            }
        }
    }
}
