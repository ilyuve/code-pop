// Repository types
export interface Repo {
  id: string;
  name: string;
  path: string;
  gitUrl?: string;
  status: 'indexing' | 'indexed' | 'completed' | 'error';
  totalFiles: number;
  indexedFiles: number;
  fileCount?: number;
  symbolCount?: number;
  createdAt: string;
  lastIndexedAt: string;
}

// Search types
export interface ScoreBreakdown {
  vector?: number;
  symbol?: number;
  bm25?: number;
  graph?: number;
  final?: number;
  [key: string]: number | undefined;
}

export interface SearchResult {
  repoId: string;
  repoName: string;
  filePath: string;
  lineNumber: number;
  code: string;
  score: number;
  scoreBreakdown: ScoreBreakdown;
}

// Settings types
export interface Settings {
  apiEndpoint: string;
  embeddingProvider: 'openai' | 'local';
  theme: 'light' | 'dark';
}

// Stats types
export interface Stats {
  totalRepos: number;
  totalFiles: number;
  recentSearches: string[];
}

// API response types
export interface ApiResponse<T> {
  data: T;
  error?: string;
}

// Benchmark types
export interface BenchmarkRun {
  id: string;
  query: string;
  repoId?: string;
  mode: 'with_codepop' | 'without_codepop';
  latencyMs: number;
  resultsCount: number;
  relevantResultsCount: number;
  tokenConsumed: number;
  accuracyScore: number;
  createdAt: string;
}

export interface BenchmarkSummary {
  totalRuns: number;
  avgLatencyMs: number;
  avgTokenConsumed: number;
  avgAccuracyScore: number;
  latencyTrend: { timestamp: string; latencyMs: number }[];
  savingsVsBaseline: Record<string, number>;
}

export interface SearchHistoryStats {
  totalQueries: number;
  avgLatencyMs: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  estimatedTokensSaved: number;
}

// Form types
export interface AddRepoForm {
  name?: string;
  path?: string;
  gitUrl?: string;
}
