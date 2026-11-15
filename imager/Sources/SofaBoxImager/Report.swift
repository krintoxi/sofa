import Foundation
import ImagerKit
import ImagerMac

/// `--versions` and `--disks`: what the app would show, as text. Reads only; never opens or writes a disk.
enum Report {
    static func run(versions: Bool, disks: Bool) -> Int32 {
        var needs: Int64 = 1
        var status: Int32 = 0
        let url = ImagerModel.chosenListURL()
        let target = ImagerModel.chosenTarget()           // --for pc: the PC's versions, and what a stick must hold
        // The list, fetched and waited for (this is a command line tool here, with nothing else to do meanwhile).
        final class Answer: @unchecked Sendable {
            var list: CardList?
            var failure = ""
        }
        let answer = Answer()
        let done = DispatchSemaphore(value: 0)
        Task.detached {
            do {
                answer.list = try CardListParser.parse(try await ImagerModel.fetchList(url), for: target,
                                                       allowLocalFiles: url.isFileURL)
            } catch {
                answer.failure = plainWords(error)
            }
            done.signal()
        }
        done.wait()
        let list = answer.list
        let failure = answer.failure
        if let list {
            needs = (list.newest ?? list.all.first)?.extractSize ?? 1
            if versions {
                print("Sofa Box OS versions \(target == .dvd ? "on a DVD" : target == .pc ? "for a PC" : "for a Raspberry Pi"), from \(url.absoluteString):")
                for c in list.all {
                    let mark = c == list.newest ? "newest " : (list.earlier.contains(c) ? "earlier" : "       ")
                    print("  \(mark)  \(c.name)  \(c.releaseDate)  \(ByteSize.text(c.downloadSize)) download, "
                          + "\(ByteSize.text(c.extractSize)) on the \(target.word)  \(c.url.absoluteString)")
                }
                for s in list.skipped { print("  left out: \(s)") }
            }
        } else {
            print("Couldn't get the list of versions from \(url.absoluteString): \(failure)")
            status = 1
        }
        if disks, target.burns {
            print("DVD burners (a blank DVD must hold \(ByteSize.text(needs))):")
            let burners = BurnerList.snapshot()
            for b in burners {
                print("  \(b.refusal(needs: needs) == nil ? "OFFERED" : "refused")  \(b.name)  \(b.subtitle(needs: needs))  \(b.id)")
            }
            if burners.isEmpty { print("  No DVD burner: plug one in and put a blank DVD in.") }
        } else if disks {
            let snap = DiskList.snapshot()
            let (offered, refused) = snap.sorted(needs: needs)
            print("Disks (a \(target.word) must hold \(ByteSize.text(needs))):")
            for d in offered {
                print("  OFFERED  /dev/\(d.bsdName)  \(d.displayName)  \(ByteSize.text(d.sizeBytes))  \(d.protocolName ?? "?")")
            }
            for (d, why) in refused {
                print("  refused  /dev/\(d.bsdName)  \(d.displayName)  \(ByteSize.text(d.sizeBytes))  \(d.protocolName ?? "?")")
                for w in why { print("             \(w.text)") }
            }
            if offered.isEmpty { print("  No \(target.word) to write: put \(target == .raspberryPi ? "an SD card" : "a USB stick") in.") }
        }
        return status
    }

    /// `--inspect FILE`: what the Imager makes of an image file, and for a Windows ISO the stick it would make. Reads only.
    static func inspect(_ url: URL) -> Int32 {
        do {
            let file = try FileRandomAccess(url: url)
            print("\(url.path): \(ByteSize.text(file.size))")
            let kind = try ImageInspector.inspect(file, name: url.lastPathComponent)
            print("  \(kind.summary)")
            guard case .windows(let w) = kind else { return kind == .unknown || kind == .discOnly ? 1 : 0 }
            print("  \(w.starts)")
            print("  editions: \(w.editions.joined(separator: ", "))")
            print("  \(w.installPath): \(ByteSize.text(w.installBytes))\(w.installIsSolid ? " (solid, ESD)" : "")"
                  + (w.needsSplit ? ", split into .swm parts for FAT32" : ""))
            print("  BOOTMGR \(ByteSize.text(w.bootmgrBytes)), UEFI loader: \(w.uefi)")
            if let why = w.refusal { print("  can't make a stick: \(why)"); return 1 }
            let size = max(Int64(16_000_000_000), w.stickBytesNeeded)
            let start = Date()
            let (stick, _) = try WindowsStick.build(iso: file, diskBytes: size, sectorBytes: 512)
            print("  on a \(ByteSize.text(size)) stick: FAT32, \(stick.clusterBytes / 1024) KB clusters, "
                  + "\(stick.usedClusters) of \(stick.clusters) used, \(ByteSize.text(stick.layout.length)) written, "
                  + "BOOTMGR at sector \(stick.loader.map { "\($0.sector), \($0.count) sectors" } ?? "none") "
                  + "(planned in \(String(format: "%.1f", Date().timeIntervalSince(start))) s)")
            print("  needs a stick of \(ByteSize.text(w.stickBytesNeeded)) or more")
            return 0
        } catch {
            print("  \(plainWords(error))")
            return 1
        }
    }

    /// `--systems`: the other systems' newest releases, as found on their own sites now.
    static func systems() -> Int32 {
        final class Box: @unchecked Sendable { var lines: [String] = []; var failed = false }
        let box = Box()
        let done = DispatchSemaphore(value: 0)
        Task.detached {
            for e in Catalog.entries {
                do {
                    let c = try await CatalogResolver.resolve(e, with: URLSessionFetcher())
                    box.lines.append("  \(c.name)  \(ByteSize.text(c.extractSize))  sha256 \(c.extractSHA256)  \(c.url.absoluteString)")
                } catch {
                    box.lines.append("  \(e.name): \(plainWords(error))")
                    box.failed = true
                }
            }
            done.signal()
        }
        done.wait()
        print("Other systems, from each project's own site:")
        box.lines.forEach { print($0) }
        return box.failed ? 1 : 0
    }
}

