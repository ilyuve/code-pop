import { useState, useEffect, useCallback } from 'react';
import { Save, RotateCcw, Sun, Moon, Server, Brain, Plus, Trash2, Play, AlertCircle, CheckCircle2, Loader2, TrendingUp } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';

interface LLMProvider {
  id?: string;
  name: string;
  provider_type: string;
  base_url: string;
  api_key: string;
  model: string;
  capability: 'chat' | 'embed' | 'both';
  priority: number;
  enabled: boolean;
  max_tokens: number;
  temperature: number;
  timeout_seconds: number;
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  extra_headers: string;
  extra_body?: string;
  created_at?: string;
  updated_at?: string;
}

interface UsageSummary {
  period_minutes: number;
  total_calls: number;
  success_calls: number;
  error_calls: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
}

interface LLMSettings {
  enable_index_chinese_enrich: boolean;
  enable_query_llm_expand: boolean;
  enable_flow_label: boolean;
  default_provider_id?: string | null;
}

interface LLMCostBreakdown {
  input_tokens: number;
  output_tokens: number;
  call_count: number;
  cost: number;
}

interface LLMCostEstimate {
  period_minutes: number;
  repo_id: string | null;
  total_cost: number;
  total_input_tokens: number;
  total_output_tokens: number;
  provider_breakdown: Record<string, LLMCostBreakdown>;
  operation_breakdown: Record<string, LLMCostBreakdown>;
}

