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
  const title = routeTitles[location.pathname] || 'Code:Pop';

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
      color: 'text-[#2D2D2D]',
      bgColor: 'bg-[#6effb0] border-2 border-[#2D2D2D]',
      label: '已连接',
      dotColor: 'bg-[#2D2D2D]',
    },
    connecting: {
      icon: Loader2,
      color: 'text-[#2D2D2D]',
      bgColor: 'bg-[#fff34d] border-2 border-[#2D2D2D]',
      label: '连接中',
      dotColor: 'bg-[#2D2D2D]',
      animate: true,
    },
    disconnected: {
      icon: WifiOff,
      color: 'text-white',
      bgColor: 'bg-[#ff3d8a] border-2 border-[#2D2D2D]',
      label: '未连接',
      dotColor: 'bg-white',
    },
  };

  const config = statusConfig[wsStatus];

  return (
    <header className="sticky top-0 z-30 bg-white border-b-2 border-[#2D2D2D]">
      <div className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-4">
          <button
            onClick={toggleSidebar}
            className="p-2 rounded-lg hover:bg-[#F5F5F0] border-2 border-transparent hover:border-[#2D2D2D] lg:hidden"
          >
            <Menu className="w-5 h-5" />
          </button>
          <h1 className="text-xl font-black text-[#2D2D2D]">
            {title}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          {/* WebSocket Status Indicator */}
          <div
            className={clsx(
              'flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-bold transition-all',
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
            className="px-4 py-2 text-sm bg-[#3b82f6] hover:bg-[#2563eb] text-white border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] rounded-lg transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[5px_5px_0_#2D2D2D] font-bold"
          >
            快速搜索
          </Link>
        </div>
      </div>
    </header>
  );
};
