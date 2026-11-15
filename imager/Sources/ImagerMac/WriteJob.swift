import CAuthOpen
import Foundation
import ImagerKit

/// One disk written, start to finish, in the only order Sofa Box Imager knows:
///
/// 1. Look at the disk again: it must be the very disk the owner confirmed (same device, media, appearance and size),
///    and `DiskPolicy` must still allow it.
/// 2. Make the plan: what goes on the disk (a card from the list, a Linux ISO, the owner's own image, or a Windows stick
///    laid out for this disk's size).
/// 3. Refuse mounts from it, then unmount every volume on it.
/// 4. Open `/dev/rdiskN` through `authopen` (macOS's own password prompt), and check the opened disk's own size and
///    sector size against the confirmed ones.
/// 5. Write (`CardPipeline`): the first and last megabytes blanked, aligned 1 MiB writes, the first megabyte last, then
///    every byte read back and checked against the SHA-256 (the list's, the project's, or what was streamed).
/// 6. Eject.
public final class WriteJob: @unchecked Sendable {     // its state is behind `lock`
    public enum Stage: Equatable {
        case checking
        case preparing
        case unmounting
        case waitingForPassword
        case writing(WriteProgress)
        case ejecting
        case done
    }

    /// What's written, in words ("Sofa Box OS 1.1.86", "Ubuntu Desktop 26.04.1 LTS", "Windows 11 (x64)").
    public let title: String
    /// The smallest disk it fits on: the policy refuses anything smaller.
    public let needs: Int64
    public let confirmed: DiskDescription
    private let makePlan: (DiskDescription) throws -> WritePlan
    private let opener: DiskOpener
    /// Which disks may be written. Always `DiskPolicy` (through the snapshot) in the app; tests that write a RAM disk
    /// they attached themselves replace it, since the policy rightly refuses disk images.
    var vet: (DiskDescription, DiskSnapshot) -> [DiskRefusal] = { d, snap in snap.refusals(for: d, needs: 0) }
    private let lock = NSLock()
    private var cancelled = false
    private var source: PackedSource?
    /// The SHA-256 the disk read back as, once it's written.
    public private(set) var writtenSHA256: String?

    /// A card from the list (packed, or an ISO written whole), checked against the list's SHA-256.
    public convenience init(card: Card, disk: DiskDescription, opener: DiskOpener = AuthOpener(),
                            source: @escaping () throws -> PackedSource) {
        self.init(title: card.name, needs: card.extractSize, disk: disk, opener: opener) { _ in
            .card(card, source: source)
        }
    }

    /// Anything else: `plan` is made once the disk is looked at again, before anything is unmounted.
    public init(title: String, needs: Int64, disk: DiskDescription, opener: DiskOpener = AuthOpener(),
                plan: @escaping (DiskDescription) throws -> WritePlan) {
        self.title = title
        self.needs = needs
        confirmed = disk
        self.opener = opener
        makePlan = plan
        vet = { d, snap in snap.refusals(for: d, needs: needs) }
    }

    public func cancel() {
        lock.lock()
        cancelled = true
        let s = source
        lock.unlock()
        s?.cancel()
    }

