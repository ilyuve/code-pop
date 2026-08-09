import { useMemo, useState } from 'react';
import {
  TrendingDown,
  Database,
  FileText,
  ArrowUpRight,
  Search,
  Bot,
  DollarSign,
  Activity,
  Layers,
  Server,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useRepos } from '../hooks/useRepos';
import {
  fetchSearchHistoryStats,
  fetchSearchHistoryDaily,
  fetchSearchHistoryRecent,
  fetchLLMUsage,
  fetchLLMCost,
  fetchLLMDailyUsage,
} from '../api';
import type {
  SearchHistoryDailyStats,
  SearchHistoryRecentItem,
  LLMCostEstimate,
  LLMUsageSummary,
  LLMDailyUsage,
} from '../types';
import { clsx } from 'clsx';

const STATS_COLORS = {
  queries: '#ff3d8a',
  inputTokens: '#2ad4ff',
  outputTokens: '#fff34d',
  saved: '#6effb0',
  accent: '#ff8a3d',
  border: '#2D2D2D',
  llmCalls: '#b88dff',
  llmCost: '#ff3d8a',
  purple: '#b88dff',
  teal: '#2ad4ff',
  pink: '#ff3d8a',
  yellow: '#fff34d',
  green: '#6effb0',
  orange: '#ff8a3d',
};

const OPERATION_COLORS: Record<string, string> = {
  enrich_chunk: STATS_COLORS.pink,
  enrich_symbol_flow: STATS_COLORS.teal,
  query_expand: STATS_COLORS.yellow,
  chat: STATS_COLORS.purple,
  embed: STATS_COLORS.green,
  unknown: STATS_COLORS.orange,
};

const formatTokens = (num: number) => {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return String(num);
};

const formatCurrency = (value: number) => {
  if (value === 0) return '$0.0000';
  if (value < 0.01) return `$${value.toFixed(6)}`;
  return `$${value.toFixed(4)}`;
};

