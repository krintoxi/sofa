import Foundation
@testable import ImagerKit
import XCTest

/// `DiskPolicy` with made-up disks. The internal SSD, APFS container and RAM disk below are copied from what
/// DiskArbitration and IOKit said on a real Mac (2026-11-10, macOS 27.2, Apple silicon); the card readers are written
/// from Apple's documented keys and need a real reader to confirm (see the README).
final class DiskPolicyTests: XCTestCase {
    static let card: Int64 = 5_226_102_784                // Sofa Box OS 1.1.54, unpacked
    static let usbChain = ["IOMedia", "IOBlockStorageDriver", "IOSCSIPeripheralDeviceType00",
                           "IOSCSILogicalUnitNub", "IOUSBMassStorageInterfaceNub", "IOUSBMassStorageDriverNub",
                           "IOUSBHostInterface", "IOUSBHostDevice"]

    // MARK: disks

    /// A 64 GB microSD card in a USB card reader.
    static func usbCardReader(size: Int64 = 63_864_569_856) -> DiskDescription {
        DiskDescription(bsdName: "disk4", sizeBytes: size, isInternal: false, isRemovable: true, isEjectable: true,
                        protocolName: "USB", vendor: "Generic", model: "STORAGE DEVICE", mediaName: "Generic STORAGE DEVICE Media",
                        iconFile: "Removable.icns", mediaPath: "IODeviceTree:/usb@1/STORAGE@1:0",
                        appearanceTime: 815_000_000, ioClassChain: usbChain)
    }

    /// A 32 GB card in a MacBook Pro's own SD slot: macOS calls it internal, removable.
    static func builtInSDSlot() -> DiskDescription {
        DiskDescription(bsdName: "disk5", sizeBytes: 31_914_983_424, isInternal: true, isRemovable: true,
                        isEjectable: true, protocolName: "Secure Digital", vendor: "Apple", model: "SDXC Reader",
                        mediaName: "SDXC Card", iconFile: "SD.icns",
                        ioClassChain: ["IOMedia", "IOBlockStorageDriver", "AppleSDXCBlockStorageDevice", "AppleSDXCSlot",
                                       "AppleSDXC"])
    }

    /// disk0 on the Mac these were written on: the internal SSD, 500.3 GB (under the size limit!).
    static func internalSSD() -> DiskDescription {
        DiskDescription(bsdName: "disk0", sizeBytes: 500_277_792_768, blockSize: 4096, isInternal: true,
                        isRemovable: false, isEjectable: false, protocolName: "Apple Fabric", model: "APPLE SSD AP0512Z",
                        mediaName: "APPLE SSD AP0512Z Media", iconFile: "Internal.icns",
                        ioClassChain: ["IOMedia", "IOBlockStorageDriver", "IOEmbeddedNVMeBlockDevice",
                                       "AppleANS3CGv2Controller", "RTBuddyService", "RTBuddy", "AppleA7IOPNub",
                                       "AppleASCWrapV6"],
                        volumes: [MountedVolume(name: "Macintosh HD", mountPoint: "/", bsdName: "disk3s3s1"),
                                  MountedVolume(name: "Data", mountPoint: "/System/Volumes/Data", bsdName: "disk3s1")])
    }

    /// disk3: the APFS container on disk0 ("synthesized").
    static func apfsContainer() -> DiskDescription {
        DiskDescription(bsdName: "disk3", sizeBytes: 494_332_366_848, blockSize: 4096, isInternal: true,
                        isRemovable: false, isEjectable: false, protocolName: "Apple Fabric", model: "APPLE SSD AP0512Z",
                        mediaName: "AppleAPFSMedia", iconFile: "Internal.icns",
                        ioClassChain: ["AppleAPFSMedia", "AppleAPFSContainerScheme", "IOMedia", "IOGUIDPartitionScheme",
                                       "IOMedia", "IOBlockStorageDriver", "IOEmbeddedNVMeBlockDevice",
                                       "AppleANS3CGv2Controller"])
    }

    /// A RAM disk (`hdiutil attach -nomount ram://`): no "internal" key at all, removable and ejectable. A filter
    /// that only asks "removable and not internal?" would offer it.
    static func ramDisk(size: Int64 = 8_589_934_592) -> DiskDescription {
        DiskDescription(bsdName: "disk7", sizeBytes: size, isInternal: nil, isRemovable: true, isEjectable: true,
                        protocolName: "Virtual Interface", vendor: "Apple", model: "Disk Image",
                        mediaName: "Apple read/write Media", iconFile: "Removable.icns",
                        ioClassChain: ["IOMedia", "IOBlockStorageDriver", "IODiskImageBlockStorageDeviceOutKernel",
                                       "IOHDIXHDDriveOutKernel", "IOHDIXController", "IOResources"])
    }

