import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
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
  Webhook,
  Copy,
  Check,
  X,
  Timer,
} from 'lucide-react';
import { useRepo, useRepos } from '../hooks/useRepos';
import { useIndexing, STAGE_ORDER, STAGE_LABELS } from '../hooks/useIndexing';
import { StatusBadge } from '../components/StatusBadge';
import { RepoProviderIcon } from '../components/RepoProviderIcon';
import { ConfirmModal } from '../components/ConfirmModal';
import { LoadingSpinner, PageLoader } from '../components/LoadingSpinner';
import { fetchRepoFiles, fetchRepoSymbols, cancelIndexing, previewRepoBranches, getRepoWebhook, generateRepoWebhookToken } from '../api';
import type { BranchPreview, RepoWebhookInfo } from '../api';
import { clsx } from 'clsx';
import { useState, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

export const RepoDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { deleteRepo, reindex, updateRepo, isDeleting, isReindexing, isUpdating } = useRepos();
  const { data: repo, isLoading, error } = useRepo(id!);
  const { isIndexing, progress, stageProgress, currentStageLabel, timing, error: indexingError, logs } = useIndexing(id!, repo);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [showLogs, setShowLogs] = useState(true);
  const [isCanceling, setIsCanceling] = useState(false);
  const [showBranchModal, setShowBranchModal] = useState(false);
  const [activeBranchesInput, setActiveBranchesInput] = useState('');
  const [preview, setPreview] = useState<BranchPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [selectedBranches, setSelectedBranches] = useState<string[]>([]);
  const [saveNotice, setSaveNotice] = useState('');
  const [showWebhookModal, setShowWebhookModal] = useState(false);
  const [webhookInfo, setWebhookInfo] = useState<RepoWebhookInfo | null>(null);
  const [webhookLoading, setWebhookLoading] = useState(false);
  const [copiedField, setCopiedField] = useState<'url' | 'token' | null>(null);
  const [showAutoSyncModal, setShowAutoSyncModal] = useState(false);
  const [autoSyncDraftEnabled, setAutoSyncDraftEnabled] = useState(false);
  const [autoSyncDraftInterval, setAutoSyncDraftInterval] = useState(5);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const logsContainerRef = useRef<HTMLDivElement>(null);

  // 判断当前访问地址是否为本地/内网，用于提示 Webhook 回调地址是否可达
  const hostname = window.location.hostname;
  const isLocalOrPrivateHost =
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname === '0.0.0.0' ||
    hostname.endsWith('.local') ||
    /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(hostname);

  const showTemporaryNotice = (text: string) => {
    setSaveNotice(text);
    // 刷新仓库信息与索引日志（即使仓库处于 indexed 也会重新拉取）
    queryClient.invalidateQueries({ queryKey: ['repo', id] });
    queryClient.invalidateQueries({ queryKey: ['indexingLogs', id] });
    window.setTimeout(() => setSaveNotice(''), 6000);
  };

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
    setShowDeleteModal(true);
  };

  const openWebhookModal = async () => {
    setShowWebhookModal(true);
    setCopiedField(null);
    setWebhookLoading(true);
    try {
      const info = await getRepoWebhook(id!);
      setWebhookInfo(info);
    } catch (err) {
      console.error('Failed to load webhook info:', err);
    } finally {
      setWebhookLoading(false);
    }
  };

  const handleGenerateToken = async () => {
    setWebhookLoading(true);
    try {
      const info = await generateRepoWebhookToken(id!);
      setWebhookInfo(info);
    } catch (err) {
      console.error('Failed to generate webhook token:', err);
    } finally {
      setWebhookLoading(false);
    }
  };

  const copyText = async (field: 'url' | 'token', text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      window.setTimeout(() => setCopiedField(null), 1500);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const handleReindex = () => {
    reindex(id!);
    showTemporaryNotice('已触发增量同步，请查看下方日志确认执行结果');
  };

  const handleOpenAutoSyncModal = () => {
    setAutoSyncDraftEnabled(repo.autoSync);
    setAutoSyncDraftInterval(repo.autoSyncInterval);
    setShowAutoSyncModal(true);
  };

  const handleSaveAutoSync = () => {
    updateRepo(
      { id: id!, data: { autoSync: autoSyncDraftEnabled, autoSyncInterval: autoSyncDraftInterval } },
      {
        onSuccess: () => {
          setShowAutoSyncModal(false);
          showTemporaryNotice(
            autoSyncDraftEnabled
              ? `已开启自动增量：每 ${autoSyncDraftInterval} 分钟自动检查主分支与业务分支的更新并同步`
              : '已关闭自动增量'
          );
        },
      }
    );
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
          showTemporaryNotice(
            '业务分支配置已保存，已触发增量同步（删除/重建分支索引），请查看下方日志'
          );
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
        className="flex items-center gap-2 text-[#2D2D2D] font-bold hover:text-[#ff3d8a] transition-colors"
      >
        <ArrowLeft className="w-5 h-5" />
        返回仓库列表
      </button>

      {saveNotice && (
        <div className="flex items-center gap-2 text-sm text-[#2D2D2D] bg-[#e8fff4] border-2 border-[#2D2D2D] rounded-xl px-4 py-3 font-medium">
          <Info className="w-4 h-4 shrink-0" />
          {saveNotice}
        </div>
      )}

      {/* Header */}
      <div className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D] p-6">
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-4">
            <RepoProviderIcon
              gitUrl={repo.gitUrl}
              containerClassName="p-3 rounded-xl"
              className="w-8 h-8"
            />
            <div>
              <h1 className="text-2xl font-black text-[#2D2D2D]">
                {repo.name}
              </h1>
              {repo.description && (
                <p className="text-sm text-[#666] mt-1 max-w-lg">
                  {repo.description}
                </p>
              )}
              <p className="text-xs text-[#999] mt-1 font-mono">
                {repo.path}
              </p>
              {/* 已索引分支（与列表卡片一致） */}
              <div className="flex flex-wrap items-center gap-1.5 mt-2">
                <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border-2 border-[#2D2D2D] bg-[#2ad4ff] text-[#2D2D2D] font-bold" title="默认分支">
                  <GitBranch className="w-3 h-3" />
                  {repo.defaultBranch}
                </span>
                {repo.activeBranches
                  .filter((b) => b !== repo.defaultBranch)
                  .slice(0, 2)
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

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[#fff34d] border-2 border-[#2D2D2D] rounded-lg shadow-[2px_2px_0_#2D2D2D]">
              <FileText className="w-5 h-5 text-[#2D2D2D]" />
            </div>
            <div>
              <p className="text-xs text-[#999] font-medium">索引文件</p>
              <p className="font-black text-[#2D2D2D]">
                {repo.indexedFiles} / {repo.totalFiles}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[#2ad4ff] border-2 border-[#2D2D2D] rounded-lg shadow-[2px_2px_0_#2D2D2D]">
              <Clock className="w-5 h-5 text-[#2D2D2D]" />
            </div>
            <div>
              <p className="text-xs text-[#999] font-medium">创建时间</p>
              <p className="font-black text-[#2D2D2D]">
                {new Date(repo.createdAt).toLocaleDateString()}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[#b88dff] border-2 border-[#2D2D2D] rounded-lg shadow-[2px_2px_0_#2D2D2D]">
              <RefreshCw className="w-5 h-5 text-white" />
            </div>
            <div>
              <p className="text-xs text-[#999] font-medium">最后索引</p>
              <p className="font-black text-[#2D2D2D]">
                {repo.lastIndexedAt
                  ? new Date(repo.lastIndexedAt).toLocaleDateString()
                  : '-'}
              </p>
            </div>
          </div>
          <div>
            {repo.gitUrl && (
              <div>
                <p className="text-xs text-[#999] font-medium">Git URL</p>
                <p className="font-black text-[#2D2D2D] truncate">
                  {repo.gitUrl}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Indexing Progress */}
      {(isIndexing || repo.status === 'indexing') && progress && (
        <div className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D] p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h3 className="text-lg font-black text-[#2D2D2D]">
                索引进度
              </h3>
              <span className="flex items-center gap-1 text-xs px-2 py-1 bg-[#fff34d] border-2 border-[#2D2D2D] text-[#2D2D2D] font-bold rounded-full">
                <div className="w-2 h-2 bg-[#ff3d8a] rounded-full animate-pulse" />
                进行中
              </span>
            </div>
            <div className="flex items-center gap-3">
              {currentStageLabel && (
                <span className="text-sm font-bold px-3 py-1 rounded-full bg-[#2ad4ff] border-2 border-[#2D2D2D] text-[#2D2D2D]">
                  {currentStageLabel}
                </span>
              )}
              <button
                onClick={handleCancel}
                disabled={isCanceling}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-[#ff3d8a] font-bold hover:bg-[#ffe3ef] border-2 border-transparent hover:border-[#ff3d8a] rounded-lg transition-colors"
              >
                {isCanceling ? <LoadingSpinner size="sm" /> : <LogOut className="w-4 h-4" />}
                取消索引
              </button>
            </div>
          </div>

          {/* Overall progress */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm font-bold text-[#2D2D2D]">总进度</span>
              <div className="flex items-center gap-3 text-xs">
                {timing && (
                  <>
                    <span className="text-[#666] font-medium">
                      已用时 <span className="font-bold text-[#2D2D2D]">{formatDuration(timing.elapsedSeconds)}</span>
                    </span>
                    <span className="text-[#666] font-medium">
                      预计剩余 <span className="font-bold text-[#2D2D2D]">{formatDuration(timing.estimatedRemainingSeconds)}</span>
                    </span>
                  </>
                )}
                <span className="font-black text-[#ff3d8a]">
                  {progress.percentage}%
                </span>
              </div>
            </div>
            <div className="h-3 bg-[#F5F5F0] border-2 border-[#2D2D2D] rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-[#ff3d8a] to-[#2ad4ff] rounded-full transition-all duration-500"
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
                        'px-2.5 py-1 rounded-full text-xs font-bold border-2 border-[#2D2D2D] transition-colors',
                        isCurrent
                          ? 'bg-[#fff34d] text-[#2D2D2D]'
                          : isPast
                            ? 'bg-[#6effb0] text-[#2D2D2D]'
                            : 'bg-[#F5F5F0] text-[#999]'
                      )}
                    >
                      {STAGE_LABELS[stage] ?? stage}
                    </span>
                    {idx < STAGE_ORDER.length - 1 && (
                      <ChevronRight className="w-3 h-3 text-[#2D2D2D]" />
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {indexingError && (
            <div className="flex items-start gap-2 text-sm text-white bg-[#ff3d8a] border-2 border-[#2D2D2D] p-3 rounded-lg font-medium">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <span>{indexingError}</span>
            </div>
          )}
        </div>
      )}

      {/* Logs Section（索引中与索引完成均显示，默认展开） */}
      <div className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D] p-6">
        <button
          onClick={() => setShowLogs(!showLogs)}
          className="flex items-center gap-2 text-sm font-bold text-[#2D2D2D] hover:text-[#ff3d8a] transition-colors"
        >
          <Terminal className="w-4 h-4" />
          索引日志
          {logs.length > 0 && (
            <span className="px-2 py-0.5 text-xs bg-[#2ad4ff] border-2 border-[#2D2D2D] rounded-full font-bold">
              {logs.length}
            </span>
          )}
          {showLogs ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showLogs && (
          <div
            ref={logsContainerRef}
            className="mt-3 h-48 overflow-y-auto bg-[#e8f4ff] rounded-lg border-2 border-[#2D2D2D] p-4 font-mono text-xs space-y-2"
          >
            {logs.length === 0 ? (
              <p className="text-[#999]">暂无日志信息</p>
            ) : (
              logs.map((log, idx) => (
                <div key={idx} className="flex items-start gap-2">
                  {getLogIcon(log.level)}
                  <div className="flex-1">
                    <span className="text-[#999] mr-2">
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

      {/* Error Message */}
      {repo.status === 'error' && repo.errorMessage && (
        <div className="bg-[#ffe3ef] border-2 border-[#ff3d8a] rounded-xl p-6">
          <div className="flex items-start gap-4">
            <div className="p-2 bg-[#ff3d8a] border-2 border-[#2D2D2D] rounded-lg">
              <AlertCircle className="w-6 h-6 text-white" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-black text-[#2D2D2D] mb-2">
                索引失败
              </h3>
              <p className="text-sm text-[#2D2D2D] font-medium leading-relaxed mb-4">
                {repo.errorMessage}
              </p>

              <div className="bg-white border-2 border-[#2D2D2D] rounded-lg p-4 mb-4">
                <h4 className="text-sm font-black text-[#2D2D2D] mb-2 flex items-center gap-2">
                  <Info className="w-4 h-4" />
                  可能的解决方案
                </h4>
                <ul className="text-xs text-[#2D2D2D] font-medium space-y-1.5">
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
                className="h-48 overflow-y-auto bg-[#e8f4ff] rounded-lg p-4 font-mono text-xs space-y-2"
              >
                {logs.length === 0 ? (
                  <p className="text-[#999]">暂无日志信息</p>
                ) : (
                  logs.map((log, idx) => (
                    <div key={idx} className="flex items-start gap-2">
                      {getLogIcon(log.level)}
                      <div className="flex-1">
                        <span className="text-[#999] mr-2">
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

      {/* Actions：左侧为增量同步相关，右侧为仓库管理操作 */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleOpenAutoSyncModal}
            disabled={isUpdating}
            title="点击配置自动增量：开启后按设置间隔自动检查远程仓库主分支与业务分支的更新并增量同步"
            className={clsx(
              'flex items-center gap-2 px-6 py-3 border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] rounded-xl font-bold transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-[4px_4px_0_#2D2D2D]',
              repo.autoSync
                ? 'bg-[#6effb0] text-[#2D2D2D]'
                : 'bg-[#F5F5F0] text-[#999]'
            )}
          >
            {repo.autoSync ? (
              <div className="w-2 h-2 rounded-full bg-[#2D2D2D] animate-pulse" />
            ) : (
              <Timer className="w-5 h-5" />
            )}
            自动增量{repo.autoSync ? `（${repo.autoSyncInterval} 分钟 / 开）` : '（关）'}
          </button>
          <button
            onClick={handleReindex}
            disabled={isReindexing || repo.status === 'indexing'}
            title="手动执行一次：仅同步有变更的分支增量数据，服务停机后点击此按钮可补齐遗漏的增量更新"
            className={clsx(
              'flex items-center gap-2 px-6 py-3 rounded-xl font-bold border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] transition-all duration-200',
              isReindexing || repo.status === 'indexing'
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed shadow-none'
                : 'bg-[#2ad4ff] hover:bg-[#4adee0] text-[#2D2D2D] hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D]'
            )}
          >
            <GitBranch className="w-5 h-5" />
            手动增量同步
          </button>
          <button
            onClick={openWebhookModal}
            className="flex items-center gap-2 px-6 py-3 bg-[#b88dff] hover:bg-[#cba7ff] text-white border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] rounded-xl font-bold transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D]"
          >
            <Webhook className="w-5 h-5" />
            Push 自动同步
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleReindex}
            disabled={isReindexing || repo.status === 'indexing'}
            className={clsx(
              'flex items-center gap-2 px-6 py-3 rounded-xl font-bold border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] transition-all duration-200',
              isReindexing || repo.status === 'indexing'
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed shadow-none'
                : 'bg-[#ff3d8a] hover:bg-[#ff5c9d] text-white hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D]'
            )}
          >
            <RefreshCw className={clsx('w-5 h-5', isReindexing && 'animate-spin')} />
            {repo.status === 'indexing' ? '强制重新索引' : '重新索引'}
          </button>
          <button
            onClick={handleOpenBranchModal}
            disabled={isUpdating}
            className="flex items-center gap-2 px-6 py-3 bg-[#fff34d] hover:bg-[#ffed00] text-[#2D2D2D] border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] rounded-xl font-bold transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D]"
          >
            <Settings className="w-5 h-5" />
            配置业务分支
          </button>
          <button
            onClick={handleDelete}
            disabled={isDeleting}
            className="flex items-center gap-2 px-6 py-3 bg-[#ffe3ef] hover:bg-[#ffd3e4] text-[#ff3d8a] border-2 border-[#ff3d8a] rounded-xl font-bold transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[4px_4px_0_#ff3d8a]"
          >
            <Trash2 className="w-5 h-5" />
            删除仓库
          </button>
        </div>
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

      {/* 删除仓库高危确认 */}
      <ConfirmModal
        open={showDeleteModal}
        title="删除仓库"
        danger
        confirmText={isDeleting ? '删除中...' : '确认删除'}
        loading={isDeleting}
        description={
          <div className="space-y-2">
            <p className="font-bold text-[#ff3d8a]">
              删除后不可恢复，请谨慎操作！
            </p>
            <p>
              将删除仓库 <span className="font-black text-[#2D2D2D]">{repo.name}</span> 的：
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>全部索引数据（代码向量、符号、检索记录）</li>
              <li>本地克隆的代码（含所有分支）</li>
              <li>该仓库的 Webhook 绑定与自动增量配置</li>
            </ul>
            <p className="pt-1">此操作不会影响远程仓库本身。</p>
          </div>
        }
        onConfirm={() => {
          deleteRepo(id!);
          navigate('/repos');
        }}
        onCancel={() => setShowDeleteModal(false)}
      />

      {/* Auto Sync Config Modal */}
      {showAutoSyncModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-2xl w-full max-w-md p-6 border-4 border-[#2D2D2D] shadow-[8px_8px_0_rgba(45,45,45,0.4)]">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-xl font-black text-[#2D2D2D] flex items-center gap-2">
                <Timer className="w-5 h-5" style={{ color: '#0a8f5c' }} />
                自动增量
              </h2>
              <button
                onClick={() => setShowAutoSyncModal(false)}
                className="p-1.5 rounded-lg border-2 border-transparent hover:border-[#2D2D2D] hover:bg-[#F5F5F0] transition-colors"
              >
                <X className="w-5 h-5 text-[#2D2D2D]" />
              </button>
            </div>

            <p className="text-sm text-[#666] mb-5">
              开启后 CodePop 按设定间隔自动检查远程仓库主分支与配置的业务分支，有更新即增量同步，无需配置 Webhook。
            </p>

            <div className="mb-5">
              <p className="text-sm font-bold text-[#2D2D2D] mb-2">开关</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setAutoSyncDraftEnabled(true)}
                  className={clsx(
                    'px-4 py-2 rounded-lg border-2 font-bold transition-colors',
                    autoSyncDraftEnabled
                      ? 'bg-[#6effb0] border-[#2D2D2D] text-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D]'
                      : 'bg-[#F5F5F0] border-transparent text-[#999] hover:text-[#2D2D2D]'
                  )}
                >
                  开启
                </button>
                <button
                  onClick={() => setAutoSyncDraftEnabled(false)}
                  className={clsx(
                    'px-4 py-2 rounded-lg border-2 font-bold transition-colors',
                    !autoSyncDraftEnabled
                      ? 'bg-[#F5F5F0] border-[#2D2D2D] text-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D]'
                      : 'bg-white border-transparent text-[#999] hover:text-[#2D2D2D]'
                  )}
                >
                  关闭
                </button>
              </div>
            </div>

            <div className={clsx('mb-6', !autoSyncDraftEnabled && 'opacity-40')}>
              <p className="text-sm font-bold text-[#2D2D2D] mb-2">检查间隔</p>
              <div className="flex gap-2">
                {[5, 15, 30, 60].map((minutes) => (
                  <button
                    key={minutes}
                    onClick={() => setAutoSyncDraftInterval(minutes)}
                    disabled={!autoSyncDraftEnabled}
                    className={clsx(
                      'px-3 py-2 rounded-lg border-2 font-bold transition-colors disabled:cursor-not-allowed',
                      autoSyncDraftEnabled && autoSyncDraftInterval === minutes
                        ? 'bg-[#2ad4ff] border-[#2D2D2D] text-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D]'
                        : 'bg-[#F5F5F0] border-transparent text-[#999] hover:text-[#2D2D2D]'
                    )}
                  >
                    {minutes} 分钟
                  </button>
                ))}
              </div>
            </div>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowAutoSyncModal(false)}
                className="px-4 py-2 text-[#666] hover:bg-[#F5F5F0] rounded-lg font-bold transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSaveAutoSync}
                disabled={isUpdating}
                className="px-5 py-2 bg-[#0a8f5c] hover:bg-[#0ba86b] text-white rounded-lg font-bold transition-colors disabled:opacity-50"
              >
                {isUpdating ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Webhook Bind Modal */}
      {showWebhookModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-2xl w-full max-w-md p-6 border-4 border-[#2D2D2D] shadow-[8px_8px_0_rgba(45,45,45,0.4)]">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-xl font-black text-[#2D2D2D] flex items-center gap-2">
                <Webhook className="w-5 h-5" style={{ color: '#b88dff' }} />
                Push 自动同步
              </h2>
              <button
                onClick={() => setShowWebhookModal(false)}
                className="p-1.5 rounded-lg border-2 border-transparent hover:border-[#2D2D2D] hover:bg-[#F5F5F0] transition-colors"
              >
                <X className="w-5 h-5 text-[#2D2D2D]" />
              </button>
            </div>

            {webhookLoading && !webhookInfo ? (
              <div className="flex justify-center py-10">
                <LoadingSpinner />
              </div>
            ) : (
              <div className="space-y-5">
                <p className="text-sm text-[#666]">
                  在 GitHub / Gitee 仓库配置 Webhook 后，代码 push 到主分支或已配置的业务分支会自动增量同步。将下面两项填入远程仓库的 Webhook 配置即可完成绑定。
                </p>

                <div>
                  <p className="text-sm font-bold text-[#2D2D2D] mb-1">Webhook 地址</p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 px-3 py-2 bg-[#F5F5F0] border-2 border-[#2D2D2D] rounded-lg text-xs break-all">
                      {webhookInfo ? `${window.location.origin}${webhookInfo.webhook_url}` : '...'}
                    </code>
                    <button
                      onClick={() => webhookInfo && copyText('url', `${window.location.origin}${webhookInfo.webhook_url}`)}
                      className="p-2 bg-[#2ad4ff] border-2 border-[#2D2D2D] rounded-lg hover:bg-[#4adee0] transition-colors"
                      title="复制地址"
                    >
                      {copiedField === 'url' ? <Check className="w-4 h-4 text-[#2D2D2D]" /> : <Copy className="w-4 h-4 text-[#2D2D2D]" />}
                    </button>
                  </div>
                  {isLocalOrPrivateHost ? (
                    <div className="mt-2 bg-[#fff8e1] border-2 border-[#ff8a3d] rounded-lg p-3 text-xs text-[#2D2D2D] space-y-1.5">
                      <p className="font-black flex items-center gap-1">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" style={{ color: '#ff8a3d' }} />
                        当前为本地/内网地址，GitHub / Gitee 服务器无法访问
                      </p>
                      <p>· 云服务器部署：用公网地址（如 http://IP:13000）打开 CodePop，此处会自动变为公网回调地址，直接填入远程仓库即可</p>
                      <p>· 本地调试：先用内网穿透（cpolar / ngrok / frp）把 13000 端口暴露到公网，再把「穿透地址 + {webhookInfo ? webhookInfo.webhook_url : ''}」填入远程仓库</p>
                    </div>
                  ) : (
                    <div className="mt-2 bg-[#e8fff4] border-2 border-[#0a8f5c] rounded-lg p-3 text-xs text-[#2D2D2D]">
                      <p className="font-black flex items-center gap-1">
                        <Check className="w-3.5 h-3.5 shrink-0" style={{ color: '#0a8f5c' }} />
                        当前为公网地址，可直接填入远程仓库配置
                      </p>
                    </div>
                  )}
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-sm font-bold text-[#2D2D2D]">仓库密钥</p>
                    <button
                      onClick={handleGenerateToken}
                      disabled={webhookLoading}
                      className="text-xs font-bold text-[#b88dff] hover:underline disabled:opacity-50"
                    >
                      {webhookInfo?.webhook_token ? '重置密钥' : '生成密钥'}
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 px-3 py-2 bg-[#F5F5F0] border-2 border-[#2D2D2D] rounded-lg text-xs font-mono break-all">
                      {webhookInfo?.webhook_token || '（未生成，点击右上「生成密钥」）'}
                    </code>
                    {webhookInfo?.webhook_token && (
                      <button
                        onClick={() => copyText('token', webhookInfo.webhook_token)}
                        className="p-2 bg-[#b88dff] border-2 border-[#2D2D2D] rounded-lg hover:bg-[#cba7ff] transition-colors"
                        title="复制密钥"
                      >
                        {copiedField === 'token' ? <Check className="w-4 h-4 text-white" /> : <Copy className="w-4 h-4 text-white" />}
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-[#999] mt-1">密钥由系统生成，仅对该仓库生效，请妥善保管；重置后旧密钥立即失效。</p>
                </div>

                <div className="bg-[#e8f4ff] border-2 border-[#2D2D2D] rounded-xl p-4 space-y-1.5 text-sm text-[#2D2D2D]">
                  <p className="font-black mb-1">配置步骤</p>
                  <p>1. GitHub：仓库 Settings → Webhooks → Add webhook，粘贴地址，Secret 填密钥，事件选 push</p>
                  <p>2. Gitee：仓库管理 → WebHooks，粘贴地址，密码填密钥，事件选 Push</p>
                  <p>3. 完成后 push 到主分支或已配置的业务分支，将自动增量同步</p>
                </div>
              </div>
            )}
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
