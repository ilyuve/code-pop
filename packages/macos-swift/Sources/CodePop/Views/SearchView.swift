import SwiftUI

struct SearchView: View {
    @EnvironmentObject private var appState: AppState
    @StateObject private var viewModel = SearchViewModel()
    @State private var repos: [Repo] = []

    var body: some View {
        VStack(spacing: 0) {
            searchBar
            resultsList
        }
        .navigationTitle("代码搜索")
        .task {
            await loadRepos()
        }
    }

    private var searchBar: some View {
        HStack(spacing: 12) {
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundColor(.secondary)
                TextField("搜索代码、函数、符号...", text: $viewModel.query)
                    .textFieldStyle(.plain)
                    .onSubmit {
                        Task { await viewModel.search(api: appState.apiService) }
                    }
                if !viewModel.query.isEmpty {
                    Button(action: { viewModel.clear() }) {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundColor(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(8)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            Picker("仓库", selection: $viewModel.selectedRepoId) {
                Text("全部仓库").tag(nil as String?)
                ForEach(repos) { repo in
                    Text(repo.name).tag(repo.id as String?)
                }
            }
            .pickerStyle(.menu)
            .frame(width: 160)

            Button("搜索") {
                Task { await viewModel.search(api: appState.apiService) }
            }
            .keyboardShortcut(.defaultAction)
            .disabled(viewModel.query.trimmingCharacters(in: .whitespaces).isEmpty)

            if viewModel.isLoading {
                ProgressView()
                    .scaleEffect(0.8)
            }
        }
        .padding()
    }

    private var resultsList: some View {
        List {
            if let error = viewModel.errorMessage {
                Section {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .foregroundColor(.red)
                }
            }

            if viewModel.results.isEmpty && !viewModel.isLoading && viewModel.errorMessage == nil && !viewModel.query.isEmpty {
                Section {
                    Text("暂无结果")
                        .foregroundColor(.secondary)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.vertical, 40)
                }
            }

            ForEach(viewModel.results) { result in
                SearchResultRow(result: result)
            }
        }
        .listStyle(.inset)
    }

    private func loadRepos() async {
        do {
            repos = try await appState.apiService.fetchRepos()
        } catch {
            repos = []
        }
    }
}

struct SearchResultRow: View {
    let result: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(result.filePath)
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundColor(.primary)
                Spacer()
                Text(result.language.uppercased())
                    .font(.caption2)
                    .foregroundColor(.secondary)
                Text(String(format: "%.2f", result.score))
                    .font(.caption2)
                    .foregroundColor(.green)
                    .frame(minWidth: 32, alignment: .trailing)
            }

            Text(result.content)
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(.secondary)
                .lineLimit(4)

            if !result.symbols.isEmpty {
                HStack(spacing: 6) {
                    ForEach(result.symbols.prefix(4), id: \.self) { symbol in
                        Text(symbol)
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.accentColor.opacity(0.12))
                            .foregroundColor(.accentColor)
                            .clipShape(Capsule())
                    }
                }
            }
        }
        .padding(.vertical, 6)
    }
}
