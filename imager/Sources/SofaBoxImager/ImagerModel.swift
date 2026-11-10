import AppKit
import Foundation
import ImagerKit
import ImagerMac

/// Everything the window shows, and the one write it may be running.
@MainActor
final class ImagerModel: ObservableObject {
    enum ListState: Equatable {
        case loading
        case loaded(CardList)
        case failed(String)
    }

    enum Phase: Equatable {
        case choosing
        case running(String, Double?)
        case done(card: String, disk: String)
        case failed(String)
    }

    nonisolated static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"

    @Published var list: ListState = .loading
    @Published var card: Card? { didSet { refreshDisks() } }
    @Published var offered: [DiskDescription] = []
    @Published var refused: [(DiskDescription, [DiskRefusal])] = []
    @Published var diskName: String?
    @Published var phase: Phase = .choosing
    @Published var confirming = false
    /// What's being written to what, while it is.
    @Published var jobTitle = ""

    let listURL: URL
    let listIsLocal: Bool
    /// False in the tests that draw the window with made-up cards and disks: nothing is fetched or looked up.
    let live: Bool
    private var watcher: DiskWatcher?
    private var job: WriteJob?

    var isWriting: Bool { if case .running = phase { return true } else { return false } }
    var chosenDisk: DiskDescription? { offered.first { $0.bsdName == diskName } }

    /// The list: ours on GitHub. For testing before it's published, `--list FILE-or-URL` or SOFA_BOX_IMAGER_LIST.
    nonisolated static func chosenListURL() -> URL {
        let args = CommandLine.arguments
        var given = ProcessInfo.processInfo.environment["SOFA_BOX_IMAGER_LIST"]
        if let i = args.firstIndex(of: "--list"), i + 1 < args.count { given = args[i + 1] }
        guard let g = given, !g.isEmpty else { return CardListSource.defaultURL }
        let url = g.contains("://") ? URL(string: g) : URL(fileURLWithPath: (g as NSString).expandingTildeInPath)
        return url ?? CardListSource.defaultURL
    }

