import axios from 'axios';
import type { Repo, SearchResult, Stats, AddRepoForm, BenchmarkRun, BenchmarkSummary, SearchHistoryStats, SearchHistoryDailyStats, SearchHistoryRecentItem, CodeContext } from '../types';

const apiClient = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// Backend status -> frontend status mapping
const mapStatus = (status: string): Repo['status'] => {
  if (status === 'indexed') return 'completed';
  if (status === 'indexing') return 'indexing';
  if (status === 'error') return 'error';
  return 'indexing';
};

const mapRepo = (data: any): Repo => ({
  id: data.id,
  name: data.name,
  path: data.local_path || data.path || '',
  gitUrl: data.git_url || data.gitUrl,
  status: mapStatus(data.status),
  errorMessage: data.error_message || data.errorMessage,
  totalFiles: data.total_files || 0,
  indexedFiles: data.indexed_files || 0,
  fileCount: data.total_files || 0,
  symbolCount: 0,
  createdAt: data.created_at || data.createdAt,
  lastIndexedAt: data.last_indexed_at || data.lastIndexedAt,
});

const mapSearchResult = (data: any): SearchResult => ({
  repoId: data.repo_id,
  repoName: data.repo_name || '',
  filePath: data.file_path,
  lineNumber: data.line,
  code: data.content,
  language: data.language || '',
  score: data.score,
  scoreBreakdown: data.score_breakdown || {},
});

// Repository APIs
export const fetchRepos = async (): Promise<Repo[]> => {
  const response = await apiClient.get('/repos');
  return response.data.map(mapRepo);
};

export const fetchRepo = async (id: string): Promise<Repo> => {
  const response = await apiClient.get(`/repos/${id}`);
  return mapRepo(response.data);
};

export const addRepo = async (data: AddRepoForm): Promise<Repo> => {
  const payload: any = {
    name: data.name || data.gitUrl?.split('/').pop()?.replace(/\.git$/, '') || data.path?.split('/').pop() || 'repo',
  };
  if (data.gitUrl) {
    payload.git_url = data.gitUrl;
  }
  if (data.path) {
    payload.path = data.path;
  }
  const response = await apiClient.post('/repos', payload);
  return mapRepo(response.data);
};

export const updateRepo = async (id: string, data: Partial<AddRepoForm>): Promise<Repo> => {
  const response = await apiClient.patch(`/repos/${id}`, data);
  return mapRepo(response.data);
};

export const deleteRepo = async (id: string): Promise<void> => {
  await apiClient.delete(`/repos/${id}`);
};

export const reindexRepo = async (id: string): Promise<void> => {
  await apiClient.post(`/repos/${id}/index`);
};

export const fetchRepoFiles = async (id: string): Promise<any[]> => {
  const response = await apiClient.get(`/repos/${id}/files`);
  return response.data;
};

export const fetchRepoSymbols = async (id: string, filePath?: string): Promise<any[]> => {
  const url = filePath ? `/repos/${id}/symbols?file_path=${encodeURIComponent(filePath)}` : `/repos/${id}/symbols`;
  const response = await apiClient.get(url);
  return response.data;
};

export const fetchIndexingLogs = async (id: string): Promise<any[]> => {
  const response = await apiClient.get(`/repos/${id}/logs`);
  return response.data.logs;
};

export const fetchIndexingProgress = async (id: string): Promise<any> => {
  const response = await apiClient.get(`/repos/${id}/progress`);
  return response.data;
};

export const cancelIndexing = async (id: string): Promise<void> => {
  await apiClient.post(`/repos/${id}/cancel`);
};

// Search APIs
export const searchCode = async (query: string, repoId?: string, limit: number = 20): Promise<SearchResult[]> => {
  const response = await apiClient.post('/search', { query, repo_id: repoId, limit });
  return response.data.map(mapSearchResult);
};

export const searchSymbol = async (query: string, repoId?: string): Promise<any[]> => {
  const response = await apiClient.post('/search/symbol', { query, repo_id: repoId });
  return response.data;
};

export const searchContext = async (query: string, repoId?: string, limit: number = 20): Promise<CodeContext> => {
  const response = await apiClient.post('/search/context', { query, repo_id: repoId, limit });
  const context = response.data.context;
  
  context.code_snippets = context.code_snippets.map((snippet: any) => mapSearchResult(snippet));
  
  return context;
};

