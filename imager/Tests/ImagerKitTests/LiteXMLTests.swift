import Foundation
@testable import ImagerKit
import XCTest
#if canImport(FoundationXML)
import FoundationXML
#endif

/// Our small XML reader, which reads a Windows image's list of editions: what it reads, where it stops, and that it
/// reads a real-looking list the same as Foundation's `XMLParser`.
final class LiteXMLTests: XCTestCase {
    /// Shaped like the XML at the end of a Windows 11 `install.wim` (the parts the Imager reads, and some it doesn't).
    static let editions = """
    <WIM><TOTALBYTES>5523542180</TOTALBYTES>\
    <IMAGE INDEX="1"><DIRCOUNT>24158</DIRCOUNT><WINDOWS><ARCH>9</ARCH><PRODUCTNAME>Microsoft&#174; Windows&#174; \
    Operating System</PRODUCTNAME><EDITIONID>Core</EDITIONID><INSTALLATIONTYPE>Client</INSTALLATIONTYPE>\
    <LANGUAGES><LANGUAGE>en-US</LANGUAGE><DEFAULT>en-US</DEFAULT></LANGUAGES><VERSION><MAJOR>10</MAJOR><MINOR>0</MINOR>\
    <BUILD>26300</BUILD><SPBUILD>9457</SPBUILD><SPLEVEL>0</SPLEVEL></VERSION></WINDOWS><NAME>Windows 11 Home</NAME>\
    <DESCRIPTION>Windows 11 Home</DESCRIPTION><FLAGS>Core</FLAGS><DISPLAYNAME>Windows 11 Home</DISPLAYNAME>\
    <DISPLAYDESCRIPTION>Windows 11 Home</DISPLAYDESCRIPTION></IMAGE>
    <IMAGE INDEX='2'><WINDOWS><ARCH>9</ARCH><EDITIONID>ProfessionalWorkstation</EDITIONID><VERSION><MAJOR>10</MAJOR>\
    <MINOR>0</MINOR><BUILD>26300</BUILD><SPBUILD>9457</SPBUILD></VERSION></WINDOWS>\
    <NAME>Windows 11 Pro for Workstations</NAME><DISPLAYNAME>Windows 11 Pro &amp; &lt;Workstations&gt;</DISPLAYNAME>\
    <!-- a comment --><EMPTY/><EMPTY2 A="1" /></IMAGE></WIM>
    """

    private final class Recorder: LiteXML.Reader {
        var events: [String] = []
        func start(_ name: String, attributes: [String: String]) {
            events.append("<" + ([name] + attributes.keys.sorted().map { "\($0)=\(attributes[$0]!)" }).joined(separator: " "))
        }
        func text(_ text: String) { if let last = events.last, last.hasPrefix("'") { events[events.count - 1] = String(last.dropLast()) + text + "'" } else { events.append("'" + text + "'") } }
        func end(_ name: String) { events.append(">" + name) }
    }

    private func read(_ xml: String) -> (Bool, [String]) {
        let r = Recorder()
        let ok = LiteXML.read(xml, into: r)
        return (ok, r.events)
    }

    func testTheEditionsList() {
        let images = WIMFile.parseImages(utf16(LiteXMLTests.editions))
        XCTAssertEqual(images.count, 2)
        XCTAssertEqual(images[0].index, 1)
        XCTAssertEqual(images[0].name, "Windows 11 Home")
        XCTAssertEqual(images[0].edition, "Core")
        XCTAssertEqual(images[0].arch, 9)
        XCTAssertEqual(images[0].build, 26300)
        XCTAssertEqual(images[0].servicePackBuild, 9457)
        XCTAssertEqual(images[1].index, 2)
        XCTAssertEqual(images[1].displayName, "Windows 11 Pro & <Workstations>")
        XCTAssertEqual(images[1].edition, "ProfessionalWorkstation")
    }

    func testWhatItReads() {
        let (ok, events) = read(#"<?xml version="1.0"?><a x="1" y='&quot;2&#x41;'>t&amp;u<![CDATA[<raw>]]><b/></a>"#)
        XCTAssertTrue(ok)
        XCTAssertEqual(events, [#"<a x=1 y="2A"#, "'t&u<raw>'", "<b", ">b", ">a"])
    }

    func testWhereItStops() {
        for bad in ["<a>", "<a></b>", "<a x=1></a>", "<a>&nbsp;</a>", "<a>& </a>", "<!DOCTYPE a><a/>", "<a", "<a><!-- </a>",
                    "<a x=\"1></a>", "</a>", "<a/ >"] {
            XCTAssertFalse(read(bad).0, bad)
        }
        // Everything before the fault is still told.
        XCTAssertEqual(read("<a><b>x</b><c>&bad;</c></a>").1, ["<a", "<b", "'x'", ">b", "<c"])
    }

    #if canImport(FoundationXML) || canImport(Darwin)
    /// Foundation's own parser reads the same editions from the same list.
    func testTheSameAsFoundationsParser() {
        final class Old: NSObject, XMLParserDelegate {
            var events: [String] = []
            var text = ""
            func flush() { if !text.isEmpty { events.append(text); text = "" } }
            func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?, qualifiedName: String?,
                        attributes: [String: String] = [:]) {
                flush(); events.append("<" + ([name] + attributes.keys.sorted().map { "\($0)=\(attributes[$0]!)" }).joined(separator: " "))
            }
            func parser(_ parser: XMLParser, foundCharacters string: String) { text += string }
            func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName: String?) {
                flush(); events.append(">" + name)
            }
        }
        final class New: LiteXML.Reader {
            var events: [String] = []
            var text = ""
            func flush() { if !text.isEmpty { events.append(text); text = "" } }
            func start(_ name: String, attributes: [String: String]) {
                flush(); events.append("<" + ([name] + attributes.keys.sorted().map { "\($0)=\(attributes[$0]!)" }).joined(separator: " "))
            }
            func text(_ string: String) { text += string }
            func end(_ name: String) { flush(); events.append(">" + name) }
        }
        let old = Old()
        let parser = XMLParser(data: Data(LiteXMLTests.editions.utf8))
        parser.delegate = old
        XCTAssertTrue(parser.parse())
        old.flush()
        let new = New()
        XCTAssertTrue(LiteXML.read(LiteXMLTests.editions, into: new))
        new.flush()
        XCTAssertEqual(new.events, old.events)
    }
    #endif

    private func utf16(_ s: String) -> Data {
        var d = Data([0xFF, 0xFE])
        for u in s.utf16 { d.append(UInt8(u & 0xFF)); d.append(UInt8(u >> 8)) }
        return d
    }
}