    /// The list's bytes: a file on this Mac, or over HTTPS.
    nonisolated static func fetchList(_ url: URL) async throws -> Data {
        if url.isFileURL { return try Data(contentsOf: url) }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30)
        req.setValue("SofaBoxImager/\(version)", forHTTPHeaderField: "User-Agent")
        let (data, resp) = try await URLSession.shared.data(for: req)
        if let code = (resp as? HTTPURLResponse)?.statusCode, code != 200 { throw DownloadError.http(code) }
        return data
    }

    init(live: Bool = true) {
        self.live = live
        listURL = Self.chosenListURL()
        listIsLocal = listURL.isFileURL
        guard live else { return }
        watcher = DiskWatcher { [weak self] in self?.refreshDisks() }
        loadList()
    }

    func loadList() {
        list = .loading
        let url = listURL
        let local = listIsLocal
        Task {
            do {
                let data = try await Self.fetchList(url)
                let parsed = try CardListParser.parse(data, allowLocalFiles: local)
                for s in parsed.skipped { NSLog("Sofa Box Imager: left out of the list: %@", s) }
                list = .loaded(parsed)
                if card == nil || !parsed.all.contains(where: { $0 == card }) { card = parsed.newest ?? parsed.all.first }
            } catch let e as CardListError {
                list = .failed(e.description)
            } catch let e as DownloadError {
                list = .failed("Couldn't get the list of Sofa Box OS versions: \(e.description)")
            } catch {
                list = .failed("Couldn't get the list of Sofa Box OS versions: \(error.localizedDescription)")
            }
        }
    }

    func refreshDisks() {
        guard live else { return }
        // Before the list is in, any card shows (nothing can be written without a version anyway).
        let needs = card?.extractSize ?? 1
        Task.detached(priority: .userInitiated) {
            let sorted = DiskList.snapshot().sorted(needs: needs)
            await MainActor.run {
                self.offered = sorted.offered
                self.refused = sorted.refused.filter { !Self.isQuietlySkipped($0.0, $0.1) }
                if let name = self.diskName, !sorted.offered.contains(where: { $0.bsdName == name }) {
                    self.diskName = nil
                }
                if self.diskName == nil, sorted.offered.count == 1 { self.diskName = sorted.offered[0].bsdName }
            }
        }
    }

    /// APFS containers and the like are parts of other disks: listing them under "not shown" only confuses.
    nonisolated static func isQuietlySkipped(_ d: DiskDescription, _ why: [DiskRefusal]) -> Bool {
        why.contains(.notPhysical) && !why.contains(.diskImage)
    }

    func askToWrite() {
        guard card != nil, chosenDisk != nil, !isWriting else { return }
        confirming = true
    }

    func write() {
        confirming = false
        guard let card, let disk = chosenDisk, !isWriting else { return }
        let ua = "SofaBoxImager/\(Self.version)"
        let job = WriteJob(card: card, disk: disk) {
            if card.url.isFileURL { return try FileSource(url: card.url) as PackedSource }
            return HTTPSource(url: card.url, expectedSize: card.downloadSize, userAgent: ua)
        }
        self.job = job
        jobTitle = "Writing \(card.name) to “\(disk.displayName)” (\(ByteSize.text(disk.sizeBytes)))"
        phase = .running("Checking the card…", nil)
        let reporter = StageReporter { [weak self] text, fraction in
            // A late update never turns a finished write back into a running one.
            guard let self, self.isWriting else { return }
            self.phase = .running(text, fraction)
        }
        let cardName = card.name
        let diskTitle = disk.displayName
        Thread.detachNewThread {
            do {
                try job.run { reporter.report($0) }
                Task { @MainActor in
                    self.phase = .done(card: cardName, disk: diskTitle)
                    self.job = nil
                    self.diskName = nil
                    self.refreshDisks()
                }
            } catch {
                let text = plainWords(error)
                Task { @MainActor in
                    self.phase = .failed(text)
                    self.job = nil
                    self.refreshDisks()
                }
            }
        }
    }

    func cancel() {
        job?.cancel()
        if case .running = phase { phase = .running("Stopping…", nil) }
    }

    func reset() {
        phase = .choosing
        refreshDisks()
    }
}

/// Turns the job's stages into words, at most ten times a second, on the main queue.
final class StageReporter: @unchecked Sendable {     // used from the job's one thread
    private let publish: @MainActor (String, Double?) -> Void
    private var last = Date.distantPast
    private var lastPhase: WriteProgress.Phase?
    private var speedFrom: (Date, Int64)?

    init(_ publish: @escaping @MainActor (String, Double?) -> Void) { self.publish = publish }

    func report(_ stage: WriteJob.Stage) {
        let text: String
        var fraction: Double? = nil
        switch stage {
        case .checking: text = "Checking the card…"
        case .unmounting: text = "Unmounting the card's volumes…"
        case .waitingForPassword: text = "Waiting for your password…"
        case .ejecting: text = "Ejecting the card…"
        case .done: text = "Done."
        case .writing(let p):
            let now = Date()
            let changed = p.phase != lastPhase
            if changed { speedFrom = (now, p.done); lastPhase = p.phase }
            guard changed || now.timeIntervalSince(last) >= 0.1 || p.done == p.total else { return }
            fraction = p.fraction
            var speed = ""
            if let (t0, b0) = speedFrom, now.timeIntervalSince(t0) > 2 {
                let rate = Double(p.done - b0) / now.timeIntervalSince(t0)
                speed = " · \(ByteSize.text(Int64(rate)))/s"
            }
            let pct = Int(p.fraction * 100)
            switch p.phase {
            case .writing: text = "Downloading and writing… \(pct)%\(speed)"
            case .finishing: text = "Finishing the write…"
            case .verifying: text = "Checking every byte on the card… \(pct)%\(speed)"
            }
        }
        last = Date()
        let f = fraction
        let publish = self.publish
        Task { @MainActor in publish(text, f) }
    }
}
