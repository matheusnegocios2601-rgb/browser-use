#if os(iOS)
import Foundation
import GarfadaCore
import Observation

/// Estado global: a tabela TACO e o prato atual (salvo no aparelho, nada vai para a internet).
@MainActor
@Observable
final class AppStore {
	let database: FoodDatabase?
	let loadError: String?
	private(set) var meal: [MealItem]

	private static let mealKey = "garfada.meal.v1"

	init() {
		do {
			database = try FoodDatabase.bundled()
			loadError = nil
		} catch {
			database = nil
			loadError = String(describing: error)
		}
		meal = Self.loadMeal()
	}

	func add(_ food: Food, portion: Portion) {
		meal.append(MealItem(foodID: food.id, portion: portion))
		save()
	}

	func remove(at offsets: IndexSet) {
		meal.remove(atOffsets: offsets)
		save()
	}

	func clearMeal() {
		meal.removeAll()
		save()
	}

	private func save() {
		guard let data = try? JSONEncoder().encode(meal) else { return }
		UserDefaults.standard.set(data, forKey: Self.mealKey)
	}

	private static func loadMeal() -> [MealItem] {
		guard let data = UserDefaults.standard.data(forKey: mealKey),
			let items = try? JSONDecoder().decode([MealItem].self, from: data)
		else { return [] }
		return items
	}
}
#endif
