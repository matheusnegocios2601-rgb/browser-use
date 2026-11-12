#if os(iOS)
import GarfadaCore
import SwiftUI

struct CameraScreen: View {
	let database: FoodDatabase
	@Environment(AppStore.self) private var store
	@State private var camera: CameraModel
	@State private var selected: Detection?
	@State private var showAbout = false

	init(database: FoodDatabase) {
		self.database = database
		_camera = State(initialValue: CameraModel(database: database))
	}

	var body: some View {
		ZStack {
			Palette.ink.ignoresSafeArea()
			if camera.status == .running {
				CameraPreview(session: camera.session).ignoresSafeArea()
				Viewfinder(active: !camera.detections.isEmpty)
					.padding(.horizontal, 40)
					.padding(.vertical, 140)
					.allowsHitTesting(false)
			}
			VStack(spacing: 0) {
				header
				Spacer()
				switch camera.status {
				case .running, .idle:
					panel
				case .unauthorized:
					permissionMessage
				case .unavailable:
					ContentUnavailableView("Câmera indisponível", systemImage: "camera.badge.ellipsis")
				}
			}
		}
		.task { await camera.start() }
		.onDisappear { camera.stop() }
		.sheet(item: $selected) { detection in
			NavigationStack { DetectionScreen(database: database, detection: detection) }
				.environment(store)
				.presentationDetents([.large])
		}
		.sheet(isPresented: $showAbout) { AboutScreen() }
	}

	private var header: some View {
		HStack {
			Wordmark()
			Spacer()
			Button { showAbout = true } label: {
				Image(systemName: "info.circle").font(.title2)
			}
			.accessibilityLabel("Sobre o Garfada")
		}
		.padding(.horizontal, 20)
		.padding(.vertical, 10)
		.background(.ultraThinMaterial)
	}

	private var panel: some View {
		VStack(alignment: .leading, spacing: 10) {
			HStack {
				Text(camera.detections.isEmpty ? "Aponte para a comida" : "Estou vendo")
					.font(.headline)
				Spacer()
				Button {
					camera.isFrozen.toggle()
				} label: {
					Label(camera.isFrozen ? "Retomar" : "Congelar", systemImage: camera.isFrozen ? "play.fill" : "pause.fill")
						.font(.subheadline.weight(.semibold))
				}
				.buttonStyle(.bordered)
			}
			if camera.detections.isEmpty {
				Text("Analiso a imagem ao vivo, aqui no iPhone. Nenhuma foto é salva ou enviada.")
					.font(.footnote)
					.foregroundStyle(.secondary)
			}
			ForEach(camera.detections) { detection in
				Button { selected = detection } label: { DetectionRow(detection: detection) }
					.buttonStyle(.plain)
			}
		}
		.padding(16)
		.background(.regularMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
		.padding(.horizontal, 12)
		.padding(.bottom, 8)
		.animation(.snappy, value: camera.detections.map(\.label))
	}

	private var permissionMessage: some View {
		Card {
			Text("O Garfada precisa da câmera").font(.headline)
			Text("A análise acontece só no seu iPhone. Ative em Ajustes > Garfada > Câmera.")
				.foregroundStyle(.secondary)
			Button("Abrir Ajustes") {
				if let url = URL(string: UIApplication.openSettingsURLString) {
					UIApplication.shared.open(url)
				}
			}
			.buttonStyle(.borderedProminent)
		}
		.padding()
	}
}

private struct DetectionRow: View {
	let detection: Detection

	var body: some View {
		HStack(spacing: 12) {
			VStack(alignment: .leading, spacing: 4) {
				Text(detection.name).font(.body.weight(.semibold))
				HStack(spacing: 6) {
					badge
					Text("confiança \(Format.percent(detection.confidence))")
						.font(.caption)
						.foregroundStyle(.secondary)
				}
			}
			Spacer()
			if case .known(let candidates) = detection.kind, let first = candidates.first {
				VStack(alignment: .trailing) {
					Text(Format.number(first.kcal)).font(.title3.weight(.bold).monospacedDigit())
					Text("kcal/100 g").font(.caption2).foregroundStyle(.secondary)
				}
			}
			Image(systemName: "chevron.right").foregroundStyle(.tertiary)
		}
		.padding(12)
		.background(Palette.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
		.contentShape(Rectangle())
	}

	@ViewBuilder private var badge: some View {
		switch detection.kind {
		case .known:
			tag("TACO", Palette.lime)
		case .notInTable:
			tag("fora da TACO", Palette.amber)
		case .generic:
			tag("genérico", Palette.cream)
		}
	}

	private func tag(_ text: String, _ color: Color) -> some View {
		Text(text)
			.font(.caption2.weight(.bold))
			.padding(.horizontal, 6)
			.padding(.vertical, 2)
			.foregroundStyle(Palette.ink)
			.background(color, in: Capsule())
	}
}

/// Cantos da mira, iguais aos do logo.
private struct Viewfinder: View {
	var active: Bool

	var body: some View {
		GeometryReader { geo in
			let len = min(geo.size.width, geo.size.height) * 0.14
			Path { p in
				let w = geo.size.width, h = geo.size.height
				p.move(to: .init(x: 0, y: len)); p.addLine(to: .zero); p.addLine(to: .init(x: len, y: 0))
				p.move(to: .init(x: w - len, y: 0)); p.addLine(to: .init(x: w, y: 0)); p.addLine(to: .init(x: w, y: len))
				p.move(to: .init(x: 0, y: h - len)); p.addLine(to: .init(x: 0, y: h)); p.addLine(to: .init(x: len, y: h))
				p.move(to: .init(x: w - len, y: h)); p.addLine(to: .init(x: w, y: h)); p.addLine(to: .init(x: w, y: h - len))
			}
			.stroke(active ? Palette.lime : Palette.cream.opacity(0.6), style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round))
			.animation(.easeInOut(duration: 0.25), value: active)
		}
	}
}
#endif
