import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var appState: AppState
    @State private var selectedTab: SidebarItem = .search

    enum SidebarItem: String, CaseIterable, Identifiable {
        case search = "搜索"
        case repos = "仓库"
        case status = "状态"
        case settings = "设置"

        var id: String { rawValue }
        var icon: String {
            switch self {
            case .search: return "magnifyingglass"
            case .repos: return "folder"
            case .status: return "waveform.path.ecg"
            case .settings: return "gearshape"
            }
        }
    }

    var body: some View {
        NavigationSplitView {
            List(SidebarItem.allCases, selection: $selectedTab) { item in
                Label(item.rawValue, systemImage: item.icon)
                    .tag(item)
            }
            .listStyle(.sidebar)
            .frame(minWidth: 180)
            .navigationTitle("CodePop")
        } detail: {
            Group {
                switch selectedTab {
                case .search:
                    SearchView()
                case .repos:
                    ReposView()
                case .status:
                    StatusView()
                case .settings:
                    SettingsView()
                }
            }
            .environmentObject(appState)
        }
        .toolbar {
            ToolbarItem(placement: .principal) {
                Text("CodePop")
                    .font(.headline)
            }
            ToolbarItem(placement: .automatic) {
                ConnectionStatusView()
                    .environmentObject(appState)
            }
        }
    }
}

struct ConnectionStatusView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: appState.apiService.isReachable ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundColor(appState.apiService.isReachable ? .green : .orange)
                .imageScale(.small)
            Text(appState.apiService.isReachable ? "已连接" : "未连接")
                .font(.caption)
        }
        .task {
            await appState.apiService.checkHealth()
        }
    }
}
