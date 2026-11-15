import AppKit
import ImagerKit
import SwiftUI

/// The window. It wears Sofa's own look (Theme.swift) whatever the Mac is set to, light or dark.
struct ContentView: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Header()
            Group {
                switch model.phase {
                case .choosing: ChooseView()
                case .running(let text, let fraction): RunningView(text: text, fraction: fraction)
                case .done(let card, let disk): DoneView(card: card, disk: disk)
                case .failed(let text): FailedView(text: text)
                }
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 24)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(minWidth: 640, idealWidth: 680, minHeight: 660, idealHeight: 700)
        .background(SofaBackdrop())
        .foregroundStyle(Color.paper)
        .font(SofaFonts.text(14))
        .preferredColorScheme(.dark)
        .sheet(isPresented: $model.confirming) { ConfirmView() }
    }
}

private struct Header: View {
    var body: some View {
        HStack(spacing: 14) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 54, height: 54)
                .shadow(color: .black.opacity(0.45), radius: 10, y: 4)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("Sofa").font(SofaFonts.display(30, .extraBold)).tracking(-0.9).foregroundStyle(Color.amber)
                    Text("Box Imager").font(SofaFonts.display(30, .bold)).tracking(-0.9)
                }
                Text("Writes Sofa Box OS, Linux and Windows installers to SD cards, USB sticks and DVDs, and reads every byte back.")
                    .font(SofaFonts.text(13.5))
                    .foregroundStyle(Color.mist)
            }
            Spacer()
        }
        .padding(.horizontal, 28)
        .padding(.top, 30)
        .padding(.bottom, 22)
    }
}

// MARK: choosing

private struct ChooseView: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            ModeSwitch()
            switch model.mode {
            case .sofaBox:
                TargetSwitch()
                Step(number: 1, title: "Sofa Box OS") { CardPicker() }
            case .linux:
                Step(number: 1, title: "The system") { SystemPicker() }
            case .windows:
                Step(number: 1, title: "Your Windows ISO") { WindowsPicker() }
            case .file:
                Step(number: 1, title: "Your image") { OwnFilePicker() }
            }
            if model.burns {
                Step(number: 2, title: "The DVD burner") { BurnerPicker() }
            } else {
                Step(number: 2, title: "The \(model.word) to erase") { DiskPicker() }
            }
            Spacer(minLength: 0)
            HStack(alignment: .center) {
                Text(footnote)
                    .font(SofaFonts.text(13))
                    .foregroundStyle(Color.mist)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                Button(model.burns ? "Burn…" : "Write…") { model.askToWrite() }
                    .buttonStyle(SofaButtonStyle(kind: .primary))
                    .keyboardShortcut(.defaultAction)
                    .disabled(!model.canGo)
            }
        }
    }

    private var footnote: String {
        switch model.mode {
        case .sofaBox: return "Nothing is set on the \(model.target.word): the box sets itself up on the TV."
        case .linux: return "Written exactly as the project publishes it, checked against its own SHA-256 list."
        case .windows: return "Every file comes from your ISO. Nothing is added but what you tick."
        case .file: return "Written byte for byte, then read back and checked."
        }
    }
}