    private var isCancelled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancelled
    }

    /// Runs the whole job on the calling thread (not the main one). `stage` is called on that thread.
    public func run(stage: @escaping (Stage) -> Void) throws {
        stage(.checking)
        let bsd = confirmed.bsdName
        let snapshot = DiskList.snapshot()
        guard let now = snapshot.disk(bsd) else { throw DiskOpError.gone }
        guard now.isSameDisk(as: confirmed) else { throw DiskOpError.notTheSameDisk }
        let refusals = vet(now, snapshot)
        if !refusals.isEmpty { throw JobError.refused(refusals) }
        if isCancelled { throw WriteError.cancelled }

        stage(.preparing)
        let plan = try makePlan(confirmed)
        guard plan.size <= confirmed.sizeBytes else { throw WriteError.cardTooBig(card: plan.size, disk: confirmed.sizeBytes) }
        if isCancelled { throw WriteError.cancelled }

        let blocker = MountBlocker(blocking: bsd)
        defer { blocker?.stop() }
        stage(.unmounting)
        try DiskArbitrationOps.unmountEverything(on: bsd)

        stage(.waitingForPassword)
        let fd = try opener.open(rawPath: confirmed.rawDevicePath)
        var closed = false
        defer { if !closed { close(fd) } }
        // The disk that opened must be the one confirmed, byte for byte in size.
        var sector: UInt32 = 0
        var count: UInt64 = 0
        let g = cauthopen_geometry(fd, &sector, &count)
        guard g == 0, Int(sector) == confirmed.blockSize,
              Int64(clamping: count) &* Int64(sector) == confirmed.sizeBytes else {
            throw DiskOpError.notTheSameDisk
        }
        _ = fcntl(fd, F_NOCACHE, 1)                    // read back from the card, not from memory
        if isCancelled { throw WriteError.cancelled }

        let awake = SleepGuard(reason: "Writing a disk with Sofa Box Imager")
        defer { awake.release() }
        let device = FileDescriptorDevice(fd: fd, extraSync: { _ = cauthopen_sync_disk($0) })
        let tracked = WritePlan(name: plan.name, size: plan.size, sha256: plan.sha256, packed: plan.packed,
                                downloads: plan.downloads) { [weak self] in
            let src = try plan.makeSource()
            guard let self else { return src }
            self.lock.lock()
            self.source = src
            let stop = self.cancelled
            self.lock.unlock()
            if stop { throw WriteError.cancelled }
            return src
        }
        let sha = try CardPipeline.run(plan: tracked, device: device, diskSize: confirmed.sizeBytes,
                                       sectorBytes: confirmed.blockSize,
                                       progress: { stage(.writing($0)) },
                                       isCancelled: { [weak self] in self?.isCancelled ?? true })
        lock.lock()
        writtenSHA256 = sha
        lock.unlock()
        close(fd)
        closed = true

        // Mounts stay refused until the card is ejected, so macOS never mounts the new card's boot partition.
        stage(.ejecting)
        try? DiskArbitrationOps.unmountEverything(on: bsd)
        try DiskArbitrationOps.eject(bsd)
        stage(.done)
    }
}

public enum JobError: Error, Equatable, CustomStringConvertible {
    case refused([DiskRefusal])

    public var description: String {
        switch self {
        case .refused(let why):
            return "Nothing was written: Sofa Box Imager won't write this disk. " + why.map { $0.text }.joined(separator: " ")
        }
    }
}

/// What went wrong, in the words the owner reads.
public func plainWords(_ error: Error) -> String {
    switch error {
    case let e as WriteError: return e.description
    case let e as DownloadError: return e.description
    case let e as XZError: return e.description
    case let e as DiskOpError: return e.description
    case let e as JobError: return e.description
    case let e as CardListError: return e.description
    case let e as BurnError: return e.description
    case let e as CatalogError: return e.description
    case let e as UDFError: return e.description
    case let e as WIMError: return e.description
    case let e as FATError: return e.description
    case let e as WindowsStickError: return e.description
    case let e as WindowsMedia.DetectError: return e.description
    case let e as ReadError: return e.description
    default: return error.localizedDescription
    }
}

extension WriteJob {
    /// A Windows stick from the owner's ISO: laid out for the disk once it's looked at again, every file read from the
    /// ISO as it's written, the stick read back against what was written.
    public static func windows(iso url: URL, media: WindowsMedia, options: WindowsOptions, disk: DiskDescription,
                               opener: DiskOpener = AuthOpener()) -> WriteJob {
        WriteJob(title: media.title, needs: media.stickBytesNeeded, disk: disk, opener: opener) { d in
            let iso = try FileRandomAccess(url: url)
            let (stick, built) = try WindowsStick.build(iso: iso, diskBytes: d.sizeBytes, sectorBytes: d.blockSize,
                                                        options: options)
            let layout = stick.layout
            return WritePlan(name: built.title, size: layout.length, sha256: nil, packed: false, downloads: false) {
                LayoutSource(layout)
            }
        }
    }

    /// An image of the owner's own, written whole (or unpacked, for `.xz`), read back against what was read.
    public static func image(_ url: URL, kind: ImageKind, bytes: Int64, disk: DiskDescription,
                             opener: DiskOpener = AuthOpener()) -> WriteJob {
        var packed = false
        if case .packedImage = kind { packed = true }
        return WriteJob(title: url.lastPathComponent, needs: bytes, disk: disk, opener: opener) { _ in
            WritePlan(name: url.lastPathComponent, size: bytes, sha256: nil, packed: packed, downloads: false) {
                packed ? try FileSource(url: url) as PackedSource : RandomAccessSource(try FileRandomAccess(url: url))
            }
        }
    }
}
