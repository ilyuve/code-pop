import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { BarChart3, Play, Loader2, TrendingDown, Clock, Database, Target } from 'lucide-react';
import { useRepos } from '../hooks/useRepos';
import { runBenchmark, fetchBenchmarks, fetchBenchmarkSummary } from '../api';
import { clsx } from 'clsx';

export const Benchmark = () => {
  const { repos } = useRepos();
  const [queries, setQueries] = useState('how is authentication handled?\nwhere is the database initialized?');
  const [selectedRepo, setSelectedRepo] = useState('');
  const [mode, setMode] = useState<'with_codepop' | 'without_codepop'>('with_codepop');

  const { data: runs, refetch: refetchRuns } = useQuery({
    queryKey: ['benchmarks'],
    queryFn: () => fetchBenchmarks(),
  });

  const { data: summary, refetch: refetchSummary } = useQuery({
    queryKey: ['benchmarkSummary'],
    queryFn: () => fetchBenchmarkSummary(),
  });

  const benchmarkMutation = useMutation({
    mutationFn: runBenchmark,
    onSuccess: () => {
      refetchRuns();
      refetchSummary();
    },
  });

  const handleRun = async () => {
    const queryList = queries.split('\n').map((q) => q.trim()).filter(Boolean);
    for (const query of queryList) {
      await benchmarkMutation.mutateAsync({
        query,
        repo_id: selectedRepo || undefined,
        mode,
        expected_files: [],
        expected_lines: [],
      });
    }
  };

  const maxLatency = Math.max(
    ...(summary?.latencyTrend.map((t) => t.latencyMs) || [1]),
    1
  );

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-3">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center"
          style={{ background: '#b88dff', border: '2px solid #2D2D2D', boxShadow: '4px 4px 0 #2D2D2D' }}
        >
          <BarChart3 className="w-6 h-6 text-white" />
        </div>
        <div>
          <h1 className="text-2xl font-black text-[#2D2D2D]">评测中心</h1>
          <p className="text-[#666]">量化 CodePop 对检索质量和 token 消耗的影响</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section
          className="lg:col-span-1 bg-white rounded-2xl p-6 space-y-4"
          style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <h2 className="text-lg font-black flex items-center gap-2">
            <Play className="w-5 h-5" style={{ color: '#ff3d8a' }} />
            运行评测
          </h2>

          <div>
            <label className="block text-sm font-medium text-[#666] mb-1">测试查询（每行一个）</label>
            <textarea
              value={queries}
              onChange={(e) => setQueries(e.target.value)}
              rows={6}
              className="w-full px-3 py-2 rounded-xl border-2 border-[#2D2D2D] bg-[#F5F5F0] focus:outline-none focus:ring-2 focus:ring-[#ff3d8a]"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[#666] mb-1">目标仓库</label>
            <select
              value={selectedRepo}
              onChange={(e) => setSelectedRepo(e.target.value)}
              className="w-full px-3 py-2 rounded-xl border-2 border-[#2D2D2D] bg-[#F5F5F0]"
            >
              <option value="">全部仓库</option>
              {repos.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-[#666] mb-1">对比模式</label>
            <div className="flex gap-2">
              {(['with_codepop', 'without_codepop'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={clsx(
                    'flex-1 px-3 py-2 rounded-xl text-sm font-bold border-2 transition-colors',
                    mode === m
                      ? 'bg-[#2D2D2D] text-white border-[#2D2D2D]'
                      : 'bg-white text-[#666] border-[#2D2D2D] hover:bg-[#F5F5F0]'
                  )}
                >
                  {m === 'with_codepop' ? '使用 CodePop' : 'Baseline'}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={handleRun}
            disabled={benchmarkMutation.isPending}
            className="w-full py-3 rounded-xl font-bold flex items-center justify-center gap-2 transition-transform active:scale-95 disabled:opacity-60"
            style={{ background: '#ff3d8a', color: 'white', border: '2px solid #2D2D2D', boxShadow: '4px 4px 0 #2D2D2D' }}
          >
            {benchmarkMutation.isPending ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Play className="w-5 h-5" />
            )}
            开始评测
          </button>
        </section>

        <section
          className="lg:col-span-2 bg-white rounded-2xl p-6"
          style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <h2 className="text-lg font-black flex items-center gap-2 mb-4">
            <TrendingDown className="w-5 h-5" style={{ color: '#2ad4ff' }} />
            对比概览
          </h2>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            {[
              { label: '总运行次数', value: summary?.totalRuns ?? 0, icon: Database, color: '#ff3d8a' },
              { label: '平均耗时 (ms)', value: summary?.avgLatencyMs?.toFixed(0) ?? '-', icon: Clock, color: '#2ad4ff' },
              { label: '平均 Token', value: summary?.avgTokenConsumed?.toFixed(0) ?? '-', icon: Database, color: '#fff34d' },
              { label: '平均准确率', value: summary?.avgAccuracyScore ? `${(summary.avgAccuracyScore * 100).toFixed(0)}%` : '-', icon: Target, color: '#6effb0' },
            ].map((stat) => (
              <div
                key={stat.label}
                className="p-4 rounded-xl"
                style={{ background: '#F5F5F0', border: '2px solid #2D2D2D' }}
              >
                <stat.icon className="w-5 h-5 mb-2" style={{ color: stat.color }} />
                <p className="text-xs text-[#666]">{stat.label}</p>
                <p className="text-xl font-black">{stat.value}</p>
              </div>
            ))}
          </div>

          {summary?.savingsVsBaseline && (
            <div className="mb-6 p-4 rounded-xl" style={{ background: '#6effb020', border: '2px solid #2D2D2D' }}>
              <p className="font-bold mb-2">相比 Baseline 节省</p>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-[#666]">耗时</p>
                  <p className="text-lg font-black">
                    {summary.savingsVsBaseline.latency_percent ?? 0}%
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[#666]">Token</p>
                  <p className="text-lg font-black">
                    {summary.savingsVsBaseline.token_percent ?? 0}%
                  </p>
                </div>
              </div>
            </div>
          )}

          <h3 className="font-bold mb-3">延迟趋势</h3>
          <div className="h-40 flex items-end gap-1">
            {(summary?.latencyTrend || []).map((point, i) => (
              <div
                key={i}
                className="flex-1 rounded-t bg-[#2ad4ff] hover:bg-[#ff3d8a] transition-colors relative group"
                style={{ height: `${(point.latencyMs / maxLatency) * 100}%`, minHeight: 4 }}
              >
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block text-xs bg-[#2D2D2D] text-white px-2 py-1 rounded whitespace-nowrap">
                  {point.latencyMs}ms
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section
        className="bg-white rounded-2xl p-6"
        style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
      >
        <h2 className="text-lg font-black mb-4">评测记录</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b-2 border-[#2D2D2D]">
                <th className="text-left py-2 px-3">查询</th>
                <th className="text-left py-2 px-3">模式</th>
                <th className="text-right py-2 px-3">耗时 (ms)</th>
                <th className="text-right py-2 px-3">结果数</th>
                <th className="text-right py-2 px-3">相关数</th>
                <th className="text-right py-2 px-3">Token</th>
                <th className="text-right py-2 px-3">准确率</th>
              </tr>
            </thead>
            <tbody>
              {(runs || []).map((run) => (
                <tr key={run.id} className="border-b border-slate-100 hover:bg-[#F5F5F0]">
                  <td className="py-2 px-3 max-w-xs truncate">{run.query}</td>
                  <td className="py-2 px-3">
                    <span
                      className="px-2 py-1 rounded text-xs font-bold"
                      style={{
                        background: run.mode === 'with_codepop' ? '#6effb020' : '#fff34d20',
                        color: '#2D2D2D',
                      }}
                    >
                      {run.mode === 'with_codepop' ? 'CodePop' : 'Baseline'}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-right">{run.latencyMs}</td>
                  <td className="py-2 px-3 text-right">{run.resultsCount}</td>
                  <td className="py-2 px-3 text-right">{run.relevantResultsCount}</td>
                  <td className="py-2 px-3 text-right">{run.tokenConsumed}</td>
                  <td className="py-2 px-3 text-right">{(run.accuracyScore * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};
