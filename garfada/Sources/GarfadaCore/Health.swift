import Foundation

/// Avaliação "saudável ou não" com critérios explícitos e citáveis. Nada de achismo:
/// cada conclusão aparece com o número e a regra que a gerou.
///
/// Regras:
/// - "Alto em" sódio / gordura saturada: mesmos limites da lupa frontal da Anvisa (RDC 429/2020),
///   por 100 g (sólidos: sódio ≥ 600 mg, saturada ≥ 6 g) ou 100 mL (líquidos: 300 mg, 3 g).
///   A TACO não mede açúcar separadamente, então açúcar só é sinalizado pela categoria.
/// - Fibra na porção: "fonte" ≥ 2,5 g, "alto conteúdo" ≥ 5 g (RDC 54/2012, por porção).
/// - In natura / minimamente processado e refrigerantes: Guia Alimentar para a População Brasileira (2014).
public struct HealthAssessment: Hashable, Sendable {
	public enum Verdict: String, Sendable {
		case good = "Boa escolha"
		case ok = "Neutro"
		case moderation = "Com moderação"
		case avoid = "Evite no dia a dia"
	}

	public struct Finding: Hashable, Sendable {
		public enum Tone: Sendable { case positive, negative, neutral }
		public let tone: Tone
		public let text: String
	}

	public let verdict: Verdict
	public let findings: [Finding]

	public static let sodiumLimitSolid = 600.0
	public static let sodiumLimitLiquid = 300.0
	public static let saturatedLimitSolid = 6.0
	public static let saturatedLimitLiquid = 3.0
	public static let fiberSourcePerPortion = 2.5
	public static let fiberHighPerPortion = 5.0

	public init(food: Food, grams: Double) {
		precondition(grams >= 0)
		var findings: [Finding] = []
		let liquid = food.isLiquid
		let unit = liquid ? "100 mL" : "100 g"

		let sodiumLimit = liquid ? Self.sodiumLimitLiquid : Self.sodiumLimitSolid
		if let sodium = food.sodium, sodium >= sodiumLimit {
			findings.append(.init(tone: .negative, text: "Alto em sódio: \(Self.fmt(sodium)) mg por \(unit) (limite da lupa Anvisa: \(Self.fmt(sodiumLimit)) mg)."))
		}
		let satLimit = liquid ? Self.saturatedLimitLiquid : Self.saturatedLimitSolid
		if let sat = food.saturated, sat >= satLimit {
			findings.append(.init(tone: .negative, text: "Alto em gordura saturada: \(Self.fmt(sat)) g por \(unit) (limite da lupa Anvisa: \(Self.fmt(satLimit)) g)."))
		}
		if food.category == "Produtos açucarados" {
			findings.append(.init(tone: .negative, text: "Produto açucarado (a TACO não mede o açúcar separadamente; classificação pela categoria)."))
		}
		if food.name.hasPrefix("Refrigerante") || food.name.hasPrefix("Bebida isotônica") {
			findings.append(.init(tone: .negative, text: "Bebida ultraprocessada: o Guia Alimentar recomenda evitar."))
		}

		let fiber = NutritionFacts(food: food, grams: grams).fiber
		if let fiber, fiber >= Self.fiberHighPerPortion {
			findings.append(.init(tone: .positive, text: "Alto conteúdo de fibra nesta porção: \(Self.fmt(fiber)) g (≥ 5 g, RDC 54/2012)."))
		} else if let fiber, fiber >= Self.fiberSourcePerPortion {
			findings.append(.init(tone: .positive, text: "Fonte de fibra nesta porção: \(Self.fmt(fiber)) g (≥ 2,5 g, RDC 54/2012)."))
		}

		if Self.isInNatura(food) {
			findings.append(.init(tone: .positive, text: "Alimento in natura ou minimamente processado: base da alimentação segundo o Guia Alimentar."))
		}
		if food.category == "Gorduras e óleos" {
			findings.append(.init(tone: .neutral, text: "Óleos e gorduras: o Guia Alimentar recomenda usar em pequenas quantidades."))
		}
		if food.saturated == nil, !liquid {
			findings.append(.init(tone: .neutral, text: "A TACO não publica gordura saturada para este alimento."))
		}

		let negatives = findings.filter { $0.tone == .negative }.count
		let positives = findings.filter { $0.tone == .positive }.count
		switch (negatives, positives) {
		case (2..., _): verdict = .avoid
		case (1, _): verdict = .moderation
		case (0, 1...): verdict = .good
		default: verdict = food.category == "Gorduras e óleos" ? .moderation : .ok
		}
		self.findings = findings
	}

	static func isInNatura(_ food: Food) -> Bool {
		let processedMarkers = ["frit", "doce", "calda", "chips", "enlatad", "conserva", "industrializad", "concentrado", "xarope", "pó"]
		let lower = food.name.lowercased()
		if processedMarkers.contains(where: { lower.contains($0) }) { return false }
		switch food.category {
		case "Verduras, hortaliças e derivados", "Leguminosas e derivados":
			return true
		case "Frutas e derivados":
			return lower.contains("cru") || lower.contains("polpa")
		default:
			return false
		}
	}

	static func fmt(_ v: Double) -> String {
		let rounded = (v * 10).rounded() / 10
		let s = rounded == rounded.rounded() ? String(Int(rounded)) : String(rounded)
		return s.replacingOccurrences(of: ".", with: ",")
	}
}
