import AppKit
import CryptoKit

/// Draws icons with AppKit, so letter icons need no Pillow (session 585's icon troubles all came
/// from the python fallback). Shapes follow the macOS app icon grid: a rounded square inset in
/// the canvas, so baked apps sit at the same size as other apps in the Dock.
enum IconRenderer {
    /// The colour the old installer gave a name (sha256 of the name picks the hue), kept so
    /// re-baked apps keep their colour.
    static func color(for name: String) -> NSColor {
        let digest = Array(SHA256.hash(data: Data(name.utf8)))
        let value = (Int(digest[29]) << 8) | Int(digest[30])
        return NSColor(calibratedHue: CGFloat(value) / 65535.0, saturation: 0.62, brightness: 0.86, alpha: 1)
    }

    static func bitmap(size: Int, draw: (CGRect) -> Void) -> NSBitmapImageRep? {
        guard let rep = NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
            samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
            bytesPerRow: 0, bitsPerPixel: 0)
        else { return nil }
        rep.size = NSSize(width: size, height: size)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        draw(CGRect(x: 0, y: 0, width: size, height: size))
        NSGraphicsContext.restoreGraphicsState()
        return rep
    }

    static func write(_ rep: NSBitmapImageRep?, to path: String) -> Bool {
        guard let data = rep?.representation(using: .png, properties: [:]) else { return false }
        do {
            try data.write(to: URL(fileURLWithPath: path))
            return true
        } catch {
            return false
        }
    }

    /// The rounded square body, with a soft top-to-bottom gradient of `base`.
    static func drawBody(in canvas: CGRect, base: NSColor) -> CGRect {
        let side = canvas.width * 0.8125
        let body = CGRect(x: canvas.midX - side / 2, y: canvas.midY - side / 2, width: side, height: side)
        let path = NSBezierPath(roundedRect: body, xRadius: side * 0.225, yRadius: side * 0.225)
        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.25)
        shadow.shadowBlurRadius = canvas.width * 0.02
        shadow.shadowOffset = NSSize(width: 0, height: -canvas.width * 0.01)
        NSGraphicsContext.saveGraphicsState()
        shadow.set()
        base.setFill()
        path.fill()
        NSGraphicsContext.restoreGraphicsState()
        let top = base.blended(withFraction: 0.25, of: .white) ?? base
        let bottom = base.blended(withFraction: 0.15, of: .black) ?? base
        NSGradient(starting: top, ending: bottom)?.draw(in: path, angle: -90)
        return body
    }

    static func renderLetterIcon(to path: String, name: String) -> Bool {
        let letter = name.first(where: { $0.isLetter || $0.isNumber }).map { String($0).uppercased() } ?? "A"
        let rep = bitmap(size: 1024) { canvas in
            let body = drawBody(in: canvas, base: color(for: name))
            let font = NSFont.systemFont(ofSize: body.height * 0.56, weight: .semibold)
            let text = NSAttributedString(string: letter, attributes: [.font: font, .foregroundColor: NSColor.white])
            let size = text.size()
            // Centre on the cap height rather than the line box, so letters sit optically centred.
            let y = body.midY - (font.capHeight / 2) + font.descender
            text.draw(at: CGPoint(x: body.midX - size.width / 2, y: y))
        }
        return write(rep, to: path)
    }

    static func symbol(_ names: [String], pointSize: CGFloat) -> NSImage? {
        for name in names {
            if let image = NSImage(systemSymbolName: name, accessibilityDescription: nil)?
                .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: pointSize, weight: .semibold)) {
                return image
            }
        }
        return nil
    }

    static func drawAppIcon(in canvas: CGRect) {
        let base = NSColor(calibratedRed: 0.93, green: 0.45, blue: 0.20, alpha: 1)
        let body = drawBody(in: canvas, base: base)
        guard let glyph = symbol(["macwindow.badge.plus", "macwindow"], pointSize: body.height * 0.5) else { return }
        let fit = body.insetBy(dx: body.width * 0.2, dy: body.height * 0.2)
        let scale = min(fit.width / glyph.size.width, fit.height / glyph.size.height)
        let size = NSSize(width: glyph.size.width * scale, height: glyph.size.height * scale)
        let white = NSImage(size: size, flipped: false) { rect in
            glyph.draw(in: rect)
            NSColor.white.set()
            rect.fill(using: .sourceAtop)
            return true
        }
        white.draw(in: CGRect(x: body.midX - size.width / 2, y: body.midY - size.height / 2, width: size.width, height: size.height))
    }

    static func renderAppIconSet(into dir: String) -> Bool {
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        var ok = true
        for base in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let suffix = scale == 2 ? "@2x" : ""
                let file = "\(dir)/icon_\(base)x\(base)\(suffix).png"
                ok = write(bitmap(size: base * scale, draw: drawAppIcon), to: file) && ok
            }
        }
        return ok
    }
}
