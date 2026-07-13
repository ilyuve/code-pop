import type { SearchResult, ScoreBreakdown } from '../types';
import { CodePreview } from './CodePreview';
import { FileText, Copy, CheckCircle, ChevronDown, BarChart3 } from 'lucide-react';
import { useState } from 'react';
import { clsx } from 'clsx';

interface SearchResultsProps {
  results: SearchResult[];
  isLoading?: boolean;
  unavailableSources?: string[];
}

const SCORE_LABELS: Record<string, string> = {
  vector: '向量',
  symbol: '符号',
  bm25: 'BM25',
  graph: '调用图',
  final: '综合',
};

const SCORE_COLORS: Record<string, string> = {
  vector: '#ff3d8a',
  symbol: '#2ad4ff',
  bm25: '#fff34d',
  graph: '#b88dff',
  final: '#6effb0',
};

const UNAVAILABLE_LABELS: Record<string, string> = {
  vector: '向量暂不可用',
  symbol: '符号暂不可用',
  bm25: 'BM25暂不可用',
  graph: '调用图暂不可用',
};

export const SearchResults = ({ results, isLoading, unavailableSources = [] }: SearchResultsProps) => {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleCopy = async (result: SearchResult) => {
    const code = result.code;
    await navigator.clipboard.writeText(code);
    setCopiedId(`${result.repoId}-${result.filePath}-${result.lineNumber}`);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const toggleExpand = (resultId: string) => {
    setExpandedId((prev) => (prev === resultId ? null : resultId));
  };

  const renderScoreBreakdown = (breakdown: ScoreBreakdown) => {
    const entries = Object.entries(breakdown)
      .filter(([, value]) => typeof value === 'number')
      .sort(([, a], [, b]) => (b as number) - (a as number));

    if (entries.length === 0) return null;

    return (
      <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-700/50 space-y-2">
        {entries.map(([key, value]) => {
          const percentage = Math.min(Math.max((value as number) * 100, 0), 100);
          const label = SCORE_LABELS[key] || key;
          const color = SCORE_COLORS[key] || '#94a3b8';
          return (
            <div key={key} className="flex items-center gap-3 text-sm">
              <span className="w-14 text-slate-500 dark:text-slate-400 shrink-0">{label}</span>
              <div className="flex-1 h-2 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${percentage}%`, backgroundColor: color }}
                />
              </div>
              <span className="w-14 text-right font-medium text-slate-700 dark:text-slate-300">
                {(value as number).toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 animate-pulse"
          >
            <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-1/3 mb-4" />
            <div className="h-20 bg-slate-100 dark:bg-slate-700/50 rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="text-center py-12 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
        <FileText className="w-12 h-12 mx-auto text-slate-300 dark:text-slate-600 mb-4" />
        <p className="text-slate-500 dark:text-slate-400">
          暂无搜索结果，请尝试其他关键词
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="text-sm text-slate-500 dark:text-slate-400 mb-4">
        找到 {results.length} 个匹配结果
      </div>
      {unavailableSources.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {unavailableSources.map((source) => (
            <span
              key={source}
              className="text-xs px-2 py-1 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-600 dark:text-yellow-400 rounded border border-yellow-200 dark:border-yellow-700"
            >
              {UNAVAILABLE_LABELS[source] || `${source}暂不可用`}
            </span>
          ))}
        </div>
      )}
      {results.map((result, index) => {
        const resultId = `${result.repoId}-${result.filePath}-${result.lineNumber}`;
        const isCopied = copiedId === resultId;
        const isExpanded = expandedId === resultId;

        return (
          <div
            key={index}
            className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden hover:border-indigo-200 dark:hover:border-indigo-700 transition-colors"
          >
            <div className="flex items-center justify-between px-4 py-3 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700">
              <div className="flex items-center gap-2 text-sm">
                <FileText className="w-4 h-4 text-slate-400" />
                <span className="text-slate-600 dark:text-slate-300">
                  {result.filePath}
                </span>
                <span className="text-slate-400">行 {result.lineNumber}</span>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => toggleExpand(resultId)}
                  className={clsx(
                    'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors',
                    isExpanded
                      ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                      : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600'
                  )}
                >
                  <BarChart3 className="w-3 h-3" />
                  <span>{result.score.toFixed(2)}</span>
                  <ChevronDown
                    className={clsx('w-3 h-3 transition-transform', isExpanded && 'rotate-180')}
                  />
                </button>
                <span className="text-xs px-2 py-1 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 rounded">
                  {result.repoName}
                </span>
                <button
                  onClick={() => handleCopy(result)}
                  className={clsx(
                    'p-1.5 rounded-lg transition-colors',
                    isCopied
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400'
                      : 'hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-400'
                  )}
                >
                  {isCopied ? (
                    <CheckCircle className="w-4 h-4" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>
            <CodePreview code={result.code} language="typescript" />
            {isExpanded && renderScoreBreakdown(result.scoreBreakdown)}
          </div>
        );
      })}
    </div>
  );
};
