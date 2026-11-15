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

    static let stick = DiskDescription(
        bsdName: "disk7", sizeBytes: 32_015_679_488, isInternal: false, isRemovable: true, isEjectable: true,
        protocolName: "USB", vendor: "SanDisk", model: "Ultra", mediaName: "SanDisk Ultra Media",
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

    func testProgressInWordsForAStick() async {
        var said: [String] = []
        let r = StageReporter(word: CardTarget.pc.word) { text, _ in said.append(text) }
        r.report(.checking)
        r.report(.unmounting)
        r.report(.writing(WriteProgress(phase: .verifying, done: 1000, total: 1000)))
        r.report(.ejecting)
        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(said, ["Checking the stick…", "Unmounting the stick's volumes…", "Checking every byte on the stick… 100%",
                              "Ejecting the stick…"])
    }

    /// For a PC: the same list read again for a PC's images, the version offered is a PC's, and a stick is asked for.
    func testForAPC() throws {
        let m = ImagerModel(live: false)
        let entry: (String, String, [String]) -> [String: Any] = { name, file, devices in
            ["name": name, "description": "x", "url": "https://github.com/krintoxi/sofa/releases/download/x/\(file)",
             "extract_size": 4_294_967_296, "image_download_size": 1_500_000_000,
             "extract_sha256": String(repeating: "cd", count: 32), "release_date": "2026-11-12", "devices": devices]
        }
        let doc: [String: Any] = ["os_list": [entry("Sofa Box OS 1.1.74", "sofa-box-os-1.1.74.img.xz", ["pi4-64bit"]),
                                              entry("Sofa Box OS 1.1.74 for a PC (testing)", "sofa-box-os-1.1.74-pc.img.xz",
                                                    ["sofa-box-pc-x86_64"])]]
        m.use(listData: try JSONSerialization.data(withJSONObject: doc))
        XCTAssertEqual(m.card?.name, "Sofa Box OS 1.1.74")
        m.target = .pc
        XCTAssertEqual(m.card?.name, "Sofa Box OS 1.1.74 for a PC (testing)")
        m.target = .raspberryPi
        XCTAssertEqual(m.card?.name, "Sofa Box OS 1.1.74")
        m.use(listData: try JSONSerialization.data(withJSONObject: ["os_list": [doc["os_list"].map { ($0 as! [Any])[0] }!]]))
        m.target = .pc
        XCTAssertEqual(m.list, .failed("The list has no Sofa Box OS for a PC yet."))
        XCTAssertNil(m.card)
    }

    static let dvdCard = Card(name: "Sofa Box OS 1.1.85 for a PC (testing)", summary: "",
                              url: URL(string: "https://github.com/krintoxi/sofa/releases/download/box-os-v1.1.85/sofa-box-os-1.1.85-pc-dvd.iso")!,
                              downloadSize: 1_512_634_368, extractSize: 1_512_634_368,
                              extractSHA256: String(repeating: "ef", count: 32), releaseDate: "2026-11-13", website: nil)
    static let superDrive = Burner(id: "IOService:/a/IODVDServices", name: "Apple SuperDrive", writesDVD: true,
                                   disc: .init(type: "DVD-R", isDVD: true, isBlank: true, freeBytes: 4_700_372_992))
    static let oldDrive = Burner(id: "IOService:/b/IODVDServices", name: "HL-DT-ST DVDRW GX40N", writesDVD: true, disc: nil)

    private func dvdModel(_ phase: ImagerModel.Phase = .choosing) -> ImagerModel {
        let m = model(phase)
        m.target = .dvd
        m.list = .loaded(CardList(newest: Self.dvdCard, others: [], earlierTitle: "", earlier: [], skipped: []))
        m.card = Self.dvdCard
        m.burners = [Self.superDrive, Self.oldDrive]
        m.burnerID = Self.superDrive.id
        return m
    }

    /// On a DVD: the list read for the DVD's file, a burner with a blank DVD is what's chosen, and nothing else is.
    func testOnADVD() throws {
        let m = ImagerModel(live: false)
        let entry: (String, String, [String], Int64) -> [String: Any] = { name, file, devices, download in
            ["name": name, "description": "x", "url": "https://github.com/krintoxi/sofa/releases/download/x/\(file)",
             "extract_size": 1_512_634_368, "image_download_size": download,
             "extract_sha256": String(repeating: "ef", count: 32), "release_date": "2026-11-13", "devices": devices]
        }
        m.use(listData: try JSONSerialization.data(withJSONObject: ["os_list": [
            entry("Sofa Box OS 1.1.85 for a PC (testing)", "sofa-box-os-1.1.85-pc.img.xz", ["sofa-box-pc-x86_64"], 1_400_000_000),
            entry("Sofa Box OS 1.1.85 for a PC, on a DVD (testing)", "sofa-box-os-1.1.85-pc-dvd.iso", ["sofa-box-pc-dvd"], 1_512_634_368)]]))
        m.target = .dvd
        XCTAssertEqual(m.card?.name, "Sofa Box OS 1.1.85 for a PC, on a DVD (testing)")
        m.burners = [Self.oldDrive]
        m.burnerID = Self.oldDrive.id                         // no disc in it: never the one chosen
        XCTAssertNil(m.chosenBurner)
        XCTAssertFalse(m.canGo)
        m.askToWrite()
        XCTAssertFalse(m.confirming)
        m.burners = [Self.superDrive, Self.oldDrive]
        m.burnerID = Self.superDrive.id
        XCTAssertEqual(m.chosenBurner, Self.superDrive)
        XCTAssertTrue(m.canGo)
        m.askToWrite()
        XCTAssertTrue(m.confirming)
        m.target = .pc                                        // a stick needs a disk, not a burner
        XCTAssertFalse(m.canGo)
    }

    func testProgressInWordsForADVD() async {
        var said: [(String, Double?)] = []
        let r = BurnReporter { text, fraction in said.append((text, fraction)) }
        r.report(.checking)
        r.report(.downloading(done: 500, total: 1000))
        try? await Task.sleep(nanoseconds: 150_000_000)
        r.report(.checkingDownload)
        r.report(.burning(0.3))
        try? await Task.sleep(nanoseconds: 150_000_000)
        r.report(.verifying(nil))
        try? await Task.sleep(nanoseconds: 150_000_000)
        r.report(.verifying(0.8))
        r.report(.done)
        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(said.map(\.0), ["Checking the burner and the disc…", "Downloading… 50%", "Checking the download…",
                                       "Burning… 30%", "Checking the disc…", "Checking the disc… 80%", "Done."])
        XCTAssertEqual(said[1].1, 0.5)
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
        // No OS customisation: nothing in the app writes a user, a password of its own, SSH or Wi-Fi settings onto a
        // card or a Linux stick. (The one setup file it can write is a Windows 11 stick's autounattend.xml, and only for
        // the switches the owner ticks: WindowsStickTests checks what's in it.)
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
        let size = CGSize(width: 680, height: 700)
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
            // for a PC: a USB stick
            let pc = model()
            pc.target = .pc
            let pcCard = Card(name: "Sofa Box OS 1.1.74 for a PC (testing)", summary: "",
                              url: URL(string: "https://github.com/krintoxi/sofa/releases/download/box-os-v1.1.74/sofa-box-os-1.1.74-pc.img.xz")!,
                              downloadSize: 1_500_000_000, extractSize: 4_294_967_296,
                              extractSHA256: String(repeating: "cd", count: 32), releaseDate: "2026-11-12", website: nil)
            pc.list = .loaded(CardList(newest: pcCard, others: [], earlierTitle: "", earlier: [], skipped: []))
            pc.card = pcCard
            pc.offered = [Self.stick]
            pc.diskName = "disk7"
            try draw(ContentView().environmentObject(pc), size, look, out.appendingPathComponent("7-pc-choose.png"))
            let pcDone = model(.done(card: "Sofa Box OS 1.1.74 for a PC (testing)", disk: "SanDisk Ultra"))
            pcDone.target = .pc
            try draw(ContentView().environmentObject(pcDone), size, look, out.appendingPathComponent("8-pc-done.png"))
            // on a DVD: a burner with a blank DVD, one without a disc
            try draw(ContentView().environmentObject(dvdModel()), size, look, out.appendingPathComponent("9-dvd-choose.png"))
            try draw(ConfirmView().environmentObject(dvdModel()), CGSize(width: 480, height: 330), look,
                     out.appendingPathComponent("10-dvd-confirm.png"))
            try draw(ContentView().environmentObject(dvdModel(.running("Burning… 37%", 0.37))), size, look,
                     out.appendingPathComponent("11-dvd-burning.png"))
            try draw(ContentView().environmentObject(dvdModel(.done(card: "Sofa Box OS 1.1.85 for a PC (testing)", disk: "Apple SuperDrive"))),
                     size, look, out.appendingPathComponent("12-dvd-done.png"))
            let none = dvdModel()
            none.burners = []
            none.burnerID = nil
            try draw(ContentView().environmentObject(none), size, look, out.appendingPathComponent("13-dvd-no-burner.png"))
            // Linux, Windows, your own image
            try draw(ContentView().environmentObject(linuxModel()), size, look, out.appendingPathComponent("14-linux.png"))
            let w = windowsModel()
            try draw(ContentView().environmentObject(w), size, look, out.appendingPathComponent("15-windows.png"))
            w.skipHardwareChecks = true
            w.useLocalAccount = true
            w.accountName = "Den"
            try draw(ContentView().environmentObject(w), size, look, out.appendingPathComponent("16-windows-switches.png"))
            w.confirming = true
            try draw(ConfirmView().environmentObject(w), CGSize(width: 480, height: 460), look,
                     out.appendingPathComponent("17-windows-confirm.png"))
            let wDone = windowsModel(.done(card: "Windows 11 (x64)", disk: "SanDisk Ultra"))
            try draw(ContentView().environmentObject(wDone), size, look, out.appendingPathComponent("18-windows-done.png"))
            let wEmpty = windowsModel()
            wEmpty.windowsFile = .none
            try draw(ContentView().environmentObject(wEmpty), size, look, out.appendingPathComponent("19-windows-empty.png"))
            try draw(ContentView().environmentObject(fileModel(.hybridISO(partitions: .gpt))), size, look,
                     out.appendingPathComponent("20-own-image.png"))
            try draw(ContentView().environmentObject(fileModel(.discOnly)), size, look,
                     out.appendingPathComponent("21-own-image-dvd-only.png"))
            // Windows 7 on a DVD
            let w7 = windowsModel()
            var seven = Self.eleven
            seven.version = .seven
            seven.build = 7601
            seven.editions = ["Windows 7 Ultimate"]
            seven.fileBytes = 3_220_000_000
            w7.windowsFile = .read(URL(fileURLWithPath: "/Users/someone/Downloads/Win7_Ult_SP1_English_x64.iso"),
                                   .windows(seven), 3_224_686_592)
            w7.toDisc = true
            w7.burners = [Self.superDrive]
            w7.burnerID = Self.superDrive.id
            try draw(ContentView().environmentObject(w7), size, look, out.appendingPathComponent("22-windows7-dvd.png"))
            w7.confirming = true
            try draw(ConfirmView().environmentObject(w7), CGSize(width: 480, height: 360), look,
                     out.appendingPathComponent("23-windows7-dvd-confirm.png"))
        }
    }

    static let ubuntu = Card(name: "Ubuntu Desktop 26.04.1 LTS", summary: "",
                             url: URL(string: "https://releases.ubuntu.com/26.04/ubuntu-26.04.1-desktop-amd64.iso")!,
                             downloadSize: 6_482_409_472, extractSize: 6_482_409_472,
                             extractSHA256: "601e30fbf5d97759367c632e2c33630665039b7e2158fd068403da3ccf1bda1f",
                             releaseDate: "", website: nil)
    static let eleven = WindowsMedia(version: .eleven, build: 26300, arch: .x64,
                                     editions: ["Windows 11 Home", "Windows 11 Pro"], installPath: "sources/install.wim",
                                     installBytes: 8_161_000_000, installIsSolid: false, volumeName: "CCCOMA_X64FRE_EN-US_DV9",
                                     biosBoot: true, bootmgrBytes: 484_000, uefi: .onTheISO("efi/boot/bootx64.efi"),
                                     fileBytes: 9_040_000_000, fileCount: 1073, hasUnattend: false)

    private func linuxModel(_ phase: ImagerModel.Phase = .choosing) -> ImagerModel {
        let m = model(phase)
        m.mode = .linux
        m.use(system: Self.ubuntu, for: "ubuntu")
        m.offered = [Self.stick]
        m.diskName = "disk7"
        return m
    }

    private func windowsModel(_ phase: ImagerModel.Phase = .choosing) -> ImagerModel {
        let m = model(phase)
        m.mode = .windows
        m.windowsFile = .read(URL(fileURLWithPath: "/Users/someone/Downloads/Win11_26300_English_x64.iso"),
                              .windows(Self.eleven), 9_047_330_816)
        m.offered = [Self.stick]
        m.diskName = "disk7"
        return m
    }

    private func fileModel(_ kind: ImageKind) -> ImagerModel {
        let m = model()
        m.mode = .file
        m.ownFile = .read(URL(fileURLWithPath: "/Users/someone/Downloads/some-system.iso"), kind, 2_925_092_864)
        m.offered = [Self.stick]
        m.diskName = "disk7"
        return m
    }

    /// Linux, Windows and your own image: what's written, onto what, in the words the window uses.
    func testEachModeWritesWhatsChosen() {
        let l = linuxModel()
        XCTAssertEqual(l.word, "stick")
        XCTAssertEqual(l.item?.name, "Ubuntu Desktop 26.04.1 LTS")
        XCTAssertEqual(l.item?.needs, 6_482_409_472)
        XCTAssertTrue(l.canGo)
        l.systemID = "raspios"                       // not found yet: nothing to write
        XCTAssertEqual(l.word, "card")
        XCTAssertNil(l.item)
        XCTAssertFalse(l.canGo)

        let w = windowsModel()
        XCTAssertEqual(w.item?.name, "Windows 11 (x64)")
        XCTAssertEqual(w.item?.needs, Self.eleven.stickBytesNeeded)
        XCTAssertTrue(w.windowsOptions.isEmpty, "every switch is off until ticked")
        XCTAssertTrue(w.canGo)
        w.useLocalAccount = true                    // ticked, with no name yet
        XCTAssertNotNil(w.optionsProblem)
        XCTAssertFalse(w.canGo)
        w.accountName = "Den"
        XCTAssertTrue(w.canGo)
        XCTAssertEqual(w.windowsOptions, WindowsOptions(localAccount: "Den"))
        // The switches are Windows 11's: a Windows 10 ISO never carries them.
        var ten = Self.eleven
        ten.version = .ten
        w.windowsFile = .read(URL(fileURLWithPath: "/x.iso"), .windows(ten), 1)
        XCTAssertTrue(w.windowsOptions.isEmpty)
        // An ISO that isn't Windows writes nothing here.
        w.windowsFile = .read(URL(fileURLWithPath: "/x.iso"), .discOnly, 1)
        XCTAssertNil(w.item)
        XCTAssertFalse(w.canGo)

        XCTAssertEqual(fileModel(.hybridISO(partitions: .mbr)).item?.name, "some-system.iso")
        XCTAssertNil(fileModel(.discOnly).item)
        XCTAssertNil(fileModel(.unknown).item)
        XCTAssertNil(fileModel(.windows(Self.eleven)).item, "a Windows ISO is made into a stick, never written whole")
    }

    /// On a DVD: a Windows ISO or one of the owner's own, burned as it is; sized against what a DVD holds; never with
    /// the Windows 11 switches (the disc is Microsoft's ISO, unchanged).
    func testWindowsAndOwnISOsOnADVD() {
        let w = windowsModel()
        w.skipHardwareChecks = true
        w.toDisc = true
        XCTAssertTrue(w.burns)
        XCTAssertTrue(w.windowsOptions.isEmpty, "a DVD carries no switches")
        XCTAssertEqual(w.burnBytes, 9_047_330_816)
        let dl = Burner(id: "IOService:/c/IODVDServices", name: "Pioneer BDR-XD08", writesDVD: true,
                        disc: .init(type: "DVD+R DL", isDVD: true, isBlank: true, freeBytes: 8_547_991_552))
        w.burners = [dl]
        w.burnerID = dl.id
        XCTAssertNil(w.chosenBurner, "Windows 11's 9 GB ISO fits no DVD")
        XCTAssertFalse(w.canGo)
        // Windows 7: 3.2 GB, a single-layer DVD.
        var seven = Self.eleven
        seven.version = .seven
        w.windowsFile = .read(URL(fileURLWithPath: "/Users/someone/Downloads/Win7_Ult_SP1_English_x64.iso"), .windows(seven),
                              3_224_686_592)
        w.burners = [Self.superDrive]
        w.burnerID = Self.superDrive.id
        XCTAssertEqual(w.chosenBurner, Self.superDrive)
        XCTAssertEqual(w.burnTitle, "Windows 7 (x64)")
        XCTAssertTrue(w.canGo)
        w.askToWrite()
        XCTAssertTrue(w.confirming)
        // Back to a stick: a disk, not a burner.
        w.toDisc = false
        XCTAssertFalse(w.burns)
        // Your own image: an ISO burns, a disk image doesn't.
        let own = fileModel(.discOnly)
        own.toDisc = true
        own.burners = [Self.superDrive]
        own.burnerID = Self.superDrive.id
        XCTAssertNotNil(own.discISO)
        XCTAssertTrue(own.canGo)
        let img = fileModel(.diskImage(partitions: .mbr))
        img.toDisc = true
        img.burners = [Self.superDrive]
        img.burnerID = Self.superDrive.id
        XCTAssertNil(img.discISO)
        XCTAssertFalse(img.canGo)
        // Choosing another kind of write starts again on a stick.
        own.mode = .windows
        XCTAssertFalse(own.toDisc)
        XCTAssertTrue(discWords(9_047_330_816).fits == false)
        XCTAssertTrue(discWords(6_140_975_104).text.contains("double-layer"))
        XCTAssertTrue(discWords(3_224_686_592).fits)
    }

    func testProgressInWordsForWhatsNotDownloaded() async {
        var said: [String] = []
        let r = StageReporter(word: "stick", downloads: false, building: true) { text, _ in said.append(text) }
        r.report(.preparing)
        r.report(.writing(WriteProgress(phase: .writing, done: 500, total: 1000)))
        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(said, ["Laying out the stick from the ISO…", "Writing… 50%"])
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
