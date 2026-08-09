import { useState, useEffect, useRef } from 'react';
import { Plus, X, FolderGit2, GitBranch, Loader2, CheckCircle2, AlertTriangle, Github, Code2 } from 'lucide-react';
import { useRepos } from '../hooks/useRepos';
import { RepoCard } from '../components/RepoCard';
import { ConfirmModal } from '../components/ConfirmModal';
import { LoadingSpinner, PageLoader } from '../components/LoadingSpinner';
import { useStore } from '../store';
import { previewRepoBranches } from '../api';
import type { BranchPreview } from '../api';
import type { Repo } from '../types';

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

  // Live indexing progress is maintained by the global WebSocket bridge
  // (mounted in App.tsx), so the card progress matches the detail page.
  const indexingProgress = useStore((state) => state.indexingProgress);

  const [showAddModal, setShowAddModal] = useState(false);
  const [platform, setPlatform] = useState<'github' | 'gitee'>('github');
  const [gitUrlInput, setGitUrlInput] = useState('');
  const [activeBranchesInput, setActiveBranchesInput] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  // 待删除的仓库（列表页删除前需高危确认）
  const [deleteTarget, setDeleteTarget] = useState<Repo | null>(null);

  // Remote branch preview for the create-repo form (manually triggered).
  const [preview, setPreview] = useState<BranchPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [selectedActiveBranches, setSelectedActiveBranches] = useState<string[]>([]);

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
    const trimmed = value.trim();
    if (!trimmed) {
      setPreview(null);
      setPreviewError('');
      setSelectedActiveBranches([]);
    }
  };

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

  // 按托管平台校验仓库地址格式
  const validateGitUrl = (url: string, p: typeof platform): string | null => {
    if (!url) return '请输入仓库地址';
    const host = p === 'github' ? 'github.com' : 'gitee.com';
    if (!url.includes(host)) {
      return p === 'github'
        ? '请输入 GitHub 仓库地址（应包含 github.com）'
        : '请输入 Gitee 仓库地址（应包含 gitee.com）';
    }
    if (!/^https?:\/\/|^git@|^ssh:\/\//.test(url)) {
      return '仓库地址需以 http(s)://、git@ 或 ssh:// 开头';
    }
    return null;
  };

  // 归一化 git 地址用于重复检测（与后端 _normalize_git_url 保持一致）
  const normalizeGitUrl = (url: string) => {
    const u = url.trim().toLowerCase().replace(/\/+$/, '');
    return u.endsWith('.git') ? u.slice(0, -4) : u;
  };

  const handleAdd = () => {
    const url = gitUrlInput.trim();
    const error = validateGitUrl(url, platform);
    if (error) {
      alert(error);
      return;
    }
    // 提前拦截已添加过的地址，避免重复索引
    const duplicated = repos.some(
      (r) => r.gitUrl && normalizeGitUrl(r.gitUrl) === normalizeGitUrl(url),
    );
    if (duplicated) {
      alert('该仓库地址已添加过，请勿重复索引');
      return;
    }
    const payload: Parameters<typeof addRepo>[0] = { gitUrl: url };
    const activeBranches =
      selectedActiveBranches.length > 0 ? selectedActiveBranches : parseActiveBranches();
    if (activeBranches.length > 0) {
      payload.activeBranches = activeBranches;
    }
    addRepo(payload, { onSuccess: handleAddSuccess, onError: handleAddError });
  };

  const handleAddSuccess = () => {
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
            className="px-4 py-2 bg-white border-2 border-[#2D2D2D] rounded-lg text-[#2D2D2D] font-bold focus:outline-none focus:border-[#2ad4ff] shadow-[3px_3px_0_#2D2D2D]"
          >
            <option value="all">全部状态</option>
            <option value="completed">已完成</option>
            <option value="indexing">索引中</option>
            <option value="error">错误</option>
          </select>
          <span className="text-sm text-[#666] font-medium">
            共 {filteredRepos.length} 个仓库
          </span>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-[#ff3d8a] hover:bg-[#ff5c9d] text-white border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] rounded-lg transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D] font-bold"
        >
          <Plus className="w-5 h-5" />
          添加仓库
        </button>
      </div>

      {/* Repository Grid */}
      {filteredRepos.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[6px_6px_0_#2D2D2D]">
          <FolderGit2 className="w-16 h-16 mx-auto text-[#b88dff] mb-4" />
          <h3 className="text-lg font-bold text-[#2D2D2D] mb-2">
            {repos.length === 0 ? '暂无仓库' : '没有符合条件的仓库'}
          </h3>
          <p className="text-[#666] mb-6">
            {repos.length === 0
              ? '添加您的第一个代码仓库开始使用'
              : '尝试更改筛选条件'}
          </p>
          {repos.length === 0 && (
            <button
              onClick={() => setShowAddModal(true)}
              className="px-4 py-2 bg-[#2ad4ff] hover:bg-[#4adee0] text-[#2D2D2D] border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] rounded-lg transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D] font-bold"
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
                onDelete={(id) => {
                  const target = repos.find((r) => r.id === id);
                  setDeleteTarget(target || null);
                }}
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
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-md p-6 animate-scaleIn border-4 border-[#2D2D2D] shadow-[8px_8px_0_rgba(45,45,45,0.5)]">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-black text-[#2D2D2D]">
                添加仓库
              </h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="p-2 hover:bg-[#F5F5F0] rounded-lg transition-colors border-2 border-transparent hover:border-[#2D2D2D]"
              >
                <X className="w-5 h-5 text-[#2D2D2D]" />
              </button>
            </div>

            {/* 先选择托管平台 */}
            <div className="flex gap-2 mb-6">
              <button
                onClick={() => {
                  setPlatform('github');
                  setGitUrlInput('');
                  setPreview(null);
                  setPreviewError('');
                  setSelectedActiveBranches([]);
                }}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg font-bold border-2 border-[#2D2D2D] transition-all ${
                  platform === 'github'
                    ? 'bg-[#2ad4ff] text-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D]'
                    : 'bg-[#F5F5F0] text-[#2D2D2D] hover:bg-[#fff34d]'
                }`}
              >
                <Github className="w-5 h-5" />
                GitHub
              </button>
              <button
                onClick={() => {
                  setPlatform('gitee');
                  setGitUrlInput('');
                  setPreview(null);
                  setPreviewError('');
                  setSelectedActiveBranches([]);
                }}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg font-bold border-2 border-[#2D2D2D] transition-all ${
                  platform === 'gitee'
                    ? 'bg-[#ff3d8a] text-white shadow-[3px_3px_0_#2D2D2D]'
                    : 'bg-[#F5F5F0] text-[#2D2D2D] hover:bg-[#fff34d]'
                }`}
              >
                <Code2 className="w-5 h-5" />
                Gitee
              </button>
            </div>

            {/* Input */}
            <div className="mb-4">
              <input
                type="text"
                value={gitUrlInput}
                onChange={(e) => handleGitUrlChange(e.target.value)}
                placeholder={
                  platform === 'github'
                    ? 'https://github.com/user/repo.git'
                    : 'https://gitee.com/user/repo.git'
                }
                className="w-full px-4 py-3 bg-white border-2 border-[#2D2D2D] rounded-lg text-[#2D2D2D] placeholder-[#999] focus:outline-none focus:border-[#2ad4ff] focus:shadow-[3px_3px_0_#2ad4ff] transition-all font-mono"
              />
            </div>

            {/* Git branch preview (only for git URL, manually triggered) */}
            {gitUrlInput.trim() && (
              <div className="mb-6 space-y-4">
                {!preview && !previewLoading && !previewError && (
                  <button
                    onClick={() => fetchPreview(gitUrlInput.trim())}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 border-2 border-[#2D2D2D] text-[#2D2D2D] bg-[#fff34d] hover:bg-[#ffed00] shadow-[3px_3px_0_#2D2D2D] rounded-lg text-sm font-bold transition-all hover:translate-y-[-2px] hover:shadow-[5px_5px_0_#2D2D2D]"
                  >
                    <GitBranch className="w-4 h-4" />
                    拉取远程分支
                  </button>
                )}
                {previewLoading && (
                  <div className="flex items-center gap-2 text-sm text-[#666] font-medium">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    正在获取远程分支列表...
                  </div>
                )}
                {previewError && !previewLoading && (
                  <div className="flex items-start gap-2 text-sm text-[#2D2D2D] bg-[#ff3d8a] p-3 rounded-lg border-2 border-[#2D2D2D]">
                    <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-white" />
                    <span className="flex-1 text-white">无法获取远程分支：{previewError}</span>
                    <button
                      onClick={() => fetchPreview(gitUrlInput.trim())}
                      className="shrink-0 text-white font-bold underline"
                    >
                      重试
                    </button>
                  </div>
                )}
                {preview && !previewLoading && (
                  <>
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-[#666] font-medium">默认分支：</span>
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[#2ad4ff] border-2 border-[#2D2D2D] text-[#2D2D2D] font-bold">
                        <CheckCircle2 className="w-3 h-3" />
                        {preview.default_branch}
                      </span>
                      <span className="text-xs text-[#999]">（自动识别，作为主分支始终全量索引）</span>
                    </div>
                    {preview.branches.filter((b) => b !== preview.default_branch).length > 0 && (
                      <div>
                        <label className="block text-sm font-bold text-[#2D2D2D] mb-1.5">
                          业务分支（最多 2 个）
                        </label>
                        <div className="max-h-40 overflow-y-auto space-y-1.5 rounded-lg border-2 border-[#2D2D2D] p-2">
                          {preview.branches
                            .filter((b) => b !== preview.default_branch)
                            .map((branch) => {
                              const checked = selectedActiveBranches.includes(branch);
                              return (
                                <label
                                  key={branch}
                                  className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer hover:bg-[#F5F5F0] transition-colors"
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleActiveBranch(branch)}
                                    className="w-4 h-4 accent-[#ff3d8a]"
                                  />
                                  <span className="text-sm text-[#2D2D2D] font-medium">{branch}</span>
                                </label>
                              );
                            })}
                        </div>
                        <p className="mt-1 text-xs text-[#999]">
                          选中后为这些分支构建额外 diff 索引。
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={() => setShowAddModal(false)}
                className="flex-1 px-4 py-3 bg-[#F5F5F0] hover:bg-[#e8e8e0] text-[#2D2D2D] border-2 border-[#2D2D2D] rounded-lg transition-all font-bold hover:translate-y-[-2px] hover:shadow-[3px_3px_0_#2D2D2D]"
              >
                取消
              </button>
              <button
                onClick={handleAdd}
                disabled={isAdding || !gitUrlInput.trim()}
                className="flex-1 px-4 py-3 bg-[#2ad4ff] hover:bg-[#4adee0] disabled:bg-slate-200 disabled:shadow-none disabled:translate-y-0 disabled:cursor-not-allowed text-[#2D2D2D] border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] rounded-lg transition-all font-bold hover:translate-y-[-2px] hover:shadow-[6px_6px_0_#2D2D2D] flex items-center justify-center gap-2"
              >
                {isAdding ? <LoadingSpinner size="sm" /> : '添加'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除仓库高危确认 */}
      <ConfirmModal
        open={!!deleteTarget}
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
              将删除仓库 <span className="font-black text-[#2D2D2D]">{deleteTarget?.name || ''}</span> 的：
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
          if (deleteTarget) {
            deleteRepo(deleteTarget.id);
          }
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
};