/// What to write: Sofa Box OS, another Linux, Windows, or an image of your own.
private struct ModeSwitch: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        HStack(spacing: 8) {
            ForEach(Mode.allCases) { m in
                let on = model.mode == m
                Button { model.mode = m } label: {
                    HStack(spacing: 7) {
                        Image(systemName: m.symbol).font(.system(size: 13, weight: .semibold))
                        Text(m.choice).font(SofaFonts.text(14, .semibold))
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .foregroundStyle(on ? Color.amberInk : Color.soft)
                    .background(Capsule().fill(on ? Color.amber : Color.slate2))
                    .overlay(Capsule().stroke(on ? Color.clear : Color.line))
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .disabled(model.isWriting)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
    }
}

/// Linux: the systems we list, each found on its project's own site.
private struct SystemPicker: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Text(model.systemEntry.name).font(SofaFonts.text(15, .semibold)).foregroundStyle(Color.paper)
                Image(systemName: "chevron.up.chevron.down").font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color.mist)
            }
            .padding(.leading, 16)
            .padding(.trailing, 14)
            .padding(.vertical, 9)
            .background(Capsule().fill(Color.slate2))
            .overlay(Capsule().stroke(Color.line))
            .overlay {
                Menu {
                    Section("For a PC (a USB stick)") {
                        ForEach(Catalog.entries.filter { $0.medium == .stick }) { e in Button(e.name) { model.systemID = e.id } }
                    }
                    Section("For a Raspberry Pi (an SD card)") {
                        ForEach(Catalog.entries.filter { $0.medium == .sdCard }) { e in Button(e.name) { model.systemID = e.id } }
                    }
                } label: { Color.clear }
                    .menuStyle(.borderlessButton)
                    .menuIndicator(.hidden)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .opacity(0.02)
                    .accessibilityLabel("System")
            }
            .fixedSize()
            Text(model.systemEntry.summary).font(SofaFonts.text(13)).foregroundStyle(Color.mist)
            switch model.system {
            case .none, .finding:
                HStack(spacing: 10) {
                    SofaProgress(fraction: nil).frame(width: 120)
                    Text("Finding the newest release on \(model.systemEntry.home.host ?? "its site")…").foregroundStyle(Color.mist)
                }
            case .found(let c):
                Text("\(c.name) · \(ByteSize.text(c.downloadSize)) download\(c.isPacked ? " · \(ByteSize.text(c.extractSize)) on the card" : "")")
                    .font(SofaFonts.text(13, .medium)).foregroundStyle(Color.soft)
                Text("From \(c.url.host ?? "?"), checked against the project's own SHA-256 list.")
                    .font(SofaFonts.text(12)).foregroundStyle(Color.mist)
            case .failed(let why):
                Text(why).foregroundStyle(Color.alert).fixedSize(horizontal: false, vertical: true)
                Button("Try Again") { model.findSystem() }.buttonStyle(SofaButtonStyle())
            }
        }
    }
}

/// Windows: an ISO the owner brings (Microsoft's own page has 10 and 11), what's in it, and the Windows 11 switches.
private struct WindowsPicker: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Button(model.windowsFile.url == nil ? "Choose ISO…" : "Choose Another…") { model.chooseFile(forWindows: true) }
                    .buttonStyle(SofaButtonStyle())
                    .disabled(model.isWriting)
                if let u = model.windowsFile.url {
                    Text(u.lastPathComponent).font(SofaFonts.text(13, .medium)).foregroundStyle(Color.soft)
                        .lineLimit(1).truncationMode(.middle)
                }
            }
            switch model.windowsFile {
            case .none:
                Text("Windows 7, 8.1, 10 or 11. Sofa Box Imager never downloads Windows: Microsoft's own pages have 10 and 11.")
                    .font(SofaFonts.text(13)).foregroundStyle(Color.mist).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 14) {
                    Link("Windows 11 from Microsoft", destination: ImagerModel.windows11Page)
                    Link("Windows 10 from Microsoft", destination: ImagerModel.windows10Page)
                }
                .font(SofaFonts.text(13, .medium))
            case .reading:
                HStack(spacing: 10) {
                    SofaProgress(fraction: nil).frame(width: 120)
                    Text("Reading the ISO…").foregroundStyle(Color.mist)
                }
            case .failed(_, let why):
                Text(why).foregroundStyle(Color.alert).fixedSize(horizontal: false, vertical: true)
            case .read(_, let kind, _):
                if case .windows(let w) = kind {
                    Text(w.summary).font(SofaFonts.text(13, .medium)).foregroundStyle(Color.soft)
                    if let why = w.refusal {
                        Text(why).foregroundStyle(Color.alert).fixedSize(horizontal: false, vertical: true)
                    } else {
                        Text(w.starts + (w.needsSplit ? " Its install.wim (\(ByteSize.text(w.installBytes))) is split into parts to fit FAT32." : ""))
                            .font(SofaFonts.text(12)).foregroundStyle(Color.mist).fixedSize(horizontal: false, vertical: true)
                        if w.version == .eleven { ElevenSwitches() }
                    }
                } else {
                    Text("This isn't a Windows installer ISO. \(kind.summary)")
                        .foregroundStyle(Color.alert).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

/// The two Windows 11 switches, each off unless ticked.
private struct ElevenSwitches: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SofaCheck(isOn: $model.skipHardwareChecks, label: "Skip the TPM 2.0, Secure Boot and 4 GB RAM checks")
            HStack(spacing: 10) {
                SofaCheck(isOn: $model.useLocalAccount, label: "A local account, no Microsoft account:")
                TextField("Name", text: $model.accountName)
                    .textFieldStyle(.plain)
                    .font(SofaFonts.text(13))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.slate2))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.line))
                    .frame(width: 150)
                    .disabled(!model.useLocalAccount)
            }
            if let why = model.optionsProblem {
                Text(why).font(SofaFonts.text(12)).foregroundStyle(Color.alert)
            } else if model.useLocalAccount {
                Text("It has no password at first: Windows signs it in once by itself, then asks for a new password at the next sign-in.")
                    .font(SofaFonts.text(12)).foregroundStyle(Color.mist).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.top, 2)
    }
}

