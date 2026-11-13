import Foundation
@testable import ImagerKit
import XCTest

/// On a DVD: which burner and disc can take Sofa Box OS, and hdiutil's progress lines.
final class BurningTests: XCTestCase {
    let needs: Int64 = 1_500_000_256
    func burner(_ disc: Burner.Disc?, writesDVD: Bool = true) -> Burner {
        Burner(id: "IOService:/x/IODVDServices", name: "HL-DT-ST DVDRW GX40N", writesDVD: writesDVD, disc: disc)
    }

    func testOnlyABlankDVDBigEnough() {
        let blank = Burner.Disc(type: "DVD-R", isDVD: true, isBlank: true, freeBytes: 4_700_372_992)
        XCTAssertNil(burner(blank).refusal(needs: needs))
        XCTAssertEqual(burner(blank).subtitle(needs: needs), "Blank DVD-R in it · 4.7 GB")
        XCTAssertEqual(burner(nil).refusal(needs: needs), "No disc in it: put a blank DVD in (DVD-R or DVD+R).")
        XCTAssertEqual(burner(blank, writesDVD: false).refusal(needs: needs), "It doesn't burn DVDs.")
        XCTAssertEqual(burner(.init(type: "CD-R", isDVD: false, isBlank: true, freeBytes: 700_000_000)).refusal(needs: needs),
                       "The disc in it is a CD-R, not a DVD.")
        XCTAssertEqual(burner(.init(type: "DVD-RW", isDVD: true, isBlank: false, freeBytes: 0)).refusal(needs: needs),
                       "The DVD-RW in it isn't blank.")                     // (never erased by Sofa Box Imager)
        XCTAssertEqual(burner(.init(type: "DVD+R", isDVD: true, isBlank: true, freeBytes: 1_000_000_000)).refusal(needs: needs),
                       "The DVD+R in it holds 1 GB; Sofa Box OS needs 1.5 GB.")
    }

    func testHdiutilsProgressLines() {
        XCTAssertEqual(BurnOutput.parse("PERCENT:42.500000"), .percent(0.425))
        XCTAssertEqual(BurnOutput.parse("PERCENT:-1.000000"), .percent(nil))
        XCTAssertEqual(BurnOutput.parse("PERCENT:100"), .percent(1))
        XCTAssertEqual(BurnOutput.parse("MESSAGE:Verifying burn…\n"), .message("Verifying burn…"))
        XCTAssertEqual(BurnOutput.parse("hdiutil: burn failed"), .other("hdiutil: burn failed"))
        XCTAssertTrue(BurnOutput.isVerifying("Verifying burn…"))
        XCTAssertFalse(BurnOutput.isVerifying("Preparing data for burn"))
    }
}
