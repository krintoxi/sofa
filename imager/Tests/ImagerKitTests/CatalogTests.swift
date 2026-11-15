import Foundation
@testable import ImagerKit
import XCTest

/// The Linux list: each project's own files, as they read on 2026-11-14 (cut down), turned into what's written.
final class CatalogTests: XCTestCase {
    static let ubuntuMeta = """
    Dist: jammy
    Name: Jammy Jellyfish
    Version: 22.04.5 LTS
    Supported: 1

    Dist: noble
    Name: Noble Numbat
    Version: 24.04.5 LTS
    Supported: 1

    Dist: resolute
    Name: Resolute Raccoon
    Version: 26.04.1 LTS
    Supported: 1

    Dist: someday
    Name: Not Yet
    Version: 28.04 LTS
    Supported: 0
    """
    static let ubuntuSums = """
    487f87faaf547ea30e0aba4d5b53346292571256b25333a978db1692bcee9dd2 *ubuntu-26.04-desktop-amd64.iso
    dec49008a71f6098d0bcfc822021f4d042d5f2db279e4d75bdd981304f1ca5d9 *ubuntu-26.04-live-server-amd64.iso
    601e30fbf5d97759367c632e2c33630665039b7e2158fd068403da3ccf1bda1f *ubuntu-26.04.1-desktop-amd64.iso
    cc8a95cde20f6ced61a322420de00f10cc3c90ced545daa46cb9c1a117f1d927 *ubuntu-26.04.1-live-server-amd64.iso
    """
    static let debianSums = """
    a7ef94ac2fb9a7fec454552abd629b7cc9d5155c886165a45649f5ce6167e355  debian-13.7.0-amd64-netinst.iso
    d33ed0c64bde5ff43445c0c530f9da599954d8585771c55345cb840d7997d4a7  debian-edu-13.7.0-amd64-netinst.iso
    d6d4e0d038936230229a66b7c1765452e73c72a962e79dbb99544882295271e8  debian-mac-13.7.0-amd64-netinst.iso
    """
    static let mintIndex = #"<a href="21.3/">21.3/</a> <a href="22/">22/</a> <a href="22.10/">22.10/</a> <a href="22.3/">22.3/</a>"#
    static let mintSums = """
    a081ab202cfda17f6924128dbd2de8b63518ac0531bcfe3f1a1b88097c459bd4 *linuxmint-22.10-cinnamon-64bit.iso
    7609294da613b75eea89bb918292125e9f06418a368136fb190466e15bf8c373 *linuxmint-22.10-mate-64bit.iso
    """
    static let fedora = """
    [{"version":"44","arch":"x86_64","link":"https://download.fedoraproject.org/pub/fedora/linux/releases/44/Workstation/x86_64/iso/Fedora-Workstation-Live-44-1.7.x86_64.iso","variant":"Workstation","subvariant":"Workstation","sha256":"1620295f6a00c27c3208f0c00b8ece4eab1ec69b9002152d97488bf26a426ddf","size":"2851612672"},
     {"version":"45","arch":"x86_64","link":"https://download.fedoraproject.org/pub/fedora/linux/releases/45/Workstation/x86_64/iso/Fedora-Workstation-Live-45-1.4.x86_64.iso","variant":"Workstation","subvariant":"Workstation","sha256":"68338c6bfe4f0d64151f2e47efe9f44a8855ad05b460e56b844fb3fa2c9a3beb","size":"2925092864"},
     {"version":"46 Beta","arch":"x86_64","link":"https://download.fedoraproject.org/pub/fedora/linux/releases/test/46_Beta/Workstation/x86_64/iso/Fedora-Workstation-Live-46-0.1.x86_64.iso","variant":"Workstation","subvariant":"Workstation","sha256":"0000000000000000000000000000000000000000000000000000000000000000","size":"3000000000"},
     {"version":"45","arch":"aarch64","link":"https://download.fedoraproject.org/pub/fedora/linux/releases/45/Workstation/aarch64/images/x.raw.xz","variant":"Workstation","subvariant":"Workstation","sha256":"1111111111111111111111111111111111111111111111111111111111111111","size":"3000000000"}]
    """
    static let raspberryPi = """
    {"imager": {}, "os_list": [
     {"name": "Raspberry Pi OS (64-bit)", "description": "A port of Debian Trixie with the Raspberry Pi Desktop",
      "url": "https://downloads.raspberrypi.com/raspios_arm64/images/raspios_arm64-2026-10-06/2026-10-06-raspios-trixie-arm64.img.xz",
      "extract_size": 6744440832, "extract_sha256": "2e0024bca282503a5cb6755500cbd7998cfc141c8f452808b59f9178623d2f0d",
      "image_download_size": 1364720984, "release_date": "2026-10-06", "devices": ["pi5-64bit", "pi4-64bit", "pi3-64bit"]},
     {"name": "Raspberry Pi OS (other)", "subitems": [
      {"name": "Raspberry Pi OS Lite (64-bit)", "description": "No desktop",
       "url": "https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-10-06/2026-10-06-raspios-trixie-arm64-lite.img.xz",
       "extract_size": 3082813440, "extract_sha256": "b8a393dc1c3701450b5fffbfe74368a98fb6eab7415ce456cc0cead886ea8780",
       "image_download_size": 512000000, "release_date": "2026-10-06", "devices": ["pi5-64bit", "pi4-64bit", "pi3-64bit"]}]}]}
    """

