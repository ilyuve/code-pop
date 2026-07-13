import { useState, useMemo } from 'react';
import { SearchBox } from '../components/SearchBox';
import { SearchResults } from '../components/SearchResults';
import { FlowView } from '../components/FlowView';
import { useSearch } from '../hooks/useSearch';
import { useRepos } from '../hooks/useRepos';
import { Filter, Code2, Layers, ArrowUpDown, GitBranch } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { searchContext } from '../api';
import { useStore } from '../store';
import type { CodeContext } from '../types';

const LANGUAGE_OPTIONS = ['python', 'typescript', 'javascript', 'go', 'java', 'rust', 'cpp'];
const SYMBOL_OPTIONS = ['function', 'class', 'interface', 'variable'];
const SORT_OPTIONS = [
  { value: 'relevance', label: '相关度' },
  { value: 'newest', label: '最新索引' },
];

export const Search = () => {
  const { repos } = useRepos();
  const { query, setQuery, results, isSearching, search, clearResults, recentSearches } =
    useSearch();
  const [selectedRepoId, setSelectedRepoId] = useState<string>('');
  const [selectedLanguage, setSelectedLanguage] = useState<string>('');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('relevance');
  const [viewMode, setViewMode] = useState<'simple' | 'smart'>('smart');
  const [contextResults, setContextResults] = useState<CodeContext | null>(null);

  const contextSearchMutation = useMutation({
    mutationFn: ({ query, repoId }: { query: string; repoId?: string }) =>
      searchContext(query, repoId),
    onSuccess: (context) => {
      setContextResults(context);
    },
  });

  const handleSearch = (searchQuery: string) => {
    if (searchQuery.trim()) {
      search(searchQuery, selectedRepoId || undefined);
      if (viewMode === 'smart') {
        contextSearchMutation.mutate({ query: searchQuery, repoId: selectedRepoId || undefined });
      }
    }
  };

  const handleRepoFilter = (repoId: string) => {
    setSelectedRepoId(repoId);
    if (query.trim()) {
      search(query, repoId || undefined);
      if (viewMode === 'smart') {
        contextSearchMutation.mutate({ query, repoId });
      }
    }
  };

  const handleViewModeChange = (mode: 'simple' | 'smart') => {
    setViewMode(mode);
    if (mode === 'smart' && query.trim()) {
      contextSearchMutation.mutate({ query, repoId: selectedRepoId || undefined });
    }
  };

  const filteredResults = useMemo(() => {
    let filtered = [...results];
    if (selectedLanguage) {
      filtered = filtered.filter((r) =>
        r.language?.toLowerCase().includes(selectedLanguage.toLowerCase())
      );
    }
    if (selectedSymbol) {
      filtered = filtered.filter((r) =>
        (r as any).symbolType?.toLowerCase() === selectedSymbol.toLowerCase()
      );
    }
    if (sortBy === 'newest') {
      filtered.sort((a, b) => (b.score || 0) - (a.score || 0));
    }
    return filtered;
  }, [results, selectedLanguage, selectedSymbol, sortBy]);

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Search Header */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">
          代码搜索
        </h2>
        <div className="flex flex-col md:flex-row gap-4 mb-4">
          <div className="flex-1">
            <SearchBox
              value={query}
              onChange={setQuery}
              onSearch={handleSearch}
              placeholder="输入搜索关键词，支持自然语言..."
              isSearching={isSearching}
              recentSearches={recentSearches}
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="w-5 h-5 text-slate-400" />
            <select
              value={selectedRepoId}
              onChange={(e) => handleRepoFilter(e.target.value)}
              className="px-4 py-2.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 min-w-[180px]"
            >
              <option value="">所有仓库</option>
              {repos.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2 bg-slate-100 dark:bg-slate-700 rounded-lg p-1">
            <button
              onClick={() => handleViewModeChange('simple')}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                viewMode === 'simple'
                  ? 'bg-white dark:bg-slate-600 text-slate-900 dark:text-white shadow-sm'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
            >
              简单模式
            </button>
            <button
              onClick={() => handleViewModeChange('smart')}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors flex items-center gap-1 ${
                viewMode === 'smart'
                  ? 'bg-white dark:bg-slate-600 text-slate-900 dark:text-white shadow-sm'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
            >
              <GitBranch className="w-3 h-3" />
              智能模式
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Code2 className="w-4 h-4 text-slate-400" />
            <select
              value={selectedLanguage}
              onChange={(e) => setSelectedLanguage(e.target.value)}
              className="px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">所有语言</option>
              {LANGUAGE_OPTIONS.map((lang) => (
                <option key={lang} value={lang}>
                  {lang}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-slate-400" />
            <select
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">所有符号类型</option>
              {SYMBOL_OPTIONS.map((sym) => (
                <option key={sym} value={sym}>
                  {sym}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <ArrowUpDown className="w-4 h-4 text-slate-400" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="px-3 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Search Results */}
      {viewMode === 'simple' ? (
        <SearchResults results={filteredResults} isLoading={isSearching} />
      ) : (
        contextResults ? (
          <FlowView context={contextResults} />
        ) : isSearching ? (
          <div className="text-center py-12 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500 mx-auto mb-4"></div>
            <p className="text-slate-500 dark:text-slate-400">智能分析中...</p>
          </div>
        ) : (
          <div className="text-center py-12 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
            <Code2 className="w-16 h-16 text-slate-300 mx-auto mb-4" />
            <p className="text-slate-500 dark:text-slate-400">在上方输入搜索关键词开始智能分析</p>
          </div>
        )
      )}

      {/* Search Tips */}
      {results.length === 0 && !isSearching && !query && (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-8">
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-4">
            搜索提示
          </h3>
          <ul className="space-y-3 text-slate-600 dark:text-slate-400">
            <li className="flex items-start gap-2">
              <span className="text-indigo-500">•</span>
              <span>输入代码片段或自然语言描述进行搜索</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-indigo-500">•</span>
              <span>使用仓库筛选器缩小搜索范围</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-indigo-500">•</span>
              <span>点击结果中的复制按钮快速复制代码</span>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
};
