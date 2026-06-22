import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var appState: AppState
    @State private var endpointInput: String = ""
    @State private var saveSuccess: Bool = false

    var body: some View {
        Form {
            Section("API 端点") {
                TextField("后端地址", text: $endpointInput)
                    .textFieldStyle(.roundedBorder)

                HStack(spacing: 12) {
                    Button("保存") {
                        appState.apiEndpoint = endpointInput
                        appState.apiService.updateBaseURL(endpointInput)
                        Task { await appState.apiService.checkHealth() }
                        withAnimation { saveSuccess = true }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                            withAnimation { saveSuccess = false }
                        }
                    }
                    .keyboardShortcut(.defaultAction)

                    if saveSuccess {
                        Label("已保存", systemImage: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    }
                }
            }

            Section("连接测试") {
                HStack(spacing: 10) {
                    Image(systemName: appState.apiService.isReachable ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                        .foregroundColor(appState.apiService.isReachable ? .green : .orange)
                    Text(appState.apiService.isReachable ? "后端服务可连接" : "无法连接后端服务")
                }

                Button("测试连接") {
                    Task { await appState.apiService.checkHealth() }
                }
            }

            Section("关于") {
                HStack {
                    Text("CodePop")
                        .font(.headline)
                    Text("代码波普")
                        .foregroundColor(.secondary)
                }
                Text("面向 AI Agent 的代码专用检索基础设施")
                    .foregroundColor(.secondary)
                Text("SwiftUI macOS 客户端")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .formStyle(.grouped)
        .navigationTitle("设置")
        .frame(minWidth: 420)
        .onAppear {
            endpointInput = appState.apiEndpoint
        }
    }
}
