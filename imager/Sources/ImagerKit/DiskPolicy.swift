import Foundation

/// A volume mounted from a disk (or from an APFS container on it).
public struct MountedVolume: Equatable, Hashable, Sendable {
    public var name: String
    public var mountPoint: String
    /// The device it's mounted from, e.g. "disk4s1" or "disk5s1" (an APFS volume in a container on disk4).
    public var bsdName: String

    public init(name: String, mountPoint: String, bsdName: String) {
        self.name = name
        self.mountPoint = mountPoint
        self.bsdName = bsdName
    }
}

/// What macOS says about one whole disk: DiskArbitration's description plus IOKit's class chain. `ImagerMac` fills it
/// from the real system; tests fill it by hand. Everything Sofa Box Imager decides about a disk is decided from this.
public struct DiskDescription: Equatable, Hashable, Sendable {
    /// "disk4". The raw device written is /dev/r + this.
    public var bsdName: String
    /// DiskArbitration's "media whole".
    public var isWhole: Bool
    public var sizeBytes: Int64
    public var blockSize: Int
    public var isWritable: Bool
    /// DiskArbitration's "device internal". nil when it doesn't say (disk images don't).
    public var isInternal: Bool?
    /// "Removable media" (an SD card in a reader, a USB stick).
    public var isRemovable: Bool
    public var isEjectable: Bool
    public var isNetwork: Bool
    /// "USB", "Secure Digital", "Apple Fabric", "PCI-Express", "Virtual Interface"...
    public var protocolName: String?
    public var vendor: String?
    public var model: String?
    /// "APPLE SSD AP0512Z Media", "SDXC Card", "AppleAPFSMedia"...
    public var mediaName: String?
    /// The media icon's file ("SD.icns" for an SD card, "Removable.icns", "Internal.icns", "External.icns").
    public var iconFile: String?
    /// IOKit's path to the media and DiskArbitration's appearance time: together, which disk this is. If either changes
    /// between choosing a disk and writing it, it's not the same disk.
    public var mediaPath: String?
    public var appearanceTime: Double?
    /// IOKit classes from the disk's media upwards, e.g. ["IOMedia", "IOBlockStorageDriver", "IOSCSIPeripheralDeviceType00", ...].
    public var ioClassChain: [String]
    /// Every volume mounted from this disk, including volumes in APFS containers whose store is on it.
    public var volumes: [MountedVolume]

    public init(bsdName: String, isWhole: Bool = true, sizeBytes: Int64, blockSize: Int = 512, isWritable: Bool = true,
                isInternal: Bool?, isRemovable: Bool, isEjectable: Bool, isNetwork: Bool = false,
                protocolName: String?, vendor: String? = nil, model: String? = nil, mediaName: String? = nil,
                iconFile: String? = nil, mediaPath: String? = nil, appearanceTime: Double? = nil,
                ioClassChain: [String], volumes: [MountedVolume] = []) {
        self.bsdName = bsdName
        self.isWhole = isWhole
        self.sizeBytes = sizeBytes
        self.blockSize = blockSize
        self.isWritable = isWritable
        self.isInternal = isInternal
        self.isRemovable = isRemovable
        self.isEjectable = isEjectable
        self.isNetwork = isNetwork
        self.protocolName = protocolName
        self.vendor = vendor
        self.model = model
        self.mediaName = mediaName
        self.iconFile = iconFile
        self.mediaPath = mediaPath
        self.appearanceTime = appearanceTime
        self.ioClassChain = ioClassChain
        self.volumes = volumes
    }

    /// The raw device Sofa Box Imager writes.
    public var rawDevicePath: String { "/dev/r" + bsdName }

    /// What the owner sees: the card's own name where it has one, else the reader's.
    public var displayName: String {
        let media = (mediaName ?? "").replacingOccurrences(of: " Media", with: "")
            .trimmingCharacters(in: .whitespaces)
        let dev = [vendor, model].compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }.joined(separator: " ")
        let name = !media.isEmpty ? media : (!dev.isEmpty ? dev : bsdName)
        return DiskPolicy.printable(name)
    }

    /// The reader or drive it's in ("Apple SDXC Reader", "Generic STORAGE DEVICE"), when it differs from the name.
    public var displayModel: String {
        let dev = [vendor, model].compactMap { $0?.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }.joined(separator: " ")
        return DiskPolicy.printable(dev)
    }

    /// Whether it's the same disk as `other`: same device, same media, same appearance, same size. A card swapped for
    /// another in the same reader gets a new appearance time; a different disk taking the same number has a new path.
    public func isSameDisk(as other: DiskDescription) -> Bool {
        bsdName == other.bsdName && mediaPath == other.mediaPath && appearanceTime == other.appearanceTime
            && sizeBytes == other.sizeBytes && blockSize == other.blockSize && model == other.model
            && mediaName == other.mediaName
    }
}

