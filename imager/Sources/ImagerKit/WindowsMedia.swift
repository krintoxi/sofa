import Foundation

/// A Windows installer ISO, as Microsoft makes them (Windows 7, 8.1, 10 and 11): what's in it, and whether a stick
/// made from it starts BIOS PCs, UEFI PCs or both. Sofa Box Imager never downloads Windows: the owner brings the ISO
/// (Microsoft's own download page has Windows 10 and 11).
public struct WindowsMedia: Equatable {
    public enum Version: String, Equatable {
        case seven = "7", eight = "8.1", ten = "10", eleven = "11"
    }

    public enum Arch: String, Equatable {
        case x86, x64, arm64
        /// Unattend files' name for it.
        var unattend: String {
            switch self {
            case .x86: return "x86"
            case .x64: return "amd64"
            case .arm64: return "arm64"
            }
        }
    }

    /// How a UEFI PC starts the stick.
    public enum UEFILoader: Equatable {
        /// The ISO has `efi/boot/bootx64.efi` (or bootaa64.efi, bootia32.efi), copied as it is.
        case onTheISO(String)
        /// Windows 7: the loader is only inside the ISO's UEFI boot image (`efi/microsoft/boot/efisys.bin`), and is
        /// copied out of it to `efi/boot/bootx64.efi`.
        case fromEfisys
        case none
    }

    public var version: Version
    public var build: Int?
    public var arch: Arch
    public var editions: [String]
    /// "sources/install.wim", "sources/install.esd" or "sources/install.swm", as the ISO spells it.
    public var installPath: String
    public var installBytes: Int64
    public var installIsSolid: Bool
    public var volumeName: String
    public var biosBoot: Bool
    public var bootmgrBytes: Int64
    public var uefi: UEFILoader
    public var fileBytes: Int64
    public var fileCount: Int
    public var hasUnattend: Bool

    /// Whether `install.wim` must be split into `.swm` parts to fit FAT32 (a file can't reach 4 GB).
    public var needsSplit: Bool { installBytes > FAT32Stick.maxFile }

    /// "Windows 11 (x64)", "Windows 7 (x86)".
    public var title: String { "Windows \(version.rawValue) (\(arch == .x64 ? "x64" : arch == .arm64 ? "ARM64" : "32-bit"))" }

    /// Why it can't make a stick, in words; nil when it can.
    public var refusal: String? {
        if needsSplit && installIsSolid {
            return "Its \(installPath.split(separator: "/").last!) is \(ByteSize.text(installBytes)) and packed solid (an ESD), so it can't be split to fit FAT32. Microsoft's ISO from its download page has an install.wim, which can."
        }
        if !biosBoot && uefi == .none { return "It has neither BOOTMGR (for BIOS PCs) nor a UEFI loader: nothing could start the stick." }
        return nil
    }

    /// What a PC needs to start the stick, in words.
    public var starts: String {
        let uefiOK = uefi != .none
        switch (biosBoot, uefiOK) {
        case (true, true):
            return version == .seven
                ? "Starts PCs with BIOS or legacy boot (CSM). On UEFI it needs CSM on and Secure Boot off: Windows 7 predates both."
                : "Starts PCs with UEFI (Secure Boot on or off) and older ones with BIOS."
        case (true, false): return "Starts PCs with BIOS or legacy boot (CSM) only."
        case (false, true): return "Starts PCs with UEFI only."
        default: return "Starts nothing."
        }
    }

    public var summary: String {
        var s = title
        if let b = build { s += ", build \(b)" }
        s += " · \(editions.count == 1 ? "1 edition" : "\(editions.count) editions") · \(ByteSize.text(fileBytes))"
        return s
    }

    /// The smallest stick it fits on.
    public var stickBytesNeeded: Int64 {
        // Files rounded to 32 KB clusters, the folders, the FATs, the first megabyte, and a margin.
        fileBytes + Int64(fileCount) * 32768 + (64 << 20)
    }

    public enum DetectError: Error, Equatable, CustomStringConvertible {
        case notWindows(String)
        public var description: String {
            switch self {
            case .notWindows(let why): return "It isn't a Windows installer ISO: \(why)."
            }
        }
    }