export const Stats = () => {
  const { repos } = useRepos();
  const [selectedRepo, setSelectedRepo] = useState<string | undefined>();
  const [days, setDays] = useState(7);

  const { data: stats } = useQuery({
    queryKey: ['searchHistoryStats', selectedRepo],
    queryFn: () => fetchSearchHistoryStats(selectedRepo || undefined),
    refetchInterval: 30000,
  });

  const { data: dailyStats } = useQuery({
    queryKey: ['searchHistoryDaily', selectedRepo, days],
    queryFn: () => fetchSearchHistoryDaily(selectedRepo || undefined, days),
    refetchInterval: 30000,
  });

  const { data: recentItems } = useQuery({
    queryKey: ['searchHistoryRecent', selectedRepo],
    queryFn: () => fetchSearchHistoryRecent(selectedRepo || undefined, 10),
    refetchInterval: 30000,
  });

  const { data: llmUsage } = useQuery({
    queryKey: ['llmUsage', selectedRepo, days],
    queryFn: () => fetchLLMUsage(60, days),
    refetchInterval: 30000,
  });

  const { data: llmCost } = useQuery({
    queryKey: ['llmCost', selectedRepo, days],
    queryFn: () => fetchLLMCost(60, selectedRepo || undefined, days),
    refetchInterval: 30000,
  });

  const { data: llmDaily } = useQuery({
    queryKey: ['llmDaily', selectedRepo, days],
    queryFn: () => fetchLLMDailyUsage(days, selectedRepo || undefined),
    refetchInterval: 30000,
  });

  const cumulativeQueries = dailyStats?.reduce((sum, d) => sum + d.totalQueries, 0) || 0;
  const cumulativeInputTokens = dailyStats?.reduce((sum, d) => sum + d.totalInputTokens, 0) || 0;
  const cumulativeOutputTokens = dailyStats?.reduce((sum, d) => sum + d.totalOutputTokens, 0) || 0;
  const cumulativeSaved = Math.max(0, cumulativeQueries * 20000 - (cumulativeInputTokens + cumulativeOutputTokens));

  const modeDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    recentItems?.forEach((item) => {
      counts[item.mode] = (counts[item.mode] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [recentItems]);

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const getModeColor = (mode: string) => {
    switch (mode) {
      case 'hybrid':
        return '#2ad4ff';
      case 'mcp_search':
        return '#ff3d8a';
      case 'symbol':
        return '#fff34d';
      default:
        return '#b88dff';
    }
  };

  const renderLineChart = (data: SearchHistoryDailyStats[], inputKey: keyof SearchHistoryDailyStats = 'totalInputTokens', outputKey: keyof SearchHistoryDailyStats = 'totalOutputTokens') => {
    if (!data || data.length === 0) {
      return (
        <div className="h-48 flex items-center justify-center text-[#999]">暂无数据</div>
      );
    }

    const maxToken = Math.max(
      ...data.map((d) => (d[inputKey] as number) || 0),
      ...data.map((d) => (d[outputKey] as number) || 0),
      1,
    );

    const pointsInput = data
      .map((d, i) => {
        const x = data.length === 1 ? 50 : (i / (data.length - 1)) * 100;
        const y = 100 - (((d[inputKey] as number) || 0) / maxToken) * 90;
        return `${x},${y}`;
      })
      .join(' ');

    const pointsOutput = data
      .map((d, i) => {
        const x = data.length === 1 ? 50 : (i / (data.length - 1)) * 100;
        const y = 100 - (((d[outputKey] as number) || 0) / maxToken) * 90;
        return `${x},${y}`;
      })
      .join(' ');

    return (
      <div className="relative h-48">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
          <defs>
            <linearGradient id="inputGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#2ad4ff" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#2ad4ff" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="outputGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#ff3d8a" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#ff3d8a" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={`0,100 ${pointsInput} 100,100`} fill="url(#inputGradient)" />
          <polygon points={`0,100 ${pointsOutput} 100,100`} fill="url(#outputGradient)" />
          <polyline points={pointsInput} fill="none" stroke="#2ad4ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <polyline points={pointsOutput} fill="none" stroke="#ff3d8a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div className="absolute bottom-0 left-0 right-0 flex justify-between px-4 text-xs text-[#666]">
          {data.map((d) => (
            <span key={d.date}>{formatDate(d.date)}</span>
          ))}
        </div>
      </div>
    );
  };

  const renderLLMLineChart = (data: LLMDailyUsage[]) => {
    if (!data || data.length === 0) {
      return <div className="h-48 flex items-center justify-center text-[#999]">暂无数据</div>;
    }

    const maxToken = Math.max(...data.map((d) => d.input_tokens), ...data.map((d) => d.output_tokens), 1);

    const pointsInput = data
      .map((d, i) => {
        const x = data.length === 1 ? 50 : (i / (data.length - 1)) * 100;
        const y = 100 - (d.input_tokens / maxToken) * 90;
        return `${x},${y}`;
      })
      .join(' ');

    const pointsOutput = data
      .map((d, i) => {
        const x = data.length === 1 ? 50 : (i / (data.length - 1)) * 100;
        const y = 100 - (d.output_tokens / maxToken) * 90;
        return `${x},${y}`;
      })
      .join(' ');

    return (
      <div className="relative h-48">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
          <defs>
            <linearGradient id="llmInputGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#b88dff" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#b88dff" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="llmOutputGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#ff8a3d" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#ff8a3d" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={`0,100 ${pointsInput} 100,100`} fill="url(#llmInputGradient)" />
          <polygon points={`0,100 ${pointsOutput} 100,100`} fill="url(#llmOutputGradient)" />
          <polyline points={pointsInput} fill="none" stroke="#b88dff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <polyline points={pointsOutput} fill="none" stroke="#ff8a3d" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div className="absolute bottom-0 left-0 right-0 flex justify-between px-4 text-xs text-[#666]">
          {data.map((d) => (
            <span key={d.date}>{formatDate(d.date)}</span>
          ))}
        </div>
      </div>
    );
  };

  const renderDistributionBars = (
    data: [string, LLMCostBreakdown][],
    totalTokens: number,
  ) => {
    if (!data || data.length === 0) {
      return <div className="h-40 flex items-center justify-center text-[#999]">暂无数据</div>;
    }

    return (
      <div className="space-y-3">
        {data.map(([key, value]) => {
          const tokens = value.input_tokens + value.output_tokens;
          const percentage = totalTokens > 0 ? (tokens / totalTokens) * 100 : 0;
          const color = OPERATION_COLORS[key] || STATS_COLORS.purple;
          return (
            <div key={key}>
              <div className="flex justify-between text-sm mb-1">
                <span className="font-semibold text-[#2D2D2D]">{key}</span>
                <span className="text-[#666]">
                  {formatTokens(tokens)} ({percentage.toFixed(1)}%)
                </span>
              </div>
              <div className="h-3 w-full bg-[#F5F5F0] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.max(percentage, 1)}%`, backgroundColor: color }}
                />
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderProviderBars = (estimate?: LLMCostEstimate) => {
    const breakdown = estimate?.provider_breakdown;
    if (!breakdown || Object.keys(breakdown).length === 0) {
      return <div className="h-40 flex items-center justify-center text-[#999]">暂无数据</div>;
    }

    const total = (estimate?.total_input_tokens || 0) + (estimate?.total_output_tokens || 0);
    const entries = Object.entries(breakdown).sort((a, b) => {
      const ta = a[1].input_tokens + a[1].output_tokens;
      const tb = b[1].input_tokens + b[1].output_tokens;
      return tb - ta;
    });

    return (
      <div className="space-y-3">
        {entries.map(([name, value], index) => {
          const tokens = value.input_tokens + value.output_tokens;
          const percentage = total > 0 ? (tokens / total) * 100 : 0;
          const colors = [STATS_COLORS.pink, STATS_COLORS.teal, STATS_COLORS.yellow, STATS_COLORS.green, STATS_COLORS.purple];
          const color = colors[index % colors.length];
          return (
            <div key={name}>
              <div className="flex justify-between text-sm mb-1">
                <span className="font-semibold text-[#2D2D2D]">{name}</span>
                <span className="text-[#666]">
                  {formatTokens(tokens)} ({percentage.toFixed(1)}%)
                </span>
              </div>
              <div className="h-3 w-full bg-[#F5F5F0] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.max(percentage, 1)}%`, backgroundColor: color }}
                />
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const operationBreakdownEntries = useMemo(() => {
    if (!llmCost?.operation_breakdown) return [];
    return Object.entries(llmCost.operation_breakdown).sort(
      (a, b) => b[1].input_tokens + b[1].output_tokens - (a[1].input_tokens + a[1].output_tokens),
    );
  }, [llmCost]);

  const llmTotalTokens = (llmCost?.total_input_tokens || 0) + (llmCost?.total_output_tokens || 0);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{
              backgroundColor: `${STATS_COLORS.accent}20`,
              border: `2px solid ${STATS_COLORS.accent}`,
              boxShadow: '4px 4px 0 #2D2D2D',
            }}
          >
            <TrendingDown className="w-6 h-6" style={{ color: STATS_COLORS.accent }} />
          </div>
          <div>
            <h1 className="text-2xl font-black" style={{ color: STATS_COLORS.border }}>
              Token 统计
            </h1>
            <p className="text-sm text-[#666]">查询消耗、索引增强与 LLM 成本追踪</p>
          </div>
        </div>
      </div>

      <div
        className="bg-white rounded-2xl p-4 border-2"
        style={{ borderColor: STATS_COLORS.border, boxShadow: '4px 4px 0 #2D2D2D' }}
      >
        <label className="text-sm font-semibold text-[#666] mr-3">仓库：</label>
        <select
          value={selectedRepo || ''}
          onChange={(e) => setSelectedRepo(e.target.value || undefined)}
          className="px-4 py-2 rounded-xl border-2 outline-none focus:ring-2"
          style={{ borderColor: STATS_COLORS.border }}
        >
          <option value="">全部仓库</option>
          {repos.map((repo) => (
            <option key={repo.id} value={repo.id}>
              {repo.name}
            </option>
          ))}
        </select>
      </div>

      {/* Search stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="今日查询"
          value={stats?.totalQueries || 0}
          icon={<Search className="w-5 h-5" />}
          color={STATS_COLORS.queries}
          format="number"
        />
        <StatCard
          label="今日输入 Token"
          value={stats?.totalInputTokens || 0}
          icon={<FileText className="w-5 h-5" />}
          color={STATS_COLORS.inputTokens}
          format="tokens"
        />
        <StatCard
          label="今日输出 Token"
          value={stats?.totalOutputTokens || 0}
          icon={<Database className="w-5 h-5" />}
          color={STATS_COLORS.outputTokens}
          format="tokens"
        />
        <StatCard
          label="今日节省 Token（估算）"
          value={stats?.estimatedTokensSaved || 0}
          icon={<ArrowUpRight className="w-5 h-5" />}
          color={STATS_COLORS.saved}
          format="tokens"
          hint="基于 20k/次基线估算，非精确值"
        />
      </div>

      {/* LLM usage cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label={`${days}日 LLM 调用`}
          value={llmUsage?.total_calls || 0}
          icon={<Bot className="w-5 h-5" />}
          color={STATS_COLORS.llmCalls}
          format="number"
        />
        <StatCard
          label={`${days}日 LLM 输入 Token`}
          value={llmCost?.total_input_tokens || 0}
          icon={<FileText className="w-5 h-5" />}
          color={STATS_COLORS.inputTokens}
          format="tokens"
        />
        <StatCard
          label={`${days}日 LLM 输出 Token`}
          value={llmCost?.total_output_tokens || 0}
          icon={<Database className="w-5 h-5" />}
          color={STATS_COLORS.outputTokens}
          format="tokens"
        />
        <StatCard
          label={`${days}日 LLM 成本（估算）`}
          value={llmCost?.total_cost || 0}
          icon={<DollarSign className="w-5 h-5" />}
          color={STATS_COLORS.llmCost}
          format="currency"
        />
      </div>

      {/* Trend charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div
          className="bg-white rounded-2xl p-6 border-2"
          style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
              搜索 Token 消耗走势
            </h2>
            <div className="flex gap-2">
              <PeriodButton active={days === 7} onClick={() => setDays(7)} label="7日" />
              <PeriodButton active={days === 30} onClick={() => setDays(30)} label="30日" />
            </div>
          </div>
          {renderLineChart(dailyStats || [])}
          <div className="flex justify-center gap-6 mt-4 text-sm">
            <Legend color="#2ad4ff" label="输入 Token" />
            <Legend color="#ff3d8a" label="输出 Token" />
          </div>
        </div>

        <div
          className="bg-white rounded-2xl p-6 border-2"
          style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
              LLM 消耗走势
            </h2>
            <div className="flex gap-2">
              <PeriodButton active={days === 7} onClick={() => setDays(7)} label="7日" />
              <PeriodButton active={days === 30} onClick={() => setDays(30)} label="30日" />
            </div>
          </div>
          {renderLLMLineChart(llmDaily || [])}
          <div className="flex justify-center gap-6 mt-4 text-sm">
            <Legend color="#b88dff" label="输入 Token" />
            <Legend color="#ff8a3d" label="输出 Token" />
          </div>
        </div>
      </div>

      {/* Distribution charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div
          className="bg-white rounded-2xl p-6 border-2"
          style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <div className="flex items-center gap-3 mb-4">
            <Layers className="w-5 h-5" style={{ color: STATS_COLORS.purple }} />
            <h2 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
              LLM Operation 分布
            </h2>
          </div>
          {renderDistributionBars(operationBreakdownEntries, llmTotalTokens)}
        </div>

        <div
          className="bg-white rounded-2xl p-6 border-2"
          style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <div className="flex items-center gap-3 mb-4">
            <Server className="w-5 h-5" style={{ color: STATS_COLORS.teal }} />
            <h2 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
              Provider 分布
            </h2>
          </div>
          {renderProviderBars(llmCost)}
        </div>

        <div
          className="bg-white rounded-2xl p-6 border-2"
          style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <div className="flex items-center gap-3 mb-4">
            <Activity className="w-5 h-5" style={{ color: STATS_COLORS.pink }} />
            <h2 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
              搜索模式分布
            </h2>
          </div>
          {modeDistribution.length === 0 ? (
            <div className="h-40 flex items-center justify-center text-[#999]">暂无数据</div>
          ) : (
            <div className="space-y-3">
              {modeDistribution.map(([mode, count]) => {
                const total = recentItems?.length || 1;
                const percentage = (count / total) * 100;
                return (
                  <div key={mode}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-semibold text-[#2D2D2D]">{mode}</span>
                      <span className="text-[#666]">
                        {count} 次 ({percentage.toFixed(1)}%)
                      </span>
                    </div>
                    <div className="h-3 w-full bg-[#F5F5F0] rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${Math.max(percentage, 1)}%`, backgroundColor: getModeColor(mode) }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Recent calls */}
      <div
        className="bg-white rounded-2xl p-6 border-2"
        style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
      >
        <h2 className="text-lg font-bold mb-4" style={{ color: STATS_COLORS.border }}>
          最近调用
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b-2" style={{ borderColor: STATS_COLORS.border }}>
                <th className="text-left py-3 px-4 font-bold text-sm text-[#666]">查询语句</th>
                <th className="text-left py-3 px-4 font-bold text-sm text-[#666]">模式</th>
                <th className="text-left py-3 px-4 font-bold text-sm text-[#666]">仓库</th>
                <th className="text-right py-3 px-4 font-bold text-sm text-[#666]">输入 Token</th>
                <th className="text-right py-3 px-4 font-bold text-sm text-[#666]">输出 Token</th>
                <th className="text-right py-3 px-4 font-bold text-sm text-[#666]">合计</th>
                <th className="text-right py-3 px-4 font-bold text-sm text-[#666]">耗时</th>
                <th className="text-right py-3 px-4 font-bold text-sm text-[#666]">时间</th>
              </tr>
            </thead>
            <tbody>
              {recentItems?.map((item: SearchHistoryRecentItem) => (
                <tr key={item.id} className="border-b border-slate-100 hover:bg-[#F5F5F0]">
                  <td className="py-3 px-4">
                    <span className="text-sm truncate max-w-xs inline-block" title={item.query}>
                      {item.query}
                    </span>
                  </td>
                  <td className="py-3 px-4">
                    <span
                      className="px-2 py-1 rounded text-xs font-semibold"
                      style={{ backgroundColor: `${getModeColor(item.mode)}20`, color: getModeColor(item.mode) }}
                    >
                      {item.mode}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-sm text-[#666]">{item.repoName || '-'}</td>
                  <td className="py-3 px-4 text-sm text-right">{formatTokens(item.inputTokens)}</td>
                  <td className="py-3 px-4 text-sm text-right">{formatTokens(item.outputTokens)}</td>
                  <td className="py-3 px-4 text-sm text-right font-semibold">
                    {formatTokens(item.inputTokens + item.outputTokens)}
                  </td>
                  <td className="py-3 px-4 text-sm text-right">{item.latencyMs}ms</td>
                  <td className="py-3 px-4 text-sm text-right text-[#999]">{formatTime(item.createdAt)}</td>
                </tr>
              ))}
              {(!recentItems || recentItems.length === 0) && (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-[#999]">
                    暂无调用记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Cumulative stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="累计查询" value={cumulativeQueries} icon={<Search className="w-4 h-4" />} color={STATS_COLORS.queries} format="number" small />
        <StatCard
          label="累计输入 Token"
          value={cumulativeInputTokens}
          icon={<FileText className="w-4 h-4" />}
          color={STATS_COLORS.inputTokens}
          format="tokens"
          small
        />
        <StatCard
          label="累计输出 Token"
          value={cumulativeOutputTokens}
          icon={<Database className="w-4 h-4" />}
          color={STATS_COLORS.outputTokens}
          format="tokens"
          small
        />
        <StatCard
          label="累计节省（估算）"
          value={cumulativeSaved}
          icon={<ArrowUpRight className="w-4 h-4" />}
          color={STATS_COLORS.saved}
          format="tokens"
          small
        />
      </div>
    </div>
  );
};

interface StatCardProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  color: string;
  format: 'number' | 'tokens' | 'currency';
  hint?: string;
  small?: boolean;
}

function StatCard({ label, value, icon, color, format, hint, small }: StatCardProps) {
  const displayValue =
    format === 'currency'
      ? formatCurrency(value)
      : format === 'tokens'
      ? formatTokens(value)
      : String(value);

  return (
    <div
      className={clsx('bg-white rounded-2xl border-2', small ? 'p-4' : 'p-6')}
      style={{ borderColor: STATS_COLORS.border, boxShadow: small ? '4px 4px 0 #2D2D2D' : '6px 6px 0 #2D2D2D' }}
    >
      {!small && <div className="h-1 rounded-t-lg mb-4" style={{ backgroundColor: color }} />}
      <div className="flex items-center justify-between">
        <div>
          <p className={clsx('text-[#666]', small ? 'text-xs' : 'text-sm')}>{label}</p>
          <p className={clsx('font-black mt-1', small ? 'text-2xl' : 'text-4xl')} style={{ color: STATS_COLORS.border }}>
            {displayValue}
          </p>
          {hint && <p className="text-xs text-[#999] mt-2">{hint}</p>}
        </div>
        <div
          className={clsx('rounded-xl flex items-center justify-center', small ? 'w-8 h-8' : 'w-10 h-10')}
          style={{ backgroundColor: `${color}20`, border: `2px solid ${color}` }}
        >
          {icon}
        </div>
      </div>
    </div>
  );
}

function PeriodButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={clsx('px-4 py-2 rounded-lg font-semibold transition-all', active ? 'bg-[#2D2D2D] text-white' : 'bg-[#F5F5F0] text-[#666]')}
    >
      {label}
    </button>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="w-4 h-1 rounded" style={{ backgroundColor: color }} />
      <span className="text-[#666]">{label}</span>
    </div>
  );
}

interface LLMCostBreakdown {
  input_tokens: number;
  output_tokens: number;
  call_count: number;
  cost: number;
}