    /// A 1 TB USB SSD (the owner's backup drive, say).
    static func usbSSD(size: Int64 = 1_000_204_886_016) -> DiskDescription {
        DiskDescription(bsdName: "disk6", sizeBytes: size, isInternal: false, isRemovable: false, isEjectable: true,
                        protocolName: "USB", vendor: "Samsung", model: "PSSD T7", mediaName: "Samsung PSSD T7 Media",
                        iconFile: "External.icns", ioClassChain: usbChain,
                        volumes: [MountedVolume(name: "Backups", mountPoint: "/Volumes/Backups", bsdName: "disk8s1")])
    }

    private func why(_ d: DiskDescription, needs: Int64 = card, startup: Set<String> = [],
                     protected: [String] = []) -> [DiskRefusal] {
        DiskPolicy.refusals(for: d, needs: needs, startupDisks: startup, protectedPaths: protected)
    }

    // MARK: offered

    func testAnSDCardInAUSBReaderIsOffered() {
        XCTAssertEqual(why(Self.usbCardReader()), [])
    }

    func testAnSDCardInTheMacsOwnSlotIsOffered() {
        XCTAssertEqual(why(Self.builtInSDSlot()), [])
        var byIconOnly = Self.builtInSDSlot()
        byIconOnly.protocolName = "PCI-Express"
        XCTAssertEqual(why(byIconOnly), [])
    }

    func testAUSBStickWithAVolumeIsOffered() {
        var d = Self.usbCardReader(size: 15_376_000_000)
        d.volumes = [MountedVolume(name: "bootfs", mountPoint: "/Volumes/bootfs", bsdName: "disk4s1")]
        XCTAssertEqual(why(d, protected: ["/Users/leo", "/Applications/Sofa Box Imager.app", "/private/var/folders/x"]), [])
    }

    func testAnExternalSSDUnderTheLimitIsOfferedButSaysWhatItIs() {
        // The limit doesn't catch a 500 GB external SSD; the confirmation, which names it, does.
        let d = Self.usbSSD(size: 500_107_862_016)
        XCTAssertEqual(why(d), [])
        XCTAssertEqual(d.displayName, "Samsung PSSD T7")
        XCTAssertEqual(d.displayModel, "Samsung PSSD T7")
    }

    // MARK: refused

    func testTheInternalSSDIsRefused() {
        let w = why(Self.internalSSD(), startup: ["disk0", "disk3"])
        XCTAssertTrue(w.contains(.insideTheMac))
        XCTAssertTrue(w.contains(.notRemovable))
        XCTAssertTrue(w.contains(.startupDisk))
        XCTAssertTrue(w.contains(.systemVolume("Macintosh HD")))
        // Even with nothing mounted and no startup set, inside-the-Mac alone refuses it.
        var bare = Self.internalSSD()
        bare.volumes = []
        XCTAssertEqual(why(bare), [.insideTheMac, .notRemovable])
    }

    func testAnAPFSContainerIsRefused() {
        let w = why(Self.apfsContainer())
        XCTAssertTrue(w.contains(.notPhysical))
        XCTAssertTrue(w.contains(.insideTheMac))
    }

    func testDiskImagesAreRefused() {
        let w = why(Self.ramDisk())
        XCTAssertTrue(w.contains(.diskImage))
        XCTAssertTrue(w.contains(.unknownLocation))
        // Each sign on its own is enough.
        var model = Self.usbCardReader()
        model.model = "Disk Image"
        XCTAssertTrue(why(model).contains(.diskImage))
        var proto = Self.usbCardReader()
        proto.protocolName = "Disk Image"
        XCTAssertTrue(why(proto).contains(.diskImage))
        var chain = Self.usbCardReader()
        chain.ioClassChain = ["IOMedia", "IOBlockStorageDriver", "IODiskImageBlockStorageDeviceOutKernel", "IOHDIXController"]
        XCTAssertTrue(why(chain).contains(.diskImage))
    }

    func testOtherVirtualDisksAreRefused() {
        for chain in [["IOMedia", "AppleRAIDMirrorSet", "AppleRAID"],
                      ["IOMedia", "IOBlockStorageDriver", "AppleVirtIOBlockStorageDevice"],
                      ["IOMedia", "CoreStorageLogical"],
                      ["IOMedia"],
                      []] {
            var d = Self.usbCardReader()
            d.ioClassChain = chain
            XCTAssertTrue(why(d).contains(.notPhysical), "\(chain)")
        }
        var apfsByName = Self.usbCardReader()
        apfsByName.mediaName = "AppleAPFSMedia"
        XCTAssertTrue(why(apfsByName).contains(.notPhysical))
    }