    /// Reads a Windows ISO's UDF folders and its install image's header and XML.
    public static func detect(_ iso: RandomAccess) throws -> WindowsMedia {
        let volume = try UDFReader.read(iso)
        return try detect(volume.root, iso: iso, volumeName: volume.name)
    }

    static func detect(_ root: UDFNode, iso: RandomAccess, volumeName: String) throws -> WindowsMedia {
        guard let sources = root.child("sources"), sources.isDirectory else { throw DetectError.notWindows("no sources folder") }
        guard sources.child("boot.wim") != nil else { throw DetectError.notWindows("no sources/boot.wim") }
        guard let install = ["install.wim", "install.esd", "install.swm"].lazy.compactMap({ sources.child($0) }).first,
              !install.isDirectory else {
            throw DetectError.notWindows("no sources/install.wim or install.esd")
        }
        let wim = try WIMFile(install.contents(in: iso))
        guard let first = wim.images.first else { throw DetectError.notWindows("its install image lists no Windows") }
        let major = first.major ?? 0
        let minor = first.minor ?? 0
        let build = first.build
        let version: Version
        switch (major, minor) {
        case (6, 1): version = .seven
        case (6, 2), (6, 3): version = .eight
        case (10, _): version = (build ?? 0) >= 22000 ? .eleven : .ten
        default: throw DetectError.notWindows("Windows \(major).\(minor) isn't one Sofa Box Imager makes sticks for")
        }
        let arch: Arch
        switch first.arch {
        case 0: arch = .x86
        case 12: arch = .arm64
        default: arch = .x64
        }
        let bootmgr = root.child("bootmgr")
        // BIOS PCs: BOOTMGR and its BCD, and BOOTMGR small enough for where a boot sector puts it.
        let bios = bootmgr != nil && root.find("boot/bcd") != nil && arch != .arm64
            && (bootmgr?.size ?? 0) <= BootCode.largestLoader
        let loaderName = arch == .x64 ? "bootx64.efi" : arch == .arm64 ? "bootaa64.efi" : "bootia32.efi"
        var uefi = UEFILoader.none
        if let l = root.find("efi/boot/" + loaderName), !l.isDirectory {
            uefi = .onTheISO("efi/boot/" + l.name)
        } else if arch == .x64, root.find("efi/microsoft/boot/efisys.bin") != nil, root.find("efi/microsoft/boot/bcd") != nil {
            uefi = .fromEfisys
        }
        var count = 0
        root.walk { _, n in if !n.isDirectory { count += 1 } }
        let names = wim.images.map { $0.displayName.isEmpty ? $0.name : $0.displayName }.filter { !$0.isEmpty }
        return WindowsMedia(version: version, build: build, arch: arch, editions: names,
                            installPath: "sources/" + install.name, installBytes: install.size,
                            installIsSolid: wim.hasSolidResources, volumeName: volumeName, biosBoot: bios,
                            bootmgrBytes: bootmgr?.size ?? 0, uefi: uefi, fileBytes: root.totalFileBytes,
                            fileCount: count, hasUnattend: root.child("autounattend.xml") != nil)
    }
}

/// The Windows 11 switches the owner may tick (each off unless ticked), written as an `autounattend.xml` at the
/// stick's root, which Windows Setup reads by itself. Nothing else about Setup changes: it still asks which disk to
/// install on, and erases nothing by itself.
public struct WindowsOptions: Equatable {
    /// Setup skips its TPM 2.0, Secure Boot and 4 GB RAM checks (Microsoft's own LabConfig keys).
    public var skipHardwareChecks = false
    /// A local account with this name instead of a Microsoft account: the network isn't required to finish setting up,
    /// and the account's password is set at its first sign-in.
    public var localAccount: String?

    public init(skipHardwareChecks: Bool = false, localAccount: String? = nil) {
        self.skipHardwareChecks = skipHardwareChecks
        self.localAccount = localAccount
    }

    public var isEmpty: Bool { !skipHardwareChecks && localAccount == nil }

