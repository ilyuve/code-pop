import SwiftUI

struct ReposView: View {
    @EnvironmentObject private var appState: AppState
    @StateObject private var viewModel = ReposViewModel()

    var body: some View {
        VStack(spacing: 0) {
            List {
                if viewModel.repos.isEmpty && !viewModel.isLoading {
                    Section {
                        Text("还没有仓库")
                            .foregroundColor(.secondary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, 40)
                    }
                }

                ForEach(viewModel.repos) { repo in
                    RepoRow(repo: repo, viewModel: viewModel)
                }
            }
            .listStyle(.inset)
        }
        .navigationTitle("仓库")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(action: { viewModel.showAddSheet = true }) {
                    Label("添加", systemImage: "plus")
                }
            }
        }
        .task {
            await viewModel.load(api: appState.apiService)
        }
        .sheet(isPresented: $viewModel.showAddSheet) {
            AddRepoSheet(viewModel: viewModel)
                .frame(minWidth: 420, minHeight: 240)
        }
    }
}

struct RepoRow: View {
    let repo: Repo
    @ObservedObject var viewModel: ReposViewModel
    @EnvironmentObject private var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: "folder.fill")
                    .foregroundColor(.accentColor)
                Text(repo.name)
                    .font(.headline)
                Spacer()
                StatusBadge(status: repo.status)
            }

            Text(repo.path)
                .font(.caption)
                .foregroundColor(.secondary)
                .lineLimit(1)

            HStack(spacing: 16) {
                Label("\(repo.fileCount)", systemImage: "doc")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Label("\(repo.symbolCount)", systemImage: "cube")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Label("\(repo.embeddingCount)", systemImage: "arrow.up.arrow.down")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
            }

            if repo.status == "indexing" {
                ProgressView(value: Double(repo.indexingProgress), total: 100)
                    .progressViewStyle(.linear)
            }
        }
        .padding(.vertical, 6)
        .contextMenu {
            Button("重建索引") {
                Task { await viewModel.reindexRepo(api: appState.apiService, id: repo.id) }
            }
            Divider()
            Button("删除", role: .destructive) {
                Task { await viewModel.deleteRepo(api: appState.apiService, id: repo.id) }
            }
        }
    }
}

struct StatusBadge: View {
    let status: String

    var body: some View {
        Text(status.capitalized)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(CodePopTheme.statusColor(status).opacity(0.12))
            .foregroundColor(CodePopTheme.statusColor(status))
            .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}

struct AddRepoSheet: View {
    @ObservedObject var viewModel: ReposViewModel
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 16) {
            Text("添加代码仓库")
                .font(.headline)

            Form {
                TextField("名称", text: $viewModel.newRepoName)
                TextField("本地路径", text: $viewModel.newRepoPath)
                TextField("Git URL（可选）", text: $viewModel.newRepoGitUrl)
            }
            .frame(width: 360)

            if let error = viewModel.errorMessage {
                Text(error)
                    .foregroundColor(.red)
                    .font(.caption)
            }

            HStack {
                Button("取消") {
                    viewModel.resetForm()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("添加") {
                    Task { await viewModel.addRepo(api: appState.apiService) }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(viewModel.newRepoName.isEmpty || viewModel.newRepoPath.isEmpty)
            }
        }
        .padding()
        .frame(width: 420)
    }
}
