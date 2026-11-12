import Foundation

/// Medida caseira com peso em gramas, da POF 2008-2009 do IBGE.
public struct HouseholdMeasure: Codable, Hashable, Sendable {
	public let name: String
	public let grams: Double
	/// Descrição original da tabela do IBGE (ex.: "Arroz cozido - escumadeira média cheia").
	public let source: String
}

/// Um alimento da TACO 4ª ed. (NEPA/UNICAMP, 2011). Valores por 100 g de parte comestível.
/// `nil` = a TACO não publica esse valor para o alimento. `0` = zero ou traço (Tr).
public struct Food: Codable, Identifiable, Hashable, Sendable {
	public let id: Int
	public let name: String
	public let category: String
	public let kcal: Double?
	public let protein: Double?
	public let fat: Double?
	public let carbs: Double?
	public let fiber: Double?
	/// mg por 100 g.
	public let sodium: Double?
	public let saturated: Double?
	public let measures: [HouseholdMeasure]

	/// Bebidas e leites: a Anvisa usa limites por 100 mL para líquidos.
	public var isLiquid: Bool {
		if category.hasPrefix("Bebidas") { return true }
		let liquidPrefixes = ["Leite, de vaca", "Leite, de cabra", "Leite, fermentado", "Bebida láctea", "Soja, extrato solúvel, natural"]
		if liquidPrefixes.contains(where: { name.hasPrefix($0) }) { return true }
		return name.contains(", suco")
	}
}

/// Nutrientes de uma porção específica.
public struct NutritionFacts: Hashable, Sendable {
	public let grams: Double
	public let kcal: Double?
	public let protein: Double?
	public let fat: Double?
	public let carbs: Double?
	public let fiber: Double?
	public let sodium: Double?
	public let saturated: Double?

	public init(food: Food, grams: Double) {
		precondition(grams >= 0, "porção negativa")
		func scale(_ per100: Double?) -> Double? { per100.map { $0 * grams / 100 } }
		self.grams = grams
		kcal = scale(food.kcal)
		protein = scale(food.protein)
		fat = scale(food.fat)
		carbs = scale(food.carbs)
		fiber = scale(food.fiber)
		sodium = scale(food.sodium)
		saturated = scale(food.saturated)
	}

	init(grams: Double, kcal: Double?, protein: Double?, fat: Double?, carbs: Double?, fiber: Double?, sodium: Double?, saturated: Double?) {
		self.grams = grams
		self.kcal = kcal
		self.protein = protein
		self.fat = fat
		self.carbs = carbs
		self.fiber = fiber
		self.sodium = sodium
		self.saturated = saturated
	}

	/// Soma porções. Se algum item não tem o valor publicado, o total vira `nil` (não inventamos).
	public static func sum(_ items: [NutritionFacts]) -> NutritionFacts {
		func add(_ kp: KeyPath<NutritionFacts, Double?>) -> Double? {
			var total = 0.0
			for item in items {
				guard let v = item[keyPath: kp] else { return nil }
				total += v
			}
			return total
		}
		return NutritionFacts(
			grams: items.reduce(0) { $0 + $1.grams },
			kcal: add(\.kcal), protein: add(\.protein), fat: add(\.fat), carbs: add(\.carbs),
			fiber: add(\.fiber), sodium: add(\.sodium), saturated: add(\.saturated)
		)
	}
}
