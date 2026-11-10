import Foundation

/// Sofa's look, as numbers: the same on every platform Sofa Box Imager is built for, and the same whether the
/// computer is set to light or dark. These are the web app's own values (`client/sofa.css`, the Midnight theme that
/// Sofa's icon is drawn in), so the imager sits beside Sofa and the box as one product. A Windows build reads this
/// same table.
public enum SofaTheme {
    /// 0xRRGGBB
    public static let ink = 0x0A0E1A          // the room: the window's background
    public static let slate = 0x151B2C        // panels
    public static let slate2 = 0x1E2639       // controls on panels
    public static let slate3 = 0x2B3552       // pressed, selected
    public static let paper = 0xEDEFF6        // text
    public static let soft = 0xC9CEDC         // secondary text
    public static let mist = 0x8C94AB         // captions
    public static let amber = 0xF4B740        // the accent: the sofa
    public static let amberHi = 0xFFC85C      // the accent, pointed at
    public static let amberInk = 0x2B1D00     // text on amber
    public static let green = 0x5ED3A0        // done, ready
    public static let alert = 0xFF8A7A        // went wrong, will erase
    /// Hairlines: paper at this opacity.
    public static let lineOpacity = 0.09

    public static let displayFamily = "Bricolage Grotesque"
    public static let textFamily = "Instrument Sans"
    /// The font files, as Sofa ships them (`client/vendor/fonts`, SIL Open Font License 1.1).
    public static let fontFiles = ["bricolage-grotesque-latin-opsz-normal.woff2",
                                   "instrument-sans-latin-wght-normal.woff2"]

    public static func rgb(_ hex: Int) -> (red: Double, green: Double, blue: Double) {
        (Double((hex >> 16) & 0xFF) / 255, Double((hex >> 8) & 0xFF) / 255, Double(hex & 0xFF) / 255)
    }
}
