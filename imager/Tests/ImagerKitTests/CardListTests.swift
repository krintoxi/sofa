import Foundation
@testable import ImagerKit
import XCTest

/// The list, as `tools/sofa-box-imager-list.py` writes it. The fixture was made by that tool's own build() and
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

    /// A list with the Pi's cards and a PC's images (tools/sofa-box-imager-list.py's pc_entries): each target reads only
    /// its own, the Pi's as before; an entry that names no devices is a Pi's, as in lists from before the PC's.
    func testAPiOrAPC() throws {
        func entry(_ name: String, _ file: String, _ devices: [String]?) -> [String: Any] {
            var e: [String: Any] = ["name": name, "description": "x",
                                    "url": "https://github.com/krintoxi/sofa/releases/download/x/\(file)",
                                    "extract_size": 4_294_967_296, "image_download_size": 1_500_000_000,
                                    "extract_sha256": String(repeating: "cd", count: 32), "release_date": "2026-11-12",
                                    "init_format": "none"]
            if let devices { e["devices"] = devices }
            return e
        }
        let pi = ["pi5-64bit", "pi4-64bit", "pi3-64bit"], pc = ["sofa-box-pc-x86_64"]
        let doc: [String: Any] = ["os_list": [
            entry("Sofa Box OS 1.1.74", "sofa-box-os-1.1.74.img.xz", pi),
            ["name": "Sofa Box OS: earlier versions", "description": "1", "subitems": [entry("Sofa Box OS 1.1.73", "sofa-box-os-1.1.73.img.xz", pi)]],
            entry("Sofa Box OS 1.1.74 for a PC (testing)", "sofa-box-os-1.1.74-pc.img.xz", pc),
            ["name": "Sofa Box OS for a PC: earlier versions", "description": "1",
             "subitems": [entry("Sofa Box OS 1.1.73 for a PC (testing)", "sofa-box-os-1.1.73-pc.img.xz", pc)]],
            entry("An old entry", "sofa-box-os-1.1.40.img.xz", nil),
        ]]
        let data = try JSONSerialization.data(withJSONObject: doc)
        let forPi = try CardListParser.parse(data)
        XCTAssertEqual(forPi.newest?.name, "Sofa Box OS 1.1.74")
        XCTAssertEqual(forPi.others.map(\.name), ["An old entry"])
        XCTAssertEqual(forPi.earlierTitle, "Sofa Box OS: earlier versions")
        XCTAssertEqual(forPi.earlier.map(\.name), ["Sofa Box OS 1.1.73"])
        let forPC = try CardListParser.parse(data, for: .pc)
        XCTAssertEqual(forPC.newest?.name, "Sofa Box OS 1.1.74 for a PC (testing)")   // (all testing: the first is offered)
        XCTAssertEqual(forPC.newest?.url.lastPathComponent, "sofa-box-os-1.1.74-pc.img.xz")
        XCTAssertEqual(forPC.others, [])
        XCTAssertEqual(forPC.earlierTitle, "Sofa Box OS for a PC: earlier versions")
        XCTAssertEqual(forPC.earlier.map(\.name), ["Sofa Box OS 1.1.73 for a PC (testing)"])
        XCTAssertTrue(forPC.skipped.contains("An old entry: not for a PC"))
        // a list from before the PC's: nothing for a PC, said so
        XCTAssertThrowsError(try CardListParser.parse(Fixture.data("sofa-box.rpi-imager-manifest"), for: .pc)) { e in
            XCTAssertEqual(e as? CardListError, .noneFor(.pc))
            XCTAssertEqual((e as? CardListError)?.description, "The list has no Sofa Box OS for a PC yet.")
        }
        XCTAssertEqual(CardTarget.named("pc"), .pc)
        XCTAssertEqual(CardTarget.named("pi"), .raspberryPi)
        XCTAssertNil(CardTarget.named("toaster"))
        XCTAssertEqual(CardTarget.pc.word, "stick")
    }

    /// On a DVD: the disc's own file (.iso, downloaded as it is), only under the DVD's tag; never for a Pi or a stick.
    func testADVD() throws {
        func entry(_ name: String, _ file: String, _ devices: [String], download: Int64 = 1_500_000_000) -> [String: Any] {
            ["name": name, "description": "x", "url": "https://github.com/krintoxi/sofa/releases/download/x/\(file)",
             "extract_size": 1_500_000_256, "image_download_size": download,
             "extract_sha256": String(repeating: "ef", count: 32), "release_date": "2026-11-13", "devices": devices]
        }
        let pc = ["sofa-box-pc-x86_64"], dvd = ["sofa-box-pc-dvd"]
        let doc: [String: Any] = ["os_list": [
            entry("Sofa Box OS 1.1.85", "sofa-box-os-1.1.85.img.xz", ["pi4-64bit"], download: 1_400_000_000),
            entry("Sofa Box OS 1.1.85 for a PC (testing)", "sofa-box-os-1.1.85-pc.img.xz", pc, download: 1_400_000_000),
            entry("Sofa Box OS 1.1.85 on a DVD (testing)", "sofa-box-os-1.1.85-pc-dvd.iso", dvd, download: 1_500_000_256),
            entry("A packed DVD", "sofa-box-os-1.1.84-pc-dvd.img.xz", dvd, download: 1_400_000_000),
            entry("A DVD that's bigger to download", "sofa-box-os-1.1.83-pc-dvd.iso", dvd, download: 1_600_000_000),
        ]]
        let data = try JSONSerialization.data(withJSONObject: doc)
        let forDVD = try CardListParser.parse(data, for: .dvd)
        XCTAssertEqual(forDVD.all.map(\.name), ["Sofa Box OS 1.1.85 on a DVD (testing)"])
        XCTAssertEqual(forDVD.newest?.downloadSize, forDVD.newest?.extractSize)
        XCTAssertTrue(forDVD.skipped.contains("A packed DVD: not a disc's .iso"))
        XCTAssertTrue(forDVD.skipped.contains("A DVD that's bigger to download: no download size"))
        XCTAssertTrue(forDVD.skipped.contains("Sofa Box OS 1.1.85 for a PC (testing): not a disc's .iso"))
        XCTAssertEqual(try CardListParser.parse(data, for: .pc).all.map(\.name), ["Sofa Box OS 1.1.85 for a PC (testing)"])
        XCTAssertEqual(try CardListParser.parse(data).all.map(\.name), ["Sofa Box OS 1.1.85"])
        XCTAssertThrowsError(try CardListParser.parse(Fixture.data("sofa-box.rpi-imager-manifest"), for: .dvd)) { e in
            XCTAssertEqual((e as? CardListError)?.description, "The list has no Sofa Box OS DVD yet.")
        }
        XCTAssertEqual(CardTarget.named("dvd"), .dvd)
        XCTAssertEqual(CardTarget.dvd.word, "disc")
        XCTAssertEqual(CardTarget.dvd.choice, "On a DVD")
        XCTAssertTrue(CardTarget.dvd.burns)
        XCTAssertFalse(CardTarget.pc.burns)
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

    /// The list as it went up on the release on 2026-11-10, its first run (no version marked stable yet).
    func testReadsThePublishedList() throws {
        let list = try CardListParser.parse(Fixture.data("published-2026-11-10.rpi-imager-manifest"))
        XCTAssertEqual(list.newest?.name, "Sofa Box OS 1.1.58")
        XCTAssertEqual(list.newest?.url.absoluteString,
                       "https://github.com/krintoxi/sofa/releases/download/box-os-v1.1.58/sofa-box-os-1.1.58.img.xz")
        XCTAssertEqual(list.newest?.extractSize, 5_226_102_784)
        XCTAssertEqual(list.others, [])
        XCTAssertEqual(list.earlier.map(\.name), ["Sofa Box OS 1.1.54", "Sofa Box OS 1.1.49", "Sofa Box OS 1.1.48",
                                                  "Sofa Box OS 1.1.47", "Sofa Box OS 1.1.46"])
        XCTAssertEqual(list.earlier[0].extractSHA256, "8b1b6299541a101af1e03f761b150f1cc606a6f067cdca301a17ff927a913e5a")
        XCTAssertEqual(list.skipped, [])
    }

    /// Once a version is marked stable the list opens with it, then a newer version and the newest build, both "(testing)".
    func testTheStableVersionIsTheOneOffered() throws {
        func entry(_ name: String, _ tag: String, _ file: String) -> [String: Any] {
            ["name": name, "description": "x", "release_date": "2026-11-20",
             "url": "https://github.com/krintoxi/sofa/releases/download/\(tag)/\(file)",
             "extract_size": 1024, "image_download_size": 100, "extract_sha256": String(repeating: "ab", count: 32)]
        }
        let doc: [String: Any] = ["os_list": [
            entry("Sofa Box OS 1.1.58 (stable)", "box-os-v1.1.58", "sofa-box-os-1.1.58.img.xz"),
            entry("Sofa Box OS 1.1.60 (testing)", "box-os-v1.1.60", "sofa-box-os-1.1.60.img.xz"),
            entry("Sofa Box OS 1.1.60, newest build (testing)", "sofa-box", "sofa-box.img.xz"),
            ["name": "Sofa Box OS: earlier versions", "description": "1 earlier versions, newest first.",
             "subitems": [entry("Sofa Box OS 1.1.54", "box-os-v1.1.54", "sofa-box-os-1.1.54.img.xz")]],
        ]]
        let list = try CardListParser.parse(try JSONSerialization.data(withJSONObject: doc))
        XCTAssertEqual(list.newest?.name, "Sofa Box OS 1.1.58 (stable)")
        XCTAssertEqual(list.newest?.isTesting, false)
        XCTAssertEqual(list.others.map(\.name), ["Sofa Box OS 1.1.60 (testing)", "Sofa Box OS 1.1.60, newest build (testing)"])
        XCTAssertEqual(list.others.map(\.isTesting), [true, true])
        XCTAssertEqual(list.earlier.map(\.name), ["Sofa Box OS 1.1.54"])
    }

    func testTheDefaultAddressIsTheReleaseAsset() {
        XCTAssertEqual(CardListSource.defaultURL.absoluteString,
                       "https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.rpi-imager-manifest")
    }
}
