import { useState } from 'react';
import { SearchBox } from '../components/SearchBox';
import { FlowView } from '../components/FlowView';
import { useSearch } from '../hooks/useSearch';
import { useRepos } from '../hooks/useRepos';
import { Code2, FolderGit2, Sparkles } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { searchContext } from '../api';
import type { CodeContext } from '../types';

const SAMPLE_QUERIES = [
  '订单支付回调流程',
  '用户登录如何校验',
  '消息推送在哪里实现',
  'handlePayCallback 怎么调用',
];

export const Search = () => {
  const { repos } = useRepos();
  const { query, setQuery, isSearching, search, recentSearches } = useSearch();
  const [selectedRepoId, setSelectedRepoId] = useState<string>('');
  const [contextResults, setContextResults] = useState<CodeContext | null>(null);

  const contextSearchMutation = useMutation({
    mutationFn: ({ query, repoId }: { query: string; repoId?: string }) =>
      searchContext(query, repoId),
    onSuccess: (context) => {
      setContextResults(context);
    },
  });

  const handleSearch = (searchQuery: string) => {
    if (!searchQuery.trim()) return;
    search(searchQuery, selectedRepoId || undefined);
    contextSearchMutation.mutate({ query: searchQuery, repoId: selectedRepoId || undefined });
  };

  const handleRepoFilter = (repoId: string) => {
    setSelectedRepoId(repoId);
    if (query.trim()) {
      search(query, repoId || undefined);
      contextSearchMutation.mutate({ query, repoId });
    }
  };

  const handleSampleQuery = (sample: string) => {
    setQuery(sample);
    handleSearch(sample);
  };

  const showEmptyState = !query && !contextResults && !isSearching && !contextSearchMutation.isPending;
  const showLoading = isSearching || contextSearchMutation.isPending;
  const showError = contextSearchMutation.isError && !contextResults;

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Search Header */}
      <div className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D] p-6">
        <h2 className="text-lg font-black text-[#2D2D2D] mb-4">
          代码智能搜索
        </h2>
        <p className="text-sm text-[#666] font-medium -mt-2 mb-4">
          用自然语言描述需求，检索代码中的实现入口、调用链与相关文件
        </p>
        <div className="flex flex-col md:flex-row gap-4 mb-4">
          <div className="flex-1">
            <SearchBox
              value={query}
              onChange={setQuery}
              onSearch={handleSearch}
              placeholder="输入自然语言描述，如：订单支付回调流程..."
              isSearching={showLoading}
              recentSearches={recentSearches}
            />
          </div>
          <div className="flex items-center gap-2">
            <FolderGit2 className="w-5 h-5 text-[#666]" />
            <select
              value={selectedRepoId}
              onChange={(e) => handleRepoFilter(e.target.value)}
              className="px-4 py-2.5 bg-white border-2 border-[#2D2D2D] rounded-lg text-[#2D2D2D] font-bold focus:outline-none focus:border-[#2ad4ff] shadow-[3px_3px_0_#2D2D2D] min-w-[180px]"
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
      </div>

      {/* Search Results */}
      {showEmptyState ? (
        <div className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D] p-8">
          <div className="flex items-center gap-3 mb-6">
            <Code2 className="w-8 h-8 text-[#b88dff]" />
            <div>
              <h3 className="text-lg font-black text-[#2D2D2D]">
                试试这些检索问题
              </h3>
              <p className="text-sm text-[#666] font-medium">
                选择下面的示例，或输入你自己的问题
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {SAMPLE_QUERIES.map((sample) => (
              <button
                key={sample}
                onClick={() => handleSampleQuery(sample)}
                className="flex items-center gap-2 px-4 py-3 bg-[#F5F5F0] hover:bg-[#fff34d] rounded-lg border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] hover:translate-y-[-2px] hover:shadow-[5px_5px_0_#2D2D2D] transition-all text-left font-medium"
              >
                <Sparkles className="w-4 h-4 text-[#ff3d8a] shrink-0" />
                <span className="text-sm text-[#2D2D2D]">{sample}</span>
              </button>
            ))}
          </div>
        </div>
      ) : showLoading ? (
        <div className="text-center py-12 bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D]">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#ff3d8a] mx-auto mb-4"></div>
          <p className="text-[#666] font-medium">智能分析中...</p>
        </div>
      ) : showError ? (
        <div className="text-center py-12 bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D]">
          <Code2 className="w-16 h-16 text-[#ff3d8a] mx-auto mb-4" />
          <p className="text-[#666] font-medium">
            检索失败，请稍后重试或更换关键词
          </p>
        </div>
      ) : contextResults ? (
        <FlowView context={contextResults} />
      ) : null}
    </div>
  );
};