/// Your own image: an ISO that's also a disk, a disk image, or a packed one (.img.xz).
private struct OwnFilePicker: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Button(model.ownFile.url == nil ? "Choose File…" : "Choose Another…") { model.chooseFile(forWindows: false) }
                    .buttonStyle(SofaButtonStyle())
                    .disabled(model.isWriting)
                if let u = model.ownFile.url {
                    Text(u.lastPathComponent).font(SofaFonts.text(13, .medium)).foregroundStyle(Color.soft)
                        .lineLimit(1).truncationMode(.middle)
                }
            }
            switch model.ownFile {
            case .none:
                Text("An .iso, an .img or an .img.xz, written to the disk whole.")
                    .font(SofaFonts.text(13)).foregroundStyle(Color.mist)
            case .reading:
                HStack(spacing: 10) {
                    SofaProgress(fraction: nil).frame(width: 120)
                    Text("Reading the file…").foregroundStyle(Color.mist)
                }
            case .failed(_, let why):
                Text(why).foregroundStyle(Color.alert).fixedSize(horizontal: false, vertical: true)
            case .read(let url, let kind, let bytes):
                if case .windows = kind {
                    Text("It's a Windows installer ISO, which needs a stick of its own making.")
                        .foregroundStyle(Color.soft).fixedSize(horizontal: false, vertical: true)
                    Button("Make a Windows Stick From It") {
                        model.mode = .windows
                        model.open(url, forWindows: true)
                    }
                    .buttonStyle(SofaButtonStyle())
                } else if kind.writtenWhole {
                    Text("\(kind.summary) \(ByteSize.text(bytes)).").font(SofaFonts.text(13, .medium))
                        .foregroundStyle(Color.soft).fixedSize(horizontal: false, vertical: true)
                } else {
                    Text(kind.summary).foregroundStyle(Color.alert).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

/// For a Raspberry Pi (an SD card), for a PC (a USB stick it starts from), or on a DVD (a disc a PC starts from): the
/// list's entries and the words follow it.
private struct TargetSwitch: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        HStack(spacing: 8) {
            ForEach(CardTarget.allCases) { t in
                let on = model.target == t
                Button { model.target = t } label: {
                    // A step below the row above it: smaller, and outlined rather than filled when chosen.
                    HStack(spacing: 6) {
                        Image(systemName: t.symbol).font(.system(size: 12, weight: .semibold))
                        Text(t.choice).font(SofaFonts.text(13, .semibold))
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .foregroundStyle(on ? Color.amber : Color.soft)
                    .background(Capsule().fill(on ? Color.slate3 : Color.slate2))
                    .overlay(Capsule().stroke(on ? Color.amber : Color.line))
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .disabled(model.isWriting)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
    }
}

private struct Step<Content: View>: View {
    let number: Int
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text("\(number)")
                .font(SofaFonts.display(15, .extraBold))
                .foregroundStyle(Color.amberInk)
                .frame(width: 26, height: 26)
                .background(Circle().fill(Color.amber))
            VStack(alignment: .leading, spacing: 10) {
                Text(title).font(SofaFonts.display(19, .bold)).tracking(-0.3)
                content
            }
        }
    }
}

private struct CardPicker: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        switch model.list {
        case .loading:
            HStack(spacing: 10) {
                SofaProgress(fraction: nil).frame(width: 120)
                Text("Getting the list of versions…").foregroundStyle(Color.mist)
            }
        case .failed(let text):
            VStack(alignment: .leading, spacing: 10) {
                Text(text).foregroundStyle(Color.alert).fixedSize(horizontal: false, vertical: true)
                Button("Try Again") { model.loadList() }.buttonStyle(SofaButtonStyle())
            }
        case .loaded(let list):
            VStack(alignment: .leading, spacing: 8) {
                // The pill is drawn here; the menu itself lies over it unseen, so none of its stock frame shows.
                HStack(spacing: 10) {
                    Text(model.card?.name ?? "Choose a version")
                        .font(SofaFonts.text(15, .semibold)).foregroundStyle(Color.paper)
                    if model.card != nil, model.card == list.newest { SofaPill(text: "Newest", color: .amber) }
                    Image(systemName: "chevron.up.chevron.down").font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color.mist)
                }
                .padding(.leading, 16)
                .padding(.trailing, 14)
                .padding(.vertical, 9)
                .background(Capsule().fill(Color.slate2))
                .overlay(Capsule().stroke(Color.line))
                .overlay {
                    Menu {
                        if let newest = list.newest {
                            Button(newest.name + " (newest)") { model.card = newest }
                        }
                        ForEach(list.others) { c in Button(c.name) { model.card = c } }
                        if !list.earlier.isEmpty {
                            Divider()
                            Section(list.earlierTitle) {
                                ForEach(list.earlier) { c in Button(c.name) { model.card = c } }
                            }
                        }
                    } label: {
                        Color.clear
                    }
                    .menuStyle(.borderlessButton)
                    .menuIndicator(.hidden)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .opacity(0.02)
                    .accessibilityLabel("Sofa Box OS version")
                }
                .fixedSize()
                if let c = model.card {
                    Text(details(c)).font(SofaFonts.text(13)).foregroundStyle(Color.mist)
                    if c.isTesting {
                        Text(model.target != .raspberryPi
                             ? "Testing: not tried on a real PC yet. Started on GitHub in virtual PCs, newer and older."
                             : "Testing: not tried on a real box yet. The version at the top is the one to keep.")
                            .font(SofaFonts.text(13)).foregroundStyle(Color.amber)
                    }
                }
                if model.listIsLocal {
                    Text("Using the list in \(model.listURL.path)").font(SofaFonts.text(11.5)).foregroundStyle(Color.mist)
                }
            }
        }
    }

    private func details(_ c: Card) -> String {
        var parts: [String] = []
        if let d = Self.day(c.releaseDate) { parts.append("Released \(d)") }
        parts.append("\(ByteSize.text(c.downloadSize)) download")
        parts.append("\(ByteSize.text(c.extractSize)) on the \(model.target.word)")
        return parts.joined(separator: " · ")
    }

    static func day(_ ymd: String) -> String? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")
        guard let d = f.date(from: ymd) else { return nil }
        let out = DateFormatter()
        out.dateStyle = .long
        out.timeStyle = .none
        out.timeZone = TimeZone(identifier: "UTC")
        return out.string(from: d)
    }
}

