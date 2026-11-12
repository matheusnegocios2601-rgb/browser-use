#if os(iOS)
import GarfadaCore
import SwiftUI

struct MealScreen: View {
	let database: FoodDatabase
	@Environment(AppStore.self) private var store
	@State private var confirmClear = false

	private struct Row: Identifiable {
		let item: MealItem
		let food: Food
		let facts: NutritionFacts
		let health: HealthAssessment
		var id: UUID { item.id }
	}

	private var rows: [Row] {
		store.meal.compactMap { item in
			guard let food = database.food(id: item.foodID) else { return nil }
			let grams = item.portion.grams
			return Row(item: item, food: food, facts: NutritionFacts(food: food, grams: grams), health: HealthAssessment(food: food, grams: grams))
		}
	}

	var body: some View {
		NavigationStack {
			Group {
				if rows.isEmpty {
					ContentUnavailableView(
						"Prato vazio",
						systemImage: "fork.knife",
						description: Text("Aponte a câmera para cada alimento e toque em \"Adicionar ao prato\".")
					)
				} else {
					List {
						Section { totals }
						Section("Itens") {
							ForEach(rows) { row in
								HStack {
									Circle().fill(Palette.color(for: row.health.verdict)).frame(width: 10, height: 10)
									VStack(alignment: .leading) {
										Text(row.food.name)
										Text(row.item.portion.label).font(.caption).foregroundStyle(.secondary)
									}
									Spacer()
									Text(Format.number(row.facts.kcal, unit: "kcal")).monospacedDigit()
								}
							}
							.onDelete { store.remove(at: $0) }
						}
					}
				}
			}
			.navigationTitle("Prato")
			.toolbar {
				if !rows.isEmpty {
					Button("Limpar", role: .destructive) { confirmClear = true }
				}
			}
			.confirmationDialog("Começar um prato novo?", isPresented: $confirmClear) {
				Button("Limpar prato", role: .destructive) { store.clearMeal() }
			}
		}
	}

	private var totals: some View {
		let total = NutritionFacts.sum(rows.map { $0.facts })
		let alerts = rows.reduce(0) { $0 + $1.health.findings.filter { $0.tone == .negative }.count }
		return VStack(alignment: .leading, spacing: 8) {
			HStack(alignment: .firstTextBaseline) {
				Text(Format.number(total.kcal))
					.font(.system(size: 48, weight: .black, design: .rounded).monospacedDigit())
				Text("kcal")
				Spacer()
				Text(Format.number(total.grams, unit: "g")).font(.title3.weight(.bold))
			}
			HStack(spacing: 16) {
				stat("Prot.", total.protein)
				stat("Carb.", total.carbs)
				stat("Gord.", total.fat)
				stat("Fibra", total.fiber)
			}
			Text(alerts == 0 ? "Nenhum alerta de sódio, gordura saturada ou açúcar." : "\(alerts) alerta(s) nos itens: veja cada um.")
				.font(.footnote)
				.foregroundStyle(alerts == 0 ? Palette.lime : Palette.amber)
		}
	}

	private func stat(_ name: String, _ value: Double?) -> some View {
		VStack(alignment: .leading) {
			Text(Format.number(value, decimals: 1, unit: "g")).font(.subheadline.weight(.semibold).monospacedDigit())
			Text(name).font(.caption).foregroundStyle(.secondary)
		}
	}
}

struct AboutScreen: View {
	var body: some View {
		NavigationStack {
			ScrollView {
				VStack(alignment: .leading, spacing: 16) {
					HStack(spacing: 14) {
						LogoMark().frame(width: 72, height: 72)
						VStack(alignment: .leading) {
							Text("garfada").font(.system(size: 34, weight: .black, design: .rounded))
							Text("Aponte. Veja o que vai no garfo.").foregroundStyle(.secondary)
						}
					}
					Card {
						Text("Como funciona").font(.headline)
						Text("1. O classificador de imagens da Apple (Vision) roda no próprio iPhone e diz o que parece estar na câmera, com a confiança dele.\n2. Eu cruzo com a TACO, a tabela oficial brasileira de composição de alimentos.\n3. O peso vem de medidas caseiras medidas pelo IBGE, ou dos gramas que você digitar.")
					}
					Card {
						Text("O que eu NÃO faço").font(.headline)
						Text("• Não mido peso pela câmera: o iPhone 14 Plus não tem sensor de profundidade (LiDAR).\n• Não invento calorias: se o alimento não está na TACO (ex.: pizza, sushi), eu aviso e você escolhe o mais parecido.\n• Não diferencio preparo (cru, cozido, frito) pela imagem: você confirma.\n• Não envio nada para a internet. Grátis e sem limite.")
					}
					Card {
						Text("Critérios de \"saudável\"").font(.headline)
						Text("• Alto em sódio / gordura saturada: limites da lupa da Anvisa (RDC 429/2020).\n• Fonte de fibra: RDC 54/2012, por porção.\n• In natura e ultraprocessados: Guia Alimentar para a População Brasileira.\nIsto não é orientação médica nem nutricional.")
					}
					Card {
						Text("Fontes").font(.headline)
						Text("TACO 4ª ed. revisada e ampliada, NEPA/UNICAMP, 2011.\nIBGE, POF 2008-2009: Tabela de Medidas Referidas para os Alimentos Consumidos no Brasil.\nDados processados por brolesi/taco e taco-br-mcp (MIT).")
							.font(.footnote)
					}
				}
				.padding()
			}
			.navigationTitle("Sobre")
			.navigationBarTitleDisplayMode(.inline)
		}
	}
}
#endif
