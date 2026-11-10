import DiskArbitration
import Foundation
import ImagerKit
import IOKit

/// The disks on this Mac right now, as `DiskPolicy` reads them, plus what the policy needs to know about the Mac itself.
public struct DiskSnapshot {
    public var disks: [DiskDescription]
    /// The whole disks (physical and APFS) that hold "/" and /System/Volumes/...: the startup disk.
    public var startupDisks: Set<String>
    /// Folders whose volumes are never erased: the home folder, this app, the temporary folder.
    public var protectedPaths: [String]

    public func disk(_ bsdName: String) -> DiskDescription? { disks.first { $0.bsdName == bsdName } }

    public func refusals(for disk: DiskDescription, needs: Int64) -> [DiskRefusal] {
        DiskPolicy.refusals(for: disk, needs: needs, startupDisks: startupDisks, protectedPaths: protectedPaths)
    }

    /// The disks Sofa Box Imager offers for a card of `needs` bytes, and the others with why not.
    public func sorted(needs: Int64) -> (offered: [DiskDescription], refused: [(DiskDescription, [DiskRefusal])]) {
        var offered: [DiskDescription] = []
        var refused: [(DiskDescription, [DiskRefusal])] = []
        for d in disks {
            let why = refusals(for: d, needs: needs)
            if why.isEmpty { offered.append(d) } else { refused.append((d, why)) }
        }
        return (offered, refused)
    }
}

/// A mounted file system: where from, where to.
struct Mount {
    var device: String          // "disk3s1"
    var mountPoint: String
    var name: String
}

public enum DiskList {
    /// Every whole disk macOS knows of, described from DiskArbitration and IOKit.
    public static func snapshot() -> DiskSnapshot {
        let session = DASessionCreate(kCFAllocatorDefault)
        let mounts = currentMounts()
        // Which whole disks each mounted volume lives on (an APFS volume: its container and the container's store).
        var volumesByDisk: [String: [MountedVolume]] = [:]
        var startup: Set<String> = []
        for m in mounts {
            let owners = wholeDisks(holding: m.device)
            for o in owners {
                volumesByDisk[o, default: []].append(MountedVolume(name: m.name, mountPoint: m.mountPoint,
                                                                   bsdName: m.device))
            }
            if m.mountPoint == "/" || m.mountPoint == "/System/Volumes" || m.mountPoint.hasPrefix("/System/Volumes/") {
                startup.formUnion(owners)
            }
        }
        var disks: [DiskDescription] = []
        if let session {
            for bsd in wholeDiskNames() {
                if var d = describe(bsd, session: session) {
                    d.volumes = volumesByDisk[bsd] ?? []
                    disks.append(d)
                }
            }
        }
        disks.sort { (Int($0.bsdName.dropFirst(4)) ?? 0) < (Int($1.bsdName.dropFirst(4)) ?? 0) }
        let protected = [NSHomeDirectory(), Bundle.main.bundlePath, NSTemporaryDirectory()]
            .map { URL(fileURLWithPath: $0).resolvingSymlinksInPath().path }
        return DiskSnapshot(disks: disks, startupDisks: startup, protectedPaths: protected)
    }