private struct DiskPicker: View {
    @EnvironmentObject var model: ImagerModel
    @State private var showRefused = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.offered.isEmpty {
                Panel {
                    HStack(spacing: 12) {
                        Image(systemName: model.symbol).font(.system(size: 22)).foregroundStyle(Color.mist)
                        Text(model.word == "card"
                             ? "Put the SD card in: a USB card reader, or the Mac's own SD slot. It shows here by itself."
                             : model.word == "stick"
                             ? "Put the USB stick in\(model.item.map { " (\(ByteSize.text($0.needs)) or more)" } ?? ""). It shows here by itself."
                             : "Put the USB stick or the SD card in. It shows here by itself.")
                            .foregroundStyle(Color.soft)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                    .padding(16)
                }
            } else {
                VStack(spacing: 8) {
                    ForEach(model.offered, id: \.bsdName) { d in
                        DiskRow(disk: d, chosen: d.bsdName == model.diskName, symbol: model.symbol + ".fill") {
                            model.diskName = d.bsdName
                        }
                    }
                }
            }
            Text("Only removable and external disks of \(ByteSize.text(DiskPolicy.largestDisk)) or less are shown. Never the Mac's own disks or disk images.")
                .font(SofaFonts.text(12))
                .foregroundStyle(Color.mist)
                .fixedSize(horizontal: false, vertical: true)
            if !model.refused.isEmpty {
                Button { withAnimation(.easeOut(duration: 0.15)) { showRefused.toggle() } } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.right").font(.system(size: 10, weight: .bold))
                            .rotationEffect(.degrees(showRefused ? 90 : 0))
                        Text("Not shown (\(model.refused.count))").font(SofaFonts.text(13, .medium))
                    }
                    .foregroundStyle(Color.soft)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                if showRefused {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(model.refused, id: \.0.bsdName) { d, why in
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(d.displayName) · \(ByteSize.text(d.sizeBytes))").font(SofaFonts.text(13, .medium))
                                Text(why.map(\.text).joined(separator: " "))
                                    .font(SofaFonts.text(12)).foregroundStyle(Color.mist)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .padding(.leading, 16)
                }
            }
        }
    }
}

