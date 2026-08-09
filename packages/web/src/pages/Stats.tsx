import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  PiggyBank,
  TrendingUp,
  Clock,
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

// ===== ECharts 按需引入（只注册折线图所需模块，控制包体积） =====
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

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

// 省钱主题强调色（深绿，区别于荧光色，突出「省钱」维度）
const SAVE_GREEN = '#0a8f5c';

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

const formatCNYValue = (v: number) => `¥${v >= 100 ? v.toFixed(0) : v.toFixed(2)}`;

const hexToRgba = (hex: string, alpha: number) => {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

// ===== 省钱换算假设（可调参数）=====
// 无 CodePop 时 LLM 每次查询需读取的基线 token 数（与后端估算逻辑一致）
const BASELINE_TOKENS_PER_QUERY = 20000;
// 假设 LLM 输入 token 单价（Claude Opus 5 输入价），单位 USD / 1M tokens
const COST_PER_1M_TOKENS_USD = 5;
// 固定美元兑人民币汇率（演示用临时汇率，可随时调整）
const USD_TO_CNY = 7.2;

const tokensToUSD = (tokens: number) => (tokens / 1_000_000) * COST_PER_1M_TOKENS_USD;

const formatCNY = (tokens: number) => {
  const cny = tokensToUSD(tokens) * USD_TO_CNY;
  return `¥${cny >= 100 ? cny.toFixed(0) : cny.toFixed(2)}`;
};

// 单次查询节省的 token（基线 - 实际消耗，负值记为 0）
const savedTokensForQuery = (input: number, output: number) =>
  Math.max(0, BASELINE_TOKENS_PER_QUERY - (input + output));

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
  const cumulativeSaved = Math.max(0, cumulativeQueries * BASELINE_TOKENS_PER_QUERY - (cumulativeInputTokens + cumulativeOutputTokens));

  // 按天数聚合节省金额：今日（stats 接口直接给）、近 3 天 / 近 7 天（从 daily 聚合）
  const savedTokensByDays = (n: number) => {
    const daysSlice = (dailyStats || []).slice(-n);
    const queries = daysSlice.reduce((s, d) => s + d.totalQueries, 0);
    const input = daysSlice.reduce((s, d) => s + d.totalInputTokens, 0);
    const output = daysSlice.reduce((s, d) => s + d.totalOutputTokens, 0);
    return Math.max(0, queries * BASELINE_TOKENS_PER_QUERY - (input + output));
  };
  const todaySavedTokens = stats?.estimatedTokensSaved || 0;
  const saved3dTokens = savedTokensByDays(3);
  const saved7dTokens = savedTokensByDays(7);
  // 近 3 天 / 近 7 天 / 累计 省钱换算成人民币
  const saved3dCNY = tokensToUSD(saved3dTokens) * USD_TO_CNY;
  const saved7dCNY = tokensToUSD(saved7dTokens) * USD_TO_CNY;
  const todaySavedCNY = tokensToUSD(todaySavedTokens) * USD_TO_CNY;
  const cumulativeSavedCNY = tokensToUSD(cumulativeSaved) * USD_TO_CNY;
  const llmCostCNY = (llmCost?.total_cost || 0) * USD_TO_CNY;

  // 每日节省金额（用于「节省金额走势」折线图）
  const savedDailySeries = useMemo(() => {
    return (dailyStats || []).map((d) => {
      const savedTokens = Math.max(
        0,
        d.totalQueries * BASELINE_TOKENS_PER_QUERY - (d.totalInputTokens + d.totalOutputTokens),
      );
      return { date: d.date, cny: tokensToUSD(savedTokens) * USD_TO_CNY };
    });
  }, [dailyStats]);

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

  // ===== 折线图数据 =====
  const searchChartLabels = (dailyStats || []).map((d) => formatDate(d.date));
  const llmChartLabels = (llmDaily || []).map((d) => formatDate(d.date));
  const savedChartLabels = savedDailySeries.map((d) => formatDate(d.date));

  const cnyAxisFormatter = (v: number) => formatCNYValue(v);
  const tokenAxisFormatter = (v: number) => formatTokens(v);

  return (
    <div className="p-6 space-y-8 max-w-7xl mx-auto">
      {/* 页头 */}
      <div className="flex flex-wrap items-center justify-between gap-4">
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
            <p className="text-sm text-[#666]">查询消耗、省钱估算与 LLM 成本追踪</p>
          </div>
        </div>

        <div
          className="flex items-center gap-3 bg-white rounded-xl px-4 py-2.5 border-2"
          style={{ borderColor: STATS_COLORS.border, boxShadow: '4px 4px 0 #2D2D2D' }}
        >
          <label className="text-sm font-semibold text-[#666]">仓库：</label>
          <select
            value={selectedRepo || ''}
            onChange={(e) => setSelectedRepo(e.target.value || undefined)}
            className="px-3 py-1.5 rounded-lg border-2 outline-none focus:ring-2 bg-[#F5F5F0]"
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
      </div>

      {/* ===== ① 省钱统计（核心高亮） ===== */}
      <Section
        icon={<PiggyBank className="w-5 h-5 text-white" />}
        title="省钱统计"
        accent={SAVE_GREEN}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            money
            label="今日节省（估算）"
            value={todaySavedCNY}
            icon={<DollarSign className="w-5 h-5" />}
            color={SAVE_GREEN}
            format="cny"
            hint="按 20k/次基线 + 单价折算"
          />
          <StatCard
            money
            label="近 3 天节省（估算）"
            value={saved3dCNY}
            icon={<TrendingDown className="w-5 h-5" />}
            color={SAVE_GREEN}
            format="cny"
            hint="USD→CNY 按固定汇率 7.2"
          />
          <StatCard
            money
            label="近 7 天节省（估算）"
            value={saved7dCNY}
            icon={<ArrowUpRight className="w-5 h-5" />}
            color={SAVE_GREEN}
            format="cny"
            hint="USD→CNY 按固定汇率 7.2"
          />
          <StatCard
            money
            label={`近 ${days} 天累计节省`}
            value={cumulativeSavedCNY}
            icon={<PiggyBank className="w-5 h-5" />}
            color={SAVE_GREEN}
            format="cny"
            hint={`统计窗口为当前所选近 ${days} 天`}
          />
        </div>
        <p className="text-xs text-[#666] mt-4 leading-relaxed">
          估算口径：无 CodePop 时 LLM 每次查询需读取约 {BASELINE_TOKENS_PER_QUERY.toLocaleString()} token
          的基线代码；省下部分按 Claude Opus 5 输入单价 ${COST_PER_1M_TOKENS_USD}/1M tokens 计费，
          USD→CNY 汇率按 {USD_TO_CNY} 折算。金额仅为估算，供展示参考。
        </p>
      </Section>

      {/* ===== ② 今日检索概况 ===== */}
      <Section
        icon={<Search className="w-5 h-5 text-white" />}
        title="今日检索概况"
        subtitle="统计页检索接口的实际消耗"
        accent={STATS_COLORS.pink}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
            label="平均耗时（ms）"
            value={stats?.avgLatencyMs || 0}
            icon={<Clock className="w-5 h-5" />}
            color={STATS_COLORS.accent}
            format="number"
            hint="查询平均响应耗时"
          />
        </div>
      </Section>

      {/* ===== ③ LLM 消耗概况 ===== */}
      <Section
        icon={<Bot className="w-5 h-5 text-white" />}
        title={`LLM 消耗概况（近 ${days} 天）`}
        subtitle="启用在线 LLM 增强时的 token 与成本消耗"
        accent={STATS_COLORS.purple}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
            hint={`≈ ¥${formatCNYValue(llmCostCNY).slice(1)}`}
          />
        </div>
      </Section>

      {/* ===== ④ 趋势走势（7日/30日切换） ===== */}
      <Section
        icon={<Activity className="w-5 h-5 text-white" />}
        title="趋势走势"
        subtitle="切换「7 日 / 30 日」查看每日变化"
        accent={STATS_COLORS.teal}
      >
        {/* 节省金额走势 - 全宽突出 */}
        <div
          className="bg-white rounded-2xl p-6 border-2"
          style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
        >
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-2">
              <DollarSign className="w-5 h-5" style={{ color: SAVE_GREEN }} />
              <h3 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
                节省金额走势（估算）
              </h3>
            </div>
            <div className="flex gap-2">
              <PeriodButton active={days === 7} onClick={() => setDays(7)} label="7日" />
              <PeriodButton active={days === 30} onClick={() => setDays(30)} label="30日" />
            </div>
          </div>
          <PopLineChart
            series={[
              { name: '每日节省', color: SAVE_GREEN, data: savedDailySeries.map((d) => d.cny), area: true },
            ]}
            labels={savedChartLabels}
            showLegend={false}
            yFormatter={cnyAxisFormatter}
            valueFormatter={cnyAxisFormatter}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
          <div
            className="bg-white rounded-2xl p-6 border-2"
            style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
          >
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <h3 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
                搜索 Token 消耗走势
              </h3>
              <div className="flex gap-2">
                <PeriodButton active={days === 7} onClick={() => setDays(7)} label="7日" />
                <PeriodButton active={days === 30} onClick={() => setDays(30)} label="30日" />
              </div>
            </div>
            <PopLineChart
              series={[
                { name: '输入 Token', color: '#2ad4ff', data: (dailyStats || []).map((d) => d.totalInputTokens) },
                { name: '输出 Token', color: '#ff3d8a', data: (dailyStats || []).map((d) => d.totalOutputTokens) },
              ]}
              labels={searchChartLabels}
              yFormatter={tokenAxisFormatter}
              valueFormatter={(v) => `${formatTokens(v)} tokens`}
            />
          </div>

          <div
            className="bg-white rounded-2xl p-6 border-2"
            style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
          >
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <h3 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>
                LLM 消耗走势
              </h3>
              <div className="flex gap-2">
                <PeriodButton active={days === 7} onClick={() => setDays(7)} label="7日" />
                <PeriodButton active={days === 30} onClick={() => setDays(30)} label="30日" />
              </div>
            </div>
            <PopLineChart
              series={[
                { name: '输入 Token', color: '#b88dff', data: (llmDaily || []).map((d) => d.input_tokens) },
                { name: '输出 Token', color: '#ff8a3d', data: (llmDaily || []).map((d) => d.output_tokens) },
              ]}
              labels={llmChartLabels}
              yFormatter={tokenAxisFormatter}
              valueFormatter={(v) => `${formatTokens(v)} tokens`}
            />
          </div>
        </div>
      </Section>

      {/* ===== ⑤ 分布统计 ===== */}
      <Section
        icon={<Layers className="w-5 h-5 text-white" />}
        title="分布统计"
        subtitle="LLM 操作、Provider 与检索模式的占比"
        accent={STATS_COLORS.orange}
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div>
            <div className="flex items-center gap-2 mb-4">
              <Layers className="w-5 h-5" style={{ color: STATS_COLORS.purple }} />
              <h3 className="text-base font-bold" style={{ color: STATS_COLORS.border }}>
                LLM Operation 分布
              </h3>
            </div>
            {renderDistributionBars(operationBreakdownEntries, llmTotalTokens)}
          </div>

          <div>
            <div className="flex items-center gap-2 mb-4">
              <Server className="w-5 h-5" style={{ color: STATS_COLORS.teal }} />
              <h3 className="text-base font-bold" style={{ color: STATS_COLORS.border }}>
                Provider 分布
              </h3>
            </div>
            {renderProviderBars(llmCost)}
          </div>

          <div>
            <div className="flex items-center gap-2 mb-4">
              <Activity className="w-5 h-5" style={{ color: STATS_COLORS.pink }} />
              <h3 className="text-base font-bold" style={{ color: STATS_COLORS.border }}>
                搜索模式分布
              </h3>
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
      </Section>

      {/* ===== ⑥ 最近调用 ===== */}
      <Section
        icon={<FileText className="w-5 h-5 text-white" />}
        title="最近调用"
        subtitle="最近 10 次检索记录（含单次节省估算）"
        accent={STATS_COLORS.pink}
      >
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
                <th className="text-right py-3 px-4 font-bold text-sm text-[#666]">节省（估算）</th>
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
                  <td className="py-3 px-4 text-sm text-right text-[#0a8f5c] font-bold">
                    {formatCNY(savedTokensForQuery(item.inputTokens, item.outputTokens))}
                  </td>
                  <td className="py-3 px-4 text-sm text-right">{item.latencyMs}ms</td>
                  <td className="py-3 px-4 text-sm text-right text-[#999]">{formatTime(item.createdAt)}</td>
                </tr>
              ))}
              {(!recentItems || recentItems.length === 0) && (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-[#999]">
                    暂无调用记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ===== ⑦ 累计统计 ===== */}
      <Section
        icon={<TrendingUp className="w-5 h-5 text-white" />}
        title={`累计统计（近 ${days} 天）`}
        subtitle="当前所选仓库在统计窗口内的累计数据"
        accent={STATS_COLORS.yellow}
      >
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
      </Section>
    </div>
  );
};

