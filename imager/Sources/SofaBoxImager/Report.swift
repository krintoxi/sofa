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
                print("Sofa Box OS versions \(target == .pc ? "for a PC" : "for a Raspberry Pi"), from \(url.absoluteString):")
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
        if disks {
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
            if offered.isEmpty { print("  No \(target.word) to write: put \(target == .pc ? "a USB stick" : "an SD card") in.") }
        }
        return status
    }
}
