import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Layout/Sidebar';
import { Header } from './components/Layout/Header';
import { Footer } from './components/Layout/Footer';
import { Dashboard } from './pages/Dashboard';
import { Repos } from './pages/Repos';
import { RepoDetail } from './pages/RepoDetail';
import { Search } from './pages/Search';
import { Benchmark } from './pages/Benchmark';
import { Settings } from './pages/Settings';
import { Monitor } from './pages/Monitor';
import { Stats } from './pages/Stats';
import { useStore } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import { useQueryClient } from '@tanstack/react-query';
import { clsx } from 'clsx';

/**
 * Global WebSocket bridge mounted at the app root.
 *
 * Keeps a single /ws connection alive across all pages so the header
 * connection indicator, the repository card progress bars and the detail
 * page progress all share the same real-time source of truth. REST polling
 * in useIndexing stays as a fallback / detail source.
 */
function GlobalSocketBridge() {
  const queryClient = useQueryClient();
  const { setWsStatus, addRealTimeUpdate, updateRepo, setIndexingProgress } = useStore();
  const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

  useWebSocket(wsUrl, {
    onConnect: () => setWsStatus('connected'),
    onDisconnect: () => setWsStatus('disconnected'),
    onMessage: (data: unknown) => {
      const msg = data as {
        type?: string;
        repoId?: string;
        status?: string;
        progress?: number;
        stage?: string;
        stage_progress?: unknown;
        error?: unknown;
        log?: unknown;
      };
      if (msg?.type !== 'repo_update' || !msg?.repoId) return;

      addRealTimeUpdate(`repo_${msg.repoId}`, msg);
      setIndexingProgress(msg.repoId, {
        progress: msg.progress ?? 0,
        stage: msg.stage ?? '',
        stageProgress: (msg.stage_progress as {
          stage: string;
          current: number;
          total: number;
          percentage: number;
        } | null) ?? null,
      });

      // Backend pushes status 'synced' after a successful branch sync; the
      // frontend Repo model only knows indexed/completed, so normalize it.
      let nextStatus = msg.status;
      if (nextStatus === 'synced') {
        nextStatus = 'indexed';
      }
      if (nextStatus) {
        updateRepo(msg.repoId, { status: nextStatus } as never);
        queryClient.setQueryData(['repos'], (old: unknown) => {
          if (!Array.isArray(old)) return old;
          return old.map((r) =>
            (r as { id: string }).id === msg.repoId
              ? { ...(r as object), status: nextStatus }
              : r
          );
        });
      }

      if (msg.progress !== undefined) {
        // Keep the detail-page progress query in sync with the push so both
        // the card and the detail view show identical numbers. WS messages
        // carry a single stage's stage_progress; merge it into the dict keyed
        // by stage name (matching GET /api/repos/{id}/progress shape) so
        // useIndexing can resolve stage_progress[current_stage].
        queryClient.setQueryData(['indexingProgress', msg.repoId], (old: unknown) => {
          const base = old && typeof old === 'object' ? (old as Record<string, unknown>) : {};
          const rawSp = base.stage_progress;
          const sp =
            rawSp && typeof rawSp === 'object' && !Array.isArray(rawSp)
              ? { ...(rawSp as Record<string, unknown>) }
              : {};
          const mergedSp =
            msg.stage && msg.stage_progress
              ? { ...sp, [msg.stage]: msg.stage_progress }
              : sp;
          return {
            ...base,
            overall_progress: msg.progress,
            current_stage: msg.stage ?? base.current_stage ?? null,
            stage_progress: mergedSp,
          };
        });
      }
    },
    reconnectOnMount: true,
  });

  return null;
}

function App() {
  const { sidebarOpen, settings } = useStore();

  return (
    <Router>
      <GlobalSocketBridge />
      <div className={clsx('min-h-screen flex flex-col bg-[var(--bg)] dark:bg-[var(--bg)] transition-colors')}>
        <Sidebar />
        <div
          className={clsx(
            'flex-1 flex flex-col transition-all duration-300',
            sidebarOpen ? 'ml-64' : 'ml-16'
          )}
        >
          <Header />
          <main className="flex-1 p-6">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/repos" element={<Repos />} />
              <Route path="/repos/:id" element={<RepoDetail />} />
              <Route path="/search" element={<Search />} />
              <Route path="/benchmark" element={<Benchmark />} />
              <Route path="/stats" element={<Stats />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/monitor" element={<Monitor />} />
            </Routes>
          </main>
          <Footer />
        </div>
      </div>
    </Router>
  );
}

export default App;