// ===== 维度分组容器：波普风标题栏 + 内容区 =====
function Section({
  icon,
  title,
  subtitle,
  accent,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  accent: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="bg-white rounded-2xl border-2 overflow-hidden"
      style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}
    >
      <header
        className="flex items-center gap-3 px-6 py-4 border-b-2"
        style={{ borderColor: STATS_COLORS.border, backgroundColor: `${accent}18` }}
      >
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{ backgroundColor: accent, border: '2px solid #2D2D2D', boxShadow: '2px 2px 0 #2D2D2D' }}
        >
          {icon}
        </div>
        <div className="min-w-0">
          <h2 className="text-lg font-black leading-tight" style={{ color: STATS_COLORS.border }}>
            {title}
          </h2>
          {subtitle && <p className="text-xs text-[#666] mt-0.5">{subtitle}</p>}
        </div>
      </header>
      <div className="p-6">{children}</div>
    </section>
  );
}

// ===== ECharts 折线图封装（处理初始化 / 自适应缩放 / 主题色） =====
interface ChartSeries {
  name: string;
  color: string;
  data: number[];
  area?: boolean;
}

interface PopLineChartProps {
  series: ChartSeries[];
  labels: string[];
  height?: number;
  showLegend?: boolean;
  yFormatter?: (v: number) => string;
  valueFormatter?: (v: number) => string;
}

