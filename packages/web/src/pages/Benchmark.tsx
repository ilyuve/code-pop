import { useState, useMemo } from 'react';
import {
  Search,
  Play,
  Loader2,
  AlertCircle,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Layers,
  GitBranch,
  FileCode,
  Binary,
  Database,
  Share2,
  SlidersHorizontal,
  X,
  Cpu,
  Lock,
} from 'lucide-react';
import { useRepos } from '../hooks/useRepos';
import { debugSearch } from '../api';
import { clsx } from 'clsx';
import type { DebugSearchResponse, DebugPathSnapshot, DebugFusionHit, SearchResult, CodeContext } from '../types';

const PATH_CONFIG: { key: string; label: string; icon: React.ElementType; color: string; bg: string }[] = [
  { key: 'vector', label: 'Vector', icon: Share2, color: '#2ad4ff', bg: '#e6faff' },
  { key: 'sparse', label: 'Sparse', icon: Binary, color: '#6effb0', bg: '#eafff5' },
  { key: 'symbol', label: 'Symbol', icon: FileCode, color: '#fff34d', bg: '#fffee6' },
  { key: 'bm25', label: 'BM25', icon: Database, color: '#ff3d8a', bg: '#ffe6f2' },
  { key: 'graph', label: 'Graph', icon: GitBranch, color: '#b88dff', bg: '#f2e6ff' },
];

const DEFAULT_LIMIT = 20;
const DEFAULT_TOP_K = 20;
const MAX_TOP_K = 20;

// Virtual branch used to render a merged main + compare branch view.
const ALL_BRANCH = '__all__';