    /// Why a local account's name can't be used; nil when it can.
    public static func accountNameProblem(_ name: String) -> String? {
        let n = name.trimmingCharacters(in: .whitespaces)
        if n.isEmpty { return "Type a name for the account." }
        if n.count > 20 { return "Windows allows 20 characters at most." }
        if n.contains(where: { "\"/\\[]:;|=,+*?<>@%".contains($0) || $0.isNewline || ($0.asciiValue ?? 32) < 32 }) {
            return "Windows doesn't allow \" / \\ [ ] : ; | = , + * ? < > @ % in a name."
        }
        if n.allSatisfy({ $0 == "." || $0 == " " }) { return "The name can't be only dots and spaces." }
        let reserved = ["administrator", "guest", "defaultaccount", "wdagutilityaccount", "system", "user", "users",
                        "everyone", "administrators", "none"]
        if reserved.contains(n.lowercased()) { return "Windows keeps “\(n)” for itself: choose another name." }
        return nil
    }

    static func xmlEscape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&apos;")
    }

    /// The `autounattend.xml`, or nil when nothing is ticked.
    public func unattend(arch: WindowsMedia.Arch) -> String? {
        guard !isEmpty else { return nil }
        let a = arch.unattend
        let component = { (name: String) in
            "<component name=\"\(name)\" processorArchitecture=\"\(a)\" publicKeyToken=\"31bf3856ad364e35\" language=\"neutral\" versionScope=\"nonSxS\" xmlns:wcm=\"http://schemas.microsoft.com/WMIConfig/2002/State\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
        }
        var x = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        x += "<!-- Made by Sofa Box Imager for the switches ticked when this stick was written. -->\n"
        x += "<unattend xmlns=\"urn:schemas-microsoft-com:unattend\">\n"
        if skipHardwareChecks {
            x += "  <settings pass=\"windowsPE\">\n    \(component("Microsoft-Windows-Setup"))\n      <RunSynchronous>\n"
            for (i, key) in ["BypassTPMCheck", "BypassSecureBootCheck", "BypassRAMCheck"].enumerated() {
                x += "        <RunSynchronousCommand wcm:action=\"add\">\n"
                x += "          <Order>\(i + 1)</Order>\n"
                x += "          <Path>reg add HKLM\\SYSTEM\\Setup\\LabConfig /v \(key) /t REG_DWORD /d 1 /f</Path>\n"
                x += "        </RunSynchronousCommand>\n"
            }
            x += "      </RunSynchronous>\n    </component>\n  </settings>\n"
        }
        if let raw = localAccount {
            let name = WindowsOptions.xmlEscape(raw.trimmingCharacters(in: .whitespaces))
            x += "  <settings pass=\"specialize\">\n    \(component("Microsoft-Windows-Deployment"))\n      <RunSynchronous>\n"
            x += "        <RunSynchronousCommand wcm:action=\"add\">\n          <Order>1</Order>\n"
            x += "          <Path>reg add HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\OOBE /v BypassNRO /t REG_DWORD /d 1 /f</Path>\n"
            x += "        </RunSynchronousCommand>\n      </RunSynchronous>\n    </component>\n  </settings>\n"
            x += "  <settings pass=\"oobeSystem\">\n    \(component("Microsoft-Windows-Shell-Setup"))\n"
            x += "      <OOBE>\n        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>\n      </OOBE>\n"
            x += "      <UserAccounts>\n        <LocalAccounts>\n          <LocalAccount wcm:action=\"add\">\n"
            x += "            <Name>\(name)</Name>\n            <DisplayName>\(name)</DisplayName>\n"
            x += "            <Group>Administrators</Group>\n"
            x += "            <Password>\n              <Value></Value>\n              <PlainText>true</PlainText>\n            </Password>\n"
            x += "          </LocalAccount>\n        </LocalAccounts>\n      </UserAccounts>\n"
            x += "      <FirstLogonCommands>\n        <SynchronousCommand wcm:action=\"add\">\n          <Order>1</Order>\n"
            x += "          <CommandLine>net user &quot;\(name)&quot; /logonpasswordchg:yes</CommandLine>\n"
            x += "          <Description>Set this account's password at its next sign-in</Description>\n"
            x += "        </SynchronousCommand>\n      </FirstLogonCommands>\n    </component>\n  </settings>\n"
        }
        x += "</unattend>\n"
        return x
    }
}