/// Why Sofa Box Imager won't write a disk. Every reason is said to the owner in plain words.
public enum DiskRefusal: Equatable, Hashable, Sendable {
    case notAWholeDisk
    case oddDeviceName
    case diskImage
    case notPhysical
    case network
    case readOnly
    case insideTheMac
    case unknownLocation
    case notRemovable
    case startupDisk
    case systemVolume(String)
    case inUse(String)
    case unknownSize
    case tooSmall(need: Int64)
    case tooLarge(limit: Int64)
    case oddBlockSize(Int)

    public var text: String {
        switch self {
        case .notAWholeDisk: return "It's a part of a disk, not a whole one."
        case .oddDeviceName: return "macOS gave it a name Sofa Box Imager doesn't expect."
        case .diskImage: return "It's a disk image, not a card."
        case .notPhysical: return "It isn't a physical disk (an APFS container, a RAID set or similar)."
        case .network: return "It's on the network."
        case .readOnly: return "It's read-only. If it's an SD card, slide the lock switch on its side."
        case .insideTheMac: return "It's inside the Mac."
        case .unknownLocation: return "macOS doesn't say whether it's inside the Mac."
        case .notRemovable: return "It isn't removable or ejectable."
        case .startupDisk: return "The Mac starts up from it."
        case .systemVolume(let v): return "It holds the Mac's own volume \(v)."
        case .inUse(let v): return "It holds \(v), which Sofa Box Imager or your home folder is on."
        case .unknownSize: return "macOS doesn't say how big it is."
        case .tooSmall(let need):
            return "It's too small: Sofa Box OS needs \(ByteSize.text(need))."
        case .tooLarge(let limit):
            return "It's bigger than \(ByteSize.text(limit)), more than any SD card for a Pi: almost certainly a hard drive or SSD."
        case .oddBlockSize(let n): return "Its sectors are \(n) bytes, which Sofa Box Imager doesn't write."
        }
    }
}

/// The one place that decides which disks Sofa Box Imager may write. Pure: it reads a `DiskDescription` and nothing
/// else, so every rule is unit-tested with made-up disks. A disk is offered only when no rule refuses it.
public enum DiskPolicy {
    /// The biggest disk offered. SD cards for a Pi are 8 to 512 GB, and Sofa Box OS needs about 5.3 GB; the box's guide
    /// says 32 GB is plenty. Cards are sold in decimal gigabytes and never hold more than they say, so 512 GB cards are
    /// under 512,000,000,000 bytes; 520 GB leaves room for an odd one. 1 TB and bigger disks are almost always the
    /// owner's backup drive or SSD, so they aren't offered at all. (This doesn't protect a 500 GB external SSD: the
    /// other rules and the owner's confirmation do. It's one guard of several, not the only one.)
    public static let largestDisk: Int64 = 520_000_000_000

    /// Protocols and IOKit classes that mean "not a real disk".
    static let virtualProtocols: Set<String> = ["virtual interface", "disk image"]
    static let virtualClassMarks = ["HDIX", "DiskImage", "AppleAPFS", "AppleRAID", "CoreStorage", "AppleLVM",
                                    "IOFDisk", "RAMDisk", "Virtual", "VirtIO"]
    static let cardProtocols: Set<String> = ["secure digital", "sd", "sdxc", "sdhc"]
    static let nearestClasses = 6

