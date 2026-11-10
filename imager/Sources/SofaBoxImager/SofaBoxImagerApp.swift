import AppKit
import SwiftUI

/// `--versions` and `--disks` print what the app would show and exit, without a window (for checking a build, and for
/// "why isn't my card offered?"). They read only. Anything else opens the app.
@main
enum Main {
    static func main() {
        let args = CommandLine.arguments
        if args.contains("--versions") || args.contains("--disks") {
            exit(Report.run(versions: args.contains("--versions"), disks: args.contains("--disks")))
        }
        SofaBoxImagerApp.main()
    }
}

/// Sofa Box Imager: one window, one path. Pick the version, pick the card, confirm, write, check, eject.
struct SofaBoxImagerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = ImagerModel()

    var body: some Scene {
        Window("Sofa Box Imager", id: "main") {
            ContentView()
                .environmentObject(model)
                .tint(Color.amber)
                .onAppear { delegate.model = model }
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(replacing: .help) {
                Button("Sofa Box Guide") {
                    NSWorkspace.shared.open(URL(string: "https://github.com/krintoxi/sofa/blob/main/deploy/sofa-box/README.md")!)
                }
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: ImagerModel?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Run straight from `swift run` (no bundle), it would otherwise have no Dock icon or menu bar.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    /// Quitting mid-write leaves a blank card: ask first.
    @MainActor
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model, model.isWriting else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "A card is being written"
        alert.informativeText = "If you quit now, the card is left blank and needs writing again."
        alert.addButton(withTitle: "Keep Writing")
        alert.addButton(withTitle: "Stop and Quit")
        alert.alertStyle = .warning
        guard alert.runModal() == .alertSecondButtonReturn else { return .terminateCancel }
        model.cancel()
        // Give the writer a moment to blank the card's first megabyte.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
}