/// On a DVD: the Mac's burners, each with the disc in it. Only one with a blank DVD big enough can be chosen.
private struct BurnerPicker: View {
    @EnvironmentObject var model: ImagerModel

    var body: some View {
        let needs = model.card?.extractSize ?? 1
        VStack(alignment: .leading, spacing: 10) {
            if model.burners.isEmpty {
                Panel {
                    HStack(spacing: 12) {
                        Image(systemName: "opticaldiscdrive").font(.system(size: 22)).foregroundStyle(Color.mist)
                        Text("Plug in a DVD burner (Apple's USB SuperDrive, or any USB DVD writer) and put a blank DVD-R or DVD+R in. It shows here by itself.")
                            .foregroundStyle(Color.soft)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                    .padding(16)
                }
            } else {
                VStack(spacing: 8) {
                    ForEach(model.burners) { b in
                        let ready = b.refusal(needs: needs) == nil
                        Button { if ready { model.burnerID = b.id } } label: {
                            Panel(ring: b.id == model.burnerID && ready ? .amber : nil) {
                                HStack(spacing: 12) {
                                    Image(systemName: "opticaldiscdrive.fill")
                                        .font(.system(size: 20))
                                        .foregroundStyle(b.id == model.burnerID && ready ? Color.amber : Color.mist)
                                        .frame(width: 28)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(b.name).font(SofaFonts.text(15, .semibold))
                                        Text(b.subtitle(needs: needs)).font(SofaFonts.text(12)).foregroundStyle(Color.mist)
                                            .fixedSize(horizontal: false, vertical: true)
                                    }
                                    Spacer()
                                }
                                .padding(12)
                            }
                            .opacity(ready ? 1 : 0.6)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(!ready)
                    }
                }
            }
            Text("Only a blank DVD is burned: Sofa Box Imager never erases a disc.")
                .font(SofaFonts.text(12))
                .foregroundStyle(Color.mist)
        }
    }
}

private struct DiskRow: View {
    let disk: DiskDescription
    let chosen: Bool
    var symbol = "sdcard.fill"
    let choose: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: choose) {
            Panel(ring: chosen ? .amber : (hover ? Color.paper.opacity(0.25) : nil)) {
                HStack(spacing: 12) {
                    Image(systemName: symbol)
                        .font(.system(size: 20))
                        .foregroundStyle(chosen ? Color.amber : Color.mist)
                        .frame(width: 28)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(disk.displayName).font(SofaFonts.text(15, .semibold))
                        Text(subtitle).font(SofaFonts.text(12)).foregroundStyle(Color.mist)
                    }
                    Spacer()
                    Text(ByteSize.text(disk.sizeBytes)).font(SofaFonts.text(14, .semibold)).monospacedDigit()
                        .foregroundStyle(Color.soft)
                    Image(systemName: chosen ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: 18))
                        .foregroundStyle(chosen ? Color.amber : Color.mist.opacity(0.6))
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .contentShape(RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityAddTraits(chosen ? .isSelected : [])
    }

    private var subtitle: String {
        var parts: [String] = []
        if !disk.displayModel.isEmpty && disk.displayModel != disk.displayName { parts.append(disk.displayModel) }
        if let p = disk.protocolName { parts.append(p) }
        let vols = disk.volumes.map(\.name).filter { !$0.isEmpty }
        if !vols.isEmpty { parts.append("holds " + vols.joined(separator: ", ")) }
        parts.append(disk.bsdName)
        return parts.joined(separator: " · ")
    }
}

// MARK: confirming

struct ConfirmView: View {
    @EnvironmentObject var model: ImagerModel
    @State private var sure = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if model.burns {
                burnBody
            } else if let d = model.chosenDisk, let c = model.item {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 22)).foregroundStyle(Color.alert)
                    Text("Erase “\(d.displayName)” and write \(c.name)?")
                        .font(SofaFonts.display(20, .bold)).tracking(-0.3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Panel {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 7) {
                        row(model.word.prefix(1).uppercased() + model.word.dropFirst(), d.displayName)
                        if !d.displayModel.isEmpty && d.displayModel != d.displayName { row("In", d.displayModel) }
                        if let how = d.protocolName, !how.isEmpty { row("Connected by", how) }
                        row("Size", ByteSize.text(d.sizeBytes))
                        row("Device", "/dev/\(d.bsdName)")
                        row("On it now", d.volumes.isEmpty ? "No volumes mounted from it"
                            : d.volumes.map(\.name).joined(separator: ", "))
                        if model.mode == .windows, !model.windowsOptions.isEmpty {
                            row("Windows 11", [model.windowsOptions.skipHardwareChecks ? "TPM, Secure Boot and RAM checks skipped" : nil,
                                               model.windowsOptions.localAccount.map { "local account “\($0)”" }]
                                .compactMap { $0 }.joined(separator: "; "))
                        }
                    }
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                Text("Everything on this \(model.word) will be erased. This can't be undone. macOS will ask for your password next.")
                    .foregroundStyle(Color.soft)
                    .fixedSize(horizontal: false, vertical: true)
                SofaCheck(isOn: $sure, label: "This is the \(model.word) I want to erase")
                HStack(spacing: 10) {
                    Spacer()
                    Button("Cancel") { model.confirming = false }
                        .buttonStyle(SofaButtonStyle())
                        .keyboardShortcut(.cancelAction)
                    Button("Erase and Write") { model.write() }
                        .buttonStyle(SofaButtonStyle(kind: .danger))
                        .disabled(!sure)
                }
            } else {
                Text("The \(model.word) isn't there any more.")
                HStack { Spacer(); Button("OK") { model.confirming = false }.buttonStyle(SofaButtonStyle()) }
            }
        }
        .padding(24)
        .frame(width: 480)
        .background(Color.ink)
        .foregroundStyle(Color.paper)
        .font(SofaFonts.text(14))
        .preferredColorScheme(.dark)
    }

    /// On a DVD: nothing is erased (only a blank disc is offered), so no password and no second box to tick.
    @ViewBuilder private var burnBody: some View {
        if let b = model.chosenBurner, let c = model.card {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "opticaldiscdrive.fill").font(.system(size: 22)).foregroundStyle(Color.amber)
                Text("Burn \(c.name) to the DVD in “\(b.name)”?")
                    .font(SofaFonts.display(20, .bold)).tracking(-0.3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Panel {
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 7) {
                    row("Burner", b.name)
                    row("Disc", b.subtitle(needs: c.extractSize))
                    row("Download", ByteSize.text(c.downloadSize))
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Text("Sofa Box Imager downloads it, checks it against the list, burns it, and reads the disc back to check it. A DVD-R or DVD+R is burned once.")
                .foregroundStyle(Color.soft)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 10) {
                Spacer()
                Button("Cancel") { model.confirming = false }
                    .buttonStyle(SofaButtonStyle())
                    .keyboardShortcut(.cancelAction)
                Button("Burn") { model.write() }
                    .buttonStyle(SofaButtonStyle(kind: .primary))
                    .keyboardShortcut(.defaultAction)
            }
        } else {
            Text("The DVD burner or its disc isn't there any more.")
            HStack { Spacer(); Button("OK") { model.confirming = false }.buttonStyle(SofaButtonStyle()) }
        }
    }

    private func row(_ name: String, _ value: String) -> some View {
        GridRow {
            Text(name).foregroundStyle(Color.mist)
            Text(value).font(SofaFonts.text(14, .medium)).textSelection(.enabled)
        }
    }
}

