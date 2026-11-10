import AppKit
@testable import ImagerKit
import ImagerMac
@testable import SofaBoxImager
import SwiftUI
import XCTest

/// The app's own words and window, with made-up cards and disks: nothing here looks at a real disk or the network.
@MainActor
final class WindowTests: XCTestCase {
    static let list: CardList = {
        func card(_ name: String, _ day: String, _ tag: String) -> Card {
            Card(name: name, summary: "", url: URL(string: "https://github.com/krintoxi/sofa/releases/download/\(tag).img.xz")!,
                 downloadSize: 1_367_936_428, extractSize: 5_226_102_784,
                 extractSHA256: "8b1b6299541a101af1e03f761b150f1cc606a6f067cdca301a17ff927a913e5a",
                 releaseDate: day, website: nil)
        }
        return CardList(newest: card("Sofa Box OS 1.1.54", "2026-11-10", "box-os-v1.1.54/sofa-box-os-1.1.54"),
                        others: [], earlierTitle: "Sofa Box OS: earlier versions",
                        earlier: [card("Sofa Box OS 1.1.49", "2026-11-09", "box-os-v1.1.49/sofa-box-os-1.1.49")],
                        skipped: [])
    }()

    static let sdCard = DiskDescription(
        bsdName: "disk4", sizeBytes: 63_864_569_856, isInternal: false, isRemovable: true, isEjectable: true,
        protocolName: "USB", vendor: "Generic", model: "STORAGE DEVICE", mediaName: "Generic STORAGE DEVICE Media",
        ioClassChain: ["IOMedia", "IOBlockStorageDriver", "IOSCSIPeripheralDeviceType00"],
        volumes: [MountedVolume(name: "bootfs", mountPoint: "/Volumes/bootfs", bsdName: "disk4s1")])
    static let builtIn = DiskDescription(
        bsdName: "disk5", sizeBytes: 31_914_983_424, isInternal: true, isRemovable: true, isEjectable: true,
        protocolName: "Secure Digital", vendor: "Apple", model: "SDXC Reader", mediaName: "SDXC Card",
        iconFile: "SD.icns", ioClassChain: ["IOMedia", "IOBlockStorageDriver", "AppleSDXCBlockStorageDevice"])
    static let backup = DiskDescription(
        bsdName: "disk6", sizeBytes: 1_000_204_886_016, isInternal: false, isRemovable: false, isEjectable: true,
        protocolName: "USB", vendor: "Samsung", model: "PSSD T7", mediaName: "Samsung PSSD T7 Media",
        ioClassChain: ["IOMedia", "IOBlockStorageDriver", "IOSCSIPeripheralDeviceType00"])

    private func model(_ phase: ImagerModel.Phase = .choosing) -> ImagerModel {
        let m = ImagerModel(live: false)
        m.list = .loaded(Self.list)
        m.card = Self.list.newest
        m.offered = [Self.sdCard, Self.builtIn]
        m.refused = [(Self.backup, DiskPolicy.refusals(for: Self.backup, needs: 5_226_102_784))]
        m.diskName = "disk4"
        m.phase = phase
        return m
    }

    func testWhatsChosenIsWhatsWritten() {
        let m = model()
        XCTAssertEqual(m.chosenDisk?.bsdName, "disk4")
        XCTAssertFalse(m.isWriting)
        m.askToWrite()
        XCTAssertTrue(m.confirming)
        // A disk that's no longer offered can't be chosen.
        m.offered = [Self.builtIn]
        XCTAssertNil(m.chosenDisk)
        m.confirming = false
        m.askToWrite()
        XCTAssertFalse(m.confirming)
        // No version, no write.
        m.offered = [Self.sdCard]
        m.card = nil
        m.askToWrite()
        XCTAssertFalse(m.confirming)
    }

