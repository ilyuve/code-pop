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
} from 'lucide-react';
import { useRepo, useRepos } from '../hooks/useRepos';
import { useIndexing } from '../hooks/useIndexing';
import { StatusBadge } from '../components/StatusBadge';
import { LoadingSpinner, PageLoader } from '../components/LoadingSpinner';
import { fetchRepoFiles, fetchRepoSymbols } from '../api';
import { clsx } from 'clsx';
import { useState } from 'react';

export const RepoDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { deleteRepo, reindex, isDeleting, isReindexing } = useRepos();
  const { data: repo, isLoading, error } = useRepo(id!);
  const { isIndexing, progress } = useIndexing(id!);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());

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
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">
            索引进度
          </h3>
          <div className="flex items-center gap-4 mb-4">
            <div className="flex-1">
              <div className="h-3 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                  style={{ width: `${progress.percentage}%` }}
                />
              </div>
            </div>
            <span className="text-lg font-semibold text-indigo-600 dark:text-indigo-400">
              {progress.percentage}%
            </span>
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            正在索引: {progress.current} / {progress.total} 个文件
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={handleReindex}
          disabled={isReindexing}
          className={clsx(
            'flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-colors',
            isReindexing
              ? 'bg-slate-100 dark:bg-slate-700 text-slate-400 cursor-not-allowed'
              : 'bg-indigo-500 hover:bg-indigo-600 text-white'
          )}
        >
          <RefreshCw className={clsx('w-5 h-5', isReindexing && 'animate-spin')} />
          {repo.status === 'indexing' ? '强制重新索引' : '重新索引'}
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
