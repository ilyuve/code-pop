import { Link } from 'react-router-dom';
import { FolderGit2, RefreshCw, Trash2, Clock, GitBranch, Search, Hash, Layers, Network } from 'lucide-react';
import type { Repo } from '../types';
import { StatusBadge } from './StatusBadge';
import { clsx } from 'clsx';

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
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5 hover:shadow-lg transition-all duration-200 hover:border-indigo-200 dark:hover:border-indigo-700">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-100 dark:bg-indigo-900/30 rounded-lg">
            <FolderGit2 className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
          </div>
          <div>
            <Link
              to={`/repos/${repo.id}`}
              className="font-semibold text-slate-900 dark:text-white hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
            >
              {repo.name}
            </Link>
            <p className="text-sm text-slate-500 dark:text-slate-400 truncate max-w-xs">
              {repo.path}
            </p>
          </div>
        </div>
        <StatusBadge status={repo.status} />
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
        <div>
          <p className="text-slate-500 dark:text-slate-400">文件数</p>
          <p className="font-medium text-slate-900 dark:text-white">
            {repo.indexedFiles} / {repo.totalFiles}
          </p>
        </div>
        <div>
          <p className="text-slate-500 dark:text-slate-400">创建时间</p>
          <p className="font-medium text-slate-900 dark:text-white flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {new Date(repo.createdAt).toLocaleDateString()}
          </p>
        </div>
        <div>
          <p className="text-slate-500 dark:text-slate-400">最后索引</p>
          <p className="font-medium text-slate-900 dark:text-white">
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
              <span className="text-slate-500 dark:text-slate-400">索引阶段</span>
              <span className="flex items-center gap-1 text-indigo-600 dark:text-indigo-400">
                {getStageIcon(indexingStage)}
                {getStageName(indexingStage)}
              </span>
            </div>
            <span className="font-medium text-indigo-600 dark:text-indigo-400">
              {Math.round(indexingProgress)}%
            </span>
          </div>
          <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 rounded-full transition-all duration-300"
              style={{
                width: `${indexingProgress}%`,
              }}
            />
          </div>
          {stageProgress && stageProgress.total > 0 && (
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {stageProgress.current}/{stageProgress.total} ({Math.round(stageProgress.percentage)}%)
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2 pt-3 border-t border-slate-100 dark:border-slate-700">
        <Link
          to={`/repos/${repo.id}`}
          className="flex-1 px-3 py-2 text-sm text-center bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 rounded-lg transition-colors"
        >
          查看详情
        </Link>
        <button
          onClick={() => onReindex?.(repo.id)}
          disabled={isReindexing || repo.status === 'indexing'}
          className={clsx(
            'p-2 rounded-lg transition-colors',
            isReindexing || repo.status === 'indexing'
              ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 cursor-not-allowed'
              : 'bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200'
          )}
        >
          <RefreshCw className={clsx('w-4 h-4', isReindexing && 'animate-spin')} />
        </button>
        <button
          onClick={() => onDelete?.(repo.id)}
          disabled={isDeleting}
          className="p-2 rounded-lg bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 text-red-600 dark:text-red-400 transition-colors"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