    /// One look everywhere: the colours are Sofa's own, read from its style sheet, and its fonts load.
    func testTheLookIsSofas() throws {
        let css = try String(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../../client/sofa.css").standardizedFileURL, encoding: .utf8)
        let root = String(css[css.range(of: ":root {")!.upperBound...].prefix(1200))
        for (name, value) in [("--ink", SofaTheme.ink), ("--slate", SofaTheme.slate), ("--slate-2", SofaTheme.slate2),
                              ("--slate-3", SofaTheme.slate3), ("--paper", SofaTheme.paper), ("--soft", SofaTheme.soft),
                              ("--mist", SofaTheme.mist), ("--amber", SofaTheme.amber), ("--amber-hi", SofaTheme.amberHi),
                              ("--amber-ink", SofaTheme.amberInk), ("--green", SofaTheme.green), ("--alert", SofaTheme.alert)] {
            XCTAssertTrue(root.contains("\(name): #\(String(format: "%06X", value))"), name)
        }
        XCTAssertTrue(SofaFonts.loaded)
    }

    func testPartsOfOtherDisksArentListedAsRefused() {
        XCTAssertTrue(ImagerModel.isQuietlySkipped(Self.backup, [.notPhysical, .insideTheMac]))
        XCTAssertFalse(ImagerModel.isQuietlySkipped(Self.backup, [.tooLarge(limit: 1)]))
        XCTAssertFalse(ImagerModel.isQuietlySkipped(Self.backup, [.diskImage, .notPhysical]))
    }

    func testProgressInWords() async {
        var said: [(String, Double?)] = []
        let r = StageReporter { text, fraction in said.append((text, fraction)) }
        r.report(.checking)
        r.report(.unmounting)
        r.report(.waitingForPassword)
        r.report(.writing(WriteProgress(phase: .writing, done: 250, total: 1000)))
        r.report(.writing(WriteProgress(phase: .verifying, done: 1000, total: 1000)))
        r.report(.ejecting)
        r.report(.done)
        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(said.map(\.0), ["Checking the card…", "Unmounting the card's volumes…", "Waiting for your password…",
                                       "Downloading and writing… 25%", "Checking every byte on the card… 100%",
                                       "Ejecting the card…", "Done."])
        XCTAssertEqual(said[3].1, 0.25)
        XCTAssertNil(said[0].1)
    }

    /// The app never names what it must not: it isn't Raspberry Pi's Imager, and it sets nothing on the card.
    func testTheAppsOwnWords() throws {
        let sources = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../Sources").standardizedFileURL
        var text = ""
        for case let f as URL in FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil)! {
            if ["swift", "c", "h"].contains(f.pathExtension) { text += try String(contentsOf: f, encoding: .utf8) }
        }
        // What the app says, not the notes to whoever reads its code: comments are left out.
        text = text.split(separator: "\n", omittingEmptySubsequences: false).map { line -> String in
            let l = String(line)
            if l.trimmingCharacters(in: .whitespaces).hasPrefix("//") { return "" }
            if let r = l.range(of: #"\s{2,}//\s.*$"#, options: .regularExpression) { return String(l[..<r.lowerBound]) }
            return l
        }.joined(separator: "\n")
        XCTAssertTrue(text.contains("Sofa Box Imager"))
        let info = try String(contentsOf: sources.appendingPathComponent("../Resources/Info.plist"), encoding: .utf8)
        XCTAssertFalse((text + info).contains("Raspberry Pi Imager"))
        XCTAssertFalse((text + info).lowercased().contains("internet archive"))
        XCTAssertFalse((text + info).lowercased().contains("archive.org"))
        XCTAssertTrue(info.contains("<string>Sofa Box Imager</string>"))
        // No OS customisation: nothing in the app writes a user, a password of its own, SSH or Wi-Fi settings.
        for word in ["firstrun", "user-data", "userconf", "wpa_supplicant", "ssh_authorized", "cloud-init", "rpi-preseed"] {
            XCTAssertFalse(text.lowercased().contains(word), word)
        }
    }

    /// Draws each screen to a PNG, to look at: SOFA_IMAGER_SNAPSHOTS=<folder> swift test --filter WindowTests
    func testDrawTheWindow() throws {
        guard let folder = ProcessInfo.processInfo.environment["SOFA_IMAGER_SNAPSHOTS"], !folder.isEmpty else {
            throw XCTSkip("set SOFA_IMAGER_SNAPSHOTS to a folder to draw the screens")
        }
        // The test process has no bundle, so no icon of its own: give it the app's (Sofa's).
        let icon = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../../client/icons/icon-512.png").standardizedFileURL
        NSApplication.shared.applicationIconImage = NSImage(contentsOf: icon)
        XCTAssertTrue(SofaFonts.loaded, "Sofa's fonts didn't load")
        let size = CGSize(width: 640, height: 620)
        for (name, look) in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
            let out = URL(fileURLWithPath: folder).appendingPathComponent(name)
            try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
            try draw(ContentView().environmentObject(model()), size, look, out.appendingPathComponent("1-choose.png"))
            try draw(ConfirmView().environmentObject(model()), CGSize(width: 480, height: 420), look,
                     out.appendingPathComponent("2-confirm.png"))
            try draw(ContentView().environmentObject(model(.running("Downloading and writing… 42% · 14.2 MB/s", 0.42))),
                     size, look, out.appendingPathComponent("3-writing.png"))
            try draw(ContentView().environmentObject(model(.done(card: "Sofa Box OS 1.1.54", disk: "Generic STORAGE DEVICE"))),
                     size, look, out.appendingPathComponent("4-done.png"))
            try draw(ContentView().environmentObject(model(.failed(WriteError.verifyMismatch.description))),
                     size, look, out.appendingPathComponent("5-failed.png"))
            let empty = model()
            empty.offered = []
            empty.diskName = nil
            try draw(ContentView().environmentObject(empty), size, look, out.appendingPathComponent("6-no-card.png"))
        }
    }

    private func draw(_ view: some View, _ size: CGSize, _ look: NSAppearance.Name, _ url: URL) throws {
        let host = NSHostingView(rootView: view.frame(width: size.width, height: size.height)
            .background(Color.ink))
        host.frame = CGRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: look)
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.4))
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        try XCTUnwrap(rep.representation(using: .png, properties: [:])).write(to: url)
    }
}
