import Foundation
#if canImport(CryptoKit)
import CryptoKit
#endif

/// SHA-256 (FIPS 180-4), written here so that Sofa Box Imager needs nothing from the system to check a disk on Windows
/// and Linux. The same calls as CryptoKit's `SHA256`: `update(bufferPointer:)`, `update(data:)`, `finalize()`.
public struct SHA256Hasher {
    private var h0: UInt32 = 0x6a09_e667, h1: UInt32 = 0xbb67_ae85, h2: UInt32 = 0x3c6e_f372, h3: UInt32 = 0xa54f_f53a
    private var h4: UInt32 = 0x510e_527f, h5: UInt32 = 0x9b05_688c, h6: UInt32 = 0x1f83_d9ab, h7: UInt32 = 0x5be0_cd19
    /// Fewer than 64 bytes, waiting for the rest of their block.
    private var tail: [UInt8] = []
    private var length: UInt64 = 0

    public init() { tail.reserveCapacity(64) }

    public mutating func update(bufferPointer bytes: UnsafeRawBufferPointer) {
        guard var p = bytes.baseAddress, bytes.count > 0 else { return }
        var n = bytes.count
        length &+= UInt64(n)
        if !tail.isEmpty {
            let take = min(64 - tail.count, n)
            tail.append(contentsOf: UnsafeRawBufferPointer(start: p, count: take))
            p += take
            n -= take
            if tail.count == 64 {
                var s = state
                tail.withUnsafeBytes { SHA256Hasher.compress(&s, $0.baseAddress!, blocks: 1) }
                state = s
                tail.removeAll(keepingCapacity: true)
            }
        }
        let whole = n / 64
        if whole > 0 {
            var s = state
            SHA256Hasher.compress(&s, p, blocks: whole)
            state = s
            p += whole * 64
            n -= whole * 64
        }
        if n > 0 { tail.append(contentsOf: UnsafeRawBufferPointer(start: p, count: n)) }
    }

    public mutating func update(data: Data) {
        data.withUnsafeBytes { update(bufferPointer: $0) }
    }

    /// The 32-byte digest. The hasher itself is left as it was.
    public func finalize() -> [UInt8] {
        var copy = self
        let bits = length &* 8
        let used = Int(length % 64)
        var pad = [UInt8](repeating: 0, count: (used < 56 ? 56 : 120) - used + 8)
        pad[0] = 0x80
        for i in 0..<8 { pad[pad.count - 1 - i] = UInt8(truncatingIfNeeded: bits >> (UInt64(i) * 8)) }
        pad.withUnsafeBytes { copy.update(bufferPointer: $0) }
        let s = copy.state
        var out = [UInt8]()
        out.reserveCapacity(32)
        for word in [s.0, s.1, s.2, s.3, s.4, s.5, s.6, s.7] {
            out.append(UInt8(word >> 24)); out.append(UInt8(truncatingIfNeeded: word >> 16))
            out.append(UInt8(truncatingIfNeeded: word >> 8)); out.append(UInt8(truncatingIfNeeded: word))
        }
        return out
    }

    public static func hex(_ data: Data) -> String {
        var h = SHA256Hasher()
        h.update(data: data)
        return SHA256Hasher.hex(h.finalize())
    }

    static func hex<S: Sequence>(_ digest: S) -> String where S.Element == UInt8 {
        let digits = Array("0123456789abcdef".utf8)
        var s = [UInt8]()
        for b in digest { s.append(digits[Int(b >> 4)]); s.append(digits[Int(b & 15)]) }
        return String(decoding: s, as: UTF8.self)
    }

    private typealias State = (UInt32, UInt32, UInt32, UInt32, UInt32, UInt32, UInt32, UInt32)

    private var state: State {
        get { (h0, h1, h2, h3, h4, h5, h6, h7) }
        set { (h0, h1, h2, h3, h4, h5, h6, h7) = newValue }
    }