    /// The reasons `disk` may not be written with a card of `needs` bytes (empty: it may).
    /// - Parameters:
    ///   - startupDisks: the physical disks the Mac's own volumes ("/", /System/Volumes/...) live on.
    ///   - protectedPaths: paths whose volumes must never be erased (the home folder, the app itself, the temporary folder).
    public static func refusals(for disk: DiskDescription, needs: Int64, startupDisks: Set<String> = [],
                                protectedPaths: [String] = []) -> [DiskRefusal] {
        var why: [DiskRefusal] = []

        // What it is.
        if disk.bsdName.range(of: #"^disk[0-9]+$"#, options: .regularExpression) == nil { why.append(.oddDeviceName) }
        if !disk.isWhole { why.append(.notAWholeDisk) }
        let proto = (disk.protocolName ?? "").lowercased()
        // What a disk is shows right beside its media: a disk image's driver, an APFS container's scheme, a RAID set.
        // Further up are the Mac's own controllers, whose names say nothing about the disk, so they aren't read.
        let classes = Array(disk.ioClassChain.prefix(nearestClasses))
        let isImage = (disk.model ?? "") == "Disk Image" || virtualProtocols.contains(proto)
            || classes.contains { $0.contains("HDIX") || $0.contains("DiskImage") }
        if isImage { why.append(.diskImage) }
        // A physical whole disk is an IOMedia whose provider is the block storage driver of a real device. An APFS
        // container ("synthesized" disk), a RAID set or CoreStorage volume sits on other media instead.
        let physicalShape = classes.count >= 3 && classes[0] == "IOMedia" && classes[1] == "IOBlockStorageDriver"
        let virtualMark = (disk.mediaName ?? "") == "AppleAPFSMedia"
            || classes.contains { c in virtualClassMarks.contains { c.contains($0) } }
        if !isImage && (!physicalShape || virtualMark) { why.append(.notPhysical) }
        if disk.isNetwork { why.append(.network) }
        if !disk.isWritable { why.append(.readOnly) }

        // Where it is. Outside the Mac, or an SD card in the Mac's own card slot (which macOS calls internal, removable).
        let isCard = cardProtocols.contains(proto) || (disk.iconFile ?? "") == "SD.icns"
        switch disk.isInternal {
        case .some(false):
            break
        case .some(true):
            if !(disk.isRemovable && isCard) { why.append(.insideTheMac) }
        case .none:
            why.append(.unknownLocation)
        }
        if !disk.isRemovable && !disk.isEjectable { why.append(.notRemovable) }

        // What's on it.
        if startupDisks.contains(disk.bsdName) { why.append(.startupDisk) }
        for v in disk.volumes {
            if v.mountPoint == "/" || v.mountPoint.hasPrefix("/System/Volumes/") || v.mountPoint == "/System/Volumes" {
                why.append(.systemVolume(printable(v.name.isEmpty ? v.mountPoint : v.name)))
                continue
            }
            let m = v.mountPoint.hasSuffix("/") ? String(v.mountPoint.dropLast()) : v.mountPoint
            if !m.isEmpty, protectedPaths.contains(where: { $0 == m || $0.hasPrefix(m + "/") }) {
                why.append(.inUse(printable(v.name.isEmpty ? v.mountPoint : v.name)))
            }
        }

        // How big it is.
        if disk.sizeBytes <= 0 {
            why.append(.unknownSize)
        } else if needs <= 0 || disk.sizeBytes < needs {
            why.append(.tooSmall(need: needs))
        } else if disk.sizeBytes > largestDisk {
            why.append(.tooLarge(limit: largestDisk))
        }
        let b = disk.blockSize
        if b < 512 || b > CardWriter.blockBytes || b & (b - 1) != 0 { why.append(.oddBlockSize(b)) }
        // Each reason once (two of the Mac's volumes can share a name).
        var seen: Set<DiskRefusal> = []
        return why.filter { seen.insert($0).inserted }
    }

    public static func mayWrite(_ disk: DiskDescription, needs: Int64, startupDisks: Set<String> = [],
                                protectedPaths: [String] = []) -> Bool {
        refusals(for: disk, needs: needs, startupDisks: startupDisks, protectedPaths: protectedPaths).isEmpty
    }

    /// A name as it's shown: control characters and the invisible characters used to disguise text removed, one line.
    public static func printable(_ s: String) -> String {
        let bad: Set<Unicode.Scalar> = ["\u{200B}", "\u{200C}", "\u{200D}", "\u{200E}", "\u{200F}", "\u{202A}",
                                        "\u{202B}", "\u{202C}", "\u{202D}", "\u{202E}", "\u{2066}", "\u{2067}",
                                        "\u{2068}", "\u{2069}", "\u{FEFF}"]
        let scalars = s.unicodeScalars.filter { !bad.contains($0) && !CharacterSet.controlCharacters.contains($0) }
        let out = String(String.UnicodeScalarView(scalars)).trimmingCharacters(in: .whitespaces)
        return out.count > 80 ? String(out.prefix(80)) + "…" : out
    }
}

/// Sizes as the owner reads them: decimal, as cards and Finder say ("64 GB", "1.37 GB").
public enum ByteSize {
    public static func text(_ bytes: Int64) -> String {
        let f = ByteCountFormatter()
        f.countStyle = .decimal
        f.allowedUnits = [.useKB, .useMB, .useGB, .useTB]
        return f.string(fromByteCount: bytes)
    }
}