    func testOnlyTheClassesBesideTheMediaAreRead() {
        // A controller far above a real card, with a name that would count beside the media.
        var d = Self.usbCardReader()
        d.ioClassChain = Self.usbChain + ["AppleVirtualPlatformUSBHost", "IOHDIXController"]
        XCTAssertEqual(d.ioClassChain.firstIndex(of: "AppleVirtualPlatformUSBHost"), 8)
        XCTAssertEqual(why(d), [])
        // The same names within reach refuse it.
        d.ioClassChain = ["IOMedia", "IOBlockStorageDriver", "X", "Y", "Z", "AppleVirtualDisk"]
        XCTAssertEqual(why(d), [.notPhysical])
        d.ioClassChain = ["IOMedia", "IOBlockStorageDriver", "X", "Y", "IOHDIXController"]
        XCTAssertEqual(why(d), [.diskImage])
    }

    func testEachReasonIsSaidOnce() {
        var d = Self.internalSSD()
        d.volumes.append(MountedVolume(name: "Macintosh HD", mountPoint: "/System/Volumes/Update/mnt1", bsdName: "disk3s3"))
        let w = why(d)
        XCTAssertEqual(w.filter { $0 == .systemVolume("Macintosh HD") }.count, 1)
    }

    func testTooBigIsRefused() {
        XCTAssertEqual(why(Self.usbSSD()), [.tooLarge(limit: DiskPolicy.largestDisk)])
        XCTAssertEqual(why(Self.usbCardReader(size: DiskPolicy.largestDisk)), [])
        XCTAssertEqual(why(Self.usbCardReader(size: DiskPolicy.largestDisk + 1)), [.tooLarge(limit: DiskPolicy.largestDisk)])
        // A real 512 GB card fits under the limit.
        XCTAssertEqual(why(Self.usbCardReader(size: 512_000_000_000)), [])
    }

    func testTooSmallIsRefused() {
        XCTAssertEqual(why(Self.usbCardReader(size: 3_965_190_144)), [.tooSmall(need: Self.card)])
        XCTAssertEqual(why(Self.usbCardReader(size: Self.card)), [])
        XCTAssertEqual(why(Self.usbCardReader(size: Self.card - 512)), [.tooSmall(need: Self.card)])
        XCTAssertEqual(why(Self.usbCardReader(size: 0)), [.unknownSize])
        XCTAssertEqual(why(Self.usbCardReader(), needs: 0), [.tooSmall(need: 0)])     // no card size, no write
    }

    func testPartitionsAndOddNamesAreRefused() {
        var part = Self.usbCardReader()
        part.bsdName = "disk4s1"
        part.isWhole = false
        XCTAssertEqual(why(part), [.oddDeviceName, .notAWholeDisk])
        for name in ["disk", "rdisk4", "/dev/disk4", "disk4 ", "disk-1", "../disk4", "disk4\n"] {
            var d = Self.usbCardReader()
            d.bsdName = name
            XCTAssertTrue(why(d).contains(.oddDeviceName), name)
        }
    }

    func testLockedNetworkAndFixedDisksAreRefused() {
        var locked = Self.usbCardReader()
        locked.isWritable = false
        XCTAssertEqual(why(locked), [.readOnly])
        var network = Self.usbCardReader()
        network.isNetwork = true
        XCTAssertEqual(why(network), [.network])
        var fixed = Self.usbCardReader()
        fixed.isRemovable = false
        fixed.isEjectable = false
        XCTAssertEqual(why(fixed), [.notRemovable])
    }

    func testInsideTheMacUnlessItsACardInTheSlot() {
        var internalSDNotRemovable = Self.builtInSDSlot()
        internalSDNotRemovable.isRemovable = false
        XCTAssertEqual(why(internalSDNotRemovable), [.insideTheMac])
        var internalRemovableNotSD = Self.builtInSDSlot()
        internalRemovableNotSD.protocolName = "SATA"
        internalRemovableNotSD.iconFile = "Removable.icns"
        XCTAssertEqual(why(internalRemovableNotSD), [.insideTheMac])
        var unknown = Self.usbCardReader()
        unknown.isInternal = nil
        XCTAssertEqual(why(unknown), [.unknownLocation])
    }

    func testTheStartupDiskAndTheMacsVolumesAreRefusedEvenOutside() {
        // A Mac started from an external SSD: outside, ejectable, small enough, and still never offered.
        var external = Self.usbSSD(size: 256_060_514_304)
        external.volumes = [MountedVolume(name: "Macintosh HD", mountPoint: "/", bsdName: "disk9s1s1"),
                            MountedVolume(name: "Preboot", mountPoint: "/System/Volumes/Preboot", bsdName: "disk9s2")]
        let w = why(external, startup: ["disk6"])
        XCTAssertTrue(w.contains(.startupDisk))
        XCTAssertTrue(w.contains(.systemVolume("Macintosh HD")))
        XCTAssertTrue(w.contains(.systemVolume("Preboot")))
        var startupOnly = Self.usbSSD(size: 256_060_514_304)
        startupOnly.volumes = []
        XCTAssertEqual(why(startupOnly, startup: ["disk6"]), [.startupDisk])
    }