function PopLineChart({
  series,
  labels,
  height = 220,
  showLegend = true,
  yFormatter,
  valueFormatter,
}: PopLineChartProps) {
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);

  // 用稳定的回调 ref 绑定容器：数据到达后容器才挂载，此时初始化图表实例；卸载时销毁。
  // （不能放在空依赖的 useEffect 里做初始化——数据未到时容器不存在，effect 不会重跑。）
  const setContainerRef = useCallback((node: HTMLDivElement | null) => {
    if (node && !chartRef.current) {
      chartRef.current = echarts.init(node);
    } else if (!node && chartRef.current) {
      chartRef.current.dispose();
      chartRef.current = null;
    }
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);

    const option: Record<string, unknown> = {
      animationDuration: 400,
      grid: { top: showLegend ? 40 : 20, left: 8, right: 12, bottom: 4, containLabel: true },
      legend: showLegend
        ? {
            top: 0,
            right: 0,
            icon: 'roundRect',
            itemWidth: 18,
            itemHeight: 8,
            textStyle: { color: '#666', fontSize: 12 },
          }
        : undefined,
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#2D2D2D',
        borderColor: '#2D2D2D',
        borderWidth: 1,
        padding: [8, 12],
        textStyle: { color: '#fff', fontSize: 12 },
        formatter: (params: unknown) => {
          const items = params as Array<{ marker: string; seriesName: string; value: number; dataIndex: number }>;
          if (!items || items.length === 0) return '';
          const date = labels[items[0].dataIndex] || '';
          const body = items
            .map(
              (it) =>
                `${it.marker}<b>${it.seriesName}</b>：<b>${valueFormatter ? valueFormatter(it.value) : it.value}</b>`,
            )
            .join('<br/>');
          return `<div style="font-weight:700;margin-bottom:4px">${date}</div>${body}`;
        },
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#bbb' } },
        axisTick: { show: false },
        axisLabel: {
          color: '#666',
          fontSize: 11,
          interval: labels.length > 12 ? Math.ceil(labels.length / 8) : 0,
        },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#eee', type: 'dashed' } },
        axisLabel: { color: '#666', fontSize: 11, formatter: yFormatter },
      },
      series: series.map((s) => ({
        name: s.name,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        data: s.data,
        lineStyle: { width: 3, color: s.color },
        itemStyle: { color: s.color, borderColor: '#fff', borderWidth: 2 },
        areaStyle: s.area
          ? {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: hexToRgba(s.color, 0.35) },
                { offset: 1, color: hexToRgba(s.color, 0) },
              ]),
            }
          : undefined,
      })),
    };
    // strict 关闭，option 结构按上面字面量保证，类型上放宽为 any
    chart.setOption(option as any);
    return () => {
      window.removeEventListener('resize', onResize);
    };
  }, [series, labels, showLegend, yFormatter, valueFormatter]);

  if (labels.length === 0) {
    return <div className="flex items-center justify-center text-[#999]" style={{ height: 220 }}>暂无数据</div>;
  }

  return <div ref={setContainerRef} style={{ height, width: '100%' }} />;
}