/// Builds the FAT32 stick for a Windows ISO: every file of the ISO, `install.wim` split into `.swm` parts when it's
/// over FAT32's 4 GB limit (Microsoft's own documented way: `DISM /Split-Image`, which Setup reads by itself), Windows
/// 7's UEFI loader copied out of its boot image, the owner's switches as `autounattend.xml`, and our boot code for
/// BIOS PCs pointed at BOOTMGR.
public enum WindowsStick {
    /// - Parameters:
    ///   - splitAbove: an install image bigger than this is split (FAT32's limit; the tests pass less).
    ///   - partBytes: the most a split part holds.
    public static func build(iso: RandomAccess, diskBytes: Int64, sectorBytes: Int, options: WindowsOptions = .init(),
                             splitAbove: Int64 = FAT32Stick.maxFile,
                             partBytes: Int64 = WIMSplitter.defaultPartBytes) throws -> (FAT32Stick, WindowsMedia) {
        let volume = try UDFReader.read(iso)
        let media = try WindowsMedia.detect(volume.root, iso: iso, volumeName: volume.name)
        if let why = media.refusal { throw WindowsStickError.refused(why) }
        if !options.isEmpty {
            guard media.version == .eleven else { throw WindowsStickError.refused("The switches are for Windows 11 only.") }
            guard !media.hasUnattend else {
                throw WindowsStickError.refused("This ISO has its own autounattend.xml, so the switches can't be added.")
            }
            if let n = options.localAccount, let why = WindowsOptions.accountNameProblem(n) {
                throw WindowsStickError.refused(why)
            }
        }
        let root = FATItem.folder("", modified: volume.root.modified)
        func copy(_ node: UDFNode, into folder: FATItem, path: String) throws {
            for c in node.children {
                let p = path.isEmpty ? c.name : path + "/" + c.name
                if c.isDirectory {
                    let f = FATItem.folder(c.name, modified: c.modified)
                    folder.add(f)
                    try copy(c, into: f, path: p)
                } else if p.compare(media.installPath, options: .caseInsensitive) == .orderedSame && c.size > splitAbove {
                    let file = c.contents(in: iso)
                    let wim = try WIMFile(file)
                    let base = (c.name as NSString).deletingPathExtension
                    for part in try WIMSplitter.split(file, wim: wim, base: base, partBytes: partBytes) {
                        folder.add(.file(part.name, LayoutFile(part.layout), modified: c.modified))
                    }
                } else {
                    folder.add(.file(c.name, c.contents(in: iso), modified: c.modified))
                }
            }
        }
        try copy(volume.root, into: root, path: "")

        if media.uefi == .fromEfisys, let efisys = volume.root.find("efi/microsoft/boot/efisys.bin") {
            let image = try FATImage(efisys.contents(in: iso))
            guard let loader = try image.file("EFI/BOOT/BOOTX64.EFI") else {
                throw WindowsStickError.refused("Its UEFI boot image has no EFI/BOOT/BOOTX64.EFI.")
            }
            let efi = root.child("efi") ?? { let f = FATItem.folder("efi"); root.add(f); return f }()
            let boot = efi.child("boot") ?? { let f = FATItem.folder("boot"); efi.add(f); return f }()
            if boot.child("bootx64.efi") == nil { boot.add(.file("bootx64.efi", DataRandomAccess(try loader.read(at: 0, count: Int(loader.size))))) }
        }
        if let xml = options.unattend(arch: media.arch) {
            root.add(.file("autounattend.xml", DataRandomAccess(Data(xml.utf8))))
        }
        let bios = media.biosBoot && media.bootmgrBytes <= BootCode.largestLoader
        let label = "WINDOWS " + media.version.rawValue
        let seed = UInt32(truncatingIfNeeded: (media.volumeName + "\(iso.size)").utf8.reduce(UInt32(2_166_136_261)) {
            ($0 ^ UInt32($1)) &* 16_777_619
        })
        let stick = try FAT32Stick(root: root, diskBytes: diskBytes, sectorBytes: sectorBytes, label: label,
                                   loaderPath: bios ? volume.root.child("bootmgr")!.name : nil, seed: seed)
        return (stick, media)
    }
}

public enum WindowsStickError: Error, Equatable, CustomStringConvertible {
    case refused(String)
    public var description: String {
        switch self {
        case .refused(let why): return "Nothing was written: \(why)"
        }
    }
}
