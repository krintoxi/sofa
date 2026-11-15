import CryptoKit
import Foundation
@testable import ImagerKit
import XCTest

/// The Windows stick, piece by piece, on made-up Windows ISOs: the UDF reader against the folder the ISO was made
/// from, the WIM splitter against the WIM it split, and the finished FAT32 stick against macOS's own FAT checker
/// (`fsck_msdos`) and macOS's own FAT driver, which mounts it and reads every file back.
final class WindowsStickTests: XCTestCase {
    static let eleven: FakeWindowsISO.Made = try! FakeWindowsISO.make(FakeWIM.windows11)

    // MARK: UDF

    func testTheUDFReaderReadsWhatTheISOWasMadeFrom() throws {
        let made = Self.eleven
        let iso = try FileRandomAccess(url: made.iso)
        XCTAssertTrue(UDFReader.isUDF(iso))
        let volume = try UDFReader.read(iso)
        XCTAssertEqual(volume.name, "CCCOMA_X64FRE_EN-US_DV9")
        var read: [String: Data] = [:]
        try volume.root.walk { path, node in
            if !node.isDirectory { read[path] = try node.contents(in: iso).read(at: 0, count: Int(node.size)) }
        }
        let expected = try files(in: made.folder)
        XCTAssertEqual(Set(read.keys), Set(expected.keys))
        for (k, v) in expected { XCTAssertEqual(read[k], v, k) }
        XCTAssertNotNil(volume.root.find("SOURCES/Install.WIM"), "paths are found whatever their case")
        XCTAssertNil(volume.root.find("sources/nothing.here"))
    }

    func testANonUDFFileIsntReadAsUDF() throws {
        let f = DataRandomAccess(noise(1 << 20, seed: 3))
        XCTAssertFalse(UDFReader.isUDF(f))
        XCTAssertThrowsError(try UDFReader.read(f)) { XCTAssertEqual($0 as? UDFError, .notUDF) }
    }

    // MARK: what's on the ISO

    func testWindowsIsFoundAndNamed() throws {
        let iso = try FileRandomAccess(url: Self.eleven.iso)
        guard case .windows(let w) = try ImageInspector.inspect(iso, name: "win.iso") else { return XCTFail("not Windows") }
        XCTAssertEqual(w.version, .eleven)
        XCTAssertEqual(w.build, 26100)
        XCTAssertEqual(w.arch, .x64)
        XCTAssertEqual(w.editions, ["Windows 11 Home", "Windows 11 Pro"])
        XCTAssertEqual(w.installPath, "sources/install.wim")
        XCTAssertTrue(w.biosBoot)
        XCTAssertEqual(w.uefi, .onTheISO("efi/boot/bootx64.efi"))
        XCTAssertFalse(w.needsSplit)
        XCTAssertNil(w.refusal)
        XCTAssertEqual(w.title, "Windows 11 (x64)")
    }

    func testWindows10And7AreToldApart() throws {
        let ten = try FakeWindowsISO.make(FakeWIM.windows10)
        let w10 = try WindowsMedia.detect(try FileRandomAccess(url: ten.iso))
        XCTAssertEqual(w10.version, .ten)
        // Windows 7: no efi/boot/bootx64.efi on the ISO, only inside its UEFI boot image.
        let seven = try FakeWindowsISO.make(FakeWIM.windows7, uefi: false, efisysLoader: true)
        let w7 = try WindowsMedia.detect(try FileRandomAccess(url: seven.iso))
        XCTAssertEqual(w7.version, .seven)
        XCTAssertEqual(w7.uefi, .fromEfisys)
        XCTAssertTrue(w7.starts.contains("CSM"))
        // ARM64: UEFI only.
        var arm = FakeWIM.windows11
        arm[0].arch = 12
        arm[1].arch = 12
        let a = try FakeWindowsISO.make(arm, extra: ["efi/boot/bootaa64.efi": noise(1000, seed: 5)])
        let wa = try WindowsMedia.detect(try FileRandomAccess(url: a.iso))
        XCTAssertEqual(wa.arch, .arm64)
        XCTAssertFalse(wa.biosBoot)
        XCTAssertEqual(wa.uefi, .onTheISO("efi/boot/bootaa64.efi"))
    }