    @inline(__always) private static func rotr(_ x: UInt32, _ n: UInt32) -> UInt32 { (x >> n) | (x << (32 &- n)) }

    private static func compress(_ s: inout State, _ data: UnsafeRawPointer, blocks: Int) {
        withUnsafeTemporaryAllocation(of: UInt32.self, capacity: 64) { w in
            sha256K.withUnsafeBufferPointer { k in
                var (h0, h1, h2, h3, h4, h5, h6, h7) = s
                var p = data
                for _ in 0..<blocks {
                    for i in 0..<16 { w[i] = UInt32(bigEndian: p.loadUnaligned(fromByteOffset: i * 4, as: UInt32.self)) }
                    for i in 16..<64 {
                        let a = w[i - 15], b = w[i - 2]
                        let s0 = rotr(a, 7) ^ rotr(a, 18) ^ (a >> 3)
                        let s1 = rotr(b, 17) ^ rotr(b, 19) ^ (b >> 10)
                        w[i] = w[i - 16] &+ s0 &+ w[i - 7] &+ s1
                    }
                    var a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7
                    for i in 0..<64 {
                        let t1 = h &+ (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) &+ ((e & f) ^ (~e & g)) &+ k[i] &+ w[i]
                        let t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) &+ ((a & b) ^ (a & c) ^ (b & c))
                        h = g; g = f; f = e; e = d &+ t1
                        d = c; c = b; b = a; a = t1 &+ t2
                    }
                    h0 &+= a; h1 &+= b; h2 &+= c; h3 &+= d; h4 &+= e; h5 &+= f; h6 &+= g; h7 &+= h
                    p += 64
                }
                s = (h0, h1, h2, h3, h4, h5, h6, h7)
            }
        }
    }
}

private let sha256K: [UInt32] = [
    0x428a_2f98, 0x7137_4491, 0xb5c0_fbcf, 0xe9b5_dba5, 0x3956_c25b, 0x59f1_11f1, 0x923f_82a4, 0xab1c_5ed5,
    0xd807_aa98, 0x1283_5b01, 0x2431_85be, 0x550c_7dc3, 0x72be_5d74, 0x80de_b1fe, 0x9bdc_06a7, 0xc19b_f174,
    0xe49b_69c1, 0xefbe_4786, 0x0fc1_9dc6, 0x240c_a1cc, 0x2de9_2c6f, 0x4a74_84aa, 0x5cb0_a9dc, 0x76f9_88da,
    0x983e_5152, 0xa831_c66d, 0xb003_27c8, 0xbf59_7fc7, 0xc6e0_0bf3, 0xd5a7_9147, 0x06ca_6351, 0x1429_2967,
    0x27b7_0a85, 0x2e1b_2138, 0x4d2c_6dfc, 0x5338_0d13, 0x650a_7354, 0x766a_0abb, 0x81c2_c92e, 0x9272_2c85,
    0xa2bf_e8a1, 0xa81a_664b, 0xc24b_8b70, 0xc76c_51a3, 0xd192_e819, 0xd699_0624, 0xf40e_3585, 0x106a_a070,
    0x19a4_c116, 0x1e37_6c08, 0x2748_774c, 0x34b0_bcb5, 0x391c_0cb3, 0x4ed8_aa4a, 0x5b9c_ca4f, 0x682e_6ff3,
    0x748f_82ee, 0x78a5_636f, 0x84c8_7814, 0x8cc7_0208, 0x90be_fffa, 0xa450_6ceb, 0xbef9_a3f7, 0xc671_78f2,
]

/// The SHA-256 the writer checks disks with. On the Mac it stays Apple's (CryptoKit), which every card so far has been
/// checked with, until ours has been timed against it on real cards; on Windows and Linux it's ours.
#if canImport(CryptoKit)
typealias WriterSHA256 = CryptoKit.SHA256
#else
typealias WriterSHA256 = SHA256Hasher
#endif
