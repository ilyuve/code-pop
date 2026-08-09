import { Link } from 'react-router-dom';
import { RefreshCw, Trash2, Clock, GitBranch, Search, Hash, Layers, Network } from 'lucide-react';
import type { Repo } from '../types';
import { StatusBadge } from './StatusBadge';
import { RepoProviderIcon } from './RepoProviderIcon';
import { clsx } from 'clsx';

const MAX_ACTIVE_BRANCHES = 2;

interface RepoCardProps {
  repo: Repo;
  onDelete?: (id: string) => void;
  onReindex?: (id: string) => void;
  isDeleting?: boolean;
  isReindexing?: boolean;
  indexingProgress?: number;
  indexingStage?: string;
  stageProgress?: {
    stage: string;
    current: number;
    total: number;
    percentage: number;
  };
}

export const RepoCard = ({
  repo,
  onDelete,
  onReindex,
  isDeleting,
  isReindexing,
  indexingProgress = 0,
  indexingStage = '',
  stageProgress,
}: RepoCardProps) => {
  const getStageIcon = (stage: string) => {
    switch (stage) {
      case 'git_sync': return <GitBranch className="w-4 h-4" />;
      case 'scan': return <Search className="w-4 h-4" />;
      case 'symbols': return <Hash className="w-4 h-4" />;
      case 'embeddings': return <Layers className="w-4 h-4" />;
      case 'call_graph': return <Network className="w-4 h-4" />;
      default: return <RefreshCw className="w-4 h-4" />;
    }
  };

  const getStageName = (stage: string) => {
    switch (stage) {
      case 'git_sync': return '同步代码';
      case 'scan': return '扫描文件';
      case 'symbols': return '提取符号';
      case 'embeddings': return '生成向量';
      case 'call_graph': return '构建调用图';
      default: return '索引中';
    }
  };
  return (
    <div className="bg-white rounded-xl border-2 border-[#2D2D2D] p-5 shadow-[6px_6px_0_#2D2D2D] transition-all duration-200 hover:translate-y-[-4px] hover:shadow-[8px_8px_0_#2D2D2D]">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <RepoProviderIcon gitUrl={repo.gitUrl} />
          <div>
            <Link
              to={`/repos/${repo.id}`}
              className="font-bold text-[#2D2D2D] hover:text-[#ff3d8a] transition-colors"
            >
              {repo.name}
            </Link>
            {repo.description && (
              <p className="text-sm text-[#666] truncate max-w-xs">
                {repo.description}
              </p>
            )}
            <p className="text-xs text-[#999] truncate max-w-xs font-mono">
              {repo.path}
            </p>
            <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
              <span
                className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border-2 border-[#2D2D2D] bg-[#2ad4ff] text-[#2D2D2D] font-bold"
                title="默认分支"
              >
                <GitBranch className="w-3 h-3" />
                {repo.defaultBranch}
              </span>
              {repo.activeBranches && repo.activeBranches.length > 0 && repo.activeBranches
                .filter((b) => b !== repo.defaultBranch)
                .slice(0, MAX_ACTIVE_BRANCHES)
                .map((branch) => (
                  <span
                    key={branch}
                    className="text-xs px-2 py-0.5 rounded-full border-2 border-[#2D2D2D] bg-[#fff34d] text-[#2D2D2D] font-bold"
                    title="业务分支"
                  >
                    {branch}
                  </span>
                ))}
            </div>
          </div>
        </div>
        <StatusBadge status={repo.status} />
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
        <div>
          <p className="text-[#999] font-medium">文件数</p>
          <p className="font-bold text-[#2D2D2D]">
            {repo.indexedFiles} / {repo.totalFiles}
          </p>
        </div>
        <div>
          <p className="text-[#999] font-medium">创建时间</p>
          <p className="font-bold text-[#2D2D2D] flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {new Date(repo.createdAt).toLocaleDateString()}
          </p>
        </div>
        <div>
          <p className="text-[#999] font-medium">最后索引</p>
          <p className="font-bold text-[#2D2D2D]">
            {repo.lastIndexedAt
              ? new Date(repo.lastIndexedAt).toLocaleDateString()
              : '-'}
          </p>
        </div>
      </div>

      {repo.status === 'indexing' && (
        <div className="mb-4 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-[#999] font-medium">索引阶段</span>
              <span className="flex items-center gap-1 font-bold text-[#2ad4ff]">
                {getStageIcon(indexingStage)}
                {getStageName(indexingStage)}
              </span>
            </div>
            <span className="font-bold text-[#ff3d8a]">
              {Math.round(indexingProgress)}%
            </span>
          </div>
          <div className="h-3 bg-[#F5F5F0] border-2 border-[#2D2D2D] rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-[#ff3d8a] to-[#2ad4ff] transition-all duration-300"
              style={{
                width: `${indexingProgress}%`,
              }}
            />
          </div>
          {stageProgress && stageProgress.total > 0 && (
            <div className="text-xs text-[#999] font-medium">
              {stageProgress.current}/{stageProgress.total} ({Math.round(stageProgress.percentage)}%)
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2 pt-3 border-t-2 border-[#2D2D2D]">
        <Link
          to={`/repos/${repo.id}`}
          className="flex-1 px-3 py-2 text-sm text-center font-bold bg-[#fffbdd] hover:bg-[#fff8b8] text-[#2D2D2D] border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] rounded-lg transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[5px_5px_0_#2D2D2D]"
        >
          查看详情
        </Link>
        <button
          onClick={() => onReindex?.(repo.id)}
          disabled={isReindexing || repo.status === 'indexing'}
          className={clsx(
            'p-2 rounded-lg border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] transition-all duration-200',
            isReindexing || repo.status === 'indexing'
              ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
              : 'bg-[#2ad4ff] text-[#2D2D2D] hover:translate-y-[-2px] hover:shadow-[5px_5px_0_#2D2D2D]'
          )}
        >
          <RefreshCw className={clsx('w-4 h-4', isReindexing && 'animate-spin')} />
        </button>
        <button
          onClick={() => onDelete?.(repo.id)}
          disabled={isDeleting}
          className="p-2 rounded-lg bg-[#ff3d8a] hover:bg-[#ff5c9d] text-white border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[5px_5px_0_#2D2D2D]"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
