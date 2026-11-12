import Foundation

/// Rótulo do classificador de imagens da Apple mapeado para alimentos da TACO.
public struct LabelEntry: Codable, Hashable, Sendable {
	/// Identificador do `VNClassifyImageRequest` (ex.: "rice").
	public let label: String
	/// Nome em português.
	public let name: String
	/// Candidatos na TACO; o primeiro é o pré-selecionado. Vazio = não existe na TACO.
	public let foodIDs: [Int]
}

/// Um alimento reconhecido pela câmera, já cruzado com a TACO.
public struct Detection: Identifiable, Hashable, Sendable {
	public enum Kind: Hashable, Sendable {
		/// Existe na TACO: temos números reais.
		case known(candidates: [Food])
		/// A Apple reconhece, mas a TACO não tem: não há número confiável.
		case notInTable
		/// Só sabemos que é comida ("food", "fruit"...).
		case generic
	}

	public var id: String { label }
	public let label: String
	public let name: String
	/// Confiança do classificador da Apple, 0...1.
	public let confidence: Double
	public let kind: Kind
}

public enum FoodDatabaseError: Error, Equatable {
	case missingResource(String)
	case unknownFoodID(label: String, id: Int)
}

public final class FoodDatabase: Sendable {
	public let foods: [Food]
	public let labels: [String: LabelEntry]
	public let genericLabels: [String: String]
	private let byID: [Int: Food]
	private let searchKeys: [Int: String]

	private static let genericNames: [String: String] = [
		"food": "Comida",
		"fruit": "Fruta",
		"vegetable": "Legume / verdura",
		"dessert": "Sobremesa",
		"drink": "Bebida",
		"baked_goods": "Assado / padaria",
		"grain": "Grão",
	]

	public init(foodsJSON: Data, labelsJSON: Data) throws {
		struct LabelsFile: Decodable {
			let labels: [LabelEntry]
			let generic: [String]
		}
		let foods = try JSONDecoder().decode([Food].self, from: foodsJSON)
		let labelsFile = try JSONDecoder().decode(LabelsFile.self, from: labelsJSON)
		let byID = Dictionary(uniqueKeysWithValues: foods.map { ($0.id, $0) })
		for entry in labelsFile.labels {
			for id in entry.foodIDs where byID[id] == nil {
				throw FoodDatabaseError.unknownFoodID(label: entry.label, id: id)
			}
		}
		self.foods = foods
		self.byID = byID
		self.labels = Dictionary(uniqueKeysWithValues: labelsFile.labels.map { ($0.label, $0) })
		self.genericLabels = Dictionary(
			uniqueKeysWithValues: labelsFile.generic.map { ($0, Self.genericNames[$0] ?? $0) }
		)
		self.searchKeys = Dictionary(uniqueKeysWithValues: foods.map { ($0.id, Self.normalize($0.name + " " + $0.category)) })
		assert(self.foods.count == byID.count, "ids duplicados na TACO")
	}

	/// Carrega os dados embarcados no app.
	public static func bundled() throws -> FoodDatabase {
		guard let foodsURL = Bundle.module.url(forResource: "taco", withExtension: "json") else {
			throw FoodDatabaseError.missingResource("taco.json")
		}
		guard let labelsURL = Bundle.module.url(forResource: "labels", withExtension: "json") else {
			throw FoodDatabaseError.missingResource("labels.json")
		}
		return try FoodDatabase(foodsJSON: Data(contentsOf: foodsURL), labelsJSON: Data(contentsOf: labelsURL))
	}

	public func food(id: Int) -> Food? { byID[id] }

	/// Busca sem acento e sem diferenciar maiúsculas; todas as palavras precisam aparecer.
	public func search(_ query: String, limit: Int = 60) -> [Food] {
		let tokens = Self.normalize(query).split(separator: " ").map(String.init)
		guard !tokens.isEmpty else { return [] }
		let hits = foods.filter { food in
			let key = searchKeys[food.id] ?? ""
			return tokens.allSatisfy { key.contains($0) }
		}
		// Prioriza quem começa com o primeiro termo ("arroz" antes de "farinha de arroz").
		let first = tokens[0]
		let sorted = hits.sorted { a, b in
			let aStarts = Self.normalize(a.name).hasPrefix(first)
			let bStarts = Self.normalize(b.name).hasPrefix(first)
			if aStarts != bStarts { return aStarts }
			return a.id < b.id
		}
		return Array(sorted.prefix(limit))
	}

	/// Converte as classificações do Vision (rótulo, confiança) em detecções úteis, da mais para a menos provável.
	/// Rótulos que não são comida são descartados. Específicos vêm antes dos genéricos.
	public func detections(from classifications: [(label: String, confidence: Double)], minimumConfidence: Double = 0.1) -> [Detection] {
		var result: [Detection] = []
		var seenNames = Set<String>()
		for (label, confidence) in classifications.sorted(by: { $0.confidence > $1.confidence }) where confidence >= minimumConfidence {
			if let entry = labels[label] {
				// "rice" e "salad" podem ter o mesmo nome PT de outro rótulo (ex.: lemon/lime): mostra uma vez só.
				guard seenNames.insert(entry.name).inserted else { continue }
				let candidates = entry.foodIDs.compactMap { byID[$0] }
				result.append(Detection(
					label: label, name: entry.name, confidence: confidence,
					kind: candidates.isEmpty ? .notInTable : .known(candidates: candidates)
				))
			} else if let name = genericLabels[label] {
				result.append(Detection(label: label, name: name, confidence: confidence, kind: .generic))
			}
		}
		let specific = result.filter { if case .generic = $0.kind { return false } else { return true } }
		let generic = result.filter { if case .generic = $0.kind { return true } else { return false } }
		return specific + generic
	}

	static func normalize(_ s: String) -> String {
		s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: Locale(identifier: "pt_BR"))
			.replacingOccurrences(of: ",", with: " ")
			.replacingOccurrences(of: "-", with: " ")
	}
}
