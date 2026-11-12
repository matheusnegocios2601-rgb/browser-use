#if os(iOS)
import GarfadaCore
import SwiftUI

/// O que abre ao tocar num item reconhecido pela câmera.
struct DetectionScreen: View {
	let database: FoodDatabase
	let detection: Detection

	var body: some View {
		switch detection.kind {
		case .known(let candidates):
			FoodDetailScreen(candidates: candidates, recognized: detection)
		case .notInTable:
			VStack(spacing: 0) {
				Card {
					Label("\(detection.name) não está na TACO", systemImage: "exclamationmark.triangle.fill")
						.font(.headline)
						.foregroundStyle(Palette.amber)
					Text("Reconheci \(detection.name.lowercased()) (\(Format.percent(detection.confidence))), mas a tabela oficial não tem esse alimento. Para não inventar número, escolha abaixo o item mais parecido ou os ingredientes separados.")
						.font(.subheadline)
				}
				.padding()
				SearchScreen(database: database)
			}
			.navigationTitle(detection.name)
		case .generic:
			SearchScreen(database: database)
				.navigationTitle("Qual comida é?")
		}
	}
}

struct FoodDetailScreen: View {
	let candidates: [Food]
	var recognized: Detection?

	@Environment(AppStore.self) private var store
	@Environment(\.dismiss) private var dismiss
	@State private var food: Food
	@State private var portion: Portion
	@State private var added = false

	init(candidates: [Food], recognized: Detection? = nil) {
		precondition(!candidates.isEmpty)
		self.candidates = candidates
		self.recognized = recognized
		_food = State(initialValue: candidates[0])
		_portion = State(initialValue: Portion.standard(for: candidates[0]))
	}

	private var facts: NutritionFacts { NutritionFacts(food: food, grams: portion.grams) }
	private var health: HealthAssessment { HealthAssessment(food: food, grams: portion.grams) }

	var body: some View {
		ScrollView {
			VStack(alignment: .leading, spacing: 14) {
				if let recognized {
					Text("Reconhecido pela câmera: \(recognized.name) · confiança \(Format.percent(recognized.confidence))")
						.font(.footnote)
						.foregroundStyle(.secondary)
				}
				if candidates.count > 1 {
					varietyPicker
				}
				summary
				PortionEditor(food: food, portion: $portion)
				weightNotice
				macros
				healthCard
				sources
			}
			.padding()
		}
		.navigationTitle(food.name)
		.navigationBarTitleDisplayMode(.inline)
		.safeAreaInset(edge: .bottom) {
			Button {
				store.add(food, portion: portion)
				added = true
				dismiss()
			} label: {
				Label("Adicionar ao prato", systemImage: "plus.circle.fill")
					.font(.headline)
					.frame(maxWidth: .infinity)
					.padding(.vertical, 6)
			}
			.buttonStyle(.borderedProminent)
			.foregroundStyle(Palette.ink)
			.padding()
			.background(.bar)
			.sensoryFeedback(.success, trigger: added)
		}
		.onChange(of: food) { _, newFood in
			portion = Portion.standard(for: newFood)
		}
	}

	private var varietyPicker: some View {
		Card {
			Text("Qual exatamente?").font(.headline)
			Text("A câmera não distingue o preparo (cru, cozido, frito). Escolha o certo, porque as calorias mudam muito.")
				.font(.footnote)
				.foregroundStyle(.secondary)
			Picker("Variedade", selection: $food) {
				ForEach(candidates) { Text($0.name).tag($0) }
			}
			.pickerStyle(.menu)
		}
	}

	private var summary: some View {
		HStack(alignment: .firstTextBaseline) {
			Text(Format.number(facts.kcal))
				.font(.system(size: 56, weight: .black, design: .rounded).monospacedDigit())
				.contentTransition(.numericText())
			Text("kcal").font(.title2.weight(.semibold))
			Spacer()
			VStack(alignment: .trailing) {
				Text(Format.number(portion.grams, unit: "g")).font(.title2.weight(.bold))
				Text(health.verdict.rawValue)
					.font(.subheadline.weight(.bold))
					.foregroundStyle(Palette.color(for: health.verdict))
			}
		}
		.animation(.snappy, value: portion)
	}

	private var weightNotice: some View {
		Label {
			Text("A câmera do iPhone 14 Plus não mede peso (não tem LiDAR). O peso acima vem da medida caseira do IBGE que você escolher. Para exatidão, pese numa balança e digite os gramas.")
				.font(.footnote)
		} icon: {
			Image(systemName: "scalemass")
		}
		.foregroundStyle(.secondary)
	}

