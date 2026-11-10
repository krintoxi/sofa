import Foundation

/// The packed card, a piece at a time, in order. `next()` blocks until the next piece is in; nil at the end.
public protocol PackedSource: AnyObject {
    func next() throws -> Data?
    func cancel()
}

public enum DownloadError: Error, Equatable, CustomStringConvertible {
    case http(Int)
    case wrongSize(got: Int64, expected: Int64)
    case cannotResume
    case network(String)
    case cancelled

    public var description: String {
        switch self {
        case .http(let code): return "The download failed: the server answered \(code)."
        case .wrongSize(let got, let expected):
            return "The download is \(ByteSize.text(got)), not the \(ByteSize.text(expected)) the list says."
        case .cannotResume: return "The connection dropped and the download couldn't carry on where it stopped."
        case .network(let why): return "The download failed: \(why)"
        case .cancelled: return "Stopped."
        }
    }
}

/// A card already on this Mac (tests, and lists opened from a file).
public final class FileSource: PackedSource {
    private let handle: FileHandle
    private var cancelled = false

    public init(url: URL) throws {
        handle = try FileHandle(forReadingFrom: url)
    }

    deinit { try? handle.close() }

    public func next() throws -> Data? {
        if cancelled { throw DownloadError.cancelled }
        let d = try handle.read(upToCount: CardWriter.blockBytes) ?? Data()
        return d.isEmpty ? nil : d
    }

    public func cancel() { cancelled = true }
}

/// Streams the card over HTTPS while it's being unpacked and written. Holds at most a few megabytes: when the card
/// writes slower than the network, the download pauses until the writer catches up. If the connection drops, it carries
/// on from the byte it stopped at (an HTTP Range request), a few times, and only when the server answers with exactly
/// that range; otherwise it stops rather than guess.
public final class HTTPSource: NSObject, PackedSource, URLSessionDataDelegate {
    public static let highWater = 32 << 20
    public static let lowWater = 8 << 20
    public static let retries = 4

    private let url: URL
    private let expectedSize: Int64?
    private let userAgent: String
    private let retryDelay: Double
    private var session: URLSession!
    private let lock = NSCondition()

    // All under `lock`.
    private var queue: [Data] = []
    private var queued = 0
    private var received: Int64 = 0
    private var task: URLSessionDataTask?
    private var paused = false
    private var done = false
    private var failure: Error?
    private var attempts = 0
    private var cancelled = false
    private var started = false
    private var responseOK = false

    /// - Parameters:
    ///   - expectedSize: the list's `image_download_size`; a download of any other length is refused.
    ///   - configuration: tests pass one with their own URLProtocol.
    ///   - retryDelay: seconds before the first retry; each further one waits twice as long.
    public init(url: URL, expectedSize: Int64?, userAgent: String = "SofaBoxImager",
                configuration: URLSessionConfiguration = .ephemeral, retryDelay: Double = 1) {
        self.url = url
        self.expectedSize = expectedSize
        self.userAgent = userAgent
        self.retryDelay = retryDelay
        super.init()
        let config = configuration
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.urlCache = nil
        config.timeoutIntervalForRequest = 60
        let delegateQueue = OperationQueue()
        delegateQueue.maxConcurrentOperationCount = 1
        session = URLSession(configuration: config, delegate: self, delegateQueue: delegateQueue)
    }

    private func startTask() {                                     // with `lock` held
        var req = URLRequest(url: url)
        req.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        req.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        if received > 0 { req.setValue("bytes=\(received)-", forHTTPHeaderField: "Range") }
        responseOK = false
        paused = false
        let t = session.dataTask(with: req)
        task = t
        t.resume()
    }

    public func next() throws -> Data? {
        lock.lock()
        defer { lock.unlock() }
        if !started {
            started = true
            startTask()
        }
        while queue.isEmpty && !done && failure == nil && !cancelled { lock.wait() }
        if cancelled { throw DownloadError.cancelled }
        if !queue.isEmpty {
            let d = queue.removeFirst()
            queued -= d.count
            if paused && queued <= HTTPSource.lowWater {
                paused = false
                task?.resume()
            }
            return d
        }
        if let f = failure { throw f }
        return nil
    }

    public func cancel() {
        lock.lock()
        cancelled = true
        task?.cancel()
        lock.broadcast()
        lock.unlock()
        session.invalidateAndCancel()
    }

    /// How many times the download has carried on after a drop.
    public var resumes: Int {
        lock.lock()
        defer { lock.unlock() }
        return attempts
    }

    /// Tests: drops the connection as a network failure would (the download then carries on by itself).
    func dropConnection() {
        lock.lock()
        task?.cancel()
        lock.unlock()
    }

    private func fail(_ e: Error) {                                 // with `lock` held
        if failure == nil { failure = e }
        task?.cancel()
        lock.broadcast()
    }

    // MARK: URLSessionDataDelegate

    public func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                           completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        lock.lock()
        defer { lock.unlock() }
        guard dataTask === task, !cancelled else { completionHandler(.cancel); return }
        let http = response as? HTTPURLResponse
        let code = http?.statusCode ?? 200          // file:// and the like have no status
        var total: Int64? = nil
        if received == 0 {
            guard code == 200 else { fail(DownloadError.http(code)); completionHandler(.cancel); return }
            if response.expectedContentLength >= 0 { total = response.expectedContentLength }
        } else {
            // Carrying on: only exactly the range asked for will do.
            guard code == 206, let range = http?.value(forHTTPHeaderField: "Content-Range"),
                  let m = range.range(of: #"^bytes (\d+)-(\d+)/(\d+)$"#, options: .regularExpression) else {
                fail(DownloadError.cannotResume); completionHandler(.cancel); return
            }
            let parts = range[m].dropFirst("bytes ".count).split(whereSeparator: { $0 == "-" || $0 == "/" })
                .compactMap { Int64($0) }
            guard parts.count == 3, parts[0] == received else {
                fail(DownloadError.cannotResume); completionHandler(.cancel); return
            }
            total = parts[2]
        }
        if let t = total, let e = expectedSize, t != e {
            fail(DownloadError.wrongSize(got: t, expected: e)); completionHandler(.cancel); return
        }
        responseOK = true
        completionHandler(.allow)
    }

    public func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock()
        defer { lock.unlock() }
        guard dataTask === task, responseOK, !cancelled, failure == nil else { return }
        received += Int64(data.count)
        if let e = expectedSize, received > e {
            fail(DownloadError.wrongSize(got: received, expected: e))
            return
        }
        queue.append(data)
        queued += data.count
        if !paused && queued >= HTTPSource.highWater {
            paused = true
            dataTask.suspend()
        }
        lock.broadcast()
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock()
        defer { lock.unlock() }
        guard task === self.task, !cancelled, failure == nil else { return }
        if error == nil && responseOK {
            if let e = expectedSize, received != e {
                fail(DownloadError.wrongSize(got: received, expected: e))
            } else {
                done = true
                lock.broadcast()
            }
            return
        }
        // Dropped: carry on from where it stopped, a few times, waiting a little longer each time.
        attempts += 1
        guard attempts <= HTTPSource.retries else {
            fail(DownloadError.network(error?.localizedDescription ?? "the connection dropped"))
            return
        }
        let wait = retryDelay * Double(1 << (attempts - 1))
        DispatchQueue.global().asyncAfter(deadline: .now() + wait) { [weak self] in
            guard let self else { return }
            self.lock.lock()
            if !self.cancelled && self.failure == nil { self.startTask() }
            self.lock.unlock()
        }
    }
}