export const Settings = () => {
  const { settings, updateSettings } = useStore();
  const [apiEndpoint, setApiEndpoint] = useState(settings.apiEndpoint);
  const [embeddingProvider, setEmbeddingProvider] = useState(settings.embeddingProvider);
  const [theme, setTheme] = useState(settings.theme);
  const [hasChanges, setHasChanges] = useState(false);
  const [saved, setSaved] = useState(false);

  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [editingProvider, setEditingProvider] = useState<LLMProvider | null>(null);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; ok: boolean; message: string } | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [llmSettings, setLlmSettings] = useState<LLMSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [cost, setCost] = useState<LLMCostEstimate | null>(null);
  const [costPeriod, setCostPeriod] = useState<number>(60);

  useEffect(() => {
    const changed =
      apiEndpoint !== settings.apiEndpoint ||
      embeddingProvider !== settings.embeddingProvider ||
      theme !== settings.theme;
    setHasChanges(changed);
  }, [apiEndpoint, embeddingProvider, theme, settings]);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const resp = await fetch(`${apiEndpoint}/admin/llm/providers`);
      const data = await resp.json();
      setProviders(data.providers || []);
    } catch (e) {
      console.error('Failed to load providers', e);
    } finally {
      setLoadingProviders(false);
    }
  }, [apiEndpoint]);

  const fetchUsage = useCallback(async () => {
    try {
      const resp = await fetch(`${apiEndpoint}/admin/llm/usage?minutes=60`);
      const data = await resp.json();
      setUsage(data);
    } catch (e) {
      console.error('Failed to load usage', e);
    }
  }, [apiEndpoint]);

  const fetchLlmSettings = useCallback(async () => {
    try {
      const resp = await fetch(`${apiEndpoint}/admin/llm/settings`);
      const data = await resp.json();
      setLlmSettings(data.settings);
    } catch (e) {
      console.error('Failed to load LLM settings', e);
    }
  }, [apiEndpoint]);

  const fetchCost = useCallback(async () => {
    try {
      const resp = await fetch(`${apiEndpoint}/admin/llm/cost?minutes=${costPeriod}`);
      const data = await resp.json();
      setCost(data);
    } catch (e) {
      console.error('Failed to load cost', e);
    }
  }, [apiEndpoint, costPeriod]);

  useEffect(() => {
    fetchProviders();
    fetchUsage();
    fetchLlmSettings();
    fetchCost();
  }, [fetchProviders, fetchUsage, fetchLlmSettings, fetchCost]);

  const saveLlmSettings = async () => {
    if (!llmSettings) return;
    setSavingSettings(true);
    try {
      const resp = await fetch(`${apiEndpoint}/admin/llm/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(llmSettings),
      });
      if (!resp.ok) throw new Error('Save failed');
      const data = await resp.json();
      setLlmSettings(data.settings);
    } catch (e) {
      alert('保存设置失败：' + (e as Error).message);
    } finally {
      setSavingSettings(false);
    }
  };

  const handleSave = () => {
    updateSettings({
      apiEndpoint,
      embeddingProvider,
      theme,
    });
    localStorage.setItem('codepop-api-endpoint', apiEndpoint);
    document.documentElement.classList.toggle('dark', theme === 'dark');
    setHasChanges(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleReset = () => {
    setApiEndpoint('http://localhost:8080/api');
    setEmbeddingProvider('openai');
    setTheme('dark');
    setHasChanges(true);
  };

  const handleThemeChange = (newTheme: 'light' | 'dark') => {
    setTheme(newTheme);
    document.documentElement.classList.toggle('dark', newTheme === 'dark');
  };

  const handleAddProvider = () => {
    setEditingProvider({
      name: '',
      provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com',
      api_key: '',
      model: 'deepseek-chat',
      capability: 'chat',
      priority: providers.length,
      enabled: true,
      max_tokens: 4096,
      temperature: 0.1,
      timeout_seconds: 60,
      cost_per_1k_input: 0,
      cost_per_1k_output: 0,
      extra_headers: '',
      extra_body: '',
    });
    setTestResult(null);
  };

  const handleEditProvider = (provider: LLMProvider) => {
    setEditingProvider({ ...provider, api_key: '' });
    setTestResult(null);
  };

  const handleCancelEdit = () => {
    setEditingProvider(null);
    setTestResult(null);
  };

  const handleSaveProvider = async () => {
    if (!editingProvider) return;
    const url = editingProvider.id
      ? `${apiEndpoint}/admin/llm/providers/${editingProvider.id}`
      : `${apiEndpoint}/admin/llm/providers`;
    const method = editingProvider.id ? 'PUT' : 'POST';
    try {
      const resp = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingProvider),
      });
      if (!resp.ok) throw new Error('Save failed');
      await fetchProviders();
      setEditingProvider(null);
    } catch (e) {
      alert('保存失败：' + (e as Error).message);
    }
  };

  const handleDeleteProvider = async (id: string) => {
    if (!confirm('确定删除这个 Provider 吗？')) return;
    try {
      const resp = await fetch(`${apiEndpoint}/admin/llm/providers/${id}`, { method: 'DELETE' });
      if (!resp.ok) throw new Error('Delete failed');
      await fetchProviders();
    } catch (e) {
      alert('删除失败：' + (e as Error).message);
    }
  };

  const handleTestProvider = async (id: string) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const resp = await fetch(`${apiEndpoint}/admin/llm/providers/${id}/test`, { method: 'POST' });
      const data = await resp.json();
      setTestResult({
        id,
        ok: data.ok,
        message: data.ok
          ? `连接成功，延迟 ${data.latency_ms}ms，模型 ${data.model}`
          : `连接失败：${data.error}`,
      });
    } catch (e) {
      setTestResult({ id, ok: false, message: '请求异常：' + (e as Error).message });
    } finally {
      setTestingId(null);
    }
  };

  const formatNumber = (n: number) => n.toLocaleString();

  return (
    <div className="space-y-6 animate-fadeIn max-w-4xl">
      {/* API Configuration */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-indigo-100 dark:bg-indigo-900/30 rounded-lg">
            <Server className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">API 配置</h2>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            API 端点地址
          </label>
          <input
            type="text"
            value={apiEndpoint}
            onChange={(e) => setApiEndpoint(e.target.value)}
            placeholder="http://localhost:8080/api"
            className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">CodePop 后端服务的 API 地址</p>
        </div>
      </section>

      {/* LLM Provider Management */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-violet-100 dark:bg-violet-900/30 rounded-lg">
              <Brain className="w-5 h-5 text-violet-600 dark:text-violet-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">LLM Provider 管理</h2>
          </div>
          <button
            onClick={handleAddProvider}
            disabled={editingProvider !== null}
            className="flex items-center gap-2 px-4 py-2 bg-violet-500 hover:bg-violet-600 disabled:bg-slate-300 text-white rounded-lg text-sm font-medium"
          >
            <Plus className="w-4 h-4" />
            新增 Provider
          </button>
        </div>

        {editingProvider && (
          <div className="mb-6 p-4 bg-slate-50 dark:bg-slate-700/50 rounded-xl border border-slate-200 dark:border-slate-600 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">名称</label>
                <input
                  type="text"
                  value={editingProvider.name}
                  onChange={(e) => setEditingProvider({ ...editingProvider, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">协议类型</label>
                <select
                  value={editingProvider.provider_type}
                  onChange={(e) => setEditingProvider({ ...editingProvider, provider_type: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                >
                  <option value="openai_compatible">OpenAI Compatible</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="glm">GLM</option>
                  <option value="azure">Azure</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Base URL</label>
                <input
                  type="text"
                  value={editingProvider.base_url}
                  onChange={(e) => setEditingProvider({ ...editingProvider, base_url: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">API Key</label>
                <input
                  type="password"
                  value={editingProvider.api_key}
                  onChange={(e) => setEditingProvider({ ...editingProvider, api_key: e.target.value })}
                  placeholder={editingProvider.id ? '留空表示不修改' : ''}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">模型</label>
                <input
                  type="text"
                  value={editingProvider.model}
                  onChange={(e) => setEditingProvider({ ...editingProvider, model: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">能力</label>
                <select
                  value={editingProvider.capability}
                  onChange={(e) => setEditingProvider({ ...editingProvider, capability: e.target.value as LLMProvider['capability'] })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                >
                  <option value="chat">Chat</option>
                  <option value="embed">Embed</option>
                  <option value="both">Both</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">优先级（越小越优先）</label>
                <input
                  type="number"
                  value={editingProvider.priority}
                  onChange={(e) => setEditingProvider({ ...editingProvider, priority: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Max Tokens</label>
                <input
                  type="number"
                  value={editingProvider.max_tokens}
                  onChange={(e) => setEditingProvider({ ...editingProvider, max_tokens: parseInt(e.target.value) || 4096 })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Temperature</label>
                <input
                  type="number"
                  step="0.1"
                  value={editingProvider.temperature}
                  onChange={(e) => setEditingProvider({ ...editingProvider, temperature: parseFloat(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">超时（秒）</label>
                <input
                  type="number"
                  value={editingProvider.timeout_seconds}
                  onChange={(e) => setEditingProvider({ ...editingProvider, timeout_seconds: parseInt(e.target.value) || 60 })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">输入成本 / 1K tokens（USD）</label>
                <input
                  type="number"
                  step="0.000001"
                  value={editingProvider.cost_per_1k_input}
                  onChange={(e) => setEditingProvider({ ...editingProvider, cost_per_1k_input: parseFloat(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">输出成本 / 1K tokens（USD）</label>
                <input
                  type="number"
                  step="0.000001"
                  value={editingProvider.cost_per_1k_output}
                  onChange={(e) => setEditingProvider({ ...editingProvider, cost_per_1k_output: parseFloat(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
                />
              </div>
              <div className="flex items-center gap-3">
                <input
                  id="enabled"
                  type="checkbox"
                  checked={editingProvider.enabled}
                  onChange={(e) => setEditingProvider({ ...editingProvider, enabled: e.target.checked })}
                  className="w-4 h-4 rounded border-slate-300 text-violet-600 focus:ring-violet-500"
                />
                <label htmlFor="enabled" className="text-sm text-slate-700 dark:text-slate-300">启用</label>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Extra Headers（JSON）</label>
                <textarea
                  value={editingProvider.extra_headers}
                  onChange={(e) => setEditingProvider({ ...editingProvider, extra_headers: e.target.value })}
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm font-mono"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Extra Body（JSON）</label>
                <textarea
                  value={editingProvider.extra_body}
                  onChange={(e) => setEditingProvider({ ...editingProvider, extra_body: e.target.value })}
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm font-mono"
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleSaveProvider}
                className="flex items-center gap-2 px-4 py-2 bg-violet-500 hover:bg-violet-600 text-white rounded-lg text-sm font-medium"
              >
                <Save className="w-4 h-4" />
                保存
              </button>
              <button
                onClick={handleCancelEdit}
                className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg text-sm"
              >
                取消
              </button>
            </div>
          </div>
        )}

        {loadingProviders ? (
          <div className="flex items-center justify-center py-8 text-slate-500 dark:text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            加载中...
          </div>
        ) : (
          <div className="space-y-3">
            {providers.length === 0 && (
              <div className="text-center py-8 text-slate-500 dark:text-slate-400 text-sm">
                暂无 Provider，点击右上角添加（支持 DeepSeek / GLM / OpenAI 等兼容 API）
              </div>
            )}
            {providers.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between p-4 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-violet-200 dark:hover:border-violet-800 transition-colors"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900 dark:text-white">{p.name}</span>
                    <span className={clsx(
                      'px-2 py-0.5 rounded text-xs font-medium',
                      p.enabled
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                        : 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400'
                    )}>
                      {p.enabled ? '启用' : '禁用'}
                    </span>
                    <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400">
                      {p.capability}
                    </span>
                    <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400">
                      {p.provider_type}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {p.model} · 优先级 {p.priority} · {p.base_url}
                    {(p.cost_per_1k_input || p.cost_per_1k_output) && (
                      <span className="ml-2">
                        ${p.cost_per_1k_input}/1K in · ${p.cost_per_1k_output}/1K out
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {testResult && testResult.id === p.id && (
                    <div className={clsx(
                      'flex items-center gap-1 text-xs',
                      testResult.ok
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-rose-600 dark:text-rose-400'
                    )}>
                      {testResult.ok ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
                      <span className="max-w-[200px] truncate">{testResult.message}</span>
                    </div>
                  )}
                  <button
                    onClick={() => p.id && handleTestProvider(p.id)}
                    disabled={testingId === p.id}
                    className="p-2 text-slate-500 hover:text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/20 rounded-lg transition-colors"
                    title="测试连接"
                  >
                    {testingId === p.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                  </button>
                  <button
                    onClick={() => handleEditProvider(p)}
                    className="p-2 text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg transition-colors"
                    title="编辑"
                  >
                    <Server className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => p.id && handleDeleteProvider(p.id)}
                    className="p-2 text-slate-500 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20 rounded-lg transition-colors"
                    title="删除"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Global LLM Settings */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
              <Server className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">LLM 功能开关</h2>
          </div>
          <button
            onClick={saveLlmSettings}
            disabled={savingSettings}
            className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-slate-300 text-white rounded-lg text-sm font-medium"
          >
            {savingSettings ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存开关
          </button>
        </div>
        {llmSettings ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50">
              <div>
                <div className="text-sm font-medium text-slate-900 dark:text-white">索引中文语义增强</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">为代码片段生成中文摘要、关键词和同义词</div>
              </div>
              <input
                type="checkbox"
                checked={llmSettings.enable_index_chinese_enrich}
                onChange={(e) => setLlmSettings({ ...llmSettings, enable_index_chinese_enrich: e.target.checked })}
                className="w-5 h-5 rounded border-slate-300 text-amber-600 focus:ring-amber-500"
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50">
              <div>
                <div className="text-sm font-medium text-slate-900 dark:text-white">查询 LLM 扩展</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">本地同义词未命中时请求 LLM 生成扩展词</div>
              </div>
              <input
                type="checkbox"
                checked={llmSettings.enable_query_llm_expand}
                onChange={(e) => setLlmSettings({ ...llmSettings, enable_query_llm_expand: e.target.checked })}
                className="w-5 h-5 rounded border-slate-300 text-amber-600 focus:ring-amber-500"
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50">
              <div>
                <div className="text-sm font-medium text-slate-900 dark:text-white">Flow Label 生成</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">为符号生成层、模块、中文名等流程标签</div>
              </div>
              <input
                type="checkbox"
                checked={llmSettings.enable_flow_label}
                onChange={(e) => setLlmSettings({ ...llmSettings, enable_flow_label: e.target.checked })}
                className="w-5 h-5 rounded border-slate-300 text-amber-600 focus:ring-amber-500"
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50">
              <div>
                <div className="text-sm font-medium text-slate-900 dark:text-white">默认 Provider</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">未指定时使用的 LLM Provider</div>
              </div>
              <select
                value={llmSettings.default_provider_id || ''}
                onChange={(e) => setLlmSettings({ ...llmSettings, default_provider_id: e.target.value || null })}
                className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
              >
                <option value="">自动选择</option>
                {providers.filter((p) => p.enabled).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <div className="text-center py-6 text-slate-500 dark:text-slate-400 text-sm">加载中...</div>
        )}
      </section>

      {/* Cost Dashboard */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-100 dark:bg-emerald-900/30 rounded-lg">
              <TrendingUp className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">LLM 成本估算</h2>
          </div>
          <select
            value={costPeriod}
            onChange={(e) => setCostPeriod(parseInt(e.target.value))}
            className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-900 dark:text-white text-sm"
          >
            <option value={60}>最近 1 小时</option>
            <option value={360}>最近 6 小时</option>
            <option value={1440}>最近 24 小时</option>
            <option value={10080}>最近 7 天</option>
          </select>
        </div>
        {cost ? (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
                <div className="text-xs text-slate-500 dark:text-slate-400">预估总成本</div>
                <div className="text-xl font-semibold text-slate-900 dark:text-white">${cost.total_cost.toFixed(6)}</div>
              </div>
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
                <div className="text-xs text-slate-500 dark:text-slate-400">输入 Tokens</div>
                <div className="text-xl font-semibold text-slate-900 dark:text-white">{formatNumber(cost.total_input_tokens)}</div>
              </div>
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
                <div className="text-xs text-slate-500 dark:text-slate-400">输出 Tokens</div>
                <div className="text-xl font-semibold text-slate-900 dark:text-white">{formatNumber(cost.total_output_tokens)}</div>
              </div>
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
                <div className="text-xs text-slate-500 dark:text-slate-400">调用次数</div>
                <div className="text-xl font-semibold text-slate-900 dark:text-white">
                  {formatNumber(Object.values(cost.provider_breakdown).reduce((sum, p) => sum + p.call_count, 0))}
                </div>
              </div>
            </div>
            {Object.keys(cost.provider_breakdown).length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-3">按 Provider</h3>
                <div className="space-y-2">
                  {Object.entries(cost.provider_breakdown).map(([name, data]) => (
                    <div key={name} className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50">
                      <div className="text-sm text-slate-700 dark:text-slate-300">{name}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {data.call_count} 次 · {formatNumber(data.input_tokens)} / {formatNumber(data.output_tokens)} tokens · ${data.cost.toFixed(6)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {Object.keys(cost.operation_breakdown).length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-slate-900 dark:text-white mb-3">按 Operation</h3>
                <div className="space-y-2">
                  {Object.entries(cost.operation_breakdown).map(([name, data]) => (
                    <div key={name} className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-700/50">
                      <div className="text-sm text-slate-700 dark:text-slate-300">{name}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {data.call_count} 次 · {formatNumber(data.input_tokens)} / {formatNumber(data.output_tokens)} tokens · ${data.cost.toFixed(6)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-6 text-slate-500 dark:text-slate-400 text-sm">暂无数据</div>
        )}
      </section>

      {/* Usage Dashboard */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-emerald-100 dark:bg-emerald-900/30 rounded-lg">
            <TrendingUp className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">LLM 用量监控（最近 1 小时）</h2>
        </div>
        {usage ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
              <div className="text-xs text-slate-500 dark:text-slate-400">总调用</div>
              <div className="text-xl font-semibold text-slate-900 dark:text-white">{usage.total_calls}</div>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
              <div className="text-xs text-slate-500 dark:text-slate-400">成功 / 失败</div>
              <div className="text-xl font-semibold text-slate-900 dark:text-white">
                {usage.success_calls} / {usage.error_calls}
              </div>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
              <div className="text-xs text-slate-500 dark:text-slate-400">输入 / 输出 Tokens</div>
              <div className="text-xl font-semibold text-slate-900 dark:text-white">
                {formatNumber(usage.input_tokens)} / {formatNumber(usage.output_tokens)}
              </div>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
              <div className="text-xs text-slate-500 dark:text-slate-400">总延迟</div>
              <div className="text-xl font-semibold text-slate-900 dark:text-white">{usage.latency_ms}ms</div>
            </div>
          </div>
        ) : (
          <div className="text-center py-6 text-slate-500 dark:text-slate-400 text-sm">暂无数据</div>
        )}
      </section>

      {/* Embedding Provider */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-emerald-100 dark:bg-emerald-900/30 rounded-lg">
            <Brain className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Embedding 提供商</h2>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <button
            onClick={() => setEmbeddingProvider('openai')}
            className={clsx(
              'p-4 rounded-xl border-2 transition-all duration-200 text-left',
              embeddingProvider === 'openai'
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
            )}
          >
            <h3 className="font-semibold text-slate-900 dark:text-white mb-1">OpenAI</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">使用 OpenAI API 进行 embedding</p>
          </button>
          <button
            onClick={() => setEmbeddingProvider('local')}
            className={clsx(
              'p-4 rounded-xl border-2 transition-all duration-200 text-left',
              embeddingProvider === 'local'
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
            )}
          >
            <h3 className="font-semibold text-slate-900 dark:text-white mb-1">本地模型</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">使用本地部署的 embedding 模型</p>
          </button>
        </div>
      </section>

      {/* Theme Toggle */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
            {theme === 'dark' ? (
              <Moon className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            ) : (
              <Sun className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            )}
          </div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">主题设置</h2>
        </div>
        <div className="flex gap-4">
          <button
            onClick={() => handleThemeChange('light')}
            className={clsx(
              'flex-1 p-4 rounded-xl border-2 transition-all duration-200 flex flex-col items-center gap-2',
              theme === 'light'
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
            )}
          >
            <Sun className="w-6 h-6 text-amber-500" />
            <span className="font-medium text-slate-900 dark:text-white">浅色</span>
          </button>
          <button
            onClick={() => handleThemeChange('dark')}
            className={clsx(
              'flex-1 p-4 rounded-xl border-2 transition-all duration-200 flex flex-col items-center gap-2',
              theme === 'dark'
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
            )}
          >
            <Moon className="w-6 h-6 text-indigo-500" />
            <span className="font-medium text-slate-900 dark:text-white">深色</span>
          </button>
        </div>
      </section>

      {/* Action Buttons */}
      <div className="flex gap-3">
        <button
          onClick={handleSave}
          disabled={!hasChanges}
          className={clsx(
            'flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-all duration-200',
            hasChanges
              ? 'bg-indigo-500 hover:bg-indigo-600 text-white'
              : 'bg-slate-100 dark:bg-slate-700 text-slate-400 cursor-not-allowed'
          )}
        >
          <Save className="w-5 h-5" />
          {saved ? '已保存!' : '保存设置'}
        </button>
        <button
          onClick={handleReset}
          className="flex items-center gap-2 px-6 py-3 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 rounded-xl font-medium transition-colors"
        >
          <RotateCcw className="w-5 h-5" />
          重置
        </button>
      </div>
    </div>
  );
};
