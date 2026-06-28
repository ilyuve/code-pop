import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderGit2,
  Search,
  BarChart3,
  Settings,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from 'lucide-react';
import { useStore } from '../../store';
import { clsx } from 'clsx';

const navItems = [
  { path: '/', icon: LayoutDashboard, label: '仪表盘', color: '#ff3d8a' },
  { path: '/repos', icon: FolderGit2, label: '仓库', color: '#2ad4ff' },
  { path: '/search', icon: Search, label: '搜索', color: '#fff34d' },
  { path: '/benchmark', icon: BarChart3, label: '评测', color: '#b88dff' },
  { path: '/settings', icon: Settings, label: '设置', color: '#6effb0' },
];

export const Sidebar = () => {
  const { sidebarOpen, toggleSidebar } = useStore();
  const location = useLocation();

  return (
    <aside
      className={clsx(
        'fixed left-0 top-0 h-full z-40 transition-all duration-300',
        'bg-white border-r-2 border-[#2D2D2D]',
        sidebarOpen ? 'w-64' : 'w-16'
      )}
      style={{ boxShadow: '4px 0 0 #fff34d' }}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b-2 border-[#2D2D2D]">
        <div 
          className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ background: 'linear-gradient(135deg, #ff3d8a 0%, #b88dff 100%)', border: '2px solid #2D2D2D', boxShadow: '3px 3px 0 #2D2D2D' }}
        >
          <Sparkles className="w-6 h-6 text-white" />
        </div>
        {sidebarOpen && (
          <div className="flex flex-col">
            <span className="font-black text-lg tracking-tight">CodePop</span>
            <span className="text-xs text-[#666] font-medium">代码波普</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="p-3 space-y-2">
        {navItems.map(({ path, icon: Icon, label, color }) => {
          const isActive = location.pathname === path;
          return (
            <NavLink
              key={path}
              to={path}
              className={clsx(
                'flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200',
                isActive
                  ? 'bg-[#2D2D2D] text-white'
                  : 'hover:bg-[#F5F5F0] hover:text-[#ff3d8a]'
              )}
              style={!isActive ? { borderLeft: `3px solid ${color}` } : undefined}
            >
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 transition-all"
                style={{
                  background: isActive ? 'transparent' : `${color}20`,
                  border: isActive ? '2px solid #2D2D2D' : `2px solid ${color}`,
                }}
              >
                <Icon 
                  className="w-5 h-5" 
                  style={{ color: isActive ? 'white' : color }}
                />
              </div>
              {sidebarOpen && (
                <span className="font-semibold whitespace-nowrap">{label}</span>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Toggle Button */}
      <button
        onClick={toggleSidebar}
        className={clsx(
          'absolute bottom-6 w-8 h-8 rounded-full flex items-center justify-center',
          'bg-[#2D2D2D] text-white transition-all',
          'hover:bg-[#ff3d8a] hover:scale-110',
          sidebarOpen ? '-right-4' : 'left-1/2 -translate-x-1/2'
        )}
        style={{ boxShadow: '3px 3px 0 rgba(0,0,0,0.2)' }}
      >
        {sidebarOpen ? (
          <ChevronLeft className="w-4 h-4" />
        ) : (
          <ChevronRight className="w-4 h-4" />
        )}
      </button>
    </aside>
  );
};