export const fetchSearchHistory = async (limit: number = 10): Promise<any[]> => {
  const response = await apiClient.get(`/search/history?limit=${limit}`);
  return response.data;
};

export const fetchSearchHistoryStats = async (repoId?: string): Promise<SearchHistoryStats> => {
  const params = new URLSearchParams();
  if (repoId) params.append('repo_id', repoId);
  const response = await apiClient.get(`/search/history/stats?${params.toString()}`);
  const data = response.data;
  return {
    totalQueries: data.total_queries || 0,
    avgLatencyMs: data.avg_latency_ms || 0,
    totalInputTokens: data.total_input_tokens || 0,
    totalOutputTokens: data.total_output_tokens || 0,
    estimatedTokensSaved: data.estimated_tokens_saved || 0,
  };
};

export const fetchSearchHistoryDaily = async (
  repoId?: string,
  days: number = 7
): Promise<SearchHistoryDailyStats[]> => {
  const params = new URLSearchParams();
  if (repoId) params.append('repo_id', repoId);
  params.append('days', String(days));
  const response = await apiClient.get(`/search/history/daily?${params.toString()}`);
  return response.data.map((r: any) => ({
    date: r.date,
    totalQueries: r.total_queries || 0,
    totalInputTokens: r.total_input_tokens || 0,
    totalOutputTokens: r.total_output_tokens || 0,
    totalResultsCount: r.total_results_count || 0,
  }));
};

export const fetchSearchHistoryRecent = async (
  repoId?: string,
  limit: number = 10
): Promise<SearchHistoryRecentItem[]> => {
  const params = new URLSearchParams();
  if (repoId) params.append('repo_id', repoId);
  params.append('limit', String(limit));
  const response = await apiClient.get(`/search/history/recent?${params.toString()}`);
  return response.data.map((r: any) => ({
    id: r.id,
    query: r.query,
    repoId: r.repo_id,
    repoName: r.repo_name,
    mode: r.mode,
    resultsCount: r.results_count || 0,
    latencyMs: r.latency_ms || 0,
    inputTokens: r.input_tokens || 0,
    outputTokens: r.output_tokens || 0,
    createdAt: r.created_at,
  }));
};

// Benchmark APIs
export const runBenchmark = async (payload: {
  query: string;
  repo_id?: string;
  mode: 'with_codepop' | 'without_codepop';
  expected_files?: string[];
  expected_lines?: number[];
}): Promise<BenchmarkRun> => {
  const response = await apiClient.post('/search/benchmark', payload);
  return {
    id: response.data.id,
    query: response.data.query,
    repoId: response.data.repo_id,
    mode: response.data.mode,
    latencyMs: response.data.latency_ms,
    resultsCount: response.data.results_count,
    relevantResultsCount: response.data.relevant_results_count,
    tokenConsumed: response.data.token_consumed,
    accuracyScore: response.data.accuracy_score,
    createdAt: response.data.created_at,
  };
};

export const fetchBenchmarks = async (params?: { repoId?: string; mode?: string }): Promise<BenchmarkRun[]> => {
  const query = new URLSearchParams();
  if (params?.repoId) query.append('repo_id', params.repoId);
  if (params?.mode) query.append('mode', params.mode);
  const response = await apiClient.get(`/search/benchmark?${query.toString()}`);
  return response.data.map((r: any) => ({
    id: r.id,
    query: r.query,
    repoId: r.repo_id,
    mode: r.mode,
    latencyMs: r.latency_ms,
    resultsCount: r.results_count,
    relevantResultsCount: r.relevant_results_count,
    tokenConsumed: r.token_consumed,
    accuracyScore: r.accuracy_score,
    createdAt: r.created_at,
  }));
};

export const fetchBenchmarkSummary = async (): Promise<BenchmarkSummary> => {
  const response = await apiClient.get('/search/benchmark/summary');
  return {
    totalRuns: response.data.total_runs,
    avgLatencyMs: response.data.avg_latency_ms,
    avgTokenConsumed: response.data.avg_token_consumed,
    avgAccuracyScore: response.data.avg_accuracy_score,
    latencyTrend: response.data.latency_trend,
    savingsVsBaseline: response.data.savings_vs_baseline,
  };
};

// Health APIs
export const fetchHealth = async (): Promise<any> => {
  const response = await apiClient.get('/health');
  return response.data;
};

export default apiClient;
