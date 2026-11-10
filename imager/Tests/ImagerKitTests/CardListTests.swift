import Foundation
@testable import ImagerKit
import XCTest

/// The list, as `tools/sofa-box-imager-list.py` (PR #35) writes it. The fixture was made by that tool's own build() and
/// check() from made-up releases; 1.1.54's sizes and SHA-256 are the real card's, the other versions are invented.
final class CardListTests: XCTestCase {
    func testReadsTheListTheToolWrites() throws {
        let list = try CardListParser.parse(Fixture.data("sofa-box.rpi-imager-manifest"))
        XCTAssertEqual(list.newest?.name, "Sofa Box OS 1.1.55")
        XCTAssertEqual(list.newest?.releaseDate, "2026-11-11")
        XCTAssertEqual(list.others.map(\.name), ["Sofa Box OS 1.1.56, newest build (testing)"])
        XCTAssertTrue(list.others[0].isTesting)
        XCTAssertEqual(list.earlierTitle, "Sofa Box OS: earlier versions")
        XCTAssertEqual(list.earlier.map(\.name), ["Sofa Box OS 1.1.54", "Sofa Box OS 1.1.49"])
        XCTAssertEqual(list.skipped, [])
        let real = list.earlier[0]
        XCTAssertEqual(real.downloadSize, 1_367_936_428)
        XCTAssertEqual(real.extractSize, 5_226_102_784)
        XCTAssertEqual(real.extractSHA256, "8b1b6299541a101af1e03f761b150f1cc606a6f067cdca301a17ff927a913e5a")
        XCTAssertEqual(real.url.absoluteString,
                       "https://github.com/krintoxi/sofa/releases/download/box-os-v1.1.54/sofa-box-os-1.1.54.img.xz")
        XCTAssertEqual(real.website?.absoluteString, "https://github.com/krintoxi/sofa/releases/tag/box-os-v1.1.54")
        XCTAssertEqual(list.all.count, 4)
    }

    private func one(_ fields: [String: Any], allowLocalFiles: Bool = false) throws -> CardList {
        var e: [String: Any] = [
            "name": "Sofa Box OS 9.9.9", "description": "x",
            "url": "https://github.com/krintoxi/sofa/releases/download/box-os-v9.9.9/sofa-box-os-9.9.9.img.xz",
            "extract_size": 5_226_102_784, "image_download_size": 1_367_936_428,
            "extract_sha256": String(repeating: "ab", count: 32), "release_date": "2026-11-10",
            "devices": ["pi5-64bit", "pi4-64bit", "pi3-64bit"], "init_format": "none",
        ]
        for (k, v) in fields { e[k] = v is NSNull ? nil : v }
        let doc: [String: Any] = ["os_list": [e]]
        return try CardListParser.parse(try JSONSerialization.data(withJSONObject: doc), allowLocalFiles: allowLocalFiles)
    }

    private func assertSkipped(_ fields: [String: Any], file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertThrowsError(try one(fields), file: file, line: line) { e in
            XCTAssertEqual(e as? CardListError, .noCards, file: file, line: line)
        }
    }

    func testAGoodEntry() throws {
        let c = try XCTUnwrap(try one([:]).newest)
        XCTAssertEqual(c.extractSize, 5_226_102_784)
        XCTAssertFalse(c.isTesting)
    }

    func testEntriesThatCantBeCheckedAreLeftOut() {
        assertSkipped(["url": "http://github.com/krintoxi/sofa/releases/download/x/sofa-box.img.xz"])
        assertSkipped(["url": "file:///tmp/sofa-box.img.xz"])                    // only from a list on this Mac
        assertSkipped(["url": "https://example.com/sofa-box.zip"])
        assertSkipped(["url": NSNull()])
        assertSkipped(["extract_sha256": NSNull()])
        assertSkipped(["extract_sha256": String(repeating: "AB", count: 32)])   // the tool writes lowercase
        assertSkipped(["extract_sha256": String(repeating: "a", count: 63)])
        assertSkipped(["extract_sha256": String(repeating: "g", count: 64)])
        assertSkipped(["extract_size": NSNull()])
        assertSkipped(["extract_size": 0])
        assertSkipped(["extract_size": -512])
        assertSkipped(["extract_size": 5_226_102_785])                            // not whole sectors
        assertSkipped(["extract_size": 1.5])
        assertSkipped(["image_download_size": NSNull()])
        assertSkipped(["image_download_size": 6_000_000_000])                     // bigger than it unpacks to
        assertSkipped(["devices": ["pi2-32bit"]])
        assertSkipped(["name": ""])
    }

    func testLocalFilesOnlyFromALocalList() throws {
        let c = try one(["url": "file:///tmp/sofa-box.img.xz"], allowLocalFiles: true)
        XCTAssertEqual(c.newest?.url.scheme, "file")
    }

    func testOddDatesAndWebsitesAreDropped() throws {
        let c = try XCTUnwrap(try one(["release_date": "yesterday", "website": "http://example.com"]).newest)
        XCTAssertEqual(c.releaseDate, "")
        XCTAssertNil(c.website)
    }

    func testNotAList() {
        XCTAssertThrowsError(try CardListParser.parse(Data("<html>".utf8))) { XCTAssertEqual($0 as? CardListError, .notJSON) }
        XCTAssertThrowsError(try CardListParser.parse(Data(#"{"os_list": []}"#.utf8))) {
            XCTAssertEqual($0 as? CardListError, .noCards)
        }
        XCTAssertThrowsError(try CardListParser.parse(Data(count: CardListSource.largestList + 1))) {
            XCTAssertEqual($0 as? CardListError, .tooBig)
        }
    }

    func testTestingFirstStillPicksTheNumberedVersion() throws {
        let numbered: [String: Any] = [
            "name": "Sofa Box OS 1.1.55", "description": "x",
            "url": "https://github.com/krintoxi/sofa/releases/download/box-os-v1.1.55/sofa-box-os-1.1.55.img.xz",
            "extract_size": 1024, "image_download_size": 100, "extract_sha256": String(repeating: "cd", count: 32),
        ]
        var testing = numbered
        testing["name"] = "Sofa Box OS 1.1.56, newest build (testing)"
        testing["url"] = "https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.img.xz"
        let doc: [String: Any] = ["os_list": [testing, numbered]]
        let list = try CardListParser.parse(try JSONSerialization.data(withJSONObject: doc))
        XCTAssertEqual(list.newest?.name, "Sofa Box OS 1.1.55")
        XCTAssertEqual(list.others.map(\.isTesting), [true])
    }

    func testTheDefaultAddressIsTheReleaseAsset() {
        XCTAssertEqual(CardListSource.defaultURL.absoluteString,
                       "https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.rpi-imager-manifest")
    }
}
