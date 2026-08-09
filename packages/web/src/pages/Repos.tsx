import { useState, useEffect, useRef } from 'react';
import { Plus, X, FolderGit2, GitBranch, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { useRepos } from '../hooks/useRepos';
import { RepoCard } from '../components/RepoCard';
import { LoadingSpinner, PageLoader } from '../components/LoadingSpinner';
import { useStore } from '../store';
import { previewRepoBranches } from '../api';
import type { BranchPreview } from '../api';

type AddType = 'path' | 'git';

interface IndexingProgress {
  progress: number;
  stage: string;
  stageProgress: {
    stage: string;
    current: number;
    total: number;
    percentage: number;
  } | null;
}

export const Repos = () => {
  const {
    repos,
    isLoading,
    addRepo,
    deleteRepo,
    reindex,
    isAdding,
    isDeleting,
    isReindexing,
  } = useRepos();

  const addRealTimeUpdate = useStore((state) => state.addRealTimeUpdate);

  const [showAddModal, setShowAddModal] = useState(false);
  const [addType, setAddType] = useState<AddType>('path');
  const [pathInput, setPathInput] = useState('');
  const [gitUrlInput, setGitUrlInput] = useState('');
  const [activeBranchesInput, setActiveBranchesInput] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [indexingProgress, setIndexingProgress] = useState<Record<string, IndexingProgress>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelayRef = useRef(1000);

  // Remote branch preview for the create-repo form
  const [preview, setPreview] = useState<BranchPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [selectedActiveBranches, setSelectedActiveBranches] = useState<string[]>([]);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connectWebSocket = () => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
    
    wsRef.current = new WebSocket(wsUrl);

    wsRef.current.onopen = () => {
      console.log('WebSocket connected');
      reconnectDelayRef.current = 1000;
    };

    wsRef.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'repo_update') {
          const { repoId, progress, stage, stage_progress, error, log } = data;
          setIndexingProgress(prev => ({
            ...prev,
            [repoId]: {
              progress: progress || 0,
              stage: stage || '',
              stageProgress: stage_progress || null,
            },
          }));
          addRealTimeUpdate(`repo_${repoId}`, {
            progress,
            stage,
            stage_progress,
            error,
            log,
          });
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    wsRef.current.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    wsRef.current.onclose = (event) => {
      console.log('WebSocket disconnected, reconnecting in', reconnectDelayRef.current, 'ms');
      setTimeout(() => {
        if (wsRef.current?.readyState !== WebSocket.OPEN) {
          connectWebSocket();
        }
      }, reconnectDelayRef.current);
      reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 30000);
    };
  };

  useEffect(() => {
    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmount');
      }
    };
  }, [addRealTimeUpdate]);

  const parseActiveBranches = (): string[] => {
    return activeBranchesInput
      .split(/[,\s]+/)
      .map((b) => b.trim())
      .filter((b) => b.length > 0);
  };

  const fetchPreview = async (url: string) => {
    setPreviewLoading(true);
    setPreviewError('');
    setPreview(null);
    setSelectedActiveBranches([]);
    try {
      const data = await previewRepoBranches(url);
      setPreview(data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '无法获取远程分支列表';
      setPreviewError(detail);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleGitUrlChange = (value: string) => {
    setGitUrlInput(value);
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
    }
    const trimmed = value.trim();
    if (!trimmed) {
      setPreview(null);
      setPreviewError('');
      setSelectedActiveBranches([]);
      return;
    }
    // Debounce remote branch preview
    previewTimerRef.current = setTimeout(() => {
      fetchPreview(trimmed);
    }, 600);
  };

  useEffect(() => {
    return () => {
      if (previewTimerRef.current) {
        clearTimeout(previewTimerRef.current);
      }
    };
  }, []);

  const toggleActiveBranch = (branch: string) => {
    setSelectedActiveBranches((prev) => {
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

  const handleAdd = () => {
    const payload: Parameters<typeof addRepo>[0] =
      addType === 'path' ? { path: pathInput.trim() } : { gitUrl: gitUrlInput.trim() };
    const activeBranches =
      addType === 'git' && selectedActiveBranches.length > 0
        ? selectedActiveBranches
        : parseActiveBranches();
    if (activeBranches.length > 0) {
      payload.activeBranches = activeBranches;
    }
    if (addType === 'path' && pathInput.trim()) {
      addRepo(payload, { onSuccess: handleAddSuccess, onError: handleAddError });
    } else if (addType === 'git' && gitUrlInput.trim()) {
      addRepo(payload, { onSuccess: handleAddSuccess, onError: handleAddError });
    }
  };

  const handleAddSuccess = () => {
    setPathInput('');
    setGitUrlInput('');
    setActiveBranchesInput('');
    setSelectedActiveBranches([]);
    setPreview(null);
    setPreviewError('');
    setShowAddModal(false);
  };

  const handleAddError = (error: any) => {
    console.error('Add repo error:', error);
    const detail = error?.response?.data?.detail || error?.message || '添加仓库失败';
    alert(`添加失败: ${detail}`);
  };

  const filteredRepos = repos.filter((repo) => {
    if (filterStatus === 'all') return true;
    return repo.status === filterStatus;
  });

  if (isLoading) {
    return <PageLoader />;
  }

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="px-4 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="all">全部状态</option>
            <option value="completed">已完成</option>
            <option value="indexing">索引中</option>
            <option value="error">错误</option>
          </select>
          <span className="text-sm text-slate-500 dark:text-slate-400">
            共 {filteredRepos.length} 个仓库
          </span>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg transition-colors"
        >
          <Plus className="w-5 h-5" />
          添加仓库
        </button>
      </div>

      {/* Repository Grid */}
      {filteredRepos.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
          <FolderGit2 className="w-16 h-16 mx-auto text-slate-300 dark:text-slate-600 mb-4" />
          <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2">
            {repos.length === 0 ? '暂无仓库' : '没有符合条件的仓库'}
          </h3>
          <p className="text-slate-500 dark:text-slate-400 mb-6">
            {repos.length === 0
              ? '添加您的第一个代码仓库开始使用'
              : '尝试更改筛选条件'}
          </p>
          {repos.length === 0 && (
            <button
              onClick={() => setShowAddModal(true)}
              className="px-4 py-2 bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg transition-colors"
            >
              添加仓库
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {filteredRepos.map((repo) => {
            const progress = indexingProgress[repo.id];
            return (
              <RepoCard
                key={repo.id}
                repo={repo}
                onDelete={deleteRepo}
                onReindex={reindex}
                isDeleting={isDeleting}
                isReindexing={isReindexing}
                indexingProgress={progress?.progress || 0}
                indexingStage={progress?.stage || ''}
                stageProgress={progress?.stageProgress || undefined}
              />
            );
          })}
        </div>
      )}

      {/* Add Repository Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-slate-800 rounded-2xl w-full max-w-md p-6 animate-scaleIn">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white">
                添加仓库
              </h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="p-2 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            {/* Add Type Tabs */}
            <div className="flex gap-2 mb-6">
              <button
                onClick={() => setAddType('path')}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg transition-colors ${
                  addType === 'path'
                    ? 'bg-indigo-500 text-white'
                    : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-600'
                }`}
              >
                <FolderGit2 className="w-5 h-5" />
                本地路径
              </button>
              <button
                onClick={() => setAddType('git')}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg transition-colors ${
                  addType === 'git'
                    ? 'bg-indigo-500 text-white'
                    : 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-600'
                }`}
              >
                <GitBranch className="w-5 h-5" />
                Git URL
              </button>
            </div>

            {/* Input */}
            <div className="mb-4">
              {addType === 'path' ? (
                <input
                  type="text"
                  value={pathInput}
                  onChange={(e) => setPathInput(e.target.value)}
                  placeholder="/path/to/your/repository"
                  className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              ) : (
                <input
                  type="text"
                  value={gitUrlInput}
                  onChange={(e) => handleGitUrlChange(e.target.value)}
                  placeholder="https://github.com/user/repo.git"
                  className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              )}
            </div>

            {/* Git branch preview (only for git URL) */}
            {addType === 'git' && gitUrlInput.trim() && (
              <div className="mb-6 space-y-4">
                {previewLoading && (
                  <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    正在获取远程分支列表...
                  </div>
                )}
                {previewError && !previewLoading && (
                  <div className="flex items-start gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-3 rounded-lg">
                    <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                    <span>无法获取远程分支：{previewError}</span>
                  </div>
                )}
                {preview && !previewLoading && (
                  <>
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-slate-500 dark:text-slate-400">默认分支：</span>
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        {preview.default_branch}
                      </span>
                      <span className="text-xs text-slate-400">（自动识别，作为主分支始终全量索引）</span>
                    </div>
                    {preview.branches.filter((b) => b !== preview.default_branch).length > 0 && (
                      <div>
                        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                          业务分支（最多 2 个）
                        </label>
                        <div className="max-h-40 overflow-y-auto space-y-1.5 rounded-lg border border-slate-200 dark:border-slate-600 p-2">
                          {preview.branches
                            .filter((b) => b !== preview.default_branch)
                            .map((branch) => {
                              const checked = selectedActiveBranches.includes(branch);
                              return (
                                <label
                                  key={branch}
                                  className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleActiveBranch(branch)}
                                    className="w-4 h-4 accent-indigo-500"
                                  />
                                  <span className="text-sm text-slate-700 dark:text-slate-300">{branch}</span>
                                </label>
                              );
                            })}
                        </div>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          选中后为这些分支构建额外 diff 索引。
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Active Branches (legacy path mode) */}
            {addType === 'path' && (
              <div className="mb-6">
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  业务分支（可选，最多 2 个，用逗号或空格分隔）
                </label>
                <input
                  type="text"
                  value={activeBranchesInput}
                  onChange={(e) => setActiveBranchesInput(e.target.value)}
                  placeholder="feature/payment, feature/order"
                  className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  默认只索引主分支；配置业务分支后会额外构建 diff 索引。
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={() => setShowAddModal(false)}
                className="flex-1 px-4 py-3 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleAdd}
                disabled={
                  isAdding ||
                  (addType === 'path' ? !pathInput.trim() : !gitUrlInput.trim())
                }
                className="flex-1 px-4 py-3 bg-indigo-500 hover:bg-indigo-600 disabled:bg-slate-300 dark:disabled:bg-slate-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                {isAdding ? <LoadingSpinner size="sm" /> : '添加'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