    func testVolumesHoldingTheHomeFolderOrTheAppAreRefused() {
        var d = Self.usbSSD(size: 256_060_514_304)
        d.volumes = [MountedVolume(name: "Work", mountPoint: "/Volumes/Work", bsdName: "disk6s2")]
        XCTAssertEqual(why(d, protected: ["/Volumes/Work/Users/leo"]), [.inUse("Work")])
        XCTAssertEqual(why(d, protected: ["/Volumes/Work"]), [.inUse("Work")])
        XCTAssertEqual(why(d, protected: ["/Volumes/Workshop/x"]), [])          // a prefix of the name isn't the volume
        XCTAssertEqual(why(d, protected: ["/Users/leo"]), [])
    }

    func testSectorSizes() {
        for (size, ok) in [(512, true), (4096, true), (1 << 20, true), (0, false), (256, false), (520, false),
                           (2 << 20, false), (3000, false)] {
            var d = Self.usbCardReader()
            d.blockSize = size
            XCTAssertEqual(why(d).isEmpty, ok, "\(size)")
        }
    }

    /// Every combination of where-it-is flags: nothing inside the Mac, unknown, virtual or fixed is ever offered.
    func testEveryCombinationOfFlags() {
        let base = Self.usbCardReader()
        for inside in [Bool?.none, false, true] {
            for removable in [false, true] {
                for ejectable in [false, true] {
                    for sdLike in [false, true] {
                        for image in [false, true] {
                            for apfs in [false, true] {
                                var d = base
                                d.isInternal = inside
                                d.isRemovable = removable
                                d.isEjectable = ejectable
                                d.protocolName = sdLike ? "Secure Digital" : "USB"
                                if image { d.model = "Disk Image" }
                                if apfs { d.mediaName = "AppleAPFSMedia" }
                                let offered = DiskPolicy.mayWrite(d, needs: Self.card)
                                let expected = !image && !apfs && (removable || ejectable)
                                    && (inside == false || (inside == true && removable && sdLike))
                                XCTAssertEqual(offered, expected,
                                               "internal \(String(describing: inside)) removable \(removable) ejectable \(ejectable) sd \(sdLike) image \(image) apfs \(apfs)")
                            }
                        }
                    }
                }
            }
        }
    }

    func testNamesAreShownSafely() {
        var d = Self.usbCardReader()
        d.mediaName = "SDXC\u{202E}gpj.exe Card\u{0007} Media"
        XCTAssertEqual(d.displayName, "SDXCgpj.exe Card")
        d.mediaName = String(repeating: "A", count: 200)
        XCTAssertEqual(d.displayName.count, 81)
        d.mediaName = " Media"
        d.vendor = nil
        d.model = nil
        XCTAssertEqual(d.displayName, "disk4")
        XCTAssertEqual(Self.builtInSDSlot().displayName, "SDXC Card")
        XCTAssertEqual(Self.builtInSDSlot().displayModel, "Apple SDXC Reader")
    }

    func testTheSameDiskMeansTheSameCardInTheSamePlace() {
        let a = Self.usbCardReader()
        XCTAssertTrue(a.isSameDisk(as: a))
        var swapped = a
        swapped.appearanceTime = 815_000_100                     // a card taken out and put back in, or another one
        XCTAssertFalse(a.isSameDisk(as: swapped))
        var otherReader = a
        otherReader.mediaPath = "IODeviceTree:/usb@2/STORAGE@1:0"
        XCTAssertFalse(a.isSameDisk(as: otherReader))
        var bigger = a
        bigger.sizeBytes += 512
        XCTAssertFalse(a.isSameDisk(as: bigger))
        var mounted = a                                          // volumes come and go; that's still the same disk
        mounted.volumes = [MountedVolume(name: "bootfs", mountPoint: "/Volumes/bootfs", bsdName: "disk4s1")]
        XCTAssertTrue(a.isSameDisk(as: mounted))
    }

    func testEveryRefusalSaysSomething() {
        let all: [DiskRefusal] = [.notAWholeDisk, .oddDeviceName, .diskImage, .notPhysical, .network, .readOnly,
                                  .insideTheMac, .unknownLocation, .notRemovable, .startupDisk, .systemVolume("x"),
                                  .inUse("x"), .unknownSize, .tooSmall(need: 1), .tooLarge(limit: 1), .oddBlockSize(3)]
        for r in all { XCTAssertFalse(r.text.isEmpty) }
        XCTAssertTrue(DiskRefusal.tooLarge(limit: DiskPolicy.largestDisk).text.contains("520 GB"))
    }
}
