// Repository types
export interface Repo {
  id: string;
  name: string;
  path: string;
  gitUrl?: string;
  status: 'indexing' | 'indexed' | 'completed' | 'error';
  errorMessage?: string;
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
  language: string;
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

export interface SearchHistoryDailyStats {
  date: string;
  totalQueries: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalResultsCount: number;
}

export interface SearchHistoryRecentItem {
  id: string;
  query: string;
  repoId?: string;
  repoName?: string;
  mode: string;
  resultsCount: number;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  createdAt: string;
}

// Form types
export interface AddRepoForm {
  name?: string;
  path?: string;
  gitUrl?: string;
}

// CodeContext types
export interface SymbolEntry {
  id: string;
  name: string;
  type: string;
  file_path: string;
  line: number;
  relevance_score: number;
}

export interface CallChain {
  root: SymbolEntry;
  upstream: SymbolEntry[];
  downstream: SymbolEntry[];
  depth: number;
}

export interface FileSummary {
  path: string;
  role: string;
  relevance_score: number;
  key_symbols: string[];
}

export interface CodeContext {
  query: string;
  query_intent: string;
  matched_concepts: string[];
  entry_points: SymbolEntry[];
  call_chain: CallChain | null;
  related_files: FileSummary[];
  code_snippets: SearchResult[];
  total_files: number;
  total_symbols: number;
  search_latency_ms: number;
  degraded: boolean;
  degradation_reason?: string;
  unavailable_sources: string[];
}

export interface CodeContextResponse {
  context: CodeContext;
  success: boolean;
  error?: string;
}
