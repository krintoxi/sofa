import AppKit
import CoreText
import ImagerKit
import SwiftUI

/// Sofa's colours and type for SwiftUI (the numbers are `SofaTheme`'s), and the app's own controls drawn in them.
extension Color {
    init(sofa hex: Int) {
        let c = SofaTheme.rgb(hex)
        self.init(.sRGB, red: c.red, green: c.green, blue: c.blue, opacity: 1)
    }

    static let ink = Color(sofa: SofaTheme.ink)
    static let slate = Color(sofa: SofaTheme.slate)
    static let slate2 = Color(sofa: SofaTheme.slate2)
    static let slate3 = Color(sofa: SofaTheme.slate3)
    static let paper = Color(sofa: SofaTheme.paper)
    static let soft = Color(sofa: SofaTheme.soft)
    static let mist = Color(sofa: SofaTheme.mist)
    static let amber = Color(sofa: SofaTheme.amber)
    static let amberHi = Color(sofa: SofaTheme.amberHi)
    static let amberInk = Color(sofa: SofaTheme.amberInk)
    static let sofaGreen = Color(sofa: SofaTheme.green)
    static let alert = Color(sofa: SofaTheme.alert)
    static let line = Color.paper.opacity(SofaTheme.lineOpacity)
}

/// Sofa's two typefaces, loaded from the app (or, in a build run straight from the source, from Sofa's own folder).
/// Without them the system's rounded face stands in.
enum SofaFonts {
    enum Weight: String { case regular = "", medium = "Medium", semibold = "SemiBold", bold = "Bold", extraBold = "ExtraBold" }

    /// PostScript names of each family's named weights, found when the files are registered.
    private static let names: [String: [String]] = {
        var found: [String: [String]] = [:]
        var folders: [URL] = []
        if let r = Bundle.main.resourceURL { folders.append(r.appendingPathComponent("Fonts")) }
        folders.append(URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../../client/vendor/fonts").standardizedFileURL)
        for file in SofaTheme.fontFiles {
            guard let url = folders.map({ $0.appendingPathComponent(file) })
                .first(where: { FileManager.default.fileExists(atPath: $0.path) }) else { continue }
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
            let all = (CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor] ?? [])
                .compactMap { CTFontDescriptorCopyAttribute($0, kCTFontNameAttribute) as? String }
            found[file.hasPrefix("bricolage") ? SofaTheme.displayFamily : SofaTheme.textFamily] = all
        }
        return found
    }()

    private static func name(_ family: String, _ weight: Weight) -> String? {
        guard let all = names[family], !all.isEmpty else { return nil }
        if weight == .regular { return all.first { !$0.contains("_") } ?? all[0] }
        return all.first { $0.hasSuffix("_" + weight.rawValue) } ?? all.first { !$0.contains("_") }
    }

    static var loaded: Bool { names.count == SofaTheme.fontFiles.count }

    /// Headings and the name: Bricolage Grotesque.
    static func display(_ size: CGFloat, _ weight: Weight = .bold) -> Font {
        if let n = name(SofaTheme.displayFamily, weight) { return .custom(n, fixedSize: size) }
        return .system(size: size, weight: .bold, design: .rounded)
    }

    /// Everything else: Instrument Sans.
    static func text(_ size: CGFloat, _ weight: Weight = .regular) -> Font {
        if let n = name(SofaTheme.textFamily, weight) { return .custom(n, fixedSize: size) }
        return .system(size: size, weight: weight == .regular ? .regular : .semibold)
    }
}

/// Sofa's buttons: pills. Amber for the one thing to do, quiet for the rest, coral for erasing.
struct SofaButtonStyle: ButtonStyle {
    enum Kind { case primary, quiet, danger }
    var kind: Kind = .quiet
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View { Pill(kind: kind, enabled: enabled, configuration: configuration) }

    private struct Pill: View {
        let kind: Kind
        let enabled: Bool
        let configuration: Configuration
        @State private var hover = false

        var body: some View {
            configuration.label
                .font(SofaFonts.text(14, .semibold))
                .foregroundStyle(kind == .primary ? Color.amberInk : (kind == .danger ? Color.ink : Color.paper))
                .padding(.horizontal, 22)
                .padding(.vertical, 10)
                .background(Capsule().fill(fill))
                .overlay(Capsule().stroke(kind == .quiet ? Color.line : .clear))
                .opacity(enabled ? 1 : 0.38)
                .scaleEffect(configuration.isPressed ? 0.97 : 1)
                .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
                .onHover { hover = $0 }
                .contentShape(Capsule())
        }

        private var fill: Color {
            switch kind {
            case .primary: return hover && enabled ? .amberHi : .amber
            case .danger: return .alert
            case .quiet: return Color.paper.opacity(hover && enabled ? 0.2 : 0.12)
            }
        }
    }
}

/// A panel: slate, a hairline, rounded as Sofa's cards are.
struct Panel<Content: View>: View {
    var ring: Color? = nil
    @ViewBuilder let content: Content

    var body: some View {
        content
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.slate))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(ring ?? .line, lineWidth: ring == nil ? 1 : 2))
    }
}

/// Sofa's progress bar: thin, amber on a pale track. `nil` slides back and forth.
struct SofaProgress: View {
    let fraction: Double?
    @State private var slide = false

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.paper.opacity(0.16))
                if let f = fraction {
                    Capsule().fill(Color.amber).frame(width: max(8, g.size.width * min(1, max(0, f))))
                        .animation(.easeOut(duration: 0.25), value: f)
                } else {
                    Capsule().fill(Color.amber).frame(width: g.size.width * 0.3)
                        .offset(x: slide ? g.size.width * 0.7 : 0)
                        .onAppear { withAnimation(.easeInOut(duration: 1.1).repeatForever()) { slide = true } }
                }
            }
        }
        .frame(height: 8)
    }
}

/// A tick box in amber.
struct SofaCheck: View {
    @Binding var isOn: Bool
    let label: String

    var body: some View {
        Button { isOn.toggle() } label: {
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(isOn ? Color.amber : Color.slate2)
                    .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).stroke(isOn ? .clear : Color.mist.opacity(0.6)))
                    .overlay(Image(systemName: "checkmark").font(.system(size: 11, weight: .heavy))
                        .foregroundStyle(Color.amberInk).opacity(isOn ? 1 : 0))
                    .frame(width: 20, height: 20)
                Text(label).font(SofaFonts.text(14, .medium)).foregroundStyle(Color.paper)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isOn ? .isSelected : [])
    }
}

/// Sofa's pill: a dot and a word.
struct SofaPill: View {
    let text: String
    var color: Color = .sofaGreen

    var body: some View {
        HStack(spacing: 8) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text).font(SofaFonts.text(13, .semibold)).foregroundStyle(color)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
        .background(Capsule().fill(color.opacity(0.14)))
    }
}

/// The room: ink, with the amber of the sofa glowing in one corner, as Sofa's pages glow with what's playing.
struct SofaBackdrop: View {
    var body: some View {
        ZStack {
            Color.ink
            RadialGradient(colors: [Color.amber.opacity(0.16), .clear], center: .topLeading, startRadius: 0, endRadius: 420)
            RadialGradient(colors: [Color.slate3.opacity(0.55), .clear], center: .bottomTrailing, startRadius: 0, endRadius: 520)
        }
        .ignoresSafeArea()
    }
}
