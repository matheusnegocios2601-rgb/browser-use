import XCTest
@testable import GarfadaCore

final class GarfadaCoreTests: XCTestCase {
	var db: FoodDatabase!

	override func setUpWithError() throws {
		db = try FoodDatabase.bundled()
	}

	func testBundledTableIsCompleteTACO() throws {
		XCTAssertEqual(db.foods.count, 597)
		// Valores conferidos com a TACO 4ª ed. impressa.
		let arroz = try XCTUnwrap(db.food(id: 3))
		XCTAssertEqual(arroz.name, "Arroz, tipo 1, cozido")
		XCTAssertEqual(arroz.kcal, 128)
		let banana = try XCTUnwrap(db.food(id: 182))
		XCTAssertEqual(banana.kcal, 98)
		XCTAssertEqual(banana.sodium, 0, "Tr (traço) vira 0")
	}

	func testEveryLabelPointsToRealFoods() {
		for entry in db.labels.values {
			for id in entry.foodIDs {
				XCTAssertNotNil(db.food(id: id), "\(entry.label) -> \(id)")
			}
		}
		XCTAssertTrue(db.labels["pizza"]!.foodIDs.isEmpty, "pizza não existe na TACO: não pode ter número")
	}

	func testPortionUsesIBGEMeasure() throws {
		let arroz = try XCTUnwrap(db.food(id: 3))
		let portion = Portion.standard(for: arroz)
		XCTAssertEqual(portion.measure?.name, "escumadeira")
		XCTAssertEqual(portion.grams, 85)
		let facts = NutritionFacts(food: arroz, grams: portion.grams)
		XCTAssertEqual(try XCTUnwrap(facts.kcal), 108.8, accuracy: 0.001)

		var two = portion
		two.quantity = 2
		XCTAssertEqual(two.grams, 170)
	}

	func testFoodWithoutMeasureDefaultsTo100g() throws {
		let semMedida = try XCTUnwrap(db.foods.first { $0.measures.isEmpty })
		XCTAssertEqual(Portion.standard(for: semMedida).grams, 100)
	}

	func testSumPropagatesMissingValues() throws {
		let a = NutritionFacts(food: try XCTUnwrap(db.food(id: 3)), grams: 100)
		let missing = try XCTUnwrap(db.foods.first { $0.saturated == nil })
		let b = NutritionFacts(food: missing, grams: 100)
		let total = NutritionFacts.sum([a, b])
		XCTAssertNil(total.saturated, "sem dado publicado não somamos zero escondido")
		XCTAssertEqual(total.grams, 200)
	}

	func testHealthRules() throws {
		// Manteiga com sal: saturada 49,2 g (alta), sódio 579 mg (abaixo de 600) -> só 1 alerta.
		let manteiga = try XCTUnwrap(db.food(id: 261))
		XCTAssertEqual(HealthAssessment(food: manteiga, grams: 10).verdict, .moderation)
		// Salame: sódio 1574 mg e saturada 9,6 g -> 2 alertas.
		let salame = try XCTUnwrap(db.food(id: 443))
		XCTAssertEqual(HealthAssessment(food: salame, grams: 30).verdict, .avoid)

		let feijao = try XCTUnwrap(db.food(id: 561))
		let feijaoEval = HealthAssessment(food: feijao, grams: 100)
		XCTAssertEqual(feijaoEval.verdict, .good)
		XCTAssertTrue(feijaoEval.findings.contains { $0.text.contains("fibra") })

		let cola = try XCTUnwrap(db.food(id: 480))
		XCTAssertTrue(cola.isLiquid)
		XCTAssertNotEqual(HealthAssessment(food: cola, grams: 200).verdict, .good)

		let batataFrita = try XCTUnwrap(db.food(id: 93))
		XCTAssertFalse(HealthAssessment.isInNatura(batataFrita))
	}

	func testDetectionsFilterNonFoodAndOrderSpecificFirst() {
		let detections = db.detections(from: [
			(label: "food", confidence: 0.9),
			(label: "table", confidence: 0.8),
			(label: "rice", confidence: 0.6),
			(label: "pizza", confidence: 0.3),
			(label: "bean", confidence: 0.05),
		])
		XCTAssertEqual(detections.map(\.label), ["rice", "pizza", "food"])
		guard case .known(let candidates) = detections[0].kind else { return XCTFail() }
		XCTAssertEqual(candidates.first?.id, 3)
		XCTAssertEqual(detections[1].kind, .notInTable)
		XCTAssertEqual(detections[2].kind, .generic)
	}

	func testSearchIgnoresAccents() {
		let results = db.search("feijao preto")
		XCTAssertEqual(results.first?.name, "Feijão, preto, cozido")
		XCTAssertTrue(db.search("   ").isEmpty)
		XCTAssertEqual(db.search("arroz").first?.name.hasPrefix("Arroz"), true)
	}
}
