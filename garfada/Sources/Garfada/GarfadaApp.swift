#if os(iOS)
import GarfadaCore
import SwiftUI

@main
struct GarfadaApp: App {
	@State private var store = AppStore()

	var body: some Scene {
		WindowGroup {
			RootView()
				.environment(store)
				.preferredColorScheme(.dark)
				.tint(Palette.lime)
		}
	}
}

struct RootView: View {
	@Environment(AppStore.self) private var store

	var body: some View {
		if let database = store.database {
			TabView {
				CameraScreen(database: database)
					.tabItem { Label("Câmera", systemImage: "viewfinder") }
				MealScreen(database: database)
					.tabItem { Label("Prato", systemImage: "fork.knife") }
					.badge(store.meal.count)
				NavigationStack { SearchScreen(database: database) }
					.tabItem { Label("Buscar", systemImage: "magnifyingglass") }
			}
		} else {
			ContentUnavailableView(
				"Erro ao abrir a tabela TACO",
				systemImage: "exclamationmark.triangle",
				description: Text(store.loadError ?? "Erro desconhecido")
			)
		}
	}
}
#endif
