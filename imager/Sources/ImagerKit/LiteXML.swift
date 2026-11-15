import Foundation

/// Just enough XML to read a Windows image's list of editions (`WIMFile.parseImages`), written here so that Windows and
/// Linux need no XML library: elements, attributes in either quote, text, comments, `<?...?>`, CDATA, the five named
/// entities and numeric ones. No DTD: a `<!DOCTYPE` stops it. Like `XMLParser`, it stops at the first thing that isn't
/// well formed, having told the reader everything before it.
enum LiteXML {
    protocol Reader: AnyObject {
        func start(_ name: String, attributes: [String: String])
        func text(_ text: String)
        func end(_ name: String)
    }

    /// Reads `xml` from the start, telling `reader` as it goes. False if it stopped early.
    @discardableResult
    static func read(_ xml: String, into reader: Reader) -> Bool {
        let b = Array(xml.utf8)
        var i = 0
        var open: [String] = []

        func starts(_ s: String, at j: Int) -> Bool {
            let u = Array(s.utf8)
            return j + u.count <= b.count && Array(b[j..<j + u.count]) == u
        }
        func find(_ s: String, from j: Int) -> Int? {
            let u = Array(s.utf8)
            var k = j
            while k + u.count <= b.count {
                if b[k] == u[0] && Array(b[k..<k + u.count]) == u { return k }
                k += 1
            }
            return nil
        }
        func isSpace(_ c: UInt8) -> Bool { c == 0x20 || c == 0x09 || c == 0x0A || c == 0x0D }
        func isNameByte(_ c: UInt8) -> Bool {
            !isSpace(c) && c != UInt8(ascii: ">") && c != UInt8(ascii: "/") && c != UInt8(ascii: "=")
                && c != UInt8(ascii: "<") && c != UInt8(ascii: "\"") && c != UInt8(ascii: "'")
        }
        func name(from j: inout Int) -> String? {
            let s = j
            while j < b.count && isNameByte(b[j]) { j += 1 }
            return j > s ? String(decoding: b[s..<j], as: UTF8.self) : nil
        }
        func skipSpace(_ j: inout Int) { while j < b.count && isSpace(b[j]) { j += 1 } }

        while i < b.count {
            if b[i] != UInt8(ascii: "<") {
                var j = i
                while j < b.count && b[j] != UInt8(ascii: "<") { j += 1 }
                guard let t = decodeEntities(b[i..<j]) else { return false }
                reader.text(t)
                i = j
                continue
            }
            if starts("<?", at: i) {
                guard let e = find("?>", from: i + 2) else { return false }
                i = e + 2
            } else if starts("<!--", at: i) {
                guard let e = find("-->", from: i + 4) else { return false }
                i = e + 3
            } else if starts("<![CDATA[", at: i) {
                guard let e = find("]]>", from: i + 9) else { return false }
                reader.text(String(decoding: b[i + 9..<e], as: UTF8.self))
                i = e + 3
            } else if starts("<!", at: i) {
                return false
            } else if starts("</", at: i) {
                var j = i + 2
                guard let n = name(from: &j) else { return false }
                skipSpace(&j)
                guard j < b.count, b[j] == UInt8(ascii: ">"), open.last == n else { return false }
                open.removeLast()
                reader.end(n)
                i = j + 1
            } else {
                var j = i + 1
                guard let n = name(from: &j) else { return false }
                var attributes: [String: String] = [:]
                while true {
                    skipSpace(&j)
                    guard j < b.count else { return false }
                    if b[j] == UInt8(ascii: ">") {
                        reader.start(n, attributes: attributes)
                        open.append(n)
                        i = j + 1
                        break
                    }
                    if b[j] == UInt8(ascii: "/") {
                        guard j + 1 < b.count, b[j + 1] == UInt8(ascii: ">") else { return false }
                        reader.start(n, attributes: attributes)
                        reader.end(n)
                        i = j + 2
                        break
                    }
                    guard let a = name(from: &j) else { return false }
                    skipSpace(&j)
                    guard j < b.count, b[j] == UInt8(ascii: "=") else { return false }
                    j += 1
                    skipSpace(&j)
                    guard j < b.count, b[j] == UInt8(ascii: "\"") || b[j] == UInt8(ascii: "'") else { return false }
                    let quote = b[j]
                    let s = j + 1
                    j = s
                    while j < b.count && b[j] != quote && b[j] != UInt8(ascii: "<") { j += 1 }
                    guard j < b.count, b[j] == quote, let v = decodeEntities(b[s..<j]) else { return false }
                    attributes[a] = v
                    j += 1
                }
            }
        }
        return open.isEmpty
    }

    /// `&amp;` `&lt;` `&gt;` `&quot;` `&apos;` `&#NN;` `&#xHH;`. Nil for any other, or a bare `&`.
    static func decodeEntities(_ s: ArraySlice<UInt8>) -> String? {
        guard s.contains(UInt8(ascii: "&")) else { return String(decoding: s, as: UTF8.self) }
        var out = ""
        var run = s.startIndex
        var i = s.startIndex
        while i < s.endIndex {
            guard s[i] == UInt8(ascii: "&") else {
                i += 1
                continue
            }
            out += String(decoding: s[run..<i], as: UTF8.self)
            guard let semi = s[i...].firstIndex(of: UInt8(ascii: ";")), semi - i <= 12 else { return nil }
            let entity = String(decoding: s[(i + 1)..<semi], as: UTF8.self)
            switch entity {
            case "amp": out += "&"
            case "lt": out += "<"
            case "gt": out += ">"
            case "quot": out += "\""
            case "apos": out += "'"
            default:
                let hex = entity.hasPrefix("#x") || entity.hasPrefix("#X")
                guard entity.hasPrefix("#"),
                      let v = UInt32(entity.dropFirst(hex ? 2 : 1), radix: hex ? 16 : 10),
                      let scalar = Unicode.Scalar(v) else { return nil }
                out.unicodeScalars.append(scalar)
            }
            i = semi + 1
            run = i
        }
        out += String(decoding: s[run..<s.endIndex], as: UTF8.self)
        return out
    }
}
