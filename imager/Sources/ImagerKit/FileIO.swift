import Foundation
#if os(Windows)
import CRT
import WinSDK
#endif

/// Opening a file and reading, writing and flushing it at a place, the one part of the core that differs by system.
/// On the Mac and Linux these are `open`, `fstat`, `pread`, `pwrite` and `fsync`, as before. Windows has none of the
/// last three: there it's `ReadFile` and `WriteFile` with the place given in an `OVERLAPPED`, and `FlushFileBuffers`.
///
/// Everything goes by a descriptor (`Int32`) on every system, so `FileDescriptorDevice` is the same everywhere. A
/// read or a write answers how many bytes it moved, or -1 with an errno value (`strerror` puts it into words).
public enum FileIO {
    public typealias Moved = (count: Int, code: Int32)

    #if os(Windows)
    // Windows' own numbers, written out so nothing hangs on how each macro's type comes across.
    private static let genericRead: DWORD = 0x8000_0000
    private static let genericWrite: DWORD = 0x4000_0000
    private static let shareAll: DWORD = 0x7                 // others may read, write and delete meanwhile
    private static let openExisting: DWORD = 3
    private static let attributeNormal: DWORD = 0x80
    private static let errorHandleEOF: DWORD = 38
    private static let binary: Int32 = 0x8000                // _O_BINARY: bytes as they are, no line-end changes
    /// The most one call moves: a `DWORD` counts the bytes.
    private static let most = 1 << 30

    private static func ok(_ b: Bool) -> Bool { b }
    private static func ok(_ b: WindowsBool) -> Bool { b.boolValue }
    private static func ok(_ b: Int32) -> Bool { b != 0 }

    private static func handle(_ fd: Int32) -> HANDLE? { HANDLE(bitPattern: _get_osfhandle(fd)) }

    private static func place(_ offset: Int64) -> OVERLAPPED {
        var o = OVERLAPPED()
        o.Offset = DWORD(truncatingIfNeeded: offset)
        o.OffsetHigh = DWORD(truncatingIfNeeded: offset >> 32)
        return o
    }

    /// A descriptor for the file, or -1. The file must be there already.
    public static func openFile(_ url: URL, writing: Bool = false) -> Int32 {
        let native: String? = url.withUnsafeFileSystemRepresentation { $0.map { String(cString: $0) } }
        guard let native else { return -1 }
        let h: HANDLE? = native.withCString(encodedAs: UTF16.self) {
            CreateFileW($0, writing ? genericRead | genericWrite : genericRead, shareAll, nil, openExisting,
                        attributeNormal, nil)
        }
        guard let h, Int(bitPattern: h) != -1 else { return -1 }
        let fd = _open_osfhandle(Int(bitPattern: h), binary)
        if fd < 0 { _ = CloseHandle(h) }
        return fd
    }

    public static func closeFile(_ fd: Int32) { _ = _close(fd) }

    /// The file's length (64 bits: `fstat`'s is 32 there).
    static func size(_ fd: Int32) -> Int64? {
        var s = LARGE_INTEGER()
        guard ok(GetFileSizeEx(handle(fd), &s)) else { return nil }
        return s.QuadPart
    }

    static func read(_ fd: Int32, into buffer: UnsafeMutableRawPointer, count: Int, at offset: Int64) -> Moved {
        var o = place(offset)
        var got: DWORD = 0
        if ok(ReadFile(handle(fd), buffer, DWORD(min(count, most)), &got, &o)) { return (Int(got), 0) }
        return GetLastError() == errorHandleEOF ? (0, 0) : (-1, EIO)
    }

    static func write(_ fd: Int32, from buffer: UnsafeRawPointer, count: Int, at offset: Int64) -> Moved {
        var o = place(offset)
        var put: DWORD = 0
        if ok(WriteFile(handle(fd), buffer, DWORD(min(count, most)), &put, &o)) { return (Int(put), 0) }
        return (-1, EIO)
    }

    /// 0, or an errno value. Asks Windows to put everything it holds for the file on the disk.
    static func flush(_ fd: Int32) -> Int32 { ok(FlushFileBuffers(handle(fd))) ? 0 : EIO }
    #else
    /// A descriptor for the file, or -1. The file must be there already.
    public static func openFile(_ url: URL, writing: Bool = false) -> Int32 { open(url.path, writing ? O_RDWR : O_RDONLY) }

    public static func closeFile(_ fd: Int32) { close(fd) }

    static func size(_ fd: Int32) -> Int64? {
        var st = stat()
        return fstat(fd, &st) == 0 ? Int64(st.st_size) : nil
    }

    static func read(_ fd: Int32, into buffer: UnsafeMutableRawPointer, count: Int, at offset: Int64) -> Moved {
        let n = pread(fd, buffer, count, off_t(offset))
        return (n, n < 0 ? errno : 0)
    }

    static func write(_ fd: Int32, from buffer: UnsafeRawPointer, count: Int, at offset: Int64) -> Moved {
        let n = pwrite(fd, buffer, count, off_t(offset))
        return (n, n < 0 ? errno : 0)
    }

    /// 0, or an errno value. A descriptor that can't be flushed (ENOTSUP, EINVAL) isn't a failure.
    static func flush(_ fd: Int32) -> Int32 {
        if fsync(fd) != 0 && errno != ENOTSUP && errno != EINVAL { return errno }
        return 0
    }
    #endif
}
