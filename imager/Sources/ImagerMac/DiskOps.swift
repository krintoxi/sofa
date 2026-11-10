import CAuthOpen
import DiskArbitration
import Foundation
import ImagerKit
import IOKit.pwr_mgt

public enum DiskOpError: Error, Equatable, CustomStringConvertible {
    case gone
    case unmountFailed(String)
    case stillMounted([String])
    case ejectFailed(String)
    case passwordCancelled
    case openFailed(Int32)
    case notTheSameDisk

    public var description: String {
        switch self {
        case .gone: return "The card isn't there any more."
        case .unmountFailed(let why):
            return "macOS wouldn't let go of the card's volumes (\(why)). Close anything using the card, then try again."
        case .stillMounted(let names):
            return "These volumes on the card are still in use: \(names.joined(separator: ", ")). Close anything using them, then try again."
        case .ejectFailed(let why):
            return "The card is written and checked, but macOS couldn't eject it (\(why)). Eject it in Finder before taking it out."
        case .passwordCancelled: return "Nothing was written: the password was cancelled (writing a card needs an administrator)."
        case .openFailed(let code): return "Nothing was written: macOS couldn't open the card (\(code))."
        case .notTheSameDisk:
            return "Nothing was written: the card changed since you chose it. Choose it again."
        }
    }
}

/// DiskArbitration's unmount and eject, waited for.
enum DiskArbitrationOps {
    private static let queue = DispatchQueue(label: "uk.edgeventure.sofa-box-imager.disk-ops")

    private final class Box {
        var dissent: String?
        let done = DispatchSemaphore(value: 0)
    }

    private static func run(_ bsd: String, timeout: Double,
                            _ start: (DADisk, UnsafeMutableRawPointer) -> Void) throws -> String? {
        guard let session = DASessionCreate(kCFAllocatorDefault) else { throw DiskOpError.gone }
        DASessionSetDispatchQueue(session, queue)
        defer { DASessionSetDispatchQueue(session, nil) }
        guard let disk = DADiskCreateFromBSDName(kCFAllocatorDefault, session, bsd) else { throw DiskOpError.gone }
        let box = Box()
        let ctx = Unmanaged.passRetained(box).toOpaque()
        start(disk, ctx)
        if box.done.wait(timeout: .now() + timeout) == .timedOut { return "it took too long" }
        return box.dissent
    }

    private static let callback: DADiskUnmountCallback = { _, dissenter, ctx in
        let box = Unmanaged<Box>.fromOpaque(ctx!).takeRetainedValue()
        if let dissenter {
            let status = DADissenterGetStatus(dissenter)
            let text = DADissenterGetStatusString(dissenter) as String?
            box.dissent = text ?? String(format: "0x%08x", UInt32(bitPattern: status))
        }
        box.done.signal()
    }

    /// Unmounts every volume of the whole disk `bsd`. Not forced: a volume in use stops it.
    static func unmountWhole(_ bsd: String) throws {
        if let why = try run(bsd, timeout: 60, { disk, ctx in
            DADiskUnmount(disk, DADiskUnmountOptions(kDADiskUnmountOptionWhole), callback, ctx)
        }) {
            throw DiskOpError.unmountFailed(why)
        }
    }

    static func eject(_ bsd: String) throws {
        if let why = try run(bsd, timeout: 60, { disk, ctx in
            DADiskEject(disk, DADiskEjectOptions(kDADiskEjectOptionDefault), callback, ctx)
        }) {
            throw DiskOpError.ejectFailed(why)
        }
    }

    /// Unmounts everything on `bsd`, including volumes in APFS containers whose store is on it, and checks nothing is
    /// left mounted.
    static func unmountEverything(on bsd: String) throws {
        if !DiskList.mounts(on: bsd).isEmpty { try unmountWhole(bsd) }
        // APFS volumes live on their own synthesized disk: unmount those whole disks too.
        for m in DiskList.mounts(on: bsd) {
            for owner in DiskList.wholeDisks(holding: m.device) where owner != bsd {
                try? unmountWhole(owner)
            }
        }
        let left = DiskList.mounts(on: bsd)
        if !left.isEmpty { throw DiskOpError.stillMounted(left.map { $0.name }) }
    }
}

/// While a card is written, refuses every attempt to mount anything from it (macOS would otherwise mount its boot
/// partition the moment it sees a partition table there).
final class MountBlocker {
    private let session: DASession
    private let queue = DispatchQueue(label: "uk.edgeventure.sofa-box-imager.mount-block")
    let target: String

    init?(blocking bsd: String) {
        guard let s = DASessionCreate(kCFAllocatorDefault) else { return nil }
        session = s
        target = bsd
        let ctx = Unmanaged.passRetained(self).toOpaque()
        DARegisterDiskMountApprovalCallback(session, nil, { disk, ctx in
            let me = Unmanaged<MountBlocker>.fromOpaque(ctx!).takeUnretainedValue()
            guard let name = DADiskGetBSDName(disk).map({ String(cString: $0) }) else { return nil }
            guard DiskList.wholeDisks(holding: name).contains(me.target) else { return nil }
            let d = DADissenterCreate(kCFAllocatorDefault, DAReturn(kDAReturnBusy),
                                      "Sofa Box Imager is writing this card" as CFString)
            return Unmanaged.passRetained(d)
        }, ctx)
        DASessionSetDispatchQueue(session, queue)
        self.ctx = ctx
    }

    private var ctx: UnsafeMutableRawPointer?

    func stop() {
        DASessionSetDispatchQueue(session, nil)
        if let ctx {
            Unmanaged<MountBlocker>.fromOpaque(ctx).release()
            self.ctx = nil
        }
    }
}

/// Opens a raw disk read-write. The app's only one is `AuthOpener`.
public protocol DiskOpener {
    func open(rawPath: String) throws -> Int32
}

/// Opens the disk through macOS's own `authopen`, which asks for an administrator's password in macOS's own dialog.
/// Sofa Box Imager never sees the password and installs no helper.
public struct AuthOpener: DiskOpener {
    public var prompt: String
    public var interactive: Bool

    public init(prompt: String = "Sofa Box Imager needs your password to write the card.", interactive: Bool = true) {
        self.prompt = prompt
        self.interactive = interactive
    }

    public func open(rawPath: String) throws -> Int32 {
        var fd: Int32 = -1
        var detail: Int32 = 0
        let r = cauthopen_open(rawPath, O_RDWR, prompt, interactive ? 1 : 0, &fd, &detail)
        switch Int(r) {
        case Int(CAUTHOPEN_OK): return fd
        case Int(CAUTHOPEN_CANCELLED): throw DiskOpError.passwordCancelled
        default: throw DiskOpError.openFailed(detail)
        }
    }
}

/// Keeps the Mac from sleeping while a card is written.
final class SleepGuard {
    private var id: IOPMAssertionID = 0
    private var held = false

    init(reason: String) {
        held = IOPMAssertionCreateWithName("PreventUserIdleSystemSleep" as CFString,
                                           IOPMAssertionLevel(kIOPMAssertionLevelOn), reason as CFString,
                                           &id) == kIOReturnSuccess
    }

    func release() {
        if held { IOPMAssertionRelease(id) }
        held = false
    }

    deinit { release() }
}
