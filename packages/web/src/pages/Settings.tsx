import { useState, useEffect } from 'react';
import { Save, RotateCcw, Sun, Moon, Server, Brain } from 'lucide-react';
import { useStore } from '../store';
import { clsx } from 'clsx';

export const Settings = () => {
  const { settings, updateSettings } = useStore();
  const [apiEndpoint, setApiEndpoint] = useState(settings.apiEndpoint);
  const [embeddingProvider, setEmbeddingProvider] = useState(settings.embeddingProvider);
  const [theme, setTheme] = useState(settings.theme);
  const [hasChanges, setHasChanges] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const changed =
      apiEndpoint !== settings.apiEndpoint ||
      embeddingProvider !== settings.embeddingProvider ||
      theme !== settings.theme;
    setHasChanges(changed);
  }, [apiEndpoint, embeddingProvider, theme, settings]);

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

  return (
    <div className="space-y-6 animate-fadeIn max-w-2xl">
      {/* API Configuration */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-indigo-100 dark:bg-indigo-900/30 rounded-lg">
            <Server className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            API 配置
          </h2>
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
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            CodePop 后端服务的 API 地址
          </p>
        </div>
      </section>

      {/* Embedding Provider */}
      <section className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-emerald-100 dark:bg-emerald-900/30 rounded-lg">
            <Brain className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            Embedding 提供商
          </h2>
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
            <h3 className="font-semibold text-slate-900 dark:text-white mb-1">
              OpenAI
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              使用 OpenAI API 进行 embedding
            </p>
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
            <h3 className="font-semibold text-slate-900 dark:text-white mb-1">
              本地模型
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              使用本地部署的 embedding 模型
            </p>
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
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            主题设置
          </h2>
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
