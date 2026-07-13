import { ServiceStatus } from '../components/ServiceStatus';
import { Activity } from 'lucide-react';

export const Monitor = () => {
  return (
    <div className="space-y-6 animate-fadeIn">
      <div className="flex items-center gap-3">
        <Activity className="w-6 h-6 text-indigo-500" />
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">服务监控</h1>
      </div>
      
      <ServiceStatus />
      
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">服务说明</h3>
        <div className="space-y-4">
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
              <span className="text-indigo-600 dark:text-indigo-400 font-medium">1</span>
            </div>
            <div>
              <h4 className="font-medium text-slate-900 dark:text-white">后端 API</h4>
              <p className="text-sm text-slate-500 dark:text-slate-400">检查后端服务是否正常运行，通过访问健康检查端点验证。</p>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
              <span className="text-indigo-600 dark:text-indigo-400 font-medium">2</span>
            </div>
            <div>
              <h4 className="font-medium text-slate-900 dark:text-white">前端</h4>
              <p className="text-sm text-slate-500 dark:text-slate-400">当前前端页面是否正常加载，通常始终为正常状态。</p>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
              <span className="text-indigo-600 dark:text-indigo-400 font-medium">3</span>
            </div>
            <div>
              <h4 className="font-medium text-slate-900 dark:text-white">数据库</h4>
              <p className="text-sm text-slate-500 dark:text-slate-400">检查后端与数据库的连接是否正常，通过访问仓库列表 API 验证。</p>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
              <span className="text-indigo-600 dark:text-indigo-400 font-medium">4</span>
            </div>
            <div>
              <h4 className="font-medium text-slate-900 dark:text-white">WebSocket</h4>
              <p className="text-sm text-slate-500 dark:text-slate-400">检查实时通信通道是否可用，用于推送索引进度等实时更新。</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};