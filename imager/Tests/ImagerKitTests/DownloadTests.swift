import Foundation
@testable import ImagerKit
import XCTest

/// A web server in the test: answers each request from `script`, recording what was asked.
final class ScriptedServer: URLProtocol {
    struct Reply {
        var status: Int
        var headers: [String: String] = [:]
        var body: Data
        /// Drop the connection after this many bytes of the body.
        var dropAfter: Int?
    }

    private static let lock = NSLock()
    private static var _script: ((URLRequest, Int) -> Reply)?
    private static var _requests: [URLRequest] = []

    static func serve(_ script: @escaping (URLRequest, Int) -> Reply) {
        lock.lock(); defer { lock.unlock() }
        _script = script
        _requests = []
    }

    static var requests: [URLRequest] {
        lock.lock(); defer { lock.unlock() }
        return _requests
    }

    static var configuration: URLSessionConfiguration {
        let c = URLSessionConfiguration.ephemeral
        c.protocolClasses = [ScriptedServer.self]
        return c
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        Self._requests.append(request)
        let n = Self._requests.count
        let script = Self._script!
        Self.lock.unlock()
        let r = script(request, n)
        let response = HTTPURLResponse(url: request.url!, statusCode: r.status, httpVersion: "HTTP/1.1",
                                       headerFields: r.headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        let body = r.dropAfter.map { r.body.prefix($0) } ?? r.body
        var i = 0
        while i < body.count {
            let end = min(body.count, i + 50_000)
            client?.urlProtocol(self, didLoad: body.subdata(in: body.startIndex + i..<body.startIndex + end))
            i = end
        }
        if r.dropAfter != nil {
            // A moment later, as a real connection would: by then the session has handed the bytes over, so it
            // reports the drop instead of quietly asking again from the start (which it does for a GET that
            // fails before anything arrived).
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.05) {
                self.client?.urlProtocol(self, didFailWithError: URLError(.networkConnectionLost))
            }
        } else {
            client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() {}
}

final class DownloadTests: XCTestCase {
    let url = URL(string: "https://github.com/krintoxi/sofa/releases/download/sofa-box/sofa-box.img.xz")!
    lazy var payload = Fixture.data("multiblock.img.xz")

    private func whole(_ size: Int) -> [String: String] { ["Content-Length": "\(size)"] }

    /// N from "Range: bytes=N-", or nil when the request asks for the whole file.
    private func rangeStart(_ req: URLRequest) -> Int? {
        guard let r = req.value(forHTTPHeaderField: "Range"), r.hasPrefix("bytes="), r.hasSuffix("-") else { return nil }
        return Int(r.dropFirst("bytes=".count).dropLast())
    }

    private func drain(_ s: PackedSource) throws -> Data {
        var out = Data()
        while let d = try s.next() { out.append(d) }
        return out
    }

    private func source(expected: Int64? = nil) -> HTTPSource {
        HTTPSource(url: url, expectedSize: expected ?? Int64(payload.count), configuration: ScriptedServer.configuration,
                   retryDelay: 0.01)
    }

    func testAWholeDownload() throws {
        let p = payload
        ScriptedServer.serve { _, _ in .init(status: 200, headers: self.whole(p.count), body: p) }
        XCTAssertEqual(try drain(source()), p)
        XCTAssertEqual(ScriptedServer.requests.count, 1)
        XCTAssertNil(ScriptedServer.requests[0].value(forHTTPHeaderField: "Range"))
        XCTAssertEqual(ScriptedServer.requests[0].value(forHTTPHeaderField: "User-Agent"), "SofaBoxImager")
    }

    func testCarriesOnWhereTheConnectionDropped() throws {
        let p = payload
        ScriptedServer.serve { req, _ in
            guard let from = self.rangeStart(req) else {
                return .init(status: 200, headers: self.whole(p.count), body: p, dropAfter: 70_000)
            }
            return .init(status: 206, headers: ["Content-Range": "bytes \(from)-\(p.count - 1)/\(p.count)",
                                                "Content-Length": "\(p.count - from)"],
                         body: p.suffix(from: from))
        }
        XCTAssertEqual(try drain(source()), p)
        XCTAssertEqual(ScriptedServer.requests.map { $0.value(forHTTPHeaderField: "Range") }, [nil, "bytes=70000-"])
    }

    func testWontGuessWhenTheServerIgnoresTheRange() throws {
        let p = payload
        ScriptedServer.serve { req, _ in
            .init(status: 200, headers: self.whole(p.count), body: p, dropAfter: self.rangeStart(req) == nil ? 70_000 : nil)
        }
        XCTAssertThrowsError(try drain(source())) { XCTAssertEqual($0 as? DownloadError, .cannotResume) }
    }

    func testWontAcceptTheWrongRange() throws {
        let p = payload
        ScriptedServer.serve { req, _ in
            if self.rangeStart(req) == nil { return .init(status: 200, headers: self.whole(p.count), body: p, dropAfter: 70_000) }
            return .init(status: 206, headers: ["Content-Range": "bytes 0-\(p.count - 1)/\(p.count)"], body: p)
        }
        XCTAssertThrowsError(try drain(source())) { XCTAssertEqual($0 as? DownloadError, .cannotResume) }
    }

    func testGivesUpAfterAFewDrops() throws {
        let p = payload
        // Every answer brings a thousand bytes more and drops.
        ScriptedServer.serve { req, _ in
            let from = self.rangeStart(req) ?? 0
            return .init(status: from == 0 ? 200 : 206,
                         headers: from == 0 ? self.whole(p.count) : ["Content-Range": "bytes \(from)-\(p.count - 1)/\(p.count)"],
                         body: p.suffix(from: from), dropAfter: 1000)
        }
        XCTAssertThrowsError(try drain(source())) {
            guard case .network? = $0 as? DownloadError else { return XCTFail("\($0)") }
        }
        XCTAssertEqual(ScriptedServer.requests.map { self.rangeStart($0) ?? 0 }, [0, 1000, 2000, 3000, 4000])
    }

    func testTheWrongSizeIsRefused() throws {
        let p = payload
        ScriptedServer.serve { _, _ in .init(status: 200, headers: self.whole(p.count), body: p) }
        XCTAssertThrowsError(try drain(source(expected: Int64(p.count) + 1))) {
            XCTAssertEqual($0 as? DownloadError, .wrongSize(got: Int64(p.count), expected: Int64(p.count) + 1))
        }
        // No length given, and more arrives than the list says.
        ScriptedServer.serve { _, _ in .init(status: 200, body: p) }
        XCTAssertThrowsError(try drain(source(expected: 1000))) {
            guard case .wrongSize? = $0 as? DownloadError else { return XCTFail("\($0)") }
        }
    }

    func testHTTPErrors() throws {
        ScriptedServer.serve { _, _ in .init(status: 404, body: Data("Not Found".utf8)) }
        XCTAssertThrowsError(try drain(source())) { XCTAssertEqual($0 as? DownloadError, .http(404)) }
    }

    func testCancel() throws {
        let p = payload
        ScriptedServer.serve { _, _ in .init(status: 200, headers: self.whole(p.count), body: p) }
        let s = source()
        _ = try s.next()
        s.cancel()
        XCTAssertThrowsError(try s.next()) { XCTAssertEqual($0 as? DownloadError, .cancelled) }
    }

    /// The whole pipeline from a download that drops halfway, to a checked card.
    func testDownloadUnpackWriteAndCheck() throws {
        let p = payload
        ScriptedServer.serve { req, _ in
            guard let from = self.rangeStart(req) else {
                return .init(status: 200, headers: self.whole(p.count), body: p, dropAfter: 100_001)
            }
            return .init(status: 206, headers: ["Content-Range": "bytes \(from)-\(p.count - 1)/\(p.count)"],
                         body: p.suffix(from: from))
        }
        let disk = try TempDisk(size: 4 << 20)
        try CardPipeline.run(source: source(), device: FileDescriptorDevice(fd: disk.fd), card: Fixture.card(),
                             diskSize: disk.size, sectorBytes: 512)
        XCTAssertEqual(sha256(disk.contents().prefix(Int(Fixture.cardSize))), Fixture.cardSHA256)
    }
}