export const Benchmark = () => {
  const { repos, isLoading: reposLoading } = useRepos();
  const [selectedRepo, setSelectedRepo] = useState('');
  // 主分支：自动识别为仓库默认分支（锁定，不可选）；副分支：可选业务分支，默认=主分支
  const [mainBranch, setMainBranch] = useState('');
  const [compareBranch, setCompareBranch] = useState('');
  const [branchResults, setBranchResults] = useState<Record<string, DebugSearchResponse>>({});
  const [activeResultBranch, setActiveResultBranch] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<Error | null>(null);
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [enabledPaths, setEnabledPaths] = useState<Set<string>>(() => new Set(PATH_CONFIG.map((p) => p.key)));
  const [topK, setTopK] = useState<Record<string, number>>({});
  const [topKInput, setTopKInput] = useState<Record<string, string>>({});
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [expandedFusion, setExpandedFusion] = useState(false);
  const [activeTab, setActiveTab] = useState<'context' | 'json'>('context');

  const effectiveTopK = useMemo(() => {
    const result: Record<string, number> = {};
    PATH_CONFIG.forEach((p) => {
      result[p.key] = topK[p.key] ?? DEFAULT_TOP_K;
    });
    return result;
  }, [topK]);

  // 可选分支：默认分支 + 已配置的业务分支
  const branchOptions = useMemo(() => {
    const repo = repos.find((r) => r.id === selectedRepo);
    if (!repo) return [];
    const def = repo.defaultBranch || 'main';
    const active = repo.activeBranches || [];
    return [def, ...active.filter((b) => b !== def)];
  }, [repos, selectedRepo]);

  const handleRepoChange = (repoId: string) => {
    setSelectedRepo(repoId);
    const repo = repos.find((r) => r.id === repoId);
    const def = repo?.defaultBranch || 'main';
    setMainBranch(def);
    setCompareBranch(def);
    setActiveResultBranch(def);
    setBranchResults({});
    setRunError(null);
  };

  // Merged "全部" view: main branch snippets first, then compare branch
  // snippets override by (filePath, lineNumber) — matching the backend's
  // main ∪ diff merge semantics (compare branch wins on conflicts).
  const mergedResult: DebugSearchResponse | null = useMemo(() => {
    const branches = Object.keys(branchResults);
    if (branches.length < 2) return null;
    const compareKey = branches.find((b) => b !== mainBranch);
    const mainRes = branchResults[mainBranch];
    const compareRes = compareKey ? branchResults[compareKey] : null;
    if (!mainRes || !compareRes) return null;

    const byKey = new Map<string, SearchResult>();
    for (const s of mainRes.final_context.code_snippets || []) {
      byKey.set(`${s.filePath}:${s.lineNumber}`, s);
    }
    for (const s of compareRes.final_context.code_snippets || []) {
      byKey.set(`${s.filePath}:${s.lineNumber}`, s);
    }
    const mergedSnippets = Array.from(byKey.values()).sort((a, b) => b.score - a.score);

    const ctx = compareRes.final_context;
    return {
      ...compareRes,
      final_context: {
        ...ctx,
        code_snippets: mergedSnippets,
        total_files: mergedSnippets.length,
      },
    };
  }, [branchResults, mainBranch]);

  const result: DebugSearchResponse | null = useMemo(() => {
    if (!activeResultBranch) return null;
    if (activeResultBranch === ALL_BRANCH) return mergedResult;
    return branchResults[activeResultBranch] || null;
  }, [activeResultBranch, branchResults, mergedResult]);

  const handleRun = async () => {
    if (!selectedRepo || !query.trim() || isRunning) return;
    setIsRunning(true);
    setRunError(null);
    setBranchResults({});
    try {
      const pathOverrides = {
        enabled: Array.from(enabledPaths),
        top_k: Object.fromEntries(Object.entries(effectiveTopK).filter(([, v]) => v > 0)),
      };
      const branches =
        compareBranch && compareBranch !== mainBranch ? [mainBranch, compareBranch] : [mainBranch];
      for (const b of branches) {
        const data = await debugSearch(query.trim(), selectedRepo, b, limit, pathOverrides);
        setBranchResults((prev) => ({ ...prev, [b]: data }));
      }
      setActiveResultBranch(mainBranch);
    } catch (err) {
      setRunError(err as Error);
    } finally {
      setIsRunning(false);
    }
  };

  const togglePath = (key: string) => {
    setEnabledPaths((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const updateTopK = (key: string, value: string) => {
    const num = parseInt(value, 10);
    if (Number.isNaN(num) || num <= 0) {
      // Allow empty/transitional input; query will fall back to DEFAULT_TOP_K.
      setTopKInput((prev) => ({ ...prev, [key]: value }));
      setTopK((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    } else {
      const clamped = Math.min(num, MAX_TOP_K);
      setTopKInput((prev) => ({ ...prev, [key]: String(clamped) }));
      setTopK((prev) => ({ ...prev, [key]: clamped }));
    }
  };

  const copyJson = () => {
    if (!result) return;
    navigator.clipboard.writeText(JSON.stringify(result.final_context, null, 2));
  };

  const repoOptions = useMemo(() => repos.filter((r) => r.status === 'completed' || r.status === 'indexed'), [repos]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center gap-3">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center"
          style={{ background: '#b88dff', border: '2px solid #2D2D2D', boxShadow: '4px 4px 0 #2D2D2D' }}
        >
          <Search className="w-6 h-6 text-white" />
        </div>
        <div>
          <h1 className="text-2xl font-black text-[#2D2D2D]">评测中心 (Benchmark)</h1>
          <p className="text-[#666]">可视化调试中文/英文自然语言查询的实际召回质量</p>
        </div>
      </div>

      {/* Query area */}
      <section
        className="bg-white rounded-2xl p-6 space-y-4"
        style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
      >
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="md:col-span-1">
            <label className="block text-sm font-medium text-[#666] mb-1">选择仓库 <span className="text-[#ff3d8a]">*</span></label>
            <select
              value={selectedRepo}
              onChange={(e) => handleRepoChange(e.target.value)}
              disabled={reposLoading}
              className="w-full px-3 py-2 rounded-xl border-2 border-[#2D2D2D] bg-[#F5F5F0] disabled:opacity-60"
            >
              <option value="">请选择仓库</option>
              {repoOptions.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name}
                </option>
              ))}
            </select>
            {repoOptions.length === 0 && !reposLoading && (
              <p className="text-xs text-[#ff3d8a] mt-1">没有已索引完成的仓库，无法测试。</p>
            )}
          </div>

          <div className="md:col-span-1">
            <label className="block text-sm font-medium text-[#666] mb-1">
              主分支（默认分支，自动识别）
            </label>
            <div className="flex items-center gap-2 px-3 py-2 rounded-xl border-2 border-[#2D2D2D] bg-[#F5F5F0] text-sm text-[#2D2D2D]">
              {mainBranch ? (
                <>
                  <Lock className="w-3.5 h-3.5 text-[#999]" />
                  <span className="font-bold">{mainBranch}</span>
                  <span className="text-xs text-[#999]">（不可修改）</span>
                </>
              ) : (
                <span className="text-[#999]">请先选择仓库</span>
              )}
            </div>
          </div>

          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-[#666] mb-1">
              副分支（对比分支，默认与主分支一致）
            </label>
            <select
              value={compareBranch || mainBranch}
              onChange={(e) => setCompareBranch(e.target.value)}
              disabled={!selectedRepo}
              className="w-full px-3 py-2 rounded-xl border-2 border-[#2D2D2D] bg-[#F5F5F0] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {branchOptions.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <p className="text-xs text-[#666] mt-1">
              选择业务分支时，将分别对主分支与副分支执行检索并对比结果。
            </p>
          </div>
        </div>

        {/* Query area */}
        <div className="mt-4">
          <label className="block text-sm font-medium text-[#666] mb-1">自然语言查询</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleRun()}
              disabled={!selectedRepo}
              placeholder={selectedRepo ? '输入中文或中英混合查询，例如：订单创建流程 / redis cache config' : '请先选择仓库'}
              className="flex-1 px-3 py-2 rounded-xl border-2 border-[#2D2D2D] bg-[#F5F5F0] disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-[#ff3d8a]"
            />
            <button
              onClick={handleRun}
              disabled={!selectedRepo || !query.trim() || isRunning}
              className="px-5 py-2 rounded-xl font-bold flex items-center gap-2 transition-transform active:scale-95 disabled:opacity-60"
              style={{ background: '#ff3d8a', color: 'white', border: '2px solid #2D2D2D', boxShadow: '4px 4px 0 #2D2D2D' }}
            >
              {isRunning ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
              {isRunning ? '检索中...' : '执行检索'}
            </button>
          </div>
        </div>

        {/* Parameter panel */}
        <div>
          <button
            onClick={() => setParamsOpen((v) => !v)}
            className="flex items-center gap-2 text-sm font-bold text-[#2D2D2D] hover:text-[#ff3d8a]"
          >
            <SlidersHorizontal className="w-4 h-4" />
            参数面板
            {paramsOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {paramsOpen && (
            <div className="mt-3 p-4 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D] space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                {PATH_CONFIG.map((p) => (
                  <label
                    key={p.key}
                    className={clsx(
                      'flex items-center gap-2 p-3 rounded-xl border-2 cursor-pointer transition-colors',
                      enabledPaths.has(p.key)
                        ? 'bg-white border-[#2D2D2D]'
                        : 'bg-[#E5E5E0] border-[#999] opacity-70'
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={enabledPaths.has(p.key)}
                      onChange={() => togglePath(p.key)}
                      className="w-4 h-4 accent-[#ff3d8a]"
                    />
                    <p.icon className="w-4 h-4" style={{ color: p.color }} />
                    <span className="font-bold text-sm">{p.label}</span>
                  </label>
                ))}
              </div>

              <p className="text-xs text-[#666]">
                每路召回 top_k 范围 1~{MAX_TOP_K}，留空则默认使用 {DEFAULT_TOP_K}。
              </p>

              <div className="grid grid-cols-2 md:grid-cols-6 gap-3 items-end">
                {PATH_CONFIG.map((p) => (
                  <div key={`topk-${p.key}`}>
                    <label className="block text-xs font-medium text-[#666] mb-1">{p.label} top_k</label>
                    <input
                      type="number"
                      min={1}
                      max={MAX_TOP_K}
                      value={topKInput[p.key] ?? ''}
                      placeholder={String(DEFAULT_TOP_K)}
                      onChange={(e) => updateTopK(p.key, e.target.value)}
                      className="w-full px-2 py-1 rounded-lg border-2 border-[#2D2D2D] bg-white text-sm"
                    />
                  </div>
                ))}
                <div>
                  <label className="block text-xs font-medium text-[#666] mb-1">最终 limit</label>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={limit}
                    onChange={(e) => setLimit(Math.max(1, Math.min(100, parseInt(e.target.value, 10) || 1)))}
                    className="w-full px-2 py-1 rounded-lg border-2 border-[#2D2D2D] bg-white text-sm"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {runError && (
        <div
          className="p-4 rounded-xl flex items-center gap-3"
          style={{ background: '#ffe6e6', border: '2px solid #ff3d8a' }}
        >
          <AlertCircle className="w-5 h-5 text-[#ff3d8a]" />
          <p className="font-bold text-[#2D2D2D]">检索失败：{(runError as any)?.response?.data?.detail || runError.message}</p>
        </div>
      )}

      {/* Branch comparison switcher */}
      {Object.keys(branchResults).length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-[#2D2D2D]">查看分支：</span>
          {Object.keys(branchResults).map((b) => (
            <button
              key={b}
              onClick={() => setActiveResultBranch(b)}
              className={clsx(
                'px-3 py-1.5 rounded-lg text-sm font-bold border-2 transition-colors',
                activeResultBranch === b
                  ? 'bg-[#2D2D2D] text-white border-[#2D2D2D]'
                  : 'bg-white text-[#2D2D2D] border-[#2D2D2D] hover:bg-[#F5F5F0]'
              )}
            >
              {b}
              {b === mainBranch && <span className="ml-1 text-xs opacity-70">主</span>}
              {b !== mainBranch && <span className="ml-1 text-xs opacity-70">副</span>}
            </button>
          ))}
          {Object.keys(branchResults).length > 1 && (
            <button
              onClick={() => setActiveResultBranch(ALL_BRANCH)}
              className={clsx(
                'px-3 py-1.5 rounded-lg text-sm font-bold border-2 transition-colors',
                activeResultBranch === ALL_BRANCH
                  ? 'bg-[#ff3d8a] text-white border-[#ff3d8a]'
                  : 'bg-white text-[#2D2D2D] border-[#2D2D2D] hover:bg-[#F5F5F0]'
              )}
              title="主分支 + 副分支合并结果（副分支优先覆盖）"
            >
              全部
              <span className="ml-1 text-xs opacity-70">主+副</span>
            </button>
          )}
        </div>
      )}

      {result && (
        <div className="space-y-6">
          {/* Query analysis */}
          <section
            className="bg-white rounded-2xl p-6"
            style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
          >
            <h2 className="text-lg font-black flex items-center gap-2 mb-4">
              <Cpu className="w-5 h-5" style={{ color: '#2ad4ff' }} />
              查询分析
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-3 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D]">
                <p className="text-xs text-[#666]">意图类型</p>
                <p className="font-black">{result.query_analysis.intent_type}</p>
              </div>
              <div className="p-3 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D]">
                <p className="text-xs text-[#666]">中文检测</p>
                <p className="font-black">{result.query_analysis.is_chinese ? '是' : '否'}</p>
              </div>
              <div className="p-3 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D]">
                <p className="text-xs text-[#666]">总耗时</p>
                <p className="font-black">{result.total_latency_ms} ms</p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="text-sm font-medium text-[#666]">提取概念：</span>
              {result.query_analysis.concepts.map((c) => (
                <span key={c} className="px-2 py-1 rounded-lg text-xs font-bold bg-[#2ad4ff20] border border-[#2ad4ff]">
                  {c}
                </span>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <span className="text-sm font-medium text-[#666]">扩展词：</span>
              {result.query_analysis.expanded_terms.map((t) => (
                <span key={t} className="px-2 py-1 rounded-lg text-xs font-bold bg-[#fff34d30] border border-[#fff34d]">
                  {t}
                </span>
              ))}
            </div>
          </section>

          {/* Path lanes */}
          <section>
            <h2 className="text-lg font-black flex items-center gap-2 mb-4">
              <Layers className="w-5 h-5" style={{ color: '#ff3d8a' }} />
              五路召回通道
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
              {result.paths.map((path) => (
                <PathLane
                  key={path.name}
                  path={path}
                  expanded={expandedPaths.has(path.name)}
                  onToggle={() =>
                    setExpandedPaths((prev) => {
                      const next = new Set(prev);
                      if (next.has(path.name)) next.delete(path.name);
                      else next.add(path.name);
                      return next;
                    })
                  }
                />
              ))}
            </div>
          </section>

          {/* Fusion results */}
          <section
            className="bg-white rounded-2xl p-6"
            style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-black flex items-center gap-2">
                <Layers className="w-5 h-5" style={{ color: '#6effb0' }} />
                RRF 融合结果
              </h2>
              <button
                onClick={() => setExpandedFusion((v) => !v)}
                className="text-sm font-bold flex items-center gap-1 hover:text-[#ff3d8a]"
              >
                {expandedFusion ? '收起' : '展开'}
                {expandedFusion ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            </div>
            <p className="text-sm text-[#666] mb-3">rrf_k = {result.fusion.rrf_k}，共 {result.fusion.hit_count} 条</p>
            {expandedFusion && (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {result.fusion.hits.map((hit, idx) => (
                  <FusionRow key={hit.id} hit={hit} index={idx} />
                ))}
              </div>
            )}
          </section>

          {/* Final output */}
          <section
            className="bg-white rounded-2xl overflow-hidden"
            style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}
          >
            <div className="flex items-center justify-between p-4 border-b-2 border-[#2D2D2D]">
              <h2 className="text-lg font-black flex items-center gap-2">
                <Check className="w-5 h-5" style={{ color: '#fff34d' }} />
                最终输出（上层大模型实际拿到）
              </h2>
              <div className="flex items-center gap-2">
                <div className="flex rounded-lg border-2 border-[#2D2D2D] overflow-hidden">
                  <button
                    onClick={() => setActiveTab('context')}
                    className={clsx('px-3 py-1 text-sm font-bold', activeTab === 'context' ? 'bg-[#2D2D2D] text-white' : 'bg-white')}
                  >
                    结构化
                  </button>
                  <button
                    onClick={() => setActiveTab('json')}
                    className={clsx('px-3 py-1 text-sm font-bold', activeTab === 'json' ? 'bg-[#2D2D2D] text-white' : 'bg-white')}
                  >
                    JSON
                  </button>
                </div>
                <button
                  onClick={copyJson}
                  className="p-2 rounded-lg border-2 border-[#2D2D2D] hover:bg-[#F5F5F0]"
                  title="复制 JSON"
                >
                  <Copy className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div className="p-4 max-h-[600px] overflow-y-auto">
              {activeTab === 'context' ? (
                <ContextView context={result.final_context} />
              ) : (
                <pre className="text-xs bg-[#F5F5F0] p-4 rounded-xl border-2 border-[#2D2D2D] overflow-auto">
                  <code>{JSON.stringify(result.final_context, null, 2)}</code>
                </pre>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
};

function PathLane({
  path,
  expanded,
  onToggle,
}: {
  path: DebugPathSnapshot;
  expanded: boolean;
  onToggle: () => void;
}) {
  const config = PATH_CONFIG.find((p) => p.key === path.name)!;
  const zeroHit = path.enabled && path.hit_count === 0;

  return (
    <div
      className="rounded-2xl p-4 flex flex-col"
      style={{
        background: path.enabled ? config.bg : '#E5E5E0',
        border: `2px solid ${zeroHit ? '#ff3d8a' : '#2D2D2D'}`,
        boxShadow: zeroHit ? '4px 4px 0 #ff3d8a' : '4px 4px 0 #2D2D2D',
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <config.icon className="w-4 h-4" style={{ color: config.color }} />
          <span className="font-black text-sm">{config.label}</span>
        </div>
        {!path.enabled && <X className="w-4 h-4 text-[#999]" />}
      </div>
      <div className="space-y-1 mb-3">
        <div className="flex justify-between text-xs">
          <span className="text-[#666]">命中</span>
          <span className={clsx('font-black', zeroHit && 'text-[#ff3d8a]')}>
            {path.hit_count}
          </span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-[#666]">top_k</span>
          <span className="font-black">{path.top_k}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-[#666]">耗时</span>
          <span className="font-black">{path.latency_ms} ms</span>
        </div>
      </div>
      {zeroHit && (
        <div className="mb-2 p-2 rounded-lg bg-[#ff3d8a20] text-xs font-bold text-[#ff3d8a] flex items-center gap-1">
          <AlertCircle className="w-3 h-3" />
          0 命中
        </div>
      )}
      {path.hit_count > 0 && (
        <button
          onClick={onToggle}
          className="mt-auto w-full py-1.5 rounded-lg text-xs font-bold border-2 border-[#2D2D2D] bg-white hover:bg-[#F5F5F0] flex items-center justify-center gap-1"
        >
          {expanded ? '收起' : '展开'}
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>
      )}
      {expanded && (
        <div className="mt-2 space-y-2 max-h-64 overflow-y-auto">
          {path.hits.map((hit) => (
            <div key={hit.id} className="p-2 rounded-lg bg-white border border-[#2D2D2D] text-xs">
              <div className="flex justify-between font-bold">
                <span className="truncate">{hit.file_path}</span>
                <span style={{ color: config.color }}>{hit.score.toFixed(4)}</span>
              </div>
              <p className="text-[#666] mt-1 line-clamp-3">{hit.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FusionRow({ hit, index }: { hit: DebugFusionHit; index: number }) {
  const sources = hit.sources || [];
  return (
    <div className="p-3 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-black text-sm">#{index + 1}</span>
            <span className="font-bold text-sm truncate">{hit.file_path}</span>
            <span className="text-xs text-[#666]">line {hit.line}</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {sources.map((s) => {
              const cfg = PATH_CONFIG.find((p) => p.key === s);
              if (!cfg) return null;
              return (
                <span
                  key={s}
                  className="px-1.5 py-0.5 rounded text-[10px] font-bold border border-[#2D2D2D]"
                  style={{ background: cfg.bg, color: '#2D2D2D' }}
                >
                  {cfg.label}
                </span>
              );
            })}
          </div>
          <p className="text-xs text-[#666] mt-1 line-clamp-2">{hit.content}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-lg font-black text-[#2D2D2D]">{hit.rrf_score.toFixed(4)}</p>
          <p className="text-[10px] text-[#666]">RRF</p>
        </div>
      </div>
      <div className="grid grid-cols-5 gap-2 mt-2 pt-2 border-t border-[#ccc]">
        {PATH_CONFIG.map((p) => (
          <div key={p.key} className="text-center">
            <p className="text-[10px] text-[#666]">{p.label}</p>
            <p className="text-xs font-black" style={{ color: p.color }}>
              {(hit as any)[`${p.key}_score`]?.toFixed(3) ?? '-'}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ContextView({ context }: { context: CodeContext }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="p-3 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D]">
          <p className="text-xs text-[#666]">Query Intent</p>
          <p className="font-bold text-sm">{context.query_intent}</p>
        </div>
        <div className="p-3 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D]">
          <p className="text-xs text-[#666]">Branch</p>
          <p className="font-bold text-sm">
            {context.branch}
            {context.meta?.branch_fallback && <span className="text-[#ff3d8a] ml-1 text-xs">(fallback)</span>}
          </p>
        </div>
        <div className="p-3 rounded-xl bg-[#F5F5F0] border-2 border-[#2D2D2D]">
          <p className="text-xs text-[#666]">Files / Symbols</p>
          <p className="font-bold text-sm">{context.total_files} / {context.total_symbols}</p>
        </div>
      </div>

      {context.entry_points.length > 0 && (
        <div>
          <h3 className="font-bold mb-2">入口点</h3>
          <div className="space-y-2">
            {context.entry_points.map((ep) => (
              <div key={ep.id} className="p-2 rounded-lg bg-[#2ad4ff10] border border-[#2ad4ff]">
                <span className="font-bold text-sm">{ep.name}</span>
                <span className="text-xs text-[#666] ml-2">{ep.file_path}:{ep.line}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {context.flow_summary && (
        <div>
          <h3 className="font-bold mb-2">Flow Summary</h3>
          <p className="p-3 rounded-xl bg-[#fff34d10] border-2 border-[#fff34d] text-sm">{context.flow_summary}</p>
        </div>
      )}

      {context.related_files.length > 0 && (
        <div>
          <h3 className="font-bold mb-2">Related Files</h3>
          <div className="flex flex-wrap gap-2">
            {context.related_files.map((f) => (
              <span key={f.path} className="px-2 py-1 rounded-lg text-xs font-bold bg-[#6effb010] border border-[#6effb0]">
                {f.path} <span className="text-[#666]">({f.role})</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        <h3 className="font-bold mb-2">Code Snippets（最终采纳）</h3>
        <div className="space-y-3">
          {context.code_snippets.map((snippet, idx) => (
            <SnippetRow key={snippet.filePath + snippet.lineNumber} snippet={snippet} index={idx} />
          ))}
        </div>
      </div>
    </div>
  );
}

function SnippetRow({ snippet, index }: { snippet: SearchResult; index: number }) {
  return (
    <div className="rounded-xl border-2 border-[#2D2D2D] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-[#F5F5F0] border-b-2 border-[#2D2D2D]">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-black text-sm">#{index + 1}</span>
          <span className="font-bold text-sm truncate">{snippet.filePath}</span>
          <span className="text-xs text-[#666]">line {snippet.lineNumber}</span>
        </div>
        <span className="text-xs font-black px-2 py-0.5 rounded bg-white border border-[#2D2D2D]">
          {snippet.score.toFixed(4)}
        </span>
      </div>
      <pre className="p-3 text-xs bg-white overflow-auto max-h-48">
        <code>{snippet.code}</code>
      </pre>
    </div>
  );
}
