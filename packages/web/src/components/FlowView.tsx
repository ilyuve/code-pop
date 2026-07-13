import type { CodeContext } from '../types';
import { CodePreview } from './CodePreview';
import { DegradationBanner } from './DegradationBanner';
import { FileText, GitBranch, ArrowUpCircle, ArrowDownCircle, Folder, Zap } from 'lucide-react';

interface FlowViewProps {
  context: CodeContext;
}

const INTENT_LABELS: Record<string, string> = {
  how_it_works: '流程理解',
  impact_analysis: '影响分析',
  symbol_lookup: '符号定位',
  find_bug: '问题排查',
  general: '通用搜索',
};

const INTENT_COLORS: Record<string, string> = {
  how_it_works: 'bg-blue-100 text-blue-600',
  impact_analysis: 'bg-red-100 text-red-600',
  symbol_lookup: 'bg-green-100 text-green-600',
  find_bug: 'bg-yellow-100 text-yellow-600',
  general: 'bg-gray-100 text-gray-600',
};

const ROLE_LABELS: Record<string, string> = {
  controller: 'Controller',
  service: 'Service',
  repository: 'Repository',
  model: 'Model',
  config: 'Config',
  middleware: 'Middleware',
  utility: 'Utility',
  test: 'Test',
  other: 'Other',
};

const ROLE_COLORS: Record<string, string> = {
  controller: 'bg-pink-100 text-pink-600',
  service: 'bg-blue-100 text-blue-600',
  repository: 'bg-green-100 text-green-600',
  model: 'bg-yellow-100 text-yellow-600',
  config: 'bg-purple-100 text-purple-600',
  middleware: 'bg-orange-100 text-orange-600',
  utility: 'bg-gray-100 text-gray-600',
  test: 'bg-teal-100 text-teal-600',
  other: 'bg-slate-100 text-slate-600',
};

export const FlowView = ({ context }: FlowViewProps) => {
  return (
    <div className="flow-view space-y-6">
      <DegradationBanner degraded={context.degraded || false} reason={context.degradation_reason} />
      <div className="flex items-center gap-4">
        <div className={`px-3 py-1 rounded-full text-sm font-medium ${INTENT_COLORS[context.query_intent] || INTENT_COLORS.general}`}>
          意图: {INTENT_LABELS[context.query_intent] || context.query_intent}
        </div>
        {context.matched_concepts.length > 0 && (
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-yellow-500" />
            <span className="text-sm text-slate-500">
              匹配: {context.matched_concepts.slice(0, 5).join(', ')}
              {context.matched_concepts.length > 5 && ` +${context.matched_concepts.length - 5}`}
            </span>
          </div>
        )}
        <span className="text-sm text-slate-400 ml-auto">
          耗时 {context.search_latency_ms}ms
        </span>
      </div>

      {context.entry_points.length > 0 && (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
          <h3 className="flex items-center gap-2 text-lg font-semibold text-slate-800 dark:text-slate-200 mb-4">
            <GitBranch className="w-5 h-5 text-indigo-500" />
            入口点 ({context.total_symbols})
          </h3>
          <div className="space-y-3">
            {context.entry_points.map((ep) => (
              <div
                key={ep.id}
                className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-100 dark:border-slate-700"
              >
                <div className="flex items-center gap-3">
                  <FileText className="w-4 h-4 text-slate-400" />
                  <div>
                    <span className="font-medium text-slate-800 dark:text-slate-200">{ep.name}</span>
                    <span className="text-slate-400 text-sm ml-2">({ep.type})</span>
                  </div>
                </div>
                <div className="text-sm text-slate-500">
                  {ep.file_path}:{ep.line}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {context.call_chain && (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
          <h3 className="flex items-center gap-2 text-lg font-semibold text-slate-800 dark:text-slate-200 mb-4">
            <GitBranch className="w-5 h-5 text-indigo-500" />
            调用链 (深度: {context.call_chain.depth})
          </h3>
          <div className="chain-graph space-y-6">
            {context.call_chain.upstream.length > 0 && (
              <div className="upstream">
                <h4 className="flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                  <ArrowUpCircle className="w-4 h-4 text-red-400" />
                  上游调用者
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {context.call_chain.upstream.map((s) => (
                    <div
                      key={s.id}
                      className="p-3 bg-red-50 dark:bg-red-900/10 rounded-lg border border-red-100 dark:border-red-800"
                    >
                      <div className="font-medium text-slate-800 dark:text-slate-200">{s.name}</div>
                      <div className="text-xs text-slate-500 mt-1">{s.file_path}:{s.line}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="root-node flex justify-center py-4">
              <div className="px-6 py-3 bg-indigo-50 dark:bg-indigo-900/20 rounded-xl border-2 border-indigo-200 dark:border-indigo-700 text-center">
                <div className="text-sm text-indigo-500 mb-1">入口函数</div>
                <div className="font-semibold text-indigo-700 dark:text-indigo-300">
                  {context.call_chain.root.name}
                </div>
                <div className="text-xs text-indigo-400 mt-1">
                  {context.call_chain.root.file_path}:{context.call_chain.root.line}
                </div>
              </div>
            </div>

            {context.call_chain.downstream.length > 0 && (
              <div className="downstream">
                <h4 className="flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                  <ArrowDownCircle className="w-4 h-4 text-green-400" />
                  下游被调用者
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {context.call_chain.downstream.map((s) => (
                    <div
                      key={s.id}
                      className="p-3 bg-green-50 dark:bg-green-900/10 rounded-lg border border-green-100 dark:border-green-800"
                    >
                      <div className="font-medium text-slate-800 dark:text-slate-200">{s.name}</div>
                      <div className="text-xs text-slate-500 mt-1">{s.file_path}:{s.line}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {context.related_files.length > 0 && (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
          <h3 className="flex items-center gap-2 text-lg font-semibold text-slate-800 dark:text-slate-200 mb-4">
            <Folder className="w-5 h-5 text-indigo-500" />
            涉及文件 ({context.total_files})
          </h3>
          <div className="flex flex-wrap gap-2">
            {context.related_files.map((f) => (
              <div
                key={f.path}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${ROLE_COLORS[f.role] || ROLE_COLORS.other} border-transparent`}
              >
                <span className="text-xs font-medium">{ROLE_LABELS[f.role] || f.role}</span>
                <span className="text-sm truncate max-w-xs">{f.path}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-slate-800 dark:text-slate-200 mb-4">
          <FileText className="w-5 h-5 text-indigo-500" />
          代码片段 ({context.code_snippets.length})
        </h3>
        <div className="space-y-4">
          {context.code_snippets.map((snippet, index) => (
            <div
              key={index}
              className="bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-100 dark:border-slate-700 overflow-hidden"
            >
              <div className="flex items-center justify-between px-4 py-2 bg-slate-100 dark:bg-slate-800/80">
                <div className="flex items-center gap-2 text-sm">
                  <FileText className="w-4 h-4 text-slate-400" />
                  <span className="text-slate-600 dark:text-slate-300">{snippet.filePath}</span>
                  <span className="text-slate-400">行 {snippet.lineNumber}</span>
                </div>
                <span className="text-xs px-2 py-1 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 rounded">
                  {snippet.repoName}
                </span>
              </div>
              <CodePreview code={snippet.code} language="typescript" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};