import { useState } from 'react';
import { TrendingDown, Database, Cpu, FileText, Clock, Package, ArrowUpRight } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useRepos } from '../hooks/useRepos';
import { fetchSearchHistoryStats, fetchSearchHistoryDaily, fetchSearchHistoryRecent } from '../api';
import type { SearchHistoryDailyStats, SearchHistoryRecentItem } from '../types';
import { clsx } from 'clsx';

const STATS_COLORS = {
  queries: '#ff3d8a',
  inputTokens: '#2ad4ff',
  outputTokens: '#fff34d',
  saved: '#6effb0',
  accent: '#ff8a3d',
  border: '#2D2D2D',
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

  const cumulativeQueries = dailyStats?.reduce((sum, d) => sum + d.totalQueries, 0) || 0;
  const cumulativeInputTokens = dailyStats?.reduce((sum, d) => sum + d.totalInputTokens, 0) || 0;
  const cumulativeOutputTokens = dailyStats?.reduce((sum, d) => sum + d.totalOutputTokens, 0) || 0;
  const cumulativeSaved = Math.max(0, cumulativeQueries * 20000 - (cumulativeInputTokens + cumulativeOutputTokens));

  const formatTokens = (num: number) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return String(num);
  };

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
      case 'hybrid': return '#2ad4ff';
      case 'mcp_search': return '#ff3d8a';
      case 'symbol': return '#fff34d';
      default: return '#b88dff';
    }
  };

  const renderLineChart = (data: SearchHistoryDailyStats[]) => {
    if (!data || data.length === 0) {
      return (
        <div className="h-48 flex items-center justify-center text-[#999]">
          暂无数据
        </div>
      );
    }

    const maxToken = Math.max(
      ...data.map(d => d.totalInputTokens),
      ...data.map(d => d.totalOutputTokens),
      1
    );

    const pointsInput = data.map((d, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - (d.totalInputTokens / maxToken) * 90;
      return `${x},${y}`;
    }).join(' ');

    const pointsOutput = data.map((d, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - (d.totalOutputTokens / maxToken) * 90;
      return `${x},${y}`;
    }).join(' ');

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
          <polygon
            points={`0,100 ${pointsInput} 100,100`}
            fill="url(#inputGradient)"
          />
          <polygon
            points={`0,100 ${pointsOutput} 100,100`}
            fill="url(#outputGradient)"
          />
          <polyline
            points={pointsInput}
            fill="none"
            stroke="#2ad4ff"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <polyline
            points={pointsOutput}
            fill="none"
            stroke="#ff3d8a"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <div className="absolute bottom-0 left-0 right-0 flex justify-between px-4 text-xs text-[#666]">
          {data.map(d => (
            <span key={d.date}>{formatDate(d.date)}</span>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: `${STATS_COLORS.accent}20`, border: `2px solid ${STATS_COLORS.accent}`, boxShadow: '4px 4px 0 #2D2D2D' }}
          >
            <TrendingDown className="w-6 h-6" style={{ color: STATS_COLORS.accent }} />
          </div>
          <div>
            <h1 className="text-2xl font-black" style={{ color: STATS_COLORS.border }}>Token 统计</h1>
            <p className="text-sm text-[#666]">查询消耗、节省与调用追踪</p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl p-4 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '4px 4px 0 #2D2D2D' }}>
        <label className="text-sm font-semibold text-[#666] mr-3">仓库：</label>
        <select
          value={selectedRepo || ''}
          onChange={(e) => setSelectedRepo(e.target.value || undefined)}
          className="px-4 py-2 rounded-xl border-2 outline-none focus:ring-2"
          style={{ borderColor: STATS_COLORS.border }}
        >
          <option value="">全部仓库</option>
          {repos.map(repo => (
            <option key={repo.id} value={repo.id}>{repo.name}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl p-6 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}>
          <div className="h-1 rounded-t-lg mb-4" style={{ backgroundColor: STATS_COLORS.queries }} />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#666]">今日查询</p>
              <p className="text-4xl font-black mt-1" style={{ color: STATS_COLORS.border }}>{stats?.totalQueries || 0}</p>
            </div>
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.queries}20`, border: `2px solid ${STATS_COLORS.queries}` }}
            >
              <Search className="w-5 h-5" style={{ color: STATS_COLORS.queries }} />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}>
          <div className="h-1 rounded-t-lg mb-4" style={{ backgroundColor: STATS_COLORS.inputTokens }} />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#666]">今日输入 Token</p>
              <p className="text-4xl font-black mt-1" style={{ color: STATS_COLORS.border }}>{formatTokens(stats?.totalInputTokens || 0)}</p>
            </div>
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.inputTokens}20`, border: `2px solid ${STATS_COLORS.inputTokens}` }}
            >
              <FileText className="w-5 h-5" style={{ color: STATS_COLORS.inputTokens }} />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}>
          <div className="h-1 rounded-t-lg mb-4" style={{ backgroundColor: STATS_COLORS.outputTokens }} />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#666]">今日输出 Token</p>
              <p className="text-4xl font-black mt-1" style={{ color: STATS_COLORS.border }}>{formatTokens(stats?.totalOutputTokens || 0)}</p>
            </div>
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.outputTokens}20`, border: `2px solid ${STATS_COLORS.outputTokens}` }}
            >
              <Database className="w-5 h-5" style={{ color: STATS_COLORS.outputTokens }} />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}>
          <div className="h-1 rounded-t-lg mb-4" style={{ backgroundColor: STATS_COLORS.saved }} />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-[#666]">今日节省 Token（估算）</p>
              <p className="text-4xl font-black mt-1" style={{ color: STATS_COLORS.border }}>{formatTokens(stats?.estimatedTokensSaved || 0)}</p>
              <p className="text-xs text-[#999] mt-2">基于 20k/次基线估算，非精确值</p>
            </div>
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.saved}20`, border: `2px solid ${STATS_COLORS.saved}` }}
            >
              <ArrowUpRight className="w-5 h-5" style={{ color: STATS_COLORS.saved }} />
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl p-6 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold" style={{ color: STATS_COLORS.border }}>Token 消耗走势</h2>
          <div className="flex gap-2">
            <button
              onClick={() => setDays(7)}
              className={clsx('px-4 py-2 rounded-lg font-semibold transition-all', days === 7 ? 'bg-[#2D2D2D] text-white' : 'bg-[#F5F5F0] text-[#666]')}
            >
              7日
            </button>
            <button
              onClick={() => setDays(30)}
              className={clsx('px-4 py-2 rounded-lg font-semibold transition-all', days === 30 ? 'bg-[#2D2D2D] text-white' : 'bg-[#F5F5F0] text-[#666]')}
            >
              30日
            </button>
          </div>
        </div>
        {renderLineChart(dailyStats || [])}
        <div className="flex justify-center gap-6 mt-4 text-sm">
          <div className="flex items-center gap-2">
            <div className="w-4 h-1 rounded" style={{ backgroundColor: '#2ad4ff' }} />
            <span className="text-[#666]">输入 Token</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-1 rounded" style={{ backgroundColor: '#ff3d8a' }} />
            <span className="text-[#666]">输出 Token</span>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl p-6 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '6px 6px 0 #2D2D2D' }}>
        <h2 className="text-lg font-bold mb-4" style={{ color: STATS_COLORS.border }}>最近调用</h2>
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
                  <td className="py-3 px-4 text-sm text-right font-semibold">{formatTokens(item.inputTokens + item.outputTokens)}</td>
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

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl p-4 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '4px 4px 0 #2D2D2D' }}>
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.queries}20`, border: `2px solid ${STATS_COLORS.queries}` }}
            >
              <Search className="w-4 h-4" style={{ color: STATS_COLORS.queries }} />
            </div>
            <div>
              <p className="text-xs text-[#666]">累计查询</p>
              <p className="text-2xl font-black" style={{ color: STATS_COLORS.border }}>{cumulativeQueries}</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl p-4 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '4px 4px 0 #2D2D2D' }}>
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.inputTokens}20`, border: `2px solid ${STATS_COLORS.inputTokens}` }}
            >
              <FileText className="w-4 h-4" style={{ color: STATS_COLORS.inputTokens }} />
            </div>
            <div>
              <p className="text-xs text-[#666]">累计输入 Token</p>
              <p className="text-2xl font-black" style={{ color: STATS_COLORS.border }}>{formatTokens(cumulativeInputTokens)}</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl p-4 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '4px 4px 0 #2D2D2D' }}>
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.outputTokens}20`, border: `2px solid ${STATS_COLORS.outputTokens}` }}
            >
              <Database className="w-4 h-4" style={{ color: STATS_COLORS.outputTokens }} />
            </div>
            <div>
              <p className="text-xs text-[#666]">累计输出 Token</p>
              <p className="text-2xl font-black" style={{ color: STATS_COLORS.border }}>{formatTokens(cumulativeOutputTokens)}</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl p-4 border-2" style={{ borderColor: STATS_COLORS.border, boxShadow: '4px 4px 0 #2D2D2D' }}>
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: `${STATS_COLORS.saved}20`, border: `2px solid ${STATS_COLORS.saved}` }}
            >
              <ArrowUpRight className="w-4 h-4" style={{ color: STATS_COLORS.saved }} />
            </div>
            <div>
              <p className="text-xs text-[#666]">累计节省（估算）</p>
              <p className="text-2xl font-black" style={{ color: STATS_COLORS.border }}>{formatTokens(cumulativeSaved)}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
