import Compression
import Foundation

public enum XZError: Error, Equatable, CustomStringConvertible {
    case corrupt
    case truncated
    case badPadding
    case cannotStart

    public var description: String {
        switch self {
        case .corrupt: return "The downloaded card is damaged (its xz data doesn't unpack)."
        case .truncated: return "The downloaded card ends early."
        case .badPadding: return "The downloaded card has bytes after its end that shouldn't be there."
        case .cannotStart: return "macOS couldn't start unpacking the card."
        }
    }
}

/// Unpacks an `.xz` file as it streams in, with macOS's own Compression framework (`COMPRESSION_LZMA` is the xz
/// container). Cards are made by `xz -T0`, which cuts the data into many blocks; Compression handles those. An xz file
/// may also hold several streams one after another, with zero padding between them (in multiples of four bytes);
/// Compression stops at the end of the first, so each further stream gets a fresh decoder here. Compression checks
/// each block's check and the stream's index, so a damaged download stops with `.corrupt`.
public final class XZDecoder {
    public static let outputBytes = 1 << 20

    private var stream: UnsafeMutablePointer<compression_stream>?
    private let out: UnsafeMutablePointer<UInt8>
    /// Between streams: counting zero bytes of stream padding.
    private var between = false
    private var padding = 0
    public private(set) var streams = 0
    public private(set) var packedBytes: Int64 = 0
    public private(set) var unpackedBytes: Int64 = 0

    public init() throws {
        out = .allocate(capacity: XZDecoder.outputBytes)
        try startStream()
    }

    deinit {
        if let s = stream {
            compression_stream_destroy(s)
            s.deallocate()
        }
        out.deallocate()
    }

    private func startStream() throws {
        if let s = stream {
            compression_stream_destroy(s)
            s.deallocate()
            stream = nil
        }
        let s = UnsafeMutablePointer<compression_stream>.allocate(capacity: 1)
        guard compression_stream_init(s, COMPRESSION_STREAM_DECODE, COMPRESSION_LZMA) == COMPRESSION_STATUS_OK else {
            s.deallocate()
            throw XZError.cannotStart
        }
        stream = s
        between = false
        padding = 0
    }

    /// Feeds packed bytes; `output` gets the unpacked bytes, in order, up to a megabyte at a time.
    public func feed(_ input: UnsafeRawBufferPointer, output: (UnsafeRawBufferPointer) throws -> Void) throws {
        guard var p = input.baseAddress?.assumingMemoryBound(to: UInt8.self) else { return }
        var left = input.count
        packedBytes += Int64(left)
        while left > 0 {
            if between {
                // Zero padding between streams, then the next stream.
                while left > 0 && p.pointee == 0 {
                    padding += 1
                    p += 1
                    left -= 1
                }
                if left == 0 { return }
                guard padding % 4 == 0 else { throw XZError.badPadding }
                try startStream()
            }
            let s = stream!
            s.pointee.src_ptr = UnsafePointer(p)
            s.pointee.src_size = left
            while true {
                s.pointee.dst_ptr = out
                s.pointee.dst_size = XZDecoder.outputBytes
                let before = s.pointee.src_size
                let status = compression_stream_process(s, 0)
                let made = XZDecoder.outputBytes - s.pointee.dst_size
                // A decoder that neither takes input nor gives output would loop for ever.
                if status == COMPRESSION_STATUS_OK && made == 0 && s.pointee.src_size == before && before > 0 {
                    throw XZError.corrupt
                }
                if made > 0 {
                    unpackedBytes += Int64(made)
                    try output(UnsafeRawBufferPointer(start: out, count: made))
                }
                if status == COMPRESSION_STATUS_ERROR { throw XZError.corrupt }
                if status == COMPRESSION_STATUS_END {
                    streams += 1
                    between = true
                    padding = 0
                    break
                }
                // More to do while input is left or the output filled up.
                if s.pointee.src_size == 0 && made < XZDecoder.outputBytes { break }
            }
            let used = left - s.pointee.src_size
            p += used
            left = s.pointee.src_size
            if !between { return }      // all input taken by the current stream
        }
    }

    public func feed(_ data: Data, output: (UnsafeRawBufferPointer) throws -> Void) throws {
        try data.withUnsafeBytes { try feed($0, output: output) }
    }

    /// The input has ended: the last stream must be complete, and padding after it whole.
    public func finish(output: (UnsafeRawBufferPointer) throws -> Void) throws {
        if between {
            guard padding % 4 == 0 else { throw XZError.badPadding }
            return
        }
        guard let s = stream, packedBytes > 0 else { throw XZError.truncated }
        s.pointee.src_size = 0
        while true {
            s.pointee.dst_ptr = out
            s.pointee.dst_size = XZDecoder.outputBytes
            let status = compression_stream_process(s, Int32(COMPRESSION_STREAM_FINALIZE.rawValue))
            let made = XZDecoder.outputBytes - s.pointee.dst_size
            if made > 0 {
                unpackedBytes += Int64(made)
                try output(UnsafeRawBufferPointer(start: out, count: made))
            }
            if status == COMPRESSION_STATUS_END {
                streams += 1
                between = true
                return
            }
            if status == COMPRESSION_STATUS_ERROR || made == 0 { throw XZError.truncated }
        }
    }
}
