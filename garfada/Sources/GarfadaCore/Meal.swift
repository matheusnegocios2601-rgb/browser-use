import Foundation

/// Porção escolhida: uma medida caseira do IBGE vezes uma quantidade, ou gramas digitados.
public struct Portion: Codable, Hashable, Sendable {
	public var measure: HouseholdMeasure?
	public var quantity: Double
	public var manualGrams: Double

	public static func standard(for food: Food) -> Portion {
		if let first = food.measures.first {
			return Portion(measure: first, quantity: 1, manualGrams: first.grams)
		}
		return Portion(measure: nil, quantity: 1, manualGrams: 100)
	}

	public var grams: Double {
		let g = measure.map { $0.grams * quantity } ?? manualGrams
		assert(g >= 0)
		return g
	}

	public var label: String {
		guard let measure else { return "\(HealthAssessment.fmt(manualGrams)) g" }
		return "\(HealthAssessment.fmt(quantity)) × \(measure.name) (\(HealthAssessment.fmt(grams)) g)"
	}
}

/// Um item do prato do dia.
public struct MealItem: Codable, Identifiable, Hashable, Sendable {
	public var id: UUID
	public let foodID: Int
	public var portion: Portion
	public let addedAt: Date

	public init(foodID: Int, portion: Portion, addedAt: Date = .now) {
		self.id = UUID()
		self.foodID = foodID
		self.portion = portion
		self.addedAt = addedAt
	}
}
