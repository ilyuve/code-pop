import { useState, useEffect, useCallback } from 'react';
import { Save, Server, Plus, Trash2, Play, AlertCircle, CheckCircle2, Loader2, Brain } from 'lucide-react';
import {
  fetchLLMProviders,
  fetchLLMSettings,
  saveLLMSettings,
  saveLLMProvider,
  deleteLLMProvider,
  testLLMProvider,
} from '../api';
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

interface LLMSettings {
  enable_index_chinese_enrich: boolean;
  enable_query_llm_expand: boolean;
  enable_flow_label: boolean;
  default_provider_id?: string | null;
}

// 已知厂商的 USD/1K tokens 参考单价（供新增 Provider 时预填，用户可按实际套餐修改）。
const PRESET_COSTS: Record<string, { input: number; output: number }> = {
  deepseek: { input: 0.00027, output: 0.0011 },
  glm: { input: 0.0001, output: 0.0001 },
  openai_compatible: { input: 0, output: 0 },
  azure: { input: 0, output: 0 },
  custom: { input: 0, output: 0 },
};

export const Settings = () => {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [editingProvider, setEditingProvider] = useState<LLMProvider | null>(null);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; ok: boolean; message: string } | null>(null);
  const [llmSettings, setLlmSettings] = useState<LLMSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const data = await fetchLLMProviders();
      setProviders(data);
    } catch (e) {
      console.error('Failed to load providers', e);
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  const fetchLlmSettings = useCallback(async () => {
    try {
      const data = await fetchLLMSettings();
      setLlmSettings(data);
    } catch (e) {
      console.error('Failed to load LLM settings', e);
    }
  }, []);

  useEffect(() => {
    fetchProviders();
    fetchLlmSettings();
  }, [fetchProviders, fetchLlmSettings]);

  const saveLlmSettings = async () => {
    if (!llmSettings) return;
    setSavingSettings(true);
    try {
      const data = await saveLLMSettings(llmSettings);
      setLlmSettings(data);
    } catch (e) {
      alert('保存设置失败：' + (e as Error).message);
    } finally {
      setSavingSettings(false);
    }
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

  // 切换协议类型时预填已知厂商的 USD/1K tokens 参考单价。
  const handleProviderTypeChange = (providerType: string) => {
    setEditingProvider((prev) => {
      if (!prev) return prev;
      const preset = PRESET_COSTS[providerType];
      return {
        ...prev,
        provider_type: providerType,
        cost_per_1k_input: preset ? preset.input : prev.cost_per_1k_input,
        cost_per_1k_output: preset ? preset.output : prev.cost_per_1k_output,
      };
    });
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
    try {
      await saveLLMProvider(editingProvider);
      await fetchProviders();
      setEditingProvider(null);
    } catch (e) {
      alert('保存失败：' + (e as Error).message);
    }
  };

  const handleDeleteProvider = async (id: string) => {
    if (!confirm('确定删除这个 Provider 吗？')) return;
    try {
      await deleteLLMProvider(id);
      await fetchProviders();
    } catch (e) {
      alert('删除失败：' + (e as Error).message);
    }
  };

  const handleTestProvider = async (id: string) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const data = await testLLMProvider(id);
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

  return (
    <div className="space-y-6 animate-fadeIn max-w-7xl mx-auto">
      {/* MCP 接入说明 */}
      <section className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-[#ff3d8a] rounded-lg border-2 border-[#2D2D2D] shadow-[2px_2px_0_#2D2D2D]">
            <Server className="w-5 h-5 text-white" />
          </div>
          <h2 className="text-lg font-black text-[#2D2D2D]">MCP 接入</h2>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-4 leading-relaxed">
          在 Claude Code / Cursor / Trae 等 AI 工具的 MCP 配置中添加以下任一服务器，即可让 AI 直接检索你的代码库
          （<strong className="text-slate-600 dark:text-slate-300">search_code</strong>、
          <strong className="text-slate-600 dark:text-slate-300">analyze_impact</strong>、
          <strong className="text-slate-600 dark:text-slate-300">list_repositories</strong>、
          <strong className="text-slate-600 dark:text-slate-300">list_file_symbols</strong> 等工具）。
          地址中的 <code className="font-mono bg-white px-1 rounded">HOST</code> 请替换为你的 CodePop 服务器地址（公网 IP 或内网 IP 均可）。
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div className="rounded-xl border-2 border-[#2D2D2D] p-4 bg-[#F5F5F0]">
            <div className="text-sm font-bold text-[#2D2D2D] mb-2">Claude Code / Cursor</div>
            <pre className="text-xs font-mono bg-white border border-slate-200 rounded-lg p-3 overflow-x-auto text-[#2D2D2D]">{`{
  "mcpServers": {
    "codepop": {
      "type": "http",
      "url": "http://HOST:18080/mcp/sse"
    }
  }
}`}</pre>
          </div>
          <div className="rounded-xl border-2 border-[#2D2D2D] p-4 bg-[#F5F5F0]">
            <div className="text-sm font-bold text-[#2D2D2D] mb-2">Trae</div>
            <pre className="text-xs font-mono bg-white border border-slate-200 rounded-lg p-3 overflow-x-auto text-[#2D2D2D]">{`{
  "mcpServers": {
    "codepop": {
      "url": "http://HOST:18080/mcp/http"
    }
  }
}`}</pre>
          </div>
        </div>

        <div className="flex items-start gap-2 rounded-lg bg-[#fff34d]/30 border-2 border-[#2D2D2D] p-3">
          <AlertCircle className="w-4 h-4 text-[#2D2D2D] shrink-0 mt-0.5" />
          <p className="text-xs text-[#2D2D2D] leading-relaxed">
            注意：Trae 会按 URL 后缀自动选择传输协议，<code className="font-mono bg-white px-1 rounded">/mcp/sse</code> 结尾会被判定为旧版 SSE 导致连接超时，
            因此 Trae 请使用 <code className="font-mono bg-white px-1 rounded">/mcp/http</code>；Claude Code / Cursor 使用 <code className="font-mono bg-white px-1 rounded">/mcp/sse</code> 即可。
            接入后直接在 AI 对话中提问，如「帮我找一下登录的 JWT 验证逻辑在哪」「这个项目的限流是怎么实现的」，AI 会自动调用 CodePop 检索并返回结果。
          </p>
        </div>
      </section>

      {/* LLM Provider Management */}
      <section className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[#fff34d] rounded-lg border-2 border-[#2D2D2D] shadow-[2px_2px_0_#2D2D2D]">
              <Brain className="w-5 h-5 text-[#2D2D2D]" />
            </div>
            <h2 className="text-lg font-black text-[#2D2D2D]">LLM Provider 管理</h2>
          </div>
          <button
            onClick={handleAddProvider}
            disabled={editingProvider !== null}
            className="flex items-center gap-2 px-4 py-2 bg-[#ff3d8a] hover:bg-[#ff5c9d] disabled:bg-slate-300 text-white border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] rounded-lg text-sm font-bold"
          >
            <Plus className="w-4 h-4" />
            新增 Provider
          </button>
        </div>

        <p className="text-xs text-slate-500 dark:text-slate-400 mb-5 leading-relaxed">
          该配置用于 Code:Pop 的<strong className="text-slate-600 dark:text-slate-300">中文增强能力</strong>：
          索引时为代码块生成中文摘要、关键词、同义词（中文语义增强），为符号生成流程标签（Flow Label），
          查询时用 LLM 生成扩展词（查询 LLM 扩展）。未配置或未启用时，这些中文能力会被跳过、按本地词库降级运行。
          「输入/输出成本」以 USD/1K tokens 为单位填写，用于下方「LLM 成本估算」面板（如 DeepSeek 约输入 0.00027、输出 0.0011，可参考厂商官网按实际套餐调整）。
        </p>

        {editingProvider && (
          <div className="mb-6 p-4 bg-slate-50 dark:bg-slate-700/50 rounded-xl border border-slate-200 dark:border-slate-600 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">名称</label>
                <input
                  type="text"
                  value={editingProvider.name}
                  onChange={(e) => setEditingProvider({ ...editingProvider, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">协议类型</label>
                <select
                  value={editingProvider.provider_type}
                  onChange={(e) => handleProviderTypeChange(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
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
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">API Key</label>
                <input
                  type="password"
                  value={editingProvider.api_key}
                  onChange={(e) => setEditingProvider({ ...editingProvider, api_key: e.target.value })}
                  placeholder={editingProvider.id ? '留空表示不修改' : ''}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">模型</label>
                <input
                  type="text"
                  value={editingProvider.model}
                  onChange={(e) => setEditingProvider({ ...editingProvider, model: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">能力</label>
                <select
                  value={editingProvider.capability}
                  onChange={(e) => setEditingProvider({ ...editingProvider, capability: e.target.value as LLMProvider['capability'] })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
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
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Max Tokens</label>
                <input
                  type="number"
                  value={editingProvider.max_tokens}
                  onChange={(e) => setEditingProvider({ ...editingProvider, max_tokens: parseInt(e.target.value) || 4096 })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Temperature</label>
                <input
                  type="number"
                  step="0.1"
                  value={editingProvider.temperature}
                  onChange={(e) => setEditingProvider({ ...editingProvider, temperature: parseFloat(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">超时（秒）</label>
                <input
                  type="number"
                  value={editingProvider.timeout_seconds}
                  onChange={(e) => setEditingProvider({ ...editingProvider, timeout_seconds: parseInt(e.target.value) || 60 })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">输入成本（USD/1K tokens）</label>
                <input
                  type="number"
                  step="0.000001"
                  value={editingProvider.cost_per_1k_input}
                  onChange={(e) => setEditingProvider({ ...editingProvider, cost_per_1k_input: parseFloat(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">输出成本（USD/1K tokens）</label>
                <input
                  type="number"
                  step="0.000001"
                  value={editingProvider.cost_per_1k_output}
                  onChange={(e) => setEditingProvider({ ...editingProvider, cost_per_1k_output: parseFloat(e.target.value) || 0 })}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div className="flex items-center gap-3">
                <input
                  id="enabled"
                  type="checkbox"
                  checked={editingProvider.enabled}
                  onChange={(e) => setEditingProvider({ ...editingProvider, enabled: e.target.checked })}
                  className="w-4 h-4 rounded border-2 border-[#2D2D2D] accent-[#ff3d8a]"
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
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm font-mono focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Extra Body（JSON）</label>
                <textarea
                  value={editingProvider.extra_body}
                  onChange={(e) => setEditingProvider({ ...editingProvider, extra_body: e.target.value })}
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg border-2 border-[#2D2D2D] bg-white text-[#2D2D2D] text-sm font-mono focus:outline-none focus:border-[#2ad4ff] focus:shadow-[2px_2px_0_#2ad4ff] transition-all"
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleSaveProvider}
                className="flex items-center gap-2 px-4 py-2 bg-[#2ad4ff] hover:bg-[#4adee0] text-[#2D2D2D] border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] rounded-lg text-sm font-bold"
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
                className="flex items-center justify-between p-4 rounded-xl border-2 border-[#2D2D2D] shadow-[2px_2px_0_#2D2D2D] hover:translate-y-[-2px] hover:shadow-[4px_4px_0_#2D2D2D] transition-all"
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
      <section className="bg-white rounded-xl border-2 border-[#2D2D2D] shadow-[4px_4px_0_#2D2D2D] p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[#2ad4ff] rounded-lg border-2 border-[#2D2D2D] shadow-[2px_2px_0_#2D2D2D]">
              <Server className="w-5 h-5 text-[#2D2D2D]" />
            </div>
            <h2 className="text-lg font-black text-[#2D2D2D]">LLM 功能开关</h2>
          </div>
          <button
            onClick={saveLlmSettings}
            disabled={savingSettings}
            className="flex items-center gap-2 px-4 py-2 bg-[#6effb0] hover:bg-[#8dffc5] disabled:bg-slate-300 text-[#2D2D2D] border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] rounded-lg text-sm font-bold"
          >
            {savingSettings ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存开关
          </button>
        </div>
        {llmSettings ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between p-3 rounded-lg bg-[#F5F5F0] border-2 border-[#2D2D2D]">
              <div>
                <div className="text-sm font-medium text-slate-900 dark:text-white">索引中文语义增强</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">为代码片段生成中文摘要、关键词和同义词</div>
              </div>
              <input
                type="checkbox"
                checked={llmSettings.enable_index_chinese_enrich}
                onChange={(e) => setLlmSettings({ ...llmSettings, enable_index_chinese_enrich: e.target.checked })}
                className="w-5 h-5 rounded border-2 border-[#2D2D2D] accent-[#ff3d8a]"
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-[#F5F5F0] border-2 border-[#2D2D2D]">
              <div>
                <div className="text-sm font-medium text-slate-900 dark:text-white">查询 LLM 扩展</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">本地同义词未命中时请求 LLM 生成扩展词</div>
              </div>
              <input
                type="checkbox"
                checked={llmSettings.enable_query_llm_expand}
                onChange={(e) => setLlmSettings({ ...llmSettings, enable_query_llm_expand: e.target.checked })}
                className="w-5 h-5 rounded border-2 border-[#2D2D2D] accent-[#ff3d8a]"
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-[#F5F5F0] border-2 border-[#2D2D2D]">
              <div>
                <div className="text-sm font-medium text-slate-900 dark:text-white">Flow Label 生成</div>
                <div className="text-xs text-slate-500 dark:text-slate-400">为符号生成层、模块、中文名等流程标签</div>
              </div>
              <input
                type="checkbox"
                checked={llmSettings.enable_flow_label}
                onChange={(e) => setLlmSettings({ ...llmSettings, enable_flow_label: e.target.checked })}
                className="w-5 h-5 rounded border-2 border-[#2D2D2D] accent-[#ff3d8a]"
              />
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-[#F5F5F0] border-2 border-[#2D2D2D]">
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
    </div>
  );
};