    func testAnISOWithoutWindowsPartsIsntWindows() throws {
        let dir = try scratch("notwin")
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("t/sources"), withIntermediateDirectories: true)
        try Data("x".utf8).write(to: dir.appendingPathComponent("t/sources/install.wim"))
        let iso = dir.appendingPathComponent("x.iso")
        try sh("/usr/bin/hdiutil", ["makehybrid", "-quiet", "-iso", "-udf", "-o", iso.path, dir.appendingPathComponent("t").path])
        let f = try FileRandomAccess(url: iso)
        XCTAssertThrowsError(try WindowsMedia.detect(f))
        XCTAssertEqual(try ImageInspector.inspect(f), .discOnly)
    }

    // MARK: splitting install.wim

    func testTheWIMIsReadAsWritten() throws {
        let data = FakeWIM.make(images: FakeWIM.windows11, resources: [100, 200, 300])
        let wim = try WIMFile(DataRandomAccess(data))
        XCTAssertEqual(wim.imageCount, 2)
        XCTAssertEqual(wim.entries.count, 5)
        XCTAssertEqual(wim.entries.filter(\.isMetadata).count, 2)
        XCTAssertEqual(wim.images.map(\.build), [26100, 26100])
        XCTAssertEqual(wim.images.first?.arch, 9)
        XCTAssertFalse(wim.hasSolidResources)
        XCTAssertThrowsError(try WIMFile(DataRandomAccess(noise(4096, seed: 9)))) { XCTAssertEqual($0 as? WIMError, .notAWIM) }
    }

    func testSplitPartsHoldEveryResourceOnceAndFitTheirLimit() throws {
        let sizes = [40_000, 120_000, 2_000, 65_536, 300_000, 9, 150_000, 150_000]
        let data = FakeWIM.make(images: FakeWIM.windows11, resources: sizes)
        let file = DataRandomAccess(data)
        let wim = try WIMFile(file)
        let limit: Int64 = 400_000
        let parts = try WIMSplitter.split(file, wim: wim, partBytes: limit)
        XCTAssertGreaterThan(parts.count, 1)
        XCTAssertEqual(parts.map(\.name), (1...parts.count).map { WIMSplitter.partName("install", $0) })
        XCTAssertEqual(parts[0].name, "install.swm")
        XCTAssertEqual(parts[1].name, "install2.swm")
        var seen: [Data: Int] = [:]
        for (i, p) in parts.enumerated() {
            XCTAssertLessThanOrEqual(p.layout.length, limit, p.name)
            let bytes = try p.layout.read(at: 0, count: Int(p.layout.length))
            let part = try WIMFile(DataRandomAccess(bytes))
            XCTAssertEqual(part.part, UInt16(i + 1))
            XCTAssertEqual(part.totalParts, UInt16(parts.count))
            XCTAssertEqual(part.guid, wim.guid)
            XCTAssertEqual(part.imageCount, wim.imageCount)
            XCTAssertNotEqual(part.flags & WIMFile.flagSpanned, 0)
            XCTAssertEqual(part.xmlData, wim.xmlData)
            XCTAssertEqual(part.integrity, .empty)
            XCTAssertEqual(part.entries.filter(\.isMetadata).count, i == 0 ? 2 : 0, "metadata is in the first part only")
            for e in part.entries {
                XCTAssertEqual(e.part, UInt16(i + 1))
                // The resource at its new place is byte for byte the one in the original.
                let original = try XCTUnwrap(wim.entries.first { $0.hash == e.hash })
                XCTAssertEqual(e.resource.size, original.resource.size)
                XCTAssertEqual(e.resource.flags, original.resource.flags)
                XCTAssertEqual(e.resource.originalSize, original.resource.originalSize)
                XCTAssertEqual(e.refCount, original.refCount)
                XCTAssertEqual(bytes.slice(Int(e.resource.offset), Int(e.resource.size)),
                               data.slice(Int(original.resource.offset), Int(original.resource.size)))
                seen[e.hash, default: 0] += 1
            }
        }
        XCTAssertEqual(seen.count, wim.entries.count)
        XCTAssertTrue(seen.values.allSatisfy { $0 == 1 }, "every resource is in exactly one part")
    }

    func testAResourceBiggerThanAPartCantBeSplit() throws {
        let data = FakeWIM.make(images: FakeWIM.windows11, resources: [10_000, 500_000])
        let file = DataRandomAccess(data)
        XCTAssertThrowsError(try WIMSplitter.split(file, wim: try WIMFile(file), partBytes: 200_000)) {
            XCTAssertEqual($0 as? WIMError, .resourceTooBig(500_000))
        }
    }

    func testASolidGroupStaysInOnePart() throws {
        let data = FakeWIM.make(images: FakeWIM.windows11, resources: [3000, 3000, 3000], solid: true)
        let file = DataRandomAccess(data)
        let wim = try WIMFile(file)
        XCTAssertTrue(wim.hasSolidResources)
        let parts = try WIMSplitter.split(file, wim: wim, partBytes: 11_000)
        let holding = parts.filter { $0.entries.contains { $0.isSolid } }
        XCTAssertEqual(holding.count, 1)
        let solid = holding[0].entries.filter(\.isSolid)
        XCTAssertEqual(solid.count, 5)
        // Files inside a solid resource keep their place in it; the solid resources themselves move.
        XCTAssertEqual(solid.filter { !$0.isSolidResource }.map(\.resource.offset), [0, 5000, 10000])
        let bytes = try holding[0].layout.read(at: 0, count: Int(holding[0].layout.length))
        for e in solid where e.isSolidResource {
            let o = try XCTUnwrap(wim.entries.first { $0.isSolidResource && $0.resource.size == e.resource.size })
            XCTAssertEqual(bytes.slice(Int(e.resource.offset), Int(e.resource.size)),
                           data.slice(Int(o.resource.offset), Int(o.resource.size)))
        }
    }

    // MARK: the FAT32 stick

    /// The finished stick, checked by macOS: `fsck_msdos` finds nothing wrong, and its FAT driver reads every file back
    /// as it was on the ISO, long names and all, with install.wim split into parts that put it back together.
    func testTheStickIsAFAT32VolumeMacOSReadsBack() throws {
        let made = Self.eleven
        let iso = try FileRandomAccess(url: made.iso)
        let disk: Int64 = 64 << 20
        let (stick, media) = try WindowsStick.build(iso: iso, diskBytes: disk, sectorBytes: 512, splitAbove: 200_000,
                                                    partBytes: 400_000)
        XCTAssertEqual(media.version, .eleven)
        let dir = try scratch("stick")
        defer { try? FileManager.default.removeItem(at: dir) }
        let image = dir.appendingPathComponent("stick.img")
        try writeLayout(stick.layout, size: disk, to: image)

        // The partition on its own, for fsck_msdos.
        let part = dir.appendingPathComponent("part.img")
        let all = try Data(contentsOf: image)
        try all.subdata(in: 1 << 20..<Int(disk)).write(to: part)
        let fsck = try sh("/sbin/fsck_msdos", ["-n", part.path])
        XCTAssertFalse(fsck.lowercased().contains("fix"), fsck)

        let onStick = try filesOnStick(image)
        var expected = try files(in: made.folder)
        let wim = expected.removeValue(forKey: "sources/install.wim")!
        XCTAssertNil(onStick["sources/install.wim"])
        let swm = onStick.keys.filter { $0.hasPrefix("sources/install") && $0.hasSuffix(".swm") }.sorted()
        XCTAssertGreaterThan(swm.count, 1)
        for (k, v) in expected { XCTAssertEqual(onStick[k], v, k) }
        XCTAssertEqual(Set(onStick.keys), Set(expected.keys).union(swm))
        // The parts hold every resource of the original, unchanged.
        let original = try WIMFile(DataRandomAccess(wim))
        var hashes = Set<Data>()
        for name in swm {
            let p = try WIMFile(DataRandomAccess(onStick[name]!))
            for e in p.entries {
                let o = try XCTUnwrap(original.entries.first { $0.hash == e.hash })
                XCTAssertEqual(onStick[name]!.slice(Int(e.resource.offset), Int(e.resource.size)),
                               wim.slice(Int(o.resource.offset), Int(o.resource.size)))
                hashes.insert(e.hash)
            }
        }
        XCTAssertEqual(hashes.count, original.entries.count)
    }

    func testTheBootCodeIsPointedAtBOOTMGR() throws {
        let iso = try FileRandomAccess(url: Self.eleven.iso)
        let disk: Int64 = 64 << 20
        let (stick, _) = try WindowsStick.build(iso: iso, diskBytes: disk, sectorBytes: 512)
        let bytes = try stick.layout.read(at: 0, count: Int(stick.layout.length))
        // The MBR: our code, one active FAT32 (LBA) partition from the first megabyte to the end.
        XCTAssertEqual(Array(bytes.prefix(BootCode.mbrCode.count)), BootCode.mbrCode)
        XCTAssertEqual(bytes.byte(446), 0x80)
        XCTAssertEqual(bytes.byte(450), 0x0C)
        XCTAssertEqual(bytes.le32(454), 2048)
        XCTAssertEqual(Int64(bytes.le32(458)), disk / 512 - 2048)
        XCTAssertEqual(bytes.slice(510, 2), Data([0x55, 0xAA]))
        // The boot sector, and its backup at sector 6.
        let vbr = bytes.slice(1 << 20, 512)
        XCTAssertEqual(bytes.slice((1 << 20) + 6 * 512, 512), vbr)
        XCTAssertEqual(vbr.slice(0, 3), Data([0xEB, 0x58, 0x90]))
        XCTAssertEqual(vbr.slice(82, 8), Data("FAT32   ".utf8))
        XCTAssertEqual(vbr.le32(28), 2048, "hidden sectors: where the partition starts")
        XCTAssertEqual(vbr.slice(71, 11), Data("WINDOWS 11 ".utf8))
        // The run it reads is BOOTMGR, whole.
        let loader = try XCTUnwrap(stick.loader)
        XCTAssertEqual(Int64(vbr.le32(BootCode.loaderSectorOffset)), loader.sector)
        XCTAssertEqual(Int64(vbr.le16(BootCode.loaderCountOffset)), loader.count)
        let bootmgr = try Data(contentsOf: Self.eleven.folder.appendingPathComponent("bootmgr"))
        XCTAssertEqual(loader.count, Int64((bootmgr.count + 511) / 512))
        let at = Int((2048 + loader.sector) * 512)
        XCTAssertEqual(bytes.slice(at, bootmgr.count), bootmgr)
        // The data starts on a megabyte, as flash likes.
        let reserved = Int64(vbr.le16(14))
        let fat = Int64(vbr.le32(36))
        XCTAssertEqual((2048 + reserved + 2 * fat) % 2048, 0)
    }

    func testTheSameISOMakesTheSameStick() throws {
        let iso = try FileRandomAccess(url: Self.eleven.iso)
        let a = try WindowsStick.build(iso: iso, diskBytes: 64 << 20, sectorBytes: 512).0.layout
        let b = try WindowsStick.build(iso: iso, diskBytes: 64 << 20, sectorBytes: 512).0.layout
        XCTAssertEqual(a.length, b.length)
        XCTAssertEqual(try a.read(at: 0, count: Int(a.length)), try b.read(at: 0, count: Int(b.length)))
    }

    func testAStickTooSmallOrWithOddSectorsIsRefused() throws {
        let iso = try FileRandomAccess(url: Self.eleven.iso)
        XCTAssertThrowsError(try WindowsStick.build(iso: iso, diskBytes: 4 << 20, sectorBytes: 512)) {
            guard case .tooSmall = $0 as? FATError else { return XCTFail("\($0)") }
        }
        XCTAssertThrowsError(try WindowsStick.build(iso: iso, diskBytes: 64 << 20, sectorBytes: 4096)) {
            XCTAssertEqual($0 as? FATError, .sectorSize(4096))
        }
    }

    func testAFileOver4GBCantGoOnFAT32() throws {
        final class Huge: RandomAccess {
            let size: Int64 = 5_000_000_000
            func read(at offset: Int64, count: Int) throws -> Data { Data(count: count) }
        }
        let root = FATItem.folder("", [.file("big.bin", Huge())])
        XCTAssertThrowsError(try FAT32Stick(root: root, diskBytes: 8_000_000_000, label: "X", loaderPath: nil, seed: 1)) {
            XCTAssertEqual($0 as? FATError, .fileTooBig("big.bin", 5_000_000_000))
        }
    }

    func testShortNamesAreUniqueAndLongNamesKept() {
        var taken = Set<[UInt8]>()
        let a = FAT32Stick.shortName(for: "api-ms-win-core-file-l1.dll", taken: &taken)
        let b = FAT32Stick.shortName(for: "api-ms-win-core-file-l2.dll", taken: &taken)
        XCTAssertEqual(String(decoding: a, as: UTF8.self), "API-MS~1DLL")
        XCTAssertEqual(String(decoding: b, as: UTF8.self), "API-MS~2DLL")
        XCTAssertEqual(String(decoding: FAT32Stick.shortName(for: "bootmgr", taken: &taken), as: UTF8.self), "BOOTMGR    ")
        XCTAssertEqual(String(decoding: FAT32Stick.shortName(for: "BOOTX64.EFI", taken: &taken), as: UTF8.self), "BOOTX64 EFI")
        XCTAssertNil(FAT32Stick.exactShort("bootmgr"), "lower case needs a long name to keep its case")
        XCTAssertNotNil(FAT32Stick.exactShort("BOOTMGR"))
    }

    // MARK: Windows 7's UEFI loader

    func testWindows7GetsItsUEFILoaderFromItsBootImage() throws {
        let seven = try FakeWindowsISO.make(FakeWIM.windows7, uefi: false, efisysLoader: true)
        let iso = try FileRandomAccess(url: seven.iso)
        let disk: Int64 = 64 << 20
        let (stick, media) = try WindowsStick.build(iso: iso, diskBytes: disk, sectorBytes: 512)
        XCTAssertEqual(media.version, .seven)
        let dir = try scratch("seven")
        defer { try? FileManager.default.removeItem(at: dir) }
        let image = dir.appendingPathComponent("stick.img")
        try writeLayout(stick.layout, size: disk, to: image)
        let onStick = try filesOnStick(image)
        XCTAssertEqual(onStick["efi/boot/bootx64.efi"], noise(98_765, seed: 17))
        // And the FAT12 reader finds it on its own.
        let efisys = try FATImage(DataRandomAccess(try Data(contentsOf: seven.folder.appendingPathComponent("efi/microsoft/boot/efisys.bin"))))
        let loader = try XCTUnwrap(try efisys.file("efi/boot/bootx64.efi"))
        XCTAssertEqual(try loader.read(at: 0, count: Int(loader.size)), noise(98_765, seed: 17))
        XCTAssertNil(try efisys.file("EFI/BOOT/NOTHERE.EFI"))
    }

    // MARK: the Windows 11 switches

    func testNoSwitchesNoUnattendFile() throws {
        XCTAssertNil(WindowsOptions().unattend(arch: .x64))
        let iso = try FileRandomAccess(url: Self.eleven.iso)
        let (stick, _) = try WindowsStick.build(iso: iso, diskBytes: 64 << 20, sectorBytes: 512)
        let dir = try scratch("plain")
        defer { try? FileManager.default.removeItem(at: dir) }
        try writeLayout(stick.layout, size: 64 << 20, to: dir.appendingPathComponent("s.img"))
        XCTAssertNil(try filesOnStick(dir.appendingPathComponent("s.img"))["autounattend.xml"])
    }

    func testTheSwitchesWriteOnlyWhatsTicked() throws {
        let checks = try XCTUnwrap(WindowsOptions(skipHardwareChecks: true).unattend(arch: .x64))
        for key in ["BypassTPMCheck", "BypassSecureBootCheck", "BypassCPUCheck", "BypassRAMCheck"] {
            XCTAssertTrue(checks.contains("/v \(key) /t REG_DWORD /d 1 /f"), key)
        }
        XCTAssertEqual(checks.components(separatedBy: "<RunSynchronousCommand").count - 1, 4, "one command a key, no more")
        XCTAssertFalse(checks.contains("LocalAccount"))
        XCTAssertFalse(checks.contains("BypassNRO"))
        XCTAssertTrue(checks.contains("processorArchitecture=\"amd64\""))
        let account = try XCTUnwrap(WindowsOptions(localAccount: "Sofa & Co").unattend(arch: .arm64))
        XCTAssertTrue(account.contains("<Name>Sofa &amp; Co</Name>"))
        XCTAssertTrue(account.contains("BypassNRO"))
        XCTAssertTrue(account.contains("/logonpasswordchg:yes"))
        XCTAssertFalse(account.contains("BypassTPMCheck"))
        XCTAssertTrue(account.contains("processorArchitecture=\"arm64\""))
        // Never anything that chooses or erases a disk by itself, and never a product key.
        for x in [checks, account] {
            for word in ["DiskConfiguration", "WillWipeDisk", "InstallTo", "ProductKey", "AutoLogon"] {
                XCTAssertFalse(x.contains(word), word)
            }
            XCTAssertNoThrow(try XMLDocument(xmlString: x))
        }
        // On the stick, at the root.
        let iso = try FileRandomAccess(url: Self.eleven.iso)
        let (stick, _) = try WindowsStick.build(iso: iso, diskBytes: 64 << 20, sectorBytes: 512,
                                                options: WindowsOptions(skipHardwareChecks: true, localAccount: "Sofa"))
        let dir = try scratch("switches")
        defer { try? FileManager.default.removeItem(at: dir) }
        try writeLayout(stick.layout, size: 64 << 20, to: dir.appendingPathComponent("s.img"))
        let xml = try XCTUnwrap(try filesOnStick(dir.appendingPathComponent("s.img"))["autounattend.xml"])
        XCTAssertEqual(String(decoding: xml, as: UTF8.self),
                       WindowsOptions(skipHardwareChecks: true, localAccount: "Sofa").unattend(arch: .x64))
    }

    func testTheSwitchesAreForWindows11Only() throws {
        let ten = try FakeWindowsISO.make(FakeWIM.windows10)
        XCTAssertThrowsError(try WindowsStick.build(iso: try FileRandomAccess(url: ten.iso), diskBytes: 64 << 20, sectorBytes: 512,
                                                    options: WindowsOptions(skipHardwareChecks: true))) {
            XCTAssertEqual($0 as? WindowsStickError, .refused("The switches are for Windows 11 only."))
        }
        let own = try FakeWindowsISO.make(FakeWIM.windows11, extra: ["autounattend.xml": Data("<unattend/>".utf8)])
        XCTAssertThrowsError(try WindowsStick.build(iso: try FileRandomAccess(url: own.iso), diskBytes: 64 << 20, sectorBytes: 512,
                                                    options: WindowsOptions(localAccount: "Sofa")))
    }

    func testAccountNamesWindowsWouldRefuseAreRefused() {
        XCTAssertNil(WindowsOptions.accountNameProblem("Den"))
        XCTAssertNil(WindowsOptions.accountNameProblem("Living Room"))
        XCTAssertNotNil(WindowsOptions.accountNameProblem(""))
        XCTAssertNotNil(WindowsOptions.accountNameProblem("   "))
        XCTAssertNotNil(WindowsOptions.accountNameProblem("a/b"))
        XCTAssertNotNil(WindowsOptions.accountNameProblem("Administrator"))
        XCTAssertNotNil(WindowsOptions.accountNameProblem(String(repeating: "x", count: 21)))
        XCTAssertNotNil(WindowsOptions.accountNameProblem("..."))
    }

    func testAnESDTooBigToSplitIsRefusedInWords() {
        let w = WindowsMedia(version: .ten, build: 19045, arch: .x64, editions: ["Windows 10 Pro"],
                             installPath: "sources/install.esd", installBytes: 4_600_000_000, installIsSolid: true,
                             volumeName: "X", biosBoot: true, bootmgrBytes: 400_000, uefi: .onTheISO("efi/boot/bootx64.efi"),
                             fileBytes: 5_000_000_000, fileCount: 900, hasUnattend: false)
        XCTAssertNotNil(w.refusal)
        XCTAssertTrue(w.refusal!.contains("install.wim"))
    }
}
