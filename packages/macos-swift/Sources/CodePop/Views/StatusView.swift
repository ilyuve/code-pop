import SwiftUI

struct StatusView: View {
    @EnvironmentObject private var appState: AppState
    @StateObject private var viewModel = StatusViewModel()

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                if viewModel.isLoading && viewModel.status == nil {
                    ProgressView()
                        .scaleEffect(1.2)
                        .padding(.top, 60)
                } else if let status = viewModel.status {
                    statusContent(status)
                } else if let error = viewModel.errorMessage {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .foregroundColor(.red)
                        .padding(.top, 60)
                }
            }
            .padding()
            .frame(maxWidth: .infinity)
        }
        .navigationTitle("系统状态")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(action: {
                    Task { await viewModel.load(api: appState.apiService) }
                }) {
                    Image(systemName: "arrow.clockwise")
                }
            }
        }
        .task {
            await viewModel.load(api: appState.apiService)
        }
    }

    private func statusContent(_ status: SystemStatus) -> some View {
        VStack(spacing: 20) {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180))], spacing: 16) {
                StatusMetricCard(title: "状态", value: status.status.capitalized, color: CodePopTheme.statusColor(status.status))
                StatusMetricCard(title: "版本", value: status.version, color: .accentColor)
                StatusMetricCard(title: "运行时间", value: formatUptime(status.uptime), color: .green)
                StatusMetricCard(title: "活跃请求", value: "\(status.activeRequests)", color: .orange)
                StatusMetricCard(title: "索引任务", value: "\(status.indexingTasks)", color: .purple)
                StatusMetricCard(title: "降级功能", value: "\(status.degradedFeatures.count)", color: status.degradedFeatures.isEmpty ? .green : .red)
            }

            if !status.degradedFeatures.isEmpty {
                GroupBox("降级功能") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(status.degradedFeatures, id: \.self) { feature in
                            Label(feature, systemImage: "exclamationmark.circle")
                                .font(.body)
                        }
                    }
                    .padding(4)
                }
            }

            if !status.metrics.isEmpty {
                GroupBox("指标") {
                    Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 8) {
                        ForEach(Array(status.metrics.keys.sorted()), id: \.self) { key in
                            GridRow {
                                Text(key)
                                    .foregroundColor(.secondary)
                                Text(String(format: "%.2f", status.metrics[key] ?? 0))
                                    .gridColumnAlignment(.trailing)
                            }
                        }
                    }
                    .padding(4)
                }
            }
        }
    }

    private func formatUptime(_ seconds: Double) -> String {
        let hours = Int(seconds) / 3600
        let minutes = (Int(seconds) % 3600) / 60
        return "\(hours)h \(minutes)m"
    }
}

struct StatusMetricCard: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundColor(.secondary)
            Text(value)
                .font(.system(size: 18, weight: .semibold, design: .rounded))
                .foregroundColor(color)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}