// MARK: running and after

private struct RunningView: View {
    @EnvironmentObject var model: ImagerModel
    let text: String
    let fraction: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Panel {
                VStack(alignment: .leading, spacing: 14) {
                    Text(model.jobTitle.isEmpty ? (model.burns ? "Burning the DVD" : "Writing the \(model.word)") : model.jobTitle)
                        .font(SofaFonts.display(19, .bold)).tracking(-0.3)
                        .fixedSize(horizontal: false, vertical: true)
                    SofaProgress(fraction: fraction)
                    Text(text).font(SofaFonts.text(14, .medium)).foregroundStyle(Color.soft).monospacedDigit()
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Text("Leave the \(model.word) in until Sofa Box Imager says it's done.").foregroundStyle(Color.mist)
            Spacer(minLength: 0)
            HStack {
                Spacer()
                Button("Stop") { model.cancel() }.buttonStyle(SofaButtonStyle())
            }
        }
    }
}

private struct DoneView: View {
    @EnvironmentObject var model: ImagerModel
    let card: String
    let disk: String

    private var windowsNext: String {
        let seven = model.windowsMedia?.version == .seven
        return "Put the stick in the PC and start the PC from it: as it starts, press its start menu key (often F12, F11, F10, F8 or Esc). "
            + (seven ? "Windows 7 needs the PC's legacy boot (CSM) on and Secure Boot off. " : "")
            + "Windows Setup starts, and asks which drive to install Windows on."
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Panel {
                VStack(alignment: .leading, spacing: 12) {
                    SofaPill(text: model.burns ? "Burned, checked and ejected" : "Checked and ejected")
                    Text(model.burns ? "The DVD is ready" : "The \(model.word) is ready")
                        .font(SofaFonts.display(26, .extraBold)).tracking(-0.6)
                    Text(model.burns ? "\(card) is on the DVD from “\(disk)”, and the disc was read back and checked."
                         : "\(card) is on “\(disk)”, and every byte was read back and checked.")
                        .foregroundStyle(Color.soft)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Text(model.mode == .windows ? windowsNext
                 : model.mode == .linux ? (model.word == "card"
                    ? "Take the card out and put it in the Pi, then plug the Pi into its power. Raspberry Pi OS sets itself up on its first start."
                    : "Take the stick out and put it in the PC. Start the PC from the stick: as it starts, press its start menu key (often F12, F11, F10, F8 or Esc). If it doesn't start, turn Secure Boot off in the PC's settings and try again.")
                 : model.mode == .file ? "Take the disk out and put it where it goes."
                 : model.target == .dvd
                 ? "Put the DVD in the PC, plugged into the TV, and start the PC from the disc: as it starts, press its start menu key (often F12, F11, F10, F8 or Esc). Sofa Box OS runs from the disc and sets itself up on the TV; what's set up is kept until the PC restarts. To keep it: Settings → This box → Install on this computer."
                 : model.target == .pc
                 ? "Take the stick out and put it in the PC, plugged into the TV. Start the PC from the stick: as it starts, press its start menu key (often F12, F11, F10, F8 or Esc; on a Mac with an Intel chip, hold Option). Sofa Box OS runs from the stick and sets itself up on the TV."
                 : "Take the card out and put it in the Pi. Plug the Pi into the TV, then into its power. The box sets itself up on the TV.")
                .foregroundStyle(Color.soft)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            HStack {
                Spacer()
                Button(model.burns ? "Burn Another DVD" : "Write Another \(model.word.prefix(1).uppercased() + model.word.dropFirst())") { model.reset() }
                    .buttonStyle(SofaButtonStyle(kind: .primary))
                    .keyboardShortcut(.defaultAction)
            }
        }
    }
}

private struct FailedView: View {
    @EnvironmentObject var model: ImagerModel
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Panel {
                VStack(alignment: .leading, spacing: 12) {
                    SofaPill(text: model.burns ? "Not burned" : "Not written", color: .alert)
                    Text(model.burns ? "The DVD wasn't burned" : "The \(model.word) wasn't written")
                        .font(SofaFonts.display(26, .extraBold)).tracking(-0.6)
                    Text(text).foregroundStyle(Color.soft)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer(minLength: 0)
            HStack {
                Spacer()
                Button("OK") { model.reset() }
                    .buttonStyle(SofaButtonStyle(kind: .primary))
                    .keyboardShortcut(.defaultAction)
            }
        }
    }
}