    /// The network, as a table of answers; anything else is a 404.
    final class Stub: CatalogFetcher {
        var pages: [String: String] = [:]
        var lengths: [String: Int64] = [:]
        var asked: [String] = []
        func text(_ url: URL) async throws -> String {
            asked.append(url.absoluteString)
            guard let t = pages[url.absoluteString] else { throw DownloadError.http(404) }
            return t
        }
        func length(_ url: URL) async throws -> Int64 {
            asked.append("HEAD " + url.absoluteString)
            guard let n = lengths[url.absoluteString] else { throw DownloadError.http(404) }
            return n
        }
    }

    static func stub() -> Stub {
        let s = Stub()
        s.pages["https://changelogs.ubuntu.com/meta-release-lts"] = ubuntuMeta
        s.pages["https://releases.ubuntu.com/26.04/SHA256SUMS"] = ubuntuSums
        s.lengths["https://releases.ubuntu.com/26.04/ubuntu-26.04.1-desktop-amd64.iso"] = 6_482_409_472
        s.pages["https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA256SUMS"] = debianSums
        s.lengths["https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.7.0-amd64-netinst.iso"] = 792_723_456
        s.pages["https://mirrors.kernel.org/linuxmint/stable/"] = mintIndex
        s.pages["https://mirrors.kernel.org/linuxmint/stable/22.10/sha256sum.txt"] = mintSums
        s.lengths["https://mirrors.kernel.org/linuxmint/stable/22.10/linuxmint-22.10-cinnamon-64bit.iso"] = 3_090_000_000
        s.pages["https://fedoraproject.org/releases.json"] = fedora
        s.pages["https://downloads.raspberrypi.com/os_list_imagingutility_v4.json"] = raspberryPi
        return s
    }

    func testSumsFilesInEveryShape() {
        let sums = SumsFile.parse("""
        a7ef94ac2fb9a7fec454552abd629b7cc9d5155c886165a45649f5ce6167e355  debian-13.7.0-amd64-netinst.iso
        601E30FBF5D97759367C632E2C33630665039B7E2158FD068403DA3CCF1BDA1F *ubuntu-26.04.1-desktop-amd64.iso
        SHA256 (Fedora-Workstation-Live-45-1.4.x86_64.iso) = 68338c6bfe4f0d64151f2e47efe9f44a8855ad05b460e56b844fb3fa2c9a3beb
        not a line
        1234 short.iso
        a7ef94ac2fb9a7fec454552abd629b7cc9d5155c886165a45649f5ce6167e355  ../escapes.iso
        """)
        XCTAssertEqual(sums.count, 3)
        XCTAssertEqual(sums["ubuntu-26.04.1-desktop-amd64.iso"], "601e30fbf5d97759367c632e2c33630665039b7e2158fd068403da3ccf1bda1f")
        XCTAssertEqual(sums["Fedora-Workstation-Live-45-1.4.x86_64.iso"]?.prefix(8), "68338c6b")
        XCTAssertNil(sums["../escapes.iso"])
    }