interface StatCardProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  color: string;
  format: 'number' | 'tokens' | 'currency' | 'cny';
  hint?: string;
  small?: boolean;
  money?: boolean;
}

function StatCard({ label, value, icon, color, format, hint, small, money }: StatCardProps) {
  const displayValue =
    format === 'currency'
      ? formatCurrency(value)
      : format === 'cny'
      ? `¥${value >= 100 ? value.toFixed(0) : value.toFixed(2)}`
      : format === 'tokens'
      ? formatTokens(value)
      : String(value);

  const accentColor = money ? SAVE_GREEN : color;

  return (
    <div
      className={clsx('rounded-2xl border-2', small ? 'p-4' : 'p-6', money && 'bg-[#f0fff6]')}
      style={{ borderColor: money ? SAVE_GREEN : STATS_COLORS.border, boxShadow: small ? '4px 4px 0 #2D2D2D' : '6px 6px 0 #2D2D2D' }}
    >
      {!small && <div className="h-1 rounded-t-lg mb-4" style={{ backgroundColor: accentColor }} />}
      <div className="flex items-center justify-between">
        <div>
          <p className={clsx('text-[#666]', small ? 'text-xs' : 'text-sm')}>{label}</p>
          <p
            className={clsx('font-black mt-1 truncate', small ? 'text-2xl' : 'text-4xl')}
            style={{ color: money ? SAVE_GREEN : STATS_COLORS.border }}
          >
            {displayValue}
          </p>
          {hint && <p className="text-xs text-[#999] mt-2">{hint}</p>}
        </div>
        <div
          className={clsx('rounded-xl flex items-center justify-center', small ? 'w-8 h-8' : 'w-10 h-10')}
          style={{ backgroundColor: `${accentColor}20`, border: `2px solid ${accentColor}` }}
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

interface LLMCostBreakdown {
  input_tokens: number;
  output_tokens: number;
  call_count: number;
  cost: number;
}
