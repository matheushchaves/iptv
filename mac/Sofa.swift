// A casca do Sofá no Mac: o ícone na barra e a janela só mostram a página do vigia, que é quem sabe de tudo.
// Compilar: instalar-mac.sh. Com --barra, abre só o ícone (é assim que ele sobe no login).
import AppKit
import WebKit

let statusPage = URL(string: "http://127.0.0.1:8010/")!
let statusAPI = URL(string: "http://127.0.0.1:8010/api/status")!
let refreshSeconds: TimeInterval = 3
let requestSeconds: TimeInterval = 2
let vigiaGone = "Vigia fora do ar"
let vigiaGonePage = """
    <!doctype html><meta charset="utf-8"><body style="margin:0;padding:24px;background:#17121c;color:#f3ece4;
    font:18px system-ui"><b>Vigia fora do ar</b><p style="color:#a99cb5">Se ele não voltar sozinho, rode o
    instalar-mac.sh de novo.</p>
    """

struct Status: Decodable {
    let color: String
    let title: String
}

@MainActor
final class Shell: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let popover = NSPopover()
    private let popoverPage = NSViewController()
    private var window: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        setUpIcon()
        popoverPage.view = makeWebView()
        popover.contentViewController = popoverPage
        popover.contentSize = NSSize(width: 380, height: 560)
        popover.behavior = .transient
        Timer.scheduledTimer(withTimeInterval: refreshSeconds, repeats: true) { [weak self] _ in
            Task { await self?.refresh() }
        }
        Task { await refresh() }
        if !CommandLine.arguments.contains("--barra") {
            showWindow()
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return false
    }

    private func setUpIcon() {
        guard let button = item.button else { return }
        if let image = NSImage(systemSymbolName: "sofa.fill", accessibilityDescription: "Sofá") {
            image.isTemplate = true
            button.image = image
        } else {
            button.title = "Sofá"
        }
        button.target = self
        button.action = #selector(clicked)
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
    }

    private func tint(for color: String) -> NSColor? {
        switch color {
        case "green": return .systemGreen
        case "yellow": return .systemYellow
        case "red": return .systemRed
        default: return nil
        }
    }

    private func paint(color: String, title: String) {
        item.button?.contentTintColor = tint(for: color)
        item.button?.toolTip = title
    }

    private func refresh() async {
        do {
            let request = URLRequest(url: statusAPI, timeoutInterval: requestSeconds)
            let (data, _) = try await URLSession.shared.data(for: request)
            let status = try JSONDecoder().decode(Status.self, from: data)
            paint(color: status.color, title: status.title)
        } catch {
            paint(color: "red", title: vigiaGone)
        }
    }

    @objc private func clicked(_ sender: NSStatusBarButton) {
        if NSApp.currentEvent?.type == .rightMouseUp {
            showMenu()
        } else if popover.isShown {
            popover.performClose(sender)
        } else {
            load(popoverPage.view)
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
        }
    }

    private func showMenu() {
        let menu = NSMenu()
        menu.addItem(withTitle: "Abrir janela", action: #selector(openWindow), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Sair", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "")
        item.menu = menu
        item.button?.performClick(nil)
        item.menu = nil
    }

    @objc private func openWindow() {
        showWindow()
    }

    private func showWindow() {
        if window == nil {
            let created = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 640),
                                   styleMask: [.titled, .closable, .miniaturizable, .resizable],
                                   backing: .buffered, defer: false)
            created.title = "Sofá"
            created.isReleasedWhenClosed = false
            created.contentView = makeWebView()
            created.center()
            window = created
        }
        if let page = window?.contentView {
            load(page)
        }
        if #available(macOS 14, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
        window?.makeKeyAndOrderFront(nil)
    }

    private func makeWebView() -> WKWebView {
        let view = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        view.uiDelegate = self
        view.navigationDelegate = self
        return view
    }

    private func load(_ view: NSView) {
        (view as? WKWebView)?.load(URLRequest(url: statusPage))
    }

    // "Abrir o Sofá" abre em outra aba: sem isto, o clique não faria nada dentro do WKWebView
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        webView.loadHTMLString(vigiaGonePage, baseURL: nil)
    }
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let shell = Shell()
    app.delegate = shell
    app.setActivationPolicy(.accessory)
    withExtendedLifetime(shell) { app.run() }  // app.delegate é fraco
}
