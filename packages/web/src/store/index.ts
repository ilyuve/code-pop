import { create } from 'zustand';
import { persist } from 'zustand/middleware/persist';
import type { Repo, SearchResult, Settings } from '../types';
import type { WebSocketStatus } from '../hooks/useWebSocket';

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  stage: string | null;
}

interface AppStore {
  // Repository State
  repos: Repo[];
  setRepos: (repos: Repo[]) => void;
  addRepo: (repo: Repo) => void;
  updateRepo: (id: string, updates: Partial<Repo>) => void;
  removeRepo: (id: string) => void;

  // Search State
  searchResults: SearchResult[];
  setSearchResults: (results: SearchResult[]) => void;
  recentSearches: string[];
  addRecentSearch: (query: string) => void;

  // Settings State
  settings: Settings;
  updateSettings: (settings: Partial<Settings>) => void;

  // UI State
  sidebarOpen: boolean;
  toggleSidebar: () => void;

  // WebSocket State
  wsStatus: WebSocketStatus;
  setWsStatus: (status: WebSocketStatus) => void;
  wsUrl: string;
  setWsUrl: (url: string) => void;
  realTimeUpdates: Record<string, unknown>;
  addRealTimeUpdate: (key: string, data: unknown) => void;
  clearRealTimeUpdates: () => void;

  // Indexing Logs State
  indexingLogs: Record<string, LogEntry[]>;
  addIndexingLog: (repoId: string, log: LogEntry) => void;
  setIndexingLogs: (repoId: string, logs: LogEntry[]) => void;
  clearIndexingLogs: (repoId: string) => void;
}

export const useStore = create<AppStore>()(
  persist(
    (set) => ({
      // Repository State
      repos: [],
      setRepos: (repos) => set({ repos }),
      addRepo: (repo) => set((state) => ({ repos: [...state.repos, repo] })),
      updateRepo: (id, updates) =>
        set((state) => ({
          repos: state.repos.map((repo) =>
            repo.id === id ? { ...repo, ...updates } : repo
          ),
        })),
      removeRepo: (id) =>
        set((state) => ({
          repos: state.repos.filter((repo) => repo.id !== id),
        })),

      // Search State
      searchResults: [],
      setSearchResults: (results) => set({ searchResults: results }),
      recentSearches: [],
      addRecentSearch: (query) =>
        set((state) => ({
          recentSearches: [query, ...state.recentSearches.filter((q) => q !== query)].slice(0, 10),
        })),

      // Settings State
      settings: {
        apiEndpoint: 'http://localhost:8080/api',
        embeddingProvider: 'openai',
        theme: 'dark',
      },
      updateSettings: (newSettings) =>
        set((state) => ({
          settings: { ...state.settings, ...newSettings },
        })),

      // UI State
      sidebarOpen: true,
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),

      // WebSocket State
      wsStatus: 'disconnected',
      setWsStatus: (status) => set({ wsStatus: status }),
      wsUrl: 'ws://localhost:8080/ws',
      setWsUrl: (url) => set({ wsUrl: url }),
      realTimeUpdates: {},
      addRealTimeUpdate: (key, data) =>
        set((state) => ({
          realTimeUpdates: { ...state.realTimeUpdates, [key]: data },
        })),
      clearRealTimeUpdates: () => set({ realTimeUpdates: {} }),

      // Indexing Logs State
      indexingLogs: {},
      addIndexingLog: (repoId, log) =>
        set((state) => ({
          indexingLogs: {
            ...state.indexingLogs,
            [repoId]: [...(state.indexingLogs[repoId] || []), log],
          },
        })),
      setIndexingLogs: (repoId, logs) =>
        set((state) => ({
          indexingLogs: {
            ...state.indexingLogs,
            [repoId]: logs,
          },
        })),
      clearIndexingLogs: (repoId) =>
        set((state) => {
          const newLogs = { ...state.indexingLogs };
          delete newLogs[repoId];
          return { indexingLogs: newLogs };
        }),
    }),
    {
      name: 'codepop-storage',
      partialize: (state) => ({
        settings: state.settings,
        recentSearches: state.recentSearches,
        sidebarOpen: state.sidebarOpen,
        wsUrl: state.wsUrl,
      }),
    }
  )
);
