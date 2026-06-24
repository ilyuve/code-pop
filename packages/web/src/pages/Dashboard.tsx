import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FolderGit2,
  Files,
  Hash,
  Search,
  TrendingUp,
  Clock,
  Sparkles,
  Zap,
  ArrowRight,
} from 'lucide-react';
import { useRepos } from '../hooks/useRepos';
import { useSearch } from '../hooks/useSearch';
import { useWebSocket } from '../hooks/useWebSocket';
import { useStore } from '../store';

export const Dashboard = () => {
  const { repos, isLoading: reposLoading } = useRepos();
  const { recentSearches } = useSearch();
  const { wsUrl, setWsStatus, addRealTimeUpdate, updateRepo } = useStore();
  const [animated, setAnimated] = useState(false);

  // WebSocket connection for real-time updates
  const { status, lastMessage, send } = useWebSocket(wsUrl, {
    onMessage: (data: unknown) => {
      const msg = data as { type?: string; repoId?: string; [key: string]: unknown };
      if (msg.type === 'repo_update' && msg.repoId) {
        addRealTimeUpdate(`repo_${msg.repoId}`, msg);
        // Update repo in store if we have the data
        if (msg.repoId && msg.data) {
          updateRepo(msg.repoId as string, msg.data as Partial<import('../types').Repo>);
        }
      }
    },
    onConnect: () => setWsStatus('connected'),
    onDisconnect: () => setWsStatus('disconnected'),
    reconnectOnMount: true,
  });

  // Sync WebSocket status to store
  useEffect(() => {
    setWsStatus(status);
  }, [status, setWsStatus]);

  // Request initial data on connect
  useEffect(() => {
    if (status === 'connected') {
      send({ type: 'subscribe', channels: ['repos', 'indexing'] });
    }
  }, [status, send]);

  useEffect(() => {
    setAnimated(true);
  }, []);

  const totalFiles = repos.reduce((acc, r) => acc + (r.fileCount || 0), 0);
  const totalSymbols = repos.reduce((acc, r) => acc + (r.symbolCount || 0), 0);
  const indexedRepos = repos.filter(r => r.status === 'indexed').length;

  const stats = [
    {
      label: '代码仓库',
      value: repos.length,
      icon: FolderGit2,
      color: '#ff3d8a',
      bgColor: '#ff3d8a20',
    },
    {
      label: '已索引文件',
      value: totalFiles,
      icon: Files,
      color: '#2ad4ff',
      bgColor: '#2ad4ff20',
    },
    {
      label: '代码符号',
      value: totalSymbols,
      icon: Hash,
      color: '#fff34d',
      bgColor: '#fff34d20',
    },
    {
      label: '索引完成',
      value: indexedRepos,
      icon: TrendingUp,
      color: '#6effb0',
      bgColor: '#6effb020',
    },
  ];

  return (
    <div className="p-8 space-y-8">
      {/* Hero Section */}
      <section
        className="relative overflow-hidden rounded-2xl p-8 animate-fadeIn"
        style={{
          background: 'linear-gradient(135deg, #ff3d8a 0%, #b88dff 100%)',
          border: '3px solid #2D2D2D',
          boxShadow: '8px 8px 0 #2D2D2D',
        }}
      >
        {/* Dot Pattern */}
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage: `
              radial-gradient(circle, rgba(255,255,255,0.3) 0 2px, transparent 2px),
              radial-gradient(circle, rgba(255,255,255,0.15) 0 1px, transparent 1px)
            `,
            backgroundSize: '16px 16px, 8px 8px',
            backgroundPosition: '0 0, 4px 4px',
          }}
        />

        <div className="relative z-10">
          <div className="flex items-center gap-3 mb-4">
            <div
              className="w-14 h-14 rounded-xl flex items-center justify-center"
              style={{
                background: '#fff34d',
                border: '2px solid #2D2D2D',
                boxShadow: '4px 4px 0 #2D2D2D',
              }}
            >
              <Sparkles className="w-8 h-8 text-[#2D2D2D]" />
            </div>
            <div>
              <h1 className="text-3xl font-black text-white tracking-tight">
                代码波普
              </h1>
              <p className="text-white/80 font-medium">
                让代码真正活着，让 AI 真正理解
              </p>
            </div>
          </div>

          <p className="text-white/90 text-lg mb-6 max-w-2xl">
            面向 AI Agent 的代码专用检索基础设施。通过混合索引、智能检索与上下文压缩，
            为 Claude Code、Cursor 等编码 Agent 提供精准的代码上下文。
          </p>

          <div className="flex gap-4">
            <Link
              to="/repos"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-bold"
              style={{
                background: '#fff34d',
                color: '#2D2D2D',
                border: '2px solid #2D2D2D',
                boxShadow: '4px 4px 0 #2D2D2D',
              }}
            >
              <Zap className="w-5 h-5" />
              添加仓库
            </Link>
            <Link
              to="/search"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-bold"
              style={{
                background: 'rgba(255,255,255,0.2)',
                color: 'white',
                border: '2px solid white',
              }}
            >
              <Search className="w-5 h-5" />
              开始搜索
            </Link>
          </div>
        </div>
      </section>

      {/* Stats Grid */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat, index) => (
          <div
            key={stat.label}
            className="relative bg-white rounded-2xl p-6 animate-fadeIn"
            style={{
              border: '2px solid #2D2D2D',
              boxShadow: '6px 6px 0 #2D2D2D',
              animationDelay: `${index * 100}ms`,
            }}
          >
            <div
              className="absolute top-0 left-0 w-full h-1 rounded-t-xl"
              style={{ background: stat.color }}
            />
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm text-[#666] font-medium mb-1">{stat.label}</p>
                <p className="text-4xl font-black text-[#2D2D2D]">
                  {reposLoading ? (
                    <span className="skeleton h-12 w-24 inline-block" />
                  ) : (
                    stat.value.toLocaleString()
                  )}
                </p>
              </div>
              <div
                className="w-14 h-14 rounded-xl flex items-center justify-center"
                style={{
                  background: stat.bgColor,
                  border: `2px solid ${stat.color}`,
                }}
              >
                <stat.icon className="w-7 h-7" style={{ color: stat.color }} />
              </div>
            </div>
          </div>
        ))}
      </section>

      {/* Two Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Recent Repos */}
        <section className="bg-white rounded-2xl p-6 animate-fadeIn" style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D' }}>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-black flex items-center gap-2">
              <FolderGit2 className="w-6 h-6" style={{ color: '#2ad4ff' }} />
              最近仓库
            </h2>
            <Link
              to="/repos"
              className="text-sm font-semibold flex items-center gap-1 hover:text-[#ff3d8a] transition-colors"
            >
              查看全部
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {reposLoading ? (
            <div className="space-y-4">
              {[1, 2, 3].map(i => (
                <div key={i} className="skeleton h-20 rounded-xl" />
              ))}
            </div>
          ) : repos.length === 0 ? (
            <div className="text-center py-12">
              <div
                className="w-20 h-20 rounded-2xl mx-auto mb-4 flex items-center justify-center"
                style={{ background: '#F5F5F0', border: '2px dashed #2D2D2D' }}
              >
                <FolderGit2 className="w-10 h-10 text-[#666]" />
              </div>
              <p className="text-[#666] mb-4">还没有添加任何仓库</p>
              <Link
                to="/repos"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold"
                style={{ background: '#ff3d8a', color: 'white', border: '2px solid #2D2D2D' }}
              >
                添加第一个仓库
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              {repos.slice(0, 5).map((repo, index) => (
                <Link
                  key={repo.id}
                  to={`/repos/${repo.id}`}
                  className="block p-4 rounded-xl border-2 border-transparent hover:border-[#ff3d8a] transition-all"
                  style={{ background: '#F5F5F0' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div
                        className="w-10 h-10 rounded-lg flex items-center justify-center"
                        style={{
                          background: '#2D2D2D',
                          color: '#fff34d',
                          fontWeight: 'bold',
                          fontSize: '14px',
                        }}
                      >
                        {repo.name.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <p className="font-bold">{repo.name}</p>
                        <p className="text-sm text-[#666]">{repo.path}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className="px-2 py-1 rounded-lg text-xs font-bold"
                        style={{
                          background: repo.status === 'indexed' ? '#6effb020' : '#fff34d20',
                          color: repo.status === 'indexed' ? '#2D2D2D' : '#2D2D2D',
                        }}
                      >
                        {repo.status === 'indexed' ? '已索引' : '索引中'}
                      </span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* Recent Searches */}
        <section className="bg-white rounded-2xl p-6 animate-fadeIn" style={{ border: '2px solid #2D2D2D', boxShadow: '6px 6px 0 #2D2D2D', animationDelay: '200ms' }}>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-black flex items-center gap-2">
              <Clock className="w-6 h-6" style={{ color: '#b88dff' }} />
              最近搜索
            </h2>
            <Link
              to="/search"
              className="text-sm font-semibold flex items-center gap-1 hover:text-[#ff3d8a] transition-colors"
            >
              查看全部
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {recentSearches.length === 0 ? (
            <div className="text-center py-12">
              <div
                className="w-20 h-20 rounded-2xl mx-auto mb-4 flex items-center justify-center"
                style={{ background: '#F5F5F0', border: '2px dashed #2D2D2D' }}
              >
                <Search className="w-10 h-10 text-[#666]" />
              </div>
              <p className="text-[#666] mb-4">还没有搜索记录</p>
              <Link
                to="/search"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold"
                style={{ background: '#2ad4ff', color: '#2D2D2D', border: '2px solid #2D2D2D' }}
              >
                开始搜索
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {recentSearches.map((search, index) => (
                <Link
                  key={index}
                  to={`/search?q=${encodeURIComponent(search)}`}
                  className="flex items-center gap-3 p-3 rounded-xl hover:bg-[#F5F5F0] transition-colors"
                >
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{ background: '#fff34d20' }}
                  >
                    <Search className="w-5 h-5" style={{ color: '#fff34d' }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{search}</p>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Ticker */}
      <div
        className="overflow-hidden py-3"
        style={{ background: '#fff34d', borderTop: '2px solid #2D2D2D', borderBottom: '2px solid #2D2D2D' }}
      >
        <div className="flex gap-8 animate-[ticker_30s_linear_infinite] whitespace-nowrap">
          {[...Array(2)].map((_, i) => (
            <span key={i} className="flex items-center gap-8 text-sm font-bold text-[#2D2D2D]">
              <span>代码波普</span>
              <span className="w-2 h-2 rounded-full bg-[#ff3d8a]" />
              <span>让代码真正活着</span>
              <span className="w-2 h-2 rounded-full bg-[#2ad4ff]" />
              <span>AI 代码检索基础设施</span>
              <span className="w-2 h-2 rounded-full bg-[#6effb0]" />
              <span>POP ART STYLE</span>
              <span className="w-2 h-2 rounded-full bg-[#b88dff]" />
              <span>VECTOR SEARCH</span>
              <span className="w-2 h-2 rounded-full bg-[#ff8a3d]" />
              <span>SEMANTIC CODE SEARCH</span>
              <span className="w-2 h-2 rounded-full bg-[#ff3d8a]" />
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};
