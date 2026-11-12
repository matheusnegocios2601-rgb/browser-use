#if os(iOS)
import GarfadaCore
import SwiftUI

enum Palette {
	/// #14160F
	static let ink = Color(red: 0.078, green: 0.086, blue: 0.059)
	/// #FF5A36
	static let pepper = Color(red: 1.0, green: 0.353, blue: 0.212)
	/// #D4F25A
	static let lime = Color(red: 0.831, green: 0.949, blue: 0.353)
	/// #F6EFE3
	static let cream = Color(red: 0.965, green: 0.937, blue: 0.890)
	/// #FFB23F
	static let amber = Color(red: 1.0, green: 0.698, blue: 0.247)
	static let card = Color.white.opacity(0.07)

	static func color(for verdict: HealthAssessment.Verdict) -> Color {
		switch verdict {
		case .good: lime
		case .ok: cream
		case .moderation: amber
		case .avoid: pepper
		}
	}
}

enum Format {
	static func number(_ value: Double?, decimals: Int = 0, unit: String = "") -> String {
		guard let value else { return "—" }
		let formatted = value.formatted(.number.precision(.fractionLength(decimals)).locale(Locale(identifier: "pt_BR")))
		return unit.isEmpty ? formatted : "\(formatted) \(unit)"
	}

	static func percent(_ value: Double) -> String {
		"\(Int((value * 100).rounded()))%"
	}
}

/// Logo desenhado em código (mesmo desenho de Design/logo.svg, grade 1024).
struct LogoMark: View {
	var background = true

	var body: some View {
		Canvas { ctx, size in
			let s = min(size.width, size.height) / 1024
			func rect(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> CGRect {
				CGRect(x: x * s, y: y * s, width: w * s, height: h * s)
			}
			func circle(_ cx: CGFloat, _ cy: CGFloat, _ r: CGFloat) -> Path {
				Path(ellipseIn: rect(cx - r, cy - r, 2 * r, 2 * r))
			}
			if background {
				ctx.fill(Path(roundedRect: rect(0, 0, 1024, 1024), cornerRadius: 230 * s), with: .color(Palette.ink))
			}
			// Mira
			let style = StrokeStyle(lineWidth: 44 * s, lineCap: .round, lineJoin: .round)
			let corners: [([CGPoint], Double)] = [
				([.init(x: 150, y: 290), .init(x: 150, y: 150), .init(x: 290, y: 150)], 1),
				([.init(x: 734, y: 150), .init(x: 874, y: 150), .init(x: 874, y: 290)], 0.35),
				([.init(x: 150, y: 734), .init(x: 150, y: 874), .init(x: 290, y: 874)], 1),
				([.init(x: 874, y: 734), .init(x: 874, y: 874), .init(x: 734, y: 874)], 1),
			]
			for (points, opacity) in corners {
				var p = Path()
				p.addLines(points.map { CGPoint(x: $0.x * s, y: $0.y * s) })
				ctx.stroke(p, with: .color(Palette.lime.opacity(opacity)), style: style)
			}
			// Bocado com mordida
			ctx.drawLayer { layer in
				layer.fill(circle(500, 540, 300), with: .color(Palette.pepper))
				layer.blendMode = .destinationOut
				layer.fill(circle(790, 330, 118), with: .color(.black))
				layer.fill(circle(700, 232, 84), with: .color(.black))
				layer.fill(circle(862, 452, 84), with: .color(.black))
			}
			// Garfo
			let cream = GraphicsContext.Shading.color(Palette.cream)
			ctx.fill(Path(roundedRect: rect(398, 350, 40, 190), cornerRadius: 20 * s), with: cream)
			ctx.fill(Path(roundedRect: rect(480, 330, 40, 210), cornerRadius: 20 * s), with: cream)
			ctx.fill(Path(roundedRect: rect(562, 350, 40, 190), cornerRadius: 20 * s), with: cream)
			var base = Path()
			base.move(to: CGPoint(x: 398 * s, y: 520 * s))
			base.addLine(to: CGPoint(x: 602 * s, y: 520 * s))
			base.addLine(to: CGPoint(x: 602 * s, y: 540 * s))
			base.addQuadCurve(to: CGPoint(x: 500 * s, y: 652 * s), control: CGPoint(x: 602 * s, y: 640 * s))
			base.addQuadCurve(to: CGPoint(x: 398 * s, y: 540 * s), control: CGPoint(x: 398 * s, y: 640 * s))
			base.closeSubpath()
			ctx.fill(base, with: cream)
			ctx.fill(Path(roundedRect: rect(480, 600, 40, 176), cornerRadius: 20 * s), with: cream)
		}
		.aspectRatio(1, contentMode: .fit)
		.accessibilityLabel("Logo do Garfada")
	}
}

struct Wordmark: View {
	var body: some View {
		HStack(spacing: 8) {
			LogoMark(background: false)
				.frame(width: 30, height: 30)
			Text("garfada")
				.font(.system(size: 26, weight: .black, design: .rounded))
				.foregroundStyle(Palette.cream)
		}
	}
}

struct Card<Content: View>: View {
	@ViewBuilder var content: Content

	var body: some View {
		VStack(alignment: .leading, spacing: 10) { content }
			.frame(maxWidth: .infinity, alignment: .leading)
			.padding(16)
			.background(Palette.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
	}
}
#endif
