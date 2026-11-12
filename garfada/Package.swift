// swift-tools-version: 6.0

import PackageDescription

let package = Package(
	name: "Garfada",
	platforms: [
		.iOS(.v17),
		.macOS(.v14),
	],
	products: [
		// Um projeto xtool deve ter exatamente um produto library: o app.
		.library(
			name: "Garfada",
			targets: ["Garfada"]
		),
	],
	targets: [
		// Lógica pura (dados TACO/IBGE, porções, avaliação de saúde). Compila e testa no Linux.
		.target(
			name: "GarfadaCore",
			resources: [.process("Resources")]
		),
		// App iOS (SwiftUI + AVFoundation + Vision). Só compila com o SDK do iOS (xtool).
		.target(
			name: "Garfada",
			dependencies: ["GarfadaCore"],
			swiftSettings: [.swiftLanguageMode(.v5)]
		),
		.testTarget(
			name: "GarfadaCoreTests",
			dependencies: ["GarfadaCore"]
		),
	]
)
