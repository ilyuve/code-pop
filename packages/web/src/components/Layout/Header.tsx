import { useLocation, Link } from 'react-router-dom';
import { Menu, X, Wifi, WifiOff, Loader2 } from 'lucide-react';
import { useStore } from '../../store';
import { clsx } from 'clsx';

const routeTitles: Record<string, string> = {
  '/': '仪表盘',
  '/repos': '仓库管理',
  '/search': '代码搜索',
  '/settings': '系统设置',
};

export const Header = () => {
  const location = useLocation();
  const { sidebarOpen, toggleSidebar, wsStatus } = useStore();
  const title = routeTitles[location.pathname] || 'CodePop';

  const statusConfig: Record<string, {
    icon: typeof Wifi;
    color: string;
    bgColor: string;
    label: string;
    dotColor: string;
    animate?: boolean;
  }> = {
    connected: {
      icon: Wifi,
      color: 'text-green-500',
      bgColor: 'bg-green-500/10',
      label: '已连接',
      dotColor: 'bg-green-500',
    },
    connecting: {
      icon: Loader2,
      color: 'text-yellow-500',
      bgColor: 'bg-yellow-500/10',
      label: '连接中',
      dotColor: 'bg-yellow-500',
      animate: true,
    },
    disconnected: {
      icon: WifiOff,
      color: 'text-red-500',
      bgColor: 'bg-red-500/10',
      label: '未连接',
      dotColor: 'bg-red-500',
    },
  };

  const config = statusConfig[wsStatus];

  return (
    <header className="sticky top-0 z-30 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
      <div className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-4">
          <button
            onClick={toggleSidebar}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 lg:hidden"
          >
            <Menu className="w-5 h-5" />
          </button>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
            {title}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          {/* WebSocket Status Indicator */}
          <div
            className={clsx(
              'flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-all',
              config.bgColor,
              config.color
            )}
          >
            <div className="relative flex items-center justify-center">
              <config.icon
                className={clsx('w-4 h-4', config.animate && 'animate-spin')}
              />
              {wsStatus === 'connected' && (
                <span
                  className={clsx(
                    'absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full',
                    config.dotColor,
                    'animate-pulse'
                  )}
                />
              )}
            </div>
            <span className="hidden sm:inline">{config.label}</span>
          </div>

          <Link
            to="/search"
            className="px-4 py-2 text-sm bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg transition-colors"
          >
            快速搜索
          </Link>
        </div>
      </div>
    </header>
  );
};
