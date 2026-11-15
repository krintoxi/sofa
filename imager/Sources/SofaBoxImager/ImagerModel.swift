import AppKit
import Foundation
import ImagerKit
import ImagerMac

/// What the window writes: Sofa Box OS (from our list), another Linux (from its project's own site), Windows (from the
/// owner's ISO), or an image file of the owner's own.
enum Mode: String, CaseIterable, Identifiable {
    case sofaBox, linux, windows, file

    var id: String { rawValue }
    var choice: String {
        switch self {
        case .sofaBox: return "Sofa Box OS"
        case .linux: return "Linux"
        case .windows: return "Windows"
        case .file: return "Your own image"
        }
    }
    var symbol: String {
        switch self {
        case .sofaBox: return "sofa"
        case .linux: return "terminal"
        case .windows: return "square.grid.2x2"
        case .file: return "doc"
        }
    }
    static func named(_ text: String) -> Mode? {
        switch text.lowercased() {
        case "linux", "systems": return .linux
        case "windows", "win": return .windows
        case "file", "own", "image": return .file
        default: return nil
        }
    }
}

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

    /// A Linux from the list, found on its project's site.
    enum SystemState: Equatable {
        case none
        case finding
        case found(Card)
        case failed(String)
    }

    /// A file the owner chose (a Windows ISO, or an image of their own), as it was read.
    enum FileState: Equatable {
        case none
        case reading(URL)
        case read(URL, ImageKind, Int64)
        case failed(URL, String)

        var url: URL? {
            switch self {
            case .none: return nil
            case .reading(let u), .read(let u, _, _), .failed(let u, _): return u
            }
        }
    }

    nonisolated static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"

    /// Microsoft's own download pages: the Imager never downloads or keeps Windows.
    static let windows11Page = URL(string: "https://www.microsoft.com/software-download/windows11")!
    static let windows10Page = URL(string: "https://www.microsoft.com/software-download/windows10ISO")!

    @Published var mode: Mode = ImagerModel.chosenMode() { didSet { if mode != oldValue { modeChanged() } } }
    @Published var list: ListState = .loading
    /// For a Raspberry Pi (an SD card) or a PC (a USB stick): the list is read again for it.
    @Published var target: CardTarget = ImagerModel.chosenTarget() { didSet { if target != oldValue { readList() } } }
    @Published var card: Card? { didSet { refreshDisks() } }
    /// Linux: the entry chosen, and what was found for it.
    @Published var systemID: String = Catalog.entries[0].id { didSet { if systemID != oldValue { findSystem() } } }
    @Published var system: SystemState = .none { didSet { refreshDisks() } }
    /// Windows: the ISO, and the Windows 11 switches (each off unless ticked).
    @Published var windowsFile: FileState = .none { didSet { refreshDisks() } }
    @Published var skipHardwareChecks = false
    @Published var useLocalAccount = false
    @Published var accountName = ""
    /// Your own image.
    @Published var ownFile: FileState = .none { didSet { refreshDisks() } }
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
    /// Linux entries already found since the app opened.
    private var found: [String: Card] = [:]

    var isWriting: Bool { if case .running = phase { return true } else { return false } }
    var chosenDisk: DiskDescription? { offered.first { $0.bsdName == diskName } }
    /// The burner chosen, while it has a blank DVD big enough in it.
    var chosenBurner: Burner? {
        burners.first { $0.id == burnerID && $0.refusal(needs: card?.extractSize ?? 1) == nil }
    }
    var burns: Bool { mode == .sofaBox && target.burns }

    /// The Linux entry chosen.
    var systemEntry: CatalogEntry { Catalog.entry(systemID) ?? Catalog.entries[0] }
    var foundSystem: Card? {
        if case .found(let c) = system, found[systemID] == c { return c } else { return nil }
    }
    var windowsMedia: WindowsMedia? {
        if case .read(_, .windows(let w), _) = windowsFile { return w } else { return nil }
    }
    var ownKind: (URL, ImageKind, Int64)? {
        if case .read(let u, let k, let n) = ownFile, k.writtenWhole { return (u, k, n) } else { return nil }
    }

    /// The Windows 11 switches as ticked.
    var windowsOptions: WindowsOptions {
        guard windowsMedia?.version == .eleven else { return WindowsOptions() }
        return WindowsOptions(skipHardwareChecks: skipHardwareChecks,
                              localAccount: useLocalAccount ? accountName.trimmingCharacters(in: .whitespaces) : nil)
    }

    /// Why the Windows switches can't be used as ticked; nil when they can.
    var optionsProblem: String? {
        guard windowsMedia?.version == .eleven, useLocalAccount else { return nil }
        return WindowsOptions.accountNameProblem(accountName)
    }

    /// The one word for what's written to: "card", "stick", "disc"; "disk" for an image of the owner's own.
    var word: String {
        switch mode {
        case .sofaBox: return target.word
        case .linux: return systemEntry.medium == .sdCard ? "card" : "stick"
        case .windows: return "stick"
        case .file: return "disk"
        }
    }
    var symbol: String {
        switch mode {
        case .sofaBox: return target.symbol
        case .linux: return systemEntry.medium == .sdCard ? "sdcard" : "externaldrive"
        case .windows: return "externaldrive"
        case .file: return "externaldrive"
        }
    }

    /// What's written, in words, and how many bytes the disk must hold.
    var item: (name: String, needs: Int64)? {
        switch mode {
        case .sofaBox: return card.map { ($0.name, $0.extractSize) }
        case .linux: return foundSystem.map { ($0.name, $0.extractSize) }
        case .windows: return windowsMedia.flatMap { $0.refusal == nil ? ($0.title, $0.stickBytesNeeded) : nil }
        case .file: return ownKind.map { ($0.0.lastPathComponent, $0.2) }
        }
    }

    /// A version and somewhere to put it.
    var canGo: Bool {
        if burns { return card != nil && chosenBurner != nil }
        return item != nil && chosenDisk != nil && optionsProblem == nil
    }

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

    /// `--for linux`, `--for windows` or `--for file`: the window opens on that. Sofa Box OS otherwise.
    nonisolated static func chosenMode() -> Mode {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--for"), i + 1 < args.count, let m = Mode.named(args[i + 1]) { return m }
        return .sofaBox
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
                guard let self, self.burns, self.phase == .choosing else { return }
                self.refreshBurners()
            }
        }
        loadList()
        if mode == .linux { findSystem() }
    }

    private func modeChanged() {
        diskName = nil
        if mode == .linux, case .none = system { findSystem() }
        refreshDisks()
    }

    func loadList() {
        list = .loading
        let url = listURL
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

    /// Linux: the entry's newest release, its address and its SHA-256, from its project's own site.
    func findSystem() {
        let entry = systemEntry
        if let c = found[entry.id] { system = .found(c); return }
        // Never the last entry's card under this one's name.
        system = .finding
        guard live else { return }
        let ua = "SofaBoxImager/\(Self.version)"
        Task {
            do {
                let c = try await CatalogResolver.resolve(entry, with: URLSessionFetcher(userAgent: ua))
                found[entry.id] = c
                if systemID == entry.id { system = .found(c) }
            } catch {
                if systemID == entry.id { system = .failed(plainWords(error)) }
            }
        }
    }

    /// For the tests: a Linux entry as it would be found.
    func use(system c: Card, for id: String) {
        found[id] = c
        if systemID == id { system = .found(c) } else { systemID = id }
    }

    /// Windows and your own image: the file read (its first sectors, and a Windows ISO's folders and install image).
    func open(_ url: URL, forWindows: Bool) {
        let state = FileState.reading(url)
        if forWindows { windowsFile = state } else { ownFile = state }
        Task.detached(priority: .userInitiated) {
            let result: FileState
            do {
                let f = try FileRandomAccess(url: url)
                let kind = try ImageInspector.inspect(f, name: url.lastPathComponent)
                var bytes = f.size
                if case .packedImage(let n) = kind { bytes = n }
                result = .read(url, kind, bytes)
            } catch {
                result = .failed(url, plainWords(error))
            }
            await MainActor.run {
                if forWindows {
                    if self.windowsFile.url == url { self.windowsFile = result }
                } else if self.ownFile.url == url {
                    self.ownFile = result
                }
            }
        }
    }

    func chooseFile(forWindows: Bool) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.message = forWindows ? "Choose a Windows ISO (Windows 7, 8.1, 10 or 11)"
            : "Choose a disk image: an .iso, an .img, or an .img.xz"
        panel.prompt = "Choose"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        open(url, forWindows: forWindows)
    }

    func refreshDisks() {
        guard live else { return }
        if burns { return refreshBurners() }
        // Before anything is chosen, any disk shows (nothing can be written without it anyway).
        let needs = item?.needs ?? 1
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

    /// The job for what's chosen, onto `disk`.
    func makeJob(for disk: DiskDescription) -> WriteJob? {
        let ua = "SofaBoxImager/\(Self.version)"
        let opener = AuthOpener(prompt: "Sofa Box Imager needs your password to write the \(word).")
        func download(_ c: Card) -> () throws -> PackedSource {
            {
                if c.url.isFileURL { return try FileSource(url: c.url) as PackedSource }
                return HTTPSource(url: c.url, expectedSize: c.downloadSize, userAgent: ua)
            }
        }
        switch mode {
        case .sofaBox:
            guard let c = card else { return nil }
            return WriteJob(card: c, disk: disk, opener: opener, source: download(c))
        case .linux:
            guard let c = foundSystem else { return nil }
            return WriteJob(card: c, disk: disk, opener: opener, source: download(c))
        case .windows:
            guard let w = windowsMedia, let url = windowsFile.url else { return nil }
            return .windows(iso: url, media: w, options: windowsOptions, disk: disk, opener: opener)
        case .file:
            guard let (url, kind, bytes) = ownKind else { return nil }
            return .image(url, kind: kind, bytes: bytes, disk: disk, opener: opener)
        }
    }

    func write() {
        if burns { return burn() }
        confirming = false
        guard let disk = chosenDisk, let what = item, !isWriting, let job = makeJob(for: disk) else { return }
        self.job = job
        jobTitle = "Writing \(what.name) to “\(disk.displayName)” (\(ByteSize.text(disk.sizeBytes)))"
        phase = .running("Checking the \(word)…", nil)
        let downloads = mode == .sofaBox || mode == .linux
        let reporter = StageReporter(word: word, downloads: downloads, building: mode == .windows) { [weak self] text, fraction in
            // A late update never turns a finished write back into a running one.
            guard let self, self.isWriting else { return }
            self.phase = .running(text, fraction)
        }
        let name = what.name
        let diskTitle = disk.displayName
        Thread.detachNewThread {
            do {
                try job.run { reporter.report($0) }
                Task { @MainActor in
                    self.phase = .done(card: name, disk: diskTitle)
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
    /// Downloaded as it's written (a card, a Linux ISO), or read from this Mac (Windows, your own image).
    private let downloads: Bool
    /// A Windows stick: laid out first, from the ISO.
    private let building: Bool
    private var last = Date.distantPast
    private var lastPhase: WriteProgress.Phase?
    private var speedFrom: (Date, Int64)?

    init(word: String = "card", downloads: Bool = true, building: Bool = false,
         _ publish: @escaping @MainActor (String, Double?) -> Void) {
        self.word = word
        self.downloads = downloads
        self.building = building
        self.publish = publish
    }

    func report(_ stage: WriteJob.Stage) {
        let text: String
        var fraction: Double? = nil
        switch stage {
        case .checking: text = "Checking the \(word)…"
        case .preparing: text = building ? "Laying out the stick from the ISO…" : "Getting ready…"
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
            case .writing: text = "\(downloads ? "Downloading and writing" : "Writing")… \(pct)%\(speed)"
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
