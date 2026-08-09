import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  FolderGit2,
  RefreshCw,
  Trash2,
  Clock,
  FileText,
  AlertCircle,
  ChevronRight,
  ChevronDown,
  Folder,
  Code,
  LogOut,
  XCircle,
  Info,
  AlertTriangle,
  Terminal,
  ChevronUp,
  Settings,
  GitBranch,
} from 'lucide-react';
import { useRepo, useRepos } from '../hooks/useRepos';
import { useIndexing, STAGE_ORDER, STAGE_LABELS } from '../hooks/useIndexing';
import { StatusBadge } from '../components/StatusBadge';
import { LoadingSpinner, PageLoader } from '../components/LoadingSpinner';
import { fetchRepoFiles, fetchRepoSymbols, cancelIndexing, previewRepoBranches } from '../api';
import type { BranchPreview } from '../api';
import { clsx } from 'clsx';
import { useState, useRef, useEffect } from 'react';

export const RepoDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { deleteRepo, reindex, updateRepo, isDeleting, isReindexing, isUpdating } = useRepos();
  const { data: repo, isLoading, error } = useRepo(id!);
  const { isIndexing, progress, stageProgress, currentStageLabel, timing, error: indexingError, logs } = useIndexing(id!, repo);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [showLogs, setShowLogs] = useState(false);
  const [isCanceling, setIsCanceling] = useState(false);
  const [showBranchModal, setShowBranchModal] = useState(false);
  const [activeBranchesInput, setActiveBranchesInput] = useState('');
  const [preview, setPreview] = useState<BranchPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [selectedBranches, setSelectedBranches] = useState<string[]>([]);
  const logsContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (showLogs && logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [logs, showLogs]);

  const handleCancel = async () => {
    if (window.confirm('确定要取消当前索引进程吗？')) {
      setIsCanceling(true);
      try {
        await cancelIndexing(id!);
        setIsCanceling(false);
      } catch (err) {
        console.error('Failed to cancel indexing:', err);
        setIsCanceling(false);
      }
    }
  };

  const getLogIcon = (level: string) => {
    switch (level) {
      case 'error':
        return <XCircle className="w-4 h-4 text-red-500" />;
      case 'warning':
        return <AlertTriangle className="w-4 h-4 text-yellow-500" />;
      default:
        return <Info className="w-4 h-4 text-blue-500" />;
    }
  };

  const getLogLevelColor = (level: string) => {
    switch (level) {
      case 'error':
        return 'text-red-600 dark:text-red-400';
      case 'warning':
        return 'text-yellow-600 dark:text-yellow-400';
      default:
        return 'text-slate-600 dark:text-slate-400';
    }
  };

  const formatDuration = (seconds: number | null | undefined) => {
    if (seconds === null || seconds === undefined || seconds < 0) return '-';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
  };

  const { data: files = [] } = useQuery({
    queryKey: ['repoFiles', id],
    queryFn: () => fetchRepoFiles(id!),
    enabled: !!id && repo?.status === 'indexed',
  });

  const { data: symbols = [] } = useQuery({
    queryKey: ['repoSymbols', id, selectedFile],
    queryFn: () => fetchRepoSymbols(id!, selectedFile || undefined),
    enabled: !!id && !!selectedFile,
  });

  const handleDelete = () => {
    if (window.confirm('确定要删除这个仓库吗？')) {
      deleteRepo(id!);
      navigate('/repos');
    }
  };

  const handleReindex = () => {
    reindex(id!);
  };

  const handleOpenBranchModal = () => {
    const branches = repo?.activeBranches?.filter((b) => b !== repo.defaultBranch) || [];
    setActiveBranchesInput(branches.join(', '));
    setSelectedBranches(branches);
    setPreview(null);
    setPreviewError('');
    // 先立即打开弹窗，远程分支列表由用户点击「拉取远程分支」手动触发，
    // 避免网络慢/失败时弹窗卡住，也便于失败后原地重试。
    setShowBranchModal(true);
  };

  const handleFetchBranches = () => {
    if (!repo?.gitUrl) return;
    setPreviewLoading(true);
    setPreviewError('');
    setPreview(null);
    previewRepoBranches(repo.gitUrl)
      .then((data) => setPreview(data))
      .catch((err: any) =>
        setPreviewError(err?.response?.data?.detail || err?.message || '无法获取远程分支列表')
      )
      .finally(() => setPreviewLoading(false));
  };

  const toggleBranch = (branch: string) => {
    setSelectedBranches((prev) => {
      if (prev.includes(branch)) {
        return prev.filter((b) => b !== branch);
      }
      if (prev.length >= 2) {
        alert('个人版最多支持 2 个业务分支');
        return prev;
      }
      return [...prev, branch];
    });
  };

  const handleSaveBranches = () => {
    const activeBranches =
      preview && !previewLoading
        ? selectedBranches
        : activeBranchesInput
            .split(/[,\s]+/)
            .map((b) => b.trim())
            .filter((b) => b.length > 0);
    if (activeBranches.length > 2) {
      alert('个人版最多支持 2 个业务分支');
      return;
    }
    updateRepo(
      { id: id!, data: { activeBranches } },
      {
        onSuccess: () => {
          setShowBranchModal(false);
        },
      }
    );
  };

  const toggleDir = (dir: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      return next;
    });
  };

  const buildTree = (paths: string[]) => {
    const root: Record<string, any> = {};
    paths.forEach((path) => {
      const parts = path.split('/');
      let node = root;
      parts.forEach((part, idx) => {
        if (!node[part]) {
          node[part] = { children: {}, isFile: idx === parts.length - 1, fullPath: parts.slice(0, idx + 1).join('/') };
        }
        node = node[part].children;
      });
    });
    return root;
  };

  const renderTree = (node: Record<string, any>, depth = 0) => {
    return Object.entries(node).map(([name, info]) => {
      const isFile = info.isFile;
      const fullPath = info.fullPath;
      const paddingLeft = depth * 16 + 8;
      if (isFile) {
        return (
          <button
            key={fullPath}
            onClick={() => setSelectedFile(fullPath)}
            className={clsx(
              'w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm rounded-lg transition-colors',
              selectedFile === fullPath
                ? 'bg-[#ff3d8a20] text-[#ff3d8a] font-semibold'
                : 'text-[#666] hover:bg-[#F5F5F0]'
            )}
            style={{ paddingLeft }}
          >
            <FileText className="w-4 h-4 shrink-0" />
            <span className="truncate">{name}</span>
          </button>
        );
      }
      const isExpanded = expandedDirs.has(fullPath);
      return (
        <div key={fullPath}>
          <button
            onClick={() => toggleDir(fullPath)}
            className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-sm font-medium text-[#2D2D2D] hover:bg-[#F5F5F0] rounded-lg"
            style={{ paddingLeft }}
          >
            {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            <Folder className="w-4 h-4 shrink-0" style={{ color: '#fff34d' }} />
            <span className="truncate">{name}</span>
          </button>
          {isExpanded && (
            <div>{renderTree(info.children, depth + 1)}</div>
          )}
        </div>
      );
    });
  };

  const filePaths = files.map((f: any) => f.path || f);
  const tree = buildTree(filePaths);

  if (isLoading) {
    return <PageLoader />;
  }

  if (error || !repo) {
    return (
      <div className="text-center py-16">
        <AlertCircle className="w-16 h-16 mx-auto text-red-400 mb-4" />
        <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2">
          仓库不存在
        </h3>
        <p className="text-slate-500 dark:text-slate-400 mb-6">
          无法找到该仓库，可能已被删除
        </p>
        <button
          onClick={() => navigate('/repos')}
          className="px-4 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg transition-colors"
        >
          返回仓库列表
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Back Button */}
      <button
        onClick={() => navigate('/repos')}
        className="flex items-center gap-2 text-slate-600 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
      >
        <ArrowLeft className="w-5 h-5" />
        返回仓库列表
      </button>

      {/* Header */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-indigo-100 dark:bg-indigo-900/30 rounded-xl">
              <FolderGit2 className="w-8 h-8 text-indigo-600 dark:text-indigo-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
                {repo.name}
              </h1>
              <p className="text-slate-500 dark:text-slate-400 mt-1">
                {repo.path}
              </p>
            </div>
          </div>
          <StatusBadge status={repo.status} />
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-slate-100 dark:bg-slate-700 rounded-lg">
              <FileText className="w-5 h-5 text-slate-500" />
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400">索引文件</p>
              <p className="font-semibold text-slate-900 dark:text-white">
                {repo.indexedFiles} / {repo.totalFiles}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-slate-100 dark:bg-slate-700 rounded-lg">
              <Clock className="w-5 h-5 text-slate-500" />
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400">创建时间</p>
              <p className="font-semibold text-slate-900 dark:text-white">
                {new Date(repo.createdAt).toLocaleDateString()}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-slate-100 dark:bg-slate-700 rounded-lg">
              <RefreshCw className="w-5 h-5 text-slate-500" />
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400">最后索引</p>
              <p className="font-semibold text-slate-900 dark:text-white">
                {repo.lastIndexedAt
                  ? new Date(repo.lastIndexedAt).toLocaleDateString()
                  : '-'}
              </p>
            </div>
          </div>
          <div>
            {repo.gitUrl && (
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">Git URL</p>
                <p className="font-semibold text-slate-900 dark:text-white truncate">
                  {repo.gitUrl}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Indexing Progress */}
      {(isIndexing || repo.status === 'indexing') && progress && (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                索引进度
              </h3>
              <span className="flex items-center gap-1 text-xs px-2 py-1 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 rounded-full">
                <div className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse" />
                进行中
              </span>
            </div>
            <div className="flex items-center gap-3">
              {currentStageLabel && (
                <span className="text-sm font-medium px-3 py-1 rounded-full bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
                  {currentStageLabel}
                </span>
              )}
              <button
                onClick={handleCancel}
                disabled={isCanceling}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
              >
                {isCanceling ? <LoadingSpinner size="sm" /> : <LogOut className="w-4 h-4" />}
                取消索引
              </button>
            </div>
          </div>

          {/* Overall progress */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">总进度</span>
              <div className="flex items-center gap-3 text-xs">
                {timing && (
                  <>
                    <span className="text-slate-500 dark:text-slate-400">
                      已用时 <span className="font-medium text-slate-700 dark:text-slate-300">{formatDuration(timing.elapsedSeconds)}</span>
                    </span>
                    <span className="text-slate-500 dark:text-slate-400">
                      预计剩余 <span className="font-medium text-slate-700 dark:text-slate-300">{formatDuration(timing.estimatedRemainingSeconds)}</span>
                    </span>
                  </>
                )}
                <span className="font-semibold text-indigo-600 dark:text-indigo-400">
                  {progress.percentage}%
                </span>
              </div>
            </div>
            <div className="h-3 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
                style={{ width: `${progress.percentage}%` }}
              />
            </div>
          </div>

          {/* Stage pipeline */}
          {stageProgress && (
            <div className="flex flex-wrap items-center gap-2">
              {STAGE_ORDER.map((stage, idx) => {
                const isCurrent = stageProgress.stage === stage;
                const isPast = STAGE_ORDER.indexOf(stageProgress.stage) > idx;
                return (
                  <div key={stage} className="flex items-center gap-2">
                    <span
                      className={clsx(
                        'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                        isCurrent
                          ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                          : isPast
                            ? 'bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400'
                            : 'text-slate-400 dark:text-slate-500'
                      )}
                    >
                      {STAGE_LABELS[stage] ?? stage}
                    </span>
                    {idx < STAGE_ORDER.length - 1 && (
                      <ChevronRight className="w-3 h-3 text-slate-300 dark:text-slate-600" />
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {indexingError && (
            <div className="flex items-start gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-3 rounded-lg">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <span>{indexingError}</span>
            </div>
          )}

          {/* Logs Section */}
          <div className="border-t border-slate-200 dark:border-slate-700 pt-4">
            <button
              onClick={() => setShowLogs(!showLogs)}
              className="flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
            >
              <Terminal className="w-4 h-4" />
              索引日志
              {logs.length > 0 && (
                <span className="px-2 py-0.5 text-xs bg-slate-100 dark:bg-slate-700 rounded-full">
                  {logs.length}
                </span>
              )}
              {showLogs ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            {showLogs && (
              <div
                ref={logsContainerRef}
                className="mt-3 h-48 overflow-y-auto bg-slate-50 dark:bg-slate-900 rounded-lg p-4 font-mono text-xs space-y-2"
              >
                {logs.length === 0 ? (
                  <p className="text-slate-500 dark:text-slate-400">暂无日志信息</p>
                ) : (
                  logs.map((log, idx) => (
                    <div key={idx} className="flex items-start gap-2">
                      {getLogIcon(log.level)}
                      <div className="flex-1">
                        <span className="text-slate-400 mr-2">
                          {new Date(log.timestamp).toLocaleTimeString()}
                        </span>
                        <span className={getLogLevelColor(log.level)}>
                          {log.message}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error Message */}
      {repo.status === 'error' && repo.errorMessage && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-6">
          <div className="flex items-start gap-4">
            <div className="p-2 bg-red-100 dark:bg-red-800 rounded-lg">
              <AlertCircle className="w-6 h-6 text-red-600 dark:text-red-400" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-red-800 dark:text-red-300 mb-2">
                索引失败
              </h3>
              <p className="text-sm text-red-700 dark:text-red-400 leading-relaxed mb-4">
                {repo.errorMessage}
              </p>

              <div className="bg-white/50 dark:bg-slate-800/50 rounded-lg p-4 mb-4">
                <h4 className="text-sm font-semibold text-red-800 dark:text-red-300 mb-2 flex items-center gap-2">
                  <Info className="w-4 h-4" />
                  可能的解决方案
                </h4>
                <ul className="text-xs text-red-600 dark:text-red-400 space-y-1.5">
                  {repo.errorMessage?.includes('git') && (
                    <li className="flex items-start gap-2">
                      <span className="text-red-500">•</span>
                      检查 Git 仓库 URL 是否正确，网络是否可以访问
                    </li>
                  )}
                  {repo.errorMessage?.includes('embed') || repo.errorMessage?.includes('vector') ? (
                    <li className="flex items-start gap-2">
                      <span className="text-red-500">•</span>
                      检查模型文件是否已正确下载，尝试重新运行 scripts/download_models.py
                    </li>
                  ) : null}
                  {repo.errorMessage?.includes('memory') || repo.errorMessage?.includes('OOM') ? (
                    <li className="flex items-start gap-2">
                      <span className="text-red-500">•</span>
                      当前可用内存不足，尝试关闭其他应用或增加系统内存
                    </li>
                  ) : null}
                  {repo.errorMessage?.includes('database') || repo.errorMessage?.includes('postgresql') ? (
                    <li className="flex items-start gap-2">
                      <span className="text-red-500">•</span>
                      检查 PostgreSQL 连接配置，确认数据库服务已启动且网络可达
                    </li>
                  ) : null}
                  <li className="flex items-start gap-2">
                    <span className="text-red-500">•</span>
                    查看下方索引日志获取详细错误信息
                  </li>
                </ul>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={handleReindex}
                  disabled={isReindexing}
                  className="flex items-center gap-2 px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg font-medium transition-colors"
                >
                  <RefreshCw className={clsx('w-4 h-4', isReindexing && 'animate-spin')} />
                  重新索引
                </button>
                <button
                  onClick={() => setShowLogs(true)}
                  className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-slate-700 text-red-600 dark:text-red-400 rounded-lg font-medium transition-colors border border-red-200 dark:border-red-700"
                >
                  <Terminal className="w-4 h-4" />
                  查看日志
                </button>
              </div>
            </div>
          </div>

          {showLogs && (
            <div className="mt-4 border-t border-red-200 dark:border-red-800 pt-4">
              <div
                ref={logsContainerRef}
                className="h-48 overflow-y-auto bg-slate-50 dark:bg-slate-900 rounded-lg p-4 font-mono text-xs space-y-2"
              >
                {logs.length === 0 ? (
                  <p className="text-slate-500 dark:text-slate-400">暂无日志信息</p>
                ) : (
                  logs.map((log, idx) => (
                    <div key={idx} className="flex items-start gap-2">
                      {getLogIcon(log.level)}
                      <div className="flex-1">
                        <span className="text-slate-400 mr-2">
                          {new Date(log.timestamp).toLocaleTimeString()}
                        </span>
                        <span className={getLogLevelColor(log.level)}>
                          {log.message}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={handleReindex}
          disabled={isReindexing || repo.status === 'indexing'}
          className={clsx(
            'flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-colors',
            isReindexing || repo.status === 'indexing'
              ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 cursor-not-allowed'
              : 'bg-indigo-500 hover:bg-indigo-600 text-white'
          )}
        >
          <RefreshCw className={clsx('w-5 h-5', isReindexing && 'animate-spin')} />
          {repo.status === 'indexing' ? '强制重新索引' : '重新索引'}
        </button>
        <button
          onClick={handleReindex}
          disabled={isReindexing || repo.status === 'indexing'}
          title="仅同步有变更的分支增量数据，服务停机后点击此按钮可补齐遗漏的增量更新"
          className={clsx(
            'flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-colors border border-indigo-200 dark:border-indigo-700',
            isReindexing || repo.status === 'indexing'
              ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 cursor-not-allowed'
              : 'bg-white dark:bg-slate-700 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400'
          )}
        >
          <GitBranch className="w-5 h-5" />
          增量同步
        </button>
        <button
          onClick={handleOpenBranchModal}
          disabled={isUpdating}
          className="flex items-center gap-2 px-6 py-3 bg-white dark:bg-slate-700 hover:bg-slate-50 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-600 rounded-xl font-medium transition-colors"
        >
          <Settings className="w-5 h-5" />
          配置业务分支
        </button>
        <button
          onClick={handleDelete}
          disabled={isDeleting}
          className="flex items-center gap-2 px-6 py-3 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 text-red-600 dark:text-red-400 rounded-xl font-medium transition-colors"
        >
          <Trash2 className="w-5 h-5" />
          删除仓库
        </button>
      </div>

      {/* Branch Config Modal */}
      {showBranchModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-xl max-w-md w-full p-6">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
              配置业务分支
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
              默认分支始终为 <span className="font-medium text-slate-700 dark:text-slate-300">{repo.defaultBranch}</span>。
              下方可配置额外索引的最多 2 个业务分支，修改后会自动触发增量同步。
            </p>
            {repo.gitUrl && !previewLoading && !preview && !previewError && (
              <button
                onClick={handleFetchBranches}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 mb-4 border border-indigo-200 dark:border-indigo-700 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg text-sm font-medium transition-colors"
              >
                <GitBranch className="w-4 h-4" />
                拉取远程分支
              </button>
            )}
            {previewLoading && (
              <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400 mb-4">
                <LoadingSpinner size="sm" />
                正在获取远程分支列表...
              </div>
            )}
            {previewError && !previewLoading && (
              <div className="flex items-start gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-3 rounded-lg mb-4">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span className="flex-1">无法获取远程分支：{previewError}</span>
                <button
                  onClick={handleFetchBranches}
                  className="shrink-0 text-indigo-600 dark:text-indigo-400 font-medium hover:underline"
                >
                  重试
                </button>
              </div>
            )}
            {preview && !previewLoading && preview.branches.filter((b) => b !== repo.defaultBranch).length > 0 ? (
              <div className="max-h-48 overflow-y-auto space-y-1.5 rounded-lg border border-slate-200 dark:border-slate-600 p-2 mb-4">
                {preview.branches
                  .filter((b) => b !== repo.defaultBranch)
                  .map((branch) => {
                    const checked = selectedBranches.includes(branch);
                    return (
                      <label
                        key={branch}
                        className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleBranch(branch)}
                          className="w-4 h-4 accent-indigo-500"
                        />
                        <span className="text-sm text-slate-700 dark:text-slate-300">{branch}</span>
                      </label>
                    );
                  })}
              </div>
            ) : (
              <input
                type="text"
                value={activeBranchesInput}
                onChange={(e) => setActiveBranchesInput(e.target.value)}
                placeholder="feature/payment, feature/order"
                className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 mb-4"
              />
            )}
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-6">
              {preview && !previewLoading
                ? '勾选要额外索引的业务分支（最多 2 个）；留空表示只保留默认分支。'
                : '用逗号或空格分隔；留空表示只保留默认分支。'}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowBranchModal(false)}
                className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSaveBranches}
                disabled={isUpdating}
                className="px-4 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50"
              >
                {isUpdating ? '保存中...' : '保存并同步'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* File Tree & Symbols */}
      {repo.status === 'indexed' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <section
            className="lg:col-span-1 bg-white rounded-2xl p-4"
            style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
          >
            <h3 className="text-lg font-black mb-3 flex items-center gap-2">
              <Folder className="w-5 h-5" style={{ color: '#fff34d' }} />
              文件树
            </h3>
            <div className="max-h-[500px] overflow-y-auto space-y-1">
              {filePaths.length === 0 ? (
                <p className="text-sm text-[#666]">暂无文件</p>
              ) : (
                renderTree(tree)
              )}
            </div>
          </section>

          <section
            className="lg:col-span-2 bg-white rounded-2xl p-4"
            style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
          >
            <h3 className="text-lg font-black mb-3 flex items-center gap-2">
              <Code className="w-5 h-5" style={{ color: '#2ad4ff' }} />
              {selectedFile ? `符号：${selectedFile}` : '文件符号'}
            </h3>
            {!selectedFile ? (
              <p className="text-sm text-[#666]">点击左侧文件查看符号列表</p>
            ) : symbols.length === 0 ? (
              <p className="text-sm text-[#666]">该文件暂无符号</p>
            ) : (
              <div className="space-y-2 max-h-[500px] overflow-y-auto">
                {symbols.map((s: any) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between p-3 rounded-xl"
                    style={{ background: '#F5F5F0' }}
                  >
                    <div>
                      <p className="font-bold text-sm">{s.name}</p>
                      <p className="text-xs text-[#666]">{s.type} · 第 {s.line} 行</p>
                    </div>
                    <span
                      className="px-2 py-1 rounded text-xs font-bold"
                      style={{ background: '#2ad4ff20', color: '#2D2D2D' }}
                    >
                      {s.kind}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
};