	private var macros: some View {
		Card {
			Text("Nesta porção").font(.headline)
			Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
				macroRow("Proteína", facts.protein, "g")
				macroRow("Carboidratos", facts.carbs, "g")
				macroRow("Gorduras", facts.fat, "g")
				macroRow("Gordura saturada", facts.saturated, "g")
				macroRow("Fibras", facts.fiber, "g")
				macroRow("Sódio", facts.sodium, "mg", decimals: 0)
			}
			Text("— = valor não publicado na TACO para este alimento.")
				.font(.caption2)
				.foregroundStyle(.tertiary)
		}
	}

	private func macroRow(_ name: String, _ value: Double?, _ unit: String, decimals: Int = 1) -> some View {
		GridRow {
			Text(name).foregroundStyle(.secondary)
			Text(Format.number(value, decimals: decimals, unit: unit))
				.monospacedDigit()
				.gridColumnAlignment(.trailing)
		}
	}

	private var healthCard: some View {
		Card {
			HStack {
				Circle().fill(Palette.color(for: health.verdict)).frame(width: 12, height: 12)
				Text(health.verdict.rawValue).font(.headline)
			}
			if health.findings.isEmpty {
				Text("Nenhum alerta pelos critérios usados.").font(.subheadline).foregroundStyle(.secondary)
			}
			ForEach(health.findings, id: \.self) { finding in
				Label {
					Text(finding.text).font(.subheadline)
				} icon: {
					Image(systemName: icon(for: finding.tone))
						.foregroundStyle(color(for: finding.tone))
				}
			}
		}
	}

	private func icon(for tone: HealthAssessment.Finding.Tone) -> String {
		switch tone {
		case .positive: "checkmark.circle.fill"
		case .negative: "exclamationmark.circle.fill"
		case .neutral: "info.circle"
		}
	}

	private func color(for tone: HealthAssessment.Finding.Tone) -> Color {
		switch tone {
		case .positive: Palette.lime
		case .negative: Palette.pepper
		case .neutral: .secondary
		}
	}

	private var sources: some View {
		VStack(alignment: .leading, spacing: 4) {
			Text("Fonte: TACO 4ª ed., NEPA/UNICAMP (2011), valores por 100 g.")
			if let measure = portion.measure {
				Text("Medida: IBGE, POF 2008-2009 (\"\(measure.source)\").")
			}
		}
		.font(.caption)
		.foregroundStyle(.tertiary)
	}
}

struct PortionEditor: View {
	let food: Food
	@Binding var portion: Portion

	var body: some View {
		Card {
			Text("Porção").font(.headline)
			ScrollView(.horizontal, showsIndicators: false) {
				HStack {
					ForEach(food.measures, id: \.self) { measure in
						chip("\(measure.name) · \(Format.number(measure.grams))g", selected: portion.measure == measure) {
							portion.measure = measure
							portion.quantity = 1
						}
					}
					chip("em gramas", selected: portion.measure == nil) {
						portion.manualGrams = portion.grams
						portion.measure = nil
					}
				}
			}
			if let measure = portion.measure {
				Stepper(value: $portion.quantity, in: 0.5...20, step: 0.5) {
					Text("\(Format.number(portion.quantity, decimals: portion.quantity == portion.quantity.rounded() ? 0 : 1)) × \(measure.name)")
				}
			} else {
				Stepper(value: $portion.manualGrams, in: 5...2000, step: 10) {
					HStack {
						TextField("gramas", value: $portion.manualGrams, format: .number)
							.keyboardType(.decimalPad)
							.frame(width: 80)
							.textFieldStyle(.roundedBorder)
						Text("g")
					}
				}
			}
			if food.measures.isEmpty {
				Text("O IBGE não tem medida caseira para este alimento: informe os gramas.")
					.font(.caption)
					.foregroundStyle(.secondary)
			}
		}
	}

	private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
		Button(action: action) {
			Text(title)
				.font(.subheadline.weight(.semibold))
				.padding(.horizontal, 12)
				.padding(.vertical, 8)
				.foregroundStyle(selected ? Palette.ink : Palette.cream)
				.background(selected ? Palette.lime : Palette.card, in: Capsule())
		}
		.buttonStyle(.plain)
	}
}

struct SearchScreen: View {
	let database: FoodDatabase
	@State private var query = ""

	var body: some View {
		List {
			if query.trimmingCharacters(in: .whitespaces).isEmpty {
				Text("Busque entre os 597 alimentos da TACO. Ex.: \"feijão preto\", \"frango grelhado\", \"pão francês\".")
					.font(.subheadline)
					.foregroundStyle(.secondary)
			}
			ForEach(database.search(query)) { food in
				NavigationLink {
					FoodDetailScreen(candidates: [food])
				} label: {
					HStack {
						VStack(alignment: .leading) {
							Text(food.name)
							Text(food.category).font(.caption).foregroundStyle(.secondary)
						}
						Spacer()
						Text(Format.number(food.kcal, unit: "kcal"))
							.font(.subheadline.monospacedDigit())
							.foregroundStyle(.secondary)
					}
				}
			}
		}
		.searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Buscar alimento")
		.navigationTitle("Buscar")
	}
}
#endif