    /// The BSD names of every whole disk ("disk0", "disk4"...), from IOKit.
    static func wholeDiskNames() -> [String] {
        var names: [String] = []
        guard let matching = IOServiceMatching("IOMedia") as NSMutableDictionary? else { return names }
        matching["Whole"] = true
        var iter: io_iterator_t = 0
        guard IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iter) == KERN_SUCCESS else { return names }
        defer { IOObjectRelease(iter) }
        while case let entry = IOIteratorNext(iter), entry != 0 {
            if let bsd = IORegistryEntryCreateCFProperty(entry, "BSD Name" as CFString, kCFAllocatorDefault, 0)?
                .takeRetainedValue() as? String {
                names.append(bsd)
            }
            IOObjectRelease(entry)
        }
        return names
    }

    /// One whole disk, or nil if DiskArbitration doesn't know it (it went away).
    static func describe(_ bsd: String, session: DASession) -> DiskDescription? {
        guard let disk = DADiskCreateFromBSDName(kCFAllocatorDefault, session, bsd),
              let d = DADiskCopyDescription(disk) as? [String: Any] else { return nil }
        func bool(_ k: CFString) -> Bool? { (d[k as String] as? NSNumber)?.boolValue }
        func string(_ k: CFString) -> String? {
            (d[k as String] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let icon = (d[kDADiskDescriptionMediaIconKey as String] as? [String: Any])?["IOBundleResourceFile"] as? String
        let size = (d[kDADiskDescriptionMediaSizeKey as String] as? NSNumber)?.int64Value ?? 0
        let block = (d[kDADiskDescriptionMediaBlockSizeKey as String] as? NSNumber)?.intValue ?? 0
        let appeared = (d["DAAppearanceTime"] as? NSNumber)?.doubleValue
        return DiskDescription(
            bsdName: bsd,
            isWhole: bool(kDADiskDescriptionMediaWholeKey) ?? false,
            sizeBytes: size,
            blockSize: block,
            isWritable: bool(kDADiskDescriptionMediaWritableKey) ?? false,
            isInternal: bool(kDADiskDescriptionDeviceInternalKey),
            isRemovable: bool(kDADiskDescriptionMediaRemovableKey) ?? false,
            isEjectable: bool(kDADiskDescriptionMediaEjectableKey) ?? false,
            isNetwork: bool(kDADiskDescriptionVolumeNetworkKey) ?? false,
            protocolName: string(kDADiskDescriptionDeviceProtocolKey),
            vendor: string(kDADiskDescriptionDeviceVendorKey),
            model: string(kDADiskDescriptionDeviceModelKey),
            mediaName: string(kDADiskDescriptionMediaNameKey),
            iconFile: icon,
            mediaPath: string(kDADiskDescriptionMediaPathKey),
            appearanceTime: appeared,
            ioClassChain: classChain(bsd))
    }

    /// IOKit classes from the disk's media up through its providers (12 at most).
    static func classChain(_ bsd: String) -> [String] {
        var chain: [String] = []
        var entry = IOServiceGetMatchingService(kIOMainPortDefault, IOBSDNameMatching(kIOMainPortDefault, 0, bsd))
        var depth = 0
        while entry != 0 && depth < 12 {
            var name = [CChar](repeating: 0, count: 128)
            IOObjectGetClass(entry, &name)
            chain.append(String(cString: name))
            var parent: io_registry_entry_t = 0
            let kr = IORegistryEntryGetParentEntry(entry, kIOServicePlane, &parent)
            IOObjectRelease(entry)
            entry = kr == KERN_SUCCESS ? parent : 0
            depth += 1
        }
        if entry != 0 { IOObjectRelease(entry) }
        return chain
    }

    /// The whole disks a device lives on: itself if whole, and every whole IOMedia above it (for an APFS volume, its
    /// container and the physical disk the container is on). Walks every provider, not just the first.
    static func wholeDisks(holding bsd: String) -> Set<String> {
        var out: Set<String> = []
        let start = IOServiceGetMatchingService(kIOMainPortDefault, IOBSDNameMatching(kIOMainPortDefault, 0, bsd))
        guard start != 0 else { return out }
        var queue: [io_registry_entry_t] = [start]
        var seen: Set<UInt64> = []
        var steps = 0
        while !queue.isEmpty && steps < 200 {
            let entry = queue.removeFirst()
            steps += 1
            var id: UInt64 = 0
            IORegistryEntryGetRegistryEntryID(entry, &id)
            if seen.insert(id).inserted {
                if IOObjectConformsTo(entry, "IOMedia") != 0,
                   let whole = IORegistryEntryCreateCFProperty(entry, "Whole" as CFString, kCFAllocatorDefault, 0)?
                    .takeRetainedValue() as? Bool, whole,
                   let name = IORegistryEntryCreateCFProperty(entry, "BSD Name" as CFString, kCFAllocatorDefault, 0)?
                    .takeRetainedValue() as? String {
                    out.insert(name)
                }
                var iter: io_iterator_t = 0
                if IORegistryEntryGetParentIterator(entry, kIOServicePlane, &iter) == KERN_SUCCESS {
                    while case let p = IOIteratorNext(iter), p != 0 { queue.append(p) }
                    IOObjectRelease(iter)
                }
            }
            IOObjectRelease(entry)
        }
        for e in queue { IOObjectRelease(e) }
        return out
    }

    /// Every mounted local file system that comes from a /dev/disk device.
    static func currentMounts() -> [Mount] {
        var buf: UnsafeMutablePointer<statfs>?
        let n = getmntinfo(&buf, MNT_NOWAIT)
        guard n > 0, let buf else { return [] }
        var out: [Mount] = []
        for i in 0..<Int(n) {
            var fs = buf[i]
            let from = withUnsafePointer(to: &fs.f_mntfromname) {
                $0.withMemoryRebound(to: CChar.self, capacity: Int(MAXPATHLEN)) { String(cString: $0) }
            }
            let on = withUnsafePointer(to: &fs.f_mntonname) {
                $0.withMemoryRebound(to: CChar.self, capacity: Int(MAXPATHLEN)) { String(cString: $0) }
            }
            guard from.hasPrefix("/dev/disk") else { continue }
            let url = URL(fileURLWithPath: on)
            let name = (try? url.resourceValues(forKeys: [.volumeNameKey]))?.volumeName
                ?? (on == "/" ? "Macintosh HD" : url.lastPathComponent)
            out.append(Mount(device: String(from.dropFirst("/dev/".count)), mountPoint: on, name: name))
        }
        return out
    }

    /// Volumes still mounted from `bsd` (directly, or from APFS containers on it).
    static func mounts(on bsd: String) -> [Mount] {
        currentMounts().filter { wholeDisks(holding: $0.device).contains(bsd) }
    }
}

/// Calls `onChange` (on the main queue, at most a few times a second) when disks come, go or change.
public final class DiskWatcher {
    private let session: DASession
    private let queue = DispatchQueue(label: "uk.edgeventure.sofa-box-imager.disk-watch")
    private let onChange: () -> Void
    private var pending = false

    public init?(onChange: @escaping () -> Void) {
        guard let s = DASessionCreate(kCFAllocatorDefault) else { return nil }
        session = s
        self.onChange = onChange
        let ctx = Unmanaged.passUnretained(self).toOpaque()
        DARegisterDiskAppearedCallback(session, nil, { _, ctx in DiskWatcher.from(ctx).changed() }, ctx)
        DARegisterDiskDisappearedCallback(session, nil, { _, ctx in DiskWatcher.from(ctx).changed() }, ctx)
        DARegisterDiskDescriptionChangedCallback(session, nil, nil, { _, _, ctx in DiskWatcher.from(ctx).changed() }, ctx)
        DASessionSetDispatchQueue(session, queue)
    }

    deinit {
        DASessionSetDispatchQueue(session, nil)
    }

    private static func from(_ ctx: UnsafeMutableRawPointer?) -> DiskWatcher {
        Unmanaged<DiskWatcher>.fromOpaque(ctx!).takeUnretainedValue()
    }

    private func changed() {                    // on `queue`
        guard !pending else { return }
        pending = true
        queue.asyncAfter(deadline: .now() + 0.4) { [weak self] in
            guard let self else { return }
            self.pending = false
            DispatchQueue.main.async { self.onChange() }
        }
    }
}
