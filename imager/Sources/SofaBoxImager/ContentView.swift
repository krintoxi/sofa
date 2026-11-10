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
        .frame(minWidth: 600, idealWidth: 640, minHeight: 580, idealHeight: 620)
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
                Text("Writes Sofa Box OS to an SD card for a Raspberry Pi 3 B+, 4 or 5.")
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
        VStack(alignment: .leading, spacing: 22) {
            Step(number: 1, title: "Sofa Box OS") { CardPicker() }
            Step(number: 2, title: "The card to erase") { DiskPicker() }
            Spacer(minLength: 0)
            HStack(alignment: .center) {
                Text("Nothing is set on the card: the box sets itself up on the TV.")
                    .font(SofaFonts.text(13))
                    .foregroundStyle(Color.mist)
                Spacer()
                Button("Write…") { model.askToWrite() }
                    .buttonStyle(SofaButtonStyle(kind: .primary))
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.card == nil || model.chosenDisk == nil)
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
                        Text("A testing build: for trying fixes early. The numbered version is the one to keep.")
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
        parts.append("\(ByteSize.text(c.extractSize)) on the card")
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
                        Image(systemName: "sdcard").font(.system(size: 22)).foregroundStyle(Color.mist)
                        Text("Put the SD card in: a USB card reader, or the Mac's own SD slot. It shows here by itself.")
                            .foregroundStyle(Color.soft)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                    .padding(16)
                }
            } else {
                VStack(spacing: 8) {
                    ForEach(model.offered, id: \.bsdName) { d in
                        DiskRow(disk: d, chosen: d.bsdName == model.diskName) { model.diskName = d.bsdName }
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

private struct DiskRow: View {
    let disk: DiskDescription
    let chosen: Bool
    let choose: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: choose) {
            Panel(ring: chosen ? .amber : (hover ? Color.paper.opacity(0.25) : nil)) {
                HStack(spacing: 12) {
                    Image(systemName: "sdcard.fill")
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
            if let d = model.chosenDisk, let c = model.card {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 22)).foregroundStyle(Color.alert)
                    Text("Erase “\(d.displayName)” and write \(c.name)?")
                        .font(SofaFonts.display(20, .bold)).tracking(-0.3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Panel {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 7) {
                        row("Card", d.displayName)
                        if !d.displayModel.isEmpty && d.displayModel != d.displayName { row("In", d.displayModel) }
                        if let how = d.protocolName, !how.isEmpty { row("Connected by", how) }
                        row("Size", ByteSize.text(d.sizeBytes))
                        row("Device", "/dev/\(d.bsdName)")
                        row("On it now", d.volumes.isEmpty ? "No volumes mounted from it"
                            : d.volumes.map(\.name).joined(separator: ", "))
                    }
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                Text("Everything on this card will be erased. This can't be undone. macOS will ask for your password next.")
                    .foregroundStyle(Color.soft)
                    .fixedSize(horizontal: false, vertical: true)
                SofaCheck(isOn: $sure, label: "This is the card I want to erase")
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
                Text("The card isn't there any more.")
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
                    Text(model.jobTitle.isEmpty ? "Writing the card" : model.jobTitle)
                        .font(SofaFonts.display(19, .bold)).tracking(-0.3)
                        .fixedSize(horizontal: false, vertical: true)
                    SofaProgress(fraction: fraction)
                    Text(text).font(SofaFonts.text(14, .medium)).foregroundStyle(Color.soft).monospacedDigit()
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Text("Leave the card in until Sofa Box Imager says it's done.").foregroundStyle(Color.mist)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Panel {
                VStack(alignment: .leading, spacing: 12) {
                    SofaPill(text: "Checked and ejected")
                    Text("The card is ready").font(SofaFonts.display(26, .extraBold)).tracking(-0.6)
                    Text("\(card) is on “\(disk)”, and every byte was read back and checked.")
                        .foregroundStyle(Color.soft)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            Text("Take the card out and put it in the Pi. Plug the Pi into the TV, then into its power. The box sets itself up on the TV.")
                .foregroundStyle(Color.soft)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            HStack {
                Spacer()
                Button("Write Another Card") { model.reset() }
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
                    SofaPill(text: "Not written", color: .alert)
                    Text("The card wasn't written").font(SofaFonts.display(26, .extraBold)).tracking(-0.6)
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
