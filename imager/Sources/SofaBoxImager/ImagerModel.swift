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
    /// For a Raspberry Pi (an SD card) or a PC (a USB stick): the list is read again for it.
    @Published var target: CardTarget = ImagerModel.chosenTarget() { didSet { if target != oldValue { readList() } } }
    @Published var card: Card? { didSet { refreshDisks() } }
    @Published var offered: [DiskDescription] = []
    /// On a DVD: the Mac's burners, and the one chosen.
    @Published var burners: [Burner] = []
    @Published var burnerID: String?
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
    private var burnJob: BurnJob?
    private var burnerTimer: Timer?
    /// The list as it came, read again for the other target without fetching it again.
    private var listData: Data?

    var isWriting: Bool { if case .running = phase { return true } else { return false } }
    var chosenDisk: DiskDescription? { offered.first { $0.bsdName == diskName } }
    /// The burner chosen, while it has a blank DVD big enough in it.
    var chosenBurner: Burner? {
        burners.first { $0.id == burnerID && $0.refusal(needs: card?.extractSize ?? 1) == nil }
    }
    /// A version and somewhere to put it.
    var canGo: Bool { card != nil && (target.burns ? chosenBurner != nil : chosenDisk != nil) }

    /// The list: ours on GitHub. For testing another one, `--list FILE-or-URL` or SOFA_BOX_IMAGER_LIST.
    nonisolated static func chosenListURL() -> URL {
        let args = CommandLine.arguments
        var given = ProcessInfo.processInfo.environment["SOFA_BOX_IMAGER_LIST"]
        if let i = args.firstIndex(of: "--list"), i + 1 < args.count { given = args[i + 1] }
        guard let g = given, !g.isEmpty else { return CardListSource.defaultURL }
        let url = g.contains("://") ? URL(string: g) : URL(fileURLWithPath: (g as NSString).expandingTildeInPath)
        return url ?? CardListSource.defaultURL
    }

    /// `--for pc` (or `--for pi`) on the command line: what the window opens on. A Raspberry Pi otherwise.
    nonisolated static func chosenTarget() -> CardTarget {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--for"), i + 1 < args.count, let t = CardTarget.named(args[i + 1]) { return t }
        return .raspberryPi
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
        // A disc going in or out of a burner: looked for every few seconds while On a DVD is chosen
        burnerTimer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.target.burns, self.phase == .choosing else { return }
                self.refreshBurners()
            }
        }
        loadList()
    }

    func loadList() {
        list = .loading
        let url = listURL
        let local = listIsLocal
        Task {
            do {
                listData = try await Self.fetchList(url)
                readList()
            } catch let e as DownloadError {
                list = .failed("Couldn't get the list of Sofa Box OS versions: \(e.description)")
            } catch {
                list = .failed("Couldn't get the list of Sofa Box OS versions: \(error.localizedDescription)")
            }
        }
    }

    /// The list read for the target chosen: its entries, and the version offered.
    func readList() {
        guard let data = listData else { return }
        do {
            let parsed = try CardListParser.parse(data, for: target, allowLocalFiles: listIsLocal)
            for s in parsed.skipped { NSLog("Sofa Box Imager: left out of the list: %@", s) }
            list = .loaded(parsed)
            if card == nil || !parsed.all.contains(where: { $0 == card }) { card = parsed.newest ?? parsed.all.first }
        } catch let e as CardListError {
            list = .failed(e.description)
            card = nil
        } catch {
            list = .failed("Couldn't read the list of Sofa Box OS versions: \(error.localizedDescription)")
            card = nil
        }
    }

    /// For the tests that draw the window: a list given as it would come, read for the target chosen.
    func use(listData data: Data) {
        listData = data
        readList()
    }

    func refreshDisks() {
        guard live else { return }
        if target.burns { return refreshBurners() }
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

    /// The burners and their discs (DiscRecording), and the one to offer: the only one that can burn, when there is one.
    func refreshBurners() {
        guard live else { return }
        let found = BurnerList.snapshot()
        let needs = card?.extractSize ?? 1
        if found != burners { burners = found }
        if let id = burnerID, !found.contains(where: { $0.id == id && $0.refusal(needs: needs) == nil }) { burnerID = nil }
        let ready = found.filter { $0.refusal(needs: needs) == nil }
        if burnerID == nil, ready.count == 1 { burnerID = ready[0].id }
    }

    func askToWrite() {
        guard canGo, !isWriting else { return }
        confirming = true
    }

    func write() {
        if target.burns { return burn() }
        confirming = false
        guard let card, let disk = chosenDisk, !isWriting else { return }
        let ua = "SofaBoxImager/\(Self.version)"
        let job = WriteJob(card: card, disk: disk,
                           opener: AuthOpener(prompt: "Sofa Box Imager needs your password to write the \(target.word).")) {
            if card.url.isFileURL { return try FileSource(url: card.url) as PackedSource }
            return HTTPSource(url: card.url, expectedSize: card.downloadSize, userAgent: ua)
        }
        self.job = job
        jobTitle = "Writing \(card.name) to “\(disk.displayName)” (\(ByteSize.text(disk.sizeBytes)))"
        phase = .running("Checking the \(target.word)…", nil)
        let reporter = StageReporter(word: target.word) { [weak self] text, fraction in
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

    /// On a DVD: download, check, burn, and check the disc (BurnJob, with macOS's hdiutil). No password: nothing is erased.
    func burn() {
        confirming = false
        guard let card, let burner = chosenBurner, !isWriting else { return }
        let ua = "SofaBoxImager/\(Self.version)"
        let job = BurnJob(card: card, burner: burner) {
            if card.url.isFileURL { return try FileSource(url: card.url) as PackedSource }
            return HTTPSource(url: card.url, expectedSize: card.downloadSize, userAgent: ua)
        }
        burnJob = job
        jobTitle = "Burning \(card.name) to the DVD in “\(burner.name)”"
        phase = .running("Checking the burner and the disc…", nil)
        let reporter = BurnReporter { [weak self] text, fraction in
            guard let self, self.isWriting else { return }
            self.phase = .running(text, fraction)
        }
        let cardName = card.name
        let burnerName = burner.name
        Thread.detachNewThread {
            do {
                try job.run { reporter.report($0) }
                Task { @MainActor in
                    self.phase = .done(card: cardName, disk: burnerName)
                    self.burnJob = nil
                    self.refreshDisks()
                }
            } catch {
                let text = plainWords(error)
                Task { @MainActor in
                    self.phase = .failed(text)
                    self.burnJob = nil
                    self.refreshDisks()
                }
            }
        }
    }

    func cancel() {
        job?.cancel()
        burnJob?.cancel()
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
    /// "card" or "stick" (CardTarget.word), in the words shown.
    private let word: String
    private var last = Date.distantPast
    private var lastPhase: WriteProgress.Phase?
    private var speedFrom: (Date, Int64)?

    init(word: String = "card", _ publish: @escaping @MainActor (String, Double?) -> Void) {
        self.word = word
        self.publish = publish
    }

    func report(_ stage: WriteJob.Stage) {
        let text: String
        var fraction: Double? = nil
        switch stage {
        case .checking: text = "Checking the \(word)…"
        case .unmounting: text = "Unmounting the \(word)'s volumes…"
        case .waitingForPassword: text = "Waiting for your password…"
        case .ejecting: text = "Ejecting the \(word)…"
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
            case .verifying: text = "Checking every byte on the \(word)… \(pct)%\(speed)"
            }
        }
        last = Date()
        let f = fraction
        let publish = self.publish
        Task { @MainActor in publish(text, f) }
    }
}

/// A DVD's stages in words, at most ten times a second, on the main queue.
final class BurnReporter: @unchecked Sendable {     // used from the job's one thread
    private let publish: @MainActor (String, Double?) -> Void
    private var last = Date.distantPast
    private var lastKind = ""
    private var speedFrom: (Date, Int64)?

    init(_ publish: @escaping @MainActor (String, Double?) -> Void) {
        self.publish = publish
    }

    func report(_ stage: BurnJob.Stage) {
        let text: String
        var fraction: Double? = nil
        let now = Date()
        let kind: String
        switch stage {
        case .downloading: kind = "downloading"
        case .burning: kind = "burning"
        case .verifying: kind = "verifying"
        default: kind = "\(stage)"
        }
        // a new stage is always said; the same one at most ten times a second
        let soon = kind == lastKind && now.timeIntervalSince(last) < 0.1
        switch stage {
        case .checking: text = "Checking the burner and the disc…"
        case .checkingDownload: text = "Checking the download…"
        case .done: text = "Done."
        case .downloading(let done, let total):
            guard !soon || done == total else { return }
            if speedFrom == nil { speedFrom = (now, done) }
            fraction = total > 0 ? Double(done) / Double(total) : nil
            var speed = ""
            if let (t0, b0) = speedFrom, now.timeIntervalSince(t0) > 2 {
                speed = " · \(ByteSize.text(Int64(Double(done - b0) / now.timeIntervalSince(t0))))/s"
            }
            text = "Downloading… \(Int((fraction ?? 0) * 100))%\(speed)"
        case .burning(let f):
            guard !soon else { return }
            fraction = f
            text = f.map { "Burning… \(Int($0 * 100))%" } ?? "Burning…"
        case .verifying(let f):
            guard !soon || f == nil else { return }
            fraction = f
            text = f.map { "Checking the disc… \(Int($0 * 100))%" } ?? "Checking the disc…"
        }
        last = now
        lastKind = kind
        let f = fraction
        let publish = self.publish
        Task { @MainActor in publish(text, f) }
    }
}
