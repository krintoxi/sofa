import CAuthOpen
import Foundation
import ImagerKit

/// One card written, start to finish, in the only order Sofa Box Imager knows:
///
/// 1. Look at the disk again: it must be the very disk the owner confirmed (same device, media, appearance and size),
///    and `DiskPolicy` must still allow it.
/// 2. Refuse mounts from it, then unmount every volume on it.
/// 3. Open `/dev/rdiskN` through `authopen` (macOS's own password prompt), and check the opened disk's own size and
///    sector size against the confirmed ones.
/// 4. Download, unpack and write (`CardPipeline`): the first and last megabytes blanked, aligned 1 MiB writes, the
///    first megabyte last, then every byte read back and checked against the list's SHA-256.
/// 5. Eject.
public final class WriteJob: @unchecked Sendable {     // its state is behind `lock`
    public enum Stage: Equatable {
        case checking
        case unmounting
        case waitingForPassword
        case writing(WriteProgress)
        case ejecting
        case done
    }

    public let card: Card
    public let confirmed: DiskDescription
    private let makeSource: () throws -> PackedSource
    private let opener: DiskOpener
    /// Which disks may be written. Always `DiskPolicy` (through the snapshot) in the app; tests that write a RAM disk
    /// they attached themselves replace it, since the policy rightly refuses disk images.
    var vet: (DiskDescription, DiskSnapshot) -> [DiskRefusal] = { d, snap in snap.refusals(for: d, needs: 0) }
    private let lock = NSLock()
    private var cancelled = false
    private var source: PackedSource?

    public init(card: Card, disk: DiskDescription, opener: DiskOpener = AuthOpener(),
                source: @escaping () throws -> PackedSource) {
        self.card = card
        confirmed = disk
        self.opener = opener
        makeSource = source
        vet = { [card] d, snap in snap.refusals(for: d, needs: card.extractSize) }
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

        let awake = SleepGuard(reason: "Writing a Sofa Box card")
        defer { awake.release() }
        let src = try makeSource()
        lock.lock()
        source = src
        let stop = cancelled
        lock.unlock()
        if stop { throw WriteError.cancelled }
        let device = FileDescriptorDevice(fd: fd, extraSync: { _ = cauthopen_sync_disk($0) })
        try CardPipeline.run(source: src, device: device, card: card, diskSize: confirmed.sizeBytes,
                             sectorBytes: confirmed.blockSize,
                             progress: { stage(.writing($0)) },
                             isCancelled: { [weak self] in self?.isCancelled ?? true })
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
    default: return error.localizedDescription
    }
}