    func testTheNewestIsChosenByVersionNotByText() throws {
        XCTAssertEqual(try UbuntuMeta.newestLTS(Self.ubuntuMeta), "26.04.1")
        XCTAssertEqual(DirectoryIndex.newestVersion(Self.mintIndex), "22.10")
        let pick = SumsFile.newest(SumsFile.parse(Self.ubuntuSums), matching: #"^ubuntu-26\.04(\.[0-9]+)?-desktop-amd64\.iso$"#)
        XCTAssertEqual(pick?.0, "ubuntu-26.04.1-desktop-amd64.iso")
        let f = try XCTUnwrap(FedoraReleases.newest(Self.fedora, variant: "Workstation", arch: "x86_64"))
        XCTAssertEqual(f.version, "45", "a beta is never chosen")
        XCTAssertEqual(f.size, 2_925_092_864)
    }

    func testEveryEntryResolvesFromItsProjectsOwnFiles() async throws {
        let s = Self.stub()
        var got: [String: Card] = [:]
        for e in Catalog.entries { got[e.id] = try await CatalogResolver.resolve(e, with: s) }
        let u = try XCTUnwrap(got["ubuntu"])
        XCTAssertEqual(u.name, "Ubuntu Desktop 26.04.1 LTS")
        XCTAssertEqual(u.url.absoluteString, "https://releases.ubuntu.com/26.04/ubuntu-26.04.1-desktop-amd64.iso")
        XCTAssertEqual(u.extractSHA256, "601e30fbf5d97759367c632e2c33630665039b7e2158fd068403da3ccf1bda1f")
        XCTAssertEqual(u.extractSize, 6_482_409_472)
        XCTAssertEqual(u.downloadSize, u.extractSize, "an ISO is written as it's downloaded")
        XCTAssertFalse(u.isPacked)
        let d = try XCTUnwrap(got["debian"])
        XCTAssertEqual(d.name, "Debian 13.7.0")
        XCTAssertEqual(d.extractSHA256, "a7ef94ac2fb9a7fec454552abd629b7cc9d5155c886165a45649f5ce6167e355")
        XCTAssertEqual(got["mint"]?.name, "Linux Mint 22.10 Cinnamon")
        XCTAssertEqual(got["mint"]?.url.absoluteString,
                       "https://mirrors.kernel.org/linuxmint/stable/22.10/linuxmint-22.10-cinnamon-64bit.iso")
        XCTAssertEqual(got["fedora"]?.name, "Fedora Workstation 45")
        XCTAssertEqual(got["fedora"]?.extractSize, 2_925_092_864)
        let pi = try XCTUnwrap(got["raspios"])
        XCTAssertTrue(pi.isPacked)
        XCTAssertEqual(pi.extractSize, 6_744_440_832)
        XCTAssertEqual(pi.downloadSize, 1_364_720_984)
        XCTAssertEqual(got["raspios-lite"]?.extractSHA256, "b8a393dc1c3701450b5fffbfe74368a98fb6eab7415ce456cc0cead886ea8780")
        // Every address asked for is the project's own, over HTTPS.
        for a in s.asked { XCTAssertTrue(a.replacingOccurrences(of: "HEAD ", with: "").hasPrefix("https://"), a) }
        XCTAssertEqual(Set(Catalog.entries.map(\.medium)), [.stick, .sdCard])
    }

    func testAnswersThatDontAddUpAreRefused() async {
        let s = Self.stub()
        s.pages["https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA256SUMS"] = "nothing here"
        await XCTAssertThrowsErrorAsync(try await CatalogResolver.resolve(Catalog.entry("debian")!, with: s))
        s.pages["https://fedoraproject.org/releases.json"] = Self.fedora.replacingOccurrences(of: "https://download", with: "http://download")
        await XCTAssertThrowsErrorAsync(try await CatalogResolver.resolve(Catalog.entry("fedora")!, with: s))
        s.lengths = [:]
        await XCTAssertThrowsErrorAsync(try await CatalogResolver.resolve(Catalog.entry("ubuntu")!, with: s))
    }
}

func XCTAssertThrowsErrorAsync<T>(_ body: @autoclosure () async throws -> T, file: StaticString = #filePath, line: UInt = #line) async {
    do {
        _ = try await body()
        XCTFail("no error", file: file, line: line)
    } catch {}
}
